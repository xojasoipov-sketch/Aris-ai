"""Bo'lim 4 — Agent Factory va Eval testlari.

Tekshiriladi:
    - EvalRunner: spec, tool, permission, prompt, brake validatsiyasi
    - AgentFactory: V-10 oqimi (understand → check → design → eval → activate)
    - Factory xato holatlari (dublikat, eval muvaffaqiyatsiz)
    - CEO va Operations agent speclari
    - Factory API endpoint
    - Factory CLI buyruq
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.builtin.operations import OPERATIONS_AGENT_SPEC
from zet.agents.eval import EvalRunner
from zet.agents.factory import AgentFactory, FactoryRequest
from zet.agents.lifecycle import AgentLifecycle
from zet.agents.registry import AgentRegistry
from zet.api.app import create_app
from zet.api.deps import get_agent_registry, get_killswitch
from zet.cli import app as cli_app
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus, PermissionLevel, TrustLevel
from zet.security.killswitch import KillSwitchState

runner = CliRunner()


# ── Eval testlari ────────────────────────────────────────────────


class TestEvalRunner:
    def test_valid_spec_passes(self) -> None:
        """To'g'ri spec barcha tekshiruvlardan o'tadi."""
        spec = AgentSpec(
            name="test",
            description="Test agent",
            system_prompt="Sen test agentisan. QOIDALAR: aniq bo'l.",
            tool_allowlist=["web.search", "time.now"],
            permission_level=PermissionLevel.READ,
        )
        result = EvalRunner().run_eval(spec)
        assert result.success
        assert result.passed == result.total
        assert result.failed == 0

    def test_empty_tools_passes(self) -> None:
        """Bo'sh tool allowlist — xato emas."""
        spec = AgentSpec(
            name="no_tools",
            description="Tool yo'q agent",
            system_prompt="Sen oddiy agentsan. QOIDALAR: javob ber.",
        )
        result = EvalRunner().run_eval(spec)
        assert result.success

    def test_unknown_tool_fails(self) -> None:
        """Noma'lum tool — eval muvaffaqiyatsiz."""
        spec = AgentSpec(
            name="bad_tools",
            description="Noma'lum tool",
            system_prompt="Sen agentsan. QOIDALAR: harakat qil.",
            tool_allowlist=["nonexistent.tool"],
        )
        result = EvalRunner().run_eval(spec)
        assert not result.success
        assert result.failed > 0
        # tools_valid testi muvaffaqiyatsiz
        tool_case = next(c for c in result.cases if c.name == "tools_valid")
        assert not tool_case.passed
        assert "nonexistent.tool" in (tool_case.error or "")

    def test_permission_violation_fails(self) -> None:
        """READ agent shell.exec (EXECUTE) tooli bilan — ruxsat buzilishi."""
        spec = AgentSpec(
            name="bad_perms",
            description="Permission buzilish",
            system_prompt="Sen agentsan. Hamma narsani qil.",
            tool_allowlist=["shell.exec"],
            permission_level=PermissionLevel.READ,
        )
        result = EvalRunner().run_eval(spec)
        assert not result.success
        perm_case = next(c for c in result.cases if c.name == "permissions_valid")
        assert not perm_case.passed

    def test_write_agent_with_note_write_passes(self) -> None:
        """WRITE agent note.write (WRITE) bilan — ruxsat mos."""
        spec = AgentSpec(
            name="writer",
            description="Writer agent",
            system_prompt="Sen yozuvchi agentsan. QOIDALAR: yoz.",
            tool_allowlist=["note.write"],
            permission_level=PermissionLevel.WRITE,
        )
        result = EvalRunner().run_eval(spec)
        perm_case = next(c for c in result.cases if c.name == "permissions_valid")
        assert perm_case.passed

    def test_short_prompt_fails(self) -> None:
        """Juda qisqa prompt — eval muvaffaqiyatsiz."""
        spec = AgentSpec(
            name="short",
            description="Qisqa prompt",
            system_prompt="Qisqa.",
        )
        result = EvalRunner().run_eval(spec)
        assert not result.success
        prompt_case = next(c for c in result.cases if c.name == "prompt_valid")
        assert not prompt_case.passed

    def test_brakes_valid(self) -> None:
        """A-07 tormozlar xavfsiz diapazonda."""
        spec = AgentSpec(
            name="safe",
            description="Safe agent",
            system_prompt="Sen xavfsiz agentsan. QOIDALAR: ehtiyot bo'l.",
            max_steps=10,
            max_tool_calls=20,
            timeout_s=120,
        )
        result = EvalRunner().run_eval(spec)
        brake_case = next(c for c in result.cases if c.name == "brakes_valid")
        assert brake_case.passed

    def test_eval_result_counts(self) -> None:
        """Eval natijasi to'g'ri sanaydi."""
        spec = AgentSpec(
            name="counter",
            description="Sanash testi",
            system_prompt="Sen agentsan. QOIDALAR: to'g'ri sana.",
        )
        result = EvalRunner().run_eval(spec)
        assert result.total == 5
        assert result.passed + result.failed == result.total


