"""interview_questions.position: the planned order of a daily pack

Without it the order came from the database, which PostgreSQL does not guarantee (a reload could shuffle the pack).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("interview_questions") as b:
        b.add_column(sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("interview_questions") as b:
        b.drop_column("position")
