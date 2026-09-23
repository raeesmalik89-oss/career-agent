"""Job Matcher agent: scores every current target job against the candidate profile and stores job_matches.

One job_matches row per (user, job, job_content_version). Re-running with a new profile or new settings updates
that row in place and keeps shown_to_user_at, so an unchanged job is never presented as new again. A material
change to the posting bumps content_version, which creates a fresh row that counts as new.
"""

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from agents.base import Agent, AgentContext, AgentResult
from agents.match_agent.profile import build_profile
from agents.match_agent.scoring import DISCLAIMER, LABEL, JobSkillView, JobView, rank_key, score_job
from agents.taxonomy import get_taxonomy
from app.db.enums import Confidence
from app.db.models import Job, JobMatch, JobSkill, Skill
from app.services import settings_service

MAX_AGE_DAYS = 45


class MatchInput(BaseModel):
    user_id: uuid.UUID
    job_ids: list[uuid.UUID] | None = None
    max_age_days: int = MAX_AGE_DAYS


def job_skill_views(db: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[JobSkillView]]:
    out: dict[uuid.UUID, list[JobSkillView]] = defaultdict(list)
    rows = db.execute(
        select(JobSkill, Skill.canonical_name, Skill.display_name)
        .outerjoin(Skill, Skill.id == JobSkill.skill_id)
        .where(JobSkill.job_id.in_(job_ids))
    ).all()
    for js, key, name in rows:
        out[js.job_id].append(JobSkillView(key, name or js.raw_text, js.requirement.value, float(js.weight)))
    return out


def job_view(job: Job, skills: list[JobSkillView]) -> JobView:
    return JobView(
        title=job.title,
        company=job.company,
        location=job.location,
        remote_type=job.remote_type.value,
        pk_eligibility=job.pk_eligibility.value,
        pk_evidence=job.pk_eligibility_evidence,
        role_family=job.role_family,
        seniority=job.seniority,
        experience_years=float(job.experience_required_years) if job.experience_required_years is not None else None,
        education=job.education_required,
        visa=job.visa_requirement,
        description=job.description,
        skills=skills,
        posted_date=job.posted_date,
        salary_known=job.salary_min is not None,
    )


class MatchingAgent(Agent[MatchInput]):
    name = "job_matcher"

    def summarize_input(self, payload: MatchInput) -> str:
        return f"jobs={'all current' if payload.job_ids is None else len(payload.job_ids)}"

    def execute(self, payload: MatchInput, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        db, user_id = ctx.db, payload.user_id
        settings, settings_version = settings_service.get_effective(db, user_id)
        taxonomy = get_taxonomy()
        profile = build_profile(db, user_id, taxonomy, settings)
        now = datetime.now(UTC)

        stmt = select(Job).where(
            Job.role_family.is_not(None),
            Job.last_seen_at >= now - timedelta(days=payload.max_age_days),
            or_(Job.closing_date.is_(None), Job.closing_date >= now.date()),
        )
        if payload.job_ids is not None:
            stmt = stmt.where(Job.id.in_(payload.job_ids))
        jobs = list(db.scalars(stmt))
        skills = job_skill_views(db, [j.id for j in jobs])
        existing = {
            (m.job_id, m.job_content_version): m
            for m in db.scalars(
                select(JobMatch).where(JobMatch.user_id == user_id, JobMatch.job_id.in_([j.id for j in jobs]))
            )
        }

        counts: Counter = Counter()
        ranked = []
        for job in jobs:
            view = job_view(job, skills.get(job.id, []))
            outcome = score_job(view, profile, settings, taxonomy)
            row = existing.get((job.id, job.content_version))
            previous = float(row.estimated_fit_score) if row else None
            if row is None:
                row = JobMatch(user_id=user_id, job_id=job.id, job_content_version=job.content_version)
                db.add(row)
                counts["created"] += 1
            else:
                counts["updated"] += 1
            row.settings_version = settings_version
            row.estimated_fit_score = Decimal(str(outcome.score))
            row.score_confidence = Confidence(outcome.confidence)
            row.breakdown = {
                "label": outcome.label(),
                "label_name": LABEL,
                "disclaimer": DISCLAIMER,
                "components": outcome.components,
                "confidence_points": outcome.confidence_points,
                "weights": settings.scoring_weights.model_dump(),
                "profile": {
                    "tech_years": profile.tech_years,
                    "tech_years_source": profile.tech_years_source,
                    "level": profile.level_index,
                },
                "previous_score": previous,
                "scored_at": now.isoformat(),
            }
            row.why_matched = outcome.why_matched
            row.why_not_matched = outcome.why_not_matched
            row.missing_skills = outcome.missing_skills
            row.partial_skills = outcome.partial_skills
            row.evidence = outcome.evidence
            row.risks = outcome.risks
            row.knockouts = outcome.knockouts
            row.recommendation = outcome.recommendation
            counts["scored"] += 1
            for k in outcome.knockouts:
                counts[f"knockout_{k['code']}"] += 1
            if outcome.knockouts:
                counts["knocked_out"] += 1
            elif outcome.qualifies:
                counts["qualifying"] += 1
                if row.shown_to_user_at is None and not row.dismissed:
                    counts["new_qualifying"] += 1
                ranked.append((rank_key(view, outcome), job, outcome))
            else:
                counts["below_threshold"] += 1
        db.flush()
        ranked.sort(key=lambda r: r[0])
        ctx.act("match_jobs", None, **{k: v for k, v in counts.items()})
        return {
            "counts": dict(counts),
            "threshold": settings.preferences.min_fit_score,
            "settings_version": settings_version,
            "profile": {"tech_years": profile.tech_years, "source": profile.tech_years_source},
            "top": [
                {
                    "job_id": str(job.id),
                    "title": job.title,
                    "company": job.company,
                    "score": o.score,
                    "confidence": o.confidence,
                    "label": o.label(),
                }
                for _, job, o in ranked[:20]
            ],
        }, None


def run_matching(
    db: Session,
    user_id: uuid.UUID,
    *,
    job_ids: list[uuid.UUID] | None = None,
    pipeline_run_id: uuid.UUID | None = None,
) -> AgentResult:
    return MatchingAgent().run(
        MatchInput(user_id=user_id, job_ids=job_ids), db, user_id=user_id, pipeline_run_id=pipeline_run_id
    )