# ── Factory testlari ──────────────────────────────────────────────


class TestAgentFactory:
    @pytest.fixture()
    def setup(self) -> tuple[AgentRegistry, AgentLifecycle, AgentFactory]:
        reg = AgentRegistry()
        lc = AgentLifecycle(reg)
        factory = AgentFactory(reg, lc, EvalRunner())
        return reg, lc, factory

    def test_create_basic(self, setup: tuple) -> None:
        """Oddiy agent yaratish."""
        _reg, _, factory = setup
        request = FactoryRequest(description="YouTube analitikasini kuzatadigan agent")
        result = factory.create(request)

        assert result.success
        assert result.agent_state is not None
        assert result.spec is not None
        assert result.eval_result is not None
        assert result.eval_result.success
        assert len(result.steps) > 0

    def test_create_with_research_keywords(self, setup: tuple) -> None:
        """Tadqiqot kalit so'zlari bilan — research bo'limi va researcher roli."""
        _, _, factory = setup
        request = FactoryRequest(description="Bozor tadqiqot qilib beruvchi agent yarat")
        result = factory.create(request)

        assert result.success
        assert result.spec is not None
        assert result.spec.division == "research"
        assert result.spec.role == "researcher"

    def test_create_with_monitor_keywords(self, setup: tuple) -> None:
        """Monitor kalit so'zlari bilan — ops bo'limi va monitor roli."""
        _, _, factory = setup
        request = FactoryRequest(description="Tizimni kuzatuvchi monitoring agenti")
        result = factory.create(request)

        assert result.success
        assert result.spec is not None
        assert result.spec.division == "ops"
        assert result.spec.role == "monitor"

    def test_create_auto_activate(self, setup: tuple) -> None:
        """auto_activate=True — TESTING dan ACTIVE ga."""
        _reg, _, factory = setup
        request = FactoryRequest(
            description="Oddiy yordamchi agent yaratilsin",
            auto_activate=True,
        )
        result = factory.create(request)

        assert result.success
        assert result.agent_state is not None
        assert result.agent_state.status == AgentStatus.ACTIVE

    def test_create_no_auto_activate(self, setup: tuple) -> None:
        """auto_activate=False — TESTING da qoladi."""
        _, _, factory = setup
        request = FactoryRequest(description="Test uchun yangi agent yaratilsin")
        result = factory.create(request)

        assert result.success
        assert result.agent_state is not None
        assert result.agent_state.status == AgentStatus.TESTING

    def test_duplicate_fails(self, setup: tuple) -> None:
        """Dublikat nom — xato."""
        _, _, factory = setup
        request = FactoryRequest(description="YouTube analitikasini kuzatadigan agent")
        factory.create(request)

        # Xuddi shu nomli agent yana yaratish
        result = factory.create(request)
        assert not result.success
        assert result.error is not None
        assert "allaqachon" in result.error

    def test_steps_recorded(self, setup: tuple) -> None:
        """Factory qadamlari qayd qilinadi."""
        _, _, factory = setup
        request = FactoryRequest(description="Yangi analitika agent yaratish kerak")
        result = factory.create(request)

        assert len(result.steps) >= 4
        assert any("UNDERSTAND" in s for s in result.steps)
        assert any("CHECK_EXISTING" in s for s in result.steps)
        assert any("DESIGN" in s for s in result.steps)
        assert any("EVAL" in s for s in result.steps)

    def test_factory_creates_prompt(self, setup: tuple) -> None:
        """Factory system prompt generatsiya qiladi."""
        _, _, factory = setup
        request = FactoryRequest(description="Bozorni tahlil qiluvchi analitika agenti yaratilsin")
        result = factory.create(request)

        assert result.success
        assert result.spec is not None
        assert len(result.spec.system_prompt) > 50
        assert "QOIDALAR" in result.spec.system_prompt

    def test_factory_selects_tools(self, setup: tuple) -> None:
        """Factory kerakli toollarni tanlaydi."""
        _, _, factory = setup
        request = FactoryRequest(description="Internet qidirish va tadqiqot agenti")
        result = factory.create(request)

        assert result.success
        assert result.spec is not None
        assert len(result.spec.tool_allowlist) > 0


# ── CEO va Operations agent testlari ─────────────────────────────


class TestCEOAgent:
    def test_spec_valid(self) -> None:
        """CEO agent spec to'g'ri."""
        assert CEO_AGENT_SPEC.name == "ceo"
        assert CEO_AGENT_SPEC.division == "ops"
        assert CEO_AGENT_SPEC.role == "manager"
        assert CEO_AGENT_SPEC.permission_level == PermissionLevel.READ
        assert CEO_AGENT_SPEC.trust_level == TrustLevel.SYSTEM

    def test_has_tools(self) -> None:
        """CEO agentda toollar bor."""
        assert "web.search" in CEO_AGENT_SPEC.tool_allowlist
        assert "time.now" in CEO_AGENT_SPEC.tool_allowlist

    def test_eval_passes(self) -> None:
        """CEO agent eval dan o'tadi."""
        result = EvalRunner().run_eval(CEO_AGENT_SPEC)
        assert result.success

    def test_prompt_has_briefing(self) -> None:
        """CEO prompt briefing formatini o'z ichiga oladi."""
        assert "Briefing" in CEO_AGENT_SPEC.system_prompt
        assert "QOIDALAR" in CEO_AGENT_SPEC.system_prompt


