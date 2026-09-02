"""HIGH #2 audit fix — Run.completed_steps + Run.plan_snapshot (KONSOLIDATSIYA v2)

`Orchestrator._run_plan()` har chaqiruvda (shu jumladan approval'dan
keyingi `resume()`) YANGI bo'sh `ExecutionContext` yaratardi — rejaning
BOSHIDAN qayta bajarardi. Idempotent bo'lmagan WRITE/EXECUTE qadam
(masalan xabar yuborish) tasdiqdan keyingi resume'da IKKINCHI marta
bajarilib qolardi. `completed_steps` DONE qadam natijalarini saqlaydi —
keyingi `execute_plan()` chaqiruvi ularni qayta bajarmasdan tiklaydi.

`plan_snapshot` — bu fix'ni TO'LIQ yopish uchun MAJBURIY topilma:
`RunRecord.plan` hech qachon hech qanday DB ustuniga yozilmagan edi,
ya'ni real restart'dan keyin `resume()` "Reja mavjud emas" bilan
darhol yiqilardi — `completed_steps` hech qachon ishlatilmas edi.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column(
            "completed_steps",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column(
        "run",
        sa.Column(
            "plan_snapshot",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("run", "plan_snapshot")
    op.drop_column("run", "completed_steps")
