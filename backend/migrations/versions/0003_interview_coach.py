"""interview coach: question-bank identity, scoring key points, spoken answers, rubric breakdown

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("interview_questions") as b:
        # Stable identity across packs (bank entry id, or "project:<fact id>:<kind>") for spaced repetition.
        b.add_column(sa.Column("bank_id", sa.String(120), nullable=True))
        b.add_column(sa.Column("key_points", JSON, nullable=False, server_default="[]"))
        b.add_column(sa.Column("spoken_answer", sa.Text(), nullable=True))
        b.create_index(op.f("ix_interview_questions_bank_id"), ["bank_id"])
    with op.batch_alter_table("interview_answers") as b:
        b.add_column(sa.Column("rubric", JSON, nullable=False, server_default="{}"))
        b.add_column(sa.Column("bank_id", sa.String(120), nullable=True))
        b.create_index(op.f("ix_interview_answers_bank_id"), ["bank_id"])


def downgrade() -> None:
    with op.batch_alter_table("interview_answers") as b:
        b.drop_index(op.f("ix_interview_answers_bank_id"))
        b.drop_column("bank_id")
        b.drop_column("rubric")
    with op.batch_alter_table("interview_questions") as b:
        b.drop_index(op.f("ix_interview_questions_bank_id"))
        b.drop_column("spoken_answer")
        b.drop_column("key_points")
        b.drop_column("bank_id")
