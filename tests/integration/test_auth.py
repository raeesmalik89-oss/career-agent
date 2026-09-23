import pyotp
from sqlalchemy import select

from app.api.v1.auth import MAX_FAILED_LOGINS
from app.core import crypto
from app.db.models import AuditLog, AuthSession
from tests.conftest import OWNER_PASSWORD, login


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    r = client.get("/healthz", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_login_me_and_audit(client, db, owner):
    headers = login(client, owner)
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["email"] == owner.email and me["role"] == "owner"
    actions = db.scalars(select(AuditLog.action).where(AuditLog.user_id == owner.id)).all()
    assert "auth.login" in actions


def test_login_sets_httponly_cookies(client, owner):
    r = client.post("/api/v1/auth/login", json={"email": owner.email, "password": OWNER_PASSWORD})
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("ca_access=") and "HttpOnly" in c and "SameSite=strict" in c for c in cookies)
    assert any(c.startswith("ca_refresh=") and "Path=/api/v1/auth" in c for c in cookies)
    # the cookie alone authenticates
    assert client.get("/api/v1/auth/me").status_code == 200


def test_wrong_password_and_unknown_user_look_identical(client, owner):
    bad = client.post("/api/v1/auth/login", json={"email": owner.email, "password": "nope"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()


def test_login_rate_limited(client, owner):
    codes = [
        client.post("/api/v1/auth/login", json={"email": owner.email, "password": "bad"}).status_code for _ in range(7)
    ]
    assert codes[:5] == [401] * 5 and 429 in codes[5:]


def test_account_lockout(client, db, owner):
    from app.api.v1.auth import login_limiter

    for _ in range(MAX_FAILED_LOGINS):
        login_limiter.reset()
        client.post("/api/v1/auth/login", json={"email": owner.email, "password": "bad"})
    login_limiter.reset()
    r = client.post("/api/v1/auth/login", json={"email": owner.email, "password": OWNER_PASSWORD})
    assert r.status_code == 423


def test_unauthenticated_and_garbage_tokens_rejected(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client, db, owner):
    client.post("/api/v1/auth/login", json={"email": owner.email, "password": OWNER_PASSWORD})
    old_refresh = client.cookies.get("ca_refresh")
    r = client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    new_refresh = client.cookies.get("ca_refresh")
    assert new_refresh and new_refresh != old_refresh

    # replaying the rotated token revokes every session of the user
    client.cookies.set("ca_refresh", old_refresh, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    active = db.scalars(
        select(AuthSession).where(AuthSession.user_id == owner.id, AuthSession.revoked_at.is_(None))
    ).all()
    assert active == []
    assert db.scalars(select(AuditLog).where(AuditLog.action == "auth.refresh_reuse_detected")).first() is not None


def test_logout_revokes_session(client, owner):
    headers = login(client, owner)
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_totp_enrolment_and_login(client, db, owner):
    headers = login(client, owner)
    uri = client.post("/api/v1/auth/totp/setup", headers=headers).json()["provisioning_uri"]
    secret = pyotp.parse_uri(uri).secret
    db.refresh(owner)
    assert secret.encode() not in owner.totp_secret_enc  # stored encrypted
    assert crypto.decrypt(owner.totp_secret_enc, b"totp" + owner.id.bytes) == secret

    code = pyotp.TOTP(secret).now()
    assert client.post("/api/v1/auth/totp/verify", headers=headers, json={"code": code}).status_code == 204

    r = client.post("/api/v1/auth/login", json={"email": owner.email, "password": OWNER_PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "totp_required"
    login(client, owner, totp_code=pyotp.TOTP(secret).now())


def test_viewer_cannot_enrol_totp(client, viewer):
    headers = login(client, viewer)
    assert client.post("/api/v1/auth/totp/setup", headers=headers).status_code == 403
