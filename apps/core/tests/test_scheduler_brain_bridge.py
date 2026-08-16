"""Scheduler → Brain integratsiyasi testlari (JB-12 §2/§23) — markaziy tuzatish.

AUDIT TOPILMASI: `AutomationDaemon` scheduled fire'larni HECH QACHON
`Brain.handle()` orqali yubormasdi — to'g'ridan-to'g'ri
`run_agent_command(rule.agent_name, rule.command)`ga borar edi. Bu —
"scheduler = ahmoq dispatcher" muammosi (spec §2's "THE MOST IMPORTANT
FIX"): murakkab (2+ tool) rejalashtirilgan vazifalar Mission/TaskGraph/
AgentSelector/ModelRouter orqali EMAS, bitta qattiq belgilangan agent
orqali bajarilardi — hech qanday kognitiv reja/tekshiruv yo'q edi.

Testlar uch qatlamda:
    1. `_brain_result_to_agent_run_result()` — tor adapter, unit darajada.
    2. `AutomationDaemon._run_once_via_brain()`/`_fire()` — soxta (lekin
       chaqiriladigan) Brain bilan WIRING'ni isbotlaydi (tez).
    3. HAQIQIY Brain → Mission → TaskGraph → HAQIQIY tool chaqiruvlari —
       to'liq zanjir, spetsifikatsiyaning aynan o'zi so'ragan ssenariy
       (TEST H'ga mos).
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.automation.scheduler import Scheduler, ScheduleRule
from zet.core.brain import Brain, BrainResult, BrainRoute
from zet.core.capability import Capability, CapabilityRegistry
from zet.core.execution_mode import ExecutionModeClassifier
from zet.core.intent import IntentRecognizer
from zet.core.mission import Mission, MissionEngine
from zet.core.mission_orchestrator import CapabilityRegistryComposer, MissionOrchestrator
from zet.core.mission_repository import MissionRepository
from zet.core.model_routing import BrainModelRouter
from zet.core.task_graph import TaskGraphExecutor
from zet.db.models import Owner
from zet.deploy.automation_daemon import AutomationDaemon, _brain_result_to_agent_run_result
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, MissionStatus, ModelTier, PermissionLevel
from zet.llm.base import ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import StubNotifier
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


def _intent_tool_use(
    *, action: str, requires_tools: list[str], task_class: str = "complex"
) -> ToolUse:
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="parse_intent",
        arguments={
            "action": action,
            "objects": ["github", "loyiha"],
            "constraints": [],
            "urgency": "normal",
            "task_class": task_class,
            "requires_tools": requires_tools,
            "ambiguity": "low",
            "clarification_question": None,
            "confidence": 0.92,
            "request_kind": "goal",
        },
    )


def _agent_tool_use(tool_name: str) -> ToolUse:
    return ToolUse(id=f"tu_{uuid.uuid4().hex[:8]}", name=tool_name, arguments={})


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


class TestBrainResultAdapter:
    """`_brain_result_to_agent_run_result()` — tor, halol adapter."""

    def test_success_maps_ok_true(self) -> None:
        result = BrainResult(text="Audit tugadi.", ok=True, route=BrainRoute.MISSION,
                              mission_id="m1")
        adapted = _brain_result_to_agent_run_result(result, agent_name="rule-agent")

        assert adapted.success is True
        assert adapted.output == "Audit tugadi."
        assert adapted.error is None
        assert adapted.agent_name == "rule-agent"
        # HALOL: Brain darajasida tool_calls_count noma'lum — soxtalashtirilmaydi.
        assert adapted.tool_calls_count == 0

    def test_failure_maps_ok_false_with_error(self) -> None:
        result = BrainResult(text="Xato yuz berdi.", ok=False, route=BrainRoute.RUN)
        adapted = _brain_result_to_agent_run_result(result, agent_name="a")

        assert adapted.success is False
        assert adapted.error == "Xato yuz berdi."

    def test_waiting_approval_mission_is_success_not_failure(self) -> None:
        """WAITING_APPROVAL — mission HAQIQATAN yaratildi, bu XATO EMAS."""
        mission = Mission(
            owner_id=uuid.uuid4(), objective="test", status=MissionStatus.WAITING_APPROVAL
        )
        result = BrainResult(
            text="Tasdiq kerak.", ok=True, route=BrainRoute.MISSION,
            mission_id=str(mission.id), mission=mission,
        )
        adapted = _brain_result_to_agent_run_result(result, agent_name="a")

        assert adapted.success is True
        assert "tasdiq kutilmoqda" in adapted.output.lower()
        assert str(mission.id) in adapted.output


class TestAutomationDaemonBrainWiring:
    """`AutomationDaemon._fire()`/`_run_once_via_brain()` — soxta Brain bilan wiring."""

    class _FakeBrain:
        def __init__(self, result: BrainResult) -> None:
            self.result = result
            self.commands: list[Any] = []

        async def handle(self, command: Any, *, dry_run: bool = False) -> BrainResult:
            self.commands.append(command)
            return self.result

    async def test_use_brain_rule_calls_brain_not_run_agent_command(
        self, session: Any, session_factory: Any
    ) -> None:
        brain = self._FakeBrain(
            BrainResult(text="Bajarildi.", ok=True, route=BrainRoute.MISSION, mission_id="m1")
        )

        async def _brain_factory(sess: Any) -> Any:
            return brain

        daemon = AutomationDaemon(
            engine=__import__("zet.automation.engine", fromlist=["AutomationEngine"]).AutomationEngine(),
            agent_registry=AgentRegistry(),
            tool_registry=ToolRegistry(),
            permission_policy=PermissionPolicy(),
            core_state=__import__("zet.core.state", fromlist=["CoreState"]).CoreState(),
            killswitch=KillSwitchState(),
            session_factory=session_factory,
            settings=__import__("zet.config", fromlist=["Settings"]).Settings(_env_file=None),
            brain_factory=_brain_factory,
        )
        rule = ScheduleRule(
            name="complex rule", agent_name="ceo", cron_expr="* * * * *",
            command="GitHub loyihamni audit qil, muammolarni top", use_brain=True,
        )
        daemon._engine.scheduler.add_rule(rule)

        await daemon._fire(rule)

        assert len(brain.commands) == 1
        assert brain.commands[0].text == rule.command
        assert brain.commands[0].channel == "schedule"
        assert brain.commands[0].metadata["schedule_id"] == rule.id

    async def test_use_brain_failure_does_not_retry(
        self, session: Any, session_factory: Any
    ) -> None:
        """JB-12: use_brain=True — MAX_ATTEMPTS sikli YO'Q (dublikat Mission
        yaratish xavfi — har chaqiruv YANGI Mission demak)."""
        brain = self._FakeBrain(
            BrainResult(text="ishlamadi", ok=False, route=BrainRoute.MISSION)
        )
        calls = 0

        async def _brain_factory(sess: Any) -> Any:
            nonlocal calls
            calls += 1
            return brain

        daemon = AutomationDaemon(
            engine=__import__("zet.automation.engine", fromlist=["AutomationEngine"]).AutomationEngine(),
            agent_registry=AgentRegistry(),
            tool_registry=ToolRegistry(),
            permission_policy=PermissionPolicy(),
            core_state=__import__("zet.core.state", fromlist=["CoreState"]).CoreState(),
            killswitch=KillSwitchState(),
            session_factory=session_factory,
            settings=__import__("zet.config", fromlist=["Settings"]).Settings(_env_file=None),
            brain_factory=_brain_factory,
        )
        rule = ScheduleRule(
            name="r", agent_name="ceo", cron_expr="* * * * *", command="ish", use_brain=True
        )
        daemon._engine.scheduler.add_rule(rule)

        await daemon._fire(rule)

        # Faqat BITTA urinish — retry sikli ishlamagan.
        assert calls == 1
        assert len(brain.commands) == 1

    async def test_use_brain_false_rule_still_uses_classic_path(self) -> None:
        """Regressiya: `use_brain=False` (default) — Brain HECH chaqirilmaydi."""
        brain_called = False

        async def _brain_factory(sess: Any) -> Any:  # pragma: no cover — chaqirilmasligi kerak
            nonlocal brain_called
            brain_called = True
            raise AssertionError("Brain chaqirilmasligi kerak edi")

        agent_registry = AgentRegistry()
        agent_registry.register(_agent_spec("ceo", tools=[]), status=AgentStatus.ACTIVE)
        daemon = AutomationDaemon(
            engine=__import__("zet.automation.engine", fromlist=["AutomationEngine"]).AutomationEngine(),
            agent_registry=agent_registry,
            tool_registry=ToolRegistry(),
            permission_policy=PermissionPolicy(),
            core_state=__import__("zet.core.state", fromlist=["CoreState"]).CoreState(),
            killswitch=KillSwitchState(),
            brain_factory=_brain_factory,
        )
        rule = ScheduleRule(
            name="simple", agent_name="ceo", cron_expr="* * * * *", command="salom ayt",
        )
        assert rule.use_brain is False
        daemon._engine.scheduler.add_rule(rule)

        await daemon._fire(rule)

        assert brain_called is False


class TestScheduleRuleUseBrainPersistsThroughUpdates:
    """`use_brain` — `pause_rule`/`resume_rule`/`record_run` orqali yo'qolib
    qolmasligi kerak (frozen model qayta qurilganda)."""

    def test_survives_pause_resume_record_run(self) -> None:
        scheduler = Scheduler()
        rule = scheduler.add_rule(
            ScheduleRule(
                name="r", agent_name="a", cron_expr="* * * * *", command="c", use_brain=True
            )
        )
        assert rule.use_brain is True

        paused = scheduler.pause_rule(rule.id)
        assert paused is not None
        assert paused.use_brain is True

        resumed = scheduler.resume_rule(rule.id)
        assert resumed is not None
        assert resumed.use_brain is True

        recorded = scheduler.record_run(rule.id)
        assert recorded is not None
        assert recorded.use_brain is True


class TestBackgroundWorkflowBridgeSetsUseBrain:
    """`BackgroundWorkflowBridge.create_schedule()` — 2+ tool → `use_brain=True`."""

    def test_two_tools_sets_use_brain_true(self) -> None:
        from zet.automation.engine import AutomationEngine
        from zet.core.agent_selector import AgentSelector
        from zet.core.background_workflow import BackgroundWorkflowBridge
        from zet.domain.command import Intent

        agent_registry = AgentRegistry()
        agent_registry.register(
            _agent_spec("multi", tools=["github.read", "code_analysis"]),
            status=AgentStatus.ACTIVE,
        )
        engine = AutomationEngine()
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine, agent_selector=AgentSelector(agent_registry)
        )
        intent = Intent(
            action="audit", original_text="har kuni audit qil",
            requires_tools=["github.read", "code_analysis"], request_kind="goal",
        )

        from zet.core.schedule_expression import ScheduleExpression

        result = bridge.create_schedule(
            intent=intent,
            expression=ScheduleExpression(cron="0 9 * * *", reason="har kuni"),
            command_text="har kuni github va kod tahlilini qil",
        )

        assert result.ok is True
        rule = engine.scheduler.get_rule(result.rule_id)
        assert rule is not None
        assert rule.use_brain is True

    def test_single_tool_sets_use_brain_false(self) -> None:
        from zet.automation.engine import AutomationEngine
        from zet.core.agent_selector import AgentSelector
        from zet.core.background_workflow import BackgroundWorkflowBridge
        from zet.core.schedule_expression import ScheduleExpression
        from zet.domain.command import Intent

        agent_registry = AgentRegistry()
        agent_registry.register(_agent_spec("simple", tools=["web.search"]), status=AgentStatus.ACTIVE)
        engine = AutomationEngine()
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine, agent_selector=AgentSelector(agent_registry)
        )
        intent = Intent(
            action="search", original_text="har kuni qidir", requires_tools=["web.search"],
            request_kind="goal",
        )

        result = bridge.create_schedule(
            intent=intent,
            expression=ScheduleExpression(cron="0 9 * * *", reason="har kuni"),
            command_text="har kuni yangilik qidir",
        )

        assert result.ok is True
        rule = engine.scheduler.get_rule(result.rule_id)
        assert rule is not None
        assert rule.use_brain is False


class TestFullChainScheduledMissionThroughBrain:
    """HAQIQIY zanjir: ScheduleRule → AutomationDaemon → Brain → Mission →
    TaskGraph → HAQIQIY tool chaqiruvlari (spec TEST H'ga mos).

    Bu — spec'ning §2/§23 aynan so'ragan isboti: murakkab rejalashtirilgan
    vazifa endi "ahmoq dispatcher" emas, TO'LIQ kognitiv yo'l orqali
    (Intent→ExecutionMode→Mission→TaskGraph→AgentSelector→ModelRouter→
    tool→COMPLETED gate) bajariladi.
    """

    async def test_scheduled_complex_rule_runs_full_cognitive_path(
        self, session: Any, owner: Owner, session_factory: Any
    ) -> None:
        # ── Capability DAG (github_audit -> analysis_report) ──
        cap_registry = CapabilityRegistry()
        cap_registry.register(
            Capability(
                name="github_audit", description="GitHub loyihani tekshiradi",
                supported_outcomes=["issues_found"],
                actions=["audit"], default_tools=["github.read"], tags=["github"],
            )
        )
        cap_registry.register(
            Capability(
                name="analysis_report", description="Muammolarni tahlil qilib hisobot tuzadi",
                supported_outcomes=["report"],
                actions=["analyze"], default_tools=["code_analysis"],
                dependencies=["github_audit"], tags=["analysis"],
            )
        )

        agent_registry = AgentRegistry()
        agent_registry.register(_agent_spec("github-auditor", tools=["github.read"]), status=AgentStatus.ACTIVE)
        agent_registry.register(_agent_spec("code-analyst", tools=["code_analysis"]), status=AgentStatus.ACTIVE)
        composer = CapabilityRegistryComposer(cap_registry, agent_registry=agent_registry)

        tool_registry = ToolRegistry()
        github_tool = _StubTool("github.read")
        analysis_tool = _StubTool("code_analysis")
        tool_registry.register(github_tool)
        tool_registry.register(analysis_tool)

        model_router = BrainModelRouter()
        agent_provider = FakeProvider(
            scripted=[
                fake_response(text="", tool_uses=(_agent_tool_use("github.read"),)),
                fake_response(text="GitHub audit yakunlandi."),
                fake_response(text="", tool_uses=(_agent_tool_use("code_analysis"),)),
                fake_response(text="Tahlil hisobot tayyor."),
            ]
        )
        task_graph_executor = TaskGraphExecutor(
            agent_registry=agent_registry, tool_registry=tool_registry,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            llm_provider=agent_provider, model_router=model_router, max_retries=0,
        )

        class _RecordingMemory:
            def __init__(self) -> None:
                self.written: list[Any] = []

            async def remember(self, owner_id: Any, content: str, *, layer: str, source: str) -> None:
                self.written.append(content)

        class _FakeContextEngine:
            async def discover(self, objective: str, *, owner_id: Any, constraints: list[str]) -> Any:
                class _Empty:
                    def to_dict(self) -> dict[str, Any]:
                        return {}
                return _Empty()

        memory = _RecordingMemory()
        repo = MissionRepository(session, owner_id=owner.id)
        mission_engine = MissionEngine(
            repository=repo, capability_registry=composer,
            context_engine=_FakeContextEngine(),  # type: ignore[arg-type]
            planner=object(), orchestrator=object(), approvals=ApprovalService(),
            memory_store=memory, task_graph_executor=task_graph_executor,
        )

        class _UnusedOrchestrator:
            async def start(self, *a: Any, **k: Any) -> Any:
                raise AssertionError("GOAL yo'lida Orchestrator.start() chaqirilmasligi kerak")

        mission_orchestrator = MissionOrchestrator(
            capability_registry=composer, context_engine=_FakeContextEngine(),
            mission_engine=mission_engine, planner=object(), executor=None,
            verifier=object(), recovery_engine=None, approval_service=ApprovalService(),
            permission_policy=PermissionPolicy(auto_approve_write=True), notifier=StubNotifier(),
            killswitch=None,
        )

        intent_provider = FakeProvider(
            name="ollama",
            scripted=[
                fake_response(text="", tool_uses=(
                    _intent_tool_use(action="github.audit", requires_tools=["github.read", "code_analysis"]),
                )),
            ],
        )
        settings_obj = __import__("zet.config", fromlist=["Settings"]).Settings(_env_file=None)
        intent_router = ModelRouter(providers={intent_provider.name: intent_provider}, session=session, settings=settings_obj)
        intent_recognizer = IntentRecognizer(intent_router)

        async def _mission_runner(command: Any) -> Any:
            return await mission_orchestrator.run(command, owner_id=owner.id)

        brain = Brain(
            orchestrator=_UnusedOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=intent_recognizer, mission_runner=_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
        )

        async def _brain_factory(sess: Any) -> Brain:
            return brain

        engine = __import__("zet.automation.engine", fromlist=["AutomationEngine"]).AutomationEngine()
        daemon = AutomationDaemon(
            engine=engine, agent_registry=agent_registry, tool_registry=tool_registry,
            permission_policy=PermissionPolicy(auto_approve_write=True),
            core_state=__import__("zet.core.state", fromlist=["CoreState"]).CoreState(),
            killswitch=KillSwitchState(),
            session_factory=session_factory,
            brain_factory=_brain_factory,
        )

        rule = ScheduleRule(
            name="scheduled cognitive audit", agent_name="github-auditor",
            cron_expr="* * * * *",
            command=(
                "GitHub loyihamni audit qil, muammolarni top, ularni "
                "ustuvorlik bo'yicha guruhla, tuzatish rejasini tuz va "
                "yakuniy hisobot ber."
            ),
            use_brain=True,
        )
        engine.scheduler.add_rule(rule)

        await daemon._fire(rule)

        # HAQIQIY DALIL: ikkala tool chaqirildi — Brain -> Mission ->
        # TaskGraph -> AgentSelector -> tool zanjiri to'liq ishladi.
        assert github_tool.calls >= 1
        assert analysis_tool.calls >= 1
        assert memory.written
