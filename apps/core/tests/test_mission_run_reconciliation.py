"""JB-13 Gap #1 — EXECUTING run-level recovery testlari.

AUDIT TOPILMASI (eng yuqori prioritet): `MissionEngine.execute()` mission
crash/restart'dan keyin qayta chaqirilganda (`mission.status` hali
EXECUTING, chunki avvalgi urinish tugallanmagan) HAR DOIM YANGI, RAQOBATDOSH
`Orchestrator` Run boshlardi — hatto avvalgi run hali "tirik"
(EXECUTING/AWAITING_APPROVAL) bo'lsa ham. Bu testlar `_reconcile_run()`
(SAFE_TO_RESUME/ALREADY_COMPLETED/NON_IDEMPOTENT_UNCERTAIN/UNKNOWN)
HAQIQIY DB + HAQIQIY Orchestrator/RunStore/Executor bilan to'g'ri
ishlashini isbotlaydi (mock emas).

MUHIM: `_real_orchestrator()` (pastda) `RunStore(session_factory=
session_factory, owner_external_id=owner.external_id)`ni to'g'ridan-to'g'ri
quradi — global `get_run_store()`/`get_session_factory()` singleton'lariga
(bular sozlanmagan/tarmoqqa bog'liq muhitda ishonchsiz — audit topilmasi,
pastdagi izohga qarang) TAYANMAYDI.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.core.mission import Mission, MissionEngine
from zet.core.mission_repository import MissionRepository
from zet.core.orchestrator import Orchestrator, RunStore
from zet.db.models import Owner
from zet.domain.enums import (
    MissionStatus,
    PermissionLevel,
    RunStatus,
    TrustLevel,
)
from zet.domain.plan import Plan, PlanStep
from zet.security.approvals import ApprovalService

# ── Yordamchilar (test_mission_engine.py'dagi `_real_orchestrator` bilan
#    bir xil naqsh — atayin mustaqil nusxa, fayllar orasida bog'liqlik
#    yaratmaslik uchun) ──────────────────────────────────────────────


def _real_intent_tool_use(requires_tools: list[str] | None = None) -> Any:
    from zet.llm.base import ToolUse

    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="parse_intent",
        arguments={
            "task_class": "normal",
            "intent_summary": "test",
            "requires_tools": requires_tools or [],
            "requires_confirmation": False,
            "ambiguity": "low",
        },
    )


def _real_plan_tool_use(steps: list[dict[str, Any]]) -> Any:
    from zet.llm.base import ToolUse

    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="create_plan",
        arguments={"summary": "test plan", "steps": steps},
    )


def _orchestrator(
    scripted: list[Any],
    *,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Any,
    approvals: ApprovalService,
    owner_external_id: str,
) -> Orchestrator:
    from zet.config import Settings
    from zet.llm.fake import FakeProvider
    from zet.llm.router import ModelRouter
    from zet.security.killswitch import KillSwitchState
    from zet.security.permissions import PermissionPolicy
    from zet.tools.builtin import build_default_registry

    provider = FakeProvider(name="ollama", scripted=scripted)
    settings = Settings(_env_file=None)
    router = ModelRouter(providers={provider.name: provider}, session=session, settings=settings)
    tool_registry = build_default_registry(notes_dir=tmp_path)
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=PermissionPolicy(auto_approve_write=True, auto_approve_medium=True),
        approval_service=approvals,
        killswitch=KillSwitchState(),
        run_store=RunStore(session_factory=session_factory, owner_external_id=owner_external_id),
        budget_usd=1.0,
    )


def _engine(
    *, repo: MissionRepository, approvals: ApprovalService, orchestrator: Orchestrator
) -> MissionEngine:
    from types import SimpleNamespace

    from zet.domain.enums import RiskLevel

    class _EmptyBundle:
        capabilities: ClassVar[list[str]] = []
        agents: ClassVar[list[str]] = []
        tools: ClassVar[list[str]] = []
        permissions_required: ClassVar[list[PermissionLevel]] = []
        risk_level = RiskLevel.LOW

    class _NoopCapabilityRegistry:
        def compose(self, objective: str, context: dict[str, Any]) -> _EmptyBundle:
            return _EmptyBundle()

    class _NoopContextEngine:
        async def discover(self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]) -> Any:
            return SimpleNamespace(to_dict=lambda: {})

    return MissionEngine(
        repository=repo,
        capability_registry=_NoopCapabilityRegistry(),  # type: ignore[arg-type]
        context_engine=_NoopContextEngine(),
        planner=SimpleNamespace(),  # type: ignore[arg-type]
        orchestrator=orchestrator,
        approvals=approvals,
    )


@pytest.fixture
def repo(session: AsyncSession, owner: Owner) -> MissionRepository:
    return MissionRepository(session, owner_id=owner.id)


@pytest.fixture
def approvals() -> ApprovalService:
    return ApprovalService()


async def _mission_at_executing(repo: MissionRepository, owner: Owner) -> Mission:
    mission = await repo.create(Mission(owner_id=owner.id, objective="reconciliation test"))
    for s in (
        MissionStatus.UNDERSTANDING,
        MissionStatus.DISCOVERING,
        MissionStatus.PLANNING,
        MissionStatus.EXECUTING,
    ):
        await repo.set_status(mission.id, s)
    return await repo.get(mission.id)


class TestAwaitingApprovalRunReused:
    """CRASH bilan mission.status hali EXECUTING (WAITING_APPROVAL'ga
    o'tish COMMIT bo'lmagan), lekin run allaqachon AWAITING_APPROVAL —
    `execute()` YANGI run BOSHLAMASLIGI, mavjudini qayta ishlatishi kerak."""

    async def test_no_duplicate_run_reuses_pending_approval(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        approvals: ApprovalService,
        repo: MissionRepository,
        tmp_path: Any,
    ) -> None:
        from zet.llm.fake import fake_response

        orch = _orchestrator(
            [
                fake_response(text="", tool_uses=(_real_intent_tool_use(),)),
                fake_response(
                    text="",
                    tool_uses=(
                        _real_plan_tool_use(
                            [
                                {
                                    "position": 0,
                                    "description": "HIGH-risk amal",
                                    "tool_name": None,
                                    "permission_required": "execute",
                                    "trust_context": "owner",
                                    "depends_on": [],
                                }
                            ]
                        ),
                    ),
                ),
            ],
            session=session,
            session_factory=session_factory,
            tmp_path=tmp_path,
            approvals=approvals,
            owner_external_id=owner.external_id,
        )

        mission = await _mission_at_executing(repo, owner)

        # "CRASH SIMULATSIYASI": orchestrator.start() to'g'ridan-to'g'ri
        # (MissionEngine.execute() chetlab o'tilib) chaqiriladi — bu
        # AWAITING_APPROVAL run yaratadi va DB'ga yozadi, lekin mission
        # o'zi hali EXECUTING'da qoladi (xuddi crash — mission WAITING_
        # APPROVAL'ga o'tish COMMIT bo'lishidan OLDIN sodir bo'lgandek).
        from zet.domain.command import Command

        pre_run_id = uuid.uuid4()
        await orch.run_store.ensure_placeholder(pre_run_id, Command(text=mission.objective))
        await repo.attach_run(mission.id, pre_run_id, attempt=1)
        record = await orch.start(Command(text=mission.objective), run_id=pre_run_id)
        assert record.status == RunStatus.AWAITING_APPROVAL
        original_approval_id = record.pending_approval_id

        # Endi YANGI (restart'dan keyingi) MissionEngine/orchestrator
        # instansi bilan `execute()` chaqiramiz — go'yoki process qayta
        # ishga tushgan.
        fresh_mission = await repo.get(mission.id)
        assert fresh_mission.run_ids == [pre_run_id]

        engine = _engine(repo=repo, approvals=approvals, orchestrator=orch)
        result_mission, result_record = await engine.execute(fresh_mission)

        # HAQIQIY DALIL: hech qanday YANGI run yaratilmadi.
        after = await repo.get(mission.id)
        assert after.run_ids == [pre_run_id], "Duplicate run yaratildi — reconciliation ishlamadi"
        assert result_mission.status == MissionStatus.WAITING_APPROVAL
        assert result_mission.pending_approval_id == original_approval_id
        assert result_record is not None
        assert result_record.run_id == pre_run_id


class TestExecutingRunSafeResume:
    """Haqiqiy DB'da qo'lda simulyatsiya qilingan crash: `run` qatori
    EXECUTING holatida, 1-qadam DONE (checkpoint), 2-qadam hali yo'q.
    `execute()` YANGI run o'rniga `orchestrator.resume()`ni chaqirishi,
    checkpoint'dagi 1-qadamni QAYTA bajarmasligi, 2-qadamni esa bajarib
    mission'ni yakunlashi kerak."""

    async def test_resumes_via_checkpoint_and_completes(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        approvals: ApprovalService,
        repo: MissionRepository,
        tmp_path: Any,
    ) -> None:
        from zet.core.executor import StepResult
        from zet.core.run_checkpoint import persist_run, persist_step_result
        from zet.domain.command import Command
        from zet.domain.enums import StepStatus
        from zet.domain.tool import ToolResult

        orch = _orchestrator(
            [],  # HECH QANDAY LLM chaqiruvi kerak emas — resume() intent/planner'ni chaqirmaydi.
            session=session,
            session_factory=session_factory,
            tmp_path=tmp_path,
            approvals=approvals,
            owner_external_id=owner.external_id,
        )

        mission = await _mission_at_executing(repo, owner)

        plan = Plan(
            summary="ikki qadamli reja",
            steps=[
                PlanStep(
                    position=0,
                    description="birinchi eslatma",
                    tool_name="note.write",
                    tool_params={"title": "MarkerA", "content": "A"},
                    permission_required=PermissionLevel.WRITE,
                    trust_context=TrustLevel.OWNER,
                    depends_on=[],
                ),
                PlanStep(
                    position=1,
                    description="ikkinchi eslatma",
                    tool_name="note.write",
                    tool_params={"title": "MarkerB", "content": "B"},
                    permission_required=PermissionLevel.WRITE,
                    trust_context=TrustLevel.OWNER,
                    depends_on=[],
                ),
            ],
        )

        run_id = uuid.uuid4()
        from zet.core.orchestrator import RunRecord

        record = RunRecord(
            run_id=run_id,
            command=Command(text=mission.objective),
            plan=plan,
            status=RunStatus.EXECUTING,
        )
        # "run" qatori DB'ga to'g'ridan-to'g'ri yoziladi (crash-simulyatsiya
        # — go'yoki bir marta persist qilingan, keyin process qulagan).
        await persist_run(session_factory, record, owner_external_id=owner.external_id)
        # 0-qadam DONE deb checkpoint qilinadi — HAQIQATDA tool
        # chaqirilmagan (bu — "avvalgi jarayon bajargan, checkpoint
        # yozgan, keyin qulagan" holatini simulyatsiya qiladi). Agar
        # resume() buni noto'g'ri qayta bajarsa — MarkerA fayli PAYDO
        # BO'LMAYDI (chunki biz o'zimiz yaratmadik), lekin bu testda biz
        # buni MUSBAT dalil sifatida ISHLATMAYMIZ — asosiy dalil pastda.
        step0_result = StepResult(
            plan.steps[0],
            status=StepStatus.DONE,
            tool_result=ToolResult(
                tool_name="note.write",
                success=True,
                output="checkpoint-dan tiklangan",
                trust_level=TrustLevel.SYSTEM,
            ),
            output="checkpoint-dan tiklangan",
        )
        await persist_step_result(session_factory, run_id, 0, step0_result)
        await session.commit()

        await repo.attach_run(mission.id, run_id, attempt=1)
        fresh_mission = await repo.get(mission.id)
        assert fresh_mission.run_ids == [run_id]

        engine = _engine(repo=repo, approvals=approvals, orchestrator=orch)
        _, result_record = await engine.execute(fresh_mission)

        # HAQIQIY DALIL #1: hech qanday YANGI run yaratilmadi — bir xil
        # run_id resume qilindi.
        after = await repo.get(mission.id)
        assert after.run_ids == [run_id]

        # HAQIQIY DALIL #2: run DONE bilan yakunlandi (ikkinchi qadam
        # HAQIQATDA bajarildi — note.write REAL tool orqali).
        assert result_record is not None
        assert result_record.status == RunStatus.DONE

        # HAQIQIY DALIL #3: MarkerA (checkpoint qilingan, 0-qadam)
        # HECH QACHON yaratilmadi (chunki tool chaqirilmadi — checkpoint
        # QAYTA bajarilmaganining to'g'ridan-to'g'ri isboti), MarkerB esa
        # (haqiqatda bajarilgan 1-qadam) DISKDA MAVJUD.
        assert not (tmp_path / "MarkerA.md").exists()
        assert (tmp_path / "MarkerB.md").exists()


