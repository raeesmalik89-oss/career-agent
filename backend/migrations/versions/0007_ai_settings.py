"""settings_versions.ai: optional AI rewriting (provider, model, local Ollama address)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("settings_versions") as b:
        b.add_column(sa.Column("ai", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings_versions") as b:
        b.drop_column("ai")
