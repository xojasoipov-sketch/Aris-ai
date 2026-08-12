"""PgCRM — DB-backed CRM (Bo'lim 6, C-03).

Ilgari `CRM` (business/crm.py) faqat in-memory edi va hech qanday DB
jadvali, API route yoki tool uni ishlatmasdi — mijozlar ma'lumoti protsess
qayta ishga tushganda yo'qolardi. `docs/04-CONSTRAINTS.md` C-03 CRM'ni
birinchi biznes ustuvorlik deb belgilagan (eng kam tashqi bog'liqlik,
eng aniq ROI).

`PgCRM` xuddi `PgMemoryStore`/`PgMemoryStore` naqshi — `CRM`ning ochiq
metodlarini oynali (async, egasiga bog'langan) takrorlaydi, lekin
haqiqiy `crm_contact`/`crm_lead`/`crm_deal` jadvallariga yozadi/o'qiydi.
Qaytariladigan qiymatlar xuddi shu `Contact`/`Lead`/`Deal` Pydantic
modellari — API ham shularni to'g'ridan-to'g'ri javob sifatida ishlatadi.

Bog'liq qarorlar:
    Bo'lim 6 — biznes agentlari (Sales)
    C-03 — CRM birinchi biznes ustuvorligi
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.business.crm import Contact, Deal, DealStage, Lead, LeadStatus
from zet.db.models.crm import CRMContact, CRMDeal, CRMLead

log = structlog.get_logger(__name__)


class CRMNotFoundError(ValueError):
    """Bog'liq yozuv (kontakt/lead) topilmadi."""


def _contact_from_row(row: CRMContact) -> Contact:
    return Contact(
        id=str(row.id),
        name=row.name,
        company=row.company,
        email=row.email,
        phone=row.phone,
        telegram=row.telegram,
        notes=row.notes,
        created_at=row.created_at,
    )


def _lead_from_row(row: CRMLead) -> Lead:
    return Lead(
        id=str(row.id),
        contact_id=str(row.contact_id),
        source=row.source,
        status=row.status,
        score=row.score,
        notes=row.notes,
        created_at=row.created_at,
    )


def _deal_from_row(row: CRMDeal) -> Deal:
    return Deal(
        id=str(row.id),
        lead_id=str(row.lead_id),
        title=row.title,
        amount=row.amount,
        stage=row.stage,
        notes=row.notes,
        created_at=row.created_at,
    )


