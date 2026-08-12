"""CRM API endpoint'lari (Bo'lim 6, C-03).

    POST /api/v1/crm/contacts             — kontakt qo'shish
    GET  /api/v1/crm/contacts             — kontaktlar ro'yxati (ixtiyoriy: qidiruv)
    GET  /api/v1/crm/contacts/{id}        — bitta kontakt

    POST /api/v1/crm/leads                — lead qo'shish
    GET  /api/v1/crm/leads                — leadlar ro'yxati (ixtiyoriy: status)
    GET  /api/v1/crm/leads/{id}           — bitta lead
    POST /api/v1/crm/leads/{id}/qualify   — lead'ni kvalifikatsiya qilish

    POST /api/v1/crm/deals                — deal qo'shish
    GET  /api/v1/crm/deals                — deallar ro'yxati (ixtiyoriy: bosqich)
    GET  /api/v1/crm/deals/{id}           — bitta deal
    POST /api/v1/crm/deals/{id}/stage     — deal bosqichini yangilash

    GET  /api/v1/crm/stats                — pipeline statistikasi

Ilgari `business/crm.py`dagi `CRM` klassi hech qanday DB jadvali, API
route yoki tool bilan bog'lanmagan edi — butunlay o'lik kod edi
(gap-analysis). `docs/04-CONSTRAINTS.md` C-03 CRM'ni eng kam tashqi
bog'liqlikka ega, eng aniq ROI'li birinchi biznes ustuvorlik deb
belgilagan. Endi shu route'lar orqali haqiqiy `crm_contact`/`crm_lead`/
`crm_deal` jadvallariga yoziladi/o'qiladi (`PgCRM`).

Bog'liq qarorlar:
    Bo'lim 6 — biznes agentlari (Sales)
    C-03 — CRM birinchi biznes ustuvorligi
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_crm
from zet.business.crm import Contact, Deal, DealStage, Lead, LeadStatus
from zet.business.pg_crm import CRMNotFoundError, PgCRM

router = APIRouter(prefix="/crm", tags=["crm"])


# ── Request modellari ────────────────────────────────────────────


class ContactCreateRequest(BaseModel):
    """Yangi kontakt so'rovi."""

    name: str = Field(..., min_length=1, max_length=200)
    company: str = ""
    email: str = ""
    phone: str = ""
    telegram: str = ""
    notes: str = ""


class LeadCreateRequest(BaseModel):
    """Yangi lead so'rovi."""

    contact_id: str = Field(..., min_length=1)
    source: str = ""
    score: int = Field(default=0, ge=0, le=100)
    notes: str = ""


class LeadQualifyRequest(BaseModel):
    """Lead kvalifikatsiya so'rovi."""

    score: int = Field(..., ge=0, le=100)
    notes: str = ""


class DealCreateRequest(BaseModel):
    """Yangi deal so'rovi."""

    lead_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1, max_length=200)
    amount: float = Field(default=0.0, ge=0.0)


class DealStageUpdateRequest(BaseModel):
    """Deal bosqichini yangilash so'rovi."""

    stage: DealStage


# ── Kontaktlar ────────────────────────────────────────────────────


@router.post("/contacts", response_model=Contact, status_code=201)
async def create_contact(
    request: ContactCreateRequest,
    crm: PgCRM = Depends(get_crm),
) -> Contact:
    """Yangi kontakt qo'shish."""
    return await crm.add_contact(
        name=request.name,
        company=request.company,
        email=request.email,
        phone=request.phone,
        telegram=request.telegram,
        notes=request.notes,
    )


@router.get("/contacts", response_model=list[Contact])
async def list_contacts(
    query: str | None = None,
    crm: PgCRM = Depends(get_crm),
) -> list[Contact]:
    """Kontaktlar ro'yxati (ixtiyoriy: nom/kompaniya/email bo'yicha qidiruv)."""
    if query:
        return await crm.find_contacts(query)
    return await crm.list_contacts()


@router.get("/contacts/{contact_id}", response_model=Contact)
async def get_contact(
    contact_id: str,
    crm: PgCRM = Depends(get_crm),
) -> Contact:
    """Bitta kontakt ma'lumotlari."""
    contact = await crm.get_contact(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Kontakt topilmadi")
    return contact


# ── Leadlar ───────────────────────────────────────────────────────


@router.post("/leads", response_model=Lead, status_code=201)
async def create_lead(
    request: LeadCreateRequest,
    crm: PgCRM = Depends(get_crm),
) -> Lead:
    """Yangi lead qo'shish."""
    try:
        return await crm.add_lead(
            contact_id=request.contact_id,
            source=request.source,
            score=request.score,
            notes=request.notes,
        )
    except CRMNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/leads", response_model=list[Lead])
async def list_leads(
    status: LeadStatus | None = None,
    crm: PgCRM = Depends(get_crm),
) -> list[Lead]:
    """Leadlar ro'yxati (ixtiyoriy status filtri)."""
    return await crm.list_leads(status)


@router.get("/leads/{lead_id}", response_model=Lead)
async def get_lead(
    lead_id: str,
    crm: PgCRM = Depends(get_crm),
) -> Lead:
    """Bitta lead ma'lumotlari."""
    lead = await crm.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead topilmadi")
    return lead


@router.post("/leads/{lead_id}/qualify", response_model=Lead)
async def qualify_lead(
    lead_id: str,
    request: LeadQualifyRequest,
    crm: PgCRM = Depends(get_crm),
) -> Lead:
    """Lead'ni kvalifikatsiya qilish — score >= 50 → QUALIFIED, aks holda UNQUALIFIED."""
    try:
        return await crm.qualify_lead(lead_id, score=request.score, notes=request.notes)
    except CRMNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Deallar ───────────────────────────────────────────────────────


@router.post("/deals", response_model=Deal, status_code=201)
async def create_deal(
    request: DealCreateRequest,
    crm: PgCRM = Depends(get_crm),
) -> Deal:
    """Yangi deal qo'shish."""
    try:
        return await crm.add_deal(
            lead_id=request.lead_id, title=request.title, amount=request.amount
        )
    except CRMNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/deals", response_model=list[Deal])
async def list_deals(
    stage: DealStage | None = None,
    crm: PgCRM = Depends(get_crm),
) -> list[Deal]:
    """Deallar ro'yxati (ixtiyoriy bosqich filtri)."""
    return await crm.list_deals(stage)


@router.get("/deals/{deal_id}", response_model=Deal)
async def get_deal(
    deal_id: str,
    crm: PgCRM = Depends(get_crm),
) -> Deal:
    """Bitta deal ma'lumotlari."""
    deal = await crm.get_deal(deal_id)
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal topilmadi")
    return deal


@router.post("/deals/{deal_id}/stage", response_model=Deal)
async def update_deal_stage(
    deal_id: str,
    request: DealStageUpdateRequest,
    crm: PgCRM = Depends(get_crm),
) -> Deal:
    """Deal bosqichini yangilash."""
    try:
        return await crm.update_deal_stage(deal_id, request.stage)
    except CRMNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Hisobotlar ────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(crm: PgCRM = Depends(get_crm)) -> dict[str, int | float]:
    """Pipeline statistikasi (kontaktlar, leadlar, deallar, qiymatlar)."""
    return await crm.stats()
