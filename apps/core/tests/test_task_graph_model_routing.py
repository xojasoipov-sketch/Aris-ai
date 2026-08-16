"""TaskGraphExecutor + BrainModelRouter wiring (JB-7).

`FakeProvider.calls` har bir LLM chaqiruvida qaysi `model` (=TaskClass
qiymati) so'ralganini yozib boradi — bu HAQIQIY dalil: agentning statik
tieri emas, task mazmuni (`tool` namespace/risk) qaysi TaskClass
tanlaganini ko'rsatadi.
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.core.mission import Mission, MissionTask
from zet.core.model_routing import BrainModelRouter
from zet.core.task_graph import TaskGraphExecutor
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel
from zet.llm.fake import FakeProvider
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


class _StubTool(Tool):
    def __init__(self, name: str) -> None:
        self._name = name

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
        return "ok"


def _mission(*, tasks: list[MissionTask]) -> Mission:
    return Mission(owner_id=uuid.uuid4(), objective="test missiya", tasks=tasks)


def _agent_spec(name: str, *, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,  # -> "normal" (task_class_for_tier)
        permission_level=PermissionLevel.WRITE,
    )


class TestPerTaskModelRouting:
    async def test_coding_tool_routes_to_coding_task_class(self) -> None:
        registry = AgentRegistry()
        registry.register(_agent_spec("dev", tools=["github.write"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("github.write"))
        provider = FakeProvider()

        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=provider,
            model_router=BrainModelRouter(),
        )
        mission = _mission(
            tasks=[MissionTask(position=0, title="github.write", tool="github.write", agent="dev")]
        )

        await executor.run(mission)

        assert provider.calls
        # Agent statik tieri T1_FREE -> "normal" bo'lardi — lekin task
        # mazmuni (github.* namespace) "coding" tanlashini talab qiladi.
        assert provider.calls[0]["model"] == "coding"

    async def test_no_router_uses_static_agent_tier(self) -> None:
        """Regressiya kafolati: `model_router=None` (default) — JB-5/6 xatti-harakati."""
        registry = AgentRegistry()
        registry.register(_agent_spec("dev", tools=["github.write"]), status=AgentStatus.ACTIVE)
        tools = ToolRegistry()
        tools.register(_StubTool("github.write"))
        provider = FakeProvider()

        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=provider,
        )
        mission = _mission(
            tasks=[MissionTask(position=0, title="github.write", tool="github.write", agent="dev")]
        )

        await executor.run(mission)

        assert provider.calls
        # `model_router` berilmagan — T1_FREE agent tieri -> "normal".
        assert provider.calls[0]["model"] == "normal"

    async def test_high_risk_tool_routes_to_complex_task_class(self) -> None:
        registry = AgentRegistry()
        registry.register(
            _agent_spec("smm", tools=["instagram.publish_photo"]), status=AgentStatus.ACTIVE
        )
        tools = ToolRegistry()
        tools.register(_StubTool("instagram.publish_photo"))
        provider = FakeProvider()

        executor = TaskGraphExecutor(
            agent_registry=registry,
            tool_registry=tools,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=provider,
            model_router=BrainModelRouter(),
        )
        mission = _mission(
            tasks=[
                MissionTask(
                    position=0,
                    title="instagram.publish_photo",
                    tool="instagram.publish_photo",
                    agent="smm",
                )
            ]
        )

        await executor.run(mission)

        assert provider.calls
        assert provider.calls[0]["model"] == "complex"
