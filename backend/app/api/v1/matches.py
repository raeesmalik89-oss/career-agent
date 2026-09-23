import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.match_agent.agent import run_matching
from agents.match_agent.scoring import DISCLAIMER, LABEL
from app.api.v1.jobs import _job_out
from app.db.enums import Actor
from app.db.models import Job, JobMatch, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.services import audit, settings_service

router = APIRouter(tags=["matches"])


class SeenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


def _match_out(m: JobMatch, job: Job, db: Session, full: bool = False) -> dict:
    out = {
        "match_id": str(m.id),
        "job": _job_out(db, job, full=full),
        "label": m.breakdown.get("label"),
        "estimated_fit_score": float(m.estimated_fit_score),
        "confidence": m.score_confidence.value,
        "disclaimer": DISCLAIMER,
        "recommendation": m.recommendation,
        "knockouts": m.knockouts,
        "is_new": m.shown_to_user_at is None,
        "dismissed": m.dismissed,
        "why_matched": m.why_matched,
        "why_not_matched": m.why_not_matched,
        "missing_skills": m.missing_skills,
        "partial_skills": m.partial_skills,
        "risks": m.risks,
    }
    if full:
        out |= {
            "components": m.breakdown.get("components"),
            "confidence_points": m.breakdown.get("confidence_points"),
            "weights": m.breakdown.get("weights"),
            "profile": m.breakdown.get("profile"),
            "previous_score": m.breakdown.get("previous_score"),
            "evidence": m.evidence,
            "settings_version": m.settings_version,
            "job_content_version": m.job_content_version,
        }
    return out


def _sort_key(m: JobMatch, job: Job) -> tuple:
    c = m.breakdown.get("components", {})
    pts = lambda k: c.get(k, {}).get("points", 0)  # noqa: E731
    return (
        -float(m.estimated_fit_score),
        -pts("skills"),
        -pts("experience"),
        -pts("github_evidence"),
        -pts("location_remote"),
        -(job.posted_date.toordinal() if job.posted_date else 0),
        -int(job.salary_min is not None),
    )


@router.get("/matches")
def list_matches(
    user: User = Depends(any_user),
    db: Session = Depends(get_db),
    min_score: float | None = Query(None, ge=0, le=100),
    new_only: bool = False,
    include_hidden: bool = False,
    include_dismissed: bool = False,
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    """Current matches (latest job version only), ranked. By default only jobs at or above your threshold
    with no knockouts: the jobs you would be shown."""
    settings, _ = settings_service.get_effective(db, user.id)
    threshold = settings.preferences.min_fit_score if min_score is None else min_score
    rows = db.execute(
        select(JobMatch, Job)
        .join(Job, Job.id == JobMatch.job_id)
        .where(JobMatch.user_id == user.id, JobMatch.job_content_version == Job.content_version)
    ).all()
    picked = [
        (m, j)
        for m, j in rows
        if (include_hidden or (not m.knockouts and float(m.estimated_fit_score) >= threshold))
        and (include_dismissed or not m.dismissed)
        and (not new_only or m.shown_to_user_at is None)
    ]
    picked.sort(key=lambda r: _sort_key(*r))
    return {
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "threshold": threshold,
        "total": len(picked),
        "matches": [_match_out(m, j, db) for m, j in picked[:limit]],
    }


@router.get("/jobs/{job_id}/match")
def get_match(job_id: uuid.UUID, user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(Job, job_id)
    m = (
        db.scalars(
            select(JobMatch).where(
                JobMatch.user_id == user.id,
                JobMatch.job_id == job_id,
                JobMatch.job_content_version == job.content_version,
            )
        ).first()
        if job
        else None
    )
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no match for this job yet; run POST /matches/run")
    settings, _ = settings_service.get_effective(db, user.id)
    return _match_out(m, job, db, full=True) | {"threshold": settings.preferences.min_fit_score}


@router.post("/matches/run")
def run(
    user: User = Depends(owner_only), db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)
) -> dict:
    """Re-score all current target jobs (after a profile, GitHub or Settings change). No network access."""
    result = run_matching(db, user.id)
    audit.record(
        db,
        action="matches.run",
        actor=Actor.user,
        user_id=user.id,
        entity_type="agent_runs",
        entity_id=result.run_id,
        after=result.output.get("counts"),
        request_id=ctx.request_id,
    )
    db.commit()
    if result.errors:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, result.errors[0].message)
    return result.output


@router.post("/matches/seen", status_code=status.HTTP_204_NO_CONTENT)
def mark_seen(body: SeenIn, user: User = Depends(owner_only), db: Session = Depends(get_db)) -> None:
    """Mark matches as shown so an unchanged job is never presented as new again."""
    now = datetime.now(UTC)
    for m in db.scalars(select(JobMatch).where(JobMatch.user_id == user.id, JobMatch.id.in_(body.match_ids))):
        m.shown_to_user_at = m.shown_to_user_at or now
    db.commit()


@router.post("/matches/{match_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss(
    match_id: uuid.UUID,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> None:
    m = db.get(JobMatch, match_id)
    if m is None or m.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "match not found")
    m.dismissed = True
    audit.record(
        db,
        action="matches.dismiss",
        actor=Actor.user,
        user_id=user.id,
        entity_type="job_matches",
        entity_id=m.id,
        request_id=ctx.request_id,
    )
    db.commit()
