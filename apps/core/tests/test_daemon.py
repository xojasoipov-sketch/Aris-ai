"""DailyScheduleDaemon testlari — V-35 kunlik avtonom jadval (gap-analysis #21).

Ilgari `DailyScheduleManager` faqat data model edi — hech narsa uni haqiqatan
ishga tushirmasdi. Bu testlar `tick()` orqali real fire mantiqini tekshiradi
(loop kutmasdan — `run_forever()` alohida, minimal tekshiriladi).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.registry import AgentRegistry
from zet.core.state import CoreState
from zet.deploy.daemon import DailyScheduleDaemon
from zet.deploy.schedule import DailyScheduleManager, DailyTask, ScheduleSlot
from zet.domain.enums import AgentStatus
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import StubNotifier
from zet.tools.builtin import build_default_registry


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 11, hh, mm, 0, tzinfo=UTC)


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def daemon(agent_registry: AgentRegistry, tmp_path: Path) -> DailyScheduleDaemon:
    schedule = DailyScheduleManager(
        tasks=[
            DailyTask(
                slot=ScheduleSlot.MORNING_BRIEF,
                agent_name="ceo",
                command="Brifing tayyorla",
                cron_expr="0 8 * * *",
            ),
        ]
    )
    return DailyScheduleDaemon(
        schedule=schedule,
        agent_registry=agent_registry,
        tool_registry=build_default_registry(notes_dir=tmp_path),
        permission_policy=PermissionPolicy(),
        core_state=CoreState(),
        killswitch=KillSwitchState(),
        timezone="UTC",
    )


class TestTick:
    async def test_fires_at_matching_time(self, daemon: DailyScheduleDaemon) -> None:
        fired = await daemon.tick(now=_at(8, 0))
        assert fired == ["08:00"]

    async def test_no_fire_outside_window(self, daemon: DailyScheduleDaemon) -> None:
        fired = await daemon.tick(now=_at(8, 1))
        assert fired == []

    async def test_no_double_fire_same_day(self, daemon: DailyScheduleDaemon) -> None:
        first = await daemon.tick(now=_at(8, 0))
        second = await daemon.tick(now=_at(8, 0))
        assert first == ["08:00"]
        assert second == []

    async def test_fires_again_next_day(self, daemon: DailyScheduleDaemon) -> None:
        await daemon.tick(now=_at(8, 0))
        tomorrow = datetime(2026, 8, 12, 8, 0, 0, tzinfo=UTC)
        fired = await daemon.tick(now=tomorrow)
        assert fired == ["08:00"]

    async def test_skipped_while_sleeping(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        state = CoreState()
        state.sleep(reason="Test")
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[DailyTask(slot=ScheduleSlot.MORNING_BRIEF, agent_name="ceo", command="x")]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=state,
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(8, 0))
        assert fired == []

    async def test_skipped_while_killswitch_engaged(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="Test")
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[DailyTask(slot=ScheduleSlot.MORNING_BRIEF, agent_name="ceo", command="x")]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=ks,
            timezone="UTC",
        )
        fired = await d.tick(now=_at(8, 0))
        assert fired == []

    async def test_disabled_task_skipped(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[
                    DailyTask(
                        slot=ScheduleSlot.MORNING_BRIEF,
                        agent_name="ceo",
                        command="x",
                        enabled=False,
                    )
                ]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(8, 0))
        assert fired == []

    async def test_missing_agent_does_not_crash(self, tmp_path: Path) -> None:
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[DailyTask(slot=ScheduleSlot.MORNING_BRIEF, agent_name="ghost", command="x")]
            ),
            agent_registry=AgentRegistry(),  # bo'sh — "ghost" yo'q
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
        )
        fired = await d.tick(now=_at(8, 0))
        # Slot mos keladi va urinildi (fired), lekin agent topilmagani uchun
        # daemon.tick_error emas — xato jim yutiladi, keyingi tick'da qayta
        # urinilmaydi (bir kunda bir marta), keyingi tick esa hech nima qilmaydi
        assert fired == ["08:00"]

    async def test_updates_agent_metrics(
        self, daemon: DailyScheduleDaemon, agent_registry: AgentRegistry
    ) -> None:
        await daemon.tick(now=_at(8, 0))
        state = agent_registry.get("ceo")
        assert state.total_runs == 1


class TestRunForever:
    async def test_stop_ends_loop(self, daemon: DailyScheduleDaemon) -> None:
        """stop() chaqirilgach run_forever() tugaydi (osilib qolmaydi)."""
        import asyncio

        daemon._tick_seconds = 3600  # uzoq — stop() darhol qaytishini tekshiradi
        task = asyncio.create_task(daemon.run_forever())
        await asyncio.sleep(0)  # loop bir marta ishlashiga imkon berish
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
        schedule = DailyScheduleManager(
            tasks=[
                DailyTask(
                    slot=ScheduleSlot.MORNING_BRIEF,
                    agent_name="ceo",
                    command="Brifing tayyorla",
                    cron_expr="0 8 * * *",
                ),
            ]
        )
        daemon = DailyScheduleDaemon(
            schedule=schedule,
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

        fired = await daemon.tick(now=_at(8, 0))

        assert fired == ["08:00"]
        assert fake_google.calls  # haqiqatan chaqirilgan
        assert agent_registry.get("ceo").total_runs == 1

    async def test_without_llm_config_falls_back_to_fake(
        self, daemon: DailyScheduleDaemon, agent_registry: AgentRegistry
    ) -> None:
        """`session_factory`/`llm_providers` berilmasa — avvalgi FakeProvider yo'li."""
        fired = await daemon.tick(now=_at(8, 0))
        assert fired == ["08:00"]
        assert agent_registry.get("ceo").total_runs == 1


class TestDelivery:
    """V-35 kunlik natijalar egaga yetkazilishi (GAP_ANALYSIS BROKEN #4)."""

    async def test_successful_fire_sends_notifier(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        notifier = StubNotifier()
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[
                    DailyTask(
                        slot=ScheduleSlot.MORNING_BRIEF,
                        agent_name="ceo",
                        command="Brifing",
                        description="Ertalabki brifing",
                    )
                ]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
            notifier=notifier,
        )

        await d.tick(now=_at(8, 0))

        assert len(notifier.sent) == 1
        assert "Ertalabki brifing" in notifier.sent[0].text

    async def test_no_notifier_is_silent_not_broken(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        """Notifier berilmasa daemon ishlashda davom etadi (fail-open)."""
        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[DailyTask(slot=ScheduleSlot.MORNING_BRIEF, agent_name="ceo", command="x")]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
        )

        fired = await d.tick(now=_at(8, 0))
        assert fired == ["08:00"]

    async def test_notify_failure_is_swallowed(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        """Xabar yubora olmasak — ish HAQIQATAN bajarilgan, daemon crash bermaydi."""

        from zet.telegram.notifier import Notification

        class ExplodingNotifier(StubNotifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("network down")

        d = DailyScheduleDaemon(
            schedule=DailyScheduleManager(
                tasks=[DailyTask(slot=ScheduleSlot.MORNING_BRIEF, agent_name="ceo", command="x")]
            ),
            agent_registry=agent_registry,
            tool_registry=build_default_registry(notes_dir=tmp_path),
            permission_policy=PermissionPolicy(),
            core_state=CoreState(),
            killswitch=KillSwitchState(),
            timezone="UTC",
            notifier=ExplodingNotifier(),
        )

        fired = await d.tick(now=_at(8, 0))
        assert fired == ["08:00"]  # crash yo'q
