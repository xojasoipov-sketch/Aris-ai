"""Execution Mode — Brain "Workflow har doim yoqilgan emas" qarori (JB-8).

MUAMMO (JB-8 spetsifikatsiyasining o'zi topgan naqsh xavfi): agar Brain
har bir so'rovni avtomatik Workflow'ga aylantirsa — "Bugun qaysi kun?"
kabi oddiy savol ham keraksiz orkestratsiya qatlamiga tushib qoladi.
Workflow — IXTIYORIY ijro rejimi, HAR DOIM YO'Q.

YECHIM: bu modul `Intent` (allaqachon LLM tomonidan klassifikatsiya
qilingan — `request_kind`, `requires_tools`) va buyruq matnining o'zidan
(aniq kalit so'zlar/iboralar) `ExecutionDecision` chiqaradi — QAYSI
ijro rejimi mos: DIRECT_RESPONSE / DIRECT_TOOL / MISSION / TASK_GRAPH /
WORKFLOW / BACKGROUND_WORKFLOW / WORKFLOW_COMMAND.

NEGA DETERMINISTIK (yana bir LLM chaqiruvi EMAS): Intent allaqachon bir
marta LLM orqali klassifikatsiya qilingan (`request_kind`,
`requires_tools`) — buni ustidan yana bir LLM chaqirish (a) keraksiz
xarajat, (b) "Brain → LLM → Router → LLM" aylanma naqshini yaratardi
(JB-7 §15 bilan bir xil tamoyil). Bu qatlam ODDIY, TUSHUNTIRILADIGAN
qoidalar to'plami.

HALOL DOIRA (JB-8, ochiq kamchilik — commit xabarida ham qaytariladi):
    Bu klass FAQAT qaror qiladi va TUSHUNTIRADI. WORKFLOW/
    BACKGROUND_WORKFLOW/WORKFLOW_COMMAND rejimlari uchun `Brain`da
    HALI haqiqiy backend ulanishi YO'Q (`WorkflowRunner` DB-persistent
    emas, Brain hech qachon uni chaqirmaydi) — bu qarorlar to'g'ri
    ANIQLANADI va LOGLANADI, lekin `Brain._handle_goal()` ularni HOZIRCHA
    mavjud Mission yo'liga (yoki WORKFLOW_COMMAND holida — hech narsa
    yangi yaratmasdan Run yo'liga) yo'naltiradi. Bu — "fake ijro" emas:
    hech qanday Workflow/Schedule OBYEKTI SOXTA YARATILMAYDI; shunchaki
    haqiqiy persistent Workflow ijrosi hali qurilmagan (keyingi JB
    uchun ochiq qoldirilgan, pastdagi docstring'da aniq ko'rsatilgan).

Bog'liq qarorlar:
    JB-2 — Brain (request_kind: chat/command/goal)
    JB-5 — Task Graph (2+ taskli mission avtomatik shu yo'lga o'tadi)
    JB-7 — BrainModelRouter (bir xil "deterministik, tushuntirilgan
           qaror" naqshi)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zet.domain.command import Intent


class ExecutionMode(StrEnum):
    """Brain tanlashi mumkin bo'lgan ijro rejimlari (JB-8 §3)."""

    DIRECT_RESPONSE = "direct_response"
    """Modeldan to'g'ridan-to'g'ri javob — tool yo'q, mission yo'q."""

    DIRECT_TOOL = "direct_tool"
    """Bitta darhol amal — bitta tool, persistent holat yo'q."""

    MISSION = "mission"
    """Ko'p qadamli, lekin BIR MARTALIK maqsad — mavjud Mission qatlami
    (saqlanadi, qayta urinadi, xotiraga yozadi — allaqachon "persistent
    operational process", faqat qayta ISHGA TUSHIRILMAYDI)."""

    TASK_GRAPH = "task_graph"
    """MISSION bilan BIR XIL yo'l — faqat tavsifiy belgi: 2+ tool kerak
    bo'lsa `MissionEngine` o'zi avtomatik `TaskGraphExecutor`ga o'tadi
    (JB-5). Bu yerda ALOHIDA chaqiruv yo'li EMAS."""

    WORKFLOW = "workflow"
    """Aniq so'ralgan yoki bosqichma-bosqich/persistent jarayon.
    HOZIRCHA: MISSION yo'liga tushadi (real Workflow backend yo'q —
    yuqoridagi modul docstring'iga qarang)."""

    BACKGROUND_WORKFLOW = "background_workflow"
    """Takrorlanuvchi/rejalashtirilgan jarayon ("har kuni soat 9da").
    HOZIRCHA: MISSION yo'liga tushadi, TAKRORLANMAYDI (Scheduler'ga
    ulanish keyingi JB)."""

    WORKFLOW_COMMAND = "workflow_command"
    """Mavjud workflow ustida amal (ko'rsat/to'xtat/davom ettir/bekor
    qil/qayta ishga tushir) — YANGI HECH NARSA YARATILMAYDI."""


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    """Brain'ning ijro rejimi qarori — HAR DOIM tushuntirilgan (JB-8 §9/§16)."""

    mode: ExecutionMode
    reason: str
    confidence: float = 1.0
    persistent: bool = False
    """`True` — jarayon so'rovlar/restart/vaqt oralig'ida saqlanishi kerak
    (WORKFLOW/BACKGROUND_WORKFLOW/MISSION uchun)."""


