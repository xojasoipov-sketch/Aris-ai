"""savdo — mahsulot va buyurtma (Z51)

`order` — SQL zaxira so'zi, shuning uchun jadval `customer_order` deb
nomlangan (`db/models/commerce.py`dagi izohga qarang).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13 07:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base
from zet.domain.commerce import OrderStatus

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_uzs", sa.Float(), nullable=False),
        sa.Column("stock_qty", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
            ["owner_id"], ["owner.id"], name=op.f("fk_product_owner_id_owner"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
    )
    op.create_index(op.f("ix_product_owner_id"), "product", ["owner_id"])
    op.create_index("ix_product_owner_active", "product", ["owner_id", "active"])
    op.create_index(op.f("ix_product_created_at"), "product", ["created_at"])

    op.create_table(
        "customer_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("status", zet.db.base.enum_column(OrderStatus), nullable=False),
        sa.Column("items", zet.db.base.JSONType, nullable=False),
        sa.Column("total_uzs", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("shipped_notified_at", zet.db.base.UTCDateTime(), nullable=True),
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
            name=op.f("fk_customer_order_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["crm_contact.id"],
            name=op.f("fk_customer_order_contact_id_crm_contact"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_order")),
    )
    op.create_index(op.f("ix_customer_order_owner_id"), "customer_order", ["owner_id"])
    op.create_index(op.f("ix_customer_order_contact_id"), "customer_order", ["contact_id"])
    op.create_index(op.f("ix_customer_order_status"), "customer_order", ["status"])
    op.create_index("ix_order_owner_status", "customer_order", ["owner_id", "status"])
    op.create_index(op.f("ix_customer_order_created_at"), "customer_order", ["created_at"])

    op.add_column(
        "crm_contact",
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(op.f("ix_crm_contact_telegram_chat_id"), "crm_contact", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_crm_contact_telegram_chat_id"), table_name="crm_contact")
    op.drop_column("crm_contact", "telegram_chat_id")

    op.drop_index(op.f("ix_customer_order_created_at"), table_name="customer_order")
    op.drop_index("ix_order_owner_status", table_name="customer_order")
    op.drop_index(op.f("ix_customer_order_status"), table_name="customer_order")
    op.drop_index(op.f("ix_customer_order_contact_id"), table_name="customer_order")
    op.drop_index(op.f("ix_customer_order_owner_id"), table_name="customer_order")
    op.drop_table("customer_order")

    op.drop_index(op.f("ix_product_created_at"), table_name="product")
    op.drop_index("ix_product_owner_active", table_name="product")
    op.drop_index(op.f("ix_product_owner_id"), table_name="product")
    op.drop_table("product")
