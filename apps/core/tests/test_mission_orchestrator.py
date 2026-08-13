"""MissionOrchestrator testlari — 6 ta yangi qatlam integratsiyasi.

MissionOrchestrator MissionEngine ustida turadi va u tomonidan bir necha
qo'shimchani beradi (kill-switch preflight, capability preflight, notifier).
Bu testlar:

    - happy path (COMPLETED, notifier chaqiriladi)
    - HIGH_RISK → WAITING_APPROVAL (approval gate)
    - verify failure → RECOVERING → COMPLETED
    - verify failure MAX_RETRIES → FAILED
    - kill switch yoqilgan → CANCELLED (execute chaqirilmaydi)
    - capability topilmadi → FAILED
    - persistensiya: POST /missions → GET /missions/{id}
    - ro'yxat: GET /missions sahifalash

MissionEngine testlaridan ajralib turadi: bu yerda MissionOrchestrator
ustida ishlaymiz — u submit→run_to_completion oqimini boshqaradi va
kill-switch/notifier hooklarini beradi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.app import create_app
from zet.api.deps import get_mission_orchestrator
from zet.core.mission import Mission, MissionEngine
from zet.core.mission_orchestrator import (
    CapabilityBundle,
    ContextEngineAdapter,
    MissionOrchestrator,
)
from zet.core.mission_repository import MissionRepository
from zet.db.models import Owner
from zet.db.models.run import Run
from zet.domain.command import Command
from zet.domain.enums import (
    MissionStatus,
    PermissionLevel,
    RiskLevel,
    RunStatus,
    RunTrigger,
    TrustLevel,
)
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import Notification, Notifier, StubNotifier

# ── Soxta bog'liqliklar ──────────────────────────────────────────


class FakeCapabilityRegistry:
    """`.compose(objective, context) -> CapabilityBundle` beruvchi soxta."""

    def __init__(self, bundle: CapabilityBundle | None = None) -> None:
        self.bundle = bundle if bundle is not None else CapabilityBundle(tools=["note.write"])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def compose(self, objective: str, context: dict[str, Any]) -> CapabilityBundle:
        self.calls.append((objective, context))
        return self.bundle


class FakeContextEngine:
    """MissionEngine `ContextDiscoveryEngineLike` protokoliga mos."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}

    async def discover(self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]):  # type: ignore[no-untyped-def]
        _ = (objective, owner_id, constraints)
        data = dict(self.data)

        class _View:
            def to_dict(self) -> dict[str, Any]:
                return data

        return _View()


@dataclass
class FakeRunRecord:
    run_id: uuid.UUID
    status: RunStatus = RunStatus.DONE
    verified_ok: bool | None = True
    pending_approval_id: uuid.UUID | None = None
    error: str | None = None


class FakeInnerOrchestrator:
    """`MissionEngine`'ga uzatiladigan soxta `Orchestrator.start()`.

    Har chaqiruvda `_queued` navbatidan bir RunRecord qaytaradi. Real
    orchestrator `start()` — kill-switch tekshiruvi, intent, plan, execute
    va verify — bu yerda hech qanday LLM ishtirokisiz o'rnini bosadi.
    """

    def __init__(self, session: AsyncSession, owner: Owner) -> None:
        self._session = session
        self._owner = owner
        self._queued: list[FakeRunRecord] = []
        self.start_calls: list[Any] = []

    def queue(self, *records: FakeRunRecord) -> None:
        self._queued.extend(records)

    async def start(self, command: Any, *, dry_run: bool = False) -> FakeRunRecord:
        _ = dry_run
        self.start_calls.append(command)
        if not self._queued:
            raise AssertionError("FakeInnerOrchestrator navbati bo'sh")
        record = self._queued.pop(0)
        # Real Run yozuvi — MissionRunLink FK talab qiladi
        run = Run(
            id=record.run_id,
            owner_id=self._owner.id,
            trigger=RunTrigger.MANUAL,
            command_text=str(getattr(command, "text", "x")),
            trace_id="trace",
        )
        self._session.add(run)
        await self._session.flush()
        return record


# ── Yordamchi fabrika ────────────────────────────────────────────


