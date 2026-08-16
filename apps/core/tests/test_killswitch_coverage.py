"""Killswitch qamrovi testlari (JB-12).

AUDIT TOPILMASI: `AgentRuntime`/`TaskGraphExecutor` killswitch'ni HECH
QACHON tekshirmasdi (`core/executor.py`dan farqli — u har DAG batch'dan
oldin `check()` chaqiradi). Mission-level restart-resume (`mission_recovery.py`
→ `MissionEngine.run_to_completion()`) ham `MissionOrchestrator`ning bir
martalik preflight tekshiruvini chetlab o'tib, killswitch'ni UMUMAN
ko'rmasdi. Bu testlar — endi HAQIQIY tekshiruv borligini, konkret
runtime yo'llar orqali isbotlaydi (mock/stub emas, haqiqiy
`KillSwitchState`).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from zet.agents.registry import AgentRegistry
from zet.agents.runtime import AgentRuntime
from zet.core.mission import Mission, MissionEngine
from zet.core.task_graph import TaskGraphExecutor
from zet.db.models import Owner
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, MissionStatus, ModelTier, PermissionLevel
from zet.llm.fake import FakeProvider, fake_response
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry


def _agent_spec(name: str = "test_agent", tools: list[str] | None = None) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools or [],
        model_policy=ModelTier.T1_FREE,
        permission_level=PermissionLevel.WRITE,
    )


class TestAgentRuntimeKillswitch:
    """`AgentRuntime` — killswitch berilgan bo'lsa, tool-loop davomida tekshiradi."""

    async def test_killswitch_engaged_before_run_stops_immediately(self) -> None:
        killswitch = KillSwitchState()
        killswitch.engage(reason="test emergency stop")
        provider = FakeProvider(scripted=[fake_response("bu javob chiqmasligi kerak")])
        runtime = AgentRuntime(
            provider=provider, tool_registry=ToolRegistry(), killswitch=killswitch
        )
        spec = _agent_spec()

        result = await runtime.run(spec, "biror ish qil")

        assert result.success is False
        assert "Emergency stop" in (result.error or "")
        # LLM HECH CHAQIRILMAGAN — killswitch qadam boshida ushlagan.
        assert result.steps_count == 1

    async def test_no_killswitch_given_runs_normally(self) -> None:
        """Ixtiyoriy parametr — berilmasa eski xatti-harakat (NOL regressiya)."""
        provider = FakeProvider(scripted=[fake_response("tayyor")])
        runtime = AgentRuntime(provider=provider, tool_registry=ToolRegistry())
        spec = _agent_spec()

        result = await runtime.run(spec, "ish")

        assert result.success is True
        assert result.output == "tayyor"

    async def test_disengaged_killswitch_does_not_block(self) -> None:
        killswitch = KillSwitchState()  # default: is_engaged=False
        provider = FakeProvider(scripted=[fake_response("tayyor")])
        runtime = AgentRuntime(
            provider=provider, tool_registry=ToolRegistry(), killswitch=killswitch
        )
        spec = _agent_spec()

        result = await runtime.run(spec, "ish")

        assert result.success is True


class TestTaskGraphExecutorKillswitch:
    """`TaskGraphExecutor` — har batch'dan oldin killswitch tekshiradi."""

    async def test_engaged_killswitch_fails_tasks_without_running_them(self) -> None:
        killswitch = KillSwitchState()
        killswitch.engage(reason="test")
        agent_registry = AgentRegistry()
        agent_registry.register(_agent_spec("a"), status=AgentStatus.ACTIVE)
        tool_registry = ToolRegistry()
        executor = TaskGraphExecutor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=FakeProvider(scripted=[fake_response("bu chiqmasligi kerak")]),
            killswitch=killswitch,
        )
        mission = Mission(
            owner_id=uuid.uuid4(),
            objective="test",
            tasks=[
                {"position": 0, "title": "t0", "agent": "a", "tool": None},
            ],
        )

        result = await executor.run(mission)

        assert result.any_failed is True
        assert result.all_done is False
        assert "kill switch" in (result.tasks[0].error or "").lower()

    async def test_no_killswitch_given_runs_normally(self) -> None:
        agent_registry = AgentRegistry()
        agent_registry.register(_agent_spec("a"), status=AgentStatus.ACTIVE)
        executor = TaskGraphExecutor(
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=FakeProvider(scripted=[fake_response("tayyor")]),
        )
        mission = Mission(
            owner_id=uuid.uuid4(),
            objective="test",
            tasks=[{"position": 0, "title": "t0", "agent": "a", "tool": None}],
        )

        result = await executor.run(mission)

        assert result.all_done is True


