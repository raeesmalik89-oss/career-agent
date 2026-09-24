"""Daily Interview Pack planner (deterministic): 6 sections x 10 questions.

Sections: skills your target jobs ask for, your gap skills, your own projects and CV numbers, troubleshooting
scenarios, system design and SRE, HR and behavioural. Priority combines how often target jobs ask for a skill,
spaced repetition (questions you scored under 70 in the last 14 days come back; ones you aced rest), and novelty.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from agents.interview_agent.bank import BankQuestion, get_bank
from agents.interview_agent.personal import PersonalQuestion, personal_hr_questions, project_questions
from agents.match_agent.profile import build_profile
from agents.taxonomy import get_taxonomy
from app.db.enums import PkEligibility
from app.db.models import InterviewAnswer, InterviewQuestion, InterviewSession, Job, JobSkill, Skill
from app.services import settings_service

SECTIONS = [
    ("target", "Skills your target jobs ask for"),
    ("gaps", "Gap skills to close"),
    ("projects", "Your projects and CV"),
    ("scenarios", "Troubleshooting scenarios"),
    ("design", "System design and SRE"),
    ("hr", "HR and behavioural"),
]
SECTION_TITLES = dict(SECTIONS)
PER_SECTION = 10
SRE_SKILLS = {"sre", "slo", "observability", "monitoring", "incident_management", "system_design", "chaos_engineering"}
WEAK, STRONG = 70, 85


@dataclass
class Candidate:
    bank_id: str
    q: BankQuestion | PersonalQuestion
    pools: set[str]
    priority: float


def job_skill_frequency(db: Session, days: int = 45) -> dict[str, float]:
    """Weighted share of current target jobs (open to Pakistan or unknown) that ask for each skill, 0..1."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(Skill.canonical_name, JobSkill.requirement, func.count(func.distinct(JobSkill.job_id)))
        .join(Skill, Skill.id == JobSkill.skill_id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(Job.role_family.is_not(None), Job.last_seen_at >= since, Job.pk_eligibility != PkEligibility.ineligible)
        .group_by(Skill.canonical_name, JobSkill.requirement)
    ).all()
    raw: dict[str, float] = defaultdict(float)
    for key, req, n in rows:
        raw[key] += n * (1.0 if req.value == "required" else 0.5)
    top = max(raw.values(), default=0) or 1
    return {k: v / top for k, v in raw.items()}


def history(db: Session, user_id: uuid.UUID) -> tuple[dict[str, date], dict[str, tuple[int, datetime]]]:
    """(last pack date per bank_id, (last score, when) per bank_id)."""
    asked = dict(
        db.execute(
            select(InterviewQuestion.bank_id, func.max(InterviewQuestion.pack_date))
            .where(InterviewQuestion.user_id == user_id, InterviewQuestion.bank_id.is_not(None))
            .group_by(InterviewQuestion.bank_id)
        ).all()
    )
    scores: dict[str, tuple[int, datetime]] = {}
    for bank_id, score, at in db.execute(
        select(InterviewAnswer.bank_id, InterviewAnswer.score, InterviewAnswer.at)
        .join(InterviewSession, InterviewSession.id == InterviewAnswer.session_id)
        .where(InterviewSession.user_id == user_id, InterviewAnswer.bank_id.is_not(None))
        .order_by(InterviewAnswer.at)
    ):
        scores[bank_id] = (score, at)  # the latest answer wins
    return asked, scores


def _priority(bank_id: str, relevance: float, day: date, asked: dict, scores: dict) -> float:
    p = relevance + 0.1
    last = scores.get(bank_id)
    recent = last and (datetime.now(UTC) - last[1].replace(tzinfo=last[1].tzinfo or UTC)).days <= 14
    if recent and last[0] < WEAK:
        p += 1.0  # weak recently: bring it back
    elif recent and last[0] >= STRONG:
        p -= 0.6  # aced it: rest it
    seen = asked.get(bank_id)
    if seen is None:
        p += 0.3
    elif (day - seen).days < 30 and not (recent and last[0] < WEAK):
        p -= 0.8 + 0.02 * (30 - (day - seen).days)
    return p


