"""GitHub Analyzer Agent: public repositories -> file-level skill evidence, project verification, report."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from agents.base import Agent, AgentContext
from agents.github_agent import client
from agents.github_agent.detectors import DETECTABLE
from agents.github_agent.report import build_github_report
from agents.github_agent.scanner import analyze_repo, downgrade_for_authorship
from agents.resume_agent.agent import sync_taxonomy
from agents.resume_agent.merge import norm, tokens
from agents.skill_levels import recompute_user_skills
from agents.taxonomy import Taxonomy, get_taxonomy
from app.db.enums import Confidence, EvidenceType
from app.db.models import GithubEvidence, GithubProfile, GithubRepository, ProfileFact, ResumeProfile
from app.services import storage


class GithubAnalyzerInput(BaseModel):
    user_id: uuid.UUID
    username: str = Field(min_length=1, max_length=39)
    include_forks: bool = False
    only: list[str] | None = None  # restrict to these repository names
    extra_identities: list[str] = Field(default_factory=list)  # other commit emails/names you use
    clone_url_override: dict[str, str] | None = None  # tests only: repo name -> local path


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


_GENERIC_REPO_WORDS = {"lab", "labs", "demo", "app", "project", "repo"}
# Words too common in project/repo names to identify a project on their own.
_NON_DISTINCTIVE = {
    "pipeline",
    "deployment",
    "api",
    "service",
    "services",
    "platform",
    "system",
    "cicd",
    "ci",
    "cd",
    "docker",
    "k8s",
    "kubernetes",
    "setup",
    "test",
    "web",
    "webapp",
    "flask",
    "secure",
    "microservice",
    "microservices",
    "cloud",
    "aws",
    "azure",
    "devops",
    "ml",
    "mlops",
    "aiops",
    "ai",
    "real",
    "time",
    "end",
    "to",
    "data",
    "monitoring",
    "automation",
    "infrastructure",
    "security",
    "stack",
    "model",
    "prediction",
}


def repo_tokens(name: str) -> set[str]:
    """'CardioCare-AIOps' -> {cardio, care, cardiocare, aiops}; generic words like 'lab' are ignored."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).replace("-", " ").replace("_", " ")
    return (tokens(spaced) | tokens(name.replace("-", " ").replace("_", " "))) - _GENERIC_REPO_WORDS


def match_project(project: dict, repos: list[str], username: str) -> str | None:
    """Link a resume project to a repository: user's explicit link, then a github URL, then name similarity."""
    if project.get("github_repo") in repos:
        return project["github_repo"]
    text = " ".join([project.get("name", ""), *project.get("context", []), *project.get("highlights", [])]).lower()
    for r in repos:
        if f"github.com/{username.lower()}/{r.lower()}" in text:
            return r
    ptoks = tokens(project.get("name"))
    best, best_score = None, 0.0
    for r in repos:
        if norm(r.replace("-", " ").replace("_", " ")) == norm(project.get("name")):
            return r
        rt = repo_tokens(r)
        if not rt:
            continue
        shared = rt & ptoks
        if not shared - _NON_DISTINCTIVE:
            continue  # e.g. "deployment-pipeline-lab" must not match any project with those two words
        score = len(shared) / len(rt)
        if score > best_score and len(shared) >= 2:
            best, best_score = r, score
    return best if best_score >= 0.66 else None


