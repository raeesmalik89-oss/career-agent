from datetime import UTC, datetime, timedelta

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import crypto
from app.core.ratelimit import RateLimiter
from app.core.security import create_access_token, new_refresh_token, sha256_hex, verify_password
from app.db.enums import Actor
from app.db.models import AuthSession, User
from app.db.session import get_db
from app.deps import ACCESS_COOKIE, REFRESH_COOKIE, RequestCtx, current_user, owner_only, request_ctx
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])

login_limiter = RateLimiter(get_settings().login_rate_limit_per_minute)
MAX_FAILED_LOGINS = 10
LOCKOUT = timedelta(minutes=15)
_TOTP_AAD = b"totp"


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(None, pattern=r"^\d{6}$")


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class MeOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    totp_enabled: bool
    timezone: str


class TotpSetupOut(BaseModel):
    provisioning_uri: str


class TotpVerifyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _issue(db: Session, response: Response, user: User, ctx: RequestCtx) -> TokenOut:
    s = get_settings()
    refresh, refresh_hash = new_refresh_token()
    session = AuthSession(
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
        user_agent=ctx.user_agent,
        ip_hash=ctx.ip_hash,
    )
    db.add(session)
    db.flush()
    access = create_access_token(user.id, user.role.value, session.id)
    common = {"httponly": True, "secure": s.cookie_secure, "samesite": "strict"}
    response.set_cookie(ACCESS_COOKIE, access, max_age=s.access_token_minutes * 60, path="/", **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=s.refresh_token_days * 86400, path="/api/v1/auth", **common)
    return TokenOut(access_token=access, expires_in=s.access_token_minutes * 60)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)):
    email = body.email.lower()
    if not login_limiter.hit(f"{ctx.ip_hash}:{email}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts; try again later")

    user = db.scalars(select(User).where(User.email == email)).first()
    now = datetime.now(UTC)
    if user and user.locked_until and _as_utc(user.locked_until) > now:
        raise HTTPException(status.HTTP_423_LOCKED, "account temporarily locked")

    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
                user.failed_logins = 0
            audit.record(
                db,
                action="auth.login_failed",
                actor=Actor.user,
                user_id=user.id,
                request_id=ctx.request_id,
                ip_hash=ctx.ip_hash,
            )
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if user.totp_enabled:
        if not body.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "totp_required")
        secret = crypto.decrypt(user.totp_secret_enc, _TOTP_AAD + user.id.bytes)
        if not pyotp.TOTP(secret).verify(body.totp_code, valid_window=1):
            audit.record(
                db,
                action="auth.totp_failed",
                actor=Actor.user,
                user_id=user.id,
                request_id=ctx.request_id,
                ip_hash=ctx.ip_hash,
            )
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    user.failed_logins = 0
    user.locked_until = None
    out = _issue(db, response, user, ctx)
    audit.record(
        db, action="auth.login", actor=Actor.user, user_id=user.id, request_id=ctx.request_id, ip_hash=ctx.ip_hash
    )
    db.commit()
    return out


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request, response: Response, db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)
):
    token = request.cookies.get(REFRESH_COOKIE)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    if not token:
        raise unauthorized
    session = db.scalars(select(AuthSession).where(AuthSession.refresh_token_hash == sha256_hex(token))).first()
    if session is None:
        raise unauthorized
    now = datetime.now(UTC)
    if session.revoked_at is not None:
        # A rotated token was replayed: assume theft and revoke every session of this user.
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == session.user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        audit.record(
            db,
            action="auth.refresh_reuse_detected",
            actor=Actor.system,
            user_id=session.user_id,
            request_id=ctx.request_id,
            ip_hash=ctx.ip_hash,
        )
        db.commit()
        raise unauthorized
    if _as_utc(session.expires_at) <= now:
        raise unauthorized
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise unauthorized
    session.revoked_at = now
    out = _issue(db, response, user, ctx)
    db.commit()
    return out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    session = db.get(AuthSession, request.state.session_id)
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
    audit.record(db, action="auth.logout", actor=Actor.user, user_id=user.id, request_id=ctx.request_id)
    db.commit()
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        totp_enabled=user.totp_enabled,
        timezone=user.timezone,
    )


@router.post("/totp/setup", response_model=TotpSetupOut)
def totp_setup(user: User = Depends(owner_only), db: Session = Depends(get_db), ctx: RequestCtx = Depends(request_ctx)):
    if user.totp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP already enabled")
    secret = pyotp.random_base32()
    user.totp_secret_enc = crypto.encrypt(secret, _TOTP_AAD + user.id.bytes)
    audit.record(db, action="auth.totp_setup_started", actor=Actor.user, user_id=user.id, request_id=ctx.request_id)
    db.commit()
    return TotpSetupOut(provisioning_uri=pyotp.TOTP(secret).provisioning_uri(user.email, "Career Agent"))


@router.post("/totp/verify", status_code=status.HTTP_204_NO_CONTENT)
def totp_verify(
    body: TotpVerifyIn,
    user: User = Depends(owner_only),
    db: Session = Depends(get_db),
    ctx: RequestCtx = Depends(request_ctx),
):
    if user.totp_secret_enc is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "call /auth/totp/setup first")
    secret = crypto.decrypt(user.totp_secret_enc, _TOTP_AAD + user.id.bytes)
    if not pyotp.TOTP(secret).verify(body.code, valid_window=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid code")
    user.totp_enabled = True
    audit.record(db, action="auth.totp_enabled", actor=Actor.user, user_id=user.id, request_id=ctx.request_id)
    db.commit()
