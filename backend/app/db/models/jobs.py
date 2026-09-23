import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum, utcnow
from app.db.enums import Confidence, PkEligibility, RemoteType, Requirement, SourceKind
from app.db.models.identity import user_fk
from app.db.types import Embedding, JSONType


class JobSource(IdMixin, TimestampMixin, Base):
    """Source registry: what we may read and whether automated applying is permitted (ToS-reviewed)."""

    __tablename__ = "job_sources"

    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[SourceKind] = mapped_column(str_enum(SourceKind, "source_kind"), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    read_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_apply_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tos_url: Mapped[str | None] = mapped_column(String(500))
    tos_notes: Mapped[str | None] = mapped_column(Text)
    tos_reviewed_at: Mapped[date | None] = mapped_column(Date)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class JobRaw(IdMixin, Base):
    __tablename__ = "jobs_raw"
    __table_args__ = (UniqueConstraint("source_id", "external_id", "payload_hash"),)

    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("job_sources.id", ondelete="CASCADE"), index=True, nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str] = mapped_column(String(300), nullable=False)
    company_normalized: Mapped[str] = mapped_column(String(300), index=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    remote_type: Mapped[RemoteType] = mapped_column(
        str_enum(RemoteType, "remote_type"), default=RemoteType.unknown, nullable=False
    )
    employment_type: Mapped[str | None] = mapped_column(String(50))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_source_text: Mapped[str | None] = mapped_column(Text)
    experience_required_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    education_required: Mapped[str | None] = mapped_column(Text)
    visa_requirement: Mapped[str | None] = mapped_column(Text)
    pk_eligibility: Mapped[PkEligibility] = mapped_column(
        str_enum(PkEligibility, "pk_eligibility"), default=PkEligibility.unknown, nullable=False
    )
    pk_eligibility_evidence: Mapped[str | None] = mapped_column(Text)
    role_family: Mapped[str | None] = mapped_column(String(50), index=True)
    seniority: Mapped[str | None] = mapped_column(String(30))
    posted_date: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    application_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    description_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Embedding())


class JobSourceLink(Base):
    """Dedup provenance: every raw posting that was merged into a canonical job."""

    __tablename__ = "job_source_links"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    raw_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs_raw.id", ondelete="CASCADE"), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_sources.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(1000), nullable=False)


class JobSkill(IdMixin, Base):
    __tablename__ = "job_skills"

    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("skills.id", ondelete="SET NULL"))
    raw_text: Mapped[str] = mapped_column(String(300), nullable=False)
    requirement: Mapped[Requirement] = mapped_column(str_enum(Requirement, "requirement"), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1.0"), nullable=False)


class JobMatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_matches"
    __table_args__ = (UniqueConstraint("user_id", "job_id", "job_content_version"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    job_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    settings_version: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_fit_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), index=True, nullable=False)
    score_confidence: Mapped[Confidence] = mapped_column(str_enum(Confidence, "confidence"), nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSONType, nullable=False)
    why_matched: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    why_not_matched: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    missing_skills: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    partial_skills: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    risks: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    knockouts: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    shown_to_user_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