# ── Kalit so'z/ibora to'plamlari ────────────────────────────────────
#
# NEGA oddiy substring, regex emas ko'pchiligida: buyruqlar qisqa,
# tabiiy til iboralari ("workflow qilib qo'y") — murakkab regex ortiqcha
# murakkablik qo'shardi, oddiy pastki registr substring qidiruvi yetarli
# va tushunarli (audit qilish oson).

_WORKFLOW_WORD_RE = re.compile(r"\bworkflow\w*\b", re.IGNORECASE)
"""`workflow`, `workflowni`, `workflowlarimni`, `workflow'ni` — hammasini tutadi."""

_AVOID_WORKFLOW_PHRASES = (
    "workflow qilma",
    "workflow yarat ma",
    "faqat hozir",
    "hozir bir marta",
    "bir marta qilib ber",
    "hozircha shunchaki",
    "workflow kerak emas",
)
"""JB-8 §11 — foydalanuvchi ANIQ ravishda workflow'dan voz kechsa, bu
BOSHQA barcha workflow signallaridan USTUN turadi (birinchi tekshiriladi)."""

_WORKFLOW_COMMAND_VERBS = (
    "to'xtat",
    "toxtat",
    "bekor qil",
    "davom ettir",
    "qayta ishga tushir",
    "holati",
    "ko'rsat",
    "korsat",
    "resume",
    "pause",
    "cancel",
    "stop",
    "status",
    "list",
    "show",
    "restart",
)
"""JB-8 §12 — mavjud workflow ustida amal (yangi yaratish EMAS)."""

_WORKFLOW_CREATE_PHRASES = (
    "workflow qilib",
    "workflow sifatida",
    "workflow yarat",
    "avtomatlashtir",
    "pipeline",
    "process qilib",
)
"""JB-8 §2/§6 — ANIQ workflow yaratish so'rovi (bir martalik, lekin
persistent/bosqichma-bosqich jarayon)."""

_RECURRING_PHRASES = (
    "har kuni",
    "har hafta",
    "har oy",
    "muntazam",
    "doimiy",
    "davriy",
    "har safar",
    "daily",
    "every day",
    "every week",
    "schedule",
    "rejalashtir",
)
"""JB-8 §6/§14 — takrorlanuvchi/fon jarayoni signali (BACKGROUND_WORKFLOW)."""

_MULTISTAGE_PERSIST_PHRASES = (
    "bosqichma-bosqich",
    "har bosqich natijasini saqla",
    "jarayonni saqla",
)
"""JB-8 §2 — aniq "workflow" so'zisiz ham persistent ko'p bosqichli
jarayon so'ralgani (masalan "Bu ishni bosqichma-bosqich yuritib, har
bosqich natijasini saqla")."""


