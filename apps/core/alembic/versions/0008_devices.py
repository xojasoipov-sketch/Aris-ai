"""qurilmalar va capability tokenlar (Bo'lim 8, A-06)

`DeviceRegistry` ilgari faqat xotirada yashardi — restart'dan keyin
barcha qurilma va tokenlar yo'qolardi. Bu jadval ularni doimiy
saqlaydi. Token bazada faqat SHA-256 xeshi sifatida, xom qiymatda
emas (yaratishda bir marta qaytariladi).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base
from zet.devices.registry import DeviceType

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "device_type",
            zet.db.base.enum_column(DeviceType),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False),
        sa.Column("online", sa.Boolean(), nullable=False),
        sa.Column("last_seen", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("meta", zet.db.base.JSONType, nullable=False),
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
            name=op.f("fk_device_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device")),
    )
    op.create_index(op.f("ix_device_owner_id"), "device", ["owner_id"])
    op.create_index(op.f("ix_device_device_type"), "device", ["device_type"])
    op.create_index(op.f("ix_device_online"), "device", ["online"])
    op.create_index("ix_device_owner_type", "device", ["owner_id", "device_type"])
    op.create_index(op.f("ix_device_created_at"), "device", ["created_at"])

    op.create_table(
        "capability_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("capabilities", zet.db.base.JSONType, nullable=False),
        sa.Column("expires_at", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("revoked_at", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
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
            ["device_id"],
            ["device.id"],
            name=op.f("fk_capability_token_device_id_device"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_token")),
        # `token_hash` `unique=True` VA `index=True` bilan e'lon qilingan
        # (`db/models/device.py`). SQLAlchemy autogenerate buni bitta
        # UNIQUE indeks sifatida ko'radi — alohida `UniqueConstraint`
        # ORTIQCHA edi (drift topilardi). Yagona indeks (unique=True) yetarli.
    )
    op.create_index(op.f("ix_capability_token_device_id"), "capability_token", ["device_id"])
    op.create_index(
        op.f("ix_capability_token_token_hash"),
        "capability_token",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_capability_token_device_revoked",
        "capability_token",
        ["device_id", "revoked_at"],
    )
    op.create_index(op.f("ix_capability_token_created_at"), "capability_token", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_capability_token_created_at"), table_name="capability_token")
    op.drop_index("ix_capability_token_device_revoked", table_name="capability_token")
    op.drop_index(op.f("ix_capability_token_token_hash"), table_name="capability_token")
    op.drop_index(op.f("ix_capability_token_device_id"), table_name="capability_token")
    op.drop_table("capability_token")

    op.drop_index(op.f("ix_device_created_at"), table_name="device")
    op.drop_index("ix_device_owner_type", table_name="device")
    op.drop_index(op.f("ix_device_online"), table_name="device")
    op.drop_index(op.f("ix_device_device_type"), table_name="device")
    op.drop_index(op.f("ix_device_owner_id"), table_name="device")
    op.drop_table("device")
