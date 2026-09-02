"""Javob va suhbat tarixi testlari (Z44).

Ega jonli sinovda uchta nosozlik topdi:

  1. "Nimalar qilolasan?" → "...rejasi — 1/1 qadam bajarildi"
     Javob emas, jarayon hisoboti. Sababi: fikrlash qadami (tool'siz
     qadam) HECH NARSA qilmasdi — LLM chaqirilmasdi.

  2. "Tushuntir" → "Nimani tushuntirib berishimni xohlaysiz?"
     Kontekst yo'q. Sababi: har xabar mustaqil run edi, suhbat tarixi
     saqlanmasdi (`conversation`/`message` jadvallariga hech kim
     yozmasdi).

  3. Ekranda "provayder topilmadi — ollama:qwen3-8b".
     Sababi: Ollama kalit talab qilmaydi, ya'ni `is_configured` har
     doim rost — hatto bulutda Ollama umuman yo'q bo'lsa ham.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.config import Env
from zet.core.executor import Executor, StepResult, _history_to_messages
from zet.core.orchestrator import _build_answer
from zet.db.models import Owner
from zet.domain.command import ConversationTurn
from zet.domain.enums import MessageRole, PermissionLevel, StepStatus
from zet.domain.plan import Plan, PlanStep
from zet.llm.factory import build_providers
from zet.memory.conversation import ConversationStore
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


def _step(position: int = 1, *, tool: str | None = None) -> PlanStep:
    return PlanStep(
        position=position,
        description=f"Qadam {position}",
        tool_name=tool,
        permission_required=PermissionLevel.READ,
    )


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


class TestAnswerIsNotAProcessReport:
    """`_build_answer` — ega natijani ko'radi, hisobotni emas."""

    def _ctx(self, *results: StepResult) -> object:
        from zet.core.executor import ExecutionContext

        plan = Plan(summary="reja", steps=[_step(i + 1) for i in range(len(results))])
        ctx = ExecutionContext(plan)
        for i, res in enumerate(results, start=1):
            ctx.record(i, res)
        return ctx

    def test_thinking_output_becomes_the_answer(self) -> None:
        """Ilgari bu yerda "reja — 1/1 qadam bajarildi" chiqardi."""
        ctx = self._ctx(StepResult(_step(), status=StepStatus.DONE, output="ZET buni qila oladi."))

        answer = _build_answer(ctx, plan_summary="imkoniyatlarni tushuntirish rejasi")  # type: ignore[arg-type]

        assert answer == "ZET buni qila oladi."
        assert "qadam bajarildi" not in answer

    def test_multiple_outputs_are_joined(self) -> None:
        ctx = self._ctx(
            StepResult(_step(1), status=StepStatus.DONE, output="Birinchi"),
            StepResult(_step(2), status=StepStatus.DONE, output="Ikkinchi"),
        )

        answer = _build_answer(ctx, plan_summary="reja")  # type: ignore[arg-type]

        assert "Birinchi" in answer
        assert "Ikkinchi" in answer

    def test_duplicate_outputs_are_not_repeated(self) -> None:
        ctx = self._ctx(
            StepResult(_step(1), status=StepStatus.DONE, output="Bir xil"),
            StepResult(_step(2), status=StepStatus.DONE, output="Bir xil"),
        )
        assert _build_answer(ctx, plan_summary="reja") == "Bir xil"  # type: ignore[arg-type]

    def test_failed_steps_are_excluded(self) -> None:
        ctx = self._ctx(
            StepResult(_step(1), status=StepStatus.FAILED, output="chala"),
            StepResult(_step(2), status=StepStatus.DONE, output="to'g'ri"),
        )
        assert _build_answer(ctx, plan_summary="reja") == "to'g'ri"  # type: ignore[arg-type]

    def test_falls_back_to_plan_summary_when_no_text(self) -> None:
        """Jim WRITE tool'lar — ega baribir nima bajarilganini bilsin."""
        ctx = self._ctx(StepResult(_step(), status=StepStatus.DONE))
        assert _build_answer(ctx, plan_summary="eslatma yozildi") == "eslatma yozildi"  # type: ignore[arg-type]


class TestThinkingStepCallsTheModel:
    """Fikrlash qadami endi haqiqiy LLM chaqiruvi."""

    async def test_without_router_stays_silent(self, tool_registry: ToolRegistry) -> None:
        """Router berilmasa eski xatti-harakat — qadam DONE, matn yo'q."""
        executor = Executor(
            registry=tool_registry,
            policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
        )
        plan = Plan(summary="reja", steps=[_step()])

        ctx = await executor.execute_plan(plan)

        assert ctx.results[1].status == StepStatus.DONE
        assert ctx.results[1].output == ""


class TestStepResultText:
    """`StepResult.text` — fikrlash chiqishi yoki tool javobi."""

    def test_prefers_thinking_output(self) -> None:
        assert StepResult(_step(), output="javob").text == "javob"

    def test_empty_when_nothing(self) -> None:
        assert StepResult(_step()).text == ""


