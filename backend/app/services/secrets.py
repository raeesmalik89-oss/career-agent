import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.db.models import Secret


def get_secret(db: Session, user_id: uuid.UUID, name: str) -> str | None:
    """Decrypted value of one of the user's stored secrets (see SECRET_NAMES), or None if it was never set."""
    row = db.scalars(select(Secret).where(Secret.user_id == user_id, Secret.name == name)).first()
    return crypto.clean_secret(crypto.decrypt(row.ciphertext, name.encode())) if row else None


def has_secret(db: Session, user_id: uuid.UUID, name: str) -> bool:
    return db.scalars(select(Secret.id).where(Secret.user_id == user_id, Secret.name == name)).first() is not None