class ExecutionModeClassifier:
    """`Intent` + buyruq matnidan `ExecutionDecision` chiqaradi (JB-8).

    Ustuvorlik tartibi (birinchi mos kelgani g'olib):
        1. Workflow'dan ANIQ voz kechish — barcha workflow signallarini bosadi.
        2. Workflow buyrug'i (mavjudini boshqarish) — YANGI hech narsa yaratmaydi.
        3. Takrorlanuvchi/rejalashtirilgan signal → BACKGROUND_WORKFLOW.
        4. Aniq workflow yaratish so'rovi (kalit so'z yoki ko'p bosqichli
           persistent ibora) → WORKFLOW.
        5. Aks holda — `Intent.request_kind`/`requires_tools`dan MINIMAL
           mos rejim (JB-8 §5: "Use the simplest execution mechanism").
    """

    def classify(self, intent: Intent, *, text: str | None = None) -> ExecutionDecision:
        raw_text = (text if text is not None else intent.original_text) or ""
        lowered = raw_text.lower()

        # 1) ANIQ voz kechish — hamma narsadan ustun.
        if any(phrase in lowered for phrase in _AVOID_WORKFLOW_PHRASES):
            base = self._base_decision(intent)
            return ExecutionDecision(
                mode=base.mode,
                reason=f"foydalanuvchi workflow'dan aniq voz kechdi — {base.reason}",
                confidence=base.confidence,
                persistent=base.persistent,
            )

        has_workflow_word = bool(_WORKFLOW_WORD_RE.search(lowered))

        # 2) Mavjud workflow ustida amal — yangi hech narsa yaratilmaydi.
        if has_workflow_word and any(v in lowered for v in _WORKFLOW_COMMAND_VERBS):
            return ExecutionDecision(
                mode=ExecutionMode.WORKFLOW_COMMAND,
                reason="mavjud workflow ustida amal so'raldi (ko'rsat/to'xtat/davom ettir/bekor qil)",
                confidence=0.9,
                persistent=True,
            )

        # 3) Takrorlanuvchi/fon jarayoni.
        if any(phrase in lowered for phrase in _RECURRING_PHRASES):
            return ExecutionDecision(
                mode=ExecutionMode.BACKGROUND_WORKFLOW,
                reason="takrorlanuvchi/rejalashtirilgan jarayon so'raldi",
                confidence=0.85,
                persistent=True,
            )

        # 4) Aniq (bir martalik) workflow yaratish so'rovi.
        if (has_workflow_word and any(p in lowered for p in _WORKFLOW_CREATE_PHRASES)) or any(
            p in lowered for p in _MULTISTAGE_PERSIST_PHRASES
        ):
            return ExecutionDecision(
                mode=ExecutionMode.WORKFLOW,
                reason="foydalanuvchi ANIQ workflow/persistent ko'p bosqichli jarayon so'radi",
                confidence=0.85,
                persistent=True,
            )

        # 5) Minimal mos rejim — Intent asosida.
        return self._base_decision(intent)

    def _base_decision(self, intent: Intent) -> ExecutionDecision:
        """JB-8 §5 "minimal execution principle" — eng oddiy yetarli mexanizm.

        `TASK_GRAPH` bu yerda ALOHIDA yo'l EMAS — u faqat "MissionEngine
        ichida 2+ tool bo'lsa avtomatik TaskGraphExecutor ishga tushadi"
        degan HAQIQATNI tushuntirish uchun label (JB-5, o'zgartirilmagan).
        """
        if intent.request_kind == "chat":
            return ExecutionDecision(
                mode=ExecutionMode.DIRECT_RESPONSE,
                reason="oddiy savol/suhbat — tool yoki persistent holat kerak emas",
            )

        if intent.request_kind == "goal":
            tool_count = len(intent.requires_tools)
            if tool_count >= 2:
                return ExecutionDecision(
                    mode=ExecutionMode.TASK_GRAPH,
                    reason=(
                        f"ko'p qadamli maqsad, {tool_count} ta tool kerak — "
                        "Mission ichida Task Graph avtomatik ishga tushadi"
                    ),
                    persistent=True,
                )
            return ExecutionDecision(
                mode=ExecutionMode.MISSION,
                reason="ko'p qadamli, bir martalik maqsad — Mission yetarli",
                persistent=True,
            )

        # request_kind == "command" (yoki noma'lum — fail-safe eng oddiysi)
        if not intent.requires_tools:
            return ExecutionDecision(
                mode=ExecutionMode.DIRECT_RESPONSE,
                reason="bitta topshiriq, tool talab qilinmaydi",
            )
        if len(intent.requires_tools) == 1:
            return ExecutionDecision(
                mode=ExecutionMode.DIRECT_TOOL,
                reason=f"bitta darhol amal ('{intent.requires_tools[0]}') — workflow ortiqcha",
            )
        return ExecutionDecision(
            mode=ExecutionMode.TASK_GRAPH,
            reason=(
                f"bitta buyruq, lekin {len(intent.requires_tools)} ta tool kerak — "
                "Mission ichida Task Graph avtomatik ishga tushadi"
            ),
        )


__all__ = ["ExecutionDecision", "ExecutionMode", "ExecutionModeClassifier"]
