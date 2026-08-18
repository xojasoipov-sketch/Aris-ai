"""CRM agent tool'lari — Sales/Support agent uchun (GAP_ANALYSIS §11).

NEGA BU FAYL KERAK BO'LDI.

`business/pg_crm.PgCRM` mavjud va REST API'da ishlaydi (`/api/v1/crm/*`),
lekin **agent uni chaqira olmasdi**: registry'da CRM tool'lari yo'q edi.
Sales agent'ining prompt'ida CRM ishlatish yozilgan-u, `tool_allowlist=
["web.search","time.now"]` — CRM'ga to'g'ridan-to'g'ri kirish yo'li yo'q.

Bu fayl `workspace_tools.py` naqshini takrorlaydi: har chaqiruvda yangi
qisqa DB sessiya ochiluvchi `CRMScope` fabrika.

Bog'liq qarorlar:
    V-31 — READ/WRITE ruxsat darajalari
    A-01 — holat bazaga saqlanadi
    C-03 — CRM birinchi biznes ustuvorligi
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from zet.business.crm import DealStage, LeadStatus
from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.business.pg_crm import PgCRM

CRMScope = Callable[[], "AbstractAsyncContextManager[PgCRM]"]
"""`async with scope() as crm:` — har chaqiruvda yangi qisqa sessiya."""


class _CRMTool(Tool):
    """CRM tool'lari uchun umumiy asos (scope+xato)."""

    def __init__(self, *, scope: CRMScope | None = None) -> None:
        self._scope = scope

    @property
    def connected(self) -> bool:
        return self._scope is not None

    def _require_scope(self) -> CRMScope:
        if self._scope is None:
            raise ToolError("CRM bazasi ulanmagan — sales tool'lari ishlamaydi")
        return self._scope


class CRMContactSearchTool(_CRMTool):
    """Kontaktlarni nom/kompaniya/telefon/email bo'yicha qidiradi."""

    @property
    def name(self) -> str:
        return "crm.contact_search"

    @property
    def description(self) -> str:
        return "CRM'dan kontakt(lar)ni qidirish (nom/kompaniya/telefon/email)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["query"],
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        query = params["query"]
        async with scope() as crm:
            contacts = await crm.find_contacts(query)
        return {"contacts": [_contact_dict(c) for c in contacts]}


class CRMContactCreateTool(_CRMTool):
    """Yangi kontakt qo'shish."""

    @property
    def name(self) -> str:
        return "crm.contact_create"

    @property
    def description(self) -> str:
        return "CRM'ga yangi kontakt qo'shish (name majburiy, qolganlari ixtiyoriy)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "company": {"type": "string", "maxLength": 200},
                "email": {"type": "string", "maxLength": 200},
                "phone": {"type": "string", "maxLength": 64},
                "telegram": {"type": "string", "maxLength": 64},
                "notes": {"type": "string", "maxLength": 2000},
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        async with scope() as crm:
            contact = await crm.add_contact(**params)
        return {"contact": _contact_dict(contact)}


