"""Snapshot of the candidate's verifiable evidence, built once per matching run.

Everything here comes from profile_facts (resume/manual) and github_evidence. Rejected facts are ignored.
Nothing is inferred from preferences except as a labelled fallback when no dated experience exists.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.skill_levels import github_skill_repos
from agents.taxonomy import Taxonomy
from app.db.models import GithubRepository, ProfileFact, UserSkill
from app.db.models import Skill as SkillRow
from app.schemas.settings import SENIORITY_LEVELS, UserSettings

TECH_FIELD_RX = re.compile(
    r"\b(computer|software|engineering|information technology|(?-i:IT)\b|artificial intelligence|ai operations|"
    r"data science|cloud|cyber|computing|informatics|mathematics|physics|electronics|telecom)",
    re.I,
)
DEGREE_LEVELS = {"doctorate": 4, "master": 3, "postgraduate": 3, "bachelor": 2, "diploma": 1, "certificate": 0}
# UK RQF/EduQual Level 6 is bachelor-equivalent in level; it is still reported as a diploma, never as a degree.
LEVEL6_RX = re.compile(r"\blevel\s*6\b", re.I)
DOMAIN_SKILLS = {"aiops": "aiops", "mlops": "mlops", "healthcare_ai": "healthcare", "devsecops": "security"}


@dataclass
class SkillEvidence:
    key: str
    name: str
    level: str | None  # strong | working | exposure (user_skills), None = not held
    resume: str | None  # "applied" | "listed" | None
    gh_high: set = field(default_factory=set)  # repo ids
    gh_medium: set = field(default_factory=set)
    fact_ids: list[str] = field(default_factory=list)
    github_evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Qualification:
    fact_id: str
    name: str
    level: int
    technical: bool
    level6_diploma: bool


@dataclass
class CandidateProfile:
    user_id: uuid.UUID
    skills: dict[str, SkillEvidence]
    tech_years: float
    tech_years_source: str  # human-readable evidence for the years figure
    tech_years_fact_ids: list[str]
    training_only: bool  # all tech months come from a training programme
    level_index: int  # index into SENIORITY_LEVELS
    qualifications: list[Qualification]
    certifications: list[dict]  # {fact_id, name, issuer}
    domains: dict[str, str]  # domain -> evidence
    repos: dict[str, GithubRepository]  # str(repo id) -> row
    pending_fact_ids: set[str]

    def has(self, key: str) -> bool:
        return key in self.skills and self.skills[key].level is not None


def _month(value: str | None, end: bool) -> date | None:
    if not value:
        return None
    if re.fullmatch(r"(?i)present|current|now", value.strip()):
        today = datetime.now(UTC).date()
        return date(today.year, today.month, 1)
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?", value.strip())
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2) or (12 if end else 1)), 1)


def merged_months(periods: list[tuple[date, date]]) -> int:
    """Months covered by possibly overlapping periods (inclusive of both end months)."""
    months: set[tuple[int, int]] = set()
    for start, end in periods:
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            months.add((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return len(months)


def level_for_years(years: float) -> int:
    """Map verified years to a seniority index (entry < 1y, junior 1-3y, mid 3-5y, senior 5-8y, staff 8y+)."""
    for limit, level in ((1, "entry"), (3, "junior"), (5, "mid"), (8, "senior")):
        if years < limit:
            return SENIORITY_LEVELS.index(level)
    return SENIORITY_LEVELS.index("staff")


def build_profile(db: Session, user_id: uuid.UUID, taxonomy: Taxonomy, settings: UserSettings) -> CandidateProfile:
    facts = [
        f
        for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id))
        if f.review_status.value != "rejected"
    ]
    names = {s.id: (s.canonical_name, s.display_name) for s in db.scalars(select(SkillRow))}
    levels = {names[us.skill_id][0]: us for us in db.scalars(select(UserSkill).where(UserSkill.user_id == user_id))}
    claims = {f.fact_key: f for f in facts if f.fact_type.value == "skill_claim"}
    gh = github_skill_repos(db, user_id, taxonomy)

    skills: dict[str, SkillEvidence] = {}
    for key in set(levels) | set(claims) | set(gh):
        us = levels.get(key)
        if us is None and key not in claims:
            continue  # README-only / low GitHub evidence never makes a skill
        claim = claims.get(key)
        g = gh.get(key, {})
        skills[key] = SkillEvidence(
            key=key,
            name=taxonomy.skills[key].name if key in taxonomy.skills else key,
            level=us.level.value if us else None,
            resume=claim.data.get("evidence") if claim else None,
            gh_high=set(g.get("high", ())),
            gh_medium=set(g.get("medium", ())),
            fact_ids=list(us.evidence_fact_ids) if us else ([str(claim.id)] if claim else []),
            github_evidence_ids=list(us.github_evidence_ids) if us else [],
        )

    tech_periods, tech_ids, training_flags = [], [], []
    for f in facts:
        if f.fact_type.value != "experience" or f.data.get("sector", "tech") != "tech":
            continue
        start, end = _month(f.data.get("start"), False), _month(f.data.get("end"), True)
        if start and end and start <= end:
            tech_periods.append((start, end))
            tech_ids.append(str(f.id))
            training_flags.append(bool(f.data.get("is_training")))
    months = merged_months(tech_periods)
    if months:
        tech_years = round(months / 12, 2)
        entries = "entry" if len(tech_ids) == 1 else "entries"
        source = f"{months} months from {len(tech_ids)} dated technology experience {entries}"
        if all(training_flags):
            source += " (a training programme)"
    else:
        tech_years = settings.preferences.tech_experience_years
        source = f"no dated technology experience found; using your Settings value ({tech_years} years)"

    quals = []
    for f in facts:
        if f.fact_type.value != "education":
            continue
        kind = f.fact_key.split("|")[-1]
        name = f.data.get("qualification") or ""
        quals.append(
            Qualification(
                fact_id=str(f.id),
                name=name,
                level=DEGREE_LEVELS.get(kind, 0),
                technical=bool(TECH_FIELD_RX.search(name)),
                level6_diploma=kind == "diploma" and bool(LEVEL6_RX.search(name)),
            )
        )
    certs = [
        {"fact_id": str(f.id), "name": f.data.get("name") or "", "issuer": f.data.get("issuer")}
        for f in facts
        if f.fact_type.value == "certification"
    ]

    domains: dict[str, str] = {}
    for f in facts:
        if f.fact_type.value == "experience" and f.data.get("sector") not in (None, "tech") and f.data.get("months"):
            domains.setdefault(f.data["sector"], f"experience: {f.data.get('title')}")
    for key, domain in DOMAIN_SKILLS.items():
        if key in skills and skills[key].level in ("strong", "working"):
            domains.setdefault(domain, f"{skills[key].name} ({skills[key].level})")

    repo_ids = {r for s in skills.values() for r in (*s.gh_high, *s.gh_medium)}
    repos = {str(r.id): r for r in db.scalars(select(GithubRepository).where(GithubRepository.id.in_(repo_ids)))}
    for s in skills.values():  # normalise ids to str for lookups
        s.gh_high = {str(r) for r in s.gh_high}
        s.gh_medium = {str(r) for r in s.gh_medium}

    return CandidateProfile(
        user_id=user_id,
        skills=skills,
        tech_years=tech_years,
        tech_years_source=source,
        tech_years_fact_ids=tech_ids,
        training_only=bool(training_flags) and all(training_flags),
        level_index=level_for_years(tech_years),
        qualifications=quals,
        certifications=certs,
        domains=domains,
        repos=repos,
        pending_fact_ids={str(f.id) for f in facts if f.review_status.value == "pending"},
    )
