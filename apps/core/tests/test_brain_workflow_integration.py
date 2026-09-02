"""Brain + Scheduler/AutomationEngine haqiqiy integratsiyasi (JB-9).

JB-8 dalili: WORKFLOW_COMMAND yangi Mission YARATMAYDI. JB-9 dalili:
u endi HAQIQIY Scheduler amalini bajaradi va BACKGROUND_WORKFLOW
HAQIQIY `ScheduleRule` yaratadi.

Bu testlar Scheduler'ning haqiqiy holatiga qaraydi (ground truth) —
soxta "test o'tdi" xabari yozmaydi.
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationEngine
from zet.automation.scheduler import ScheduleRule, ScheduleStatus
from zet.core.agent_selector import AgentSelector
from zet.core.background_workflow import BackgroundWorkflowBridge
from zet.core.brain import Brain, BrainRoute
from zet.core.execution_mode import ExecutionModeClassifier
from zet.core.mission import Mission
from zet.core.workflow_command import WorkflowCommandExecutor
from zet.domain.agent import AgentSpec
from zet.domain.command import Command, Intent
from zet.domain.enums import AgentStatus, MissionStatus, RunStatus

OWNER = uuid.uuid4()


class _FakeRun:
    def __init__(self, *, summary: str | None = "javob") -> None:
        self.run_id = uuid.uuid4()
        self.status = RunStatus.DONE
        self.result_summary = summary
        self.error: str | None = None


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.record = _FakeRun()
        self.calls: list[dict[str, Any]] = []

    async def start(
        self, command: Command, *, dry_run: bool = False, intent: Intent | None = None
    ) -> _FakeRun:
        self.calls.append({"text": command.text, "intent": intent})
        return self.record


class _FakeIntent:
    def __init__(self, *, kind: str = "command", requires_tools: list[str] | None = None) -> None:
        self.kind = kind
        self.requires_tools = requires_tools or []
        self.calls = 0

    async def recognize(self, command: Command, **_: Any) -> Intent:
        self.calls += 1
        return Intent(
            action="test",
            request_kind=self.kind,
            requires_tools=self.requires_tools,
            original_text=command.text,
        )


def _mission() -> Mission:
    return Mission(
        owner_id=OWNER,
        objective="test",
        status=MissionStatus.COMPLETED,
        run_ids=[],
    )


async def _dummy_mission_runner(command: Command) -> Mission:
    return _mission()


def _build_agent_registry(*, tool: str = "telegram.read") -> AgentRegistry:
    """Bir ACTIVE agent bilan registry — bridge unga jadval biriktira oladi."""
    reg = AgentRegistry()
    reg.register(
        AgentSpec(
            name="tg-worker",
            description="Test uchun",
            system_prompt="Sen test agentisan.",
            tool_allowlist=[tool],
        ),
        status=AgentStatus.ACTIVE,
    )
    return reg


class TestBackgroundWorkflowCreatesRealScheduleRule:
    """JB-9 §5/§28 — 'har kuni' so'rovi HAQIQIY ScheduleRule yaratadi."""

    async def test_background_workflow_creates_persistent_schedule(self) -> None:
        engine = AutomationEngine()
        registry = _build_agent_registry(tool="telegram.read")
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            agent_selector=AgentSelector(registry),
        )
        orch = _FakeOrchestrator()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="goal", requires_tools=["telegram.read"]),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            background_workflow_bridge=bridge,
        )

        result = await brain.handle(Command(text="Har kuni soat 9 da telegramimni tekshir."))

        # HAQIQIY holat — Scheduler'da qoida bo'lishi kerak.
        rules = engine.scheduler.list_rules()
        assert len(rules) == 1
        assert rules[0].cron_expr == "0 9 * * *"
        assert rules[0].agent_name == "tg-worker"
        assert rules[0].command == "Har kuni soat 9 da telegramimni tekshir."
        # Brain oqimi — yangi ROUTE.
        assert result.route == BrainRoute.BACKGROUND_WORKFLOW_CREATED
        assert result.ok is True
        # Orchestrator umuman chaqirilmagan — buyruq HAQIQATAN
        # rejalashtirildi, BIR MARTA bajarilmadi.
        assert orch.calls == []

    async def test_background_workflow_without_agent_fails_honestly(self) -> None:
        """Mos agent yo'q — HECH QANDAY jadval yaratilmaydi (soxta OK emas)."""
        engine = AutomationEngine()
        empty_registry = AgentRegistry()  # ACTIVE agent yo'q
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            agent_selector=AgentSelector(empty_registry),
        )
        orch = _FakeOrchestrator()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="goal", requires_tools=["telegram.read"]),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            background_workflow_bridge=bridge,
        )

        result = await brain.handle(Command(text="Har kuni soat 9 da telegramimni tekshir."))

        # HECH QANDAY qoida yaratilmagani — ground truth.
        assert engine.scheduler.list_rules() == []
        assert result.route == BrainRoute.BACKGROUND_WORKFLOW_CREATED
        assert result.ok is False
        assert "agent" in result.text.lower() or "topilmadi" in result.text.lower()

    async def test_background_workflow_no_cron_falls_back_to_mission(self) -> None:
        """'Har kuni' aniq bo'lmasa (parser cron topa olmaydi) — Mission yo'liga tushadi."""
        engine = AutomationEngine()
        registry = _build_agent_registry()
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            agent_selector=AgentSelector(registry),
        )
        orch = _FakeOrchestrator()
        mission_calls: list[Command] = []

        async def track_mission(command: Command) -> Mission:
            mission_calls.append(command)
            return _mission()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            # 'muntazam' — RECURRING signali bor, lekin aniq vaqt yo'q.
            intent_recognizer=_FakeIntent(kind="goal", requires_tools=["telegram.read"]),  # type: ignore[arg-type]
            mission_runner=track_mission,
            execution_mode_classifier=ExecutionModeClassifier(),
            background_workflow_bridge=bridge,
        )

        result = await brain.handle(Command(text="Muntazam ravishda telegramimni tekshir."))

        # Cron ajratib bo'lmadi → Scheduler'da hech narsa yo'q.
        assert engine.scheduler.list_rules() == []
        # Mission yo'liga tushdi (goal edi).
        assert len(mission_calls) == 1
        assert result.route == BrainRoute.MISSION

    async def test_bridge_not_provided_keeps_jb8_behavior(self) -> None:
        """Bridge berilmasa — JB-8 xatti-harakati (BACKGROUND_WORKFLOW
        Mission yo'liga tushadi, hech qanday qoida yaratilmaydi)."""
        engine = AutomationEngine()
        orch = _FakeOrchestrator()
        mission_calls: list[Command] = []

        async def track_mission(command: Command) -> Mission:
            mission_calls.append(command)
            return _mission()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="goal", requires_tools=["telegram.read"]),  # type: ignore[arg-type]
            mission_runner=track_mission,
            execution_mode_classifier=ExecutionModeClassifier(),
            # background_workflow_bridge=... — ATAYLAB berilmagan
        )

        await brain.handle(Command(text="Har kuni soat 9 da tekshir."))

        assert engine.scheduler.list_rules() == []
        assert len(mission_calls) == 1  # eski yo'l


