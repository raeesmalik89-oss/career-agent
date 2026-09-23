from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import Actor
from app.db.models import SettingsVersion, User
from app.db.session import get_db
from app.deps import RequestCtx, any_user, owner_only, request_ctx
from app.schemas.settings import UserSettings, UserSettingsOut
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsHistoryItem(BaseModel):
    version: int
    created_at: str


@router.get("", response_model=UserSettingsOut)
def get_settings_(user: User = Depends(any_user), db: Session = Depends(get_db)):
    s, version = settings_service.get_effective(db, user.id)
    return UserSettingsOut(**s.model_dump(), version=version)


@router.put("", response_model=UserSettingsOut)
def put_settings(
    body: UserSettings,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    row = settings_service.save(db, user.id, body, actor=Actor.user, request_id=ctx.request_id)
    db.commit()
    return UserSettingsOut(**body.model_dump(), version=row.version)


@router.get("/history", response_model=list[SettingsHistoryItem])
def history(user: User = Depends(any_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(SettingsVersion).where(SettingsVersion.user_id == user.id).order_by(SettingsVersion.version.desc())
    )
    return [SettingsHistoryItem(version=r.version, created_at=r.created_at.isoformat()) for r in rows]
