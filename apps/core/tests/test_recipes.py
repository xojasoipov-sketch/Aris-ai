"""6 TIZIM retsepti testlari (yangi zip).

Eng muhim invariant — HALOLLIK. Imkoniyati yetishmagan retsept hech
qachon "ready" ko'rsatilmasligi va o'rnatilmasligi kerak. Aks holda ega
uchrashuv qo'yilgan deb o'ylab, kalendarni tekshirmay qolardi.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.automation.engine import AutomationEngine
from zet.automation.recipes import (
    RECIPES,
    Capability,
    RecipeNotReadyError,
    RecipeStatus,
    TriggerKind,
    detect_capabilities,
    evaluate,
    evaluate_all,
    get_recipe,
    install,
)
from zet.automation.scheduler import validate_cron
from zet.config import Settings
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry

ALL_CAPABILITIES = frozenset(Capability)


@pytest.fixture()
def tool_registry(tmp_path: Path) -> ToolRegistry:
    return build_default_registry(notes_dir=tmp_path)


def _settings(**kwargs: object) -> Settings:
    """Test Settings — kalitlar ANIQ bo'shatiladi (`.env` ta'siri yo'q)."""
    base: dict[str, object] = {
        "anthropic_api_key": None,
        "google_api_key": None,
        "groq_api_key": None,
        "mistral_api_key": None,
        "openrouter_api_key": None,
        "openai_api_key": None,
        "telegram_bot_token": None,
    }
    base.update(kwargs)
    return Settings.model_validate(base)


class TestRecipeCatalogue:
    """Katalog slayd bilan mos."""

    def test_exactly_six_recipes(self) -> None:
        assert len(RECIPES) == 6

    def test_codes_are_t01_to_t06(self) -> None:
        assert [r.code for r in RECIPES] == ["T01", "T02", "T03", "T04", "T05", "T06"]

    def test_every_recipe_has_three_steps(self) -> None:
        """Slaydda har retsept aynan uch qadam."""
        for recipe in RECIPES:
            assert len(recipe.steps) == 3, recipe.code

    def test_steps_are_ordered(self) -> None:
        for recipe in RECIPES:
            assert [s.order for s in recipe.steps] == [1, 2, 3], recipe.code

    def test_every_recipe_states_a_result(self) -> None:
        for recipe in RECIPES:
            assert recipe.result, recipe.code
            assert recipe.promise, recipe.code

    def test_time_recipes_have_valid_cron(self) -> None:
        """TIME retsepti cron ifodasi haqiqatan yaroqli bo'lsin."""
        for recipe in RECIPES:
            if recipe.trigger_kind == TriggerKind.TIME:
                assert validate_cron(recipe.trigger_spec), recipe.code

    def test_get_recipe_by_code(self) -> None:
        assert get_recipe("T01") is not None
        assert get_recipe("t01") is not None
        assert get_recipe("T99") is None

    def test_required_is_union_of_step_needs(self) -> None:
        for recipe in RECIPES:
            expected: set[Capability] = set()
            for step in recipe.steps:
                expected |= step.needs
            assert recipe.required == expected, recipe.code


class TestCapabilityDetection:
    """Nimalar HAQIQATAN mavjud."""

    def test_cron_and_crm_always_available(self) -> None:
        available = detect_capabilities(_settings())
        assert Capability.CRON in available
        assert Capability.CRM in available

    def test_llm_requires_a_provider_key(self) -> None:
        assert Capability.LLM not in detect_capabilities(_settings(ollama_base_url=""))
        assert Capability.LLM in detect_capabilities(_settings(anthropic_api_key="k"))

    def test_telegram_send_requires_bot_token(self) -> None:
        assert Capability.TELEGRAM_SEND not in detect_capabilities(_settings())
        assert Capability.TELEGRAM_SEND in detect_capabilities(_settings(telegram_bot_token="t"))

    def test_content_publish_detected_from_tools(self, tool_registry: ToolRegistry) -> None:
        available = detect_capabilities(_settings(), tool_registry)
        assert Capability.CONTENT_PUBLISH in available

    def test_missing_integrations_are_not_claimed(self, tool_registry: ToolRegistry) -> None:
        """Hali qurilmagan imkoniyatlar "bor" deb ko'rsatilmaydi."""
        available = detect_capabilities(
            _settings(anthropic_api_key="k", telegram_bot_token="t"), tool_registry
        )
        for capability in (
            Capability.CALENDAR,
            Capability.MEETING_LINK,
            Capability.STT,
            Capability.TASK_BOARD,
            Capability.TIMED_APPROVAL,
            Capability.TELEGRAM_READ_GROUPS,
            Capability.INSTAGRAM_WEBHOOK,
        ):
            assert capability not in available, capability


