from contextlib import nullcontext
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import agents.job_agent.agents as job_agents
from agents.notification_agent import service as notify_service
from app.db.enums import Actor, ApplicationStatus
from app.db.models import Application, DailyReport, Notification, PipelineRun
from app.schemas.settings import Notifications, Preferences, UserSettings
from app.services import settings_service
from integrations.notify import DeliveryError
from scheduler.runner import due, tick
from tests.conftest import login
from tests.integration.test_matching import _scan, profile  # noqa: F401 - shared fixture


def pkt(h, m=0, day=24):
    """A September 2026 wall-clock time in Pakistan, as UTC."""
    return datetime(2026, 9, day, h, m, tzinfo=ZoneInfo("Asia/Karachi")).astimezone(UTC)


@pytest.fixture
def offline_scan(db, owner, monkeypatch):
    """The morning scan uses the fake Remotive feed instead of the network."""
    monkeypatch.setattr(job_agents, "run_job_scan", lambda _db, uid, **kw: _scan(db, owner))


class Sent(list):
    fakes: dict


@pytest.fixture
def sent(monkeypatch):
    """Fake email/Telegram senders that record messages (no network)."""
    out = Sent()

    def make(ch):
        def send(db, user_id, cfg, msg):
            if getattr(send, "fail", False):
                raise DeliveryError("server down")
            out.append((ch, msg.title))

        return send

    out.fakes = {c: make(c) for c in ("email", "telegram")}
    monkeypatch.setattr(notify_service, "SENDERS", out.fakes)
    return out


def factory(db):
    return lambda: nullcontext(db)


def _settings(db, owner, **notif):
    s = UserSettings(
        preferences=Preferences(min_fit_score=60),  # the fictional profile has no job at 80+ in the fake feed
        notifications=Notifications(
            email_enabled=True, email_to="ayesha@example.com", email_from="agent@example.com",
            smtp_host="smtp.example.com", **notif,
        )
    )  # fmt: skip
    settings_service.save(db, owner.id, s, actor=Actor.system)
    db.commit()
    return s


def test_due_on_time_catch_up_and_expired():
    s = UserSettings()
    names = lambda now: {n: t for n, _, t in due(s, now)}  # noqa: E731
    assert names(pkt(7, 3))["morning_scan"] == "schedule"
    assert names(pkt(12, 0))["morning_scan"] == "catch_up"  # laptop was off at 07:00
    assert "morning_scan" not in names(pkt(19, 30))  # 12.5 h late: skipped, tomorrow's scan will run
    assert "delta_scan" not in names(pkt(13, 5))  # off unless enabled
    assert names(pkt(9, 20))["housekeeping"] == "schedule"
    assert due(UserSettings(schedules={"enabled": False}), pkt(7, 3)) == []


def test_morning_scan_notifies_prepares_and_never_submits(db, owner, profile, offline_scan, sent):  # noqa: F811
    _settings(db, owner)
    ran = tick(factory(db), now=pkt(7, 1))
    # oldest slot first: yesterday's 20:00 evening prep (11 h late, within catch_up_hours), 06:15 housekeeping, scan
    assert [(r["pipeline"], r["trigger"]) for r in ran] == [
        ("evening_prep", "catch_up"), ("housekeeping", "catch_up"), ("morning_scan", "schedule"),
    ]  # fmt: skip
    caught_up = db.scalars(select(DailyReport).where(DailyReport.user_id == owner.id)).one()
    assert caught_up.report_date.isoformat() == "2026-09-23"  # the missed slot's own day, not today
    run = db.scalars(select(PipelineRun).where(PipelineRun.pipeline == "morning_scan")).one()
    assert run.status == "succeeded", run.steps
    assert [s["step"] for s in run.steps] == ["job_scan", "notify_matches", "prepare_packages"]

    matches = db.scalars(select(Notification).where(Notification.kind == "new_match")).all()
    per_job = [n for n in matches if n.dedup_key.startswith("match:")]
    assert len(per_job) == 10 and all(n.link.startswith("/jobs/") for n in per_job)  # capped, the rest summarised
    assert any(n.link == "/matches" and "more new matches" in n.title for n in matches)
    assert {ch for ch, _ in sent} == {"email"}  # "important" goes to email; telegram is off
    apps = db.scalars(select(Application).where(Application.user_id == owner.id)).all()
    waiting = {ApplicationStatus.prepared, ApplicationStatus.pending_approval}
    assert 0 < len(apps) <= 5 and all(a.status in waiting for a in apps)  # waiting for you, never submitted
    assert all(a.submitted_at is None for a in apps)

    # the same slots never run twice
    assert tick(factory(db), now=pkt(7, 5)) == []