class TestMissionEngineResumeKillswitch:
    """`MissionEngine.run_to_completion()` — restart-resume yo'lida killswitch.

    Bu — audit ochib bergan ENG JIDDIY gap: `mission_recovery.py`
    `MissionOrchestrator`ning bir martalik preflight tekshiruvini chetlab
    o'tib, `MissionEngine.run_to_completion()`ni TO'G'RIDAN-TO'G'RI
    chaqiradi. Bu test — restart'da qayta tiklangan (killswitch YOQILGAN
    paytda) mission HAQIQATDA ijro etilmasligini isbotlaydi.
    """

    async def test_engaged_killswitch_stops_resumed_mission(
        self, session: Any, owner: Owner
    ) -> None:
        from zet.core.mission_repository import MissionRepository

        killswitch = KillSwitchState()
        killswitch.engage(reason="test — restart paytida yoqilgan")

        repo = MissionRepository(session, owner_id=owner.id)
        mission = await repo.create(Mission(owner_id=owner.id, objective="restart test"))
        # Restart-resume ssenariysi: mission EXECUTING holatida "qotib qolgan".
        for s in (MissionStatus.UNDERSTANDING, MissionStatus.DISCOVERING,
                  MissionStatus.PLANNING, MissionStatus.EXECUTING):
            await repo.set_status(mission.id, s)

        engine = MissionEngine(
            repository=repo,
            capability_registry=object(),  # type: ignore[arg-type]
            context_engine=object(),  # type: ignore[arg-type]
            planner=object(),  # type: ignore[arg-type]
            orchestrator=object(),  # type: ignore[arg-type]
            approvals=ApprovalService(),
            killswitch=killswitch,
        )

        result = await engine.run_to_completion(mission.id)

        # HAQIQIY DALIL: mission FAILED (killswitch) bo'ldi — hech qanday
        # orchestrator/capability_registry/planner (barchasi `object()`,
        # chaqirilsa AttributeError berardi) chaqirilmadi.
        assert result.status == MissionStatus.FAILED
        assert "kill switch" in (result.error or "").lower()

    async def test_no_killswitch_given_falls_through_normally(
        self, session: Any, owner: Owner
    ) -> None:
        """Ixtiyoriy — berilmasa, `execute()` ichidagi mavjud (o'zgarishsiz)
        killswitch tekshiruviga qadar yetadi (NOL regressiya)."""
        from zet.core.mission_repository import MissionRepository

        repo = MissionRepository(session, owner_id=owner.id)
        mission = await repo.create(Mission(owner_id=owner.id, objective="test"))
        await repo.set_status(mission.id, MissionStatus.UNDERSTANDING)

        engine = MissionEngine(
            repository=repo,
            capability_registry=object(),  # type: ignore[arg-type]
            context_engine=object(),  # type: ignore[arg-type]
            planner=object(),  # type: ignore[arg-type]
            orchestrator=object(),  # type: ignore[arg-type]
            approvals=ApprovalService(),
        )

        # UNDERSTANDING -> DISCOVERING (xavfsiz, side-effect-free) -> discover()
        # chaqiriladi, u `context_engine.discover()`ni chaqiradi (`object()`
        # AttributeError beradi) — bu killswitch YO'Q ekanini isbotlash
        # uchun yetarli: xato killswitch'dan EMAS, chaqiruvdan keladi.
        with pytest.raises(AttributeError):
            await engine.run_to_completion(mission.id)