class GithubAnalyzerAgent(Agent[GithubAnalyzerInput]):
    name = "github_analyzer"

    def __init__(self, taxonomy: Taxonomy | None = None):
        self.taxonomy = taxonomy or get_taxonomy()

    def summarize_input(self, payload: GithubAnalyzerInput) -> str:
        return f"user={payload.username}; forks={payload.include_forks}; only={len(payload.only or [])}"

    def execute(self, payload: GithubAnalyzerInput, ctx: AgentContext) -> tuple[dict[str, Any], Confidence | None]:
        db, user_id = ctx.db, payload.user_id
        username = client.validate_username(payload.username)
        skills = sync_taxonomy(db, self.taxonomy)

        try:
            repos = client.list_repos(username)
        except client.GitHubError as exc:
            ctx.error("github_api", str(exc), retryable=True)
            return {}, None
        if payload.only:
            repos = [r for r in repos if r.name in set(payload.only)]
        ctx.act("listed_repositories", target=username, count=len(repos))

        profile = db.scalars(select(GithubProfile).where(GithubProfile.username == username)).first()
        if profile is None:
            profile = GithubProfile(user_id=user_id, username=username)
            db.add(profile)
            db.flush()
        elif profile.user_id != user_id:
            ctx.error("github_profile_owned", "this GitHub username is linked to another user")
            return {}, None

        identities = {username.lower(), *(i.lower() for i in payload.extra_identities)}
        resume = db.scalars(select(ResumeProfile).where(ResumeProfile.user_id == user_id)).first()
        if resume:
            identities.add(resume.name.lower())
            if resume.contacts.get("email"):
                identities.add(resume.contacts["email"].lower())

        clone_root = storage.root() / "github" / username
        repo_skills: dict[str, set[str]] = {}
        repo_readme_skills: dict[str, set[str]] = {}
        for info in repos:
            if info.fork and not payload.include_forks:
                ctx.act("skip_fork", target=info.name)
                continue
            url = (payload.clone_url_override or {}).get(info.name, info.clone_url)
            try:
                path = client.sync_clone(url, clone_root / f"{info.name}.git")
                ra = analyze_repo(path, info.name, identities, self.taxonomy)
            except client.GitHubError as exc:
                ctx.error("repo_failed", f"{info.name}: {exc}", retryable=True)
                continue

            row = db.scalars(
                select(GithubRepository).where(
                    GithubRepository.github_profile_id == profile.id, GithubRepository.name == info.name
                )
            ).first()
            if row is None:
                row = GithubRepository(github_profile_id=profile.id, name=info.name, url=info.url)
                db.add(row)
            row.url, row.is_fork, row.stars = info.url, info.fork, info.stars
            row.pushed_at = _parse_dt(info.pushed_at)
            row.languages = ra.languages
            row.readme_summary = ra.readme_summary
            row.structure = {
                **ra.structure,
                "flags": ra.flags,
                "description": info.description,
                "archived": info.archived,
            }
            row.commit_stats = ra.commit_stats
            row.default_branch_sha = ra.head_sha
            db.flush()

            db.execute(delete(GithubEvidence).where(GithubEvidence.repo_id == row.id))
            seen: set[tuple] = set()
            kept = 0
            for ev in downgrade_for_authorship(ra):
                sig = (ev.skill, ev.path, ev.detail)
                if ev.skill not in skills or sig in seen:
                    continue
                seen.add(sig)
                db.add(
                    GithubEvidence(
                        repo_id=row.id,
                        skill_id=skills[ev.skill].id,
                        evidence_type=EvidenceType(ev.evidence_type),
                        path=ev.path[:1000],
                        detail=ev.detail,
                        strength=Confidence(ev.strength),
                        commit_sha=ra.head_sha,
                    )
                )
                kept += 1
            repo_skills[info.name] = {e.skill for e in ra.evidence if e.strength != "low"}
            repo_readme_skills[info.name] = {e.skill for e in ra.evidence if e.strength == "low"}
            ctx.act("analyzed_repository", target=info.name, evidence=kept, flags=len(ra.flags))

        profile.last_synced_at = datetime.now(UTC)
        profile.stats = {"repositories": len(repo_skills), "listed": len(repos)}
        self._verify_projects(db, ctx, user_id, username, repo_skills, repo_readme_skills)
        recompute_user_skills(db, user_id, self.taxonomy)
        report = build_github_report(db, user_id, self.taxonomy)
        return report, Confidence.high if not ctx.errors else Confidence.medium

    def _verify_projects(
        self,
        db,
        ctx: AgentContext,
        user_id: uuid.UUID,
        username: str,
        repo_skills: dict[str, set[str]],
        repo_readme_skills: dict[str, set[str]],
    ) -> None:
        """Compare each resume project's claimed technologies with what its repository actually contains."""
        projects = db.scalars(
            select(ProfileFact).where(ProfileFact.user_id == user_id, ProfileFact.fact_type == "project")
        )
        for fact in projects:
            repo = match_project(fact.data, list(repo_skills), username)
            if repo is None:
                data = dict(fact.data)
                data["github"] = {"repo": None, "note": "No matching public repository found; claims unverified."}
                fact.data = data
                continue
            found = set(repo_skills[repo])
            for k in list(found):
                found |= self.taxonomy.implied(k) if k in self.taxonomy.skills else set()
            claimed = fact.data.get("technologies", [])
            checkable = [t for t in claimed if t in DETECTABLE]
            readme = repo_readme_skills.get(repo, set())
            data = dict(fact.data)
            data["github"] = {
                "repo": repo,
                "url": f"https://github.com/{username}/{repo}",
                "verified": sorted(t for t in checkable if t in found),
                # Described in the README but not visible in code/config (e.g. "deployed on EC2" without IaC).
                "readme_only": sorted(t for t in claimed if t not in found and t in readme),
                "not_found_in_repo": sorted(t for t in checkable if t not in found and t not in readme),
                "not_checkable": sorted(t for t in claimed if t not in DETECTABLE),
                "checked_at": datetime.now(UTC).isoformat(),
            }
            fact.data = data
            sources = [s for s in fact.source_ref.get("sources", []) if s.get("repo") != repo]
            fact.source_ref = {"sources": [*sources, {"repo": repo, "label": f"github:{repo}"}]}
            ctx.act(
                "verified_project",
                target=fact.data.get("name"),
                repo=repo,
                not_found=len(data["github"]["not_found_in_repo"]),
            )
