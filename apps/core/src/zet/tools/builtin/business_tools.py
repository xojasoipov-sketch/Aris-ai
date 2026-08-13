"""Business Registry agent tool'lari — C2 (KONSOLIDATSIYA v2, tungi reja).

NEGA BU FAYL KERAK BO'LDI.

`crm_tools.py` odamlar (kontaktlar) uchun tool beradi, lekin BIZNESLAR
(tashkilotlar/kanallar) uchun hech qanday tool yo'q edi — agent "yangi
biznes qo'sh" kabi buyruqni bajara olmasdi. Bu fayl `crm_tools.py`
naqshini takrorlaydi (`_CRMTool` o'rniga `_BusinessTool` — bir xil
scope+xato boshqaruvi).

Batafsil qaror: `docs/KONSOLIDATSIYA_V2_C_PLANS.md::C2`.

Bog'liq qarorlar:
    C2 — Business/Contacts Registry
    V-31 — READ/WRITE ruxsat darajalari
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.business.pg_crm import PgCRM

BusinessScope = Callable[[], "AbstractAsyncContextManager[PgCRM]"]
"""`async with scope() as crm:` — `CRMScope` bilan bir xil sessiya (bitta
`PgCRM` ob'ekti ham kontaktlarni, ham bizneslarni olib yuradi)."""


class _BusinessTool(Tool):
    """Business tool'lari uchun umumiy asos (scope+xato)."""

    def __init__(self, *, scope: BusinessScope | None = None) -> None:
        self._scope = scope

    @property
    def connected(self) -> bool:
        return self._scope is not None

    def _require_scope(self) -> BusinessScope:
        if self._scope is None:
            raise ToolError("CRM bazasi ulanmagan — business tool'lari ishlamaydi")
        return self._scope


class BusinessCreateTool(_BusinessTool):
    """Yangi biznes qo'shish."""

    @property
    def name(self) -> str:
        return "business.create"

    @property
    def description(self) -> str:
        return (
            "Yangi biznes (tashkilot/kanal) qo'shish — name majburiy, "
            "aliases/telegram_channel_ids/keywords ixtiyoriy."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "aliases": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 200},
                    "maxItems": 20,
                },
                "telegram_channel_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "maxItems": 50,
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 100},
                    "maxItems": 50,
                },
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
            business = await crm.add_business(**params)
        return {"business": _business_dict(business)}


class BusinessListTool(_BusinessTool):
    """Bizneslar ro'yxati (yoki nom/aliases bo'yicha qidiruv)."""

    @property
    def name(self) -> str:
        return "business.list"

    @property
    def description(self) -> str:
        return "Bizneslar ro'yxatini olish; `query` berilsa nom/aliases bo'yicha qidiradi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200}},
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        query = params.get("query")
        async with scope() as crm:
            businesses = await (crm.find_business(query) if query else crm.list_businesses())
        return {"businesses": [_business_dict(b) for b in businesses]}


class BusinessContactLinkTool(_BusinessTool):
    """Mavjud kontaktni biznesga bog'lash."""

    @property
    def name(self) -> str:
        return "business.contact_link"

    @property
    def description(self) -> str:
        return "Mavjud CRM kontaktini biznesga bog'lash (contact_id + business_id)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "minLength": 1},
                "business_id": {"type": "string", "minLength": 1},
            },
            "required": ["contact_id", "business_id"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return True

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        async with scope() as crm:
            contact = await crm.link_contact_to_business(**params)
        return {"contact": {"id": contact.id, "name": contact.name, "business_id": contact.business_id}}


def _business_dict(business: object) -> dict[str, Any]:
    return {
        "id": business.id,  # type: ignore[attr-defined]
        "name": business.name,  # type: ignore[attr-defined]
        "aliases": business.aliases,  # type: ignore[attr-defined]
        "telegram_channel_ids": business.telegram_channel_ids,  # type: ignore[attr-defined]
        "keywords": business.keywords,  # type: ignore[attr-defined]
        "is_active": business.is_active,  # type: ignore[attr-defined]
    }


__all__ = [
    "BusinessContactLinkTool",
    "BusinessCreateTool",
    "BusinessListTool",
    "BusinessScope",
]
