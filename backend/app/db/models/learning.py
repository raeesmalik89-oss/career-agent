import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, str_enum, utcnow
from app.db.enums import GapStatus, LearningKind, SkillLevel
from app.db.models.identity import user_fk
from app.db.types import Embedding, JSONType


def skill_fk(nullable: bool = False) -> Mapped:
    return mapped_column(Uuid, ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=nullable)


class SkillGap(IdMixin, TimestampMixin, Base):
    __tablename__ = "skill_gaps"
    __table_args__ = (UniqueConstraint("user_id", "report_date", "window_days", "skill_id"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[uuid.UUID] = skill_fk()
    jobs_requiring: Mapped[int] = mapped_column(Integer, nullable=False)
    frequency_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    trend_7d: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    have_level: Mapped[SkillLevel | None] = mapped_column(str_enum(SkillLevel, "skill_level"))
    gap_status: Mapped[GapStatus] = mapped_column(str_enum(GapStatus, "gap_status"), nullable=False)
    interview_importance: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)


class LearningItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "learning_items"

    user_id: Mapped[uuid.UUID] = user_fk()
    skill_id: Mapped[uuid.UUID] = skill_fk()
    kind: Mapped[LearningKind] = mapped_column(str_enum(LearningKind, "learning_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="todo", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewQuestion(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_questions"

    user_id: Mapped[uuid.UUID] = user_fk()
    pack_date: Mapped[date | None] = mapped_column(Date, index=True)
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ideal_answer: Mapped[str] = mapped_column(Text, nullable=False)
    testing_what: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    common_mistakes: Mapped[str] = mapped_column(Text, nullable=False)
    follow_up: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    related_fact_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    related_repo_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    skill_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Embedding())
    bank_id: Mapped[str | None] = mapped_column(String(120), index=True)
    key_points: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    spoken_answer: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)  # planned order within the day's pack (0006)


class InterviewSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"

    user_id: Mapped[uuid.UUID] = user_fk()
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avg_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    summary: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class InterviewAnswer(IdMixin, Base):
    __tablename__ = "interview_answers"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("interview_questions.id", ondelete="SET NULL")
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    mistakes: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    missing_concepts: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    improved_answer: Mapped[str] = mapped_column(Text, nullable=False)
    professional_version: Mapped[str] = mapped_column(Text, nullable=False)
    spoken_version: Mapped[str] = mapped_column(Text, nullable=False)
    rubric: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    bank_id: Mapped[str | None] = mapped_column(String(120), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConceptMap(IdMixin, TimestampMixin, Base):
    __tablename__ = "concept_maps"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", "version"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    skill_id: Mapped[uuid.UUID] = skill_fk()
    map_date: Mapped[date] = mapped_column(Date, nullable=False)
    tree: Mapped[dict] = mapped_column(JSONType, nullable=False)
    mermaid: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class KnowledgeEdge(IdMixin, Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (UniqueConstraint("user_id", "src_type", "src_id", "rel", "dst_type", "dst_id"),)

    user_id: Mapped[uuid.UUID] = user_fk()
    src_type: Mapped[str] = mapped_column(String(30), nullable=False)
    src_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, nullable=False)
    rel: Mapped[str] = mapped_column(String(40), nullable=False)
    dst_type: Mapped[str] = mapped_column(String(30), nullable=False)
    dst_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1.0"), nullable=False)
