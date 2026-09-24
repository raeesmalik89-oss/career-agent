import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.metrics import RATE_LIMITED
from app.core.ratelimit import RateLimiter
from app.core.security import decode_access_token, sha256_hex
from app.db.enums import Role
from app.db.models import AuthSession, User
from app.db.session import get_db

ACCESS_COOKIE = "ca_access"
REFRESH_COOKIE = "ca_refresh"


@dataclass
class RequestCtx:
    request_id: str
    ip_hash: str | None
    user_agent: str | None


def request_ctx(request: Request) -> RequestCtx:
    ip = request.client.host if request.client else None
    return RequestCtx(
        request_id=getattr(request.state, "request_id", ""),
        ip_hash=sha256_hex(ip) if ip else None,
        user_agent=(request.headers.get("user-agent") or "")[:300] or None,
    )


def _token_from(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(ACCESS_COOKIE)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    token = _token_from(request)
    if not token:
        raise unauthorized
    try:
        claims = decode_access_token(token)
        user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    session = db.get(AuthSession, session_id)
    if session is None or session.revoked_at is not None or session.user_id != user_id:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    request.state.session_id = session_id
    return user


def require_role(*roles: Role) -> Callable[[User], User]:
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return dep


# Every query is scoped to the signed-in user, so "owner" here means "the owner of the data being changed":
# the administrator or a member, each only ever touching their own rows.
WRITER_ROLES = (Role.owner, Role.member)
owner_only = require_role(*WRITER_ROLES)
# Functions that affect everyone: job sources, users and invites, system health and backups.
admin_only = require_role(Role.owner)
any_user = require_role(Role.owner, Role.member, Role.viewer)

LIMITERS: dict[str, RateLimiter] = {}


def rate_limit(name: str, per_minute: int) -> Callable[..., None]:
    """Per-user limit for expensive or sensitive actions (scans, syncs, uploads, password changes)."""
    limiter = LIMITERS.setdefault(name, RateLimiter(per_minute))

    def dep(user: User = Depends(current_user)) -> None:
        key = str(user.id)
        if not limiter.hit(key):
            RATE_LIMITED.labels(name).inc()
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"too many requests ({name}); try again shortly",
                headers={"Retry-After": str(limiter.retry_after(key))},
            )

    return dep
