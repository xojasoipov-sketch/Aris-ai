"""TaskGraphExecutor + AgentProvisioningService end-to-end (JB-6).

JB-5's CapabilityGap ilgari faqat hisobotga yozilardi. Bu testlar
HAQIQIY zanjirni tekshiradi: gap → real `AgentProvisioningService` →
real `AgentFactory`/`AgentLifecycle` → yangi ACTIVE agent → SHU
mavjud task o'sha zahoti (qo'shimcha mission-level retry kutmasdan)
davom etadi va muvaffaqiyatli tugaydi.
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.core.agent_provisioning import AgentProvisioningPolicy, AgentProvisioningService
from zet.core.mission import Mission, MissionTask
from zet.core.task_graph import TaskGraphExecutor
from zet.domain.enums import RiskLevel, StepStatus
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "stub"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def _execute(self, params: dict[str, Any]) -> Any:
        self.calls += 1
        return "ok"


def _mission(*, tasks: list[MissionTask]) -> Mission:
    return Mission(owner_id=uuid.uuid4(), objective="test missiya", tasks=tasks)


class TestCapabilityGapAutoProvisioning:
    async def test_gap_is_resolved_and_task_completes_with_new_agent(self) -> None:
        """Boshida HECH QANDAY agent yo'q — task LOW-risk tool talab qiladi
        (agent=None). Provisioner avtomatik agent yaratadi/faollashtiradi
        va task O'SHA yangi agent bilan muvaffaqiyatli tugaydi."""
        registry = AgentRegistry()  # bo'sh — hech qanday builtin/oldindan agent yo'q
        tools = ToolRegistry()
        tool = _StubTool("web.search")
        tools.register(tool)

        provisioner = AgentProvisioningService(agent_registry=registry)
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            agent_provisioner=provisioner,
        )

        mission = _mission(
            tasks=[MissionTask(position=0, title="web.search", tool="web.search", agent=None)]
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.DONE
        assert result.tasks[0].agent is not None
        assert result.tasks[0].agent != "web.search"  # haqiqiy generatsiya qilingan agent nomi
        assert registry.count == 1
        # Halol dalil — muvaffaqiyatli hal qilingan gap YAKUNIY natijada
        # "hal qilinmagan muammo" sifatida qaytarilmaydi.
        assert result.capability_gaps == []

    async def test_high_risk_gap_stays_unresolved_capability_gap(self) -> None:
        """HIGH risk — siyosat provisioning'ni rad etadi, task HALOL FAILED
        bo'ladi (begona agent bilan bajarilmaydi, gap qaytariladi)."""
        registry = AgentRegistry()
        tools = ToolRegistry()
        tools.register(_StubTool("shell.exec"))

        provisioner = AgentProvisioningService(agent_registry=registry)
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(),
            agent_provisioner=provisioner,
        )

        # `shell.exec` markazlashtirilgan risk jadvalida HIGH — default
        # siyosat (`disabled_min_risk=HIGH`) buni avtomatik rad etadi.
        mission = _mission(
            tasks=[MissionTask(position=0, title="shell.exec", tool="shell.exec", agent=None)]
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert registry.count == 0  # hech qanday agent avtomatik yaratilmadi
        assert len(result.capability_gaps) == 1
        assert result.capability_gaps[0].tool == "shell.exec"

    async def test_no_provisioner_keeps_jb5_behavior(self) -> None:
        """Regressiya kafolati: `agent_provisioner=None` (default) — JB-5
        xatti-harakati o'zgarmagan (gap faqat hisobotga yoziladi)."""
        registry = AgentRegistry()
        tools = ToolRegistry()
        tools.register(_StubTool("web.search"))

        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(),
        )
        mission = _mission(
            tasks=[MissionTask(position=0, title="web.search", tool="web.search", agent=None)]
        )

        result = await executor.run(mission)

        assert result.tasks[0].status == StepStatus.FAILED
        assert registry.count == 0
        assert len(result.capability_gaps) == 1

    async def test_medium_risk_gap_creates_pending_agent_but_task_still_fails(self) -> None:
        """MEDIUM risk (default: REQUIRE_APPROVAL) — agent yaratiladi
        (inson tasdig'ini kutadi), lekin ACTIVE emas, shuning uchun task
        HOZIRCHA baribir FAILED (begona/faollashtirilmagan agent bilan
        avtomatik bajarilmaydi) — lekin keyingi safar (inson tasdiqlagach)
        `AgentSelector` uni topa oladi."""
        registry = AgentRegistry()
        tools = ToolRegistry()
        tools.register(_StubTool("note.write"))

        # `note.write` xavf jadvalida odatda LOW/MEDIUM bo'lishi mumkin —
        # aniq nazorat uchun qat'iy MEDIUM ceiling bilan siyosat beramiz.
        provisioner = AgentProvisioningService(
            agent_registry=registry,
            policy=AgentProvisioningPolicy(
                auto_create_max_risk=RiskLevel.LOW, disabled_min_risk=RiskLevel.HIGH
            ),
        )
        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(),
            agent_provisioner=provisioner,
        )
        mission = _mission(
            tasks=[MissionTask(position=0, title="note.write", tool="note.write", agent=None)]
        )

        result = await executor.run(mission)

        # `note.write` MEDIUM risk (business write) — REQUIRE_APPROVAL.
        assert result.tasks[0].status == StepStatus.FAILED
        assert registry.count == 1  # agent yaratildi...
        (state,) = registry.list_agents()
        from zet.domain.enums import AgentStatus

        assert state.status != AgentStatus.ACTIVE  # ...lekin ACTIVE emas
