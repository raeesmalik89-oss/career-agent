"""The scheduled pipelines (docs/ARCHITECTURE.md section 15). Each step is a function of a StepContext that returns a
small summary dict; a step that raises is recorded as failed and the next step still runs.

Nothing here submits an application or sends anything to an employer: the most any pipeline does with applications
is *prepare* a package for your review (Settings > schedules.auto_prepare).
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.notification_agent.service import notify, retry_pending
from app.db.enums import Role
from app.db.models import (
    Application,
    GithubProfile,
    Job,
    JobMatch,
    PipelineRun,
    SchedulerState,
    Skill,
    SkillGap,
    User,
)
from app.schemas.settings import UserSettings

MATCH_NOTIFY_CAP = 10
SHARED_FETCH = timedelta(hours=3)
WRITERS = (Role.owner, Role.member)
PREPARE_CAP = 5
STALE_RUN = timedelta(hours=3)


class Skip(Exception):
    """Raised by a step that has nothing to do (recorded as 'skipped', not as a failure)."""


@dataclass
class StepContext:
    db: Session
    user_id: uuid.UUID
    settings: UserSettings
    now: datetime
    run_id: uuid.UUID
    slot: datetime | None = None  # the scheduled fire time; a late (catch-up) run still works for its own day
    state: dict = field(default_factory=dict)

    @property
    def today(self) -> date:
        """The local date of the slot being run (so yesterday's 20:00 report, caught up at 07:00, is yesterday's)."""
        return (self.slot or self.now).astimezone(ZoneInfo(self.settings.schedules.timezone)).date()


# ---- morning_scan / delta_scan ---------------------------------------------------------------------------------


def _admin(db: Session) -> User | None:
    return db.scalars(
        select(User).where(User.role == Role.owner, User.is_active.is_(True)).order_by(User.created_at)
    ).first()


def shared_queries(db: Session) -> list[str]:
    """Search terms for everyone's target roles, so one fetch serves every member."""
    from agents.job_agent.agents import build_queries
    from app.services import settings_service

    families: list[str] = []
    for u in db.scalars(select(User).where(User.role.in_(WRITERS), User.is_active.is_(True))):
        for f in settings_service.get_effective(db, u.id)[0].preferences.target_role_families:
            if f not in families:
                families.append(f)
    return build_queries(families)


def step_job_scan(ctx: StepContext) -> dict:
    """Postings are fetched once for everybody (with the administrator's source keys and quota); a member whose
    scan runs within SHARED_FETCH of the last fetch only gets their matches re-scored."""
    from agents.job_agent.agents import run_job_scan
    from agents.match_agent.agent import run_matching

    state = ctx.db.get(SchedulerState, "discovery")
    last = state.updated_at if state else None
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    admin = _admin(ctx.db)
    if last is not None and ctx.now - last < SHARED_FETCH:
        matching = run_matching(ctx.db, ctx.user_id, pipeline_run_id=ctx.run_id).output
        out = {"discovery": {"shared": True, "fetched_at": last.isoformat()}, "ingest": {}, "matching": matching,
               "errors": []}  # fmt: skip
    else:
        fetcher = admin.id if admin else ctx.user_id
        out = run_job_scan(ctx.db, fetcher, queries=shared_queries(ctx.db))
        if fetcher != ctx.user_id:
            out["matching"] = run_matching(ctx.db, ctx.user_id, pipeline_run_id=ctx.run_id).output
        if state is None:
            ctx.db.add(SchedulerState(key="discovery", value={"by": str(fetcher)}, updated_at=ctx.now))
        else:
            state.value, state.updated_at = {"by": str(fetcher)}, ctx.now
    ctx.state["scan"] = out
    counts = out.get("matching", {}).get("counts", {})
    summary = {
        "scanned": out.get("discovery", {}).get("scanned", 0),
        "per_source": out.get("discovery", {}).get("per_source", {}),
        "new_or_changed": out.get("ingest", {}).get("statuses", {}),
        "scored": counts.get("scored", 0),
        "qualifying": counts.get("qualifying", 0),
        "new_qualifying": counts.get("new_qualifying", 0),
    }
    if out.get("errors"):
        summary["warnings"] = [f"{e.get('code')}: {e.get('message')}"[:200] for e in out["errors"]][:10]
    return summary