class TestHistoryConversion:
    """Domen tarixi → LLM xabarlari."""

    def test_roles_are_mapped(self) -> None:
        turns = [
            ConversationTurn(role=MessageRole.USER, content="Nimalar qilolasan"),
            ConversationTurn(role=MessageRole.ASSISTANT, content="Ko'p narsa"),
        ]

        messages = _history_to_messages(turns)

        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == "Nimalar qilolasan"

    def test_empty_history_is_empty(self) -> None:
        assert _history_to_messages([]) == []


class TestConversationStore:
    """Suhbat tarixi DB'ga yoziladi va qaytariladi."""

    async def test_conversation_is_reused_per_channel(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Bitta kanal = bitta uzluksiz suhbat (V-02: bitta ega)."""
        store = ConversationStore(session, owner_id=owner.id)

        first = await store.get_or_create(channel="telegram")
        second = await store.get_or_create(channel="telegram")

        assert first.id == second.id

    async def test_channels_are_separate(self, session: AsyncSession, owner: Owner) -> None:
        store = ConversationStore(session, owner_id=owner.id)

        telegram = await store.get_or_create(channel="telegram")
        cli = await store.get_or_create(channel="cli")

        assert telegram.id != cli.id

    async def test_history_is_returned_oldest_first(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """LLM eng eskisi birinchi tartibni kutadi."""
        store = ConversationStore(session, owner_id=owner.id)
        conversation = await store.get_or_create(channel="telegram")

        await store.append(conversation, role=MessageRole.USER, content="birinchi")
        await store.append(conversation, role=MessageRole.ASSISTANT, content="ikkinchi")
        await store.append(conversation, role=MessageRole.USER, content="uchinchi")

        history = await store.recent_history(conversation)

        assert [t.content for t in history] == ["birinchi", "ikkinchi", "uchinchi"]

    async def test_limit_keeps_the_most_recent(self, session: AsyncSession, owner: Owner) -> None:
        store = ConversationStore(session, owner_id=owner.id)
        conversation = await store.get_or_create(channel="telegram")
        for i in range(6):
            await store.append(conversation, role=MessageRole.USER, content=f"xabar {i}")

        history = await store.recent_history(conversation, limit=2)

        assert [t.content for t in history] == ["xabar 4", "xabar 5"]

    async def test_system_and_tool_messages_are_skipped(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        """Ular ichki mexanika — ega bilan suhbatning qismi emas."""
        store = ConversationStore(session, owner_id=owner.id)
        conversation = await store.get_or_create(channel="telegram")

        await store.append(conversation, role=MessageRole.SYSTEM, content="tizim")
        await store.append(conversation, role=MessageRole.USER, content="ega")

        history = await store.recent_history(conversation)

        assert [t.content for t in history] == ["ega"]

    async def test_long_content_is_truncated(self, session: AsyncSession, owner: Owner) -> None:
        from zet.memory.conversation import MAX_CONTENT_CHARS

        store = ConversationStore(session, owner_id=owner.id)
        conversation = await store.get_or_create(channel="telegram")

        message = await store.append(
            conversation, role=MessageRole.USER, content="x" * (MAX_CONTENT_CHARS + 500)
        )

        assert len(message.content) == MAX_CONTENT_CHARS


class TestOllamaNotConfiguredInCloud:
    """Bulutda Ollama yo'q — router uni sinab vaqt sarflamasin."""

    def _settings(self, **kwargs: object) -> object:
        from zet.config import Settings

        base: dict[str, object] = {"anthropic_api_key": "k"}
        base.update(kwargs)
        return Settings.model_validate(base)

    def test_configured_in_dev(self) -> None:
        """Lokal ishlash o'zgarmaydi — ADR-0007 local-first."""
        providers = build_providers(self._settings(env=Env.DEV))  # type: ignore[arg-type]
        assert providers["ollama"].is_configured is True

    def test_not_configured_in_prod_with_loopback(self) -> None:
        """Ega ekranidagi 'provayder topilmadi — ollama' shundan edi."""
        providers = build_providers(
            self._settings(env=Env.PROD, api_token="t", ollama_base_url="http://localhost:11434")  # type: ignore[arg-type]
        )
        assert providers["ollama"].is_configured is False

    @pytest.mark.parametrize(
        "url",
        ["http://127.0.0.1:11434", "http://0.0.0.0:11434", "http://localhost:11434"],
    )
    def test_all_loopback_forms_are_recognised(self, url: str) -> None:
        providers = build_providers(
            self._settings(env=Env.PROD, api_token="t", ollama_base_url=url)  # type: ignore[arg-type]
        )
        assert providers["ollama"].is_configured is False, url

    def test_remote_ollama_still_works_in_prod(self) -> None:
        """Uy serveridagi haqiqiy Ollama — o'chirilmaydi."""
        providers = build_providers(
            self._settings(env=Env.PROD, api_token="t", ollama_base_url="http://192.168.1.50:11434")  # type: ignore[arg-type]
        )
        assert providers["ollama"].is_configured is True
