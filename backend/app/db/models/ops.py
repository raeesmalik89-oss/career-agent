import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, str_enum, utcnow
from app.db.enums import Actor, Confidence, RunStatus
from app.db.models.identity import user_fk
from app.db.types import JSONType


class AgentRun(IdMixin, Base):
    """Structured envelope every agent produces (agent_name, run_id, input_summary, actions, ...)."""

    __tablename__ = "agent_runs"

    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    agent_name: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus, "run_status"), nullable=False)
    input_summary: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    output: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    confidence: Mapped[Confidence | None] = mapped_column(str_enum(Confidence, "confidence"))
    errors: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    llm_tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdMixin, Base):
    """Append-only. On PostgreSQL a trigger rejects UPDATE/DELETE (see migration 0001)."""

    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor: Mapped[Actor] = mapped_column(str_enum(Actor, "actor"), nullable=False)
    actor_detail: Mapped[str | None] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = user_fk()
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    channels: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    delivered: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DailyReport(IdMixin, Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "report_date"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONType, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
