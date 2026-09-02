"""public_apis.search — tashqi API katalogini semantik qidirish (JB-18).

NEGA. Brain/Planner "buning uchun tashqi API bormi" deb bilishi kerak
bo'lganda (masalan foydalanuvchi "valyuta konvertatsiya qiluvchi API
bormi", "SMS yuborish uchun nima ishlatsa bo'ladi" desa) — bu tool
HAQIQIY, oldindan sinxronlangan `public-apis/public-apis` katalogidan
(sinxronlanganda 1500+ yozuv) qidiradi. LLM API nomlarini o'zi
TO'QIMAYDI — `CapabilityDiscoveryTool` (`capability_discovery.py`,
JB-16) ICHKI tool ro'yxati uchun qanday ishlagan bo'lsa, bu xuddi shu
naqsh — faqat TASHQI katalog uchun.

MUHIM CHEKLOV (Bo'lim 22 — "public-apis manba ishonch ildizi emas,
faqat kashfiyot katalogi"): bu tool natijasi hech qachon "ZET buni
HOZIR bajara oladi" degani EMAS. Katalogdagi yozuv `status="enabled"`
bo'lgandagina ORQASIDA haqiqiy, qo'lda ko'rib chiqilgan `Tool` adapter
bor va `ToolRegistry`da chaqirsa bo'ladi (buni `system.capabilities`
bilan tekshirish mumkin) — qolgan har qanday holat ("discovered",
"evaluated", "rejected", "disabled") shunchaki "bunday API mavjud
ekan" degan ma'lumot, ijro EMAS.

Bu farqni LLM javobida adashtirmaslik — aynan JB-16 CASE B bilan bir
xil xato sinfi (mavjud bo'lmagan imkoniyatni "bor" deb taxmin qilish).
Shuning uchun `description` (Planner tanlovi uchun) va `summary_text`
(LLM o'qiydigan natija) ikkalasi ham buni har doim ochiq aytadi.

`CatalogRepository` — `api/routes/public_apis.py`dagi operator
endpoint'lari bilan BIR XIL singleton
(`api/deps.py::get_public_apis_catalog_repository()`) — ikkala yo'l
(operator REST va Brain TOOL) bir xil ma'lumotni ko'radi, ikkinchi
mustaqil katalog YARATILMAYDI.

Xavfsizlik: permission=READ, risk=LOW (default jadvaldan) — faqat
jarayon-xotirasidagi katalogni o'qiydi, hech qanday tashqi tarmoq
chaqiruvi qilmaydi (tarmoqqa chiquvchi HTTP faqat `catalog/sync.py`da,
operator `POST /public-apis/refresh` chaqirganda).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zet.domain.enums import PermissionLevel
from zet.integrations.public_apis.catalog.models import APIStatus
from zet.integrations.public_apis.discovery.ranker import RankedCandidate, rank_candidates
from zet.integrations.public_apis.discovery.search import search_catalog
from zet.tools.base import Tool

if TYPE_CHECKING:
    from zet.integrations.public_apis.catalog.repository import CatalogRepository

_MAX_LIMIT = 25
_DEFAULT_LIMIT = 10


def _candidate_line(c: RankedCandidate) -> str:
    if c.status is APIStatus.ENABLED:
        note = "ZET'DA ULANGAN — haqiqatan chaqirsa bo'ladi"
    else:
        note = "faqat kashfiyot — ZET hozir bajara OLMAYDI"
    return f"- {c.name} ({c.provider}, auth={c.auth_type.value}): {note}"


class PublicAPISearchTool(Tool):
    """`CatalogRepository`dan HAQIQIY tashqi API nomzodlarini qidiradi."""

    def __init__(self, *, repository: CatalogRepository | None = None) -> None:
        # `CapabilityDiscoveryTool` bilan bir xil naqsh: `repository` —
        # `build_default_registry()` ichida yaratilgan (yoki testda
        # tashqaridan uzatilgan) obyektga ISHORA, nusxa emas.
        # `_execute()` uni SO'ROV vaqtida o'qiydi — shuning uchun
        # keyinroq `replace_all()` bilan yangilangan katalog ham
        # ko'rinadi (konstruksiya vaqtidagi bo'sh holat muammo emas).
        self._repository = repository

    @property
    def name(self) -> str:
        return "public_apis.search"

    @property
    def description(self) -> str:
        return (
            "Tashqi (public) API katalogini qidiradi — foydalanuvchi "
            "'buning uchun API bormi', 'qanday xizmat integratsiya "
            "qilsa bo'ladi' kabi savol bersa ishlating. DIQQAT: bu "
            "faqat KASHFIYOT — natijada ko'ringan API avtomatik "
            "ISHLAMAYDI, faqat 'enabled' deb belgilangani ZET orqali "
            "haqiqatan chaqirilishi mumkin (buni tekshirish uchun "
            "system.capabilities ishlating). Boshqa har qanday "
            "natijani foydalanuvchiga faqat TAKLIF sifatida ayting — "
            "ZET buni hozir bajara oladi deb AYTMANG."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Qidiruv so'zi/iborasi (masalan 'valyuta', "
                        "'geocoding', 'sms', 'ob-havo')."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": f"Nechta nomzod qaytarilsin (sukut {_DEFAULT_LIMIT}, max {_MAX_LIMIT}).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.READ

    @property
    def idempotent(self) -> bool:
        return True

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = str(params.get("query") or "").strip()
        if not query:
            return {
                "total_candidates": 0,
                "candidates": [],
                "summary_text": "Qidiruv so'zi bo'sh — hech narsa qidirilmadi.",
            }

        if self._repository is None or not self._repository.all():
            return {
                "total_candidates": 0,
                "candidates": [],
                "summary_text": (
                    "Tashqi API katalogi hali sinxronlanmagan (bo'sh). "
                    "Operator `POST /api/v1/public-apis/refresh` yoki "
                    "`z api refresh` orqali sinxronlashi kerak — "
                    "hozircha bu haqda hech narsa deyish mumkin emas "
                    "(taxmin qilinmaydi)."
                ),
            }

        limit_raw = params.get("limit")
        limit = limit_raw if isinstance(limit_raw, int) and limit_raw > 0 else _DEFAULT_LIMIT
        limit = min(limit, _MAX_LIMIT)

        keywords = [w for w in query.split() if w.strip()]
        matches = search_catalog(self._repository.all(), keywords, limit=limit)
        ranked = rank_candidates(matches)

        if not ranked:
            return {
                "total_candidates": 0,
                "candidates": [],
                "summary_text": (
                    f"'{query}' bo'yicha katalogda hech narsa topilmadi — "
                    "bunday API ZET katalogida yo'q, deb ayting, "
                    "to'qib chiqarmang."
                ),
            }

        lines = [
            f"'{query}' bo'yicha {len(ranked)} ta nomzod topildi "
            "(katalog yozuvi — ijro emas):",
            *[_candidate_line(c) for c in ranked],
        ]

        return {
            "total_candidates": len(ranked),
            "candidates": [
                {
                    "entry_id": c.entry_id,
                    "name": c.name,
                    "provider": c.provider,
                    "category": c.category,
                    "auth_type": c.auth_type.value,
                    "https_supported": c.https_supported,
                    "pricing_status": c.pricing_status,
                    "status": c.status.value,
                    "executable_now": c.status is APIStatus.ENABLED,
                    "composite_score": c.composite_score,
                    "reasons": list(c.reasons),
                }
                for c in ranked
            ],
            "summary_text": "\n".join(lines),
        }


__all__ = ["PublicAPISearchTool"]
