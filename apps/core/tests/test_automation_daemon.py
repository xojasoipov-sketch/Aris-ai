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
from zet.tools.builtin import build_default_registry


def _at(hh: int, mm: int) -> datetime:
    return datetime(2026, 8, 12, hh, mm, 0, tzinfo=UTC)  # 2026-08-12 — chorshanba


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def engine() -> AutomationEngine:
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
    engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
) -> AutomationDaemon:
    return AutomationDaemon(
        engine=engine,
        agent_registry=agent_registry,
        tool_registry=build_default_registry(notes_dir=tmp_path),
        permission_policy=PermissionPolicy(),
        core_state=CoreState(),
        killswitch=KillSwitchState(),
        timezone="UTC",
    )


class TestTick:
    async def test_fires_at_matching_time(
        self, daemon: AutomationDaemon, engine: AutomationEngine
    ) -> None:
        fired = await daemon.tick(now=_at(9, 0))
        assert len(fired) == 1

        rule = engine.scheduler.list_rules()[0]
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
        self, engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        state = CoreState()
        state.sleep(reason="Test")
        d = AutomationDaemon(
            engine=engine,
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
        self, engine: AutomationEngine, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        ks = KillSwitchState()
        ks.engage(reason="Test")
        d = AutomationDaemon(
            engine=engine,
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


class TestStop:
    async def test_stop_ends_run_forever(self, daemon: AutomationDaemon) -> None:
        import asyncio

        task = asyncio.create_task(daemon.run_forever())
        await asyncio.sleep(0)
        daemon.stop()
        await asyncio.wait_for(task, timeout=5)
        assert task.done()
