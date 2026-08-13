"""HIGH #1 audit fix — Approval.mission_id + nullable run_id (KONSOLIDATSIYA v2)

`approval.run_id` NOT NULL FK'ga `run.id`ga edi. `MissionEngine.
request_approval()` mission-darajali so'rovlarda `run_id=mission.id`
berardi — bu UUID `run` jadvalida HECH QACHON bo'lmaydi (A1 audit'da
real Postgres bilan topilgan: INSERT DOIM `ForeignKeyViolationError`
bilan yiqilardi, avval faqat "graceful skip" bilan yumshatilgan edi —
approval DB'ga HECH QACHON yozilmasdi, restart'da yo'qolardi).

Bu migratsiya `run_id`ni nullable qiladi va haqiqiy `mission_id` FK
ustunini qo'shadi (`mission.id`ga) — mission-darajali so'rovlar endi
soxta emas, HAQIQIY FK bilan yoziladi. `CheckConstraint` ikkalasidan
kamida bittasi to'ldirilishini majburlaydi.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite ALTER COLUMN/ADD CONSTRAINT'ni to'g'ridan-to'g'ri qo'llab-
    # quvvatlamaydi — batch mode butun jadvalni yangi sxema bilan qayta
    # quradi (Postgres'da esa oddiy ALTER TABLE'ga tushadi).
    with op.batch_alter_table("approval", schema=None) as batch_op:
        batch_op.alter_column("run_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.add_column(sa.Column("mission_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_approval_mission_id_mission"),
            "mission",
            ["mission_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            batch_op.f("ix_approval_mission_id"), ["mission_id"], unique=False
        )
        batch_op.create_check_constraint(
            batch_op.f("ck_approval_approval_has_run_or_mission"),
            "(run_id IS NOT NULL) OR (mission_id IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("approval", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("ck_approval_approval_has_run_or_mission"), type_="check"
        )
        batch_op.drop_index(batch_op.f("ix_approval_mission_id"))
        batch_op.drop_constraint(
            batch_op.f("fk_approval_mission_id_mission"), type_="foreignkey"
        )
        batch_op.drop_column("mission_id")
        batch_op.alter_column("run_id", existing_type=sa.Uuid(), nullable=False)
