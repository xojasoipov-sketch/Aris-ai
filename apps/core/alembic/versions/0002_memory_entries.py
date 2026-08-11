"""memory_entries jadvali

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-11 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import zet.db.base

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_entries",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=Text()), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column(
            "embedding",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=Text()), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trust_level", sa.String(length=32), nullable=False),
        sa.Column(
            "expires_at",
            zet.db.base.UTCDateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            zet.db.base.UTCDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            zet.db.base.UTCDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owner.id"],
            name=op.f("fk_memory_entries_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_entries")),
    )
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_memory_entries_created_at"),
            ["created_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_memory_entries_expires_at"),
            ["expires_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_memory_entries_layer"),
            ["layer"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_memory_entries_owner_id"),
            ["owner_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_memory_layer_owner",
            ["layer", "owner_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_memory_layer_owner")
        batch_op.drop_index(batch_op.f("ix_memory_entries_owner_id"))
        batch_op.drop_index(batch_op.f("ix_memory_entries_layer"))
        batch_op.drop_index(batch_op.f("ix_memory_entries_expires_at"))
        batch_op.drop_index(batch_op.f("ix_memory_entries_created_at"))

    op.drop_table("memory_entries")
