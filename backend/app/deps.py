import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

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


owner_only = require_role(Role.owner)
any_user = require_role(Role.owner, Role.viewer)
