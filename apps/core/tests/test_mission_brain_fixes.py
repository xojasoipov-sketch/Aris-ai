"""Mission Engine "miya" tuzatishlari testlari (audit topilmalari).

NEGA alohida fayl — ikki audit topilmasi qulflanadi:

1. "Ko'r retry": `execute()` ilgari Command'ga faqat `mission.objective`ni
   uzatardi — `MissionRecoveryAdapter` `mission.constraints`ga yozgan
   "[recovery] ..." tashxis hint'i keyingi urinish Command'iga HECH
   QACHON yetmasdi (retry aynan bir xil ko'r urinish edi). Endi
   cheklovlar `Command.history` orqali uzatiladi (`Command`da
   `constraints` maydoni yo'q — u `Intent`da) va IntentRecognizer/
   Planner/Executor LLM'lari ularni ko'radi.

2. "Bo'sh xotira": `mission.memory_updates`ni hech qanday kod
   to'ldirmasdi — `_write_memory_updates` har doim bo'sh ro'yxatni
   ko'rib, COMPLETED mission'dan keyin xotiraga hech narsa yozilmasdi.
   Endi `verify()` COMPLETED'da default yakun yozuvini qo'shadi (aniq
   berilgan yozuvlar ustuvor qoladi — default ularni bosib ketmaydi).

Soxta bog'liqliklar `test_mission_engine.py` naqshida qurilgan (u fayl
o'zgartirilmagan — bu yerda mustaqil, yengil nusxalar).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.core.mission import Mission, MissionEngine
from zet.core.mission_repository import MissionRepository
from zet.db.models import Owner
from zet.db.models.run import Run
from zet.domain.command import Command
from zet.domain.enums import (
    MessageRole,
    MissionStatus,
    PermissionLevel,
    RiskLevel,
    RunStatus,
    RunTrigger,
)
from zet.security.approvals import ApprovalService

# ── Soxta bog'liqliklar ──────────────────────────────────────────


@dataclass
class FakeBundle:
    capabilities: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions_required: list[PermissionLevel] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class FakeCapabilityRegistry:
    def __init__(self, bundle: FakeBundle) -> None:
        self.bundle = bundle

    def compose(self, objective: str, context: dict[str, Any]) -> FakeBundle:
        return self.bundle


class FakeContextEngine:
    async def discover(
        self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
    ) -> Any:
        return SimpleNamespace(to_dict=lambda: {})


@dataclass
class FakeRunRecord:
    """`RunRecord`ning yengil nusxasi — `result_summary` BILAN.

    NEGA `test_mission_engine.py`dagi fake'dan farqli: xotira testi
    `result_summary` yakuniy yozuvga kirishini tekshiradi.
    """

    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None
    result_summary: str | None = None


@dataclass
class LeanRunRecord:
    """`result_summary`SIZ record — verify() fail-open (getattr) qulfi."""

    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None


class RecordingOrchestrator:
    """start()'ga kelgan Command'larni YOZIB OLADI — audit fix'ning
    asosiy dalili shu ro'yxatda (hint keyingi Command'da ko'rinadimi)."""

    def __init__(self, session: AsyncSession, owner: Owner) -> None:
        self._session = session
        self._owner = owner
        self._queued: list[Any] = []
        self.commands: list[Command] = []

    def queue(self, *records: Any) -> None:
        self._queued.extend(records)

    async def start(self, command: Command, *, dry_run: bool = False) -> Any:
        self.commands.append(command)
        if not self._queued:
            raise AssertionError("RecordingOrchestrator navbati bo'sh")
        record = self._queued.pop(0)
        # Real Run yozuvi — MissionRunLink FK talab qiladi
        run = Run(
            id=record.run_id,
            owner_id=self._owner.id,
            trigger=RunTrigger.MANUAL,
            command_text=command.text,
            trace_id="trace",
        )
        self._session.add(run)
        await self._session.flush()
        return record


class FakeMemoryStore:
    """`remember()` chaqiruvlarining TO'LIQ argumentlarini yozib oladi."""

    def __init__(self) -> None:
        self.written: list[dict[str, Any]] = []

    async def remember(
        self,
        owner_id: uuid.UUID,
        content: str,
        *,
        layer: str,
        source: str,
    ) -> None:
        self.written.append(
            {"owner_id": owner_id, "content": content, "layer": layer, "source": source}
        )


class HintingRecovery:
    """`MissionRecoveryAdapter` xatti-harakatini takrorlaydi (LLM'siz):
    tashxis hint'ini `mission.constraints`ga yozadi — DB orqali, xuddi
    real adapter kabi."""

    def __init__(self, repo: MissionRepository, hint: str) -> None:
        self._repo = repo
        self._hint = hint
        self.calls = 0

    async def diagnose_and_patch(self, mission: Mission, last_failure: str) -> Mission:
        self.calls += 1
        return await self._repo.update(
            mission.id, constraints=[*mission.constraints, f"[recovery] {self._hint}"]
        )


# ── Fixture'lar ──────────────────────────────────────────────────


@pytest.fixture
def repo(session: AsyncSession, owner: Owner) -> MissionRepository:
    return MissionRepository(session, owner_id=owner.id)


@pytest.fixture
def approvals() -> ApprovalService:
    return ApprovalService()


