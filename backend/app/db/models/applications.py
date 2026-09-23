import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum, utcnow
from app.db.enums import Actor, AnswerCategory, ApplicationMode, ApplicationStatus, ValidationStatus
from app.db.models.identity import user_fk
from app.db.types import JSONType


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    # Hard duplicate guard: one application per user per canonical job.
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False)
    match_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("job_matches.id", ondelete="SET NULL"))
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus, "application_status"), index=True, nullable=False
    )
    mode: Mapped[ApplicationMode] = mapped_column(str_enum(ApplicationMode, "application_mode"), nullable=False)
    resume_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("resume_versions.id", ondelete="RESTRICT")
    )
    cover_letter_uri: Mapped[str | None] = mapped_column(String(1000))
    why_applied: Mapped[str | None] = mapped_column(Text)
    policy_decision: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    application_url: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_update: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApplicationAnswer(IdMixin, TimestampMixin, Base):
    __tablename__ = "application_answers"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[AnswerCategory] = mapped_column(str_enum(AnswerCategory, "answer_category"), nullable=False)
    cited_fact_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        str_enum(ValidationStatus, "validation_status"), nullable=False
    )
    validation_notes: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    approved_by_user_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApplicationEvent(IdMixin, Base):
    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    actor: Mapped[Actor] = mapped_column(str_enum(Actor, "actor"), nullable=False)
    screenshot_uri: Mapped[str | None] = mapped_column(String(1000))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
