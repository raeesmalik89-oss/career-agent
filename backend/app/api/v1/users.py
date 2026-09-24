"""Multi-user: invite-only sign-up and user administration.

Accounts are created only from an invitation the administrator makes. Invite tokens are random 256-bit values
shown once; only their SHA-256 is stored, they expire, and each can be used once. Every member's data (CV, facts,
matches, applications, practice, settings, keys) is scoped to their own user id by every query in the API.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.v1.auth import MIN_PASSWORD, TokenOut, _issue, check_password_strength
from app.core.metrics import AUTH_EVENTS
from app.core.ratelimit import RateLimiter
from app.core.security import hash_password, sha256_hex
from app.db.enums import Actor, Role
from app.db.models import Application, AuthSession, Invite, ProfileFact, User
from app.db.session import get_db
from app.deps import RequestCtx, admin_only, request_ctx
from app.schemas.settings import Preferences, UserSettings
from app.services import audit, settings_service

router = APIRouter(tags=["users"])
signup_limiter = RateLimiter(10)  # per IP per minute, for invite checks and sign-ups
INVITABLE = (Role.member, Role.viewer)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def member_defaults() -> UserSettings:
    """Neutral starting settings for a new person (the administrator's own defaults describe the administrator)."""
    return UserSettings(
        preferences=Preferences(cities=[], domain_experience={}, preferred_domains=[], tech_experience_years=0)
    )


# ---- administration --------------------------------------------------------------------------------------------


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role = Role.member
    email: EmailStr | None = None
    note: str | None = Field(None, max_length=200)
    days: int = Field(7, ge=1, le=30)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool | None = None
    role: Role | None = None


def _invite_out(i: Invite, now: datetime) -> dict:
    state = "used" if i.used_at else "revoked" if i.revoked_at else "expired" if _aware(i.expires_at) <= now else "open"
    return {
        "id": str(i.id),
        "role": i.role.value,
        "email": i.email,
        "note": i.note,
        "state": state,
        "created_at": _aware(i.created_at),
        "expires_at": _aware(i.expires_at),
        "used_at": _aware(i.used_at),
    }


@router.get("/admin/users")
def list_users(admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    last = dict(
        list(
            db.execute(
                select(AuthSession.user_id, func.max(AuthSession.created_at)).group_by(AuthSession.user_id)
            ).tuples()
        )
    )
    facts = dict(list(db.execute(select(ProfileFact.user_id, func.count()).group_by(ProfileFact.user_id)).tuples()))
    apps = dict(list(db.execute(select(Application.user_id, func.count()).group_by(Application.user_id)).tuples()))
    users = db.scalars(select(User).where(User.role != Role.system).order_by(User.created_at)).all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role": u.role.value,
            "is_active": u.is_active,
            "totp_enabled": u.totp_enabled,
            "created_at": _aware(u.created_at),
            "last_active": _aware(last.get(u.id)),
            "facts": facts.get(u.id, 0),
            "applications": apps.get(u.id, 0),
            "is_you": u.id == admin.id,
        }
        for u in users
    ]


@router.patch("/admin/users/{user_id}")
def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:
    u = db.get(User, user_id)
    if u is None or u.role == Role.system:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    if u.id == admin.id or u.role == Role.owner:
        raise HTTPException(status.HTTP_409_CONFLICT, "administrator accounts cannot be changed here")
    if body.role is not None and body.role not in INVITABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "role must be member or viewer")
    before = {"is_active": u.is_active, "role": u.role.value}
    if body.role is not None:
        u.role = body.role
    if body.is_active is not None:
        u.is_active = body.is_active
        if not body.is_active:  # signed out everywhere at once
            db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
    audit.record(db, action="admin.user_update", actor=Actor.user, user_id=admin.id, entity_type="users",
                 entity_id=u.id, before=before, after={"is_active": u.is_active, "role": u.role.value},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    return {"id": str(u.id), "is_active": u.is_active, "role": u.role.value}


@router.get("/admin/invites")
def list_invites(admin: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[dict]:
    now = datetime.now(UTC)
    return [_invite_out(i, now) for i in db.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(100))]


@router.post("/admin/invites", status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteIn, admin: User = Depends(admin_only), db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> dict:  # fmt: skip
    if body.role not in INVITABLE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invite a member or a viewer")
    if body.email and db.scalars(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "a user with that email already exists")
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    inv = Invite(
        id=uuid.uuid4(), token_hash=sha256_hex(token), role=body.role, email=body.email.lower() if body.email else None,
        note=body.note, created_by=admin.id, expires_at=now + timedelta(days=body.days),
    )  # fmt: skip
    db.add(inv)
    audit.record(db, action="admin.invite_create", actor=Actor.user, user_id=admin.id, entity_type="invites",
                 entity_id=inv.id, after={"role": body.role.value, "email": inv.email, "days": body.days},
                 request_id=ctx.request_id)  # fmt: skip
    db.commit()
    # the token is shown once, here; it cannot be recovered later
    return {**_invite_out(inv, now), "token": token, "path": f"/signup?token={token}"}


@router.delete("/admin/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(
    invite_id: uuid.UUID, admin: User = Depends(admin_only), db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
) -> None:  # fmt: skip
    inv = db.get(Invite, invite_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invite not found")
    if inv.used_at is None and inv.revoked_at is None:
        inv.revoked_at = datetime.now(UTC)
        audit.record(db, action="admin.invite_revoke", actor=Actor.user, user_id=admin.id, entity_type="invites",
                     entity_id=inv.id, request_id=ctx.request_id)  # fmt: skip
        db.commit()


# ---- public: invitation check and sign-up ----------------------------------------------------------------------


class SignupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)
    display_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)


def _limit(ctx: RequestCtx) -> None:
    if not signup_limiter.hit(ctx.ip_hash or "unknown"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts; try again in a minute")


def _usable_invite(db: Session, token: str) -> Invite:
    inv = db.scalars(select(Invite).where(Invite.token_hash == sha256_hex(token))).first()
    now = datetime.now(UTC)
    if inv is None or inv.used_at or inv.revoked_at or _aware(inv.expires_at) <= now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this invitation link is not valid (used, expired or revoked)")
    return inv


@router.get("/auth/invite")
def check_invite(token: str, db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)) -> dict:
    _limit(ctx)
    inv = _usable_invite(db, token)
    return {"role": inv.role.value, "email": inv.email, "expires_at": _aware(inv.expires_at)}


@router.post("/auth/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, response: Response, db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)):
    _limit(ctx)
    inv = _usable_invite(db, body.token)
    email = body.email.lower()
    if inv.email and inv.email != email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "this invitation is for a different email address")
    if db.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "an account with that email already exists; sign in instead")
    check_password_strength(email, body.password)
    user = User(id=uuid.uuid4(), email=email, display_name=body.display_name.strip(), role=inv.role,
                password_hash=hash_password(body.password))  # fmt: skip
    db.add(user)
    db.flush()
    settings_service.save(db, user.id, member_defaults(), actor=Actor.system)
    inv.used_at, inv.used_by = datetime.now(UTC), user.id
    audit.record(db, action="auth.signup", actor=Actor.user, user_id=user.id, entity_type="invites", entity_id=inv.id,
                 after={"role": inv.role.value}, request_id=ctx.request_id, ip_hash=ctx.ip_hash)  # fmt: skip
    out = _issue(db, response, user, ctx)
    db.commit()
    AUTH_EVENTS.labels("signup").inc()
    return out
