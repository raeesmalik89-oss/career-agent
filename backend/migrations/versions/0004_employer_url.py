"""jobs.employer_url: the employer's own posting or application page, set by the user

Scans never overwrite it (source links from aggregators such as Jooble live in url / application_url).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.add_column(sa.Column("employer_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as b:
        b.drop_column("employer_url")