def _build(
    session: AsyncSession,
    owner: Owner,
    *,
    bundle: CapabilityBundle | None = None,
    context_data: dict[str, Any] | None = None,
    max_retries: int = 2,
    killswitch: KillSwitchState | None = None,
    notifier: Notifier | None = None,
) -> tuple[MissionOrchestrator, FakeInnerOrchestrator, FakeCapabilityRegistry, StubNotifier]:
    """MissionOrchestrator + navbat qo'yiladigan FakeInnerOrchestrator."""
    repo = MissionRepository(session, owner_id=owner.id)
    reg = FakeCapabilityRegistry(bundle)
    ctx = FakeContextEngine(context_data)
    inner = FakeInnerOrchestrator(session, owner)
    approvals = ApprovalService()

    engine = MissionEngine(
        repository=repo,
        capability_registry=reg,
        context_engine=ctx,
        planner=object(),  # ishlatilmaydi (bundle -> tasks)
        orchestrator=inner,  # type: ignore[arg-type]
        approvals=approvals,
        recovery=None,
        memory_store=None,
        max_retries=max_retries,
    )
    stub = notifier or StubNotifier()
    orch = MissionOrchestrator(
        capability_registry=reg,
        context_engine=ctx,
        mission_engine=engine,
        planner=object(),
        executor=None,
        verifier=None,
        recovery_engine=None,
        approval_service=approvals,
        permission_policy=PermissionPolicy(),
        notifier=stub,
        killswitch=killswitch,
    )
    return orch, inner, reg, stub  # type: ignore[return-value]


def _command(text: str = "eslatma yoz") -> Command:
    return Command(text=text, trust_level=TrustLevel.OWNER, channel="test")


# ── 1. Happy path — barcha fazalar to'liq bajariladi ─────────────


class TestHappyPath:
    async def test_simple_intent_runs_through_all_phases_to_completed(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        orch, inner, reg, notifier = _build(session, owner)
        inner.queue(FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True))

        mission = await orch.run(_command("eslatma yoz"), owner_id=owner.id)

        assert mission.status is MissionStatus.COMPLETED
        assert reg.calls, "capability_registry.compose() chaqirilishi kerak edi"
        assert inner.start_calls, "inner orchestrator.start() chaqirilishi kerak edi"
        assert mission.tools == ["note.write"]
        # Notifier COMPLETED bo'yicha task_result yubordi
        assert any("bajarildi" in n.text.lower() for n in notifier.sent)


# ── 2. HIGH_RISK → WAITING_APPROVAL ──────────────────────────────