class TestEvaluate:
    """Tayyorlik hisoboti."""

    def test_all_ready_when_everything_available(self) -> None:
        for readiness in evaluate_all(ALL_CAPABILITIES):
            assert readiness.status == RecipeStatus.READY
            assert readiness.missing == []
            assert readiness.blocked_steps == []

    def test_nothing_ready_with_no_capabilities(self) -> None:
        for readiness in evaluate_all(frozenset()):
            assert readiness.status == RecipeStatus.MISSING_CAPABILITY
            assert readiness.missing

    def test_missing_capability_is_named(self) -> None:
        """Ega aynan NIMA yetishmayotganini ko'radi."""
        recipe = get_recipe("T01")
        assert recipe is not None
        readiness = evaluate(recipe, frozenset({Capability.LLM}))

        assert Capability.CALENDAR in readiness.missing
        assert Capability.MEETING_LINK in readiness.missing

    def test_blocked_steps_are_identified(self) -> None:
        """Qaysi qadam ishlamasligi aniq ko'rsatiladi."""
        recipe = get_recipe("T01")
        assert recipe is not None
        readiness = evaluate(recipe, frozenset({Capability.LLM}))

        assert readiness.blocked_steps == [2, 3]
        assert 1 not in readiness.blocked_steps

    def test_partial_capability_still_not_ready(self) -> None:
        """Uchtadan ikkitasi bo'lsa ham — tayyor emas."""
        recipe = get_recipe("T02")
        assert recipe is not None
        readiness = evaluate(recipe, frozenset({Capability.LLM, Capability.STT}))
        assert readiness.status == RecipeStatus.MISSING_CAPABILITY


class TestHonestyWithRealConfig:
    """Hozirgi HAQIQIY ZET holatida nima ishlaydi."""

    def test_calendar_recipes_are_honestly_blocked(self, tool_registry: ToolRegistry) -> None:
        """T01/T02/T05 kalendar yo'qligi uchun tayyor emas — va shuni aytadi."""
        available = detect_capabilities(
            _settings(anthropic_api_key="k", telegram_bot_token="t"), tool_registry
        )
        for code in ("T01", "T02", "T05"):
            recipe = get_recipe(code)
            assert recipe is not None
            readiness = evaluate(recipe, available)
            assert readiness.status == RecipeStatus.MISSING_CAPABILITY, code
            assert Capability.CALENDAR in readiness.missing, code

    def test_group_recipe_blocked_on_mtproto(self, tool_registry: ToolRegistry) -> None:
        """T03 — Bot API guruh tarixini bermaydi."""
        available = detect_capabilities(
            _settings(anthropic_api_key="k", telegram_bot_token="t"), tool_registry
        )
        recipe = get_recipe("T03")
        assert recipe is not None
        assert Capability.TELEGRAM_READ_GROUPS in evaluate(recipe, available).missing


class TestInstall:
    """O'rnatish — faqat tayyor retseptni."""

    def test_time_recipe_creates_a_schedule(self) -> None:
        engine = AutomationEngine()
        recipe = get_recipe("T06")
        assert recipe is not None

        rule_id = install(recipe, engine, ALL_CAPABILITIES)

        rules = engine.scheduler.list_rules()
        assert len(rules) == 1
        assert rules[0].id == rule_id
        assert rules[0].cron_expr == recipe.trigger_spec

    def test_event_recipe_creates_a_trigger(self) -> None:
        engine = AutomationEngine()
        recipe = get_recipe("T01")
        assert recipe is not None

        trigger_id = install(recipe, engine, ALL_CAPABILITIES)

        triggers = engine.triggers.list_triggers()
        assert len(triggers) == 1
        assert triggers[0].id == trigger_id

    def test_installed_command_lists_the_steps(self) -> None:
        engine = AutomationEngine()
        recipe = get_recipe("T06")
        assert recipe is not None

        install(recipe, engine, ALL_CAPABILITIES)

        command = engine.scheduler.list_rules()[0].command
        for step in recipe.steps:
            assert step.title in command
        assert recipe.result in command

    def test_not_ready_recipe_is_refused(self) -> None:
        """Chala retsept o'rnatilmaydi — jimgina yarim ishlamaydi."""
        engine = AutomationEngine()
        recipe = get_recipe("T01")
        assert recipe is not None

        with pytest.raises(RecipeNotReadyError) as exc:
            install(recipe, engine, frozenset({Capability.LLM}))

        assert Capability.CALENDAR.value in str(exc.value)
        assert engine.triggers.list_triggers() == []
        assert engine.scheduler.list_rules() == []

    def test_lead_agent_is_first_step_agent(self) -> None:
        engine = AutomationEngine()
        recipe = get_recipe("T04")
        assert recipe is not None

        install(recipe, engine, ALL_CAPABILITIES)

        assert engine.scheduler.list_rules()[0].agent_name == recipe.steps[0].agent_name