def _engine(
    *,
    repo: MissionRepository,
    approvals: ApprovalService,
    session: AsyncSession,
    owner: Owner,
    memory: FakeMemoryStore | None = None,
    recovery: HintingRecovery | None = None,
) -> tuple[MissionEngine, RecordingOrchestrator]:
    orch = RecordingOrchestrator(session, owner)
    engine = MissionEngine(
        repository=repo,
        capability_registry=FakeCapabilityRegistry(FakeBundle(tools=["note.write"])),
        context_engine=FakeContextEngine(),
        planner=SimpleNamespace(),  # plan() chaqirilmaydi — bundle to'g'ridan-to'g'ri task bo'ladi
        orchestrator=orch,  # type: ignore[arg-type]
        approvals=approvals,
        recovery=recovery,
        memory_store=memory,
    )
    return engine, orch


# ── 1-topilma: recovery hint keyingi attempt Command'iga yetadi ──


class TestRecoveryHintReachesNextAttempt:
    async def test_recovery_hint_visible_in_second_attempt_command(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """ASOSIY DALIL: 1-urinish yiqiladi → recovery hint yozadi →
        2-urinish Command'ining history'sida hint KO'RINADI (ilgari
        ikkala Command aynan bir xil — ko'r retry edi)."""
        recovery = HintingRecovery(repo, hint="timeout'ni oshirib qayta urin")
        engine, orch = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, recovery=recovery
        )
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e1"
            ),
            FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True),
        )

        m = await engine.submit(owner_id=owner.id, objective="tashqi API'dan ma'lumot olish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert recovery.calls == 1
        assert len(orch.commands) == 2

        # 1-urinish: hali hint yo'q — history bo'sh.
        assert orch.commands[0].history == []

        # 2-urinish: hint history orqali yetib borgan.
        second = orch.commands[1]
        assert len(second.history) == 1
        turn = second.history[0]
        assert turn.role is MessageRole.USER
        assert "[recovery] timeout'ni oshirib qayta urin" in turn.content
        # Objective o'zgarishsiz — hint text'ni ifloslamaydi.
        assert second.text == "tashqi API'dan ma'lumot olish"

    async def test_submit_constraints_reach_first_attempt_command(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """Submit'da berilgan cheklovlar ham BIRINCHI Command'ga yetadi —
        ilgari ular ham butunlay yo'qolardi."""
        engine, orch = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(
            owner_id=owner.id,
            objective="hisobot yoz",
            constraints=["o'zbek tilida", "qisqa bo'lsin"],
        )
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(orch.commands) == 1
        content = orch.commands[0].history[0].content
        assert "o'zbek tilida" in content
        assert "qisqa bo'lsin" in content

    async def test_no_constraints_keeps_history_empty(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """Cheklovsiz mission — Command o'zgarishsiz (bo'sh history),
        oddiy oqimga hech qanday shovqin qo'shilmaydi."""
        engine, orch = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        await engine.run_to_completion(m.id)

        assert orch.commands[0].history == []


# ── 2-topilma: COMPLETED mission xotiraga yoziladi ───────────────


class TestCompletedMissionMemory:
    async def test_completed_mission_writes_default_memory_entry(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """ASOSIY DALIL: hech kim `memory_updates`ni to'ldirmagan bo'lsa
        ham COMPLETED'da xotiraga default yakun yozuvi tushadi (ilgari
        HECH NARSA yozilmasdi)."""
        memory = FakeMemoryStore()
        engine, orch = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, memory=memory
        )
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(),
                status=RunStatus.DONE,
                verified_ok=True,
                result_summary="sayt tayyor: https://example.uz",
            )
        )

        m = await engine.submit(owner_id=owner.id, objective="sayt qur")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(memory.written) == 1
        entry = memory.written[0]
        assert "sayt qur" in entry["content"]  # objective
        assert "sayt tayyor: https://example.uz" in entry["content"]  # result_summary
        assert entry["layer"] == "project"
        assert entry["source"] == f"mission:{m.id}"
        assert entry["owner_id"] == owner.id

        # DB'da ham saqlangan — mission qatori nimani eslashni hujjatlaydi.
        fresh = await repo.get(m.id)
        assert len(fresh.memory_updates) == 1
        assert "sayt qur" in fresh.memory_updates[0]

    async def test_record_without_result_summary_still_writes(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """`result_summary`siz record (fail-open getattr) — yozuv faqat
        objective bilan tushadi, verify() yiqilmaydi."""
        memory = FakeMemoryStore()
        engine, orch = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, memory=memory
        )
        orch.queue(LeanRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(memory.written) == 1
        assert "ish" in memory.written[0]["content"]
        assert "natija:" not in memory.written[0]["content"]

    async def test_explicit_memory_updates_not_overwritten(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """Aniq berilgan `memory_updates` ustuvor — default yozuv ularni
        bosib ketmaydi (mavjud `test_completed_writes_memory_updates`
        kutilmasi bilan mos)."""
        memory = FakeMemoryStore()
        engine, orch = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, memory=memory
        )
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        await repo.update(m.id, memory_updates=["fikr: ega loyihani xohladi"])
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(memory.written) == 1
        assert memory.written[0]["content"] == "fikr: ega loyihani xohladi"

    async def test_failed_mission_writes_nothing(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """FAILED mission — xotiraga hech narsa tushmaydi (default yozuv
        faqat COMPLETED uchun)."""
        memory = FakeMemoryStore()
        engine, orch = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            memory=memory,
            recovery=HintingRecovery(repo, hint="h"),
        )
        # max_retries=2 (default) → 3 yiqilgan urinish → FAILED
        orch.queue(
            *[
                FakeRunRecord(
                    run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e"
                )
                for _ in range(3)
            ]
        )

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.FAILED
        assert memory.written == []
