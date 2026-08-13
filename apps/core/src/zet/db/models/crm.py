"""CRM DB modellari — kontaktlar, leadlar, deallar (Bo'lim 6).

Ilgari `business/crm.py`dagi `CRM` klassi faqat in-memory edi — protsess
qayta ishga tushganda barcha mijozlar ma'lumoti yo'qolardi. Bu jadvallar
`PgCRM` orqali haqiqiy saqlashni ta'minlaydi (`docs/04-CONSTRAINTS.md`
C-03: o'quv markaz CRM — birinchi biznes ustuvorlik).

Bog'liq qarorlar:
    Bo'lim 6 — biznes agentlari (Sales)
    C-03 — CRM birinchi biznes ustuvorligi
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.business.crm import DealStage, LeadStatus
from zet.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column


class CRMContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Kontakt — aloqa ma'lumotlari."""

    __tablename__ = "crm_contact"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    telegram: Mapped[str] = mapped_column(String(64), default="")
    """Ko'rinadigan @username — odam o'qiydigan yorliq."""

    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, default=None, index=True)
    """Telegram raqamli chat ID — DM YUBORISH shu orqali (Z51).

    Bot API'da xabar @username'ga emas, faqat SONLI chat_id'ga
    yuboriladi, va faqat foydalanuvchi botga birinchi bo'lib yozgan
    bo'lsa. Do'kon boti mijoz yozganda buni avtomatik to'ldiradi."""

    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_crm_contact_owner_name", "owner_id", "name"),)


class CRMLead(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lead — potentsial mijoz."""

    __tablename__ = "crm_lead"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_contact.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[LeadStatus] = mapped_column(
        enum_column(LeadStatus), default=LeadStatus.NEW, index=True
    )
    score: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="crm_lead_score_range"),
        Index("ix_crm_lead_owner_status", "owner_id", "status"),
    )


class CRMDeal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Deal — bitim (sotuvlar pipeline)."""

    __tablename__ = "crm_deal"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crm_lead.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(default=0.0)
    stage: Mapped[DealStage] = mapped_column(
        enum_column(DealStage), default=DealStage.PROPOSAL, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        CheckConstraint("amount >= 0", name="crm_deal_amount_positive"),
        Index("ix_crm_deal_owner_stage", "owner_id", "stage"),
    )


__all__ = ["CRMContact", "CRMDeal", "CRMLead"]
