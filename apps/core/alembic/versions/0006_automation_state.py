"""avtomatlashtirish holati saqlanadi (Z48.2)

`AutomationEngine` to'liq xotirada yashardi: ega TIZIM retseptini
yoqsa, u birinchi qayta ishga tushishdayoq jimgina yo'qolardi. Bu
soxta tugmadan yomonroq — bir necha kun ishlaydi, keyin sababsiz
to'xtaydi.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12 21:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("schedules", zet.db.base.JSONType, nullable=False),
        sa.Column("triggers", zet.db.base.JSONType, nullable=False),
        sa.Column("watchers", zet.db.base.JSONType, nullable=False),
        sa.Column(
            "created_at",
            zet.db.base.UTCDateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            zet.db.base.UTCDateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owner.id"],
            name=op.f("fk_automation_state_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_automation_state")),
    )
    op.create_index(
        op.f("ix_automation_state_owner_id"),
        "automation_state",
        ["owner_id"],
        unique=True,
    )
    op.create_index(op.f("ix_automation_state_created_at"), "automation_state", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_automation_state_created_at"), table_name="automation_state")
    op.drop_index(op.f("ix_automation_state_owner_id"), table_name="automation_state")
    op.drop_table("automation_state")
