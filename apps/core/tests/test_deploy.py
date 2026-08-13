"""Bo'lim 12 testlari — Production + Scale (Deploy, Schedule, Self-Improve, Agents).

Test guruhlari:
    1. Environment — enum qiymatlari
    2. DeployConfig — yaratish, defaults, properties, validation, frozen
    3. load_config — env o'zgaruvchilaridan yuklash
    4. validate_production_config — produksiya tekshiruvi
    5. ScheduleSlot — enum qiymatlari
    6. DailyTask — yaratish, maydonlar
    7. DailyScheduleManager — default jadval, get_task, list, stats
    8. ImprovementType — enum qiymatlari
    9. ImprovementSuggestion — yaratish, frozen
    10. SelfImproveEngine — suggest, approve, implement, pending, stats
    11. Yangi agentlar — HR, Security, Analytics
    12. Deploy __init__ exports
    13. Xavfsizlik invariantlari
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zet.agents.builtin import (
    ANALYTICS_AGENT_SPEC,
    HR_AGENT_SPEC,
    SECURITY_AGENT_SPEC,
)
from zet.deploy import (
    DailyScheduleManager,
    DailyTask,
    DeployConfig,
    Environment,
    ImprovementPriority,
    ImprovementSuggestion,
    ImprovementType,
    ScheduleSlot,
    SelfImproveEngine,
    load_config,
    validate_production_config,
)
from zet.domain.enums import PermissionLevel, TrustLevel

# ─── 1. Environment ─────────────────────────────────────────────


class TestEnvironment:
    """Environment enum testlari."""

    def test_dev(self) -> None:
        assert Environment.DEV == "dev"

    def test_staging(self) -> None:
        assert Environment.STAGING == "staging"

    def test_production(self) -> None:
        assert Environment.PRODUCTION == "production"

    def test_three_environments(self) -> None:
        assert len(Environment) == 3


# ─── 2. DeployConfig ────────────────────────────────────────────


class TestDeployConfig:
    """DeployConfig model testlari."""

    def test_defaults(self) -> None:
        c = DeployConfig()
        assert c.environment == Environment.DEV
        assert c.host == "127.0.0.1"
        assert c.port == 8000
        assert c.debug is False
        assert c.monthly_budget_usd == 10.0
        assert c.max_concurrent_runs == 3
        assert c.backup_enabled is False

    def test_is_production(self) -> None:
        c = DeployConfig(environment=Environment.PRODUCTION)
        assert c.is_production is True
        assert c.is_dev is False

    def test_is_dev(self) -> None:
        c = DeployConfig()
        assert c.is_dev is True
        assert c.is_production is False

    def test_custom_values(self) -> None:
        c = DeployConfig(
            environment=Environment.PRODUCTION,
            host="0.0.0.0",  # noqa: S104
            port=443,
            monthly_budget_usd=5.0,
            telegram_bot_token="bot:token",
            backup_enabled=True,
            caddy_enabled=True,
            caddy_domain="zet.example.com",
        )
        assert c.port == 443
        assert c.telegram_bot_token == "bot:token"
        assert c.caddy_domain == "zet.example.com"

    def test_port_validation(self) -> None:
        with pytest.raises(ValidationError):
            DeployConfig(port=0)
        with pytest.raises(ValidationError):
            DeployConfig(port=70000)

    def test_budget_validation(self) -> None:
        with pytest.raises(ValidationError):
            DeployConfig(monthly_budget_usd=-1)

    def test_frozen(self) -> None:
        c = DeployConfig()
        with pytest.raises(ValidationError):
            c.port = 9000  # type: ignore[misc]


# ─── 3. load_config ─────────────────────────────────────────────


class TestLoadConfig:
    """load_config testlari."""

    def test_default_load(self) -> None:
        # Hech qanday env o'zgaruvchi yo'q
        config = load_config()
        assert config.environment == Environment.DEV
        assert config.host == "127.0.0.1"

    def test_load_with_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_HOST", "0.0.0.0")  # noqa: S104
        monkeypatch.setenv("ZET_PORT", "9090")
        monkeypatch.setenv("ZET_DEBUG", "true")
        config = load_config()
        assert config.host == "0.0.0.0"  # noqa: S104
        assert config.port == 9090
        assert config.debug is True

    def test_load_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ZET_ENV", "production")
        config = load_config()
        assert config.environment == Environment.PRODUCTION


# ─── 4. validate_production_config ───────────────────────────────


class TestValidateProductionConfig:
    """validate_production_config testlari."""

    def test_dev_no_errors(self) -> None:
        c = DeployConfig()
        errors = validate_production_config(c)
        assert errors == []

    def test_production_missing_token(self) -> None:
        c = DeployConfig(environment=Environment.PRODUCTION)
        errors = validate_production_config(c)
        assert any("TELEGRAM_BOT_TOKEN" in e for e in errors)

    def test_production_debug_on(self) -> None:
        c = DeployConfig(
            environment=Environment.PRODUCTION,
            debug=True,
            telegram_bot_token="bot:token",
            backup_enabled=True,
        )
        errors = validate_production_config(c)
        assert any("DEBUG" in e for e in errors)

    def test_production_no_backup(self) -> None:
        c = DeployConfig(
            environment=Environment.PRODUCTION,
            telegram_bot_token="bot:token",
        )
        errors = validate_production_config(c)
        assert any("backup" in e for e in errors)

    def test_production_valid(self) -> None:
        c = DeployConfig(
            environment=Environment.PRODUCTION,
            telegram_bot_token="bot:token",
            backup_enabled=True,
        )
        errors = validate_production_config(c)
        assert errors == []


# ─── 5. ScheduleSlot ────────────────────────────────────────────


class TestScheduleSlot:
    """ScheduleSlot enum testlari."""

    def test_values(self) -> None:
        assert ScheduleSlot.MORNING_BRIEF == "08:00"
        assert ScheduleSlot.BUSINESS_CHECK == "09:00"
        assert ScheduleSlot.SMM_CHECK == "12:00"
        assert ScheduleSlot.TASK_REPORT == "18:00"
        assert ScheduleSlot.DAILY_SUMMARY == "21:00"

    def test_five_slots(self) -> None:
        assert len(ScheduleSlot) == 5


# ─── 6. DailyTask ───────────────────────────────────────────────


class TestDailyTask:
    """DailyTask model testlari."""

    def test_create(self) -> None:
        t = DailyTask(
            slot=ScheduleSlot.MORNING_BRIEF,
            agent_name="ceo",
            command="Brifing",
        )
        assert t.slot == ScheduleSlot.MORNING_BRIEF
        assert t.agent_name == "ceo"
        assert t.enabled is True

    def test_frozen(self) -> None:
        t = DailyTask(
            slot=ScheduleSlot.MORNING_BRIEF,
            agent_name="ceo",
            command="test",
        )
        with pytest.raises(AttributeError):
            t.agent_name = "changed"  # type: ignore[misc]


# ─── 7. DailyScheduleManager ────────────────────────────────────


class TestDailyScheduleManager:
    """DailyScheduleManager testlari."""

    def test_default_schedule(self) -> None:
        dsm = DailyScheduleManager()
        assert len(dsm.list_all()) == 5

    def test_get_task(self) -> None:
        dsm = DailyScheduleManager()
        task = dsm.get_task(ScheduleSlot.MORNING_BRIEF)
        assert task is not None
        assert task.agent_name == "ceo"

    def test_get_task_missing(self) -> None:
        dsm = DailyScheduleManager(tasks=[])
        assert dsm.get_task(ScheduleSlot.MORNING_BRIEF) is None

    def test_list_enabled(self) -> None:
        dsm = DailyScheduleManager()
        enabled = dsm.list_enabled()
        assert len(enabled) == 5  # All default tasks enabled

    def test_stats(self) -> None:
        dsm = DailyScheduleManager()
        s = dsm.stats
        assert s["total"] == 5
        assert s["enabled"] == 5
        assert s["disabled"] == 0

    def test_default_agents(self) -> None:
        """Default jadvalda to'g'ri agentlar borligini tekshirish."""
        dsm = DailyScheduleManager()
        agents = {t.agent_name for t in dsm.list_all()}
        assert "ceo" in agents
        assert "operations" in agents
        assert "smm" in agents

    def test_default_cron_exprs(self) -> None:
        """Default jadvalda cron ifodalar borligini tekshirish."""
        dsm = DailyScheduleManager()
        for task in dsm.list_all():
            assert task.cron_expr != ""


# ─── 8. ImprovementType ─────────────────────────────────────────


class TestImprovementType:
    """ImprovementType enum testlari."""

    def test_seven_types(self) -> None:
        assert len(ImprovementType) == 7

    def test_values(self) -> None:
        assert ImprovementType.NEW_AGENT == "new_agent"
        assert ImprovementType.COST_OPTIMIZATION == "cost_optimization"
        assert ImprovementType.BUG_FIX == "bug_fix"


# ─── 9. ImprovementSuggestion ───────────────────────────────────


class TestImprovementSuggestion:
    """ImprovementSuggestion model testlari."""

    def test_create(self) -> None:
        s = ImprovementSuggestion(
            improvement_type=ImprovementType.COST_OPTIMIZATION,
            title="Model tier ni kamaytirish",
        )
        assert s.improvement_type == ImprovementType.COST_OPTIMIZATION
        assert s.approved is False
        assert s.implemented is False
        assert len(s.id) == 12

    def test_frozen(self) -> None:
        s = ImprovementSuggestion(
            improvement_type=ImprovementType.NEW_AGENT,
            title="Test",
        )
        with pytest.raises(ValidationError):
            s.title = "changed"  # type: ignore[misc]


# ─── 10. SelfImproveEngine ──────────────────────────────────────


class TestSelfImproveEngine:
    """SelfImproveEngine testlari."""

    def test_suggest(self) -> None:
        engine = SelfImproveEngine()
        s = engine.suggest(
            improvement_type=ImprovementType.NEW_TOOL,
            title="OCR tool qo'shish",
            description="Rasmlardan matn o'qish imkoniyati",
            priority=ImprovementPriority.MEDIUM,
            estimated_impact="Yangi vazifalar bajarish",
        )
        assert s.title == "OCR tool qo'shish"
        assert engine.stats["total"] == 1

    def test_pending(self) -> None:
        engine = SelfImproveEngine()
        engine.suggest(
            improvement_type=ImprovementType.BUG_FIX,
            title="Timeout xatosini tuzatish",
        )
        pending = engine.pending()
        assert len(pending) == 1

    def test_approve(self) -> None:
        engine = SelfImproveEngine()
        s = engine.suggest(
            improvement_type=ImprovementType.BETTER_PROCESS,
            title="Workflow optimallashtirish",
        )
        assert engine.approve(s.id) is True
        approved = engine.approved_list()
        assert len(approved) == 1
        assert engine.pending() == []

    def test_approve_missing(self) -> None:
        engine = SelfImproveEngine()
        assert engine.approve("nope") is False

    def test_mark_implemented(self) -> None:
        engine = SelfImproveEngine()
        s = engine.suggest(
            improvement_type=ImprovementType.NEW_AGENT,
            title="Design agent",
        )
        engine.approve(s.id)
        assert engine.mark_implemented(s.id) is True
        assert engine.approved_list() == []
        assert engine.stats["implemented"] == 1

    def test_mark_implemented_missing(self) -> None:
        engine = SelfImproveEngine()
        assert engine.mark_implemented("nope") is False

    def test_all_suggestions(self) -> None:
        engine = SelfImproveEngine()
        engine.suggest(improvement_type=ImprovementType.NEW_TOOL, title="A")
        engine.suggest(improvement_type=ImprovementType.BUG_FIX, title="B")
        assert len(engine.all_suggestions()) == 2

    def test_stats(self) -> None:
        engine = SelfImproveEngine()
        s1 = engine.suggest(improvement_type=ImprovementType.NEW_TOOL, title="A")
        s2 = engine.suggest(improvement_type=ImprovementType.BUG_FIX, title="B")
        engine.suggest(improvement_type=ImprovementType.COST_OPTIMIZATION, title="C")
        engine.approve(s1.id)
        engine.mark_implemented(s2.id)
        s = engine.stats
        assert s["total"] == 3
        assert s["pending"] == 1
        assert s["approved"] == 1
        assert s["implemented"] == 1


# ─── 11. Yangi agentlar ─────────────────────────────────────────


class TestNewAgents:
    """Bo'lim 12 — yangi agentlar testlari."""

    def test_hr_agent_spec(self) -> None:
        assert HR_AGENT_SPEC.name == "hr"
        assert HR_AGENT_SPEC.division == "operations"
        # Yangi versiya — HR AI workforce manager, EXECUTE ruxsat
        # (agent.pause/resume/disable EXECUTE toollari).
        assert HR_AGENT_SPEC.permission_level == PermissionLevel.EXECUTE
        assert HR_AGENT_SPEC.trust_level == TrustLevel.SYSTEM

    def test_security_agent_spec(self) -> None:
        assert SECURITY_AGENT_SPEC.name == "security"
        assert SECURITY_AGENT_SPEC.division == "security"
        assert SECURITY_AGENT_SPEC.permission_level == PermissionLevel.READ
        assert SECURITY_AGENT_SPEC.trust_level == TrustLevel.SYSTEM

    def test_analytics_agent_spec(self) -> None:
        assert ANALYTICS_AGENT_SPEC.name == "analytics"
        assert ANALYTICS_AGENT_SPEC.division == "analytics"
        assert ANALYTICS_AGENT_SPEC.permission_level == PermissionLevel.READ
        assert ANALYTICS_AGENT_SPEC.trust_level == TrustLevel.SYSTEM

    def test_new_analytics_and_security_read_only(self) -> None:
        """Security va Analytics faqat READ; HR endi EXECUTE (workforce boshqaruvi)."""
        for spec in [SECURITY_AGENT_SPEC, ANALYTICS_AGENT_SPEC]:
            assert spec.permission_level == PermissionLevel.READ

    def test_all_new_agents_system_trust(self) -> None:
        """Yangi agentlar SYSTEM trust darajasida."""
        for spec in [HR_AGENT_SPEC, SECURITY_AGENT_SPEC, ANALYTICS_AGENT_SPEC]:
            assert spec.trust_level == TrustLevel.SYSTEM

    def test_total_agents_count(self) -> None:
        """Phase D'da QA va E-commerce qo'shildi — jami 14."""
        from zet.agents.builtin import __all__

        assert len(__all__) == 14

    def test_unique_agent_names(self) -> None:
        """Barcha agent nomlari unikal."""
        import zet.agents.builtin as mod
        from zet.agents.builtin import __all__ as all_specs

        names = [getattr(mod, name).name for name in all_specs]
        assert len(names) == len(set(names))


