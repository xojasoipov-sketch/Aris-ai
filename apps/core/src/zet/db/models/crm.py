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

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.business.crm import DealStage, LeadStatus
from zet.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, enum_column


class Business(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Biznes (do'kon/kanal/mijoz-tashkilot) — C2 (KONSOLIDATSIYA v2).

    NEGA bu jadval kerak bo'ldi: odamlar uchun `CRMContact` allaqachon
    bor edi (`telegram_chat_id` bilan "ism → chat_id" xaritasi), lekin
    BIZNESLAR (masalan Ingestion Router'ning qaysi kanaldan kelgan
    xabar QAYSI mijozga tegishli ekanini aniqlashi kerak bo'lgan
    tashkilotlar) uchun hech qanday struktura yo'q edi.

    Obsidian'da PARALLEL biznes-indeksi QURILMAYDI (foydalanuvchi
    taklifi ko'rib chiqilgan va rad etilgan — `docs/
    KONSOLIDATSIYA_V2_C_PLANS.md::C2` bo'limida sabab yozilgan):
    Postgres — strukturaviy haqiqat manbai, ikkita parallel manba
    drift xavfi tug'diradi.
    """

    __tablename__ = "business"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))

    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list)
    """Muqobil nomlar/yozilishlar — qidiruvda moslashtirish uchun
    (masalan "Zetlab" va "ZET Lab")."""

    vault_folder: Mapped[str] = mapped_column(String(200), default="")
    """Obsidian vault'dagi ixtiyoriy ko'zgu-papka nomi (bo'sh — hali yo'q)."""

    telegram_channel_ids: Mapped[list[int]] = mapped_column(JSONType, default=list)
    """Ushbu biznesga tegishli Telegram kanal/guruh chat_id'lari."""

    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    """Kelgusidagi Ingestion Router (C1) uchun fallback qidiruv so'zlari —
    `crm_contact.telegram_chat_id` aniq mos kelmasa ishlatiladi."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    notes: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_business_owner_name", "owner_id", "name"),)


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

    business_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("business.id", ondelete="SET NULL"), default=None, index=True
    )
    """C2 (KONSOLIDATSIYA v2): kontakt qaysi biznesga tegishli — ixtiyoriy.

    `ON DELETE SET NULL` — `workspace.py::Task.project_id` bilan bir xil
    naqsh: biznes o'chirilsa, kontaktning O'ZI yo'qolmaydi, faqat
    bog'lanish tozalanadi."""

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


__all__ = ["Business", "CRMContact", "CRMDeal", "CRMLead"]