def test_failed_step_is_recorded_and_reported(db, owner, monkeypatch, sent):
    def broken(*a, **k):
        raise RuntimeError("all sources down")

    monkeypatch.setattr(job_agents, "run_job_scan", broken)
    _settings(db, owner)
    tick(factory(db), now=pkt(7, 2))
    run = db.scalars(select(PipelineRun).where(PipelineRun.pipeline == "morning_scan")).one()
    assert run.status == "partial"  # scan failed; later steps still ran
    assert run.steps[0]["status"] == "failed" and "all sources down" in run.steps[0]["error"]
    problem = db.scalars(select(Notification).where(Notification.kind == "pipeline_problem")).one()
    assert problem.link == "/automation" and "all sources down" in problem.body


def test_evening_report_digest_quiet_hours_and_retry(db, owner, profile, offline_scan, sent):  # noqa: F811
    _settings(db, owner, quiet_hours_start=19, quiet_hours_end=7)  # evening prep at 20:00 falls in quiet hours
    tick(factory(db), now=pkt(20, 1))
    report = db.scalars(select(DailyReport).where(DailyReport.user_id == owner.id)).one()
    assert report.content_md.startswith("# Daily Career Report: 2026-09-24")
    n = db.scalars(select(Notification).where(Notification.kind == "daily_report")).one()
    assert "email" in n.channels  # digest email requested even though it is "info"
    assert n.delivered["email"]["status"] == "deferred" and not sent

    # next morning's housekeeping delivers it; a failing server is retried, not lost
    sent.fakes["email"].fail = True
    notify_service.retry_pending(db, owner.id, pkt(8, 0, day=25))
    assert n.delivered["email"]["status"] == "failed" and n.delivered["email"]["attempts"] == 1
    sent.fakes["email"].fail = False
    notify_service.retry_pending(db, owner.id, pkt(9, 0, day=25))
    assert n.delivered["email"]["status"] == "sent" and sent == [("email", n.title)]


def test_api(client, db, owner, viewer, profile, offline_scan, sent):  # noqa: F811
    h = login(client, owner)
    p = client.get("/api/v1/pipelines", headers=h).json()
    names = {x["name"]: x for x in p["pipelines"]}
    assert names["morning_scan"]["schedule"] == "daily at 07:00" and names["morning_scan"]["next_run"]
    assert names["delta_scan"]["schedule"] == "off" and p["scheduler"]["running"] is False

    assert client.post("/api/v1/pipelines/morning_scan/run", headers=login(client, viewer)).status_code == 403
    assert client.post("/api/v1/pipelines/nope/run", headers=h).status_code == 404
    r = client.post("/api/v1/pipelines/morning_scan/run", params={"wait": True}, headers=h)
    assert r.status_code == 202, r.text
    runs = client.get("/api/v1/pipeline-runs", headers=h).json()
    assert runs[0]["status"] == "succeeded" and runs[0]["trigger"] == "manual"

    alerts = client.get("/api/v1/notifications", headers=h).json()
    assert alerts["unread"] == len(alerts["items"]) > 0
    # a second manual scan finds the same jobs: no duplicate job alerts
    client.post("/api/v1/pipelines/morning_scan/run", params={"wait": True}, headers=h)
    kinds = [i["kind"] for i in client.get("/api/v1/notifications", headers=h).json()["items"]]
    assert kinds.count("new_match") == sum(1 for i in alerts["items"] if i["kind"] == "new_match")

    first = alerts["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{first}/read", headers=h).json()["read_at"]
    assert client.post("/api/v1/notifications/read-all", headers=h).json()["marked"] > 0
    assert client.get("/api/v1/notifications/unread-count", headers=h).json() == {"unread": 0}

    rep = client.post("/api/v1/reports/daily", headers=h).json()
    assert client.get(f"/api/v1/reports/daily/{rep['date']}", headers=h).json()["content_md"] == rep["content_md"]
    assert client.get("/api/v1/reports/daily", headers=h).json()[0]["date"] == rep["date"]
    assert client.get("/api/v1/reports/daily/2020-01-01", headers=h).status_code == 404

    assert client.get("/api/v1/notifications/channels", headers=h).json() == {
        "smtp_password": False, "telegram_bot_token": False,
    }  # fmt: skip
    bad = client.get("/api/v1/settings", headers=h).json()
    bad.pop("version")
    bad["schedules"]["morning_scan"] = "7am"
    assert client.put("/api/v1/settings", json=bad, headers=h).status_code == 422
