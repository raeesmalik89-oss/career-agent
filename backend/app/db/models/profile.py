import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum
from app.db.enums import Confidence, FactType, FileFormat, ResumeKind, SkillCategory, SkillLevel, SourceType
from app.db.models.identity import user_fk
from app.db.types import Embedding, JSONType


class ResumeProfile(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_profiles"

    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    contacts: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    links: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ResumeVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_versions"

    user_id: Mapped[uuid.UUID] = user_fk()
    profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("resume_profiles.id", ondelete="CASCADE"))
    kind: Mapped[ResumeKind] = mapped_column(str_enum(ResumeKind, "resume_kind"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="SET NULL"))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    file_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    format: Mapped[FileFormat] = mapped_column(str_enum(FileFormat, "file_format"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parsed: Mapped[dict | None] = mapped_column(JSONType)
    created_by_agent_run: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="SET NULL")
    )

    __table_args__ = (UniqueConstraint("user_id", "sha256"),)


class ProfileFact(IdMixin, TimestampMixin, Base):
    """The anti-hallucination anchor: every claim about the user must cite one of these rows."""

    __tablename__ = "profile_facts"

    user_id: Mapped[uuid.UUID] = user_fk()
    fact_type: Mapped[FactType] = mapped_column(str_enum(FactType, "fact_type"), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    source_type: Mapped[SourceType] = mapped_column(str_enum(SourceType, "source_type"), nullable=False)
    # {resume_version_id, page, char_span} | {repo, path, sha} | {entered_by, at}
    source_ref: Mapped[dict] = mapped_column(JSONType, nullable=False)
    verified_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[Confidence] = mapped_column(str_enum(Confidence, "confidence"), nullable=False)


class Skill(IdMixin, TimestampMixin, Base):
    __tablename__ = "skills"

    canonical_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    category: Mapped[SkillCategory] = mapped_column(str_enum(SkillCategory, "skill_category"), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    adjacent: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("skills.id", ondelete="SET NULL"))
    embedding: Mapped[list | None] = mapped_column(Embedding())


class UserSkill(IdMixin, TimestampMixin, Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "skill_id"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    skill_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[SkillLevel] = mapped_column(str_enum(SkillLevel, "skill_level"), nullable=False)
    evidence_fact_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    github_evidence_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    last_used_date: Mapped[date | None] = mapped_column(Date)
    is_outdated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
