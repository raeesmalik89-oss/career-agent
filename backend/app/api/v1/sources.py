from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import Actor
from app.db.models import JobSource, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.services import audit

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    kind: str
    base_url: str | None
    read_allowed: bool
    auto_apply_allowed: bool
    tos_url: str | None
    tos_notes: str | None
    tos_reviewed_at: date | None
    rate_limit_per_min: int
    enabled: bool


class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    auto_apply_allowed: bool | None = None
    rate_limit_per_min: int | None = Field(None, ge=1, le=120)
    tos_reviewed: bool | None = None


@router.get("", response_model=list[SourceOut])
def list_sources(_: User = Depends(any_user), db: Session = Depends(get_db)):
    return db.scalars(select(JobSource).order_by(JobSource.key)).all()


@router.patch("/{key}", response_model=SourceOut)
def patch_source(
    key: str,
    body: SourcePatch,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    src = db.scalars(select(JobSource).where(JobSource.key == key)).first()
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown source")
    before = SourceOut.model_validate(src).model_dump(mode="json")

    if body.enabled and not src.read_allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "source is not permitted for reading")
    if body.auto_apply_allowed:
        if src.config.get("auto_apply_forbidden"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "this platform's terms prohibit automated applying"
            )
        if src.tos_reviewed_at is None and not body.tos_reviewed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "review the source's terms of service first (set tos_reviewed=true)",
            )
    if body.tos_reviewed:
        src.tos_reviewed_at = date.today()
    for field in ("enabled", "auto_apply_allowed", "rate_limit_per_min"):
        value = getattr(body, field)
        if value is not None:
            setattr(src, field, value)

    after = SourceOut.model_validate(src).model_dump(mode="json")
    audit.record(
        db,
        action="source.update",
        actor=Actor.user,
        user_id=user.id,
        entity_type="job_sources",
        entity_id=src.id,
        before={k: v for k, v in before.items() if after[k] != v},
        after={k: v for k, v in after.items() if before[k] != v},
        request_id=ctx.request_id,
    )
    db.commit()
    return src
