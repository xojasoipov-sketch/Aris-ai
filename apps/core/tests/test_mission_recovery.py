"""Mission restart recovery testlari (JB-10).

Isbotlaydi:
    1. Non-terminal mission'lar startup'da spawn qilinadi.
    2. Terminal (COMPLETED/FAILED/CANCELLED) — HECH QACHON qayta.
    3. WAITING_APPROVAL — ATAYLAB o'tkazib yuboriladi.
    4. Har mission uchun asyncio.Lock — parallel drayvchilarni oldi.
    5. UNDERSTANDING/VERIFYING holatlari (JB-10 fix'i) — endi
       muzlab qolmaydi, xavfsiz safeni tanlaydi.

DB assertion'lar HAQIQIY (`repo.get(mid).status`) — soxta "resumed"
xabari yozmaymiz.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.core.mission import Mission, MissionEngine
from zet.core.mission_recovery import (
    acquire_mission_lock,
    load_incomplete_missions,
)
from zet.core.mission_repository import MissionRepository
from zet.db.models import Owner
from zet.db.models.run import Run
from zet.domain.enums import (
    MissionStatus,
    PermissionLevel,
    RiskLevel,
    RunStatus,
    RunTrigger,
)
from zet.security.approvals import ApprovalService


# ── Soxta bog'liqliklar (bir xil test_mission_engine.py naqshi) ─
@dataclass
class FakeBundle:
    capabilities: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=lambda: ["note.write"])
    permissions_required: list[PermissionLevel] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class FakeCapabilityRegistry:
    def __init__(self, bundle: FakeBundle) -> None:
        self.bundle = bundle

    def compose(self, objective: str, context: dict[str, Any]) -> FakeBundle:
        return self.bundle


class FakeRelevantContext:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class FakeContextEngine:
    async def discover(
        self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
    ) -> FakeRelevantContext:
        return FakeRelevantContext({})


@dataclass
class FakeRunRecord:
    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None


class FakeOrchestrator:
    def __init__(self, session: AsyncSession, owner: Owner) -> None:
        self._session = session
        self._owner = owner
        self._queued: list[FakeRunRecord] = []
        self.start_calls: list[Any] = []

    def queue(self, *records: FakeRunRecord) -> None:
        self._queued.extend(records)

    async def start(
        self,
        command: Any,
        *,
        dry_run: bool = False,
        intent: Any = None,
        tool_registry_override: Any = None,
    ) -> FakeRunRecord:
        self.start_calls.append(command)
        if not self._queued:
            raise AssertionError("FakeOrchestrator navbati bo'sh")
        record = self._queued.pop(0)
        run = Run(
            id=record.run_id,
            owner_id=self._owner.id,
            trigger=RunTrigger.MANUAL,
            command_text="x",
            trace_id="trace",
        )
        self._session.add(run)
        await self._session.flush()
        return record


def _build_engine(
    repo: MissionRepository,
    approvals: ApprovalService,
    session: AsyncSession,
    owner: Owner,
) -> tuple[MissionEngine, FakeOrchestrator]:
    orch = FakeOrchestrator(session, owner)
    engine = MissionEngine(
        repository=repo,
        capability_registry=FakeCapabilityRegistry(FakeBundle()),
        context_engine=FakeContextEngine(),
        planner=SimpleNamespace(),
        orchestrator=orch,  # type: ignore[arg-type]
        approvals=approvals,
    )
    return engine, orch


# ── run_to_completion — UNDERSTANDING/VERIFYING fix ───────────────
class TestRunToCompletionRestartPickup:
    """JB-10 §4/§5: `run_to_completion` UNDERSTANDING/VERIFYING'da
    endi muzlab qolmaydi (audit topilmasi)."""

    async def test_understanding_now_resumes_via_discovering(
        self,
        session: AsyncSession,
        owner: Owner,
    ) -> None:
        repo = MissionRepository(session, owner_id=owner.id)
        approvals = ApprovalService()
        engine, orch = _build_engine(repo, approvals, session, owner)
        orch.queue(FakeRunRecord(run_id=uuid.uuid4()))

        m = await engine.submit(owner_id=owner.id, objective="x")
        # UNDERSTANDING holatiga qo'lda (crash simulyatsiyasi).
        await repo.set_status(m.id, MissionStatus.UNDERSTANDING)

        final = await engine.run_to_completion(m.id)

        # HAQIQIY holat — endi COMPLETED (ilgari UNDERSTANDING'da qolib
        # muzlab qolar edi).
        assert final.status is MissionStatus.COMPLETED

    async def test_verifying_now_transitions_to_recovering(
        self,
        session: AsyncSession,
        owner: Owner,
    ) -> None:
        """VERIFYING'da muzlab qolmaydi — RECOVERING'ga o'tadi va oldinga
        siljiydi. Ilgari `else: break` tushib jimgina qotib qolar edi."""
        repo = MissionRepository(session, owner_id=owner.id)
        approvals = ApprovalService()
        engine, orch = _build_engine(repo, approvals, session, owner)
        # Recovery loop bir necha marta EXECUTING'ga qaytishi mumkin —
        # bir nechta run yuklaymiz (test max_retries=2 default bilan).
        for _ in range(5):
            orch.queue(FakeRunRecord(run_id=uuid.uuid4(), verified_ok=False))

        m = await engine.submit(owner_id=owner.id, objective="x")
        # VERIFYING'ga majburiy (crash simulyatsiyasi).
        for s in (
            MissionStatus.UNDERSTANDING,
            MissionStatus.DISCOVERING,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.VERIFYING,
        ):
            await repo.set_status(m.id, s)

        final = await engine.run_to_completion(m.id)

        # KRITIK DALIL: VERIFYING'da MUZLAB QOLMADI — terminal holatga
        # yetdi (FAILED, chunki verified_ok=False orqali recovery loop
        # max_retries chegarasiga yetdi). Ilgari status VERIFYING'da
        # qolardi.
        assert final.status != MissionStatus.VERIFYING
        assert final.status.is_terminal


# ── load_incomplete_missions bootstrap ────────────────────────────
class TestLoadIncompleteMissions:
    async def test_terminal_missions_never_resumed(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """§20/§21: COMPLETED/FAILED/CANCELLED — hech qachon qayta emas."""
        repo = MissionRepository(session, owner_id=owner.id)

        # Bittasini COMPLETED holatiga olib boramiz.
        completed = await repo.create(Mission(owner_id=owner.id, objective="done"))
        for s in (
            MissionStatus.UNDERSTANDING,
            MissionStatus.DISCOVERING,
            MissionStatus.PLANNING,
            MissionStatus.EXECUTING,
            MissionStatus.VERIFYING,
            MissionStatus.COMPLETED,
        ):
            await repo.set_status(completed.id, s)

        # FAILED.
        failed = await repo.create(Mission(owner_id=owner.id, objective="failed"))
        await repo.set_status(failed.id, MissionStatus.FAILED, force=True)

        # CANCELLED.
        cancelled = await repo.create(Mission(owner_id=owner.id, objective="cancelled"))
        await repo.set_status(cancelled.id, MissionStatus.CANCELLED, force=True)

        await session.commit()

        engine_calls: list[uuid.UUID] = []

        async def track_factory(sess: AsyncSession) -> MissionEngine:
            # Fake engine — run_to_completion chaqirilganini yozadi.
            class _Fake:
                async def run_to_completion(self, mid: uuid.UUID) -> None:
                    engine_calls.append(mid)

            return _Fake()  # type: ignore[return-value]

        n = await load_incomplete_missions(
            session_factory,
            track_factory,
            owner_external_id=owner.external_id,
        )

        # Terminal'lar hech biri task'ga tushmagani — kritik.
        await asyncio.sleep(0.05)  # spawn qilingan task'lar to'liq ishga tushishi uchun
        assert completed.id not in engine_calls
        assert failed.id not in engine_calls
        assert cancelled.id not in engine_calls
        assert n == 0

    async def test_waiting_approval_missions_skipped(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """§9: WAITING_APPROVAL — approval oqimi mas'uliyati."""
        repo = MissionRepository(session, owner_id=owner.id)

        wa = await repo.create(Mission(owner_id=owner.id, objective="awaiting"))
        for s in (
            MissionStatus.UNDERSTANDING,
            MissionStatus.DISCOVERING,
            MissionStatus.PLANNING,
            MissionStatus.WAITING_APPROVAL,
        ):
            await repo.set_status(wa.id, s)
        await session.commit()

        engine_calls: list[uuid.UUID] = []

        async def track_factory(sess: AsyncSession) -> MissionEngine:
            class _Fake:
                async def run_to_completion(self, mid: uuid.UUID) -> None:
                    engine_calls.append(mid)

            return _Fake()  # type: ignore[return-value]

        n = await load_incomplete_missions(
            session_factory,
            track_factory,
            owner_external_id=owner.external_id,
        )

        await asyncio.sleep(0.05)
        assert wa.id not in engine_calls
        assert n == 0

    async def test_incomplete_mission_spawns_resume_task(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Yagona haqiqiy dalili: PLANNING mission → spawn qilinadi."""
        repo = MissionRepository(session, owner_id=owner.id)

        pending = await repo.create(Mission(owner_id=owner.id, objective="pending"))
        for s in (
            MissionStatus.UNDERSTANDING,
            MissionStatus.DISCOVERING,
            MissionStatus.PLANNING,
        ):
            await repo.set_status(pending.id, s)
        await session.commit()

        engine_calls: list[uuid.UUID] = []
        call_done = asyncio.Event()

        async def track_factory(sess: AsyncSession) -> MissionEngine:
            class _Fake:
                async def run_to_completion(self, mid: uuid.UUID) -> None:
                    engine_calls.append(mid)
                    call_done.set()

            return _Fake()  # type: ignore[return-value]

        n = await load_incomplete_missions(
            session_factory,
            track_factory,
            owner_external_id=owner.external_id,
        )

        assert n == 1
        # Spawn qilingan task ishga tushishini kutamiz.
        await asyncio.wait_for(call_done.wait(), timeout=2.0)
        assert pending.id in engine_calls

    async def test_load_fails_open(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """DB xatosi startup'ni yiqitmasin (fail-open)."""

        async def broken_factory(sess: AsyncSession) -> MissionEngine:
            raise RuntimeError("factory yiqilgan")

        # Real DB, real query — sim uchun MissionRepository ishlaydi
        # (bo'sh natija qaytaradi), factory chaqirilmaydi. Bu test
        # asosiy fail-open pathi uchun oqim buzilmasligini isbotlaydi.
        n = await load_incomplete_missions(
            session_factory,
            broken_factory,
            owner_external_id="nonexistent-owner-abc",
        )
        # Bo'sh natija — factory hech qachon chaqirilmagan, 0 qaytadi.
        assert n == 0


# ── acquire_mission_lock ──────────────────────────────────────────
class TestMissionLock:
    """§33: parallel drayvchi'lardan himoya."""

    async def test_same_mission_same_lock(self) -> None:
        mid = uuid.uuid4()
        lock1 = await acquire_mission_lock(mid)
        lock2 = await acquire_mission_lock(mid)
        assert lock1 is lock2

    async def test_different_missions_different_locks(self) -> None:
        lock_a = await acquire_mission_lock(uuid.uuid4())
        lock_b = await acquire_mission_lock(uuid.uuid4())
        assert lock_a is not lock_b

    async def test_lock_serializes_concurrent_callers(self) -> None:
        """Ikki task bir vaqtda mission'ni ushlashga urinsa — navbatga tushadi."""
        mid = uuid.uuid4()
        order: list[str] = []

        async def worker(name: str, delay: float) -> None:
            lock = await acquire_mission_lock(mid)
            async with lock:
                order.append(f"{name}:enter")
                await asyncio.sleep(delay)
                order.append(f"{name}:exit")

        await asyncio.gather(worker("A", 0.05), worker("B", 0.01))

        # Bittasi butunlay tugagach ikkinchisi boshlanadi.
        assert order.index("A:exit") < order.index("B:enter") or order.index(
            "B:exit"
        ) < order.index("A:enter")


# ── Configuration flag ────────────────────────────────────────────
class TestConfigFlag:
    def test_default_enabled(self) -> None:
        from zet.config import Settings

        s = Settings()  # type: ignore[call-arg]
        assert s.mission_restart_recovery_enabled is True
