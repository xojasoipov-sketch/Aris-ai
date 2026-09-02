"""Mission strategiya qatlami jadvallari (Bo'lim 2, §2.2)

Mission = strategiya (nima qilish, qanday tekshirish, nimani eslash);
Run = bajarish. Bir Mission 1..N Run tug'diradi (asosiy + recovery
qayta urinishlari). `mission_run` — join jadvali; Runlar first-class
qoladi (mavjud Orchestrator ularni Mission'siz ham ishlata oladi).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-13 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base
from zet.domain.enums import MissionStatus, RiskLevel

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("outcome_criteria", sa.Text(), nullable=False),
        sa.Column("context", zet.db.base.JSONType, nullable=False),
        sa.Column("constraints", zet.db.base.JSONType, nullable=False),
        sa.Column("tasks", zet.db.base.JSONType, nullable=False),
        sa.Column("agents", zet.db.base.JSONType, nullable=False),
        sa.Column("tools", zet.db.base.JSONType, nullable=False),
        sa.Column("capabilities", zet.db.base.JSONType, nullable=False),
        sa.Column("permissions_required", zet.db.base.JSONType, nullable=False),
        sa.Column(
            "risk_level",
            zet.db.base.enum_column(RiskLevel),
            nullable=False,
        ),
        sa.Column("approval_requirements", zet.db.base.JSONType, nullable=False),
        sa.Column("deadline", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("verification_rules", zet.db.base.JSONType, nullable=False),
        sa.Column("memory_updates", zet.db.base.JSONType, nullable=False),
        sa.Column(
            "status",
            zet.db.base.enum_column(MissionStatus),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("pending_approval_id", sa.Uuid(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
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
            name=op.f("fk_mission_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mission")),
    )
    op.create_index(op.f("ix_mission_owner_id"), "mission", ["owner_id"])
    op.create_index(op.f("ix_mission_status"), "mission", ["status"])
    op.create_index(op.f("ix_mission_risk_level"), "mission", ["risk_level"])
    op.create_index(op.f("ix_mission_deadline"), "mission", ["deadline"])
    op.create_index(op.f("ix_mission_priority"), "mission", ["priority"])
    op.create_index("ix_mission_owner_status", "mission", ["owner_id", "status"])
    op.create_index("ix_mission_owner_deadline", "mission", ["owner_id", "deadline"])
    op.create_index("ix_mission_owner_priority", "mission", ["owner_id", "priority"])
    op.create_index(op.f("ix_mission_created_at"), "mission", ["created_at"])

    op.create_table(
        "mission_run",
        sa.Column("mission_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
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
            ["mission_id"],
            ["mission.id"],
            name=op.f("fk_mission_run_mission_id_mission"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["run.id"],
            name=op.f("fk_mission_run_run_id_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mission_id", "run_id", name=op.f("pk_mission_run")),
    )
    op.create_index(op.f("ix_mission_run_created_at"), "mission_run", ["created_at"])
    op.create_index("ix_mission_run_run_id", "mission_run", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_mission_run_run_id", table_name="mission_run")
    op.drop_index(op.f("ix_mission_run_created_at"), table_name="mission_run")
    op.drop_table("mission_run")

    op.drop_index(op.f("ix_mission_created_at"), table_name="mission")
    op.drop_index("ix_mission_owner_priority", table_name="mission")
    op.drop_index("ix_mission_owner_deadline", table_name="mission")
    op.drop_index("ix_mission_owner_status", table_name="mission")
    op.drop_index(op.f("ix_mission_priority"), table_name="mission")
    op.drop_index(op.f("ix_mission_deadline"), table_name="mission")
    op.drop_index(op.f("ix_mission_risk_level"), table_name="mission")
    op.drop_index(op.f("ix_mission_status"), table_name="mission")
    op.drop_index(op.f("ix_mission_owner_id"), table_name="mission")
    op.drop_table("mission")
