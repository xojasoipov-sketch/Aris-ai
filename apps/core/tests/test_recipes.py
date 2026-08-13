"""6 TIZIM retsepti testlari (yangi zip).

Eng muhim invariant — HALOLLIK. Imkoniyati yetishmagan retsept hech
qachon "ready" ko'rsatilmasligi va o'rnatilmasligi kerak. Aks holda ega
uchrashuv qo'yilgan deb o'ylab, kalendarni tekshirmay qolardi.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        "cohere_api_key": None,
        "cerebras_api_key": None,
        "deepseek_api_key": None,
        "kimi_api_key": None,
        "telegram_bot_token": None,
        # STT endi kalitga bog'liq (`ElevenLabsSTT`) — bo'shatilmasa
        # mashinadagi `.env` testni "imkoniyat bor" tomonga og'dirardi.
        "elevenlabs_api_key": None,
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
            Capability.MEETING_LINK,
            Capability.TELEGRAM_READ_GROUPS,
            Capability.INSTAGRAM_WEBHOOK,
        ):
            assert capability not in available, capability

    def test_timed_approval_capability_no_longer_exists(self) -> None:
        """B2 (KONSOLIDATSIYA v2, tungi reja): "sukut = rozilik" taymerli
        tasdiq V-32'ga zid edi — konsepsiya BUTUNLAY olib tashlangan
        (nafaqat "hali yo'q" ro'yxatida, umuman enum'da yo'q)."""
        assert "TIMED_APPROVAL" not in Capability.__members__
        assert "approval.timed" not in {c.value for c in Capability}

    def test_stt_requires_elevenlabs_key(self) -> None:
        """Kalitsiz `StubSTT` qotgan matn qaytaradi — bu imkoniyat emas."""
        assert Capability.STT not in detect_capabilities(_settings())
        assert Capability.STT in detect_capabilities(_settings(elevenlabs_api_key="k"))

    def test_board_needs_tools_wired_to_the_database(self, tmp_path: Path) -> None:
        """Tool ro'yxatda TURISHI yetarli emas — u ulangan bo'lishi kerak.

        `task.*`/`calendar.*` tool'lari DB fabrikasisiz ham ro'yxatga
        tushadi (Planner ularni ko'rib tursin), lekin chaqirilganda
        yiqiladi. O'sha holatda imkoniyatni "bor" deb sanash retseptni
        chala ishlaydigan qilib o'rnatardi.
        """
        unwired = detect_capabilities(_settings(), build_default_registry(notes_dir=tmp_path))
        assert Capability.TASK_BOARD not in unwired
        assert Capability.CALENDAR not in unwired

        @asynccontextmanager
        async def _scope() -> AsyncIterator[None]:
            yield None

        wired = detect_capabilities(
            _settings(),
            build_default_registry(notes_dir=tmp_path, workspace_scope=_scope),
        )
        assert Capability.TASK_BOARD in wired
        assert Capability.CALENDAR in wired


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

    def test_t04_no_longer_needs_a_new_capability(self, tool_registry: ToolRegistry) -> None:
        """B2 (KONSOLIDATSIYA v2, tungi reja): T04 ilgari HECH QACHON
        qurilmaydigan `TIMED_APPROVAL`ga muhtoj bo'lgani uchun DOIM
        bloklangan edi. Endi faqat allaqachon aniqlanadigan `content.
        publish`ga muhtoj — real sozlamada (Telegram bot ulangan) READY
        bo'ladi, ApprovalService orqali (aniq tasdiq, sukut emas)."""
        available = detect_capabilities(
            _settings(anthropic_api_key="k", telegram_bot_token="t"), tool_registry
        )
        recipe = get_recipe("T04")
        assert recipe is not None
        readiness = evaluate(recipe, available)
        assert readiness.status == RecipeStatus.READY, readiness.missing


class TestSequentialStepBlocking:
    """B4 (KONSOLIDATSIYA v2, tungi reja): qadamlar bitta ketma-ket
    agent chaqiruvida bajariladi (`_command_for()`) — alohida bajarish
    mexanizmi YO'Q. Shuning uchun N-qadam o'z ehtiyojini qondirsa ham,
    undan OLDINGI biror qadam bloklangan bo'lsa, N-qadamga navbat
    UMUMAN yetmaydi."""

    def test_downstream_steps_blocked_when_earlier_step_blocked(self) -> None:
        """T05: 1-qadam (INSTAGRAM_WEBHOOK, hali yo'q) bloklansa, 2/3
        -qadam O'Z ehtiyojini (LLM/CRM/CALENDAR) qondirsa ham blocked
        sifatida ko'rsatiladi — interfeys ularni "ishlaydi" deb
        yolg'on ko'rsatmasin."""
        recipe = get_recipe("T05")
        assert recipe is not None
        available = frozenset({Capability.LLM, Capability.CRM, Capability.CALENDAR, Capability.CRON})
        readiness = evaluate(recipe, available)
        assert readiness.blocked_steps == [1, 2, 3]

    def test_earlier_unblocked_step_stays_unblocked(self) -> None:
        """T01: 1-qadam (faqat LLM) hech qachon 2/3 tufayli bloklanmasin
        — propagatsiya faqat OLDINGA, ortga emas."""
        recipe = get_recipe("T01")
        assert recipe is not None
        readiness = evaluate(recipe, frozenset({Capability.LLM}))
        assert 1 not in readiness.blocked_steps
        assert readiness.blocked_steps == [2, 3]

    def test_no_capability_missing_means_nothing_blocked(self) -> None:
        for recipe in RECIPES:
            readiness = evaluate(recipe, ALL_CAPABILITIES)
            assert readiness.blocked_steps == [], recipe.code


class TestInstall:
    """O'rnatish — faqat tayyor retseptni."""

    def test_time_recipe_creates_a_schedule(self) -> None:
        engine = AutomationEngine()
        recipe = get_recipe("T06")
        assert recipe is not None

        rule_id = install(recipe, engine, ALL_CAPABILITIES)

        rules = engine.scheduler.list_rules()
        assert rules[0].id == rule_id
        assert rules[0].cron_expr == recipe.trigger_spec

    def test_daily_pulse_runs_morning_and_evening(self) -> None:
        """Slayd: "Ertalab 09:20 va kechqurun 18:40".

        Bitta cron ifodasi ikkala vaqtni bera olmaydi (daqiqalar har
        xil), shuning uchun har biri alohida qoida bo'lishi kerak —
        aks holda kechki puls umuman ishlamasdi."""
        engine = AutomationEngine()
        recipe = get_recipe("T06")
        assert recipe is not None

        install(recipe, engine, ALL_CAPABILITIES)

        crons = {rule.cron_expr for rule in engine.scheduler.list_rules()}
        assert crons == {"20 9 * * *", "40 18 * * *"}

    def test_every_recipe_cron_is_valid(self) -> None:
        """`also_at` ham cron tekshiruvidan o'tadi."""
        for recipe in RECIPES:
            if recipe.trigger_kind is not TriggerKind.TIME:
                continue
            for cron_expr in (recipe.trigger_spec, *recipe.also_at):
                validate_cron(cron_expr)

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