class PgCRM:
    """DB-backed CRM — bitta egaga (`owner_id`) bog'langan."""

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    # ── Kontaktlar ────────────────────────────────────────────────

    async def add_contact(
        self,
        *,
        name: str,
        company: str = "",
        email: str = "",
        phone: str = "",
        telegram: str = "",
        notes: str = "",
    ) -> Contact:
        row = CRMContact(
            owner_id=self._owner_id,
            name=name,
            company=company,
            email=email,
            phone=phone,
            telegram=telegram,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        log.info("crm.contact_added", id=str(row.id), name=name)
        return _contact_from_row(row)

    async def get_contact(self, contact_id: str) -> Contact | None:
        row = await self._get_contact_row(contact_id)
        return _contact_from_row(row) if row is not None else None

    async def list_contacts(self) -> list[Contact]:
        result = await self._session.execute(
            select(CRMContact).where(CRMContact.owner_id == self._owner_id)
        )
        return [_contact_from_row(r) for r in result.scalars().all()]

    async def find_contacts(self, query: str) -> list[Contact]:
        contacts = await self.list_contacts()
        q = query.lower()
        return [
            c
            for c in contacts
            if q in c.name.lower() or q in c.company.lower() or q in c.email.lower()
        ]

    # ── Leadlar ───────────────────────────────────────────────────

    async def add_lead(
        self,
        *,
        contact_id: str,
        source: str = "",
        score: int = 0,
        notes: str = "",
    ) -> Lead:
        contact_row = await self._get_contact_row(contact_id)
        if contact_row is None:
            raise CRMNotFoundError(f"Kontakt '{contact_id}' topilmadi")

        row = CRMLead(
            owner_id=self._owner_id,
            contact_id=contact_row.id,
            source=source,
            score=score,
            notes=notes,
        )
        self._session.add(row)
        await self._session.flush()
        log.info("crm.lead_added", id=str(row.id), contact_id=contact_id)
        return _lead_from_row(row)

    async def get_lead(self, lead_id: str) -> Lead | None:
        row = await self._get_lead_row(lead_id)
        return _lead_from_row(row) if row is not None else None

    async def list_leads(self, status: LeadStatus | None = None) -> list[Lead]:
        stmt = select(CRMLead).where(CRMLead.owner_id == self._owner_id)
        if status is not None:
            stmt = stmt.where(CRMLead.status == status)
        result = await self._session.execute(stmt)
        return [_lead_from_row(r) for r in result.scalars().all()]

    async def qualify_lead(self, lead_id: str, *, score: int, notes: str = "") -> Lead:
        row = await self._get_lead_row(lead_id)
        if row is None:
            raise CRMNotFoundError(f"Lead '{lead_id}' topilmadi")

        row.score = score
        row.status = LeadStatus.QUALIFIED if score >= 50 else LeadStatus.UNQUALIFIED
        if notes:
            row.notes = notes
        await self._session.flush()
        log.info("crm.lead_qualified", id=lead_id, score=score, status=row.status.value)
        return _lead_from_row(row)

    # ── Deallar ───────────────────────────────────────────────────

    async def add_deal(self, *, lead_id: str, title: str, amount: float = 0.0) -> Deal:
        lead_row = await self._get_lead_row(lead_id)
        if lead_row is None:
            raise CRMNotFoundError(f"Lead '{lead_id}' topilmadi")

        row = CRMDeal(
            owner_id=self._owner_id,
            lead_id=lead_row.id,
            title=title,
            amount=amount,
        )
        self._session.add(row)
        await self._session.flush()
        log.info("crm.deal_added", id=str(row.id), lead_id=lead_id, amount=amount)
        return _deal_from_row(row)

    async def get_deal(self, deal_id: str) -> Deal | None:
        row = await self._get_deal_row(deal_id)
        return _deal_from_row(row) if row is not None else None

    async def list_deals(self, stage: DealStage | None = None) -> list[Deal]:
        stmt = select(CRMDeal).where(CRMDeal.owner_id == self._owner_id)
        if stage is not None:
            stmt = stmt.where(CRMDeal.stage == stage)
        result = await self._session.execute(stmt)
        return [_deal_from_row(r) for r in result.scalars().all()]

    async def update_deal_stage(self, deal_id: str, stage: DealStage) -> Deal:
        row = await self._get_deal_row(deal_id)
        if row is None:
            raise CRMNotFoundError(f"Deal '{deal_id}' topilmadi")

        row.stage = stage
        await self._session.flush()
        log.info("crm.deal_stage_updated", id=deal_id, stage=stage.value)
        return _deal_from_row(row)

    # ── Hisobotlar ────────────────────────────────────────────────

    async def pipeline_value(self) -> float:
        """Pipeline umumiy qiymati (faqat faol deallar)."""
        deals = await self.list_deals()
        return sum(d.amount for d in deals if d.stage not in {DealStage.WON, DealStage.LOST})

    async def won_value(self) -> float:
        """Yutilgan deallar qiymati."""
        deals = await self.list_deals()
        return sum(d.amount for d in deals if d.stage == DealStage.WON)

    async def stats(self) -> dict[str, int | float]:
        """CRM statistikasi."""
        contacts = await self.list_contacts()
        leads = await self.list_leads()
        qualified = [lead_item for lead_item in leads if lead_item.status == LeadStatus.QUALIFIED]
        deals = await self.list_deals()
        return {
            "contacts": len(contacts),
            "leads": len(leads),
            "qualified_leads": len(qualified),
            "deals": len(deals),
            "pipeline_value": await self.pipeline_value(),
            "won_value": await self.won_value(),
        }

    # ── Yordamchi ─────────────────────────────────────────────────

    async def _get_contact_row(self, contact_id: str) -> CRMContact | None:
        try:
            row_id = uuid.UUID(contact_id)
        except ValueError:
            return None
        result = await self._session.execute(
            select(CRMContact).where(CRMContact.id == row_id, CRMContact.owner_id == self._owner_id)
        )
        return result.scalar_one_or_none()

    async def _get_lead_row(self, lead_id: str) -> CRMLead | None:
        try:
            row_id = uuid.UUID(lead_id)
        except ValueError:
            return None
        result = await self._session.execute(
            select(CRMLead).where(CRMLead.id == row_id, CRMLead.owner_id == self._owner_id)
        )
        return result.scalar_one_or_none()

    async def _get_deal_row(self, deal_id: str) -> CRMDeal | None:
        try:
            row_id = uuid.UUID(deal_id)
        except ValueError:
            return None
        result = await self._session.execute(
            select(CRMDeal).where(CRMDeal.id == row_id, CRMDeal.owner_id == self._owner_id)
        )
        return result.scalar_one_or_none()


__all__ = ["CRMNotFoundError", "PgCRM"]
