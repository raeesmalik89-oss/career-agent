import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum
from app.db.enums import Confidence, EvidenceType
from app.db.models.identity import user_fk
from app.db.types import JSONType


class GithubProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "github_profiles"

    user_id: Mapped[uuid.UUID] = user_fk()
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    token_secret_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("secrets.id", ondelete="SET NULL"))
    stats: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GithubRepository(IdMixin, TimestampMixin, Base):
    __tablename__ = "github_repositories"
    __table_args__ = (UniqueConstraint("github_profile_id", "name"),)

    github_profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("github_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    languages: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    stars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    readme_summary: Mapped[str | None] = mapped_column(Text)
    structure: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    commit_stats: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    default_branch_sha: Mapped[str | None] = mapped_column(String(40))


class GithubEvidence(IdMixin, TimestampMixin, Base):
    """Proof that a skill is actually used in a repo: a concrete file/config/workflow, never a repo name."""

    __tablename__ = "github_evidence"

    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("github_repositories.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evidence_type: Mapped[EvidenceType] = mapped_column(str_enum(EvidenceType, "evidence_type"), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    strength: Mapped[Confidence] = mapped_column(str_enum(Confidence, "confidence"), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