class TestOperationsAgent:
    def test_spec_valid(self) -> None:
        """Operations agent spec to'g'ri."""
        assert OPERATIONS_AGENT_SPEC.name == "operations"
        assert OPERATIONS_AGENT_SPEC.division == "ops"
        assert OPERATIONS_AGENT_SPEC.role == "analyst"
        assert OPERATIONS_AGENT_SPEC.permission_level == PermissionLevel.READ

    def test_has_tools(self) -> None:
        """Operations agentda toollar bor."""
        assert "web.search" in OPERATIONS_AGENT_SPEC.tool_allowlist
        assert "time.now" in OPERATIONS_AGENT_SPEC.tool_allowlist

    def test_eval_passes(self) -> None:
        """Operations agent eval dan o'tadi."""
        result = EvalRunner().run_eval(OPERATIONS_AGENT_SPEC)
        assert result.success

    def test_prompt_has_budget(self) -> None:
        """Operations prompt budjet kuzatuvini o'z ichiga oladi."""
        assert "Budjet" in OPERATIONS_AGENT_SPEC.system_prompt
        assert "$10" in OPERATIONS_AGENT_SPEC.system_prompt


# ── Factory API testlari ─────────────────────────────────────────


@pytest.fixture()
def api_registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture()
def api_client(api_registry: AgentRegistry) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_agent_registry] = lambda: api_registry
    app.dependency_overrides[get_killswitch] = KillSwitchState
    return TestClient(app, raise_server_exceptions=False)


class TestFactoryAPI:
    def test_factory_create(self, api_client: TestClient) -> None:
        """POST /agents/factory → 201."""
        resp = api_client.post(
            "/api/v1/agents/factory",
            json={"description": "YouTube analitikasini kuzatadigan agent"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"]
        assert data["agent"] is not None
        assert data["eval_result"] is not None
        assert data["eval_result"]["success"]
        assert len(data["steps"]) > 0

    def test_factory_auto_activate(self, api_client: TestClient) -> None:
        """Factory auto_activate=True."""
        resp = api_client.post(
            "/api/v1/agents/factory",
            json={
                "description": "Yangi tadqiqot agenti yaratilsin",
                "auto_activate": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"]
        assert data["agent"]["status"] == "active"

    def test_factory_duplicate(self, api_client: TestClient) -> None:
        """Dublikat → success=False."""
        api_client.post(
            "/api/v1/agents/factory",
            json={"description": "YouTube analitikasini kuzatadigan agent"},
        )
        resp = api_client.post(
            "/api/v1/agents/factory",
            json={"description": "YouTube analitikasini kuzatadigan agent"},
        )
        assert resp.status_code == 201  # HTTP 201 lekin success=False
        data = resp.json()
        assert not data["success"]
        assert data["error"] is not None

    def test_factory_short_description(self, api_client: TestClient) -> None:
        """Juda qisqa tavsif → 422."""
        resp = api_client.post(
            "/api/v1/agents/factory",
            json={"description": "ab"},
        )
        assert resp.status_code == 422


# ── Factory CLI testlari ─────────────────────────────────────────


@pytest.fixture()
def cli_registry() -> AgentRegistry:
    return AgentRegistry()


@pytest.fixture(autouse=True)
def _patch_cli_registry(cli_registry: AgentRegistry) -> object:
    with patch("zet.api.deps.get_agent_registry", return_value=cli_registry) as p:
        yield p


class TestFactoryCLI:
    def test_create_success(self, cli_registry: AgentRegistry) -> None:
        """z agent create — muvaffaqiyatli."""
        result = runner.invoke(
            cli_app,
            ["agent", "create", "YouTube analitikasini kuzatadigan agent"],
        )
        assert result.exit_code == 0
        assert "yaratildi" in result.output

    def test_create_auto_activate(self, cli_registry: AgentRegistry) -> None:
        """z agent create --auto-activate."""
        result = runner.invoke(
            cli_app,
            [
                "agent",
                "create",
                "Monitoring agenti yaratilsin",
                "--auto-activate",
            ],
        )
        assert result.exit_code == 0
        assert "yaratildi" in result.output

    def test_create_shows_steps(self, cli_registry: AgentRegistry) -> None:
        """Factory qadamlari ko'rsatiladi."""
        result = runner.invoke(
            cli_app,
            ["agent", "create", "Yangi analitika agent yaratish kerak"],
        )
        assert result.exit_code == 0
        assert "Qadamlar" in result.output
        assert "UNDERSTAND" in result.output
