"""Brain triaj va marshrutlash testlari (JB-2).

Audit topilmasi: hech bir kanal xabarni "oddiy savol" va "ko'p qadamli
maqsad" deb ajratmasdi, Mission qatlami esa faqat REST endpoint'idan
yetsa bo'lardi. Bu testlar yangi marshrutlashning HAR bir shoxini
tekshiradi — ayniqsa REGRESSIYA KAFOLATINI: mission boshlanmasa
so'rov eski Run yo'liga qaytadi.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from zet.core.brain import Brain, BrainRoute
from zet.core.intent import AmbiguousCommandError, IntentError
from zet.core.mission import Mission
from zet.domain.command import Command, Intent
from zet.domain.enums import MissionStatus, RunStatus

OWNER = uuid.uuid4()


class _FakeRun:
    """`RunRecord`ning Brain ishlatadigan qismi."""

    def __init__(self, *, summary: str | None = "javob", error: str | None = None) -> None:
        self.run_id = uuid.uuid4()
        self.status = RunStatus.DONE
        self.result_summary = summary
        self.error = error


class _FakeOrchestrator:
    def __init__(self, record: _FakeRun | None = None) -> None:
        self.record = record or _FakeRun()
        self.calls: list[dict[str, Any]] = []

    async def start(
        self,
        command: Command,
        *,
        dry_run: bool = False,
        intent: Intent | None = None,
    ) -> _FakeRun:
        self.calls.append({"text": command.text, "dry_run": dry_run, "intent": intent})
        return self.record


class _FakeIntent:
    """`IntentRecognizer` o'rniga — berilgan turni qaytaradi yoki xato otadi."""

    def __init__(self, *, kind: str = "command", raises: Exception | None = None) -> None:
        self.kind = kind
        self.raises = raises
        self.calls = 0

    async def recognize(self, command: Command, **_: Any) -> Intent:
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        return Intent(action="test", request_kind=self.kind, original_text=command.text)


def _mission(
    *,
    status: MissionStatus = MissionStatus.COMPLETED,
    run_ids: list[uuid.UUID] | None = None,
    error: str | None = None,
) -> Mission:
    return Mission(
        owner_id=OWNER,
        objective="biznesni tekshir",
        status=status,
        run_ids=run_ids or [],
        error=error,
    )


def _brain(
    orchestrator: _FakeOrchestrator,
    intent: _FakeIntent,
    *,
    mission: Mission | None = None,
    mission_error: Exception | None = None,
    run_lookup: Any = None,
    enabled: bool = True,
) -> Brain:
    mission_runner = None
    if mission is not None or mission_error is not None:

        async def mission_runner(command: Command) -> Mission:  # type: ignore[misc]
            if mission_error is not None:
                raise mission_error
            assert mission is not None
            return mission

    return Brain(
        orchestrator=orchestrator,  # type: ignore[arg-type]
        intent_recognizer=intent,  # type: ignore[arg-type]
        mission_runner=mission_runner,
        run_lookup=run_lookup,
        goal_missions_enabled=enabled,
    )