def plan(db: Session, user_id: uuid.UUID, day: date) -> list[tuple[str, Candidate]]:
    taxonomy = get_taxonomy()
    settings, _ = settings_service.get_effective(db, user_id)
    profile = build_profile(db, user_id, taxonomy, settings)
    freq = job_skill_frequency(db)
    held = {k for k, s in profile.skills.items() if s.level in ("strong", "working")}
    asked, scores = history(db, user_id)

    cands: list[Candidate] = []
    for q in get_bank().values():
        skills = set(q.skills)
        rel = max((freq.get(s, 0) for s in skills), default=0.0)
        pools = set()
        if q.section == "hr":
            pools.add("hr")
        else:
            if skills & held and rel > 0:
                pools.add("target")
            if any(s not in held and freq.get(s, 0) > 0 for s in skills):
                pools.add("gaps")
            if q.section == "scenario":
                pools.add("scenarios")
            if q.section == "design" or skills & SRE_SKILLS:
                pools.add("design")
            if not pools:
                pools.add("gaps" if skills and not skills & held else "target")
        cands.append(Candidate(q.id, q, pools, _priority(q.id, rel, day, asked, scores)))
    for pq in project_questions(db, user_id, profile, taxonomy, freq):
        rel = max((freq.get(s, 0) for s in pq.skills), default=0.2)
        cands.append(Candidate(pq.bank_id, pq, {"projects"}, _priority(pq.bank_id, rel, day, asked, scores)))
    for pq in personal_hr_questions(db, user_id, profile):
        cands.append(Candidate(pq.bank_id, pq, {"hr"}, _priority(pq.bank_id, 0.8, day, asked, scores)))

    chosen: list[tuple[str, Candidate]] = []
    used: set[str] = set()
    # Scarcest sections choose first, so a question that fits several sections goes where it is needed most.
    pool_size = {s: sum(s in c.pools for c in cands) for s, _ in SECTIONS}
    for section in sorted(pool_size, key=lambda s: (pool_size[s], s)):
        pool = sorted(
            (c for c in cands if section in c.pools and c.bank_id not in used), key=lambda c: (-c.priority, c.bank_id)
        )
        for c in pool[:PER_SECTION]:
            chosen.append((section, c))
            used.add(c.bank_id)
    # Fill any section that ran short from the best remaining questions, so the pack stays at 60 when possible.
    target_total = PER_SECTION * len(SECTIONS)
    rest = sorted((c for c in cands if c.bank_id not in used), key=lambda c: (-c.priority, c.bank_id))
    counts = {s: sum(sec == s for sec, _ in chosen) for s, _ in SECTIONS}
    for c in rest[: max(0, target_total - len(chosen))]:
        section = min((s for s, _ in SECTIONS if s in c.pools), key=lambda s: counts[s], default="target")
        counts[section] += 1
        chosen.append((section, c))
    order = {s: i for i, (s, _) in enumerate(SECTIONS)}
    return sorted(chosen, key=lambda x: (order[x[0]], -x[1].priority))


def generate_pack(db: Session, user_id: uuid.UUID, day: date, *, regenerate: bool = False) -> list[InterviewQuestion]:
    existing = list(
        db.scalars(
            select(InterviewQuestion).where(InterviewQuestion.user_id == user_id, InterviewQuestion.pack_date == day)
        )
    )
    if existing and not regenerate:
        return existing
    if existing:
        db.execute(
            delete(InterviewQuestion).where(InterviewQuestion.user_id == user_id, InterviewQuestion.pack_date == day)
        )
    skills = {s.canonical_name: str(s.id) for s in db.scalars(select(Skill))}
    rows = []
    for section, c in plan(db, user_id, day):
        q = c.q
        row = InterviewQuestion(
            user_id=user_id,
            pack_date=day,
            section=section,
            bank_id=c.bank_id,
            question=q.q,
            ideal_answer=q.ideal,
            testing_what=q.tests,
            keywords=sorted({t for p in q.points for t in p.terms})[:40],
            key_points=[[p.label, *p.terms] for p in q.points],
            common_mistakes="\n".join(q.mistakes),
            follow_up=q.follow_up,
            difficulty=q.difficulty,
            spoken_answer=q.spoken,
            related_fact_ids=list(getattr(q, "fact_ids", [])),
            skill_ids=[skills[k] for k in q.skills if k in skills],
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
