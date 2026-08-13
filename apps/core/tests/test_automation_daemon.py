"""AutomationDaemon testlari — Bo'lim 9 Scheduler'ni haqiqiy bajarish.

Ilgari `Scheduler` faqat ma'lumot modeli edi — hech qanday event loop
uni ishga tushirmasdi. Bu testlar `tick()` orqali real fire mantiqini
tekshiradi (loop kutmasdan).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationEngine
from zet.automation.scheduler import ScheduleRule
from zet.core.state import CoreState
from zet.deploy.automation_daemon import AutomationDaemon
from zet.domain.enums import AgentStatus
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import StubNotifier
from zet.tools.builtin import build_default_registry


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 12, hh, mm, 0, tzinfo=UTC)  # 2026-08-12 — chorshanba


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def automation_engine() -> AutomationEngine:
    e = AutomationEngine()
    e.add_schedule(
        ScheduleRule(
            name="Kunlik hisobot",
            agent_name="ceo",
            cron_expr="0 9 * * *",
            command="Hisobot tayyorla",
        )
    )
    return e


@pytest.fixture()
def daemon(
    automation_engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
) -> AutomationDaemon:
    return AutomationDaemon(
        engine=automation_engine,
        agent_registry=agent_registry,
        tool_registry=build_default_registry(notes_dir=tmp_path),
        permission_policy=PermissionPolicy(),
        core_state=CoreState(),
        killswitch=KillSwitchState(),
        timezone="UTC",
    )


class TestTick:
    async def test_fires_at_matching_time(
        self, daemon: AutomationDaemon, automation_engine: AutomationEngine
    ) -> None:
        fired = await daemon.tick(now=_at(9, 0))
        assert len(fired) == 1

        rule = automation_engine.scheduler.list_rules()[0]
        assert rule.run_count == 1
        assert rule.last_run_at is not None

    async def test_no_fire_outside_window(self, daemon: AutomationDaemon) -> None:
        fired = await daemon.tick(now=_at(9, 1))
        assert fired == []

    async def test_no_double_fire_same_minute(self, daemon: AutomationDaemon) -> None:
        first = await daemon.tick(now=_at(9, 0))
        second = await daemon.tick(now=_at(9, 0))
        assert len(first) == 1
        assert second == []

    async def test_fires_again_next_day(self, daemon: AutomationDaemon) -> None:
        await daemon.tick(now=_at(9, 0))
        tomorrow = datetime(2026, 8, 13, 9, 0, 0, tzinfo=UTC)
        fired = await daemon.tick(now=tomorrow)
        assert len(fired) == 1

    async def test_skipped_while_sleeping(
        self, automation_engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        state = CoreState()
        state.sleep(reason="Test")
        d = AutomationDaemon(
            engine=automation_engine,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=state,
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(9, 0))
        assert fired == []

    async def test_skipped_while_killswitch_engaged(
        self, automation_engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="Test")
        d = AutomationDaemon(
            engine=automation_engine,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=ks,
            timezone="UTC",
        )
        fired = await d.tick(now=_at(9, 0))
        assert fired == []

    async def test_paused_schedule_skipped(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        e = AutomationEngine()
        rule = e.add_schedule(
            ScheduleRule(name="X", agent_name="ceo", cron_expr="0 9 * * *", command="x")
        )
        e.scheduler.pause_rule(rule.id)
        d = AutomationDaemon(
            engine=e,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(9, 0))
        assert fired == []

    async def test_agent_not_active_skipped_gracefully(self, tmp_path: Path) -> None:
        e = AutomationEngine()
        e.add_schedule(
            ScheduleRule(name="X", agent_name="nonexistent", cron_expr="0 9 * * *", command="x")
        )
        d = AutomationDaemon(
            engine=e,
            agent_registry=AgentRegistry(),
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(9, 0))
        # Xato ko'tarilmaydi — faqat log, ro'yxatda ham qolmaydi (ishga tushmadi)
        assert fired == [e.scheduler.list_rules()[0].id]


class TestDelivery:
    """Natija EGAGA yetib borishi kerak (Z48.5).

    NEGA BU TESTLAR BOR. Daemon agentni ishga tushirar, natijani esa
    faqat LOG'ga yozardi. Ya'ni T06 "Kunlik puls" har kuni 09:20 va
    18:40 da ishlab, hech kimga hech narsa AYTMASDI — slaydda esa
    va'da aniq: "Uch qatorli xabar: siljidi / qotdi / sizdan qaror
    kutmoqda".

    Ega ko'rmaydigan joyga tushgan avtomatlashtirish natijasi
    avtomatlashtirish emas — shunchaki sarflangan token.
    """

    def _daemon(self, engine, registry, tmp_path, notifier):
        return AutomationDaemon(
            engine=engine,
            agent_registry=registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
            notifier=notifier,
        )

    async def test_fired_rule_reaches_the_owner(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        notifier = StubNotifier()

        await self._daemon(automation_engine, agent_registry, tmp_path, notifier).tick(
            now=_at(9, 0)
        )

        assert notifier.sent, "qoida ishga tushdi, lekin ega hech narsa olmadi"

    async def test_message_names_the_rule(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """Ega qaysi avtomatlashtirish yozganini bilishi kerak.

        Kuniga bir nechta retsept ishlaganda, nomsiz matn qayerdan
        kelganini aytmaydi."""
        notifier = StubNotifier()

        await self._daemon(automation_engine, agent_registry, tmp_path, notifier).tick(
            now=_at(9, 0)
        )

        assert "Kunlik hisobot" in notifier.sent[0].text

    async def test_no_notifier_is_not_an_error(self, daemon: AutomationDaemon) -> None:
        """Bildirishnoma ulanmagan bo'lsa ham qoida ishlayveradi."""
        fired = await daemon.tick(now=_at(9, 0))

        assert fired


