"""GitHub Intelligence report: skill evidence map, repository quality, resume-vs-GitHub comparison."""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.skill_levels import github_skill_repos
from agents.taxonomy import Taxonomy
from app.db.models import GithubEvidence, GithubProfile, GithubRepository, ProfileFact, Skill

EVIDENCE_NOT_FOUND = "Evidence not found."
_RANK = {"high": 2, "medium": 1, "low": 0}


def _repo_score(r: GithubRepository, high_skills: int) -> float:
    s, c = r.structure or {}, r.commit_stats or {}
    readme = s.get("readme") or {}
    return round(
        high_skills
        + 3 * bool(s.get("has_tests"))
        + 3 * bool(s.get("has_ci"))
        + 2 * bool(s.get("has_docker"))
        + 2 * bool(readme.get("has_setup"))
        + 2 * bool(readme.get("has_deploy_instructions"))
        + min(c.get("active_days", 0), 15) * 0.5,
        1,
    )


def build_github_report(db: Session, user_id: uuid.UUID, taxonomy: Taxonomy) -> dict:
    profile = db.scalars(select(GithubProfile).where(GithubProfile.user_id == user_id)).first()
    if profile is None:
        return {"profile": None, "detail": "No GitHub profile analysed yet."}
    repos = list(db.scalars(select(GithubRepository).where(GithubRepository.github_profile_id == profile.id)))
    by_id = {r.id: r for r in repos}
    rows = db.execute(
        select(GithubEvidence, Skill.canonical_name)
        .join(Skill, Skill.id == GithubEvidence.skill_id)
        .where(GithubEvidence.repo_id.in_([r.id for r in repos]))
    ).all()

    # evidence map: skill -> repo -> evidence
    emap: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for ev, key in rows:
        emap[key][by_id[ev.repo_id].name].append(
            {"path": ev.path, "type": ev.evidence_type.value, "detail": ev.detail, "strength": ev.strength.value}
        )
    evidence_map = []
    for key, per_repo in emap.items():
        best = max(_RANK[e["strength"]] for items in per_repo.values() for e in items)
        high_repos = sorted(r for r, items in per_repo.items() if any(e["strength"] == "high" for e in items))
        sd = taxonomy.skills.get(key)
        evidence_map.append(
            {
                "skill": key,
                "name": sd.name if sd else key,
                "category": sd.category if sd else "other",
                "confidence": {2: "high", 1: "medium", 0: "low"}[best],
                "repos_with_high_evidence": high_repos,
                "repos": {r: sorted(items, key=lambda e: -_RANK[e["strength"]])[:4] for r, items in per_repo.items()},
            }
        )
    evidence_map.sort(key=lambda e: (-_RANK[e["confidence"]], -len(e["repos_with_high_evidence"]), e["name"]))

    # repositories
    high_count = defaultdict(set)
    for ev, key in rows:
        if ev.strength.value == "high":
            high_count[ev.repo_id].add(key)
    repo_out = []
    for r in repos:
        s = r.structure or {}
        repo_out.append(
            {
                "name": r.name,
                "url": r.url,
                "score": _repo_score(r, len(high_count[r.id])),
                "languages": list((r.languages or {}).keys())[:4],
                "summary": r.readme_summary,
                "commits": r.commit_stats,
                "files": s.get("files"),
                "has": {
                    k: s.get(k)
                    for k in (
                        "has_readme",
                        "has_tests",
                        "has_ci",
                        "has_docker",
                        "has_kubernetes",
                        "has_iac",
                        "has_license",
                    )
                },
                "readme": s.get("readme"),
                "flags": s.get("flags", []),
                "top_skills": sorted(high_count[r.id])[:12],
            }
        )
    repo_out.sort(key=lambda x: -x["score"])

    # resume vs GitHub
    gh = github_skill_repos(db, user_id, taxonomy)
    claims = {
        f.fact_key: f
        for f in db.scalars(
            select(ProfileFact).where(ProfileFact.user_id == user_id, ProfileFact.fact_type == "skill_claim")
        )
        if f.review_status.value != "rejected"
    }
    confirmed, resume_only, github_only = [], [], []
    for key, f in sorted(claims.items(), key=lambda kv: kv[1].data.get("name", "")):
        g = gh.get(key)
        if g and (g["high"] or g["medium"]):
            confirmed.append(
                {"skill": key, "name": f.data["name"], "high_repos": len(g["high"]), "medium_repos": len(g["medium"])}
            )
        else:
            resume_only.append(
                {
                    "skill": key,
                    "name": f.data["name"],
                    "resume_evidence": f.data.get("evidence"),
                    "detail": f"Claimed on resume. No code or config on GitHub uses it. {EVIDENCE_NOT_FOUND}",
                }
            )
    for key, g in gh.items():
        if key not in claims and g["high"] and key in taxonomy.skills:
            github_only.append({"skill": key, "name": taxonomy.skills[key].name, "high_repos": len(g["high"])})
    github_only.sort(key=lambda x: -x["high_repos"])

    projects = []
    for f in db.scalars(select(ProfileFact).where(ProfileFact.user_id == user_id, ProfileFact.fact_type == "project")):
        if f.data.get("github"):
            projects.append(
                {
                    "project": f.data.get("name"),
                    "fact_id": str(f.id),
                    "not_found_in_repo": [],
                    "readme_only": [],
                    **f.data["github"],
                }
            )

    recommendations: list[str] = []
    no_readme = [r["name"] for r in repo_out if not r["has"]["has_readme"] and r["files"]]
    empty = [r["name"] for r in repo_out if not r["files"]]
    machine = [r["name"] for r in repo_out if (r["commits"] or {}).get("by_machine_identity")]
    no_tests = [r["name"] for r in repo_out[:8] if not r["has"]["has_tests"]]
    envs = [r["name"] for r in repo_out if any(".env file is committed" in f for f in r["flags"])]
    if envs:
        recommendations.append(f"Committed .env file in: {', '.join(envs)}. Check for secrets and rotate any found.")
    if machine:
        recommendations.append(
            f"Commits under a server's default identity (e.g. 'Ubuntu') in: {', '.join(machine)}. "
            "Set git user.name/user.email on those machines so GitHub credits you."
        )
    for p in projects:
        if p["not_found_in_repo"]:
            names = ", ".join(taxonomy.skills[t].name for t in p["not_found_in_repo"] if t in taxonomy.skills)
            recommendations.append(
                f"Resume project '{p['project']}' claims {names}, but its repo {p['repo']} does "
                "not contain it. Add the code/config or remove the claim."
            )
    unlinked = [p["project"] for p in projects if not p.get("repo")]
    if unlinked:
        recommendations.append(
            "No public repository found for these resume projects, so their claims cannot be verified: "
            + "; ".join(unlinked)
            + ". Publish the code, put the repository URL in your resume, or link it by setting "
            "`github_repo` on the project fact."
        )
    if github_only:
        recommendations.append(
            "Proven on GitHub but missing from your resume: " + ", ".join(g["name"] for g in github_only[:10]) + "."
        )
    if no_readme:
        recommendations.append(f"No README in: {', '.join(no_readme)}.")
    if empty:
        recommendations.append(f"Empty repositories (consider deleting or archiving): {', '.join(empty)}.")
    if no_tests:
        recommendations.append(f"Top repositories without automated tests: {', '.join(no_tests)}.")
    recommendations.append("Pin these on your GitHub profile: " + ", ".join(r["name"] for r in repo_out[:6]) + ".")

    return {
        "profile": {
            "username": profile.username,
            "repositories": len(repos),
            "last_synced_at": profile.last_synced_at.isoformat() if profile.last_synced_at else None,
        },
        "repositories": repo_out,
        "evidence_map": evidence_map,
        "resume_vs_github": {"confirmed": confirmed, "resume_only": resume_only, "github_only": github_only},
        "projects": projects,
        "recommendations": recommendations,
    }
