"""Single place that turns resume facts + GitHub evidence into user_skills levels.

  strong   - high GitHub evidence (your own commits) in >= 2 repositories, and the resume also shows the skill
             applied (or >= 3 repositories on their own)
  working  - high GitHub evidence in 1 repository, or used in resume experience/projects
  exposure - only listed on the resume, or only medium GitHub evidence
A skill the user rejected is removed, whatever the evidence says.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.taxonomy import Taxonomy
from app.db.enums import SkillLevel
from app.db.models import GithubEvidence, GithubProfile, GithubRepository, ProfileFact, Skill, UserSkill


def github_skill_repos(db: Session, user_id: uuid.UUID, taxonomy: Taxonomy) -> dict[str, dict[str, set]]:
    """skill -> {"high": {repo_id}, "medium": {...}, "low": {...}, "evidence_ids": {...}}, including implied skills."""
    rows = db.execute(
        select(GithubEvidence, Skill.canonical_name)
        .join(Skill, Skill.id == GithubEvidence.skill_id)
        .join(GithubRepository, GithubRepository.id == GithubEvidence.repo_id)
        .join(GithubProfile, GithubProfile.id == GithubRepository.github_profile_id)
        .where(GithubProfile.user_id == user_id)
    ).all()
    out: dict[str, dict[str, set]] = defaultdict(
        lambda: {"high": set(), "medium": set(), "low": set(), "evidence_ids": set()}
    )
    for ev, key in rows:
        keys = {key} | (taxonomy.implied(key) if key in taxonomy.skills and ev.strength.value != "low" else set())
        for k in keys:
            out[k][ev.strength.value].add(ev.repo_id)
            out[k]["evidence_ids"].add(str(ev.id))
    return out


def level_for(resume_evidence: str | None, gh: dict[str, set] | None) -> SkillLevel | None:
    high = len(gh["high"]) if gh else 0
    medium = len(gh["medium"]) if gh else 0
    applied = resume_evidence == "applied"
    if high >= 3 or (high >= 2 and applied):
        return SkillLevel.strong
    if high >= 1 or applied:
        return SkillLevel.working
    if resume_evidence == "listed" or medium >= 1:
        return SkillLevel.exposure
    return None  # README mentions alone never create a skill


def recompute_user_skills(db: Session, user_id: uuid.UUID, taxonomy: Taxonomy) -> dict[str, SkillLevel]:
    db.flush()
    skills = {s.canonical_name: s for s in db.scalars(select(Skill))}
    facts = list(db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id)))
    claims = {f.fact_key: f for f in facts if f.fact_type.value == "skill_claim"}
    rejected = {k for k, f in claims.items() if f.review_status.value == "rejected"}
    used_in: dict[str, list[str]] = defaultdict(list)
    for f in facts:
        if f.fact_type.value in ("experience", "project") and f.review_status.value != "rejected":
            for key in f.data.get("technologies", []):
                used_in[key].append(str(f.id))
    gh = github_skill_repos(db, user_id, taxonomy)
    current = {us.skill_id: us for us in db.scalars(select(UserSkill).where(UserSkill.user_id == user_id))}

    result: dict[str, SkillLevel] = {}
    for key in set(claims) | set(gh):
        skill = skills.get(key)
        if skill is None:
            continue
        us = current.pop(skill.id, None)
        claim = claims.get(key)
        level = None if key in rejected else level_for(claim.data.get("evidence") if claim else None, gh.get(key))
        if level is None:
            if us is not None:
                db.delete(us)
            continue
        if us is None:
            us = UserSkill(user_id=user_id, skill_id=skill.id, level=level)
            db.add(us)
        us.level = level
        us.evidence_fact_ids = ([str(claim.id)] if claim else []) + used_in.get(key, [])
        us.github_evidence_ids = sorted(gh[key]["evidence_ids"]) if key in gh else []
        us.is_outdated = bool(taxonomy.skills[key].outdated) if key in taxonomy.skills else False
        result[key] = level
    for stale in current.values():  # evidence disappeared entirely
        db.delete(stale)
    db.flush()
    return result
