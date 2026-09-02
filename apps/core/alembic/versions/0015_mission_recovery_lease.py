"""Mission recovery lease — JB-11 multi-worker restart-recovery ownership.

`mission.claimed_by`/`claim_expires_at` — DB-native "compare-and-set"
lease, atomik `UPDATE ... WHERE claimed_by IS NULL OR claim_expires_at
< now()`. In-process `asyncio.Lock` (`core/mission_recovery.py`, JB-10)
faqat bitta process ichida ishlaydi; bu ikki ustun ko'p worker/pod
holatida ham bitta mission ustida ikkita drayvchi parallel ishlamasligini
kafolatlaydi.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-16 10:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite ALTER COLUMN/ADD CONSTRAINT'ni native qo'llab-quvvatlamaydi
    # — batch_alter_table (0012/0013'dagi bilan bir xil naqsh).
    with op.batch_alter_table("mission", schema=None) as batch_op:
        batch_op.add_column(sa.Column("claimed_by", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("claim_expires_at", zet.db.base.UTCDateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("mission", schema=None) as batch_op:
        batch_op.drop_column("claim_expires_at")
        batch_op.drop_column("claimed_by")
