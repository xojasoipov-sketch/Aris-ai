"""B1 audit fix — Approval.step_position ustuni (KONSOLIDATSIYA v2)

`approval.step_id` — `step` jadvaliga FK, lekin `step` jadvali HECH
QACHON to'ldirilmaydi (Executor qadam natijasini faqat xotirada
kuzatadi). Bu ustun `step_id`ni ALMASHTIRMAYDI (kelajakda to'liq
per-step persistence qo'shilsa foydali qoladi) — shunchaki alohida,
oddiy int ustun qo'shiladi: `ApprovalRequest.step_position` bilan
to'g'ridan-to'g'ri mos, hech qanday FK'ga bog'liq emas. Natija:
restart'dan keyin "aynan qaysi reja qadami tasdiq kutayotgan edi"
ma'lumoti saqlanadi — `step` jadvali bo'sh bo'lsa ham.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approval", sa.Column("step_position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("approval", "step_position")
