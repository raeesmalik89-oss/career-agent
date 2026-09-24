"""Daily Career Report: a factual roll-up of the day (local time zone), built only from stored data.

No LLM and no guessing: every number is a count or average over rows written by the other agents."""

import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    DailyReport,
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    Job,
    JobMatch,
    JobRaw,
    JobSource,
    LearningItem,
    PipelineRun,
    Skill,
    SkillGap,
)
from app.services import settings_service

ATTENTION = ("prepared", "pending_approval", "approved", "awaiting_manual_submit")
KNOCKOUT_TEXT = {
    "pk_ineligible": "not open to Pakistan",
    "pk_unknown": "Pakistan eligibility unknown",
    "location": "location",
    "clearance": "security clearance",
    "visa": "visa",
    "seniority": "seniority above your level",
    "experience": "more years than you have",
    "unconfirmed": "summary only (paste full posting)",
}


def local_day_bounds(day: date, tz: str) -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    start = datetime.combine(day, time.min, tzinfo=z).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=z).astimezone(UTC)
    return start, end


def _current_matches(db: Session, user_id: uuid.UUID) -> list[tuple[JobMatch, Job]]:
    return list(
        db.execute(
            select(JobMatch, Job)
            .join(Job, Job.id == JobMatch.job_id)
            .where(JobMatch.user_id == user_id, JobMatch.job_content_version == Job.content_version)
        ).tuples()
    )