def _qualifying(ctx: StepContext, *, unseen_only: bool = False) -> list[tuple[JobMatch, Job]]:
    threshold = ctx.settings.preferences.min_fit_score
    q = (
        select(JobMatch, Job)
        .join(Job, Job.id == JobMatch.job_id)
        .where(
            JobMatch.user_id == ctx.user_id,
            JobMatch.job_content_version == Job.content_version,
            JobMatch.dismissed.is_(False),
            JobMatch.estimated_fit_score >= threshold,
        )
        .order_by(JobMatch.estimated_fit_score.desc())
    )
    if unseen_only:  # a match you already opened on the dashboard needs no alert
        q = q.where(JobMatch.shown_to_user_at.is_(None))
    rows = ctx.db.execute(q).tuples()
    return [(m, j) for m, j in rows if not m.knockouts]


def step_notify_matches(ctx: StepContext) -> dict:
    sent, more = 0, 0
    for m, j in _qualifying(ctx, unseen_only=True):
        if sent >= MATCH_NOTIFY_CAP:
            more += 1
            continue
        n = notify(
            ctx.db,
            ctx.user_id,
            kind="new_match",
            severity="important",
            title=f"New match {float(m.estimated_fit_score):g}: {j.title} at {j.company}",
            body=(m.recommendation or "")[:500] or None,
            link=f"/jobs/{j.id}",
            dedup_key=f"match:{j.id}",
            settings=ctx.settings,
            now=ctx.now,
        )
        if n is not None:
            sent += 1
    if more:
        notify(
            ctx.db,
            ctx.user_id,
            kind="new_match",
            severity="important",
            settings=ctx.settings,
            now=ctx.now,
            title=f"…and {more} more new matches",
            link="/matches",
            dedup_key=f"match-more:{ctx.run_id}",
        )
    scan = ctx.state.get("scan")
    if scan:
        c = scan.get("matching", {}).get("counts", {})
        notify(
            ctx.db,
            ctx.user_id,
            kind="scan_summary",
            settings=ctx.settings,
            now=ctx.now,
            title=f"Job scan: {c.get('scored', 0)} scored, {c.get('qualifying', 0)} at or above "
            f"{ctx.settings.preferences.min_fit_score}, {c.get('knocked_out', 0)} hidden by rules",
            link="/matches",
            dedup_key=f"scan:{ctx.run_id}",
        )
    return {"notified": sent, "not_notified_over_cap": more}


def step_prepare_packages(ctx: StepContext) -> dict:
    """Prepare (never submit) packages for qualifying jobs that have no application yet. Policy still decides."""
    from agents.application_agent.service import ApplicationError, prepare

    if not ctx.settings.schedules.auto_prepare:
        raise Skip("auto_prepare is off in Settings")
    have = set(ctx.db.scalars(select(Application.job_id).where(Application.user_id == ctx.user_id)))
    prepared, refused = [], 0
    for _, j in _qualifying(ctx):
        if len(prepared) >= PREPARE_CAP:
            break
        if j.id in have:
            continue
        try:
            with ctx.db.begin_nested():
                app = prepare(ctx.db, ctx.user_id, j.id, requested_by_user=False)
            prepared.append((app, j))
        except ApplicationError:
            refused += 1
    if prepared:
        notify(
            ctx.db,
            ctx.user_id,
            kind="packages_ready",
            severity="important",
            settings=ctx.settings,
            now=ctx.now,
            title=f"{len(prepared)} application package{'s' if len(prepared) > 1 else ''} ready for your review",
            body="\n".join(f"- {j.title} at {j.company}" for _, j in prepared)
            + "\n\nNothing has been sent. Review, edit and approve each one, then apply on the employer's site.",
            link="/applications",
            dedup_key=f"packages:{ctx.run_id}",
        )
    return {"prepared": len(prepared), "refused_by_policy_or_duplicate": refused}


