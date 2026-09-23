import pytest
from sqlalchemy import select, text

from app.db.enums import Actor
from app.db.models import AuditLog, JobSource
from app.services import audit
from tests.conftest import login


def test_default_settings_reflect_owner_profile(client, owner):
    s = client.get("/api/v1/settings", headers=login(client, owner)).json()
    assert s["version"] == 1
    p = s["preferences"]
    assert p["min_fit_score"] == 80 and p["daily_min_jobs_scanned"] == 30
    assert p["cities"] == ["Islamabad", "Rawalpindi"]
    assert p["auto_apply"] is False and p["approval_mode"] == "HYBRID"
    assert sum(s["scoring_weights"].values()) == 100


def test_settings_update_creates_version_and_audit_diff(client, db, owner):
    headers = login(client, owner)
    s = client.get("/api/v1/settings", headers=headers).json()
    s.pop("version")
    s["preferences"]["min_fit_score"] = 85
    r = client.put("/api/v1/settings", headers=headers, json=s)
    assert r.status_code == 200 and r.json()["version"] == 2
    assert [h["version"] for h in client.get("/api/v1/settings/history", headers=headers).json()] == [2, 1]

    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "settings.update").order_by(AuditLog.at.desc())
    ).first()
    assert entry.after == {"preferences": {"min_fit_score": 85}}
    assert entry.before == {"preferences": {"min_fit_score": 80}}


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda s: s["scoring_weights"].update(skills=50), "sum to 100"),
        (lambda s: s["preferences"].update(target_role_families=["astronaut"]), "unknown role families"),
        (lambda s: s["preferences"].update(min_fit_score=150), "less than or equal"),
        (lambda s: s["preferences"].update(surprise=True), "Extra inputs"),
    ],
)
def test_settings_validation(client, owner, mutate, fragment):
    headers = login(client, owner)
    s = client.get("/api/v1/settings", headers=headers).json()
    s.pop("version")
    mutate(s)
    r = client.put("/api/v1/settings", headers=headers, json=s)
    assert r.status_code == 422 and fragment in r.text


def test_viewer_is_read_only(client, viewer):
    headers = login(client, viewer)
    s = client.get("/api/v1/settings", headers=headers).json()
    s.pop("version")
    assert client.put("/api/v1/settings", headers=headers, json=s).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=headers).status_code == 403


def test_sources_seeded_safely(client, owner, seeded):
    sources = {s["key"]: s for s in client.get("/api/v1/sources", headers=login(client, owner)).json()}
    assert {"remoteok", "remotive", "greenhouse", "linkedin_alerts", "manual"} <= sources.keys()
    assert not any(s["auto_apply_allowed"] for s in sources.values())
    assert [k for k, s in sources.items() if s["enabled"]] == ["manual"]


def test_auto_apply_blocked_on_prohibited_platform(client, owner, seeded):
    headers = login(client, owner)
    r = client.patch("/api/v1/sources/linkedin_alerts", headers=headers, json={"auto_apply_allowed": True})
    assert r.status_code == 422 and "prohibit" in r.text


def test_auto_apply_requires_tos_review(client, db, owner, seeded):
    headers = login(client, owner)
    r = client.patch("/api/v1/sources/greenhouse", headers=headers, json={"auto_apply_allowed": True})
    assert r.status_code == 422
    r = client.patch(
        "/api/v1/sources/greenhouse", headers=headers, json={"auto_apply_allowed": True, "tos_reviewed": True}
    )
    assert r.status_code == 200 and r.json()["auto_apply_allowed"] is True
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "source.update")).first()
    assert entry.before["auto_apply_allowed"] is False and entry.after["auto_apply_allowed"] is True


def test_source_patch_rejects_unknown_fields(client, owner, seeded):
    r = client.patch("/api/v1/sources/remoteok", headers=login(client, owner), json={"read_allowed": True})
    assert r.status_code == 422


def test_seed_is_idempotent_and_preserves_owner_choices(db, seeded):
    from app.services.seed import seed_sources

    src = db.scalars(select(JobSource).where(JobSource.key == "remoteok")).one()
    src.enabled = True
    db.commit()
    assert seed_sources(db) == 0
    assert db.scalars(select(JobSource).where(JobSource.key == "remoteok")).one().enabled is True


def test_audit_redacts_secrets(db, owner):
    e = audit.record(db, action="x", actor=Actor.system, user_id=owner.id, after={"token": "abc", "ok": 1})
    db.flush()
    assert e.after == {"token": "[REDACTED]", "ok": 1}


def test_audit_log_endpoint(client, owner):
    headers = login(client, owner)
    rows = client.get("/api/v1/audit-logs?action=auth.login", headers=headers).json()
    assert rows and all(r["action"] == "auth.login" for r in rows)


@pytest.mark.postgres
def test_audit_log_is_append_only_in_postgres(db, owner):
    audit.record(db, action="immutable.test", actor=Actor.system, user_id=owner.id)
    db.flush()
    with pytest.raises(Exception, match="append-only"):
        db.execute(text("UPDATE audit_logs SET action = 'tampered'"))
