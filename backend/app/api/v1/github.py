from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.github_agent.agent import GithubAnalyzerAgent, GithubAnalyzerInput
from agents.github_agent.client import NAME_RX
from agents.github_agent.report import build_github_report
from agents.taxonomy import get_taxonomy
from app.db.enums import Actor
from app.db.models import GithubProfile, GithubRepository, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.services import audit

router = APIRouter(prefix="/github", tags=["github"])


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(pattern=NAME_RX.pattern)
    include_forks: bool = False
    only: list[str] | None = Field(None, max_length=200)
    extra_identities: list[str] = Field(default_factory=list, max_length=10)


class SyncOut(BaseModel):
    run_id: str
    ok: bool
    errors: list[dict]
    repositories: int


@router.post("/sync", response_model=SyncOut)
def sync(
    body: SyncIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    """Clone (read-only, partial) and analyse the user's public repositories. Runs synchronously for now."""
    result = GithubAnalyzerAgent().run(GithubAnalyzerInput(user_id=user.id, **body.model_dump()), db, user_id=user.id)
    audit.record(
        db,
        action="github.sync",
        actor=Actor.user,
        user_id=user.id,
        entity_type="agent_runs",
        entity_id=result.run_id,
        after={"username": body.username, "ok": result.ok},
        request_id=ctx.request_id,
    )
    db.commit()
    repos = sum(1 for a in result.actions if a.type == "analyzed_repository")
    return SyncOut(
        run_id=str(result.run_id), ok=result.ok, errors=[e.model_dump() for e in result.errors], repositories=repos
    )


@router.get("/repos")
def repos(user: User = Depends(any_user), db: Session = Depends(get_db)) -> list[dict]:
    profile = db.scalars(select(GithubProfile).where(GithubProfile.user_id == user.id)).first()
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no GitHub profile analysed yet")
    rows = db.scalars(select(GithubRepository).where(GithubRepository.github_profile_id == profile.id))
    return [
        {
            "name": r.name,
            "url": r.url,
            "languages": r.languages,
            "summary": r.readme_summary,
            "structure": r.structure,
            "commits": r.commit_stats,
            "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
        }
        for r in rows
    ]


@router.get("/intelligence")
def intelligence(user: User = Depends(any_user), db: Session = Depends(get_db)) -> dict:
    """Evidence map, repository quality, resume-vs-GitHub comparison and recommendations."""
    return build_github_report(db, user.id, get_taxonomy())
