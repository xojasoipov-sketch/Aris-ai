"""Intent Recognizer — buyruq matnini strukturalangan Intent'ga aylantiradi (Z1.7).

Kirish: xom matn ("Ertaga 10:00 uchrashuv haqida eslatma yoz")
Chiqish: `Intent(action="reminder.create", objects=[...], task_class=..., ...)`

Ishlash tartibi:
    1. LLM'ga `tool_use` (function calling) orqali buyruq yuboriladi
    2. LLM `parse_intent` tool'ini chaqiradi
    3. Javob `Intent` Pydantic modeliga validatsiya qilinadi
    4. Agar LLM buzuq javob bersa — 1 marta qayta urinadi
    5. Ikkinchi urinish ham muvaffaqiyatsiz bo'lsa — aniq xato

Bog'liq qarorlar:
    V-29 — task_class Model Router'ga uzatiladi
    A-05 — untrusted kirish alohida belgilanadi
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import structlog

from zet.domain.command import Command, ConversationTurn, Intent
from zet.domain.enums import MessageRole, TaskClass
from zet.llm.base import ChatMessage, ToolSpec
from zet.llm.router import ModelRouter, RouteResult
from zet.prompts.intent import INTENT_SYSTEM, INTENT_TOOL_SCHEMA

log = structlog.get_logger(__name__)

_MAX_RETRIES = 1
"""Buzuq LLM javobi bo'lsa, necha marta qayta urinish."""


def _history_to_messages(history: Sequence[ConversationTurn]) -> list[ChatMessage]:
    """Suhbat tarixini LLM xabarlariga o'giradi (B3 audit, KONSOLIDATSIYA v2).

    `core/executor.py::_history_to_messages` bilan bir xil konvertatsiya
    — bu yerda alohida nusxa ko'chirilgan, chunki `intent.py` `executor.py`
    ga bog'lanmasligi kerak (ular Orchestrator ostida parallel qatlamlar,
    aylanma bog'liqlik yaratmaslik uchun har biri o'z nusxasini saqlaydi).
    """
    return [
        ChatMessage(
            role="user" if turn.role == MessageRole.USER else "assistant",
            content=turn.content,
        )
        for turn in history
    ]


class IntentError(Exception):
    """Intent ajratishda xato."""


class AmbiguousCommandError(IntentError):
    """Buyruq juda noaniq — aniqlashtirish savoli bor."""

    def __init__(self, question: str, partial_intent: Intent) -> None:
        super().__init__(question)
        self.question = question
        self.partial_intent = partial_intent


_INTENT_TOOL = ToolSpec(
    name="parse_intent",
    description="Buyruqdan ajratilgan strukturalangan intent",
    input_schema=INTENT_TOOL_SCHEMA,
)


class IntentRecognizer:
    """Buyruqni Intent'ga aylantiruvchi modul.

    LLM `parse_intent` tool'ini chaqiradi — shu orqali strukturalangan
    javob olinadi (freeform text o'rniga).
    """

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def recognize(
        self,
        command: Command,
        *,
        available_tools: Sequence[str] = (),
        run_id: uuid.UUID | None = None,
    ) -> Intent:
        """Buyruqni tahlil qilib Intent qaytaradi.

        Args:
            command: foydalanuvchi buyrug'i
            available_tools: mavjud tool nomlari (LLM ga hint sifatida)

        Returns:
            Strukturalangan Intent

        Raises:
            AmbiguousCommandError: buyruq noaniq, savol bor
            IntentError: LLM javob bera olmadi
        """
        system = INTENT_SYSTEM
        if available_tools:
            tools_hint = ", ".join(available_tools)
            system += f"\n\nMAVJUD TOOLLAR: {tools_hint}"

        # B3 audit fix (KONSOLIDATSIYA v2): ILGARI faqat `command.text`
        # yuborilardi — "shunga batafsilroq ayt" kabi ergash buyruqlar
        # oldingi almashuv MATNI bo'lmasa nimani anglatishini aniqlay
        # olmasdi (LLM context'siz noaniq/xato intent chiqarardi).
        # `command.history` (ConversationStore'dan) endi LLM'ga
        # ko'rinadi — bu Executor'ning `_think()` javob yozish
        # bosqichida allaqachon qilayotgan narsa, endi Intent
        # bosqichida ham qo'llaniladi.
        messages = [
            *_history_to_messages(command.history),
            ChatMessage(role="user", content=command.text),
        ]

        for attempt in range(_MAX_RETRIES + 1):
            route_result = await self._router.complete(
                task_class=TaskClass.SIMPLE,
                messages=messages,
                system=system,
                tools=[_INTENT_TOOL],
                run_id=run_id,
            )

            intent = self._extract_intent(route_result, command)
            if intent is not None:
                log.info(
                    "intent.recognized",
                    action=intent.action,
                    task_class=intent.task_class.value,
                    ambiguity=intent.ambiguity,
                    confidence=intent.confidence,
                    attempt=attempt,
                )

                if intent.ambiguity == "high" and intent.clarification_question:
                    raise AmbiguousCommandError(
                        question=intent.clarification_question,
                        partial_intent=intent,
                    )
                return intent

            if attempt < _MAX_RETRIES:
                log.warning("intent.retry", attempt=attempt, reason="tool_use yo'q")
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "Iltimos, parse_intent tool'ini chaqiring. "
                            "Faqat shu orqali javob bering."
                        ),
                    )
                )

        raise IntentError(
            f"LLM parse_intent tool'ini chaqirmadi ({_MAX_RETRIES + 1} urinishdan keyin)"
        )

    def _extract_intent(self, route_result: RouteResult, command: Command) -> Intent | None:
        """LLM javobidan Intent ajratadi. tool_use bo'lmasa None qaytaradi."""
        response = route_result.response

        for tu in response.tool_uses:
            if tu.name == "parse_intent":
                return self._parse_tool_args(tu.arguments, command)

        return None

    def _parse_tool_args(self, args: dict[str, Any], command: Command) -> Intent:
        """Tool argumentlarini Intent'ga aylantiradi (buzuq maydonlarga bardoshli)."""
        # task_class ni validatsiya qilish — noto'g'ri qiymat bo'lsa default
        raw_task_class = args.get("task_class", "normal")
        try:
            task_class = TaskClass(raw_task_class)
        except ValueError:
            task_class = TaskClass.NORMAL

        # confidence chegaralash
        raw_confidence = args.get("confidence", 1.0)
        try:
            confidence = max(0.0, min(1.0, float(raw_confidence)))
        except (TypeError, ValueError):
            confidence = 0.5

        return Intent(
            action=str(args.get("action", "unknown")),
            objects=[str(o) for o in (args.get("objects") or [])],
            constraints=[str(c) for c in (args.get("constraints") or [])],
            urgency=str(args.get("urgency", "normal")),
            task_class=task_class,
            requires_tools=[str(t) for t in (args.get("requires_tools") or [])],
            ambiguity=str(args.get("ambiguity", "low")),
            clarification_question=args.get("clarification_question"),
            confidence=confidence,
            original_text=command.text,
            raw_llm_output=args,
        )
