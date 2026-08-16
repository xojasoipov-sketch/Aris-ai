"""Brain + ExecutionModeClassifier integratsiyasi (JB-8).

Eng muhim xavfsizlik dalili: "Workflowni to'xtat" kabi buyruq LLM
tomonidan xato ravishda `request_kind="goal"` deb belgilansa ham, Brain
YANGI Mission YARATMAYDI (mission_runner chaqirilmaydi).
"""

from __future__ import annotations

import uuid
from typing import Any

from zet.core.brain import Brain
from zet.core.execution_mode import ExecutionMode, ExecutionModeClassifier
from zet.core.mission import Mission
from zet.domain.command import Command, Intent
from zet.domain.enums import MissionStatus, RunStatus

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
    """Berilgan `request_kind`/`requires_tools` bilan Intent qaytaradi."""

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
    """`_mission_path_available` uchun mission_runner mavjudligini
    ta'minlaydi — bu testlarda haqiqatda chaqirilmaydi (request_kind
    "chat", `_handle_goal`ga yetib bormaydi)."""
    return _mission()


class TestWorkflowCommandNeverCreatesNewMission:
    async def test_stop_workflow_misclassified_as_goal_does_not_create_mission(self) -> None:
        """Eng muhim JB-8 dalili: LLM 'goal' desa ham, 'workflowni to'xtat'
        buyrug'i uchun mission_runner CHAQIRILMAYDI."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="goal")  # LLM XATO ravishda "goal" deydi
        mission_runner_calls: list[Command] = []

        async def mission_runner(command: Command) -> Mission:
            mission_runner_calls.append(command)
            return _mission()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=intent,  # type: ignore[arg-type]
            mission_runner=mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
        )

        result = await brain.handle(Command(text="Workflowni to'xtat."))

        assert mission_runner_calls == []  # HECH QANDAY yangi Mission yaratilmadi
        assert result.execution_mode == ExecutionMode.WORKFLOW_COMMAND.value
        assert orch.calls  # Run yo'liga tushdi (xavfsiz, mavjud xatti-harakat)

    async def test_ordinary_goal_still_creates_mission(self) -> None:
        """Regressiya kafolati: oddiy 'goal' so'rovlar hali ham Mission yaratadi."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="goal", requires_tools=["web.search"])
        mission_runner_calls: list[Command] = []

        async def mission_runner(command: Command) -> Mission:
            mission_runner_calls.append(command)
            return _mission()

        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=intent,  # type: ignore[arg-type]
            mission_runner=mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
        )

        result = await brain.handle(Command(text="Biznesimni tekshir va tahlil qil."))

        assert len(mission_runner_calls) == 1
        assert result.execution_mode == ExecutionMode.MISSION.value


class TestExecutionModeObservability:
    async def test_decision_attached_to_result(self) -> None:
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="chat")
        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=intent,  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
            execution_mode_classifier=ExecutionModeClassifier(),
        )

        result = await brain.handle(Command(text="Salom, qalaysan?"))

        assert result.execution_mode == ExecutionMode.DIRECT_RESPONSE.value
        assert result.execution_reason != ""

    async def test_no_classifier_leaves_execution_mode_empty(self) -> None:
        """Regressiya kafolati: klassifikator berilmasa (default) — bo'sh
        (JB-5/6/7 davridagi xatti-harakat butunlay o'zgarmagan)."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="chat")
        brain = Brain(
            orchestrator=orch,  # type: ignore[arg-type]
            intent_recognizer=intent,  # type: ignore[arg-type]
            mission_runner=_dummy_mission_runner,
        )

        result = await brain.handle(Command(text="Salom"))

        assert result.execution_mode == ""
        assert result.execution_reason == ""