class TestWorkflowCommandRealBackend:
    """JB-9 §6/§41 — 'workflowni to'xtat' HAQIQATAN pause qiladi."""

    async def test_pause_command_pauses_actual_scheduler_rule(self) -> None:
        engine = AutomationEngine()
        rule = engine.scheduler.add_rule(
            ScheduleRule(
                name="Kunlik hisobot",
                agent_name="tg-worker",
                cron_expr="0 9 * * *",
            )
        )
        assert rule.status == ScheduleStatus.ACTIVE

        executor = WorkflowCommandExecutor(engine.scheduler)
        orch = _FakeOrchestrator()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="command"),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
        )

        result = await brain.handle(Command(text="Workflowni to'xtat."))

        # HAQIQIY holat — qoida PAUSED bo'lgani.
        stored = engine.scheduler.get_rule(rule.id)
        assert stored is not None
        assert stored.status == ScheduleStatus.PAUSED
        # Brain oqimi — WORKFLOW_COMMAND route.
        assert result.route == BrainRoute.WORKFLOW_COMMAND
        assert result.ok is True
        # Orchestrator umuman chaqirilmagan — buyruq HAQIQATAN
        # Scheduler orqali bajarildi, LLM ishlatilmadi.
        assert orch.calls == []

    async def test_list_command_returns_actual_rules(self) -> None:
        engine = AutomationEngine()
        engine.scheduler.add_rule(
            ScheduleRule(name="Kunlik", agent_name="a", cron_expr="0 9 * * *")
        )
        engine.scheduler.add_rule(
            ScheduleRule(name="Haftalik", agent_name="a", cron_expr="0 9 * * 1")
        )
        executor = WorkflowCommandExecutor(engine.scheduler)

        brain = Brain(
            orchestrator=_FakeOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="command"),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
        )

        result = await brain.handle(Command(text="Workflowlarimni ko'rsat."))

        assert result.route == BrainRoute.WORKFLOW_COMMAND
        assert "Kunlik" in result.text
        assert "Haftalik" in result.text

    async def test_ambiguous_pause_pauses_nothing(self) -> None:
        """JB-9 §7 kritik xavfsizlik dalili."""
        engine = AutomationEngine()
        r1 = engine.scheduler.add_rule(
            ScheduleRule(name="A", agent_name="a", cron_expr="0 9 * * *")
        )
        r2 = engine.scheduler.add_rule(
            ScheduleRule(name="B", agent_name="a", cron_expr="0 10 * * *")
        )
        executor = WorkflowCommandExecutor(engine.scheduler)

        brain = Brain(
            orchestrator=_FakeOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="command"),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
        )

        result = await brain.handle(Command(text="Workflowni to'xtat."))

        # HECH QAYSISI o'zgarmadi — kritik xavfsizlik dalili.
        assert engine.scheduler.get_rule(r1.id).status == ScheduleStatus.ACTIVE  # type: ignore[union-attr]
        assert engine.scheduler.get_rule(r2.id).status == ScheduleStatus.ACTIVE  # type: ignore[union-attr]
        assert result.ok is False
        assert "qaysi" in result.text.lower()

    async def test_workflow_command_still_never_creates_new_mission(self) -> None:
        """JB-8 dalili saqlangan: LLM 'goal' desa ham yangi mission yo'q."""
        engine = AutomationEngine()
        engine.scheduler.add_rule(
            ScheduleRule(name="Test", agent_name="a", cron_expr="0 9 * * *")
        )
        executor = WorkflowCommandExecutor(engine.scheduler)
        orch = _FakeOrchestrator()
        mission_calls: list[Command] = []

        async def track_mission(command: Command) -> Mission:
            mission_calls.append(command)
            return _mission()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="goal"),  # type: ignore[arg-type] — LLM xato
            mission_runner=track_mission,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
        )

        await brain.handle(Command(text="Workflowni to'xtat."))

        assert mission_calls == []  # JB-8 dalili saqlanadi
        assert orch.calls == []  # JB-9: Run yo'liga ham tushmaydi (backend haqiqiy)