class TestNonIdempotentUncertainRouting:
    """Keyingi bajarilmagan qadam yon-samarali (idempotent bo'lmagan/
    noma'lum) bo'lsa — avtomatik resume QILINMAYDI, mission RECOVERING'ga
    o'tadi (RecoveryEngine tashxis qo'yishi uchun)."""

    async def test_unresolved_tool_step_routes_to_recovering(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        approvals: ApprovalService,
        repo: MissionRepository,
        tmp_path: Any,
    ) -> None:
        from zet.core.run_checkpoint import persist_run
        from zet.domain.command import Command

        orch = _orchestrator(
            [],
            session=session,
            session_factory=session_factory,
            tmp_path=tmp_path,
            approvals=approvals,
            owner_external_id=owner.external_id,
        )

        mission = await _mission_at_executing(repo, owner)

        # `tool_name=None` (faqat agent fikrlashi, hech qanday tool) —
        # `_tool_is_idempotent(None)` HAR DOIM `False` qaytaradi (xavfsiz
        # tomonga xato — spec §6: "agar noaniq bo'lsa, ko'r-ko'rona
        # takrorlama").
        plan = Plan(
            summary="agent-only qadam",
            steps=[
                PlanStep(
                    position=0,
                    description="agentning o'zi fikrlaydi",
                    tool_name=None,
                    permission_required=PermissionLevel.WRITE,
                    trust_context=TrustLevel.OWNER,
                    depends_on=[],
                ),
            ],
        )
        run_id = uuid.uuid4()
        from zet.core.orchestrator import RunRecord

        record = RunRecord(
            run_id=run_id,
            command=Command(text=mission.objective),
            plan=plan,
            status=RunStatus.EXECUTING,
        )
        await persist_run(session_factory, record, owner_external_id=owner.external_id)
        await session.commit()

        await repo.attach_run(mission.id, run_id, attempt=1)
        fresh_mission = await repo.get(mission.id)

        engine = _engine(repo=repo, approvals=approvals, orchestrator=orch)
        result_mission, result_record = await engine.execute(fresh_mission)

        # HAQIQIY DALIL: `orchestrator.resume()`/`start()` HECH QAYSI
        # bir chaqirilmadi (LLM script BO'SH edi — chaqirilganda xato
        # berardi), mission esa RECOVERING'ga o'tdi, aniq sabab bilan.
        assert result_record is None
        assert result_mission.status == MissionStatus.RECOVERING
        assert result_mission.error is not None
        assert "idempotent" in result_mission.error.lower() or "noaniq" in result_mission.error.lower()

        after = await repo.get(mission.id)
        assert after.run_ids == [run_id], "Yangi run yaratilmasligi kerak edi"