def build(db: Session, user_id: uuid.UUID, day: date) -> dict:
    settings, _ = settings_service.get_effective(db, user_id)
    tz = settings.schedules.timezone
    threshold = settings.preferences.min_fit_score
    start, end = local_day_bounds(day, tz)

    fetched = db.scalar(
        select(func.count()).select_from(JobRaw).where(JobRaw.fetched_at >= start, JobRaw.fetched_at < end)
    )
    matches = _current_matches(db, user_id)
    new_today = [(m, j) for m, j in matches if start <= _aware(j.first_seen_at) < end]
    qualifying = [
        (m, j) for m, j in matches if not m.knockouts and float(m.estimated_fit_score) >= threshold and not m.dismissed
    ]
    open_to_you = sorted(
        ((m, j) for m, j in matches if not m.knockouts and not m.dismissed),
        key=lambda mj: float(mj[0].estimated_fit_score),
        reverse=True,
    )
    knockouts = Counter(k["code"] for m, _ in new_today for k in m.knockouts)

    apps = Counter(
        s.value if hasattr(s, "value") else s
        for s in db.scalars(select(Application.status).where(Application.user_id == user_id))
    )

    pack = db.scalar(
        select(func.count())
        .select_from(InterviewQuestion)
        .where(InterviewQuestion.user_id == user_id, InterviewQuestion.pack_date == day)
    )
    scores = list(
        db.scalars(
            select(InterviewAnswer.score)
            .join(InterviewSession, InterviewSession.id == InterviewAnswer.session_id)
            .where(InterviewSession.user_id == user_id, InterviewAnswer.at >= start, InterviewAnswer.at < end)
        )
    )

    learned_today = db.scalar(
        select(func.count())
        .select_from(LearningItem)
        .where(LearningItem.user_id == user_id, LearningItem.completed_at >= start, LearningItem.completed_at < end)
    )
    plan_total = db.scalar(select(func.count()).select_from(LearningItem).where(LearningItem.user_id == user_id))
    plan_done = db.scalar(
        select(func.count())
        .select_from(LearningItem)
        .where(LearningItem.user_id == user_id, LearningItem.status == "done")
    )

    gap_day = db.scalar(
        select(func.max(SkillGap.report_date)).where(SkillGap.user_id == user_id, SkillGap.window_days == 30)
    )
    gaps = []
    if gap_day:
        gaps = [
            {
                "skill": s.canonical_name,
                "name": s.display_name,
                "status": g.gap_status.value,
                "priority": float(g.priority_score),
            }
            for g, s in db.execute(
                select(SkillGap, Skill)
                .join(Skill, Skill.id == SkillGap.skill_id)
                .where(
                    SkillGap.user_id == user_id,
                    SkillGap.report_date == gap_day,
                    SkillGap.window_days == 30,
                    SkillGap.gap_status != "have",
                )
                .order_by(SkillGap.priority_score.desc())
                .limit(5)
            ).tuples()
        ]

    runs = [
        {"pipeline": r.pipeline, "status": r.status, "trigger": r.trigger}
        for r in db.scalars(
            select(PipelineRun)
            .where(PipelineRun.user_id == user_id, PipelineRun.started_at >= start, PipelineRun.started_at < end)
            .order_by(PipelineRun.started_at)
        )
    ]
    jooble = db.scalars(select(JobSource).where(JobSource.key == "jooble")).first()
    quota = None
    if jooble and jooble.enabled:
        cfg = jooble.config or {}
        quota = {"used": int(cfg.get("requests_used", 0)), "total": int(cfg.get("quota", 500))}

    def job_row(m: JobMatch, j: Job) -> dict:
        return {"job_id": str(j.id), "title": j.title, "company": j.company, "score": float(m.estimated_fit_score)}

    return {
        "date": day.isoformat(),
        "timezone": tz,
        "threshold": threshold,
        "jobs": {
            "postings_fetched": fetched,
            "new_jobs": len(new_today),
            "new_open_to_you": sum(1 for m, _ in new_today if not m.knockouts),
            "qualifying_total": len(qualifying),
            "qualifying_new": sum(1 for m, j in qualifying if start <= _aware(j.first_seen_at) < end),
            "knockouts_today": dict(knockouts.most_common()),
            "top_open": [job_row(m, j) for m, j in open_to_you[:5]],
        },
        "applications": {"by_status": dict(apps), "needs_you": sum(apps.get(s, 0) for s in ATTENTION)},
        "interview": {
            "pack_questions": pack,
            "answered_today": len(scores),
            "avg_score_today": round(sum(scores) / len(scores), 1) if scores else None,
        },
        "learning": {"done_today": learned_today, "plan_done": plan_done, "plan_total": plan_total},
        "top_gaps": gaps,
        "pipelines": runs,
        "jooble_quota": quota,
    }


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def render_md(m: dict) -> str:
    j, a, i, learn = m["jobs"], m["applications"], m["interview"], m["learning"]
    out = [f"# Daily Career Report: {m['date']}", ""]
    out += [
        "## Jobs",
        f"- Postings fetched: {j['postings_fetched']}",
        f"- New jobs: {j['new_jobs']} ({j['new_open_to_you']} open to you)",
        f"- Matches at or above {m['threshold']}: {j['qualifying_total']} ({j['qualifying_new']} new today)",
    ]
    if j["knockouts_today"]:
        out.append(
            "- Hidden today: " + ", ".join(f"{n} {KNOCKOUT_TEXT.get(k, k)}" for k, n in j["knockouts_today"].items())
        )
    if j["top_open"]:
        out += ["", "Best jobs open to you:"]
        out += [f"- {r['score']:g} · {r['title']} at {r['company']}" for r in j["top_open"]]
    out += ["", "## Applications"]
    if a["by_status"]:
        out.append("- " + ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in sorted(a["by_status"].items())))
        out.append(f"- Waiting for you: {a['needs_you']}")
    else:
        out.append("- None yet")
    out += [
        "",
        "## Interview practice",
        f"- Today's pack: {i['pack_questions']} questions",
        f"- Answered today: {i['answered_today']}"
        + (f" (average score {i['avg_score_today']:g})" if i["avg_score_today"] is not None else ""),
    ]
    out += [
        "",
        "## Learning",
        f"- Items done today: {learn['done_today']}",
        f"- Learning plan: {learn['plan_done']}/{learn['plan_total']} done",
    ]
    if m["top_gaps"]:
        out += ["", "## Top skill gaps"]
        out += [f"- {g['name']} ({g['status']}, priority {g['priority']:g})" for g in m["top_gaps"]]
    if m["pipelines"]:
        out += ["", "## Automation"]
        out += [
            f"- {r['pipeline'].replace('_', ' ')}: {r['status']}"
            + (" (caught up)" if r["trigger"] == "catch_up" else "")
            for r in m["pipelines"]
        ]
    if m["jooble_quota"]:
        q = m["jooble_quota"]
        out += ["", f"Jooble requests used: {q['used']}/{q['total']}"]
    return "\n".join(out) + "\n"


def save(db: Session, user_id: uuid.UUID, day: date) -> DailyReport:
    metrics = build(db, user_id, day)
    row = db.scalars(select(DailyReport).where(DailyReport.user_id == user_id, DailyReport.report_date == day)).first()
    if row is None:
        row = DailyReport(user_id=user_id, report_date=day, metrics=metrics, content_md=render_md(metrics))
        db.add(row)
    else:
        row.metrics = metrics
        row.content_md = render_md(metrics)
        row.generated_at = datetime.now(UTC)
    db.flush()
    return row
