"""Scheduler, notifications and daily reports."""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from agents.notification_agent.service import send_test
from app.db.enums import Actor
from app.db.models import DailyReport, Notification, PipelineRun, SchedulerState, User
from app.db.session import get_db, get_sessionmaker
from app.deps import RequestCtx, admin_only, any_user, owner_only, rate_limit, request_ctx
from app.services import audit, settings_service
from app.services.secrets import has_secret
from scheduler.cron import parse
from scheduler.pipelines import PIPELINES
from scheduler.runner import PipelineBusy, execute, next_runs, run_now, schedule_of

router = APIRouter(tags=["automation"])
log = logging.getLogger(__name__)

HEARTBEAT_STALE = timedelta(minutes=3)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _run_out(r: PipelineRun) -> dict:
    return {
        "id": str(r.id),
        "pipeline": r.pipeline,
        "title": PIPELINES.get(r.pipeline, {}).get("title", r.pipeline),
        "trigger": r.trigger,
        "status": r.status,
        "scheduled_for": _aware(r.scheduled_for),
        "started_at": _aware(r.started_at),
        "finished_at": _aware(r.finished_at),
        "steps": r.steps,
    }


@router.get("/pipelines")
def pipelines(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    settings, _ = settings_service.get_effective(db, user.id)
    now = datetime.now(UTC)
    crons = schedule_of(settings)
    nxt = next_runs(settings, now) if settings.schedules.enabled else {}
    last: dict[str, PipelineRun] = {}
    for r in db.scalars(
        select(PipelineRun).where(PipelineRun.user_id == user.id).order_by(PipelineRun.started_at.desc()).limit(200)
    ):
        last.setdefault(r.pipeline, r)
    hb = db.get(SchedulerState, "heartbeat")
    seen = _aware(hb.updated_at) if hb else None
    return {
        "enabled": settings.schedules.enabled,
        "timezone": settings.schedules.timezone,
        "scheduler": {
            "last_seen": seen,
            "running": bool(seen and now - seen <= HEARTBEAT_STALE),
        },
        "pipelines": [
            {
                "name": name,
                "title": spec["title"],
                "about": spec["about"],
                "steps": [s for s, _ in spec["steps"]],
                "cron": crons.get(name),
                "schedule": parse(crons[name]).describe() if name in crons else "off",
                "next_run": nxt.get(name),
                "last_run": _run_out(last[name]) if name in last else None,
            }
            for name, spec in PIPELINES.items()
        ],
    }


@router.get("/pipeline-runs")
def pipeline_runs(
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
    pipeline: str | None = Query(None, max_length=40),
    limit: int = Query(30, ge=1, le=200),
) -> list[dict]:
    q = select(PipelineRun).where(PipelineRun.user_id == user.id)
    if pipeline:
        q = q.where(PipelineRun.pipeline == pipeline)
    return [_run_out(r) for r in db.scalars(q.order_by(PipelineRun.started_at.desc()).limit(limit))]


def _execute_in_background(run_id: uuid.UUID) -> None:
    with get_sessionmaker()() as db:
        run = db.get(PipelineRun, run_id)
        if run is None:
            return
        settings, _ = settings_service.get_effective(db, run.user_id)
        try:
            execute(db, run, settings)
        except Exception:  # noqa: BLE001 - recorded on the run; never crash the worker thread
            log.exception("manual pipeline run %s failed", run_id)
            db.rollback()
            run.status, run.finished_at = "failed", datetime.now(UTC)
            db.commit()


@router.post(
    "/pipelines/{name}/run", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(rate_limit("pipeline_run", 6))]
)
def run_pipeline(
    name: str,
    background: BackgroundTasks,
    wait: bool = False,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:
    """Start a pipeline now. By default it runs in the background; poll GET /pipeline-runs for the result."""
    if name not in PIPELINES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown pipeline")
    try:
        run = run_now(db, user.id, name)
    except PipelineBusy as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit.record(
        db,
        action="pipeline.run",
        actor=Actor.user,
        user_id=user.id,
        entity_type="pipeline_runs",
        entity_id=run.id,
        after={"pipeline": name},
        request_id=ctx.request_id,
    )
    db.commit()
    if wait:
        settings, _ = settings_service.get_effective(db, user.id)
        execute(db, run, settings)
    else:
        background.add_task(_execute_in_background, run.id)
    return _run_out(run)


# ---- notifications -----------------------------------------------------------------------------------------------


def _notification_out(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "created_at": _aware(n.created_at),
        "read_at": _aware(n.read_at),
        "delivered": {k: {"status": v.get("status"), "error": v.get("error")} for k, v in (n.delivered or {}).items()},
    }


@router.get("/notifications")
def notifications(
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
    unread: bool = False,
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
) -> dict:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    if before:
        q = q.where(Notification.created_at < before)
    rows = db.scalars(q.order_by(Notification.created_at.desc()).limit(limit)).all()
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {"unread": count, "items": [_notification_out(n) for n in rows]}


@router.get("/notifications/unread-count")
def unread_count(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    count = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return {"unread": count}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        db.commit()
    return _notification_out(n)


@router.post("/notifications/read-all")
def mark_all_read(user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    res = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    return {"marked": res.rowcount}


@router.get("/notifications/channels")
def channels(user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    """Which secrets the external channels need, and whether they are stored (never their values)."""
    return {
        "smtp_password": has_secret(db, user.id, "smtp_password"),
        "telegram_bot_token": has_secret(db, user.id, "telegram_bot_token"),
    }


@router.post("/notifications/test", dependencies=[Depends(rate_limit("notification_test", 3))])
def test_notification(
    user: User = Depends(owner_only), db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)
) -> dict:
    result = send_test(db, user.id)
    audit.record(
        db,
        action="notification.test",
        actor=Actor.user,
        user_id=user.id,
        entity_type="notifications",
        after={k: v.get("status") for k, v in result.items()},
        request_id=ctx.request_id,
    )
    db.commit()
    return {k: {"status": v.get("status"), "error": v.get("error")} for k, v in result.items()}


# ---- system health and backups -----------------------------------------------------------------------------------


@router.get("/system/health")
def system_health(user: User = Depends(admin_only), db: Session = Depends(get_db)) -> dict:
    from app.services.health import snapshot

    return snapshot(db, user.id)


@router.post("/system/backup", dependencies=[Depends(rate_limit("backup", 3))])
def backup_now(
    user: User = Depends(admin_only), db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)
) -> dict:
    from app.services import backup

    try:
        b = backup.create_backup()
    except backup.BackupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    audit.record(db, action="system.backup", actor=Actor.user, user_id=user.id, after={"file": b.path.name},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return {"file": b.path.name, "size_bytes": b.size, "created_at": b.created_at}


# ---- daily reports -----------------------------------------------------------------------------------------------


@router.get("/reports/daily")
def daily_reports(
    user: User = Depends(any_user), db: Session = Depends(get_db), limit: int = Query(30, ge=1, le=365)
) -> list[dict]:
    rows = db.scalars(
        select(DailyReport).where(DailyReport.user_id == user.id).order_by(DailyReport.report_date.desc()).limit(limit)
    )
    return [
        {"date": r.report_date.isoformat(), "generated_at": _aware(r.generated_at), "headline": _headline(r.metrics)}
        for r in rows
    ]


def _headline(m: dict) -> dict:
    j = m.get("jobs", {})
    return {
        "new_jobs": j.get("new_jobs", 0),
        "qualifying_new": j.get("qualifying_new", 0),
        "needs_you": m.get("applications", {}).get("needs_you", 0),
        "answered": m.get("interview", {}).get("answered_today", 0),
    }


@router.get("/reports/daily/{day}")
def daily_report(day: date, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    r = db.scalars(select(DailyReport).where(DailyReport.user_id == user.id, DailyReport.report_date == day)).first()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no report for that day (it is built by evening prep)")
    return {
        "date": r.report_date.isoformat(),
        "generated_at": _aware(r.generated_at),
        "metrics": r.metrics,
        "content_md": r.content_md,
    }


@router.post("/reports/daily", dependencies=[Depends(rate_limit("report_build", 6))])
def build_report_now(user: User = Depends(owner_only), db: Session = Depends(get_db)) -> dict:
    """Build (or rebuild) today's report without waiting for evening prep. Sends no notification."""
    from agents.report_agent.daily import save

    settings, _ = settings_service.get_effective(db, user.id)
    today = datetime.now(ZoneInfo(settings.schedules.timezone)).date()
    r = save(db, user.id, today)
    db.commit()
    return {
        "date": r.report_date.isoformat(),
        "generated_at": _aware(r.generated_at),
        "metrics": r.metrics,
        "content_md": r.content_md,
    }
