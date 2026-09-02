"""Capability-DAG → real `depends_on` → to'liq MissionEngine ijrosi (JB-5).

Bu testlar `_tool_dependencies_from_capabilities()` (capability dependency
grafidan tool-darajasidagi bog'liqlik xaritasi), `_bundle_to_tasks()`ning
shu xaritadan HAQIQIY DAG qurishi va nihoyat `MissionEngine` + real
`TaskGraphExecutor` bilan bir nechta taskli mission oxirigacha
(COMPLETED) borishini tekshiradi — mock emas, haqiqiy zanjir.
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.core.capability import Capability, CapabilityRegistry
from zet.core.mission import MissionEngine, _bundle_to_tasks
from zet.core.mission_orchestrator import (
    CapabilityRegistryComposer,
    _tool_dependencies_from_capabilities,
)
from zet.core.mission_repository import MissionRepository
from zet.core.task_graph import TaskGraphExecutor
from zet.db.models import Owner
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, MissionStatus, ModelTier, PermissionLevel, RiskLevel
from zet.security.approvals import ApprovalService
from zet.security.permissions import PermissionPolicy
from zet.tools.base import Tool
from zet.tools.registry import ToolRegistry


def _agent_spec(name: str, *, tools: list[str]) -> AgentSpec:
    return AgentSpec(
        name=name,
        description="test agent",
        system_prompt="test",
        tool_allowlist=tools,
        model_policy=ModelTier.T1_FREE,
        permission_level=PermissionLevel.WRITE,
    )


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


class TestToolDependenciesFromCapabilities:
    def test_independent_capabilities_produce_no_edges(self) -> None:
        caps = [
            Capability(name="research", description="d", default_tools=["web.search"]),
            Capability(name="content", description="d", default_tools=["note.write"]),
        ]
        deps = _tool_dependencies_from_capabilities(caps)
        assert deps == {}

    def test_dependent_capability_tools_depend_on_parent_tools(self) -> None:
        branding = Capability(name="branding", description="d", default_tools=["image.generate"])
        content = Capability(name="content", description="d", default_tools=["note.write"])
        website = Capability(
            name="website",
            description="d",
            default_tools=["github.write", "deploy.push"],
            dependencies=["branding", "content"],
        )
        # resolve() tartibida ota-capability'lar OLDIN keladi (topo-sort).
        deps = _tool_dependencies_from_capabilities([branding, content, website])

        assert set(deps["github.write"]) == {"image.generate", "note.write"}
        assert set(deps["deploy.push"]) == {"image.generate", "note.write"}
        assert "image.generate" not in deps  # branding'ning o'zi hech kimga bog'liq emas

    def test_same_capability_tools_are_not_mutually_dependent(self) -> None:
        """Bitta capability ichidagi ikkita tool — mustaqil (parallel)."""
        cap = Capability(name="smm", description="d", default_tools=["instagram.publish", "telegram.send"])
        deps = _tool_dependencies_from_capabilities([cap])
        assert deps == {}


class TestBundleToTasksRealDag:
    def test_independent_tools_get_empty_depends_on(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            Capability(name="research", description="d", default_tools=["web.search"])
        )
        registry.register(
            Capability(name="content", description="d", default_tools=["note.write"])
        )
        composer = CapabilityRegistryComposer(registry)
        bundle = composer.compose("research and write content", {})
        tasks = _bundle_to_tasks(bundle)

        assert len(tasks) == 2
        assert all(t.depends_on == [] for t in tasks)

    def test_dependent_capability_produces_real_edges_not_linear_chain(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            Capability(name="branding", description="d", default_tools=["image.generate"])
        )
        registry.register(
            Capability(name="content", description="d", default_tools=["note.write"])
        )
        registry.register(
            Capability(
                name="website",
                description="d",
                default_tools=["github.write"],
                dependencies=["branding", "content"],
                tags=["website"],
            )
        )
        composer = CapabilityRegistryComposer(registry)
        bundle = composer.compose("website branding content", {})
        tasks = _bundle_to_tasks(bundle)

        by_tool = {t.tool: t for t in tasks}
        # branding va content — MUSTAQIL (bir-biriga bog'liq emas, ESKI
        # chiziqli zanjirda content ikkinchisi branding'ga bog'liq bo'lardi).
        assert by_tool["note.write"].depends_on == []
        assert by_tool["image.generate"].depends_on == []
        # website (github.write) — IKKALASIGA HAM bog'liq (haqiqiy DAG).
        github_deps = {
            by_tool[t.tool].position
            for t in tasks
            if t.position in by_tool["github.write"].depends_on
        }
        assert {by_tool["image.generate"].position, by_tool["note.write"].position} == github_deps


class TestMissionEngineEndToEndTaskGraph:
    async def test_multi_task_mission_completes_via_task_graph(
        self, session: Any, owner: Owner
    ) -> None:
        """To'liq zanjir: capability → real DAG → TaskGraphExecutor → COMPLETED."""
        cap_registry = CapabilityRegistry()
        cap_registry.register(
            Capability(
                name="research",
                description="izlaydi",
                supported_outcomes=["market_scan"],
                actions=["search"],
                default_tools=["web.search"],
                tags=["research"],
            )
        )
        cap_registry.register(
            Capability(
                name="content",
                description="yozadi",
                supported_outcomes=["draft_article"],
                actions=["write"],
                default_tools=["note.write"],
                tags=["content"],
            )
        )

        agent_registry = AgentRegistry()
        agent_registry.register(
            _agent_spec("researcher", tools=["web.search"]), status=AgentStatus.ACTIVE
        )
        agent_registry.register(
            _agent_spec("writer", tools=["note.write"]), status=AgentStatus.ACTIVE
        )

        composer = CapabilityRegistryComposer(cap_registry, agent_registry=agent_registry)

        tool_registry = ToolRegistry()
        tool_registry.register(_StubTool("web.search"))
        tool_registry.register(_StubTool("note.write"))

        task_graph_executor = TaskGraphExecutor(
            agent_registry=agent_registry,
            tool_registry=tool_registry,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=None,  # FakeProvider (default fallback) — offline, deterministik
            max_retries=0,
        )

        repo = MissionRepository(session, owner_id=owner.id)

        class _FakeContextEngine:
            async def discover(
                self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
            ) -> Any:
                class _Empty:
                    def to_dict(self) -> dict[str, Any]:
                        return {}

                return _Empty()

        class _UnusedOrchestrator:
            """Task Graph yo'lida CHAQIRILMASLIGI kerak (dalil sifatida)."""

            @property
            def tool_registry(self) -> ToolRegistry:
                raise AssertionError("Task Graph yo'lida Orchestrator ishlatilmasligi kerak")

            async def start(self, *args: Any, **kwargs: Any) -> Any:
                raise AssertionError("Task Graph yo'lida Orchestrator.start() chaqirilmasligi kerak")

        engine = MissionEngine(
            repository=repo,
            capability_registry=composer,
            context_engine=_FakeContextEngine(),
            planner=object(),
            orchestrator=_UnusedOrchestrator(),  # type: ignore[arg-type]
            approvals=ApprovalService(),
            task_graph_executor=task_graph_executor,
        )

        mission = await engine.submit(owner_id=owner.id, objective="research and write content")
        mission = await engine.run_to_completion(mission.id)

        assert mission.status == MissionStatus.COMPLETED
        assert len(mission.tasks) == 2
        assert all(t.status.value == "done" for t in mission.tasks)
        assert mission.memory_updates  # yakuniy sintez xotiraga yozildi

    async def test_single_task_mission_still_uses_old_single_command_path(
        self, session: Any, owner: Owner
    ) -> None:
        """Regressiya kafolati: 0-1 taskli mission — task_graph_executor
        berilgan bo'lsa ham ESKI yo'lda qoladi (Orchestrator.start() chaqiriladi)."""
        from dataclasses import dataclass, field

        from zet.db.models.run import Run
        from zet.domain.enums import RunStatus, RunTrigger

        @dataclass
        class _FakeBundle:
            capabilities: list[str] = field(default_factory=list)
            agents: list[str] = field(default_factory=list)
            tools: list[str] = field(default_factory=lambda: ["only.tool"])
            permissions_required: list[PermissionLevel] = field(default_factory=list)
            risk_level: RiskLevel = RiskLevel.LOW
            tool_agents: dict[str, str] = field(default_factory=dict)

        class _FakeCapabilityRegistry:
            def compose(self, objective: str, context: dict[str, Any]) -> _FakeBundle:
                return _FakeBundle()

        class _FakeContextEngine:
            async def discover(
                self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
            ) -> Any:
                class _Empty:
                    def to_dict(self) -> dict[str, Any]:
                        return {}

                return _Empty()

        @dataclass
        class _FakeRunRecord:
            run_id: uuid.UUID
            status: RunStatus = RunStatus.DONE
            verified_ok: bool | None = True
            pending_approval_id: uuid.UUID | None = None
            error: str | None = None
            result_summary: str | None = "bajarildi"

        class _RecordingOrchestrator:
            def __init__(self) -> None:
                self.start_called = False
                self.tool_registry = ToolRegistry()

            async def start(self, command: Any, **kwargs: Any) -> _FakeRunRecord:
                self.start_called = True
                run_id = uuid.uuid4()
                run = Run(
                    id=run_id,
                    owner_id=owner.id,
                    trigger=RunTrigger.MANUAL,
                    command_text=str(getattr(command, "text", "x")),
                    trace_id="trace",
                )
                session.add(run)
                await session.flush()
                return _FakeRunRecord(run_id=run_id)

        orch = _RecordingOrchestrator()
        repo = MissionRepository(session, owner_id=owner.id)

        # task_graph_executor BERILGAN, lekin faqat 1 tool (< 2 task) bo'lgani
        # uchun ishlatilmasligi kerak.
        never_used_executor = TaskGraphExecutor(
            agent_registry=AgentRegistry(),
            tool_registry=ToolRegistry(),
            permission_policy=PermissionPolicy(),
        )

        engine = MissionEngine(
            repository=repo,
            capability_registry=_FakeCapabilityRegistry(),
            context_engine=_FakeContextEngine(),
            planner=object(),
            orchestrator=orch,  # type: ignore[arg-type]
            approvals=ApprovalService(),
            task_graph_executor=never_used_executor,
        )

        mission = await engine.submit(owner_id=owner.id, objective="single tool mission")
        mission = await engine.run_to_completion(mission.id)

        assert mission.status == MissionStatus.COMPLETED
        assert orch.start_called is True
