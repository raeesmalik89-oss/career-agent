"""resume intelligence: fact keys, review status, certificate documents, skill display names

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW = sa.Enum(
    "pending", "verified", "rejected", name="review_status", native_enum=False, create_constraint=True, length=32
)


def upgrade() -> None:
    with op.batch_alter_table("profile_facts") as b:
        b.add_column(sa.Column("fact_key", sa.String(200), nullable=False, server_default=""))
        b.add_column(sa.Column("review_status", REVIEW, nullable=False, server_default="pending"))
        b.drop_column("verified_by_user")
        b.create_unique_constraint(op.f("uq_profile_facts_user_id"), ["user_id", "fact_type", "fact_key"])

    with op.batch_alter_table("resume_versions") as b:
        b.add_column(sa.Column("original_filename", sa.String(300), nullable=True))
        b.drop_constraint(op.f("ck_resume_versions_resume_kind"), type_="check")
        b.create_check_constraint("resume_kind", "kind IN ('source', 'tailored', 'certificate')")

    with op.batch_alter_table("skills") as b:
        b.add_column(sa.Column("display_name", sa.String(100), nullable=False, server_default=""))
        b.add_column(sa.Column("outdated_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("skills") as b:
        b.drop_column("outdated_reason")
        b.drop_column("display_name")

    with op.batch_alter_table("resume_versions") as b:
        b.drop_constraint(op.f("ck_resume_versions_resume_kind"), type_="check")
        b.create_check_constraint("resume_kind", "kind IN ('source', 'tailored')")
        b.drop_column("original_filename")

    with op.batch_alter_table("profile_facts") as b:
        b.drop_constraint(op.f("uq_profile_facts_user_id"), type_="unique")
        b.drop_constraint(op.f("ck_profile_facts_review_status"), type_="check")
        b.drop_column("review_status")
        b.add_column(sa.Column("verified_by_user", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.drop_column("fact_key")
