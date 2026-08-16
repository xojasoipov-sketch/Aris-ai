"""ToolSubstitutionResolver — muqobil (bir xil vazifani bajaruvchi) tool
tanlash (JB-15 PART II).

AUDIT TOPILMASI (JB-14'da ATAYLAB qoldirilgan, JB-15 endi yopadi):
`TaskGraphExecutor` TOOL-sinf xatosidan keyin FAQAT muqobil AGENT
tanlay olardi (`AgentSelector` orqali, JB-14) — muqobil TOOL degan
tushuncha umuman yo'q edi. Agar muammo agentda emas, TOOLNING O'ZIDA
bo'lsa (masalan bitta xizmat butunlay ishlamay qolsa), boshqa agentga
o'tish yordam bermaydi — kerak bo'lgani BOSHQA, mos TOOL.

Bu modul — spec §10-12 talab qilgan "xavfsiz rezolver": u LLM'ga hech
narsa "o'ylab topishga" RUXSAT BERMAYDI, faqat `ToolRegistry`dagi
MAVJUD metadata (`Tool.capability_tag`/`permission_level`/`risk_level`)
asosida, DETERMINISTIK qaror qabul qiladi.

MA'LUM CHEKLOV (ochiq e'lon qilingan, AUDIT natijasi): joriy tool
katalogida (barcha `tools/builtin/*.py`) HALI HECH QANDAY IKKITA tool
bir xil `capability_tag`ga ega EMAS — repo'da hozircha "bir xil
vazifani bajaruvchi ikkita mustaqil tool" DEGAN JUFTLIK YO'Q (masalan
ikkita turli "xabar yuborish" xizmati). Shu sabab bu mexanizm ISHLAB
TURGAN, HAQIQIY, PRODUCTIONga ulangan kod — lekin BUGUNGI kunda
tabiiy ravishda 0 ta ishga tushirishga tayyor juft topadi (testlar
buni ro'yxatdan o'tkazilgan STUB tool'lar bilan isbotlaydi — xuddi
JB-14'ning `AgentSelector` muqobil-agent testlari kabi). Yangi tool
qo'shilib, mavjudi bilan BIR XIL `capability_tag` bersa — mexanizm
DARHOL, kod o'zgarishisiz ishga tushadi.

Bog'liq qarorlar:
    JB-15 PART II — tool intelligence
    JB-14 PART II — `AgentSelector` orqali muqobil AGENT (bu modul bilan
        BIRGA, KETMA-KET ishlatiladi — `core/task_graph.py`, birinchi
        muqobil TOOL, keyin muqobil AGENT)
    V-31 — ruxsat darajalari (substitutsiya buni HECH QACHON oshirmaydi)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from zet.domain.enums import PermissionLevel

if TYPE_CHECKING:
    from zet.tools.base import Tool
    from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolSubstitutionDecision:
    """Bitta muvaffaqiyatli substitutsiya — audit/log uchun (spec §17)."""

    original_tool: str
    alternative_tool: str
    capability_tag: str


class ToolSubstitutionResolver:
    """`failed_tool_name`ga MOS boshqa `Tool` topadi — yoki `None`.

    HECH QACHON:
        - LLM'dan so'ramaydi / LLM natijasini qabul qilmaydi (spec §12
          "Never allow LLM to invent a tool substitution").
        - ruxsat darajasini OSHIRMAYDI (READ↔WRITE almashinuvi YO'Q).
        - xavf darajasini OSHIRMAYDI (past→yuqori almashinuv YO'Q).
        - o'zini o'zi yoki `exclude`dagilarni tanlamaydi.
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._tools = tool_registry

    def find_alternative(
        self,
        failed_tool_name: str,
        *,
        caller_permission: PermissionLevel,
        exclude: frozenset[str] = frozenset(),
    ) -> Tool | None:
        """Muqobil `Tool` — yoki `None` (muqobil yo'q/xavfsiz emas).

        Args:
            failed_tool_name: muvaffaqiyatsiz bo'lgan tool nomi.
            caller_permission: chaqiruvchi AGENTning ruxsat darajasi
                (`AgentSpec.permission_level`) — nomzod shundan YUQORI
                ruxsat talab qilsa, RAD ETILADI (V-31, oshirilmaydi).
            exclude: oldin allaqachon sinalgan (yoki bila turib rad
                etilgan) tool nomlari — cheksiz aylanma tanlovni oldini
                oladi.

        Xavfsizlik qoidalari (spec §12, HAMMASI qattiq — birinchi mos
        kelmagani darhol RAD ETADI):
            1. `capability_tag` ANIQ bir xil (ikkalasi ham `None` bo'lsa
               — MOS EMAS, "teg yo'q" hech kim bilan mos kelmaydi).
            2. `permission_level` ANIQ bir xil (READ tool WRITE tool
               bilan, aksincha — HECH QACHON almashtirilmaydi).
            3. `risk_level.rank` — muvaffaqiyatsiz tool'nikidan OSHMAYDI
               (past xavfni yuqori xavf bilan avtomatik almashtirish
               YO'Q — avtorizatsiz eskalatsiya).
            4. `caller_permission >= nomzod.permission_level`.

        Bir nechta mos nomzod bo'lsa — nom bo'yicha alifbo tartibida
        BIRINCHISI tanlanadi (deterministik, `AgentSelector`ning
        alifbo-tie-break naqshi bilan bir xil, JB-14)."""
        try:
            failed_tool = self._tools.get(failed_tool_name)
        except Exception:
            return None

        tag = failed_tool.capability_tag
        if tag is None:
            return None

        candidates: list[Tool] = []
        for candidate in self._tools.list_tools():
            if candidate.name == failed_tool_name or candidate.name in exclude:
                continue
            if candidate.capability_tag != tag:
                continue
            if candidate.permission_level != failed_tool.permission_level:
                continue
            if candidate.risk_level.rank > failed_tool.risk_level.rank:
                continue
            if caller_permission < candidate.permission_level:
                continue
            candidates.append(candidate)

        if not candidates:
            return None

        candidates.sort(key=lambda t: t.name)
        chosen = candidates[0]
        log.info(
            "tool_substitution.resolved",
            failed_tool=failed_tool_name,
            alternative=chosen.name,
            capability_tag=tag,
        )
        return chosen


__all__ = ["ToolSubstitutionDecision", "ToolSubstitutionResolver"]
