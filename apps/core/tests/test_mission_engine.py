"""MissionEngine testlari (Bo'lim 2, §2.2).

NEGA. MissionEngine ilgari yo'q edi. Bu testlar strategik qatlamning
xatti-harakatini qulflaydi: happy path, HIGH risk approval,
verification failure → recovery, MAX_RETRIES cheklovi, cancel,
CapabilityRegistry va ContextDiscoveryEngine bilan integratsiya,
kill switch fail-closed, deadline auto-cancel, va invalid transition
transaction chegarasi.

Soxta bog'liqliklar (SimpleNamespace/dataklass) — real Orchestrator
ishlashi allaqachon `test_executor.py` va `test_planner.py` da qulflangan.
MissionEngine testlari faqat kompozitsiya oqimini tekshiradi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.core.mission import (
    IllegalMissionTransitionError,
    Mission,
    MissionEngine,
    MissionTask,
)
from zet.core.mission_repository import MissionRepository
from zet.db.base import utcnow
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
from zet.security.killswitch import KillSwitchEngagedError

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
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def compose(self, objective: str, context: dict[str, Any]) -> FakeBundle:
        self.calls.append((objective, context))
        return self.bundle


class FakeRelevantContext:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class FakeContextEngine:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}
        self.calls = 0

    async def discover(
        self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
    ) -> FakeRelevantContext:
        self.calls += 1
        return FakeRelevantContext(self.data)


@dataclass
class FakeRunRecord:
    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None


class FakeOrchestrator:
    """Har chaqiruvda `_runs` navbatidan bir RunRecord qaytaradi."""

    def __init__(self, session: AsyncSession, owner: Owner) -> None:
        self._session = session
        self._owner = owner
        self._queued: list[FakeRunRecord] = []
        self.start_calls: list[Any] = []
        self.raise_kill_switch = False

    def queue(self, *records: FakeRunRecord) -> None:
        self._queued.extend(records)

    async def start(self, command: Any, *, dry_run: bool = False) -> FakeRunRecord:
        self.start_calls.append(command)
        if self.raise_kill_switch:
            raise KillSwitchEngagedError("stop")
        if not self._queued:
            raise AssertionError("FakeOrchestrator navbati bo'sh")
        record = self._queued.pop(0)
        # Real Run yozuvi — MissionRunLink FK talab qiladi
        run = Run(
            id=record.run_id,
            owner_id=self._owner.id,
            trigger=RunTrigger.MANUAL,
            command_text=str(command.text if hasattr(command, "text") else "x"),
            trace_id="trace",
        )
        self._session.add(run)
        await self._session.flush()
        return record


class FakeMemoryStore:
    def __init__(self) -> None:
        self.written: list[tuple[uuid.UUID, str, str]] = []

    async def remember(
        self,
        owner_id: uuid.UUID,
        content: str,
        *,
        layer: str,
        source: str,
    ) -> None:
        self.written.append((owner_id, content, layer))


class FakeRecovery:
    def __init__(self) -> None:
        self.calls = 0

    async def diagnose_and_patch(self, mission: Mission, last_failure: str) -> Mission:
        self.calls += 1
        return mission


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
    bundle: FakeBundle | None = None,
    context: dict[str, Any] | None = None,
    memory: FakeMemoryStore | None = None,
    recovery: FakeRecovery | None = None,
    risk_classifier: Any = None,
    max_retries: int = 2,
) -> tuple[MissionEngine, FakeOrchestrator, FakeCapabilityRegistry, FakeContextEngine]:
    b = bundle or FakeBundle(tools=["note.write"])
    reg = FakeCapabilityRegistry(b)
    ctx = FakeContextEngine(context or {})
    orch = FakeOrchestrator(session, owner)
    engine = MissionEngine(
        repository=repo,
        capability_registry=reg,
        context_engine=ctx,
        planner=SimpleNamespace(),  # plan() ni chaqirmaymiz — bundle to'g'ridan-to'g'ri task'ga aylanadi
        orchestrator=orch,  # type: ignore[arg-type]
        approvals=approvals,
        recovery=recovery,
        memory_store=memory,
        risk_classifier=risk_classifier,
        max_retries=max_retries,
    )
    return engine, orch, reg, ctx


# ── Testlar ──────────────────────────────────────────────────────


class TestHappyPath:
    async def test_low_risk_completes_end_to_end(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        memory = FakeMemoryStore()
        engine, orch, _, _ = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            memory=memory,
        )
        run_id = uuid.uuid4()
        orch.queue(FakeRunRecord(run_id=run_id, status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert run_id in m.run_ids

    async def test_completed_writes_memory_updates(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        memory = FakeMemoryStore()
        engine, orch, _, _ = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            memory=memory,
        )
        run_id = uuid.uuid4()
        orch.queue(FakeRunRecord(run_id=run_id, status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await repo.update(m.id, memory_updates=["fikr: ega loyihani xohladi"])
        await engine.run_to_completion(m.id)

        assert len(memory.written) == 1
        assert "fikr:" in memory.written[0][1]


class TestApprovalGate:
    async def test_high_risk_forces_waiting_approval(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        bundle = FakeBundle(tools=["deploy"], risk_level=RiskLevel.HIGH)
        engine, orch, _, _ = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, bundle=bundle
        )

        m = await engine.submit(owner_id=owner.id, objective="deploy")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.WAITING_APPROVAL
        assert m.pending_approval_id is not None
        assert orch.start_calls == []  # execute() chaqirilmagan

    async def test_direct_execute_before_approve_illegal(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        bundle = FakeBundle(tools=["deploy"], risk_level=RiskLevel.HIGH)
        engine, _, _, _ = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, bundle=bundle
        )
        m = await engine.submit(owner_id=owner.id, objective="deploy")
        m = await engine.run_to_completion(m.id)
        assert m.status is MissionStatus.WAITING_APPROVAL

        with pytest.raises(IllegalMissionTransitionError):
            # WAITING_APPROVAL → VERIFYING taqiqlangan
            await engine.verify(m, FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True))  # type: ignore[arg-type]

    async def test_approve_transitions_to_executing(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        bundle = FakeBundle(tools=["deploy"], risk_level=RiskLevel.HIGH)
        engine, _orch, _, _ = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, bundle=bundle
        )
        m = await engine.submit(owner_id=owner.id, objective="deploy")
        m = await engine.run_to_completion(m.id)
        approval_id = m.pending_approval_id
        assert approval_id is not None

        m = await engine.approve(m.id, approval_id)
        assert m.status is MissionStatus.EXECUTING


class TestVerificationAndRecovery:
    async def test_verify_failure_enters_recovering(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        recovery = FakeRecovery()
        engine, orch, _, _ = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            recovery=recovery,
        )
        # 1-urinish: yiqiladi. 2-urinish: yiqiladi. 3-urinish: max_retries=2 → FAILED
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e1"
            ),
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e2"
            ),
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e3"
            ),
        )
        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.FAILED
        assert "max retries" in (m.error or "")
        # 3 ta run biriktirildi (asosiy + 2 recovery)
        runs = await repo.list_runs(m.id)
        assert len(runs) == 3
        assert recovery.calls == 2  # max_retries=2 → recover 2 marta chaqiriladi

    async def test_recovery_recovers_and_completes(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, orch, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e1"
            ),
            FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True),
        )
        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert m.retry_count == 1


class TestCancel:
    async def test_cancel_from_planning(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, _, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        m = await engine.submit(owner_id=owner.id, objective="ish")
        # Manually advance to PLANNING
        m = await repo.set_status(m.id, MissionStatus.UNDERSTANDING)
        m = await repo.set_status(m.id, MissionStatus.DISCOVERING)
        m = await repo.set_status(m.id, MissionStatus.PLANNING)

        m = await engine.cancel(m.id, "ega bekor qildi")
        assert m.status is MissionStatus.CANCELLED
        assert m.error == "ega bekor qildi"

    async def test_cancel_from_completed_forbidden(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, orch, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))
        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)
        assert m.status is MissionStatus.COMPLETED

        with pytest.raises(IllegalMissionTransitionError):
            await engine.cancel(m.id, "kech")


class TestCapabilityAndContext:
    async def test_capability_registry_output_used(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        bundle = FakeBundle(
            capabilities=["website.build"],
            agents=["dev"],
            tools=["website.build", "instagram.post"],
        )
        engine, orch, reg, _ = _engine(
            repo=repo, approvals=approvals, session=session, owner=owner, bundle=bundle
        )
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="sayt qur")
        m = await engine.run_to_completion(m.id)

        assert reg.calls  # compose chaqirilgan
        assert m.tools == ["website.build", "instagram.post"]
        assert m.capabilities == ["website.build"]
        # Har tool bitta MissionTask'ga aylanadi
        titles = [t["title"] if isinstance(t, dict) else t.title for t in m.tasks]
        assert titles == ["website.build", "instagram.post"]

    async def test_context_engine_output_written(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, orch, _, _ctx_engine = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            context={"project_id": "abc", "obsidian_notes": ["note1"]},
        )
        orch.queue(FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True))

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.context == {"project_id": "abc", "obsidian_notes": ["note1"]}
        # JSON round-trip qulflandi (fresh repo o'qish orqali)
        fresh = await repo.get(m.id)
        assert fresh.context == {"project_id": "abc", "obsidian_notes": ["note1"]}


class TestGuards:
    async def test_kill_switch_causes_failed(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, orch, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        orch.raise_kill_switch = True

        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.FAILED
        assert "kill switch" in (m.error or "")
        runs = await repo.list_runs(m.id)
        assert runs == []

    async def test_deadline_expired_auto_cancel(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, orch, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        past = utcnow() - timedelta(hours=1)

        m = await engine.submit(owner_id=owner.id, objective="ish", deadline=past)
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.CANCELLED
        assert "deadline" in (m.error or "")
        assert orch.start_calls == []


class TestStateMachineIntegrity:
    async def test_invalid_transition_leaves_status_unchanged(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        engine, _, _, _ = _engine(repo=repo, approvals=approvals, session=session, owner=owner)
        m = await engine.submit(owner_id=owner.id, objective="ish")
        # Manually advance to PLANNING
        m = await repo.set_status(m.id, MissionStatus.UNDERSTANDING)
        m = await repo.set_status(m.id, MissionStatus.DISCOVERING)
        m = await repo.set_status(m.id, MissionStatus.PLANNING)

        # verify() PLANNING dan chaqirilsa VERIFYING → COMPLETED taqiqlangan
        # (PLANNING → COMPLETED emas; oldindan _transition COMPLETED ni ruxsat etmaydi)
        with pytest.raises(IllegalMissionTransitionError):
            await engine.verify(
                m,
                FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True),  # type: ignore[arg-type]
            )
        fresh = await repo.get(m.id)
        assert fresh.status is MissionStatus.PLANNING


# ── MissionTask smoke ─────────────────────────────────────────────


class TestMissionTaskShape:
    def test_task_serializes(self) -> None:
        t = MissionTask(position=0, title="build", tool="website.build")
        dumped = t.model_dump(mode="json")
        assert dumped["position"] == 0
        assert dumped["tool"] == "website.build"


# ── HIGH #3 audit fix (KONSOLIDATSIYA v2) ─────────────────────────
#
# Ilgari `deps.py` HAR DOIM `recovery=None` berardi — Task-Graph
# mission'lar HECH QANDAY LLM diagnos olmasdi, faqat "dumb retry".
# Bu testlar `MissionRecoveryAdapter`ni (D4 bilan bir xil T1_FREE tier
# naqsh) HAQIQIY (soxta bo'lmagan) LLM chaqiruvi bilan tekshiradi.


class _FakeMissionLLM:
    """`api/deps.py::_VerifierJudgeProvider` bilan bir xil shaklga ega
    soxta LLM — `.complete(messages=, system=, max_tokens=)`."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, *, messages, system=None, max_tokens=300, **_):  # type: ignore[no-untyped-def]
        self.calls.append(
            {"messages": list(messages), "system": system, "max_tokens": max_tokens}
        )
        if not self._responses:
            return SimpleNamespace(text="")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)


