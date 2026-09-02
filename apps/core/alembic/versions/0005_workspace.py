"""ish maydoni jadvallari — loyiha, vazifa, kalendar (Z46)

`/projects`, `/tasks`, `/calendar` sahifalari ortida hech narsa yo'q
edi — uchalasi ham frontend fayli ichidagi qotirilgan massivdan
chizilardi.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-12 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base
from zet.domain.workspace import ProjectStatus, TaskPriority, TaskStatus

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", zet.db.base.enum_column(ProjectStatus), nullable=False),
        sa.Column("color", sa.String(length=16), nullable=False),
        sa.Column("due_at", zet.db.base.UTCDateTime(), nullable=True),
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
            name=op.f("fk_project_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
    )
    op.create_index(op.f("ix_project_owner_id"), "project", ["owner_id"])
    op.create_index(op.f("ix_project_status"), "project", ["status"])
    op.create_index("ix_project_owner_status", "project", ["owner_id", "status"])
    op.create_index(op.f("ix_project_created_at"), "project", ["created_at"])

    op.create_table(
        "task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", zet.db.base.enum_column(TaskStatus), nullable=False),
        sa.Column("priority", zet.db.base.enum_column(TaskPriority), nullable=False),
        sa.Column("due_at", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("done_at", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("assigned_agent", sa.String(length=64), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), nullable=True),
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
            name=op.f("fk_task_owner_id_owner"),
            ondelete="CASCADE",
        ),
        # SET NULL — loyiha o'chirilsa vazifalar yo'qolmaydi.
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_task_project_id_project"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["run.id"],
            name=op.f("fk_task_source_run_id_run"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
    )
    op.create_index(op.f("ix_task_owner_id"), "task", ["owner_id"])
    op.create_index(op.f("ix_task_project_id"), "task", ["project_id"])
    op.create_index(op.f("ix_task_status"), "task", ["status"])
    op.create_index(op.f("ix_task_priority"), "task", ["priority"])
    op.create_index(op.f("ix_task_due_at"), "task", ["due_at"])
    op.create_index("ix_task_owner_status", "task", ["owner_id", "status"])
    op.create_index("ix_task_owner_due", "task", ["owner_id", "due_at"])
    op.create_index(op.f("ix_task_created_at"), "task", ["created_at"])

    op.create_table(
        "calendar_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("starts_at", zet.db.base.UTCDateTime(), nullable=False),
        sa.Column("ends_at", zet.db.base.UTCDateTime(), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
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
            name=op.f("fk_calendar_event_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_calendar_event_project_id_project"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_event")),
    )
    op.create_index(op.f("ix_calendar_event_owner_id"), "calendar_event", ["owner_id"])
    op.create_index(op.f("ix_calendar_event_project_id"), "calendar_event", ["project_id"])
    op.create_index(op.f("ix_calendar_event_starts_at"), "calendar_event", ["starts_at"])
    op.create_index("ix_calendar_event_owner_start", "calendar_event", ["owner_id", "starts_at"])
    op.create_index(op.f("ix_calendar_event_created_at"), "calendar_event", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_calendar_event_created_at"), table_name="calendar_event")
    op.drop_index("ix_calendar_event_owner_start", table_name="calendar_event")
    op.drop_index(op.f("ix_calendar_event_starts_at"), table_name="calendar_event")
    op.drop_index(op.f("ix_calendar_event_project_id"), table_name="calendar_event")
    op.drop_index(op.f("ix_calendar_event_owner_id"), table_name="calendar_event")
    op.drop_table("calendar_event")

    op.drop_index(op.f("ix_task_created_at"), table_name="task")
    op.drop_index("ix_task_owner_due", table_name="task")
    op.drop_index("ix_task_owner_status", table_name="task")
    op.drop_index(op.f("ix_task_due_at"), table_name="task")
    op.drop_index(op.f("ix_task_priority"), table_name="task")
    op.drop_index(op.f("ix_task_status"), table_name="task")
    op.drop_index(op.f("ix_task_project_id"), table_name="task")
    op.drop_index(op.f("ix_task_owner_id"), table_name="task")
    op.drop_table("task")

    op.drop_index(op.f("ix_project_created_at"), table_name="project")
    op.drop_index("ix_project_owner_status", table_name="project")
    op.drop_index(op.f("ix_project_status"), table_name="project")
    op.drop_index(op.f("ix_project_owner_id"), table_name="project")
    op.drop_table("project")
