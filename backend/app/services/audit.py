import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.enums import Actor
from app.db.models import AuditLog

_REDACT = {"password", "password_hash", "token", "secret", "totp_secret_enc", "ciphertext", "refresh_token"}


def _redact(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return {k: ("[REDACTED]" if k in _REDACT else v) for k, v in data.items()}


def record(
    db: Session,
    *,
    action: str,
    actor: Actor,
    user_id: uuid.UUID | None = None,
    actor_detail: str | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
) -> AuditLog:
    """Append an audit entry. Caller owns the transaction so the entry commits atomically with the change."""
    entry = AuditLog(
        user_id=user_id,
        actor=actor,
        actor_detail=actor_detail,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_redact(before),
        after=_redact(after),
        reason=reason,
        request_id=request_id,
        ip_hash=ip_hash,
    )
    db.add(entry)
    return entry