class TestHigh3MissionRecoveryWiring:
    """HIGH #3 (KONSOLIDATSIYA v2) — Task-Graph mission'lar endi HAQIQIY
    LLM diagnos oladi, `deps.py`ning `recovery=None` gap'i yopilgan."""

    async def test_mission_recovery_calls_real_llm_and_patches_constraints(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """Sun'iy xato simulyatsiyasi: 1-run FAIL (ConnectionError), real
        `MissionRecoveryAdapter` LLM'dan diagnos so'raydi, 2-run OK bilan
        mission COMPLETED bo'ladi. Isbot: LLM chaqiruvi xato matnini
        ko'rgan, natija mission.constraints'ga YOZILGAN (DB'da saqlangan)."""
        from zet.core.mission import MissionRecoveryAdapter

        llm = _FakeMissionLLM(
            responses=["Tarmoq xatosi — qayta urinishda timeout oshirilsin."]
        )
        recovery = MissionRecoveryAdapter(llm_provider=llm, repository=repo)

        engine, orch, _, _ = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            recovery=recovery,  # type: ignore[arg-type]
        )
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(),
                status=RunStatus.DONE,
                verified_ok=False,
                error="ConnectionError: timeout",
            ),
            FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True),
        )
        m = await engine.submit(owner_id=owner.id, objective="Tashqi API'dan ma'lumot olish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED

        # ENG MUHIM DALIL #1: LLM HAQIQATAN chaqirilgan — "dumb retry" EMAS.
        assert len(llm.calls) == 1, (
            "HIGH #3 BUZILDI: Task-Graph mission recovery LLM'ni chaqirmadi"
        )
        sent_user_message = llm.calls[0]["messages"][0].content
        assert "ConnectionError: timeout" in sent_user_message
        assert "Tashqi API'dan ma'lumot olish" in sent_user_message

        # ENG MUHIM DALIL #2: diagnos natijasi DB'ga yozilgan (patch
        # haqiqatan qo'llanilgan, faqat log emas).
        final_mission = await repo.get(m.id)
        assert any(
            "Tarmoq xatosi" in c for c in final_mission.constraints
        ), f"Recovery hint constraints'ga yozilmagan: {final_mission.constraints}"

    async def test_llm_error_is_fail_open_mission_still_retries(
        self, repo: MissionRepository, approvals: ApprovalService, session, owner
    ) -> None:
        """LLM xato bersa — mission BARIBIR qayta urinadi (fail-open),
        faqat diagnos matni bo'lmaydi. `recover()`ning o'z fail-open
        falsafasiga mos (`except Exception` mission'ni yiqitmaydi)."""
        from zet.core.mission import MissionRecoveryAdapter

        llm = _FakeMissionLLM(responses=[RuntimeError("LLM provayder ishlamadi")])
        recovery = MissionRecoveryAdapter(llm_provider=llm, repository=repo)

        engine, orch, _, _ = _engine(
            repo=repo,
            approvals=approvals,
            session=session,
            owner=owner,
            recovery=recovery,  # type: ignore[arg-type]
        )
        orch.queue(
            FakeRunRecord(
                run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=False, error="e1"
            ),
            FakeRunRecord(run_id=uuid.uuid4(), status=RunStatus.DONE, verified_ok=True),
        )
        m = await engine.submit(owner_id=owner.id, objective="ish")
        m = await engine.run_to_completion(m.id)

        assert m.status is MissionStatus.COMPLETED
        assert len(llm.calls) == 1
        final_mission = await repo.get(m.id)
        assert final_mission.constraints == []  # patch qo'llanilmagan, lekin yiqilmagan ham


class TestMissionRecoveryAdapterUnit:
    """`MissionRecoveryAdapter.diagnose_and_patch()`ning o'zini,
    MissionEngine kompozitsiyasisiz, to'g'ridan-to'g'ri tekshiradi."""

    async def test_empty_llm_response_returns_mission_unchanged(
        self, repo: MissionRepository, owner
    ) -> None:
        from zet.core.mission import MissionRecoveryAdapter

        llm = _FakeMissionLLM(responses=[""])
        adapter = MissionRecoveryAdapter(llm_provider=llm, repository=repo)

        mission = await repo.create(Mission(owner_id=owner.id, objective="test"))
        result = await adapter.diagnose_and_patch(mission, "xato matni")

        assert result.constraints == []
        assert len(llm.calls) == 1


# ── A3 SHART (KONSOLIDATSIYA v2, tungi reja Bo'lim A) ────────────────
#
# "Recovery harakati HIGH-risk bo'lsa, Approval Engine'dan o'tishi
# shart — bypass yo'q." D1 shu talabni RecoveryEngine (PlanStep/Run
# darajasi) uchun qulfladi; bu yerda AYNAN SHU talab Task-Graph
# mission darajasida — REAL Orchestrator/Executor/PermissionPolicy/
# ApprovalService bilan (FakeOrchestrator stub EMAS) — qulflanadi.


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


def _real_orchestrator(scripted: list[Any], *, session, session_factory, tmp_path, approvals, owner_external_id):
    from zet.config import Settings
    from zet.core.orchestrator import Orchestrator, RunStore
    from zet.llm.fake import FakeProvider
    from zet.llm.router import ModelRouter
    from zet.security.killswitch import KillSwitchState
    from zet.security.permissions import PermissionPolicy
    from zet.tools.builtin import build_default_registry

    provider = FakeProvider(name="ollama", scripted=scripted)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(providers={provider.name: provider}, session=session, settings=settings)
    tool_registry = build_default_registry(notes_dir=tmp_path)
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=PermissionPolicy(),
        approval_service=approvals,
        killswitch=KillSwitchState(),
        run_store=RunStore(session_factory=session_factory, owner_external_id=owner_external_id),
        budget_usd=1.0,
    )


