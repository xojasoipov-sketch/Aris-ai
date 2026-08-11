"""agent jadvali (Bo'lim 3, A-02)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-11 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("division", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("tool_allowlist", zet.db.base.JSONType, nullable=False),
        sa.Column(
            "model_policy",
            zet.db.base.enum_column(zet.db.base.ModelTier),
            nullable=False,
        ),
        sa.Column(
            "permission_level",
            zet.db.base.enum_column(zet.db.base.PermissionLevel),
            nullable=False,
        ),
        sa.Column(
            "trust_level",
            zet.db.base.enum_column(zet.db.base.TrustLevel),
            nullable=False,
        ),
        sa.Column(
            "status",
            zet.db.base.enum_column(zet.db.base.AgentStatus),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("successful_runs", sa.Integer(), nullable=False),
        sa.Column("failed_runs", sa.Integer(), nullable=False),
        sa.Column("total_tool_calls_count", sa.Integer(), nullable=False),
        sa.Column("config", zet.db.base.JSONType, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent")),
        sa.UniqueConstraint("name", name=op.f("uq_agent_name")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_agent_agent_version_positive")),
        sa.CheckConstraint("max_steps >= 1", name=op.f("ck_agent_agent_max_steps_positive")),
        sa.CheckConstraint(
            "max_tool_calls >= 1", name=op.f("ck_agent_agent_max_tool_calls_positive")
        ),
        sa.CheckConstraint("timeout_s >= 10", name=op.f("ck_agent_agent_timeout_min")),
    )
    op.create_index("ix_agent_division", "agent", ["division"])
    op.create_index("ix_agent_status_name", "agent", ["status", "name"])
    op.create_index(op.f("ix_agent_status"), "agent", ["status"])
    op.create_index(op.f("ix_agent_created_at"), "agent", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_created_at"), table_name="agent")
    op.drop_index(op.f("ix_agent_status"), table_name="agent")
    op.drop_index("ix_agent_status_name", table_name="agent")
    op.drop_index("ix_agent_division", table_name="agent")
    op.drop_table("agent")