class TestSchedulePersisterCallback:
    """`schedule_persister` faqat MUTATSIYA amallarida chaqiriladi."""

    async def test_persister_called_on_pause(self) -> None:
        engine = AutomationEngine()
        rule = engine.scheduler.add_rule(
            ScheduleRule(name="Test", agent_name="a", cron_expr="0 9 * * *")
        )
        executor = WorkflowCommandExecutor(engine.scheduler)
        persist_calls = 0

        async def persist() -> None:
            nonlocal persist_calls
            persist_calls += 1

        brain = Brain(
            orchestrator=_FakeOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="command"),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
            schedule_persister=persist,
        )

        await brain.handle(Command(text="Workflowni to'xtat."))

        assert persist_calls == 1
        assert engine.scheduler.get_rule(rule.id).status == ScheduleStatus.PAUSED  # type: ignore[union-attr]

    async def test_persister_not_called_on_list(self) -> None:
        """LIST — read-only. Persist keraksiz."""
        engine = AutomationEngine()
        engine.scheduler.add_rule(
            ScheduleRule(name="Test", agent_name="a", cron_expr="0 9 * * *")
        )
        executor = WorkflowCommandExecutor(engine.scheduler)
        persist_calls = 0

        async def persist() -> None:
            nonlocal persist_calls
            persist_calls += 1

        brain = Brain(
            orchestrator=_FakeOrchestrator(),  # type: ignore[arg-type]
            intent_recognizer=_FakeIntent(kind="command"),  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
            workflow_command_executor=executor,
            schedule_persister=persist,
        )

        await brain.handle(Command(text="Workflowlarimni ko'rsat."))

        assert persist_calls == 0  # LIST — persist chaqirilmadi


class TestBackgroundWorkflowBridgeUnit:
    """`BackgroundWorkflowBridge` alohida unit test — Brain'siz."""

    def test_create_schedule_picks_agent_with_matching_tool(self) -> None:
        from zet.core.schedule_expression import ScheduleExpression

        engine = AutomationEngine()
        registry = _build_agent_registry(tool="telegram.read")
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            agent_selector=AgentSelector(registry),
        )
        intent = Intent(
            action="test",
            request_kind="goal",
            requires_tools=["telegram.read"],
            original_text="test",
        )
        expression = ScheduleExpression(cron="0 9 * * *", reason="test")

        outcome = bridge.create_schedule(
            intent=intent,
            expression=expression,
            command_text="Har kuni tekshir",
        )

        assert outcome.ok is True
        assert outcome.rule_id is not None
        stored = engine.scheduler.get_rule(outcome.rule_id)
        assert stored is not None
        assert stored.agent_name == "tg-worker"

    def test_create_schedule_no_matching_agent(self) -> None:
        from zet.core.schedule_expression import ScheduleExpression

        engine = AutomationEngine()
        registry = _build_agent_registry(tool="telegram.read")
        bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            agent_selector=AgentSelector(registry),
        )
        intent = Intent(
            action="test",
            request_kind="goal",
            requires_tools=["github.read"],  # boshqa tool — hech kim qamramaydi
            original_text="test",
        )
        expression = ScheduleExpression(cron="0 9 * * *", reason="test")

        outcome = bridge.create_schedule(
            intent=intent,
            expression=expression,
            command_text="Har kuni tekshir",
        )

        assert outcome.ok is False
        assert engine.scheduler.list_rules() == []
