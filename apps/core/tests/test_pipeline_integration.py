"""Real integration test — Executor + Task Graph DAG + Approval + Recovery zanjiri.

Fake yo'q, mock yo'q — real API TestClient orqali POST /api/v1/run.
Faqat LLM `FakeProvider` bilan almashtiriladi (real LLM narxi va no'or
sabab: aynan pipeline mantiqi tekshiriladi, model korrektligi emas).

Bu test AUDIT topgan gap'ni yopadi (§punkt 3 xato):
"Mission Engine → Task Graph → Approval Engine → Recovery Engine
zanjiri birgalikda ishlaganda hech qanday test tomonidan tekshirilmagan."
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_killswitch, get_orchestrator
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.run_checkpoint import load_pending_runs, persist_run
from zet.domain.enums import PermissionLevel
from zet.llm.base import LLMResponse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry

_PROVIDER_NAME = "ollama"
"""ModelRouter tier'lariga o'rnatilgan provayder ismi.

Fake'ni "fake" deb nomlash ModelRouter'ning `simple` tier'idagi provayder
navbatiga tushmaydi → "provayder topilmadi" xatosi. Real provayder ismi
bilan qayd qilinsa, tier `ollama` navbatida topadi va Fake'ni chaqiradi.
"""


def _intent_tool_use(requires_tools: list[str] | None = None) -> object:
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


def _plan_tool_use(steps: list[dict]) -> object:
    from zet.llm.base import ToolUse

    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="create_plan",
        arguments={"summary": "test plan", "steps": steps},
    )


def _dag_script() -> list[LLMResponse]:
    """intent → reja: 3 qadam DAG:
        0. time.now (mustaqil)
        1. note.write "left" (depends 0)
        2. note.write "right" (depends 0) — position 1 bilan parallel ishlaydi
    """
    steps = [
        {
            "position": 0,
            "description": "Vaqtni ol",
            "tool_name": "time.now",
            "permission_required": "read",
            "trust_context": "owner",
            "depends_on": [],
        },
        {
            "position": 1,
            "description": "Chap eslatma",
            "tool_name": "note.write",
            "tool_params": {"title": "left", "content": "LEFT"},
            "permission_required": "write",
            "trust_context": "owner",
            "depends_on": [0],
        },
        {
            "position": 2,
            "description": "O'ng eslatma",
            "tool_name": "note.write",
            "tool_params": {"title": "right", "content": "RIGHT"},
            "permission_required": "write",
            "trust_context": "owner",
            "depends_on": [0],
        },
    ]
    return [
        fake_response(text="", tool_uses=(_intent_tool_use(requires_tools=["time.now", "note.write"]),)),
        fake_response(text="", tool_uses=(_plan_tool_use(steps),)),
    ]


def _approval_script() -> list[LLMResponse]:
    """intent → reja: 1 EXECUTE qadam (tool_name=None) — tasdiq talab qiladi."""
    steps = [
        {
            "position": 0,
            "description": "HIGH risk amal",
            "tool_name": None,
            "permission_required": "execute",
            "trust_context": "owner",
            "depends_on": [],
        },
    ]
    return [
        fake_response(text="", tool_uses=(_intent_tool_use(),)),
        fake_response(text="", tool_uses=(_plan_tool_use(steps),)),
    ]


def _make_orchestrator(
    session: AsyncSession,
    tmp_path: Path,
    scripted: list[LLMResponse],
    *,
    approvals: ApprovalService | None = None,
    run_store: RunStore | None = None,
    killswitch: KillSwitchState | None = None,
    notifier: object | None = None,
) -> Orchestrator:
    from zet.config import Settings

    provider = FakeProvider(name=_PROVIDER_NAME, scripted=scripted)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(providers={provider.name: provider}, session=session, settings=settings)
    tool_registry = build_default_registry(notes_dir=tmp_path)
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        # `auto_approve_medium=True` — produksiya default'i bilan bir xil
        # (`deps.get_permission_policy`, `ZET_AUTO_APPROVE_MEDIUM_RISK`).
        # Bu testlar DAG/pipeline oqimini tekshiradi, MEDIUM approval
        # siyosatini emas — u alohida `test_executor_risk_table.py`da.
        permission_policy=PermissionPolicy(auto_approve_medium=True),
        approval_service=approvals or ApprovalService(),
        killswitch=killswitch or KillSwitchState(),
        run_store=run_store or RunStore(),
        budget_usd=1.0,
        notifier=notifier,  # type: ignore[arg-type]
    )


def _client_with(overrides: dict) -> TestClient:
    """`get_killswitch` avtomatik toza KS'ga override qilinadi.

    NEGA. `get_killswitch()` `@lru_cache` singleton — testlar orasida
    holat ushlanib qoladi. Bir test global KS'ni engage qilsa (masalan
    `test_killswitch_security`), keyingi testlar `/run` chaqirig'ida
    503 oladi. Har test uchun toza KS injektsiya qilamiz — override
    ro'yxatida bo'lsa (masalan aynan KS test'ida), o'zining KS'i qoladi.
    """
    app = create_app()
    if get_killswitch not in overrides:
        overrides = {get_killswitch: lambda: KillSwitchState(), **overrides}
    app.dependency_overrides.update(overrides)
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST 1: Task Graph DAG — parallel qadamlar
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration()
class TestDAGParallelBatches:
    """Real POST /api/v1/run → Executor DAG batch-by-batch bajaradi."""

    async def test_diamond_dag_executes_parallel_batch(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """3 qadam: 0 → {1, 2}. 1 va 2 bir batchda parallel ishga tushishi kerak.

        Verify DAG batching: results dict'da 3 qadam ham DONE bo'lishi kerak.
        Fayl tizimida ikkala note (left.md, right.md) yaratilishi kerak.
        """
        orchestrator = _make_orchestrator(session, tmp_path, _dag_script())
        client = _client_with({get_orchestrator: lambda: orchestrator})

        response = client.post(
            "/api/v1/run",
            json={"message": "ikki eslatma yoz DAG bilan"},
        )
        assert response.status_code == 200, response.text
        data = response.json()

        # DAG'ning 3 qadami ham bajarilgan
        assert data["status"] == "done", f"Kutildi 'done', keldi: {data['status']} — {data.get('error')}"
        assert data["steps_done"] == 3, f"3 qadam kutildi, {data['steps_done']} ta bajarildi"

        # Ikkala parallel note fizik yozilgan
        left = tmp_path / "left.md"
        right = tmp_path / "right.md"
        assert left.exists(), f"Chap eslatma yozilmagan: {left}"
        assert right.exists(), f"O'ng eslatma yozilmagan: {right}"
        assert "LEFT" in left.read_text()
        assert "RIGHT" in right.read_text()


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST 2: Approval oqimi — real /run → /approvals cross-endpoint
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration()
class TestApprovalRoundTrip:
    """Real POST /run (EXECUTE step) → 200 awaiting_approval → POST /approvals/{id}/approve → resume."""

    async def test_execute_step_blocks_then_approve_resumes(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Full flow:
            1. POST /run xavfli qadam — 200 status=awaiting_approval, pending_approval_id qaytadi
            2. POST /api/v1/approvals/{id}/approve — 200
            3. Run status DONE bo'lishi kerak (kichik execute step, boshqa hech nima)
        """
        from zet.api.deps import get_approval_service, get_run_store

        # Ikkala endpoint uchun bir xil shared state kerak
        shared_store = RunStore()
        shared_approvals = ApprovalService(ttl_minutes=30)

        orchestrator = _make_orchestrator(
            session,
            tmp_path,
            _approval_script(),
            run_store=shared_store,
            approvals=shared_approvals,
        )
        client = _client_with(
            {
                get_orchestrator: lambda: orchestrator,
                get_run_store: lambda: shared_store,
                get_approval_service: lambda: shared_approvals,
            }
        )

        # 1. Run yaratish — EXECUTE step tasdiq talab qiladi
        resp1 = client.post("/api/v1/run", json={"message": "xavfli amal"})
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()
        assert data1["status"] == "awaiting_approval", (
            f"AWAITING_APPROVAL kutildi, keldi: {data1['status']}"
        )
        approval_id = data1["pending_approval_id"]
        assert approval_id is not None, "pending_approval_id qaytmadi"

        # 2. Real POST /approvals/{id}/approve
        resp2 = client.post(
            f"/api/v1/approvals/{approval_id}/approve",
            json={"note": "test tasdiq"},
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()

        # 3. Run holati — approve dan keyin done bo'lishi kerak
        # (execute step tool_name=None, EGA tasdig'i bilan avtomatik done)
        assert data2["run_status"] == "done", (
            f"Approve keyin run 'done' kutildi, keldi: {data2['run_status']}"
        )


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST 3: Killswitch → run bloklanadi (503)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration()
class TestKillswitchBlocksRun:
    """Killswitch engaged bo'lsa POST /run 503 qaytaradi (real pipeline chaqirilmaydi)."""

    async def test_killswitch_blocks_new_run(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="integration test")
        orchestrator = _make_orchestrator(
            session, tmp_path, _dag_script(), killswitch=ks
        )
        # Killswitch route darajasida `get_killswitch` orqali tekshiriladi —
        # aynan shu test'da orchestrator'ga bergan KS'ni route'ga ham beramiz.
        client = _client_with({
            get_orchestrator: lambda: orchestrator,
            get_killswitch: lambda: ks,
        })

        resp = client.post("/api/v1/run", json={"message": "test"})
        assert resp.status_code == 503, f"503 kutildi, keldi: {resp.status_code}"


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST 4: AR-01 checkpoint — restart-round-trip
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration()
class TestRunPersistenceRoundTrip:
    """Yangi persistence: POST /run awaiting → DB'ga → restart simulyatsiyasi → tiklanadi."""

    async def test_awaiting_run_restored_after_restart(
        self, session: AsyncSession, session_factory, tmp_path: Path
    ) -> None:
        from zet.api.deps import get_approval_service, get_run_store
        from zet.db.bootstrap import get_or_create_owner

        # Owner
        await get_or_create_owner(session, external_id="test-restart")
        await session.commit()

        # 1. Sessiya A — run yaratamiz + AWAITING → DB'ga yozamiz
        store_a = RunStore()
        approvals_a = ApprovalService(ttl_minutes=30)
        orch_a = _make_orchestrator(
            session, tmp_path, _approval_script(),
            run_store=store_a, approvals=approvals_a,
        )
        client_a = _client_with({
            get_orchestrator: lambda: orch_a,
            get_run_store: lambda: store_a,
            get_approval_service: lambda: approvals_a,
        })

        resp = client_a.post("/api/v1/run", json={"message": "restart-safe amal"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_approval"
        run_id_str = data["run_id"]
        run_id = uuid.UUID(run_id_str)

        # Explicit DB checkpoint (production'da orchestrator o'zi qiladi)
        record = store_a.get(run_id)
        await persist_run(session_factory, record, owner_external_id="test-restart")

        # 2. Sessiya B — "protsess qayta ishga tushdi" — yangi bo'sh store
        store_b = RunStore()
        assert run_id not in store_b._runs

        # Startup restore
        restored = await load_pending_runs(session_factory, store_b)
        assert restored == 1, f"1 run tiklanishi kerak, keldi: {restored}"
        assert run_id in store_b._runs

        # 3. Tiklangan run haqiqiy — status va command matn saqlangan
        tiklangan = store_b.get(run_id)
        assert tiklangan.status.value == "awaiting_approval"
        assert tiklangan.command.text == "restart-safe amal"


@pytest.mark.integration()
class TestOrchestratorAutoPersist:
    """AR-01 to'liq wiring: orchestrator O'ZI persist chaqiradi (test buni chaqirmaydi).

    Bu test avvalgi `TestRunPersistenceRoundTrip`ni to'ldiradi: unda test
    o'zi `persist_run` chaqirdi ("production'da orchestrator qiladi" izohi
    bilan). Bu test o'sha izohni QULFLAB QO'YADI — RunStore'ga session_factory
    berilsa, orchestrator birinchi POST /run javobidan keyin DB'da row bor.
    """

    async def test_awaiting_run_auto_persisted_by_orchestrator(
        self, session: AsyncSession, session_factory, tmp_path: Path
    ) -> None:
        from sqlalchemy import select

        from zet.api.deps import get_approval_service, get_run_store
        from zet.db.bootstrap import get_or_create_owner
        from zet.db.models.run import Run as RunRow

        # Owner (persist_run FK'siz yiqiladi)
        await get_or_create_owner(session, external_id="auto-persist-owner")
        await session.commit()

        # AR-01 kalitli farq: RunStore session_factory BILAN.
        # Orchestrator bunday store'da har status o'zgarganda persist chaqiradi.
        store = RunStore(
            session_factory=session_factory,
            owner_external_id="auto-persist-owner",
        )
        approvals = ApprovalService(
            ttl_minutes=30, session_factory=session_factory,
        )
        orch = _make_orchestrator(
            session, tmp_path, _approval_script(),
            run_store=store, approvals=approvals,
        )
        client = _client_with({
            get_orchestrator: lambda: orch,
            get_run_store: lambda: store,
            get_approval_service: lambda: approvals,
        })

        resp = client.post("/api/v1/run", json={"message": "auto-persist test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_approval"
        run_id = uuid.UUID(data["run_id"])

        # HECH QANDAY explicit persist_run chaqirmadik — orchestrator qildi.
        # DB'da row bo'lishi kerak.
        async with session_factory() as s:
            row = (
                await s.execute(select(RunRow).where(RunRow.id == run_id))
            ).scalar_one_or_none()

        assert row is not None, "Orchestrator AWAITING_APPROVAL'da persist chaqirishi kerak edi"
        assert row.command_text == "auto-persist test"
        assert row.status.value == "awaiting_approval"

    async def test_approval_row_also_persisted_not_just_run(
        self, session: AsyncSession, session_factory, tmp_path: Path
    ) -> None:
        """A1 audit (KONSOLIDATSIYA v2): real Postgres'da topilgan
        `ForeignKeyViolationError` regression testi.

        SQLite ham `PRAGMA foreign_keys=ON` bilan ishlaydi
        (`db/session.py::_enable_sqlite_foreign_keys`) — shuning uchun bu
        test REAL Postgres'siz ham FK-tartib xatosini ushlay oladi.
        Ilgari (fix'dan oldin) `request_approval()` `run` qatoridan OLDIN
        chaqirilardi — `approval.run_id` FK hali mavjud bo'lmagan `run_id`
        ga ishora qilardi, real Postgres'da bu doim yiqilardi (SQLite'da
        esa FK yoqilgan bo'lsa ham xato `session_scope`ning o'zi
        yutmasdi — chunki bu YANGI aniqlangan gap edi, mavjud testlar
        buni tekshirmagan).
        """
        from sqlalchemy import select

        from zet.api.deps import get_approval_service, get_run_store
        from zet.db.bootstrap import get_or_create_owner
        from zet.db.models.security import Approval as ApprovalRow

        await get_or_create_owner(session, external_id="auto-persist-owner2")
        await session.commit()

        store = RunStore(session_factory=session_factory, owner_external_id="auto-persist-owner2")
        approvals = ApprovalService(ttl_minutes=30, session_factory=session_factory)
        orch = _make_orchestrator(
            session, tmp_path, _approval_script(), run_store=store, approvals=approvals,
        )
        client = _client_with({
            get_orchestrator: lambda: orch,
            get_run_store: lambda: store,
            get_approval_service: lambda: approvals,
        })

        resp = client.post("/api/v1/run", json={"message": "fk order test"})
        assert resp.status_code == 200
        data = resp.json()
        approval_id = uuid.UUID(data["pending_approval_id"])

        async with session_factory() as s:
            row = (
                await s.execute(select(ApprovalRow).where(ApprovalRow.id == approval_id))
            ).scalar_one_or_none()

        assert row is not None, (
            "Approval qatori DB'da bo'lishi kerak edi — FK-tartib bug qaytdi!"
        )
        assert row.run_id == uuid.UUID(data["run_id"])


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST 5: F1 — Telegram approval xabari (BLOCK-3 audit gap)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.integration()
class TestTelegramApprovalNotification:
    """AWAITING_APPROVAL'ga o'tganda `Notifier.send_approval()` chaqirilishi.

    AUDIT topgan gap (BLOCK-3 checklist F1): `Notifier.send_approval()`/
    `ApprovalKeyboard` production kodida HECH QAYERDA chaqirilmasdi —
    faqat testlarda. Owner HIGH_RISK qadam to'xtaganini Telegram'da
    UMUMAN ko'rmasdi. Bu test aynan shu OUTBOUND yo'lni real
    `POST /api/v1/run` orqali qulflaydi.
    """

    async def test_awaiting_approval_sends_telegram_message_with_keyboard(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        from zet.telegram.keyboards import ApprovalKeyboard
        from zet.telegram.notifier import NotificationType, StubNotifier

        stub_notifier = StubNotifier()
        orchestrator = _make_orchestrator(
            session, tmp_path, _approval_script(), notifier=stub_notifier
        )
        client = _client_with({get_orchestrator: lambda: orchestrator})

        resp = client.post("/api/v1/run", json={"message": "xavfli amal"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "awaiting_approval"
        run_id = data["run_id"]

        # Telegram'ga aynan bitta APPROVAL xabari yuborilgan bo'lishi kerak.
        approval_notifications = [
            n for n in stub_notifier.sent if n.type == NotificationType.APPROVAL
        ]
        assert len(approval_notifications) == 1, (
            f"1 ta APPROVAL xabar kutildi, keldi: {len(approval_notifications)}"
        )
        notification = approval_notifications[0]
        assert notification.run_id == run_id

        # Keyboard aynan `_approval_runner` (deps.py) kutayotgan formatda —
        # callback_data run_id'ga bog'langan, approval_id'ga EMAS (chunki
        # inbound handler pending_for_run(run_id) orqali topadi).
        expected = ApprovalKeyboard.for_run(run_id)
        assert notification.keyboard == expected, (
            "Keyboard callback_data 'approve:{run_id}'/'reject:{run_id}' "
            "formatda bo'lishi kerak"
        )

    async def test_no_notifier_configured_does_not_break_run(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        """Fail-open: `notifier=None` bo'lsa (eski wiring) run baribir ishlaydi."""
        orchestrator = _make_orchestrator(
            session, tmp_path, _approval_script(), notifier=None
        )
        client = _client_with({get_orchestrator: lambda: orchestrator})

        resp = client.post("/api/v1/run", json={"message": "xavfli amal"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "awaiting_approval"


# ══════════════════════════════════════════════════════════════════
# INTEGRATION TEST: B3 audit (KONSOLIDATSIYA v2) — suhbat konteksti
# ketma-ket xabarlar orasida yo'qolmasligi (Telegram context-loss bug)
# ══════════════════════════════════════════════════════════════════


class TestB3ConversationContextAcrossMessages:
    """B3 — 2 ta ketma-ket xabar: birinchi ma'lumot so'raydi, ikkinchisi
    "shunga" deb oldingisiga ishora qiladi. To'liq `Orchestrator.start()`
    zanjiri orqali (Intent → Plan → Executor._think()) LLM'ga yuboriladigan
    HAR BIR xabar tarixni ko'rishi kerak — faqat javob yozish bosqichi
    emas (bu allaqachon ishlagan), Intent/Plan bosqichlari ham.
    """

    async def test_second_message_llm_calls_see_first_turn_context(
        self, session: AsyncSession, tmp_path: Path
    ) -> None:
        from zet.domain.command import Command, ConversationTurn
        from zet.domain.enums import MessageRole
        from zet.domain.enums import RunStatus as _RunStatus

        thinking_step = [
            {
                "position": 0,
                "description": "Javob yoz",
                "tool_name": None,
                "permission_required": "read",
                "trust_context": "owner",
                "depends_on": [],
            }
        ]
        # Har turn uchun 3 ta LLM chaqiruv: intent → plan → thinking javob.
        scripted = [
            fake_response(text="", tool_uses=(_intent_tool_use(),)),
            fake_response(text="", tool_uses=(_plan_tool_use(thinking_step),)),
            fake_response(text="Aris AI — shaxsiy AI operatsion tizim."),
            # 2-turn:
            fake_response(text="", tool_uses=(_intent_tool_use(),)),
            fake_response(text="", tool_uses=(_plan_tool_use(thinking_step),)),
            fake_response(text="Batafsil: Aris AI mustaqil vazifalarni bajaradi."),
        ]
        orchestrator = _make_orchestrator(session, tmp_path, scripted)
        provider = orchestrator._router._providers[_PROVIDER_NAME]  # type: ignore[attr-defined]

        # ── 1-xabar: ma'lumot so'raydi, tarix bo'sh ──────────────────
        record1 = await orchestrator.start(
            Command(text="Aris AI haqida ma'lumot ber", history=[])
        )
        assert record1.status == _RunStatus.DONE
        answer1 = record1.result_summary
        assert answer1 == "Aris AI — shaxsiy AI operatsion tizim."
        assert len(provider.calls) == 3, "1-turn 3 ta LLM chaqiruv qilishi kerak edi"

        # ── 2-xabar: "shunga" — oldingi almashuvni tarix sifatida uzatamiz
        #    (aynan `get_telegram_bot()._runner` ConversationStore orqali
        #    qiladigan narsa — bu yerda qo'lda simulyatsiya qilinadi) ──
        history_turn2 = [
            ConversationTurn(role=MessageRole.USER, content="Aris AI haqida ma'lumot ber"),
            ConversationTurn(role=MessageRole.ASSISTANT, content=answer1),
        ]
        record2 = await orchestrator.start(
            Command(text="shunga batafsilroq ayt", history=history_turn2)
        )
        assert record2.status == _RunStatus.DONE
        assert len(provider.calls) == 6, "2-turn yana 3 ta LLM chaqiruv qilishi kerak edi"

        # B3 ENG MUHIM DALIL: 2-turn'ning INTENT chaqiruvi (4-chaqiruv,
        # index 3) 1-turn kontekstini ko'rgan — bug ILGARI aynan shu
        # yerda edi (`command.history` Intent bosqichiga UMUMAN
        # yetib bormasdi).
        intent_call_messages = provider.calls[3]["messages"]
        intent_contents = [m.content for m in intent_call_messages]  # type: ignore[union-attr]
        assert "Aris AI haqida ma'lumot ber" in intent_contents, (
            "B3 BUZILDI: 2-xabarning Intent bosqichi 1-xabar kontekstini ko'rmadi"
        )
        assert answer1 in intent_contents, (
            "B3 BUZILDI: 2-xabarning Intent bosqichi 1-javobni ko'rmadi"
        )
        # Joriy ("shunga...") xabar tarix orqasida, oxirida keladi
        assert intent_call_messages[-1].content == "shunga batafsilroq ayt"  # type: ignore[union-attr]

        # Plan bosqichi (5-chaqiruv, index 4) ham xuddi shunday
        plan_call_messages = provider.calls[4]["messages"]
        plan_contents = [m.content for m in plan_call_messages]  # type: ignore[union-attr]
        assert "Aris AI haqida ma'lumot ber" in plan_contents, (
            "B3 BUZILDI: 2-xabarning Plan bosqichi 1-xabar kontekstini ko'rmadi"
        )
