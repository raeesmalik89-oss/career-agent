"""Skill-gap analysis (docs/ARCHITECTURE.md section 8), deterministic.

For the jobs in your target families that are open to you (eligible or unknown), per skill:
  frequency   % of those jobs asking for it (required counts 1, preferred 0.5)
  trend_7d    frequency among jobs first seen in the last 7 days minus the 7 days before
  status      have (strong/working evidence) / partial (only listed, medium GitHub, or an adjacent skill) / missing
  priority    100 * (0.4 frequency + 0.25 role importance + 0.2 gap severity + 0.15 interview importance)
Skill levels only ever come from evidence (resume use, GitHub); studying alone never upgrades them.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from agents.interview_agent.bank import get_bank
from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.enums import GapStatus, PkEligibility, SkillLevel
from app.db.models import (
    InterviewAnswer,
    InterviewQuestion,
    InterviewSession,
    Job,
    JobMatch,
    JobSkill,
    Skill,
    SkillGap,
)
from app.services import settings_service

WEIGHTS = {"frequency": 0.4, "role_importance": 0.25, "gap_severity": 0.2, "interview_importance": 0.15}
SEVERITY = {"missing": 1.0, "partial": 0.5, "have": 0.0}
MIN_JOBS = 2  # a skill must appear in at least this many jobs to be reported


@dataclass
class Gap:
    skill: str
    name: str
    category: str
    jobs_requiring: int
    frequency_pct: float
    required_pct: float
    trend_7d: float | None
    in_qualifying_jobs: int
    have_level: str | None
    status: str
    status_reason: str
    role_importance: float
    interview_importance: float
    priority: float
    families: list[str] = field(default_factory=list)


def _jobs(db: Session, since: datetime) -> list[Job]:
    return list(
        db.scalars(
            select(Job).where(
                Job.role_family.is_not(None),
                Job.last_seen_at >= since,
                Job.pk_eligibility != PkEligibility.ineligible,
            )
        )
    )


def _skill_mentions(db: Session, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    """job id -> {skill key: 'required' | 'preferred'} (required wins)."""
    out: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    if not job_ids:
        return out
    for js, key in db.execute(
        select(JobSkill, Skill.canonical_name)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(JobSkill.job_id.in_(job_ids))
    ):
        if out[js.job_id].get(key) != "required":
            out[js.job_id][key] = js.requirement.value
    return out


def _freq(jobs: list[Job], mentions: dict) -> dict[str, float]:
    if not jobs:
        return {}
    acc: dict[str, float] = defaultdict(float)
    for j in jobs:
        for key, req in mentions.get(j.id, {}).items():
            acc[key] += 1.0 if req == "required" else 0.5
    return {k: 100 * v / len(jobs) for k, v in acc.items()}


def _interview_weakness(db: Session, user_id: uuid.UUID) -> dict[str, float]:
    """skill key -> average recent mock-interview score for questions about it."""
    skills = {str(s.id): s.canonical_name for s in db.scalars(select(Skill))}
    scores: dict[str, list[int]] = defaultdict(list)
    since = datetime.now(UTC) - timedelta(days=30)
    for a, skill_ids in db.execute(
        select(InterviewAnswer, InterviewQuestion.skill_ids)
        .join(InterviewSession, InterviewSession.id == InterviewAnswer.session_id)
        .join(InterviewQuestion, InterviewQuestion.id == InterviewAnswer.question_id)
        .where(InterviewSession.user_id == user_id, InterviewAnswer.at >= since)
    ):
        for sid in skill_ids or []:
            if sid in skills:
                scores[skills[sid]].append(a.score)
    return {k: sum(v) / len(v) for k, v in scores.items()}


def analyse(db: Session, user_id: uuid.UUID, window_days: int = 30) -> dict:
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, user_id)
    profile = build_profile(db, user_id, taxonomy, settings)
    now = datetime.now(UTC)
    jobs = _jobs(db, now - timedelta(days=window_days))
    mentions = _skill_mentions(db, [j.id for j in jobs])
    freq = _freq(jobs, mentions)
    req_pct = {
        k: 100 * sum(1 for j in jobs if mentions.get(j.id, {}).get(k) == "required") / len(jobs) for k in freq
    } if jobs else {}  # fmt: skip

    recent = [
        j for j in jobs if j.first_seen_at.replace(tzinfo=j.first_seen_at.tzinfo or UTC) >= now - timedelta(days=7)
    ]
    prior = [
        j
        for j in jobs
        if now - timedelta(days=14)
        <= j.first_seen_at.replace(tzinfo=j.first_seen_at.tzinfo or UTC)
        < now - timedelta(days=7)
    ]
    f_recent, f_prior = _freq(recent, mentions), _freq(prior, mentions)

    threshold = settings.preferences.min_fit_score
    qualifying = {
        m.job_id
        for m in db.scalars(select(JobMatch).where(JobMatch.user_id == user_id))
        if not m.knockouts and float(m.estimated_fit_score) >= threshold
    }

    targets = set(settings.preferences.target_role_families)
    by_family: dict[str, list[Job]] = defaultdict(list)
    for j in jobs:
        by_family[j.role_family].append(j)
    fam_share = {
        fam: {k: sum(1 for j in js if k in mentions.get(j.id, {})) / len(js) for k in freq}
        for fam, js in by_family.items()
        if fam in targets and js
    }
    weakness = _interview_weakness(db, user_id)
    bank_counts: dict[str, int] = defaultdict(int)
    for q in get_bank().values():
        for s in q.skills:
            bank_counts[s] += 1

    held = {k for k, s in profile.skills.items() if s.level in ("strong", "working")}
    gaps: list[Gap] = []
    for key, f in freq.items():
        n_jobs = sum(1 for j in jobs if key in mentions.get(j.id, {}))
        if n_jobs < MIN_JOBS:
            continue
        ev = profile.skills.get(key)
        level = ev.level if ev else None
        if level in ("strong", "working"):
            status, reason = "have", f"{level} evidence"
        else:
            sdef = taxonomy.skills.get(key)
            adj = sorted({*(sdef.adjacent if sdef else ())} & held)
            adj += sorted(
                k for k in held if k in taxonomy.skills and key in taxonomy.skills[k].adjacent and k not in adj
            )
            if level == "exposure":
                status, reason = "partial", "only listed on your CV or medium GitHub evidence"
            elif adj:
                status = "partial"
                reason = "you have the adjacent skill " + ", ".join(taxonomy.skills[a].name for a in adj[:2])
            else:
                status, reason = "missing", "Evidence not found."
        families = sorted(fam for fam, share in fam_share.items() if share.get(key, 0) >= 0.2)
        role_imp = len(families) / max(len(fam_share), 1)
        weak = weakness.get(key)
        interview_imp = max(min(1.0, bank_counts.get(key, 0) / 3), 1.0 if weak is not None and weak < 70 else 0.0)
        priority = 100 * (
            WEIGHTS["frequency"] * min(1.0, f / 100)
            + WEIGHTS["role_importance"] * role_imp
            + WEIGHTS["gap_severity"] * SEVERITY[status]
            + WEIGHTS["interview_importance"] * interview_imp
        )
        trend = round(f_recent.get(key, 0) - f_prior.get(key, 0), 1) if recent and prior else None
        gaps.append(
            Gap(
                skill=key,
                name=taxonomy.skills[key].name if key in taxonomy.skills else key,
                category=taxonomy.skills[key].category if key in taxonomy.skills else "other",
                jobs_requiring=n_jobs,
                frequency_pct=round(f, 1),
                required_pct=round(req_pct.get(key, 0), 1),
                trend_7d=trend,
                in_qualifying_jobs=sum(1 for j in jobs if j.id in qualifying and key in mentions.get(j.id, {})),
                have_level=level,
                status=status,
                status_reason=reason,
                role_importance=round(role_imp, 2),
                interview_importance=round(interview_imp, 2),
                priority=round(priority, 1),
                families=families,
            )
        )
    gaps.sort(key=lambda g: (-g.priority, -g.frequency_pct, g.skill))
    return {
        "window_days": window_days,
        "jobs_analysed": len(jobs),
        "qualifying_jobs": len(qualifying),
        "weights": WEIGHTS,
        "gaps": [g.__dict__ for g in gaps],
    }


def save_report(db: Session, user_id: uuid.UUID, report: dict, day: date | None = None) -> None:
    """Persist today's report per window (replacing an earlier run of the same day)."""
    day = day or datetime.now(UTC).date()
    ids = {s.canonical_name: s.id for s in db.scalars(select(Skill))}
    db.execute(
        delete(SkillGap).where(
            SkillGap.user_id == user_id, SkillGap.report_date == day, SkillGap.window_days == report["window_days"]
        )
    )
    for g in report["gaps"]:
        if g["skill"] not in ids:
            continue
        db.add(
            SkillGap(
                user_id=user_id,
                report_date=day,
                window_days=report["window_days"],
                skill_id=ids[g["skill"]],
                jobs_requiring=g["jobs_requiring"],
                frequency_pct=Decimal(str(g["frequency_pct"])),
                trend_7d=Decimal(str(g["trend_7d"])) if g["trend_7d"] is not None else None,
                have_level=SkillLevel(g["have_level"]) if g["have_level"] else None,
                gap_status=GapStatus(g["status"]),
                interview_importance=Decimal(str(g["interview_importance"])),
                priority_score=Decimal(str(g["priority"])),
            )
        )
    db.flush()
