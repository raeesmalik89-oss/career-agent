"""One snapshot of how the system is doing, shared by the System health panel and Prometheus /metrics.

Everything is read from the database (not process memory), so it also covers the separate scheduler process."""

import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.checks import config_checks
from app.db.models import AgentRun, JobRaw, JobSource, Notification, PipelineRun, SchedulerState
from app.services import backup

SCHEDULER_STALE = timedelta(minutes=3)
SCAN_STALE = timedelta(hours=30)
BACKUP_STALE = timedelta(hours=36)
DISK_LOW = 1 * 1024**3
ROOT = Path(__file__).resolve().parents[3]


@lru_cache
def migration_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _age(dt: datetime | None, now: datetime) -> float | None:
    return round((now - dt).total_seconds(), 1) if dt else None


def snapshot(db: Session, user_id: uuid.UUID | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    s = get_settings()
    problems: list[dict] = []

    def problem(level: str, code: str, message: str) -> None:
        problems.append({"level": level, "code": code, "message": message})

    t0 = time.perf_counter()
    db.execute(text("SELECT 1"))
    db_ms = round((time.perf_counter() - t0) * 1000, 1)
    try:
        current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - a database without the table is simply "not migrated"
        db.rollback()
        current = None
    head = migration_head()
    if current != head:
        problem(
            "fail", "migrations_pending", f"database is at {current}, code expects {head}: run alembic upgrade head"
        )

    hb = db.get(SchedulerState, "heartbeat")
    hb_at = _aware(hb.updated_at) if hb else None
    running = bool(hb_at and now - hb_at <= SCHEDULER_STALE)
    if not running:
        problem("warn", "scheduler_down", "the scheduler is not running (start-career-agent.cmd starts it)")

    runs = select(PipelineRun)
    if user_id:
        runs = runs.where(PipelineRun.user_id == user_id)
    last: dict[str, PipelineRun] = {}
    last_ok: dict[str, datetime] = {}
    for r in db.scalars(runs.order_by(PipelineRun.started_at.desc()).limit(300)):
        last.setdefault(r.pipeline, r)
        if r.status == "succeeded" and r.pipeline not in last_ok:
            last_ok[r.pipeline] = _aware(r.finished_at or r.started_at)
    for name, r in last.items():
        if r.status in ("failed", "partial"):
            problem("warn", f"pipeline_{name}", f"last {name.replace('_', ' ')} run {r.status}")

    last_fetch = _aware(db.scalar(select(func.max(JobRaw.fetched_at))))
    if last_fetch is None or now - last_fetch > SCAN_STALE:
        problem("warn", "scan_stale", "no job postings fetched in the last 30 hours")

    since = now - timedelta(days=1)
    failed_runs = db.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.status == "failed", AgentRun.started_at >= since)
    )
    nq = select(Notification).where(Notification.created_at >= now - timedelta(days=3))
    if user_id:
        nq = nq.where(Notification.user_id == user_id)
    undelivered = sum(
        1
        for n in db.scalars(nq)
        for ch, st in (n.delivered or {}).items()
        if ch != "dashboard" and (st or {}).get("status") == "failed"
    )
    if undelivered:
        problem("warn", "notifications_failing", f"{undelivered} email/Telegram deliveries failed in the last 3 days")

    quota = None
    jooble = db.scalars(select(JobSource).where(JobSource.key == "jooble")).first()
    if jooble and jooble.enabled:
        cfg = jooble.config or {}
        quota = {"used": int(cfg.get("requests_used", 0)), "total": int(cfg.get("quota", 500))}
        if quota["total"] - quota["used"] < 40:
            problem("warn", "jooble_quota_low", f"only {quota['total'] - quota['used']} Jooble requests left")

    is_sqlite = backup.sqlite_path() is not None
    latest_backup = backup.list_backups()[:1] if is_sqlite else []
    b_at = latest_backup[0].created_at if latest_backup else None
    if is_sqlite and (b_at is None or now - b_at > BACKUP_STALE):
        problem("warn", "backup_stale", "no database backup in the last 36 hours")

    storage = Path(s.storage_dir)
    free = shutil.disk_usage(storage if storage.exists() else Path.cwd()).free
    if free < DISK_LOW:
        problem("warn", "disk_low", f"only {free // 1024**2} MB free for storage/")

    for c in config_checks(s):
        problem(c.level, c.code, c.message)

    status = "fail" if any(p["level"] == "fail" for p in problems) else "warn" if problems else "ok"
    return {
        "status": status,
        "checked_at": now,
        "problems": problems,
        "database": {
            "ok": True,
            "latency_ms": db_ms,
            "dialect": db.get_bind().dialect.name,
            "migration": {"current": current, "head": head},
        },
        "scheduler": {"running": running, "last_seen": hb_at, "age_seconds": _age(hb_at, now)},
        "pipelines": {
            name: {"status": r.status, "started_at": _aware(r.started_at), "last_success": last_ok.get(name)}
            for name, r in last.items()
        },
        "jobs": {"last_fetch": last_fetch, "age_seconds": _age(last_fetch, now)},
        "agent_runs_failed_24h": failed_runs,
        "notifications_failed_3d": undelivered,
        "jooble_quota": quota,
        "backup": {
            "applies": is_sqlite,
            "latest": b_at,
            "age_seconds": _age(b_at, now),
            "size_bytes": latest_backup[0].size if latest_backup else None,
            "kept": len(backup.list_backups()) if is_sqlite else 0,
        },
        "disk_free_bytes": free,
    }
