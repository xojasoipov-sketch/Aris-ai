"""memory.search — ZET o'z uzoq muddatli xotirasidan qidiradi (Z45.2).

NEGA BU TOOL KERAK BO'LDI.

Ega o'zi haqidagi profilni yukladi va u `memory_entries` jadvalida
turibdi. Fikrlash qadami uni avtomatik eslaydi (`Executor.recall`).
Lekin **Planner** xotira borligini bilmasdi — u faqat tool ro'yxatini
ko'radi, u yerda xotira yo'q edi. Natijada "Men kimman?" degan savolga
reja shunday chiqdi:

    0. note.list
    1. note.read("user_profile")     ← bunday fayl yo'q, o'ylab topilgan
    2. javob yozish (depends_on: [0, 1])

1-qadam uch marta yiqildi, 2-qadam "dependency_not_ready" bo'lib
umuman ishga tushmadi — ya'ni javob yozadigan qadamgacha yetib
borilmadi va run FAILED bo'ldi. Xotira bor edi, unga yo'l yo'q edi.

Endi Planner "xotiradan qidir" degan haqiqiy qadam qo'ya oladi.

SESSIYA. Tool registry global singleton (`lru_cache`), xotira esa DB
sessiyasiga bog'liq. Shuning uchun tool sessiyani emas — **sessiya
fabrikasini** oladi va har chaqiruvda o'zi qisqa sessiya ochadi.

Ruxsat: READ — faqat o'qish.
Trust: SYSTEM — mazmun ega o'zi yozgan, tashqi manba emas.

Bog'liq qarorlar:
    V-13 — xotira qatlamlari
    V-31 — READ ruxsat darajasi
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.domain.memory import MemorySearchResult

# `Callable`/`Awaitable` ish vaqtida ham kerak — alias modul yuklanganda
# hisoblanadi, TYPE_CHECKING bloki esa u paytda ishlamaydi.
SearchFn = Callable[[str, int, float], "Awaitable[list[MemorySearchResult]]"]
"""(so'rov, limit, min_similarity) → natijalar."""

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
DEFAULT_MIN_SIMILARITY = 0.3
"""Tool chegarasi javob zanjiridagidan (0.35) biroz past.

Bu yerda LLM natijani o'zi ko'rib chiqadi va keraksizini tashlab
yuboradi; avtomatik eslashda esa hamma narsa to'g'ridan-to'g'ri
promptga tushadi, shuning uchun u yerda qattiqroq chegara kerak."""


class MemorySearchTool(Tool):
    """Uzoq muddatli xotiradan ma'noga qarab qidiradi.

    `search_fn` berilmasa tool ochiq xato qaytaradi — jimgina bo'sh
    ro'yxat emas. Aks holda "xotira yo'q" va "xotirada hech nima yo'q"
    bir xil ko'rinadi va Planner qayta-qayta shu qadamni qo'yaverardi.
    """

    def __init__(self, *, search_fn: SearchFn | None = None) -> None:
        self._search_fn = search_fn

    @property
    def name(self) -> str:
        return "memory.search"

    @property
    def description(self) -> str:
        return (
            "ZET uzoq muddatli xotirasidan ma'noga qarab qidiradi — ega haqidagi "
            "ma'lumot, oldingi qarorlar, o'rganilgan bilim va saqlangan xulosalar. "
            "Ega haqida savol berilsa (kim, nima ish qiladi, qaysi loyihalar, "
            "nimani yoqtiradi) AVVAL shu tooldan foydalan."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Qidiruv matni — savolni o'z so'zlaring bilan yoz",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Nechta yozuv qaytarilsin (1-{MAX_LIMIT})",
                    "default": DEFAULT_LIMIT,
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

    @property
    def timeout_s(self) -> int:
        # Embedding API chaqiruvi bor — 5 soniya kam bo'lishi mumkin.
        return 30

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._search_fn is None:
            raise ToolError("Xotira ulanmagan — memory.search ishlamaydi")

        query = str(params.get("query", "")).strip()
        if not query:
            raise ToolError("`query` bo'sh bo'lmasligi kerak")

        limit = max(1, min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT))
        results = await self._search_fn(query, limit, DEFAULT_MIN_SIMILARITY)

        return {
            "query": query,
            "total": len(results),
            "entries": [
                {
                    "summary": r.entry.summary or "",
                    "content": r.entry.content,
                    "layer": r.entry.layer.value,
                    "similarity": round(r.similarity, 3),
                }
                for r in results
            ],
        }


__all__ = ["DEFAULT_MIN_SIMILARITY", "MemorySearchTool", "SearchFn"]
