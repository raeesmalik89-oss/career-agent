"""multi-user: a 'member' role and invitations

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("owner", "viewer", "system")
NEW = ("owner", "member", "viewer", "system")


def _role_enum(values: tuple[str, ...], name: str = "role") -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _set_roles(values: tuple[str, ...], previous: tuple[str, ...]) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # batch mode rebuilds the table; the CHECK constraint follows the column type
        with op.batch_alter_table("users") as b:
            b.alter_column(
                "role", existing_type=_role_enum(previous), type_=_role_enum(values), existing_nullable=False
            )
    else:
        op.drop_constraint(op.f("ck_users_role"), "users", type_="check")
        allowed = ", ".join(f"'{v}'" for v in values)
        op.create_check_constraint(op.f("ck_users_role"), "users", sa.text(f"role IN ({allowed})"))


def upgrade() -> None:
    _set_roles(NEW, OLD)
    op.create_table(
        "invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("role", _role_enum(NEW, "invite_role"), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_invites_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], name=op.f("fk_invites_used_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invites")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invites_token_hash")),
    )


def downgrade() -> None:
    op.drop_table("invites")
    op.execute("UPDATE users SET role = 'viewer', is_active = false WHERE role = 'member'")
    _set_roles(OLD, NEW)
