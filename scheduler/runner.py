"""Decides which pipelines are due, claims each slot exactly once and runs its steps.

A slot is (user, pipeline, cron fire time). Claiming inserts a pipeline_runs row whose unique constraint makes a
second claim of the same slot fail, so restarts and duplicate scheduler processes cannot double-run anything.
A slot missed while the computer was off is run late ("catch_up") if it is at most schedules.catch_up_hours old.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agents.notification_agent.service import notify
from app.db.enums import Role
from app.db.models import PipelineRun, SchedulerState, User
from app.schemas.settings import UserSettings
from app.services import settings_service
from scheduler.cron import parse
from scheduler.pipelines import ORDER, PIPELINES, STALE_RUN, Skip, StepContext

log = logging.getLogger(__name__)

ON_TIME = timedelta(minutes=10)
HOUSEKEEPING_WINDOW = timedelta(hours=1)


class PipelineBusy(Exception):
    pass


def schedule_of(settings: UserSettings) -> dict[str, str]:
    s = settings.schedules
    out = {name: getattr(s, name) for name in ORDER}
    if not s.delta_scans_enabled:
        out.pop("delta_scan")
    return out


def due(settings: UserSettings, now: datetime) -> list[tuple[str, datetime, str]]:
    """(pipeline, fire time UTC, trigger) for every pipeline whose latest fire time is recent enough to run."""
    s = settings.schedules
    if not s.enabled:
        return []
    out = []
    for name, expr in schedule_of(settings).items():
        fire = parse(expr).previous_at_or_before(now, s.timezone)
        age = now - fire
        window = HOUSEKEEPING_WINDOW if name == "housekeeping" else max(timedelta(hours=s.catch_up_hours), ON_TIME)
        if age <= window:
            out.append((name, fire, "schedule" if age <= ON_TIME else "catch_up"))
    return sorted(out, key=lambda d: d[1])  # oldest slot first


def next_runs(settings: UserSettings, now: datetime) -> dict[str, datetime]:
    tz = settings.schedules.timezone
    return {name: parse(expr).next_after(now, tz) for name, expr in schedule_of(settings).items()}


def busy(db: Session, user_id: uuid.UUID, now: datetime) -> PipelineRun | None:
    """A run still in progress for this user (ignoring runs so old they were clearly interrupted)."""
    return db.scalars(
        select(PipelineRun).where(
            PipelineRun.user_id == user_id,
            PipelineRun.status == "running",
            PipelineRun.started_at >= now - STALE_RUN,
        )
    ).first()


def claim(
    db: Session, user_id: uuid.UUID, pipeline: str, fire: datetime, trigger: str, now: datetime
) -> PipelineRun | None:
    run = PipelineRun(
        id=uuid.uuid4(),
        user_id=user_id,
        pipeline=pipeline,
        scheduled_for=fire,
        trigger=trigger,
        status="running",
        steps=[],
        started_at=now,
    )
    try:
        with db.begin_nested():
            db.add(run)
    except IntegrityError:
        return None
    db.commit()
    return run


def execute(db: Session, run: PipelineRun, settings: UserSettings, now: datetime | None = None) -> PipelineRun:
    """Run every step, committing after each so partial progress is kept even if a later step fails."""
    spec = PIPELINES[run.pipeline]
    slot = run.scheduled_for if run.scheduled_for.tzinfo else run.scheduled_for.replace(tzinfo=UTC)
    ctx = StepContext(
        db=db, user_id=run.user_id, settings=settings, now=now or datetime.now(UTC), run_id=run.id, slot=slot
    )
    results: list[dict] = []
    for name, fn in spec["steps"]:
        started = datetime.now(UTC)
        entry: dict = {"step": name}
        try:
            entry["summary"] = fn(ctx)
            entry["status"] = "partial" if entry["summary"].get("warnings") else "succeeded"
            db.commit()
        except Skip as exc:
            db.rollback()
            entry.update(status="skipped", note=str(exc))
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others
            db.rollback()
            log.exception("pipeline %s step %s failed", run.pipeline, name)
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        entry["seconds"] = round((datetime.now(UTC) - started).total_seconds(), 1)
        results.append(entry)
        run.steps = list(results)
        db.commit()

    statuses = {r["status"] for r in results}
    if statuses <= {"succeeded", "skipped"}:
        run.status = "succeeded"
    elif statuses <= {"failed", "skipped"} and "failed" in statuses:
        run.status = "failed"
    else:
        run.status = "partial"
    run.finished_at = datetime.now(UTC)
    db.commit()

    if run.status != "succeeded":
        problems = [
            f"{r['step']}: {r.get('error') or ', '.join(r.get('summary', {}).get('warnings', []))}"
            for r in results
            if r["status"] in ("failed", "partial")
        ]
        notify(
            db,
            run.user_id,
            kind="pipeline_problem",
            severity="important",
            settings=settings,
            title=f"{spec['title']} {'failed' if run.status == 'failed' else 'finished with problems'}",
            body="\n".join(problems)[:1500],
            link="/automation",
            dedup_key=f"run:{run.id}",
        )
        db.commit()
    return run


def run_now(db: Session, user_id: uuid.UUID, pipeline: str, *, trigger: str = "manual") -> PipelineRun:
    """Claim a manual slot (now) and return it; the caller executes it (possibly in the background)."""
    if pipeline not in PIPELINES:
        raise KeyError(pipeline)
    now = datetime.now(UTC)
    if busy(db, user_id, now):
        raise PipelineBusy("another pipeline is still running; try again when it finishes")
    run = claim(db, user_id, pipeline, now, trigger, now)
    if run is None:
        raise PipelineBusy("that pipeline was just started")
    return run


def heartbeat(db: Session, now: datetime, detail: dict) -> None:
    row = db.get(SchedulerState, "heartbeat")
    if row is None:
        db.add(SchedulerState(key="heartbeat", value=detail, updated_at=now))
    else:
        row.value = detail
        row.updated_at = now
    db.commit()


def tick(session_factory: Callable[[], Session], now: datetime | None = None) -> list[dict]:
    """One scheduler pass over every active owner account. Returns what ran."""
    now = now or datetime.now(UTC)
    ran: list[dict] = []
    with session_factory() as db:
        owners = db.scalars(select(User).where(User.role == Role.owner, User.is_active.is_(True))).all()
        for user in owners:
            settings, _ = settings_service.get_effective(db, user.id)
            for pipeline, fire, trigger in due(settings, now):
                if busy(db, user.id, now):
                    break  # finish the current run first; this slot is still due on the next tick
                run = claim(db, user.id, pipeline, fire, trigger, now)
                if run is None:
                    continue  # already ran (or is running) for this slot
                log.info("running %s for user %s (%s, slot %s)", pipeline, user.id, trigger, fire.isoformat())
                execute(db, run, settings, now)
                ran.append({"pipeline": pipeline, "status": run.status, "trigger": trigger})
        heartbeat(db, datetime.now(UTC), {"last_tick": now.isoformat(), "ran": ran})
    return ran
