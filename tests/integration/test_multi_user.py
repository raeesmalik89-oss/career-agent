"""Multi-user: invite-only sign-up, admin-only functions, and strict separation of every person's data."""

from contextlib import nullcontext
from datetime import UTC, datetime

from sqlalchemy import select

import agents.job_agent.agents as job_agents
from app.db.enums import Role
from app.db.models import Job, PipelineRun, User
from scheduler.runner import tick
from tests.conftest import OWNER_PASSWORD, login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture

PASSWORD = "sunrise-over-margalla-42"


def test_invite_signup_flow(client, owner):
    admin = login(client, owner)
    inv = client.post("/api/v1/admin/invites", json={"email": "sara@example.com", "note": "Sara"}, headers=admin)
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    assert inv.json()["path"] == f"/signup?token={token}" and inv.json()["state"] == "open"
    # the token is shown once: the list never contains it
    assert "token" not in client.get("/api/v1/admin/invites", headers=admin).json()[0]

    assert client.get("/api/v1/auth/invite", params={"token": token}).json()["email"] == "sara@example.com"
    body = {"token": token, "display_name": "Sara Ahmed", "email": "other@example.com", "password": PASSWORD}
    assert client.post("/api/v1/auth/signup", json=body).status_code == 422  # invite is for a different address
    weak = {**body, "email": "sara@example.com", "password": "saraahmed-password"}
    assert client.post("/api/v1/auth/signup", json=weak).status_code == 422  # contains the email name
    r = client.post("/api/v1/auth/signup", json={**body, "email": "sara@example.com"})
    assert r.status_code == 201, r.text
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["role"] == "member" and me["display_name"] == "Sara Ahmed"
    # single use; bad tokens tell nothing
    again = client.post("/api/v1/auth/signup", json={**body, "email": "sara@example.com"})
    assert again.status_code == 404
    assert client.get("/api/v1/auth/invite", params={"token": "x" * 43}).status_code == 404
    listed = {u["email"]: u for u in client.get("/api/v1/admin/users", headers=admin).json()}
    assert listed["sara@example.com"]["role"] == "member" and listed[owner.email]["is_you"]
    # new members start from neutral settings, not the administrator's
    s = client.get("/api/v1/settings", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert s["preferences"]["domain_experience"] == {} and s["preferences"]["cities"] == []


def test_admin_only_functions(client, owner, member):
    m = login(client, member)
    for method, path, body in [
        ("patch", "/api/v1/sources/remotive", {"enabled": True}),
        ("post", "/api/v1/jobs/scan", {}),
        ("get", "/api/v1/system/health", None),
        ("post", "/api/v1/system/backup", None),
        ("get", "/api/v1/admin/users", None),
        ("post", "/api/v1/admin/invites", {}),
    ]:
        r = getattr(client, method)(path, headers=m, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.status_code)
    # but a member manages their own data and settings
    s = client.get("/api/v1/settings", headers=m).json()
    s.pop("version")
    s["preferences"]["min_fit_score"] = 70
    assert client.put("/api/v1/settings", json=s, headers=m).status_code == 200
    assert client.get("/api/v1/sources", headers=m).status_code == 200  # can see which sources exist


def test_one_person_never_sees_another_persons_data(client, db, owner, member, profile):  # noqa: F811
    _scan(db, owner)
    db.commit()
    a = login(client, owner)
    job = db.scalars(select(Job).where(Job.company == "Northwind Cloud")).one()
    app = client.post("/api/v1/applications", json={"job_id": str(job.id)}, headers=a).json()
    fact = client.get("/api/v1/profile/facts", headers=a).json()[0]
    session = client.post("/api/v1/interview/sessions", json={"mode": "pack", "count": 1}, headers=a).json()
    client.post("/api/v1/learning/plan", json={"skills": ["gitops"]}, headers=a)
    item = client.get("/api/v1/learning", headers=a).json()["skills"][0]["items"][0]
    client.post("/api/v1/pipelines/evening_prep/run", params={"wait": True}, headers=a)
    report_day = client.get("/api/v1/reports/daily", headers=a).json()[0]["date"]

    m = login(client, member)
    # lists are empty for the member
    assert client.get("/api/v1/applications", headers=m).json() == []
    assert client.get("/api/v1/profile/facts", headers=m).json() == []
    assert client.get("/api/v1/notifications", headers=m).json()["items"] == []
    assert client.get("/api/v1/reports/daily", headers=m).json() == []
    assert client.get("/api/v1/learning", headers=m).json()["skills"] == []
    assert client.get("/api/v1/pipeline-runs", headers=m).json() == []
    # and every direct link to the administrator's records is refused
    for method, path, body in [
        ("get", f"/api/v1/applications/{app['id']}", None),
        ("post", f"/api/v1/applications/{app['id']}/approve", None),
        ("get", f"/api/v1/applications/{app['id']}/resume.docx", None),
        ("patch", f"/api/v1/profile/facts/{fact['id']}", {"review_status": "rejected"}),
        ("get", f"/api/v1/interview/sessions/{session['id']}", None),
        ("patch", f"/api/v1/learning/items/{item['id']}", {"status": "done"}),
        ("get", f"/api/v1/reports/daily/{report_day}", None),
    ]:
        r = getattr(client, method)(path, headers=m, **({"json": body} if body is not None else {}))
        assert r.status_code in (403, 404, 422), (path, r.status_code)
        assert r.status_code != 200
    # shared job postings are visible to everyone, but scores are personal
    assert client.get(f"/api/v1/jobs/{job.id}", headers=m).status_code == 200
    assert client.get(f"/api/v1/jobs/{job.id}/match", headers=m).status_code == 404  # member has no match yet
    assert client.get(f"/api/v1/applications/{app['id']}", headers=a).status_code == 200  # still the owner's


def test_deactivated_member_is_signed_out(client, owner, member):
    m = login(client, member)
    admin = login(client, owner)
    assert client.patch(f"/api/v1/admin/users/{member.id}", json={"is_active": False}, headers=admin).json() == {
        "id": str(member.id), "is_active": False, "role": "member",
    }  # fmt: skip
    assert client.get("/api/v1/auth/me", headers=m).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": member.email, "password": OWNER_PASSWORD})
    assert r.status_code == 401
    assert client.patch(f"/api/v1/admin/users/{owner.id}", json={"is_active": False}, headers=admin).status_code == 409


def test_one_fetch_serves_everyone(db, owner, member, monkeypatch):
    calls = []

    def fake_scan(_db, uid, **kw):
        calls.append((uid, kw.get("queries")))
        return {"discovery": {"scanned": 0}, "ingest": {}, "matching": {"counts": {}}, "errors": []}

    monkeypatch.setattr(job_agents, "run_job_scan", fake_scan)
    now = datetime(2026, 9, 24, 2, 1, tzinfo=UTC)  # 07:01 in Pakistan
    tick(lambda: nullcontext(db), now=now)
    runs = db.scalars(select(PipelineRun).where(PipelineRun.pipeline == "morning_scan")).all()
    assert {r.user_id for r in runs} == {owner.id, member.id} and all(r.status == "succeeded" for r in runs)
    assert len(calls) == 1 and calls[0][0] == owner.id  # fetched once, with the administrator's keys
    assert "devops engineer" in calls[0][1]
    shared = next(r for r in runs if r.user_id == member.id).steps[0]["summary"]
    assert shared["scanned"] == 0
    assert db.scalars(select(User).where(User.role == Role.member)).one().id == member.id