class TestTriage:
    async def test_command_goes_to_run_path(self) -> None:
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="command")
        brain = _brain(orch, intent, mission=_mission())

        result = await brain.handle(Command(text="eslatma yoz"))

        assert result.route is BrainRoute.RUN
        assert result.request_kind == "command"
        assert result.text == "javob"

    async def test_chat_goes_to_run_path(self) -> None:
        orch = _FakeOrchestrator()
        brain = _brain(orch, _FakeIntent(kind="chat"), mission=_mission())

        result = await brain.handle(Command(text="salom"))

        assert result.route is BrainRoute.RUN
        assert result.request_kind == "chat"

    async def test_precomputed_intent_is_reused(self) -> None:
        """Triaj intent'i Orchestrator'ga uzatiladi — LLM ikki marta emas."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="command")
        brain = _brain(orch, intent, mission=_mission())

        await brain.handle(Command(text="eslatma yoz"))

        assert intent.calls == 1
        assert orch.calls[0]["intent"] is not None

    async def test_goal_goes_to_mission_path(self) -> None:
        run = _FakeRun(summary="biznes tahlili tayyor")
        mission = _mission(run_ids=[run.run_id])
        orch = _FakeOrchestrator()
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission=mission,
            run_lookup=lambda _rid: run,
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.MISSION
        assert result.mission_id == str(mission.id)
        # Javob MATNI mission bog'lagan run'dan keladi — mission modeli
        # javob matnini saqlamaydi.
        assert result.text == "biznes tahlili tayyor"
        # Run yo'li UMUMAN chaqirilmagan.
        assert orch.calls == []


class TestFallback:
    async def test_mission_that_never_started_falls_back_to_run(self) -> None:
        """Regressiya kafolati: capability mos kelmasa eski yo'l ishlaydi."""
        orch = _FakeOrchestrator(_FakeRun(summary="oddiy javob"))
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission=_mission(
                status=MissionStatus.FAILED,
                run_ids=[],
                error="no capability matched objective",
            ),
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.MISSION_FALLBACK
        assert result.text == "oddiy javob"
        assert len(orch.calls) == 1

    async def test_failed_mission_with_runs_is_not_retried(self) -> None:
        """Ish HAQIQATAN boshlangan bo'lsa qayta yugurtirmaymiz (ikki marta yon effekt)."""
        run = _FakeRun(summary="yarim natija")
        orch = _FakeOrchestrator()
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission=_mission(status=MissionStatus.FAILED, run_ids=[run.run_id], error="xato"),
            run_lookup=lambda _rid: run,
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.MISSION
        assert result.ok is False
        assert orch.calls == []

    async def test_mission_runner_crash_falls_back(self) -> None:
        orch = _FakeOrchestrator(_FakeRun(summary="zaxira javob"))
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission_error=RuntimeError("mission qatlami yiqildi"),
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.MISSION_FALLBACK
        assert result.text == "zaxira javob"

    @pytest.mark.parametrize(
        "exc",
        [
            AmbiguousCommandError("Nimani nazarda tutdingiz?", Intent(action="?")),
            IntentError("LLM javob bermadi"),
        ],
    )
    async def test_triage_failure_never_blocks_request(self, exc: Exception) -> None:
        """Triajning O'ZI so'rovni yiqitmaydi — Orchestrator to'g'ri ishlaydi."""
        orch = _FakeOrchestrator()
        brain = _brain(orch, _FakeIntent(raises=exc), mission=_mission())

        result = await brain.handle(Command(text="noaniq gap"))

        assert result.route is BrainRoute.RUN
        # Intent Orchestrator ichida QAYTA hisoblanadi (u yerda bu
        # holatlar allaqachon to'g'ri qayta ishlanadi).
        assert orch.calls[0]["intent"] is None


class TestDisabled:
    async def test_no_mission_runner_skips_triage_llm(self) -> None:
        """Mission yo'li yo'q bo'lsa triajga LLM sarflashning ma'nosi yo'q."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="goal")
        brain = _brain(orch, intent)  # mission_runner yo'q

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.RUN
        assert intent.calls == 0

    async def test_setting_disabled_skips_mission(self) -> None:
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="goal")
        brain = _brain(orch, intent, mission=_mission(), enabled=False)

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.RUN
        assert intent.calls == 0

    async def test_dry_run_never_creates_mission(self) -> None:
        """Quruq ishga tushirish sinov — u haqiqiy mission ochmasligi kerak."""
        orch = _FakeOrchestrator()
        intent = _FakeIntent(kind="goal")
        brain = _brain(orch, intent, mission=_mission())

        result = await brain.handle(Command(text="biznesimni tekshir"), dry_run=True)

        assert result.route is BrainRoute.RUN
        assert intent.calls == 0
        assert orch.calls[0]["dry_run"] is True


class TestMissionText:
    async def test_waiting_approval_message(self) -> None:
        orch = _FakeOrchestrator()
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission=_mission(status=MissionStatus.WAITING_APPROVAL),
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert "Tasdiq kutilmoqda" in result.text
        assert result.ok is False

    async def test_run_lookup_failure_degrades_to_status_text(self) -> None:
        """Run o'qilmasa ham ega bo'sh javob olmaydi."""

        def _broken(_rid: uuid.UUID) -> Any:
            raise RuntimeError("run topilmadi")

        run_id = uuid.uuid4()
        orch = _FakeOrchestrator()
        brain = _brain(
            orch,
            _FakeIntent(kind="goal"),
            mission=_mission(run_ids=[run_id]),
            run_lookup=_broken,
        )

        result = await brain.handle(Command(text="biznesimni tekshir"))

        assert result.route is BrainRoute.MISSION
        assert "biznesni tekshir" in result.text
