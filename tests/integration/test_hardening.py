import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pyotp

from app.config import get_settings
from app.services import backup
from tests.conftest import OWNER_PASSWORD, login

NEW_PASSWORD = "a-much-better-passphrase-9"


def test_security_headers_request_id_and_body_limit(client):
    r = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"
    for h in ("Content-Security-Policy", "Cross-Origin-Opener-Policy", "Permissions-Policy", "X-Frame-Options"):
        assert h in r.headers
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    # an id that could forge log lines is replaced, not echoed
    assert client.get("/healthz", headers={"X-Request-ID": "x y\tz"}).headers["X-Request-ID"] != "x y\tz"
    big = client.post("/api/v1/auth/login", content=b"{}", headers={"Content-Length": str(200 * 1024 * 1024)})
    assert big.status_code == 413


def test_metrics_include_health_and_can_require_a_token(client, monkeypatch):
    r = client.get("/metrics")
    assert r.status_code == 200 and "career_health_status" in r.text and "career_scheduler_up 0.0" in r.text
    monkeypatch.setattr(get_settings(), "metrics_token", "t" * 32)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32}).status_code == 200


def test_rate_limit_on_expensive_actions(client, owner):
    h = login(client, owner)
    codes = [client.post("/api/v1/matches/run", headers=h).status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429
    r = client.post("/api/v1/matches/run", headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_password_change_signs_out_other_devices(client, owner):
    laptop, phone = login(client, owner), login(client, owner)
    sessions = client.get("/api/v1/auth/sessions", headers=laptop).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1

    bad = {"current_password": "wrong-password", "new_password": NEW_PASSWORD}
    assert client.post("/api/v1/auth/password", json=bad, headers=laptop).status_code == 403
    weak = {"current_password": OWNER_PASSWORD, "new_password": "aaaaaaaaaaaaaaaa"}
    assert client.post("/api/v1/auth/password", json=weak, headers=laptop).status_code == 422
    ok = {"current_password": OWNER_PASSWORD, "new_password": NEW_PASSWORD}
    r = client.post("/api/v1/auth/password", json=ok, headers=laptop)
    assert r.status_code == 200 and r.json()["other_sessions_revoked"] == 1
    assert client.get("/api/v1/auth/me", headers=phone).status_code == 401  # signed out at once
    assert client.get("/api/v1/auth/me", headers=laptop).status_code == 200
    r = client.post("/api/v1/auth/login", json={"email": owner.email, "password": NEW_PASSWORD})
    assert r.status_code == 200


def test_revoke_sessions(client, owner):
    a, b = login(client, owner), login(client, owner)
    other = next(s for s in client.get("/api/v1/auth/sessions", headers=a).json() if not s["current"])
    assert client.post(f"/api/v1/auth/sessions/{other['id']}/revoke", headers=a).status_code == 204
    assert client.get("/api/v1/auth/me", headers=b).status_code == 401
    login(client, owner)
    assert client.post("/api/v1/auth/sessions/revoke-others", headers=a).json() == {"revoked": 1}


def test_totp_enable_and_disable(client, owner):
    h = login(client, owner)
    uri = client.post("/api/v1/auth/totp/setup", headers=h).json()["provisioning_uri"]
    totp = pyotp.parse_uri(uri)
    assert client.post("/api/v1/auth/totp/verify", json={"code": totp.now()}, headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).json()["totp_enabled"] is True
    wrong = {"password": "nope-nope-nope", "code": totp.now()}
    assert client.post("/api/v1/auth/totp/disable", json=wrong, headers=h).status_code == 403
    right = {"password": OWNER_PASSWORD, "code": totp.now()}
    assert client.post("/api/v1/auth/totp/disable", json=right, headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).json()["totp_enabled"] is False


def test_system_health(client, owner, viewer):
    assert client.get("/api/v1/system/health", headers=login(client, viewer)).status_code == 403
    h = client.get("/api/v1/system/health", headers=login(client, owner)).json()
    assert h["database"]["migration"]["current"] == h["database"]["migration"]["head"]
    codes = {p["code"] for p in h["problems"]}
    assert "scheduler_down" in codes and "migrations_pending" not in codes
    assert h["status"] in ("warn", "fail")


def _db_file(path, rows=3):
    with closing(sqlite3.connect(path)) as c:
        c.execute("CREATE TABLE t (x INTEGER)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
        c.commit()


def test_backup_is_verified_and_pruned(tmp_path):
    src = tmp_path / "live.db"
    _db_file(src)
    out = tmp_path / "backups"
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    made = [backup.create_backup(src, out, keep=2, now=t0 + timedelta(days=i)) for i in range(3)]
    kept = backup.list_backups(out)
    assert [b.path.name for b in kept] == [made[2].path.name, made[1].path.name]  # oldest pruned
    with closing(sqlite3.connect(kept[0].path)) as c:
        assert c.execute("SELECT count(*) FROM t").fetchone()[0] == 3
    assert not list(out.glob("*.part"))
    assert backup.sqlite_path("postgresql+psycopg://u:p@h/d") is None