class TestStop:
    async def test_stop_ends_run_forever(self, daemon: AutomationDaemon) -> None:
        import asyncio

        task = asyncio.create_task(daemon.run_forever())
        await asyncio.sleep(0)
        daemon.stop()
        await asyncio.wait_for(task, timeout=5)
        assert task.done()


class TestRealProviderWiring:
    """`session_factory`/`llm_providers`/`settings` berilsa — real `ModelRouter`
    orqali (`RoutedLLMProvider`, `is_autonomous=True`) ishga tushiriladi."""

    async def test_fire_uses_routed_provider(
        self,
        agent_registry: AgentRegistry,
        tmp_path: Path,
        session_factory,
    ) -> None:
        from zet.config import Settings
        from zet.domain.enums import ModelTier
        from zet.llm.fake import FakeProvider

        fake_google = FakeProvider(name="google", tier=ModelTier.T1_FREE)
        engine = AutomationEngine()
        engine.add_schedule(
            ScheduleRule(
                name="Kunlik hisobot",
                agent_name="ceo",
                cron_expr="0 9 * * *",
                command="Hisobot tayyorla",
            )
        )
        d = AutomationDaemon(
            engine=engine,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
            session_factory=session_factory,
            llm_providers={"google": fake_google},
            settings=Settings(_env_file=None),
        )

        fired = await d.tick(now=_at(9, 0))

        assert len(fired) == 1
        assert fake_google.calls  # haqiqatan chaqirilgan
        assert engine.scheduler.list_rules()[0].run_count == 1

    async def test_without_llm_config_falls_back_to_fake(
        self, daemon: AutomationDaemon, automation_engine: AutomationEngine
    ) -> None:
        """`session_factory`/`llm_providers` berilmasa — avvalgi FakeProvider yo'li."""
        fired = await daemon.tick(now=_at(9, 0))
        assert len(fired) == 1
        assert automation_engine.scheduler.list_rules()[0].run_count == 1


class TestHandoffWiring:
    """Muvaffaqiyatli fire'dan keyin AGENT_HANDOFF triggerlari uyg'onishi.

    Ilgari `HandoffDispatcher` qurilgan-u ishlab chiqarish oqimiga hech
    qachon ulanmagan edi. Endi `AutomationDaemon._fire()` muvaffaqiyatli
    bo'lgach `dispatch()` chaqiradi va navbat zanjiri ishlaydi.
    """

    async def test_successful_fire_triggers_handoff(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        # 'ceo' tugagach 'operations'ni uyg'otsin
        from zet.agents.builtin.operations import OPERATIONS_AGENT_SPEC
        from zet.automation.handoff import HandoffDispatcher
        from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType

        agent_registry.register(OPERATIONS_AGENT_SPEC, status=AgentStatus.ACTIVE)
        automation_engine.add_trigger(
            EventTrigger(
                name="ceo → operations",
                trigger_type=TriggerType.AGENT_HANDOFF,
                agent_name="operations",
                event_type="agent.completed",
                conditions=[
                    TriggerCondition(field="agent", operator="eq", value="ceo"),
                    TriggerCondition(field="success", operator="eq", value="true"),
                ],
            )
        )

        dispatcher = HandoffDispatcher(
            engine=automation_engine,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            killswitch=KillSwitchState(),
        )

        daemon = AutomationDaemon(
            engine=automation_engine,
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
            handoff_dispatcher=dispatcher,
        )
        fired = await daemon.tick(now=_at(9, 0))
        assert fired  # ceo qoidasi ishga tushdi
        # Handoff mantiqi ishlaganini bilvosita — trigger'ning `fire_count`
        # oshgan bo'lsa, uni `HandoffDispatcher` uyg'otgan (asosiy scheduler
        # AGENT_HANDOFF triggerlariga tegmaydi). To'liq zanjir mantiqi
        # `test_handoff.py`da tekshirilgan.
        triggers = automation_engine.triggers.list_triggers()
        assert triggers[0].fire_count >= 1, (
            "AGENT_HANDOFF trigger uyg'onmagan — dispatcher ulanmagan bo'lishi mumkin"
        )

    async def test_no_dispatcher_is_not_an_error(self, daemon: AutomationDaemon) -> None:
        """Handoff dispatcher berilmagan bo'lsa ham qoida ishlayveradi."""
        fired = await daemon.tick(now=_at(9, 0))
        assert fired
