"""TaskGraphExecutor testlari (JB-5).

Bu testlar `TaskGraphExecutor.run()`ning HAQIQIY xatti-harakatini
tekshiradi — soxta "muvaffaqiyat" emas: har bir tool chaqiruvi haqiqiy
`_StubTool._execute()` orqali sanaladi, agent tanlovi haqiqiy
`AgentRegistry` orqali, ruxsat esa haqiqiy `PermissionPolicy`/
`AgentRuntime` orqali tekshiriladi.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from zet.agents.registry import AgentRegistry
from zet.core.mission import Mission, MissionTask
from zet.core.task_graph import TaskGraphCycleError, TaskGraphExecutor, _tasks_to_batches
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, RiskLevel, StepStatus
from zet.llm.fake import FakeProvider, fake_response
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    """Chaqiruvlarni hisoblovchi, xatti-harakati konfiguratsiya qilinadigan tool."""

    def __init__(
        self,
        name: str,
        *,
        outcomes: list[Any] | None = None,
        risk: RiskLevel = RiskLevel.LOW,
        sleep_s: float = 0.0,
    ) -> None:
        self._name = name
        self._outcomes = list(outcomes or ["ok"])
        self._risk = risk
        self._sleep_s = sleep_s
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def risk_level(self) -> RiskLevel:
        return self._risk

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls.append(params)
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _agent_spec(
    name: str,
    *,
    tools: list[str],
    model_policy: ModelTier = ModelTier.T1_FREE,
    max_steps: int = 10,
) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=model_policy,
        permission_level=PermissionLevel.WRITE,
        max_steps=max_steps,
    )


def _mission(*, tasks: list[MissionTask]) -> Mission:
    return Mission(owner_id=uuid.uuid4(), objective="test mission", tasks=tasks)


def _executor(
    *,
    agent_registry: AgentRegistry,
    tool_registry: ToolRegistry,
    provider: FakeProvider | None = None,
    max_retries: int = 1,
    task_timeout_s: float | None = 5,
) -> TaskGraphExecutor:
    return TaskGraphExecutor(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
        llm_provider=provider,
        max_retries=max_retries,
        task_timeout_s=task_timeout_s,
    )


class TestBatching:
    """Kahn algoritmi to'g'ri ishlaydimi — mustaqil parallel, zanjir ketma-ket."""

    def test_independent_tasks_land_in_one_batch(self) -> None:
        tasks = [
            MissionTask(position=0, title="a", tool="a"),
            MissionTask(position=1, title="b", tool="b"),
        ]
        batches = _tasks_to_batches(tasks)
        assert len(batches) == 1
        assert {t.position for t in batches[0]} == {0, 1}

    def test_chain_lands_in_separate_batches(self) -> None:
        tasks = [
            MissionTask(position=0, title="a", tool="a"),
            MissionTask(position=1, title="b", tool="b", depends_on=[0]),
            MissionTask(position=2, title="c", tool="c", depends_on=[1]),
        ]
        batches = _tasks_to_batches(tasks)
        assert [sorted(t.position for t in b) for b in batches] == [[0], [1], [2]]

    def test_diamond_dependency_batches(self) -> None:
        # a -> b, a -> c, {b,c} -> d
        tasks = [
            MissionTask(position=0, title="a", tool="a"),
            MissionTask(position=1, title="b", tool="b", depends_on=[0]),
            MissionTask(position=2, title="c", tool="c", depends_on=[0]),
            MissionTask(position=3, title="d", tool="d", depends_on=[1, 2]),
        ]
        batches = _tasks_to_batches(tasks)
        assert [sorted(t.position for t in b) for b in batches] == [[0], [1, 2], [3]]

    def test_cycle_raises(self) -> None:
        tasks = [
            MissionTask(position=0, title="a", tool="a", depends_on=[1]),
            MissionTask(position=1, title="b", tool="b", depends_on=[0]),
        ]
        with pytest.raises(TaskGraphCycleError):
            _tasks_to_batches(tasks)


class TestSingleTaskExecution:
    async def test_single_task_success(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("writer", tools=["note.write"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool = _StubTool("note.write")
        tools.register(tool)

        mission = _mission(
            tasks=[MissionTask(position=0, title="note.write", tool="note.write", agent="writer")]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.any_failed is False
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].completed_at is not None
        assert result.tasks[0].started_at is not None

    async def test_no_agent_is_capability_gap_not_silent_substitution(self) -> None:
        """Agent tanlanmagan bo'lsa — begona agent bilan bajarilmaydi, gap qaytadi."""
        registry = AgentRegistry()
        registry.register(_agent_spec("unrelated", tools=["note.write"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool = _StubTool("note.write")
        tools.register(tool)

        mission = _mission(
            tasks=[MissionTask(position=0, title="note.write", tool="note.write", agent=None)]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert len(result.capability_gaps) == 1
        assert result.capability_gaps[0].tool == "note.write"
        # Halol dalil: hech qanday "unrelated" agent chaqirilmadi.
        assert tool.calls == []

    async def test_agent_became_unavailable_is_capability_gap(self) -> None:
        """Reja tuzilgandan keyin agent PAUSED bo'lib qolsa — gap, oddiy xato emas."""
        registry = AgentRegistry()
        registry.register(_agent_spec("writer", tools=["note.write"]), status=AgentStatus.PAUSED)
        tools = ToolRegistry()
        tools.register(_StubTool("note.write"))

        mission = _mission(
            tasks=[MissionTask(position=0, title="note.write", tool="note.write", agent="writer")]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert len(result.capability_gaps) == 1


class TestDependenciesAndBlocking:
    async def test_failed_dependency_blocks_downstream(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a", "b"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a"))
        tools.register(_StubTool("b"))

        # NEGA RuntimeError (LLM darajasida), tool xatosi emas: `AgentRuntime`
        # tool xatosini "yutib" oladi va modelga ko'rsatadi — model shundan
        # keyin ODOB BILAN to'xtasa, bu HALI HAM `success=True` (agent
        # o'z navbatini normal tugatdi). Task darajasidagi HAQIQIY
        # muvaffaqiyatsizlik faqat `AgentRuntime.run()`ning o'zi xato bilan
        # tugaganda yuzaga keladi (bu yerda — LLM chaqiruvi qulagan holat).
        provider = FakeProvider(scripted=[RuntimeError("simulated LLM crash")])

        mission = _mission(
            tasks=[
                MissionTask(position=0, title="a", tool="a", agent="agent"),
                MissionTask(position=1, title="b", tool="b", agent="agent", depends_on=[0]),
            ]
        )
        executor = _executor(
            agent_registry=registry, tool_registry=tools, provider=provider, max_retries=0
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[1].status == StepStatus.SKIPPED
        assert "muvaffaqiyatsiz" in (result.tasks[1].error or "")
        assert result.any_blocked is True
        assert result.any_failed is True

    async def test_dependency_order_respected(self) -> None:
        """B task, A tugagunicha ISHGA TUSHMAYDI — chaqiruv tartibi dalil."""
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a", "b"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        order: list[str] = []

        class _OrderedTool(_StubTool):
            async def _execute(self, params: dict[str, Any]) -> Any:
                order.append(self.name)
                return await super()._execute(params)

        tools.register(_OrderedTool("a"))
        tools.register(_OrderedTool("b"))

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("a"),)),
                fake_response(text="a done"),
                fake_response(tool_uses=(_tool_use("b"),)),
                fake_response(text="b done"),
            ]
        )

        mission = _mission(
            tasks=[
                MissionTask(position=0, title="a", tool="a", agent="agent"),
                MissionTask(position=1, title="b", tool="b", agent="agent", depends_on=[0]),
            ]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools, provider=provider)

        result = await executor.run(mission)

        assert result.all_done is True
        assert order == ["a", "b"]

    async def test_independent_tasks_both_run(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a", "b"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool_a = _StubTool("a")
        tool_b = _StubTool("b")
        tools.register(tool_a)
        tools.register(tool_b)

        mission = _mission(
            tasks=[
                MissionTask(position=0, title="a", tool="a", agent="agent"),
                MissionTask(position=1, title="b", tool="b", agent="agent"),
            ]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[1].status == StepStatus.DONE


class TestToolBoundary:
    async def test_unauthorized_tool_cannot_execute_even_if_requested(self) -> None:
        """Agent o'zining allowlist'ida "b"ni bilsa ham, task faqat "a"ga ega —
        model "b"ni so'rasa ham u ISHGA TUSHMAYDI (registry subset chegarasi)."""
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a", "b"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool_a = _StubTool("a")
        tool_b = _StubTool("b")
        tools.register(tool_a)
        tools.register(tool_b)

        provider = FakeProvider(
            scripted=[
                fake_response(tool_uses=(_tool_use("b"),)),  # ruxsatsiz urinish
                fake_response(text="gave up on b, done"),
            ]
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")]
        )
        executor = _executor(agent_registry=registry, tool_registry=tools, provider=provider)

        await executor.run(mission)

        # Halol dalil: "b"ning HAQIQIY _execute() kodi HECH QACHON ishlamadi.
        assert tool_b.calls == []
        assert tool_a.calls == []

    async def test_high_risk_tool_requires_approval_fails_closed(self) -> None:
        """HIGH risk tool — AgentRuntime avtonom holda bajarmaydi (V-32).

        NEGA `max_steps=1`: bitta rad etilgan tool chaqiruvi
        `AgentRuntime`ni "yiqitmaydi" — model muloyimlik bilan
        to'xtasa, bu hali ham `success=True` bo'lardi (haqiqiy xatti-
        harakat: rad etish — suhbat davomiga, halokat emas). Task
        darajasidagi HAQIQIY muvaffaqiyatsizlikni ko'rish uchun agentni
        "tool talab qilib, boshqa imkoniyat qolmaydigan" holatga
        qo'yamiz (`AgentMaxStepsError` — A-07 tormozi, `AgentRuntimeError`
        sifatida `success=False` qaytaradi).
        """
        registry = AgentRegistry()
        registry.register(
            _agent_spec("agent", tools=["danger"], max_steps=1), status=AgentStatus.ACTIVE
        )
        tools = ToolRegistry()
        danger = _StubTool("danger", risk=RiskLevel.HIGH)
        tools.register(danger)

        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("danger"),))])

        mission = _mission(
            tasks=[MissionTask(position=0, title="danger", tool="danger", agent="agent")]
        )
        executor = _executor(
            agent_registry=registry, tool_registry=tools, provider=provider, max_retries=0
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        # Halol dalil: rad etilgani uchun HAQIQIY tool kodi ishlamadi.
        assert danger.calls == []


class TestRetryAndTimeout:
    async def test_task_retries_on_failure_then_succeeds(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a"))

        provider = FakeProvider(
            scripted=[RuntimeError("simulated LLM crash"), fake_response(text="recovered")]
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")]
        )
        executor = _executor(
            agent_registry=registry, tool_registry=tools, provider=provider, max_retries=1
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].retries == 1

    async def test_task_fails_after_exhausting_retries(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a"))

        provider = FakeProvider(
            scripted=[RuntimeError("boom")] * 5,
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")]
        )
        executor = _executor(
            agent_registry=registry, tool_registry=tools, provider=provider, max_retries=2
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert result.tasks[0].retries == 2
        assert result.any_failed is True

    async def test_task_timeout_is_treated_as_failure(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["slow"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        slow_tool = _StubTool("slow", sleep_s=0.3)
        tools.register(slow_tool)

        provider = FakeProvider(scripted=[fake_response(tool_uses=(_tool_use("slow"),))] * 3)

        mission = _mission(
            tasks=[MissionTask(position=0, title="slow", tool="slow", agent="agent")]
        )
        executor = _executor(
            agent_registry=registry,
            tool_registry=tools,
            provider=provider,
            max_retries=0,
            task_timeout_s=0.05,
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert "vaqt" in (result.tasks[0].error or "").lower()


class TestResumeAndIdempotency:
    async def test_done_task_is_not_rerun(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a", "b"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool_a = _StubTool("a")
        tool_b = _StubTool("b")
        tools.register(tool_a)
        tools.register(tool_b)

        done_task = MissionTask(
            position=0, title="a", tool="a", agent="agent", status=StepStatus.DONE, result="oldin bajarilgan"
        )
        pending_task = MissionTask(position=1, title="b", tool="b", agent="agent")
        mission = _mission(tasks=[done_task, pending_task])
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert tool_a.calls == []  # DONE task qayta ishga tushmadi (idempotency)
        assert result.tasks[0].result == "oldin bajarilgan"  # eski natija saqlanib qoldi
        assert result.tasks[1].status == StepStatus.DONE  # PENDING task ISHLADI
        assert result.tasks[1].started_at is not None
        assert result.all_done is True

    async def test_running_task_resets_and_reruns_after_restart(self) -> None:
        """Process qulaganda RUNNING holatda qotib qolgan task qayta ishga tushadi."""
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tool_a = _StubTool("a")
        tools.register(tool_a)

        stuck_task = MissionTask(
            position=0, title="a", tool="a", agent="agent", status=StepStatus.RUNNING
        )
        mission = _mission(tasks=[stuck_task])
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.DONE

    async def test_mission_level_retry_resets_failed_task(self) -> None:
        """Mission-level recovery (`run()` qayta chaqirilishi) FAILED taskni
        abadiy bloklamaydi — PENDING'ga qaytarib qayta sinaydi."""
        registry = AgentRegistry()
        registry.register(_agent_spec("agent", tools=["a"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("a"))

        provider = FakeProvider(scripted=[RuntimeError("first run fails")])
        mission = _mission(tasks=[MissionTask(position=0, title="a", tool="a", agent="agent")])
        executor = _executor(
            agent_registry=registry, tool_registry=tools, provider=provider, max_retries=0
        )

        first = await executor.run(mission)
        assert first.tasks[0].status == StepStatus.FAILED

        # Mission-level recovery: yangi urinish (`recover()` sifatida) —
        # boshqa provider (bu safar muvaffaqiyatli).
        mission.tasks[:] = first.tasks
        executor2 = _executor(agent_registry=registry, tool_registry=tools, provider=None)
        second = await executor2.run(mission)

        assert second.tasks[0].status == StepStatus.DONE


class TestSynthesisAndEmptyGraph:
    async def test_empty_tasks_returns_all_done(self) -> None:
        registry = AgentRegistry()
        tools = ToolRegistry()
        mission = _mission(tasks=[])
        executor = _executor(agent_registry=registry, tool_registry=tools)

        result = await executor.run(mission)

        assert result.all_done is True
        assert result.tasks == []

    def test_synthesis_mentions_every_task(self) -> None:
        """`_synthesize()` — deterministik formatlash, LLM chaqirilmaydi.

        To'g'ridan-to'g'ri birlik testi (executor orqali emas): ikkita
        mustaqil task bitta soxta LLM navbatini bo'lishganda ijro
        tartibi (`asyncio.gather`) kafolatlanmagan bo'lardi — bu yerda
        formatlash funksiyasining o'zi tekshiriladi, muqarrar emas
        ijro tartibi emas.
        """
        from zet.core.task_graph import _synthesize

        mission = _mission(tasks=[])
        tasks = [
            MissionTask(position=0, title="a", tool="a", status=StepStatus.DONE, result="a natija"),
            MissionTask(position=1, title="b", tool="b", status=StepStatus.FAILED, error="b xato"),
        ]

        text = _synthesize(mission, tasks)

        assert "a" in text and "a natija" in text
        assert "b" in text and "b xato" in text


def _tool_use(name: str, arguments: dict[str, Any] | None = None):
    from zet.llm.base import ToolUse

    return ToolUse(id=str(uuid.uuid4()), name=name, arguments=arguments or {})
