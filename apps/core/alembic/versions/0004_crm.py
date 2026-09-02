"""crm jadvallari (Bo'lim 6, C-03)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-12 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import zet.db.base
from zet.business.crm import DealStage, LeadStatus

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crm_contact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("telegram", sa.String(length=64), nullable=False),
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
            name=op.f("fk_crm_contact_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_contact")),
    )
    op.create_index("ix_crm_contact_owner_name", "crm_contact", ["owner_id", "name"])
    op.create_index(op.f("ix_crm_contact_owner_id"), "crm_contact", ["owner_id"])
    op.create_index(op.f("ix_crm_contact_created_at"), "crm_contact", ["created_at"])

    op.create_table(
        "crm_lead",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            zet.db.base.enum_column(LeadStatus),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
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
            name=op.f("fk_crm_lead_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["crm_contact.id"],
            name=op.f("fk_crm_lead_contact_id_crm_contact"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_lead")),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name=op.f("ck_crm_lead_crm_lead_score_range")
        ),
    )
    op.create_index(op.f("ix_crm_lead_owner_id"), "crm_lead", ["owner_id"])
    op.create_index(op.f("ix_crm_lead_contact_id"), "crm_lead", ["contact_id"])
    op.create_index(op.f("ix_crm_lead_status"), "crm_lead", ["status"])
    op.create_index("ix_crm_lead_owner_status", "crm_lead", ["owner_id", "status"])
    op.create_index(op.f("ix_crm_lead_created_at"), "crm_lead", ["created_at"])

    op.create_table(
        "crm_deal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column(
            "stage",
            zet.db.base.enum_column(DealStage),
            nullable=False,
        ),
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
            name=op.f("fk_crm_deal_owner_id_owner"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["crm_lead.id"],
            name=op.f("fk_crm_deal_lead_id_crm_lead"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_crm_deal")),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_crm_deal_crm_deal_amount_positive")),
    )
    op.create_index(op.f("ix_crm_deal_owner_id"), "crm_deal", ["owner_id"])
    op.create_index(op.f("ix_crm_deal_lead_id"), "crm_deal", ["lead_id"])
    op.create_index(op.f("ix_crm_deal_stage"), "crm_deal", ["stage"])
    op.create_index("ix_crm_deal_owner_stage", "crm_deal", ["owner_id", "stage"])
    op.create_index(op.f("ix_crm_deal_created_at"), "crm_deal", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_crm_deal_created_at"), table_name="crm_deal")
    op.drop_index("ix_crm_deal_owner_stage", table_name="crm_deal")
    op.drop_index(op.f("ix_crm_deal_stage"), table_name="crm_deal")
    op.drop_index(op.f("ix_crm_deal_lead_id"), table_name="crm_deal")
    op.drop_index(op.f("ix_crm_deal_owner_id"), table_name="crm_deal")
    op.drop_table("crm_deal")

    op.drop_index(op.f("ix_crm_lead_created_at"), table_name="crm_lead")
    op.drop_index("ix_crm_lead_owner_status", table_name="crm_lead")
    op.drop_index(op.f("ix_crm_lead_status"), table_name="crm_lead")
    op.drop_index(op.f("ix_crm_lead_contact_id"), table_name="crm_lead")
    op.drop_index(op.f("ix_crm_lead_owner_id"), table_name="crm_lead")
    op.drop_table("crm_lead")

    op.drop_index(op.f("ix_crm_contact_created_at"), table_name="crm_contact")
    op.drop_index(op.f("ix_crm_contact_owner_id"), table_name="crm_contact")
    op.drop_index("ix_crm_contact_owner_name", table_name="crm_contact")
    op.drop_table("crm_contact")
