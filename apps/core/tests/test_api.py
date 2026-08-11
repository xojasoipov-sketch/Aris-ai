"""Z1.14+ — FastAPI testlari.

httpx AsyncClient bilan TestClient.

Tekshiriladi:
    - GET /api/v1/health → 200
    - GET /api/v1/status → tizim holati
    - POST /api/v1/run → to'liq pipeline (intent → reja → bajarish → tekshirish)
    - POST /api/v1/run killswitch yoqilgan → 503
    - POST /api/v1/run bo'sh message → 422
    - POST /api/v1/run EXECUTE qadami → awaiting_approval + /api/v1/approvals oqimi
    - POST /api/v1/killswitch/engage → engaged
    - POST /api/v1/killswitch/disengage → disengaged
    - POST /api/v1/killswitch/disengage allaqachon o'chirilgan → 400
    - GET /api/v1/killswitch → holat
    - TraceMiddleware: X-Trace-ID headerda qaytariladi
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.app import create_app
from zet.api.deps import get_approval_service, get_killswitch, get_orchestrator
from zet.config import Settings
from zet.core.orchestrator import Orchestrator, RunStore
from zet.llm.base import LLMResponse, ToolUse
from zet.llm.fake import FakeProvider, fake_response
from zet.llm.router import ModelRouter
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.builtin import build_default_registry

_PROVIDER_NAME = "ollama"


def _intent_tool_use(
    action: str = "reminder.create",
    task_class: str = "normal",
    requires_tools: list[str] | None = None,
) -> ToolUse:
    """parse_intent tool chaqiruvini yaratish."""
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="parse_intent",
        arguments={
            "action": action,
            "objects": [],
            "constraints": [],
            "urgency": "normal",
            "task_class": task_class,
            "requires_tools": requires_tools or [],
            "ambiguity": "low",
            "clarification_question": None,
            "confidence": 0.95,
        },
    )


def _plan_tool_use(steps: list[dict] | None = None, summary: str = "Test reja") -> ToolUse:
    """create_plan tool chaqiruvini yaratish."""
    if steps is None:
        steps = [
            {
                "position": 0,
                "description": "Vaqtni ol",
                "tool_name": "time.now",
                "permission_required": "read",
                "trust_context": "owner",
                "depends_on": [],
            },
        ]
    return ToolUse(
        id=f"tu_{uuid.uuid4().hex[:8]}",
        name="create_plan",
        arguments={"summary": summary, "steps": steps},
    )


def _happy_script() -> list[LLMResponse]:
    """intent → reja: 2 ta READ/WRITE qadam, tasdiqsiz avtomatik bajariladi."""
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
            "description": "Eslatma yoz",
            "tool_name": "note.write",
            "tool_params": {"title": "test-eslatma", "content": "Test mazmuni"},
            "permission_required": "write",
            "trust_context": "owner",
            "depends_on": [0],
        },
    ]
    return [
        fake_response(text="", tool_uses=(_intent_tool_use(requires_tools=["time.now"]),)),
        fake_response(text="", tool_uses=(_plan_tool_use(steps),)),
    ]


def _approval_script() -> list[LLMResponse]:
    """intent → reja: 1 ta EXECUTE qadam (tool_name=None) — tasdiq talab qiladi."""
    steps = [
        {
            "position": 0,
            "description": "Xavfli amal",
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
    killswitch: KillSwitchState | None = None,
) -> Orchestrator:
    """Test uchun Orchestrator — FakeProvider + in-memory sqlite sessiya bilan."""
    provider = FakeProvider(name=_PROVIDER_NAME, scripted=scripted)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    router = ModelRouter(providers={provider.name: provider}, session=session, settings=settings)
    tool_registry = build_default_registry(notes_dir=tmp_path)
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=PermissionPolicy(),
        approval_service=ApprovalService(),
        killswitch=killswitch or KillSwitchState(),
        run_store=RunStore(),
        budget_usd=1.0,
    )


def _client_for(app_overrides: dict) -> TestClient:
    app = create_app()
    app.dependency_overrides.update(app_overrides)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def killswitch() -> KillSwitchState:
    """Har bir test uchun yangi killswitch."""
    return KillSwitchState()


@pytest.fixture()
def client(killswitch: KillSwitchState) -> TestClient:
    """FastAPI test client (pipeline ishlatmaydigan endpoint'lar uchun)."""
    app = create_app()
    app.dependency_overrides[get_killswitch] = lambda: killswitch
    return TestClient(app, raise_server_exceptions=False)


# ── Health ─────────────────────────────────────────────────────────


class TestHealth:
    def test_health_check(self, client: TestClient) -> None:
        """GET /health → 200."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_status(self, client: TestClient) -> None:
        """GET /status → tizim holati."""
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "killswitch" in data
        assert "budget" in data

    def test_status_with_killswitch(self, client: TestClient, killswitch: KillSwitchState) -> None:
        """GET /status killswitch yoqilgan → killswitch_engaged."""
        killswitch.engage(reason="Test")
        resp = client.get("/api/v1/status")
        assert resp.json()["status"] == "killswitch_engaged"


# ── Run (to'liq pipeline) ─────────────────────────────────────────


class TestRun:
    async def test_create_run_success(self, session: AsyncSession, tmp_path: Path) -> None:
        """POST /run — intent → reja → bajarish → tekshirish → done."""
        orchestrator = _make_orchestrator(session, tmp_path, _happy_script())
        client = _client_for({get_orchestrator: lambda: orchestrator})

        resp = client.post("/api/v1/run", json={"message": "Ertaga uchrashuv eslatmasi yoz"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["steps_done"] == 2
        assert "run_id" in data
        assert len(data["trace_id"]) == 32

    async def test_run_with_killswitch(self, session: AsyncSession, tmp_path: Path) -> None:
        """POST /run killswitch yoqilgan → 503."""
        ks = KillSwitchState()
        ks.engage(reason="Test")
        orchestrator = _make_orchestrator(session, tmp_path, _happy_script(), killswitch=ks)
        client = _client_for({get_orchestrator: lambda: orchestrator})

        resp = client.post("/api/v1/run", json={"message": "test"})
        assert resp.status_code == 503

    def test_run_empty_message(self, client: TestClient) -> None:
        """POST /run bo'sh message → 422 (orchestrator hech qachon chaqirilmaydi)."""
        resp = client.post("/api/v1/run", json={"message": ""})
        assert resp.status_code == 422

    async def test_run_dry_run(self, session: AsyncSession, tmp_path: Path) -> None:
        """POST /run dry_run=true — haqiqiy fayl yozilmaydi, baribir done."""
        orchestrator = _make_orchestrator(session, tmp_path, _happy_script())
        client = _client_for({get_orchestrator: lambda: orchestrator})

        resp = client.post(
            "/api/v1/run",
            json={"message": "test", "dry_run": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    async def test_run_needs_approval(self, session: AsyncSession, tmp_path: Path) -> None:
        """POST /run EXECUTE qadami → awaiting_approval + pending_approval_id."""
        orchestrator = _make_orchestrator(session, tmp_path, _approval_script())
        client = _client_for({get_orchestrator: lambda: orchestrator})

        resp = client.post("/api/v1/run", json={"message": "xavfli amal bajar"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "awaiting_approval"
        assert data["pending_approval_id"] is not None

    async def test_get_run_status(self, session: AsyncSession, tmp_path: Path) -> None:
        """GET /run/{run_id} — run holatini qaytaradi."""
        orchestrator = _make_orchestrator(session, tmp_path, _happy_script())
        client = _client_for({get_orchestrator: lambda: orchestrator})

        create_resp = client.post("/api/v1/run", json={"message": "test"})
        run_id = create_resp.json()["run_id"]

        resp = client.get(f"/api/v1/run/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    def test_get_run_not_found(self, client: TestClient) -> None:
        """GET /run/{run_id} noto'g'ri id → 404."""
        resp = client.get(f"/api/v1/run/{uuid.uuid4()}")
        assert resp.status_code == 404


# ── Approvals ──────────────────────────────────────────────────────


class TestApprovals:
    async def test_approve_resumes_run(self, session: AsyncSession, tmp_path: Path) -> None:
        """Tasdiqlangandan keyin run davom etib, done bo'ladi."""
        orchestrator = _make_orchestrator(session, tmp_path, _approval_script())
        client = _client_for(
            {
                get_orchestrator: lambda: orchestrator,
                get_approval_service: lambda: orchestrator.approvals,
            }
        )

        run_resp = client.post("/api/v1/run", json={"message": "xavfli amal"})
        run_id = run_resp.json()["run_id"]
        approval_id = run_resp.json()["pending_approval_id"]

        list_resp = client.get("/api/v1/approvals", params={"run_id": run_id})
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        approve_resp = client.post(f"/api/v1/approvals/{approval_id}/approve", json={})
        assert approve_resp.status_code == 200
        data = approve_resp.json()
        assert data["run_status"] == "done"
        assert data["approval"]["status"] == "approved"

    async def test_reject_cancels_run(self, session: AsyncSession, tmp_path: Path) -> None:
        """Rad etilgan tasdiq — run CANCELLED bo'ladi."""
        orchestrator = _make_orchestrator(session, tmp_path, _approval_script())
        client = _client_for({get_orchestrator: lambda: orchestrator})

        run_resp = client.post("/api/v1/run", json={"message": "xavfli amal"})
        approval_id = run_resp.json()["pending_approval_id"]

        reject_resp = client.post(
            f"/api/v1/approvals/{approval_id}/reject",
            json={"note": "Yo'q"},
        )
        assert reject_resp.status_code == 200
        data = reject_resp.json()
        assert data["run_status"] == "cancelled"
        assert data["approval"]["status"] == "rejected"

    def test_approve_not_found(self, client: TestClient) -> None:
        """Mavjud bo'lmagan tasdiq → 404."""
        resp = client.post(f"/api/v1/approvals/{uuid.uuid4()}/approve", json={})
        assert resp.status_code == 404

    def test_list_requires_run_id(self, client: TestClient) -> None:
        """run_id bermasdan → 400."""
        resp = client.get("/api/v1/approvals")
        assert resp.status_code == 400


# ── KillSwitch ────────────────────────────────────────────────────


class TestKillSwitchAPI:
    def test_engage(self, client: TestClient) -> None:
        """POST /killswitch/engage → engaged."""
        resp = client.post(
            "/api/v1/killswitch/engage",
            json={"reason": "Test engage"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "engaged"

    def test_disengage(self, client: TestClient, killswitch: KillSwitchState) -> None:
        """POST /killswitch/disengage → disengaged."""
        killswitch.engage(reason="Test")
        resp = client.post("/api/v1/killswitch/disengage")
        assert resp.status_code == 200
        assert resp.json()["status"] == "disengaged"

    def test_disengage_already_off(self, client: TestClient) -> None:
        """POST /killswitch/disengage allaqachon o'chirilgan → 400."""
        resp = client.post("/api/v1/killswitch/disengage")
        assert resp.status_code == 400

    def test_status(self, client: TestClient) -> None:
        """GET /killswitch → holat."""
        resp = client.get("/api/v1/killswitch")
        assert resp.status_code == 200
        assert "killswitch" in resp.json()


# ── Middleware ────────────────────────────────────────────────────


class TestTraceMiddleware:
    def test_trace_id_in_response(self, client: TestClient) -> None:
        """Javob headerida X-Trace-ID bor."""
        resp = client.get("/api/v1/health")
        assert "X-Trace-ID" in resp.headers
        assert len(resp.headers["X-Trace-ID"]) == 32

    def test_trace_id_forwarded(self, client: TestClient) -> None:
        """So'rovdagi X-Trace-ID qaytariladi."""
        resp = client.get(
            "/api/v1/health",
            headers={"X-Trace-ID": "custom-trace-123"},
        )
        assert resp.headers["X-Trace-ID"] == "custom-trace-123"