# ─── 12. Deploy __init__ exports ────────────────────────────────


class TestDeployExports:
    """Deploy moduli exports testlari."""

    def test_all_exports(self) -> None:
        import zet.deploy as mod

        expected = {
            "DailyScheduleManager",
            "DailyTask",
            "DeployConfig",
            "Environment",
            "ImprovementPriority",
            "ImprovementSuggestion",
            "ImprovementType",
            "ScheduleSlot",
            "SelfImproveEngine",
            "load_config",
            "validate_production_config",
        }
        assert set(mod.__all__) == expected


# ─── 13. Xavfsizlik invariantlari ───────────────────────────────


class TestDeploySecurityInvariants:
    """Xavfsizlik invariantlari — Bo'lim 12."""

    def test_deploy_config_frozen(self) -> None:
        """DeployConfig o'zgartirib bo'lmaydi."""
        c = DeployConfig()
        with pytest.raises(ValidationError):
            c.port = 9000  # type: ignore[misc]

    def test_improvement_suggestion_frozen(self) -> None:
        """ImprovementSuggestion o'zgartirib bo'lmaydi."""
        s = ImprovementSuggestion(
            improvement_type=ImprovementType.NEW_AGENT,
            title="Test",
        )
        with pytest.raises(ValidationError):
            s.approved = True  # type: ignore[misc]

    def test_selfimprove_no_auto_implement(self) -> None:
        """SelfImproveEngine faqat TAVSIYA qiladi — avtomatik amalga oshirmaydi."""
        engine = SelfImproveEngine()
        s = engine.suggest(
            improvement_type=ImprovementType.NEW_AGENT,
            title="Auto agent",
        )
        # Tavsiya yaratildi, lekin implemented=False
        assert s.implemented is False
        assert s.approved is False

    def test_default_config_localhost(self) -> None:
        """Default konfiguratsiya 127.0.0.1 (localhost) da tinglaydi."""
        c = DeployConfig()
        assert c.host == "127.0.0.1"

    def test_production_requires_backup(self) -> None:
        """Produksiyada backup majburiy."""
        c = DeployConfig(
            environment=Environment.PRODUCTION,
            telegram_bot_token="bot:token",
            backup_enabled=False,
        )
        errors = validate_production_config(c)
        assert any("backup" in e for e in errors)

    def test_new_agents_have_brakes(self) -> None:
        """Yangi agentlarda tormozlar bor (max_steps, timeout)."""
        for spec in [HR_AGENT_SPEC, SECURITY_AGENT_SPEC, ANALYTICS_AGENT_SPEC]:
            assert spec.max_steps > 0
            assert spec.timeout_s > 0
            assert spec.max_tool_calls > 0

    def test_new_agents_have_system_prompts(self) -> None:
        """Yangi agentlarda system prompt bor."""
        for spec in [HR_AGENT_SPEC, SECURITY_AGENT_SPEC, ANALYTICS_AGENT_SPEC]:
            assert spec.system_prompt
            assert len(spec.system_prompt) > 50