class CRMLeadCreateTool(_CRMTool):
    """Kontaktga lead qo'shish."""

    @property
    def name(self) -> str:
        return "crm.lead_create"

    @property
    def description(self) -> str:
        return (
            "YOZISH: CRM'ga YANGI lead (potensial mijoz) yozuvi qo'shadi "
            "(contact_id + source + ixtiyoriy score). Mavjud lidlarni "
            "ko'rish/ro'yxatlash uchun EMAS — buning uchun crm.lead_list."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "minLength": 1},
                "source": {"type": "string", "maxLength": 64},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                "notes": {"type": "string", "maxLength": 2000},
            },
            "required": ["contact_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        async with scope() as crm:
            lead = await crm.add_lead(**params)
        return {"lead": _lead_dict(lead)}


class CRMLeadListTool(_CRMTool):
    """Lidlar ro'yxati — ixtiyoriy holat bo'yicha filtr."""

    @property
    def name(self) -> str:
        return "crm.lead_list"

    @property
    def description(self) -> str:
        return (
            "O'QISH: CRM'dagi mavjud lidlar (potensial mijozlar) ro'yxati, "
            "ixtiyoriy `status` bilan filtrlanadi (new/contacted/qualified/"
            "unqualified). Yangi lead YARATMAYDI — buning uchun crm.lead_create."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [s.value for s in LeadStatus],
                    "description": "Ixtiyoriy: shu holatdagilarni ko'rsatish",
                },
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        status_raw = params.get("status")
        status = LeadStatus(status_raw) if status_raw else None
        async with scope() as crm:
            leads = await crm.list_leads(status)
        return {"leads": [_lead_dict(lead) for lead in leads]}


class CRMDealCreateTool(_CRMTool):
    """Lead ustiga deal qo'shish."""

    @property
    def name(self) -> str:
        return "crm.deal_create"

    @property
    def description(self) -> str:
        return (
            "YOZISH: CRM'ga YANGI deal (bitim) yozuvi qo'shadi (lead_id + "
            "title + ixtiyoriy amount). Mavjud deallarni ko'rish uchun "
            "EMAS — buning uchun crm.deal_list."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "amount": {"type": "number", "minimum": 0},
            },
            "required": ["lead_id", "title"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        async with scope() as crm:
            deal = await crm.add_deal(**params)
        return {"deal": _deal_dict(deal)}


class CRMDealListTool(_CRMTool):
    """Deallar ro'yxati — ixtiyoriy bosqich bo'yicha filtr."""

    @property
    def name(self) -> str:
        return "crm.deal_list"

    @property
    def description(self) -> str:
        return (
            "O'QISH: CRM'dagi mavjud deallar (bitimlar) ro'yxati, ixtiyoriy "
            "`stage` bilan filtrlanadi (proposal/negotiation/won/lost). "
            "Yangi deal YARATMAYDI — buning uchun crm.deal_create."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": [s.value for s in DealStage],
                    "description": "Ixtiyoriy: shu bosqichdagilarni ko'rsatish",
                },
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        stage_raw = params.get("stage")
        stage = DealStage(stage_raw) if stage_raw else None
        async with scope() as crm:
            deals = await crm.list_deals(stage)
        return {"deals": [_deal_dict(deal) for deal in deals]}


class CRMStatsTool(_CRMTool):
    """CRM umumiy statistikasi — kontakt/lead/deal/qazongan qiymat."""

    @property
    def name(self) -> str:
        return "crm.stats"

    @property
    def description(self) -> str:
        return "CRM statistikasi: kontaktlar/lidlar/dealllar soni va pipeline qiymati."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        scope = self._require_scope()
        async with scope() as crm:
            stats = await crm.stats()
        return dict(stats)


# ── Serializerlar ─────────────────────────────────────────────────


def _contact_dict(contact: object) -> dict[str, Any]:
    return {
        "id": str(contact.id),  # type: ignore[attr-defined]
        "name": contact.name,  # type: ignore[attr-defined]
        "company": contact.company,  # type: ignore[attr-defined]
        "email": contact.email,  # type: ignore[attr-defined]
        "phone": contact.phone,  # type: ignore[attr-defined]
        "telegram": contact.telegram,  # type: ignore[attr-defined]
    }


def _lead_dict(lead: object) -> dict[str, Any]:
    return {
        "id": str(lead.id),  # type: ignore[attr-defined]
        "contact_id": str(lead.contact_id),  # type: ignore[attr-defined]
        "source": lead.source,  # type: ignore[attr-defined]
        "score": lead.score,  # type: ignore[attr-defined]
        "status": (
            lead.status.value if isinstance(lead.status, LeadStatus) else str(lead.status)  # type: ignore[attr-defined]
        ),
    }


def _deal_dict(deal: object) -> dict[str, Any]:
    return {
        "id": str(deal.id),  # type: ignore[attr-defined]
        "lead_id": str(deal.lead_id),  # type: ignore[attr-defined]
        "title": deal.title,  # type: ignore[attr-defined]
        "amount": deal.amount,  # type: ignore[attr-defined]
        "stage": (
            deal.stage.value if isinstance(deal.stage, DealStage) else str(deal.stage)  # type: ignore[attr-defined]
        ),
    }


__all__ = [
    "CRMContactCreateTool",
    "CRMContactSearchTool",
    "CRMDealCreateTool",
    "CRMDealListTool",
    "CRMLeadCreateTool",
    "CRMLeadListTool",
    "CRMScope",
    "CRMStatsTool",
]
