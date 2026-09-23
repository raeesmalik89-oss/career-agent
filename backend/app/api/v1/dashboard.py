"""One call for the dashboard home page: counts only, no job descriptions or personal details."""

from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.match_agent.scoring import DISCLAIMER, LABEL
from app.db.models import AgentRun, GithubProfile, GithubRepository, Job, JobMatch, JobRaw, JobSource, ProfileFact, User
from app.db.session import get_db
from app.deps import any_user
from app.services import settings_service

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    settings, version = settings_service.get_effective(db, user.id)
    prefs = settings.preferences
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    matches = db.execute(
        select(JobMatch)
        .join(Job, Job.id == JobMatch.job_id)
        .where(JobMatch.user_id == user.id, JobMatch.job_content_version == Job.content_version)
    ).scalars()
    m_counts: Counter = Counter()
    for m in matches:
        if m.dismissed:
            m_counts["dismissed"] += 1
        elif m.knockouts:
            m_counts["hidden"] += 1
        elif float(m.estimated_fit_score) >= prefs.min_fit_score:
            m_counts["qualifying"] += 1
            m_counts["new"] += m.shown_to_user_at is None
        else:
            m_counts["below_threshold"] += 1

    facts = Counter(
        dict(
            db.execute(
                select(ProfileFact.review_status, func.count())
                .where(ProfileFact.user_id == user.id)
                .group_by(ProfileFact.review_status)
            ).all()
        )
    )
    conflicts = sum(
        1 for d in db.scalars(select(ProfileFact.data).where(ProfileFact.user_id == user.id)) if d.get("conflicts")
    )

    gh = db.scalars(select(GithubProfile).where(GithubProfile.user_id == user.id)).first()
    repos = (
        db.scalar(select(func.count(GithubRepository.id)).where(GithubRepository.github_profile_id == gh.id))
        if gh
        else 0
    )

    scanned_today = db.scalar(select(func.count(JobRaw.id)).where(JobRaw.fetched_at >= today)) or 0
    metered = [
        {
            "source": s.key,
            "used": int((s.config or {}).get("requests_used", 0)),
            "quota": int((s.config or {}).get("quota", 500)),
        }
        for s in db.scalars(select(JobSource).where(JobSource.key == "jooble", JobSource.enabled.is_(True)))
    ]
    runs = db.scalars(select(AgentRun).where(AgentRun.user_id == user.id).order_by(AgentRun.started_at.desc()).limit(8))
    return {
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "settings_version": version,
        "threshold": prefs.min_fit_score,
        "matches": {k: m_counts.get(k, 0) for k in ("qualifying", "new", "below_threshold", "hidden", "dismissed")},
        "jobs": {
            "scanned_today": scanned_today,
            "daily_minimum": prefs.daily_min_jobs_scanned,
            "unique": db.scalar(select(func.count(Job.id))) or 0,
            "targets": db.scalar(select(func.count(Job.id)).where(Job.role_family.is_not(None))) or 0,
            "by_pk_eligibility": {
                k.value: v
                for k, v in db.execute(
                    select(Job.pk_eligibility, func.count())
                    .where(Job.role_family.is_not(None))
                    .group_by(Job.pk_eligibility)
                )
            },
        },
        "facts": {
            "pending": facts.get("pending", 0),
            "verified": facts.get("verified", 0),
            "rejected": facts.get("rejected", 0),
            "conflicts": conflicts,
        },
        "github": {
            "username": gh.username if gh else None,
            "repos": repos,
            "last_synced_at": gh.last_synced_at.isoformat() if gh and gh.last_synced_at else None,
        },
        "metered_sources": metered,
        "recent_runs": [
            {
                "agent": r.agent_name,
                "status": r.status.value,
                "started_at": r.started_at.isoformat(),
                "errors": len(r.errors or []),
            }
            for r in runs
        ],
    }
