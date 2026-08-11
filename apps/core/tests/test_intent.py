"""Z1.7 — Intent Recognizer testlari.

FakeProvider bilan deterministik testlar — LLM'ga chiqilmaydi.
LLM javobini tool_use orqali simulyatsiya qiladi.

Tekshiriladi:
    - Oddiy buyruqlar to'g'ri action va task_class oladi
    - Noaniq buyruq AmbiguousCommandError beradi
    - LLM tool chaqirmasa — retry va keyin IntentError
    - Buzuq tool argumentlari — xavfsiz default'lar
    - O'zbek va ingliz tilida ishlaydi
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Settings
from zet.core.intent import AmbiguousCommandError, IntentError, IntentRecognizer
from zet.domain.command import Command
from zet.domain.enums import TaskClass
from zet.llm.base import ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter

# FakeProvider nomi "ollama" — chunki Router SIMPLE task uchun birinchi
# nomzod "ollama:qwen3-8b" (provider="ollama") ni qidiradi.
_PROVIDER_NAME = "ollama"


def _fixed_now() -> datetime:
    return datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)


def _make_recognizer(session: AsyncSession, provider: FakeProvider) -> IntentRecognizer:
    """Test uchun IntentRecognizer yaratish."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(
        providers={provider.name: provider},
        session=session,
        settings=settings,
        now_fn=_fixed_now,
    )
    return IntentRecognizer(router)


def _intent_tool_use(
    action: str = "reminder.create",
    objects: list[str] | None = None,
    task_class: str = "normal",
    ambiguity: str = "low",
    confidence: float = 0.95,
    clarification_question: str | None = None,
    requires_tools: list[str] | None = None,
    urgency: str = "normal",
    constraints: list[str] | None = None,
) -> ToolUse:
    """parse_intent tool chaqiruvini yaratish."""
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="parse_intent",
        arguments={
            "action": action,
            "objects": objects or [],
            "constraints": constraints or [],
            "urgency": urgency,
            "task_class": task_class,
            "requires_tools": requires_tools or [],
            "ambiguity": ambiguity,
            "clarification_question": clarification_question,
            "confidence": confidence,
        },
    )


def _fake(**kwargs: object) -> FakeProvider:
    """Katalogga mos FakeProvider yaratish."""
    return FakeProvider(name=_PROVIDER_NAME, **kwargs)  # type: ignore[arg-type]


