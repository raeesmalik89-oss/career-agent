"""End-to-end: one user's whole journey through the public HTTP API, the way the dashboard drives it.

Only the network is faked (job boards return the fixture feed). Everything else runs for real: resume parsing,
fact review, discovery, dedup, matching, application building and validation, interview scoring, skill gaps,
the scheduler pipelines, notifications, the daily report, system health and the audit trail.
"""

import re

import pytest

import app.api.v1.jobs as jobs_api
from tests.conftest import login
from tests.fixtures.jobs import FakeHttp, remotive_payload
from tests.fixtures.resumes import PRIMARY_TXT

REMOTIVE = "https://remotive.com/api/remote-jobs"
PLACEHOLDER = re.compile(r"\[[^\]]*\]")


@pytest.fixture
def offline_boards(monkeypatch, seeded):
    real = jobs_api.run_job_scan
    fake = FakeHttp({REMOTIVE: remotive_payload()})
    monkeypatch.setattr(jobs_api, "run_job_scan", lambda db, uid, **kw: real(db, uid, **{**kw, "http": fake}))
    import agents.job_agent.agents as job_agents

    real_agent = job_agents.run_job_scan
    monkeypatch.setattr(job_agents, "run_job_scan", lambda db, uid, **kw: real_agent(db, uid, **{**kw, "http": fake}))


def test_full_journey(client, owner, viewer, offline_boards, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))
    h = login(client, owner)

    # 1. CV in, facts reviewed
    r = client.post(
        "/api/v1/resume/upload", headers=h, files=[("files", ("cv.txt", PRIMARY_TXT.encode(), "text/plain"))]
    )
    assert r.status_code == 200 and r.json()["ok"], r.text
    pending = client.get("/api/v1/profile/facts", params={"review_status": "pending"}, headers=h).json()
    assert pending
    bulk = client.post("/api/v1/profile/facts/verify-bulk", json={"fact_ids": [f["id"] for f in pending]}, headers=h)
    assert bulk.status_code == 200 and bulk.json()["verified"]

    # 2. a job source, a scan, explained matches
    assert client.patch("/api/v1/sources/remotive", json={"enabled": True}, headers=h).status_code == 200
    scan = client.post("/api/v1/jobs/scan", json={"source_keys": ["remotive"]}, headers=h)
    assert scan.status_code == 200, scan.text
    matches = client.get("/api/v1/matches", params={"min_score": 0}, headers=h).json()
    assert matches["label"] == "Estimated Resume-to-Job Fit Score"
    northwind = next(m for m in matches["matches"] if m["job"]["company"] == "Northwind Cloud")
    explained = client.get(f"/api/v1/jobs/{northwind['job']['id']}/match", headers=h).json()
    assert explained["job"]["id"] == northwind["job"]["id"] and explained["why_matched"]

    # 3. an application: prepared, placeholders written by the user, approved, submitted by the user, tracked
    app = client.post("/api/v1/applications", json={"job_id": northwind["job"]["id"]}, headers=h).json()
    assert app["status"] == "pending_approval" and app["mode"] == "assisted"
    for a in app["answers"]:
        if PLACEHOLDER.search(a["answer"] or ""):
            text = PLACEHOLDER.sub("I value how openly your team writes about its platform.", a["answer"])
            if a["category"] in ("compensation", "relocation", "visa"):
                text = ""
            r = client.patch(f"/api/v1/applications/{app['id']}/answers/{a['id']}", json={"answer": text}, headers=h)
            assert r.status_code == 200, r.text
    approved = client.post(f"/api/v1/applications/{app['id']}/approve", headers=h)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "awaiting_manual_submit"  # the agent never submits by itself
    applied = client.post(f"/api/v1/applications/{app['id']}/status", json={"status": "applied"}, headers=h).json()
    assert applied["status"] == "applied"

    # 4. interview practice
    session = client.post("/api/v1/interview/sessions", json={"mode": "pack", "count": 2}, headers=h).json()
    nxt = session["next"]
    while nxt:
        body = {"question_id": nxt["question_id"], "answer": "I would check the pod events, logs and probes first."}
        fb = client.post(f"/api/v1/interview/sessions/{session['id']}/answer", json=body, headers=h).json()
        assert 0 <= fb["score"] <= 100
        nxt = fb["next"]
    assert client.get("/api/v1/interview/stats", headers=h).json()["answers"] == 2

    # 5. skill gaps and a learning plan
    gaps = client.get("/api/v1/skills/gaps", params={"window": 30}, headers=h).json()
    assert gaps["gaps"]
    plan = client.post("/api/v1/learning/plan", json={"top": 3}, headers=h)
    assert plan.status_code == 200, plan.text

    # 6. automation: evening prep builds the report and notifies; viewers can read but not run
    assert client.post("/api/v1/pipelines/evening_prep/run", headers=login(client, viewer)).status_code == 403
    run = client.post("/api/v1/pipelines/evening_prep/run", params={"wait": True}, headers=h)
    assert run.status_code == 202, run.text
    runs = client.get("/api/v1/pipeline-runs", headers=h).json()
    assert runs[0]["status"] == "succeeded", runs[0]["steps"]
    reports = client.get("/api/v1/reports/daily", headers=h).json()
    report = client.get(f"/api/v1/reports/daily/{reports[0]['date']}", headers=h).json()
    assert "## Applications" in report["content_md"] and "applied: 1" in report["content_md"]
    kinds = {n["kind"] for n in client.get("/api/v1/notifications", headers=h).json()["items"]}
    assert "daily_report" in kinds

    # 7. operations: health, metrics, audit trail
    health = client.get("/api/v1/system/health", headers=h).json()
    assert health["database"]["migration"]["current"] == health["database"]["migration"]["head"]
    assert "career_health_status" in client.get("/metrics").text
    actions = {a["action"] for a in client.get("/api/v1/audit-logs", params={"limit": 500}, headers=h).json()}
    assert {"auth.login", "jobs.scan", "pipeline.run"} <= actions
    assert any(a.startswith("application") for a in actions)

    # 8. sign out: the session is dead at once
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
