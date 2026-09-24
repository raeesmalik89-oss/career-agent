"""scheduler + notifications: pipeline_runs, scheduler_state, notification dedup keys, notification settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline", sa.String(40), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("steps", JSON, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_pipeline_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
        sa.UniqueConstraint("user_id", "pipeline", "scheduled_for", name=op.f("uq_pipeline_runs_user_id")),
    )
    with op.batch_alter_table("pipeline_runs") as b:
        b.create_index(op.f("ix_pipeline_runs_user_id"), ["user_id"])
        b.create_index(op.f("ix_pipeline_runs_pipeline"), ["pipeline"])

    op.create_table(
        "scheduler_state",
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_scheduler_state")),
    )

    with op.batch_alter_table("notifications") as b:
        b.add_column(sa.Column("dedup_key", sa.String(160), nullable=True))
        b.create_unique_constraint(op.f("uq_notifications_user_id"), ["user_id", "dedup_key"])
    with op.batch_alter_table("settings_versions") as b:
        b.add_column(sa.Column("notifications", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings_versions") as b:
        b.drop_column("notifications")
    with op.batch_alter_table("notifications") as b:
        b.drop_constraint(op.f("uq_notifications_user_id"), type_="unique")
        b.drop_column("dedup_key")
    op.drop_table("scheduler_state")
    with op.batch_alter_table("pipeline_runs") as b:
        b.drop_index(op.f("ix_pipeline_runs_pipeline"))
        b.drop_index(op.f("ix_pipeline_runs_user_id"))
    op.drop_table("pipeline_runs")