# ---- afternoon_analysis ------------------------------------------------------------------------------------------


def step_skill_gaps(ctx: StepContext) -> dict:
    from agents.skill_agent.gaps import analyse, save_report

    previous_day = ctx.db.scalar(
        select(func.max(SkillGap.report_date)).where(
            SkillGap.user_id == ctx.user_id, SkillGap.window_days == 30, SkillGap.report_date < ctx.today
        )
    )
    top_before: set[str] | None = None  # first ever report: nothing to compare with, so no "new top gap" alerts
    if previous_day:
        top_before = set(
            ctx.db.scalars(
                select(Skill.canonical_name)
                .join(SkillGap, SkillGap.skill_id == Skill.id)
                .where(
                    SkillGap.user_id == ctx.user_id,
                    SkillGap.window_days == 30,
                    SkillGap.report_date == previous_day,
                    SkillGap.gap_status != "have",
                )
                .order_by(SkillGap.priority_score.desc())
                .limit(5)
            )
        )
    out = {}
    for window in (1, 7, 30):
        report = analyse(ctx.db, ctx.user_id, window)
        save_report(ctx.db, ctx.user_id, report, ctx.today)
        out[f"window_{window}"] = {"jobs": report["jobs_analysed"], "gaps": len(report["gaps"])}
        if window == 30:
            top = [g for g in report["gaps"] if g["status"] != "have"][:5]
            out["top_gaps"] = [g["skill"] for g in top]
            week = ctx.today.isocalendar()
            for g in top:
                if top_before is None or g["skill"] in top_before:
                    continue
                notify(
                    ctx.db,
                    ctx.user_id,
                    kind="skill_gap",
                    settings=ctx.settings,
                    now=ctx.now,
                    title=f"{g['name']} is now one of your top skill gaps (priority {g['priority']:g})",
                    body=f"Asked for in {g['jobs_requiring']} jobs open to you. {g['status_reason']}",
                    link=f"/skills/{g['skill']}",
                    dedup_key=f"gap-top:{g['skill']}:{week.year}-W{week.week}",
                )
    return out


# ---- evening_prep ------------------------------------------------------------------------------------------------


def step_interview_pack(ctx: StepContext) -> dict:
    from agents.interview_agent.pack import generate_pack

    tomorrow = ctx.today + timedelta(days=1)
    rows = generate_pack(ctx.db, ctx.user_id, tomorrow)
    return {"pack_date": tomorrow.isoformat(), "questions": len(rows)}


def step_daily_report(ctx: StepContext) -> dict:
    from agents.report_agent.daily import save

    report = save(ctx.db, ctx.user_id, ctx.today)
    cfg = ctx.settings.notifications
    notify(
        ctx.db,
        ctx.user_id,
        kind="daily_report",
        settings=ctx.settings,
        now=ctx.now,
        title=f"Daily Career Report for {ctx.today.isoformat()}",
        body=report.content_md,
        link=f"/reports/{ctx.today.isoformat()}",
        dedup_key=f"report:{ctx.today.isoformat()}",
        extra_channels=("email",) if cfg.daily_digest_email else (),
    )
    return {"report_date": ctx.today.isoformat()}


# ---- weekly_sync -------------------------------------------------------------------------------------------------


def step_github_sync(ctx: StepContext) -> dict:
    from agents.github_agent.agent import GithubAnalyzerAgent, GithubAnalyzerInput

    profile = ctx.db.scalars(select(GithubProfile).where(GithubProfile.user_id == ctx.user_id)).first()
    if profile is None:
        raise Skip("no GitHub profile analysed yet (run the first sync from the GitHub page)")
    result = GithubAnalyzerAgent().run(
        GithubAnalyzerInput(user_id=ctx.user_id, username=profile.username),
        ctx.db,
        user_id=ctx.user_id,
        pipeline_run_id=ctx.run_id,
    )
    repos = sum(1 for a in result.actions if a.type == "analyzed_repository")
    if result.errors:
        raise RuntimeError("; ".join(f"{e.code}: {e.message}" for e in result.errors)[:300])
    return {"username": profile.username, "repositories": repos}


