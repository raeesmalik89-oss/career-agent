import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum
from app.db.enums import Role
from app.db.types import JSONType


def user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"), nullable=False, default=Role.viewer)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Encrypted with the master key (see app.core.crypto); never stored in plaintext.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    oauth_provider: Mapped[str | None] = mapped_column(String(50))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(IdMixin, TimestampMixin, Base):
    """One row per refresh-token family. The token itself is only stored as a SHA-256 hash."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = user_fk()
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_hash: Mapped[str | None] = mapped_column(String(64))


class Secret(IdMixin, TimestampMixin, Base):
    """Envelope-encrypted third-party tokens (GitHub PAT, Jooble key, SMTP, Telegram...)."""

    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)


class SettingsVersion(IdMixin, TimestampMixin, Base):
    """Immutable history of user settings; the newest row is the active configuration."""

    __tablename__ = "settings_versions"

    user_id: Mapped[uuid.UUID] = user_fk()
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    preferences: Mapped[dict] = mapped_column(JSONType, nullable=False)
    scoring_weights: Mapped[dict] = mapped_column(JSONType, nullable=False)
    policy: Mapped[dict] = mapped_column(JSONType, nullable=False)
    schedules: Mapped[dict] = mapped_column(JSONType, nullable=False)
    notifications: Mapped[dict | None] = mapped_column(JSONType)  # added in 0005; older rows use defaults

    __table_args__ = (UniqueConstraint("user_id", "version"),)
