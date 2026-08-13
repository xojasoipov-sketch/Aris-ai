"""memory.write — agent uzoq muddatli xotiraga yozadi (Bo'lim 2, V-13).

NEGA BU TOOL KERAK BO'LDI.

Ilgari `memory.search` bor edi, `memory.write` esa yo'q — agentlar
xotirani faqat O'QIY olar edi. Natijada:

    - Research agenti veb'dan yangi ma'lumot o'rgansa, uni xotiraga
      saqlay olmasdi — keyingi run yana noldan boshlashardi.
    - Sales agenti mijoz haqida qaror qabul qilsa, u qaror yo'qolardi
      (CRM'ga yozish alohida masala, lekin agent xotirasi yo'q).
    - Har savol izolatsiyalangan — agent hech qachon `o'sib bormasdi`.

Bu tool xotira qatlamlariga trust_level va layer'ga qarab yozadi:
    - KNOWLEDGE — o'rganilgan bilim (research natijasi)
    - BUSINESS — mijoz/sotuv qarorlari
    - PROJECT/TASK — loyiha/vazifa konteksti
    - SHORT_TERM — vaqtincha (24 soat TTL)

XAVFSIZLIK — trust_level bilan bog'liq siyosat.

`memory/policy.py::WRITE_POLICY` allaqachon bor edi, lekin API/tool
darajasida hech qayerdan tekshirilmasdi. Endi bu yerda tekshiriladi:

    - Agent trust=SYSTEM → OWNER/KNOWLEDGE qatlamlariga YOZA OLMAYDI
    - UNTRUSTED trust → faqat SHORT_TERM

Ya'ni tashqi manbalardan (`web.read`) kelgan ma'lumot doimiy xotiraga
tushib qolmasin — u SHORT_TERM'da izolyatsiyalanadi va TTL bilan
o'chib ketadi. Buni PermissionPolicy `Executor.trust_level`ni tanlashi
bilan birga ishlaydi (A-05 dinamik trust oqimi).

Ruxsat: WRITE — real yozish.
Trust: KO'RSATILGAN qiymat (agent trust_level'iga qarab tekshiriladi).

Bog'liq qarorlar:
    V-13 — xotira qatlamlari
    V-31 — WRITE ruxsat darajasi
    A-05 — trust-level dinamik oqim
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from zet.domain.enums import PermissionLevel
from zet.domain.memory import MemoryLayer
from zet.memory.policy import MemoryPolicyError, check_write
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.domain.memory import MemoryEntry

WriteFn = Callable[..., "Awaitable[MemoryEntry]"]
"""(layer, content, summary, tags, trust_level, ttl_hours) → MemoryEntry."""

MAX_CONTENT_CHARS = 8000
"""Xotira yozuvi eng ko'p shuncha belgi. Uzun matnlar noteshka
(`note.write`) uchun mos — xotira aksincha qisqa xulosalar."""


class MemoryWriteTool(Tool):
    """Uzoq muddatli xotiraga qatlam va trust_level bilan yozadi.

    `write_fn` berilmasa — ochiq xato. Aks holda "xotira yo'q" va
    "yozildi" farqi bilinmasdi.
    """

    def __init__(self, *, write_fn: WriteFn | None = None) -> None:
        self._write_fn = write_fn

    @property
    def name(self) -> str:
        return "memory.write"

    @property
    def description(self) -> str:
        return (
            "ZET uzoq muddatli xotirasiga yozadi — o'rganilgan bilim, "
            "muhim qaror, mijoz haqida yangi ma'lumot. Qaysi qatlamga "
            "yozish tavsiyalari:\n"
            "  - KNOWLEDGE: umumiy o'rganilgan bilim (web'dan tekshirilgan)\n"
            "  - BUSINESS: sotuv/mijoz qarorlari\n"
            "  - PROJECT/TASK: loyiha yoki vazifa konteksti\n"
            "  - SHORT_TERM: vaqtincha, 24 soat ichida keraksiz bo'ladigan\n"
            "OWNER/PERSONAL qatlamlariga faqat egaya tegishli tool yoza oladi."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "layer": {
                    "type": "string",
                    "enum": [layer.value for layer in MemoryLayer],
                    "description": "Qaysi qatlamga yoziladi",
                },
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_CONTENT_CHARS,
                    "description": "Yozuv matni (qisqa xulosa, uzun matnni note.write ishlat)",
                },
                "summary": {
                    "type": "string",
                    "maxLength": 500,
                    "description": "Bir qatorli xulosa (qidiruv natijasida ko'rinadi)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                    "description": "Filtr uchun teglar",
                },
                "ttl_hours": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 24 * 90,  # 90 kun
                    "description": "Yozuv necha soat yashaydi (default: qatlamga qarab)",
                },
            },
            "required": ["layer", "content"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        # Bir xil content ikki marta yozilsa ikki yozuv paydo bo'ladi.
        return False

    @property
    def timeout_s(self) -> int:
        return 30

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        if self._write_fn is None:
            raise ToolError("Xotira ulanmagan — memory.write ishlamaydi")

        layer_str = str(params["layer"])
        try:
            layer = MemoryLayer(layer_str)
        except ValueError as exc:
            raise ToolError(f"Noto'g'ri qatlam: {layer_str}") from exc

        # ExecutionContext orqali chaqiruvchi agentning trust_level'i
        # `_execute` yopilmasida ko'rinmaydi — Tool interfeysi hozir uni
        # uzatmaydi. Trust siyosati Executor'ga qadar tekshiriladigan
        # nuqta A-05 dinamik oqimida hal qilinadi (`core/executor.py`
        # `_propagate_trust`). Bu tool esa xato qatlamga yozishga yo'l
        # qo'ymaslikni WRITE_POLICY orqali qo'shimcha qavat qiladi —
        # default trust=SYSTEM taxmini bilan.
        trust_level = str(params.get("trust_level", "system"))
        try:
            check_write(trust_level, layer)
        except MemoryPolicyError as exc:
            raise ToolError(str(exc)) from exc

        content = str(params["content"]).strip()
        if not content:
            raise ToolError("`content` bo'sh bo'lmasligi kerak")

        summary = str(params.get("summary", "")).strip() or None
        tags = list(params.get("tags", []) or [])
        ttl_hours = params.get("ttl_hours")

        entry = await self._write_fn(
            layer=layer,
            content=content,
            summary=summary,
            tags=tags,
            trust_level=trust_level,
            ttl_hours=ttl_hours,
        )
        return {
            "id": str(entry.id),
            "layer": entry.layer.value,
            "summary": entry.summary or "",
            "tags": list(entry.tags),
        }


__all__ = ["MAX_CONTENT_CHARS", "MemoryWriteTool", "WriteFn"]