class TestRecoveryRetryDoesNotReuseOldRun:
    """REGRESSIYA QULF: `recover()` `retry_count`ni oshirib YANGI urinish
    uchun EXECUTING'ga qaytarganda, `mission.run_ids`dagi OXIRGI (ESKI,
    terminal) run QAYTA ishlatilmasligi kerak — bu, agar tuzatilmasa,
    recovery patch'idan keyingi TUZATILGAN reja hech qachon
    bajarilmasligiga olib kelardi (aynan shu bug ishlab chiqish paytida
    `test_mission_engine.py::TestA3ApprovalBypassPrevention` orqali
    topildi va shu yerda alohida qulflanadi)."""

    async def test_new_attempt_after_recovery_starts_fresh_run(
        self,
        session: AsyncSession,
        owner: Owner,
        session_factory: async_sessionmaker[AsyncSession],
        approvals: ApprovalService,
        repo: MissionRepository,
        tmp_path: Any,
    ) -> None:
        mission = await _mission_at_executing(repo, owner)

        orch = _orchestrator(
            [],
            session=session,
            session_factory=session_factory,
            tmp_path=tmp_path,
            approvals=approvals,
            owner_external_id=owner.external_id,
        )

        # 1-urinishning ESKI, TERMINAL (FAILED) run'ini qo'lda yozamiz.
        from zet.core.orchestrator import RunRecord
        from zet.core.run_checkpoint import persist_run
        from zet.domain.command import Command

        old_run_id = uuid.uuid4()
        old_record = RunRecord(
            run_id=old_run_id,
            command=Command(text=mission.objective),
            plan=None,
            status=RunStatus.FAILED,
            error="1-urinish muvaffaqiyatsiz",
        )
        await persist_run(session_factory, old_record, owner_external_id=owner.external_id)
        await session.commit()
        await repo.attach_run(mission.id, old_run_id, attempt=1)

        # `recover()` allaqachon chaqirilgandek: retry_count=1 (keyingi
        # urinish = 2), mission EXECUTING'ga qaytgan.
        await repo.update(mission.id, retry_count=1)
        fresh_mission = await repo.get(mission.id)
        assert fresh_mission.run_ids == [old_run_id]
        assert fresh_mission.retry_count == 1

        engine = _engine(repo=repo, approvals=approvals, orchestrator=orch)

        # Reconciliation'ning o'zini to'g'ridan-to'g'ri sinaymiz (LLM
        # kerak emas — faqat qaror mantiqiy to'g'ri ekanini isbotlaydi).
        reconciliation = await engine._reconcile_run(fresh_mission)

        assert reconciliation.outcome == "UNKNOWN", (
            "ESKI (1-urinish) run QAYTA ishlatilmoqchi bo'ldi — "
            "recovery-retry uchun bu XATO (yangi urinish rejasi "
            "hech qachon bajarilmay qolardi)"
        )