class TestHighRiskApproval:
    async def test_high_risk_stops_at_waiting_approval(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        bundle = CapabilityBundle(
            tools=["deploy"],
            permissions_required=[PermissionLevel.EXECUTE],
            risk_level=RiskLevel.HIGH,
        )
        orch, inner, _reg, notifier = _build(session, owner, bundle=bundle)

        mission = await orch.run(_command("deploy qil"), owner_id=owner.id)

        assert mission.status is MissionStatus.WAITING_APPROVAL
        assert mission.pending_approval_id is not None
        assert inner.start_calls == []  # bajarish CHAQIRILMAGAN
        # WAITING_APPROVAL — terminal emas, notifier task_result yubormaydi
        task_results = [n for n in notifier.sent if n.type.value == "task_result"]
        assert task_results == []


# ── 3. Verify failure → RECOVERING → COMPLETED ────────────────────


class TestVerifyRecoverThenSuccess:
    async def test_recovery_recovers_and_completes(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        orch, inner, _reg, notifier = _build(session, owner)
        inner.queue(
            FakeRunRecord(run_id=uuid.uuid4(), verified_ok=False, error="birinchi urinish"),
            FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True),
        )

        mission = await orch.run(_command(), owner_id=owner.id)

        assert mission.status is MissionStatus.COMPLETED
        assert mission.retry_count == 1
        assert len(inner.start_calls) == 2
        assert any("bajarildi" in n.text.lower() for n in notifier.sent)


# ── 4. Verify failure twice → FAILED (max_retries oshdi) ─────────


class TestMaxRetriesExceeded:
    async def test_failed_verification_twice_leads_to_failed(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        # max_retries=1 → 1-fail: retry_count=1, 1>1 emas → EXECUTING
        # 2-fail: retry_count=2, 2>1 → FAILED
        orch, inner, _reg, notifier = _build(session, owner, max_retries=1)
        inner.queue(
            FakeRunRecord(run_id=uuid.uuid4(), verified_ok=False, error="e1"),
            FakeRunRecord(run_id=uuid.uuid4(), verified_ok=False, error="e2"),
        )

        mission = await orch.run(_command(), owner_id=owner.id)

        assert mission.status is MissionStatus.FAILED
        assert "max retries" in (mission.error or "").lower()
        assert len(inner.start_calls) == 2
        # Notifier terminal xato bo'yicha xabar yubordi
        assert any("yiqildi" in n.text.lower() or "failed" in n.text.lower() for n in notifier.sent)


# ── 5. Killswitch engaged → CANCELLED, execute chaqirilmaydi ─────


class TestKillSwitchPreflight:
    async def test_killswitch_engaged_cancels_before_execute(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="test emergency")
        orch, inner, _reg, notifier = _build(session, owner, killswitch=ks)

        mission = await orch.run(_command(), owner_id=owner.id)

        assert mission.status is MissionStatus.CANCELLED
        assert "kill switch" in (mission.error or "").lower()
        assert inner.start_calls == []  # bajarish CHAQIRILMAGAN
        # Terminal — notifier bekor qilindi haqida xabar yubordi
        assert any("bekor" in n.text.lower() for n in notifier.sent)


# ── 6. Missing capability → FAILED ───────────────────────────────


class TestMissingCapability:
    async def test_empty_capability_bundle_causes_failed(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        # Bo'sh bundle = hech bir capability moslashmadi
        orch, inner, _reg, notifier = _build(session, owner, bundle=CapabilityBundle())

        mission = await orch.run(_command("noma'lum ish"), owner_id=owner.id)

        assert mission.status is MissionStatus.FAILED
        assert "no capability" in (mission.error or "").lower()
        assert inner.start_calls == []
        assert any("yiqildi" in n.text.lower() for n in notifier.sent)


# ── 7. Persistensiya: POST → GET ──────────────────────────────────


class TestApiPersistence:
    async def test_create_then_get_returns_state(
        self, session: AsyncSession, owner: Owner, tmp_path: Path
    ) -> None:
        _ = tmp_path
        orch, inner, _reg, _notifier = _build(session, owner)
        inner.queue(FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True))

        # HTTP orqali POST /missions — dep override bilan bir xil orchestrator
        app = create_app()
        app.dependency_overrides[get_mission_orchestrator] = lambda: orch
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/api/v1/missions", json={"objective": "eslatma yoz"})
        assert resp.status_code == 200, resp.text
        created = resp.json()
        assert created["status"] == "completed"
        mid = created["id"]

        # GET /missions/{id}
        get_resp = client.get(f"/api/v1/missions/{mid}")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["id"] == mid
        assert fetched["status"] == "completed"
        assert fetched["objective"] == "eslatma yoz"

    async def test_get_missing_mission_returns_404(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        orch, _inner, _reg, _notifier = _build(session, owner)
        app = create_app()
        app.dependency_overrides[get_mission_orchestrator] = lambda: orch
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(f"/api/v1/missions/{uuid.uuid4()}")
        assert resp.status_code == 404


# ── 8. Ro'yxat sahifalash ────────────────────────────────────────


class TestApiPagination:
    async def test_list_missions_paginates(self, session: AsyncSession, owner: Owner) -> None:
        orch, inner, _reg, _notifier = _build(session, owner)
        # 3 ta mission yaratamiz (har biriga muvaffaqiyatli run)
        for _ in range(3):
            inner.queue(FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True))

        for i in range(3):
            await orch.run(_command(f"ish {i}"), owner_id=owner.id)

        app = create_app()
        app.dependency_overrides[get_mission_orchestrator] = lambda: orch
        client = TestClient(app, raise_server_exceptions=False)

        # Birinchi sahifa (limit=2)
        r1 = client.get("/api/v1/missions", params={"limit": 2, "offset": 0})
        assert r1.status_code == 200, r1.text
        page1 = r1.json()
        assert page1["limit"] == 2
        assert page1["offset"] == 0
        assert len(page1["items"]) == 2

        # Ikkinchi sahifa
        r2 = client.get("/api/v1/missions", params={"limit": 2, "offset": 2})
        assert r2.status_code == 200
        page2 = r2.json()
        assert len(page2["items"]) == 1
        # Ikkala sahifada bir xil mission takrorlanmasligi kerak
        ids_page1 = {m["id"] for m in page1["items"]}
        ids_page2 = {m["id"] for m in page2["items"]}
        assert ids_page1.isdisjoint(ids_page2)


# ── 9. Qo'shimcha: notifier yiqilsa mission natijasiga ta'sir qilmaydi


class TestNotifierFailOpen:
    async def test_notifier_failure_does_not_break_mission(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        class ExplodingNotifier(Notifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("tarmoq yiqildi")

        orch, inner, _reg, _n = _build(session, owner, notifier=ExplodingNotifier())
        inner.queue(FakeRunRecord(run_id=uuid.uuid4(), verified_ok=True))

        mission = await orch.run(_command(), owner_id=owner.id)

        # Notifier yiqilgan bo'lsa ham mission COMPLETED bo'lishi kerak
        assert mission.status is MissionStatus.COMPLETED


# ── 10. Adapter smoke — ContextEngineAdapter to_dict beradi ──────


class TestContextEngineAdapter:
    async def test_adapter_returns_view_with_to_dict(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        _ = session

        class _FakeSource:
            value = "memory"

        class _Frag:
            source = _FakeSource()
            content = "salom"

        class _Ctx:
            fragments = (_Frag(),)
            total_tokens = 5
            truncated = False

        class _RealContextStub:
            async def discover(self, request):  # type: ignore[no-untyped-def]
                _ = request
                return _Ctx()

        adapter = ContextEngineAdapter(_RealContextStub())
        view = await adapter.discover("ish", owner_id=owner.id, constraints=[])
        data = view.to_dict()
        assert isinstance(data, dict)
        assert data["fragments"] == [{"source": "memory", "content": "salom"}]
        assert data["total_tokens"] == 5


# ── 11. Mission fixture smoke ────────────────────────────────────


class TestMissionShape:
    async def test_completed_mission_persists_run_ids(
        self, session: AsyncSession, owner: Owner
    ) -> None:
        orch, inner, _reg, _n = _build(session, owner)
        rid = uuid.uuid4()
        inner.queue(FakeRunRecord(run_id=rid, verified_ok=True))

        mission: Mission = await orch.run(_command(), owner_id=owner.id)
        assert rid in mission.run_ids


class TestCapabilityInterfaceContract:
    """Regression: `capability_registry` param FAQAT `compose()` shartnomasini qabul qiladi.

    Bug tarixi: `mission_orchestrator.py:104` type hint ilgari
    `_CapabilityRegistryLike | CapabilityRegistry` edi. Ammo raw
    `CapabilityRegistry.resolve()` beradi, `.compose()` bermaydi.
    Line 173'da `self._capabilities.compose(...)` mypy'da union-attr xato
    berardi va noto'g'ri narsa uzatilsa runtime'da AttributeError bilan
    yiqilardi. Endi type hint faqat Protocol. `CapabilityRegistryComposer`
    haqiqiy adapter.
    """

    def test_registry_composer_provides_compose(self) -> None:
        """`CapabilityRegistryComposer` `.compose()` metodini beradi."""
        from zet.core.capability import CapabilityRegistry
        from zet.core.mission_orchestrator import CapabilityRegistryComposer

        registry = CapabilityRegistry()
        composer = CapabilityRegistryComposer(registry)
        assert hasattr(composer, "compose"), (
            "CapabilityRegistryComposer .compose() metodini bermayapti — "
            "MissionOrchestrator ishlamaydi"
        )
        # compose() aniq bo'sh registry uchun bo'sh bundle qaytarishi kerak
        bundle = composer.compose("test objective", {})
        assert bundle is not None
