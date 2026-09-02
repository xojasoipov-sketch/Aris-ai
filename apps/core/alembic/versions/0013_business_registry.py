"""Business/Contacts Registry — C2 (KONSOLIDATSIYA v2, tungi reja Bo'lim C)

Odamlar uchun mavjud `crm_contact` qayta ishlatiladi (o'zgarishsiz,
faqat ixtiyoriy `business_id` FK qo'shiladi); bizneslar uchun yangi,
kichik `business` jadvali qo'shiladi. Batafsil qaror va sabab:
`docs/KONSOLIDATSIYA_V2_C_PLANS.md::C2`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-13 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", zet.db.base.JSONType, nullable=False),
        sa.Column("vault_folder", sa.String(length=200), nullable=False),
        sa.Column("telegram_channel_ids", zet.db.base.JSONType, nullable=False),
        sa.Column("keywords", zet.db.base.JSONType, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
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
            name=op.f("fk_business_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business")),
    )
    op.create_index(op.f("ix_business_owner_id"), "business", ["owner_id"])
    op.create_index(op.f("ix_business_is_active"), "business", ["is_active"])
    op.create_index(op.f("ix_business_created_at"), "business", ["created_at"])
    op.create_index("ix_business_owner_name", "business", ["owner_id", "name"])

    # `crm_contact.business_id` — ixtiyoriy FK. SQLite ALTER COLUMN/ADD
    # CONSTRAINT'ni native qo'llab-quvvatlamaydi, shuning uchun
    # batch_alter_table (0012'dagi bilan bir xil naqsh).
    with op.batch_alter_table("crm_contact", schema=None) as batch_op:
        batch_op.add_column(sa.Column("business_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_crm_contact_business_id_business"),
            "business",
            ["business_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_crm_contact_business_id"), ["business_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("crm_contact", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_crm_contact_business_id"))
        batch_op.drop_constraint(
            batch_op.f("fk_crm_contact_business_id_business"), type_="foreignkey"
        )
        batch_op.drop_column("business_id")

    op.drop_index("ix_business_owner_name", table_name="business")
    op.drop_index(op.f("ix_business_created_at"), table_name="business")
    op.drop_index(op.f("ix_business_is_active"), table_name="business")
    op.drop_index(op.f("ix_business_owner_id"), table_name="business")
    op.drop_table("business")
