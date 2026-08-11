"""Minimal CRM — mijozlar bazasi (Bo'lim 6).

Modellar:
    - Lead — potentsial mijoz
    - Contact — aloqa ma'lumotlari
    - Deal — bitim (sotuvlar pipeline)

CRM operatsiyalari:
    - Lead yaratish va kvalifikatsiya qilish
    - Deal bosqichlarini boshqarish
    - Kontaktlar ro'yxati
    - Pipeline hisoboti

Bo'lim 6 lean: in-memory CRM. Produksiyada DB ga o'tadi.

Bog'liq qarorlar:
    Bo'lim 6 — biznes agentlari (Sales agent uchun)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class LeadStatus(StrEnum):
    """Lead holati."""

    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"


class DealStage(StrEnum):
    """Bitim bosqichi."""

    PROPOSAL = "proposal"
    NEGOTIATION = "negotiation"
    WON = "won"
    LOST = "lost"


class Contact(BaseModel, frozen=True):
    """Kontakt — aloqa ma'lumotlari."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    company: str = ""
    email: str = ""
    phone: str = ""
    telegram: str = ""
    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Lead(BaseModel, frozen=True):
    """Lead — potentsial mijoz."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    contact_id: str
    """Bog'liq kontakt ID."""

    source: str = ""
    """Lead manbasi (web, telegram, referral, va h.k.)."""

    status: LeadStatus = LeadStatus.NEW
    """Lead holati."""

    score: int = Field(default=0, ge=0, le=100)
    """Lead bali (0-100). BANT asosida."""

    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Deal(BaseModel, frozen=True):
    """Deal — bitim (sotuvlar pipeline)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    lead_id: str
    """Bog'liq lead ID."""

    title: str
    """Bitim nomi."""

    amount: float = Field(default=0.0, ge=0.0)
    """Bitim summasi (USD)."""

    stage: DealStage = DealStage.PROPOSAL
    """Bitim bosqichi."""

    notes: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CRM:
    """Minimal CRM — in-memory mijozlar bazasi.

    Bo'lim 6 lean: in-memory. Produksiyada PgCRM bilan almashtiriladi.
    """

    def __init__(self) -> None:
        self._contacts: dict[str, Contact] = {}
        self._leads: dict[str, Lead] = {}
        self._deals: dict[str, Deal] = {}

    # ── Kontaktlar ────────────────────────────────────────────────

    def add_contact(self, *, name: str, **kwargs: str) -> Contact:
        """Yangi kontakt qo'shish."""
        contact = Contact(name=name, **kwargs)
        self._contacts[contact.id] = contact
        log.info("crm.contact_added", id=contact.id, name=name)
        return contact

    def get_contact(self, contact_id: str) -> Contact | None:
        """Kontakt olish."""
        return self._contacts.get(contact_id)

    def list_contacts(self) -> list[Contact]:
        """Barcha kontaktlar."""
        return list(self._contacts.values())

    def find_contacts(self, query: str) -> list[Contact]:
        """Kontakt qidirish (nom, kompaniya, email bo'yicha)."""
        query_lower = query.lower()
        return [
            c
            for c in self._contacts.values()
            if query_lower in c.name.lower()
            or query_lower in c.company.lower()
            or query_lower in c.email.lower()
        ]

    # ── Leadlar ───────────────────────────────────────────────────

    def add_lead(
        self,
        *,
        contact_id: str,
        source: str = "",
        score: int = 0,
        notes: str = "",
    ) -> Lead:
        """Yangi lead qo'shish."""
        if contact_id not in self._contacts:
            raise ValueError(f"Kontakt '{contact_id}' topilmadi")

        lead = Lead(
            contact_id=contact_id,
            source=source,
            score=score,
            notes=notes,
        )
        self._leads[lead.id] = lead
        log.info("crm.lead_added", id=lead.id, contact_id=contact_id)
        return lead

    def get_lead(self, lead_id: str) -> Lead | None:
        """Lead olish."""
        return self._leads.get(lead_id)

    def list_leads(self, status: LeadStatus | None = None) -> list[Lead]:
        """Leadlar ro'yxati (ixtiyoriy holat filtri)."""
        if status is None:
            return list(self._leads.values())
        return [lead for lead in self._leads.values() if lead.status == status]

    def qualify_lead(self, lead_id: str, *, score: int, notes: str = "") -> Lead:
        """Lead ni kvalifikatsiya qilish.

        Raises:
            ValueError: lead topilmadi
        """
        old = self._leads.get(lead_id)
        if old is None:
            raise ValueError(f"Lead '{lead_id}' topilmadi")

        new_status = LeadStatus.QUALIFIED if score >= 50 else LeadStatus.UNQUALIFIED
        updated = Lead(
            id=old.id,
            contact_id=old.contact_id,
            source=old.source,
            status=new_status,
            score=score,
            notes=notes or old.notes,
            created_at=old.created_at,
        )
        self._leads[lead_id] = updated
        log.info(
            "crm.lead_qualified",
            id=lead_id,
            score=score,
            status=new_status.value,
        )
        return updated

    # ── Deallar ───────────────────────────────────────────────────

    def add_deal(
        self,
        *,
        lead_id: str,
        title: str,
        amount: float = 0.0,
    ) -> Deal:
        """Yangi deal qo'shish."""
        if lead_id not in self._leads:
            raise ValueError(f"Lead '{lead_id}' topilmadi")

        deal = Deal(lead_id=lead_id, title=title, amount=amount)
        self._deals[deal.id] = deal
        log.info("crm.deal_added", id=deal.id, lead_id=lead_id, amount=amount)
        return deal

    def get_deal(self, deal_id: str) -> Deal | None:
        """Deal olish."""
        return self._deals.get(deal_id)

    def list_deals(self, stage: DealStage | None = None) -> list[Deal]:
        """Deallar ro'yxati (ixtiyoriy bosqich filtri)."""
        if stage is None:
            return list(self._deals.values())
        return [d for d in self._deals.values() if d.stage == stage]

    def update_deal_stage(self, deal_id: str, stage: DealStage) -> Deal:
        """Deal bosqichini yangilash.

        Raises:
            ValueError: deal topilmadi
        """
        old = self._deals.get(deal_id)
        if old is None:
            raise ValueError(f"Deal '{deal_id}' topilmadi")

        updated = Deal(
            id=old.id,
            lead_id=old.lead_id,
            title=old.title,
            amount=old.amount,
            stage=stage,
            notes=old.notes,
            created_at=old.created_at,
        )
        self._deals[deal_id] = updated
        log.info("crm.deal_stage_updated", id=deal_id, stage=stage.value)
        return updated

    # ── Hisobotlar ────────────────────────────────────────────────

    @property
    def pipeline_value(self) -> float:
        """Pipeline umumiy qiymati (faqat faol deallar)."""
        return sum(
            d.amount for d in self._deals.values() if d.stage not in {DealStage.WON, DealStage.LOST}
        )

    @property
    def won_value(self) -> float:
        """Yutilgan deallar qiymati."""
        return sum(d.amount for d in self._deals.values() if d.stage == DealStage.WON)

    @property
    def stats(self) -> dict[str, int | float]:
        """CRM statistikasi."""
        return {
            "contacts": len(self._contacts),
            "leads": len(self._leads),
            "qualified_leads": len(self.list_leads(LeadStatus.QUALIFIED)),
            "deals": len(self._deals),
            "pipeline_value": self.pipeline_value,
            "won_value": self.won_value,
        }