class TestA3ApprovalBypassPrevention:
    """A3 SHART: `MissionRecoveryAdapter` orqali qayta urinilgan mission
    ham, xuddi birinchi urinish kabi, HIGH-risk qadamda Approval
    Engine'ni chetlab o'ta olmaydi.

    `MissionRecoveryAdapter` faqat `mission.constraints`ga matn
    yozadi (hech qanday tool chaqirmaydi, hech qanday approval
    bermaydi) — shuning uchun arxitektura jihatidan bypass STRUKTURAVIY
    RAVISHDA imkonsiz. Bu test buni REAL Orchestrator/Executor/
    PermissionPolicy/ApprovalService bilan (FakeOrchestrator emas)
    isbotlaydi: 1-urinish HAQIQIY xato bilan yiqiladi (note.read —
    mavjud bo'lmagan eslatma, D4'dagi bilan bir xil texnika),
    real MissionRecoveryAdapter LLM'dan diagnos oladi va
    constraints'ga yozadi, 2-urinishda reja HIGH-risk (EXECUTE)
    qadamga ega — va HECH QACHON avtomatik bajarilmaydi, mission
    WAITING_APPROVAL'da to'xtaydi."""

    async def test_recovery_retry_with_high_risk_step_still_requires_approval(
        self,
        repo: MissionRepository,
        approvals: ApprovalService,
        session: AsyncSession,
        owner: Owner,
        session_factory,
        tmp_path,
    ) -> None:
        from zet.core.mission import MissionRecoveryAdapter
        from zet.llm.fake import fake_response

        # 1-urinish: note.read mavjud bo'lmagan eslatmani so'raydi —
        # HAQIQIY ToolError, Run FAILED bo'ladi (D4'dagi live-diagnos
        # texnikasi bilan bir xil, soxta emas).
        attempt1 = [
            fake_response(text="", tool_uses=(_real_intent_tool_use(requires_tools=["note.read"]),)),
            fake_response(
                text="",
                tool_uses=(
                    _real_plan_tool_use(
                        [
                            {
                                "position": 0,
                                "description": "Eslatmani o'qish",
                                "tool_name": "note.read",
                                "tool_params": {"title": "MissingMissionNote"},
                                "permission_required": "read",
                                "trust_context": "owner",
                                "depends_on": [],
                            }
                        ]
                    ),
                ),
            ),
        ]
        # 2-urinish (recovery'dan keyin): reja HIGH-risk EXECUTE
        # qadamga ega (tool_name=None — `_approval_script()` bilan bir
        # xil, `test_pipeline_integration.py::TestApprovalRoundTrip`da
        # qulflangan naqsh) — bu qadam HECH QACHON avtomatik
        # bajarilmasligi kerak.
        attempt2 = [
            fake_response(text="", tool_uses=(_real_intent_tool_use(),)),
            fake_response(
                text="",
                tool_uses=(
                    _real_plan_tool_use(
                        [
                            {
                                "position": 0,
                                "description": "HIGH risk amal — recovery'dan keyin ham tasdiq talab qiladi",
                                "tool_name": None,
                                "permission_required": "execute",
                                "trust_context": "owner",
                                "depends_on": [],
                            }
                        ]
                    ),
                ),
            ),
        ]

        orch = _real_orchestrator(
            [*attempt1, *attempt2],
            session=session,
            session_factory=session_factory,
            tmp_path=tmp_path,
            approvals=approvals,
            owner_external_id=owner.external_id,
        )

        llm = _FakeMissionLLM(
            responses=["note.read xato — eslatma nomini tekshirib qayta urin."]
        )
        recovery = MissionRecoveryAdapter(llm_provider=llm, repository=repo)

        engine = MissionEngine(
            repository=repo,
            capability_registry=FakeCapabilityRegistry(FakeBundle(tools=["note.read"])),
            context_engine=FakeContextEngine({}),
            planner=SimpleNamespace(),
            orchestrator=orch,
            approvals=approvals,
            recovery=recovery,  # type: ignore[arg-type]
        )

        m = await engine.submit(owner_id=owner.id, objective="Eslatmani tekshirib xulosa chiqarish")
        m = await engine.run_to_completion(m.id)

        # ENG MUHIM DALIL #1: recovery HAQIQATAN ishga tushdi (1-urinish
        # haqiqatan yiqilgani uchun) — LLM chaqirilgan, diagnos
        # constraints'ga yozilgan.
        assert len(llm.calls) == 1, "Recovery LLM chaqirilmadi — 1-urinish yiqilmagan bo'lishi mumkin"
        final_mission = await repo.get(m.id)
        assert any("note.read xato" in c for c in final_mission.constraints)

        # ENG MUHIM DALIL #2 (SHART — bypass yo'q): 2-urinish HIGH-risk
        # qadamga yetganda mission WAITING_APPROVAL'da TO'XTAYDI —
        # recovery hech qanday holatda uni chetlab o'tmaydi, avtomatik
        # ravishda COMPLETED/EXECUTING'ga o'tmaydi.
        assert m.status is MissionStatus.WAITING_APPROVAL, (
            f"A3 SHART BUZILDI: recovery'dan keyingi HIGH-risk qadam Approval "
            f"Engine'ni chetlab o'tdi (mission.status={m.status})"
        )
        assert m.pending_approval_id is not None
        pending = approvals.get(m.pending_approval_id)
        assert pending.status.value == "pending"

        # ENG MUHIM DALIL #3: real Orchestrator ikki marta chaqirilgan
        # (1-urinish + recovery'dan keyingi 2-urinish) — recovery
        # genuinely retried orqali qayta ishga tushirilgan, birinchi
        # urinishning o'zi to'xtab qolmagan.
        assert len(orch._router._providers["ollama"].calls) == 4