class TestIntentRecognizer:
    async def test_simple_reminder(self, session: AsyncSession) -> None:
        """Oddiy eslatma buyrug'i to'g'ri tahlil qilinadi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="reminder.create",
                            objects=["uchrashuv", "10:00"],
                            task_class="normal",
                            requires_tools=["time.now", "note.write"],
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Ertaga 10:00 uchrashuv eslatmasi yoz"))

        assert intent.action == "reminder.create"
        assert "uchrashuv" in intent.objects
        assert intent.task_class == TaskClass.NORMAL
        assert intent.original_text == "Ertaga 10:00 uchrashuv eslatmasi yoz"
        assert intent.confidence == 0.95

    async def test_coding_task(self, session: AsyncSession) -> None:
        """Kod yozish buyrug'i coding task_class oladi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="code.write",
                            task_class="coding",
                            confidence=0.9,
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="FastAPI endpoint yoz"))

        assert intent.task_class == TaskClass.CODING

    async def test_ambiguous_raises(self, session: AsyncSession) -> None:
        """Noaniq buyruq AmbiguousCommandError beradi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="unknown",
                            ambiguity="high",
                            clarification_question="Nimani tuzatish kerak?",
                            confidence=0.3,
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)

        with pytest.raises(AmbiguousCommandError) as exc:
            await recognizer.recognize(Command(text="Uni tuzat"))

        assert exc.value.question == "Nimani tuzatish kerak?"
        assert exc.value.partial_intent.ambiguity == "high"

    async def test_no_tool_use_retries(self, session: AsyncSession) -> None:
        """LLM tool chaqirmasa — bitta retry, keyin IntentError."""
        provider = _fake(
            scripted=[
                fake_response(text="Bu buyruqni tushundim"),
                fake_response(text="Bajaraman!"),
            ]
        )
        recognizer = _make_recognizer(session, provider)

        with pytest.raises(IntentError, match="parse_intent"):
            await recognizer.recognize(Command(text="Eslatma yoz"))

        # 2 chaqiruv: asl + retry
        assert len(provider.calls) == 2

    async def test_retry_succeeds_on_second_attempt(self, session: AsyncSession) -> None:
        """Birinchi urinish tool_use'siz, ikkinchisi muvaffaqiyatli."""
        provider = _fake(
            scripted=[
                fake_response(text="Tushundim"),
                fake_response(
                    text="",
                    tool_uses=(_intent_tool_use(action="note.write"),),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Eslatma yoz"))

        assert intent.action == "note.write"
        assert len(provider.calls) == 2

    async def test_invalid_task_class_defaults(self, session: AsyncSession) -> None:
        """Noto'g'ri task_class → default NORMAL."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        ToolUse(
                            id="tu_1",
                            name="parse_intent",
                            arguments={
                                "action": "test",
                                "objects": [],
                                "constraints": [],
                                "urgency": "normal",
                                "task_class": "nonexistent_class",
                                "requires_tools": [],
                                "ambiguity": "low",
                                "confidence": 0.8,
                            },
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Test"))

        assert intent.task_class == TaskClass.NORMAL

    async def test_confidence_clamped(self, session: AsyncSession) -> None:
        """Confidence 0-1 orasida chegaralanadi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(_intent_tool_use(confidence=5.0),),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Test"))
        assert intent.confidence == 1.0

    async def test_negative_confidence_clamped(self, session: AsyncSession) -> None:
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(_intent_tool_use(confidence=-1.0),),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Test"))
        assert intent.confidence == 0.0

    async def test_available_tools_passed_to_system(self, session: AsyncSession) -> None:
        """Mavjud toollar system promptga qo'shiladi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="time.check",
                            requires_tools=["time.now"],
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        await recognizer.recognize(
            Command(text="Soat necha?"),
            available_tools=["time.now", "note.write"],
        )

        call = provider.calls[0]
        system = str(call.get("system", ""))
        assert "time.now" in system
        assert "note.write" in system

    async def test_wrong_tool_name_ignored(self, session: AsyncSession) -> None:
        """LLM boshqa tool chaqirsa (parse_intent emas) — retry."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        ToolUse(
                            id="tu_1",
                            name="wrong_tool",
                            arguments={"result": "boshqa"},
                        ),
                    ),
                ),
                fake_response(
                    text="",
                    tool_uses=(_intent_tool_use(action="note.write"),),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="Eslatma yoz"))
        assert intent.action == "note.write"

    async def test_uzbek_command(self, session: AsyncSession) -> None:
        """O'zbek tilidagi buyruq ishlaydi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="note.write",
                            objects=["eslatma matni"],
                            constraints=["o'zbek tilida"],
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="O'zbek tilida eslatma yoz"))

        assert intent.action == "note.write"
        assert "o'zbek tilida" in intent.constraints

    async def test_complex_task_uses_complex_class(self, session: AsyncSession) -> None:
        """Murakkab vazifa complex task_class oladi."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="analysis.deep",
                            task_class="complex",
                            objects=["loyiha arxitekturasi"],
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(
            Command(text="Loyiha arxitekturasini to'liq tahlil qil va taklif ber")
        )
        assert intent.task_class == TaskClass.COMPLEX

    async def test_high_ambiguity_without_question_no_error(self, session: AsyncSession) -> None:
        """ambiguity=high lekin clarification_question=None → xato emas."""
        provider = _fake(
            scripted=[
                fake_response(
                    text="",
                    tool_uses=(
                        _intent_tool_use(
                            action="unknown",
                            ambiguity="high",
                            clarification_question=None,
                            confidence=0.3,
                        ),
                    ),
                ),
            ]
        )
        recognizer = _make_recognizer(session, provider)
        intent = await recognizer.recognize(Command(text="buni qil"))
        assert intent.ambiguity == "high"
