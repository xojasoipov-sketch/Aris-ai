"""Scheduled fire ledger — JB-11 duplicate-scheduled-execution prevention.

`scheduled_fire(rule_id, minute_key)` bitta UNIQUE constraint — daemon
fire qilishdan oldin shu qatorni yozishga urinadi; unique violation =
boshqa process/worker allaqachon shu daqiqada shu qoidani da'vo qilgan.
Batafsil qaror: `core/mission_recovery.py` va `automation/fire_ledger.py`
docstring'lari.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-16 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_fire",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(length=32), nullable=False),
        sa.Column("minute_key", sa.String(length=20), nullable=False),
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
            name=op.f("fk_scheduled_fire_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_fire")),
        sa.UniqueConstraint(
            "rule_id", "minute_key", name=op.f("uq_scheduled_fire_rule_id_minute_key")
        ),
    )
    op.create_index(op.f("ix_scheduled_fire_owner_id"), "scheduled_fire", ["owner_id"])
    op.create_index(op.f("ix_scheduled_fire_rule_id"), "scheduled_fire", ["rule_id"])
    # `TimestampMixin.created_at` — `index=True` (db/base.py) — boshqa
    # jadvallardagi bilan bir xil (masalan `ix_business_created_at`).
    op.create_index(
        op.f("ix_scheduled_fire_created_at"), "scheduled_fire", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduled_fire_created_at"), table_name="scheduled_fire")
    op.drop_index(op.f("ix_scheduled_fire_rule_id"), table_name="scheduled_fire")
    op.drop_index(op.f("ix_scheduled_fire_owner_id"), table_name="scheduled_fire")
    op.drop_table("scheduled_fire")