def step_rescore(ctx: StepContext) -> dict:
    from agents.match_agent.agent import run_matching

    out = run_matching(ctx.db, ctx.user_id, pipeline_run_id=ctx.run_id).output
    return {k: out.get("counts", {}).get(k, 0) for k in ("scored", "qualifying", "knocked_out")}


# ---- housekeeping ------------------------------------------------------------------------------------------------


def step_retry_notifications(ctx: StepContext) -> dict:
    return retry_pending(ctx.db, ctx.user_id, ctx.now)


def step_stale_runs(ctx: StepContext) -> dict:
    """A run still 'running' after STALE_RUN hours was interrupted (computer slept, process killed)."""
    stale = ctx.db.scalars(
        select(PipelineRun).where(
            PipelineRun.user_id == ctx.user_id,
            PipelineRun.status == "running",
            PipelineRun.started_at < ctx.now - STALE_RUN,
            PipelineRun.id != ctx.run_id,
        )
    ).all()
    for r in stale:
        r.status = "failed"
        r.finished_at = ctx.now
        r.steps = [*r.steps, {"step": "interrupted", "status": "failed", "error": "the run never finished"}]
    return {"marked_interrupted": len(stale)}


def step_backup(ctx: StepContext) -> dict:
    """Once a day (the first housekeeping after 20 h), a verified copy of the SQLite database."""
    from app.services import backup

    path = backup.sqlite_path()
    if path is None:
        raise Skip("PostgreSQL: back up with pg_dump")
    if not path.is_file():
        raise Skip(f"no database file at {path}")
    if not backup.due(ctx.now):
        raise Skip("today's backup already exists")
    b = backup.create_backup(now=ctx.now)
    return {"file": b.path.name, "size_mb": round(b.size / 1024**2, 1), "kept": len(backup.list_backups())}


Step = tuple[str, Callable[[StepContext], dict]]

SCAN_STEPS: list[Step] = [
    ("job_scan", step_job_scan),
    ("notify_matches", step_notify_matches),
    ("prepare_packages", step_prepare_packages),
]

PIPELINES: dict[str, dict] = {
    "morning_scan": {
        "title": "Morning job scan",
        "about": "Fetch new postings, remove duplicates, score them, tell you about matches and prepare packages.",
        "steps": SCAN_STEPS,
    },
    "delta_scan": {
        "title": "Extra midday scan",
        "about": "The same as the morning scan (optional; uses more Jooble requests).",
        "steps": SCAN_STEPS,
    },
    "afternoon_analysis": {
        "title": "Skill-gap analysis",
        "about": "Recompute skill gaps for 1, 7 and 30 days and flag skills that enter your top 5.",
        "steps": [("skill_gaps", step_skill_gaps)],
    },
    "evening_prep": {
        "title": "Evening prep",
        "about": "Build tomorrow's interview pack and today's Daily Career Report.",
        "steps": [("interview_pack", step_interview_pack), ("daily_report", step_daily_report)],
    },
    "weekly_sync": {
        "title": "Weekly GitHub sync",
        "about": "Re-analyse your GitHub repos so new projects count as evidence, then re-score jobs.",
        "steps": [("github_sync", step_github_sync), ("rescore", step_rescore)],
    },
    "housekeeping": {
        "title": "Housekeeping",
        "about": "Retry failed email/Telegram deliveries, close interrupted runs and back up the database daily.",
        "steps": [
            ("retry_notifications", step_retry_notifications),
            ("stale_runs", step_stale_runs),
            ("backup", step_backup),
        ],
        "quiet": True,  # never notifies about itself unless it fails
    },
}

ORDER = ["housekeeping", "weekly_sync", "morning_scan", "delta_scan", "afternoon_analysis", "evening_prep"]


def now_utc() -> datetime:
    return datetime.now(UTC)
