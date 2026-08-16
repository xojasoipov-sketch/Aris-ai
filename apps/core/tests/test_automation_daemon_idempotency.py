"""AutomationDaemon restart-idempotency testlari (JB-10).

MUAMMO (JB-9 auditi): `_last_fired_minute` dict in-memory bo'lgani
uchun restart mid-minute bo'lsa (redeploy, crash) bir xil qoida
IKKINCHI marta ishga tushishi mumkin edi.

JB-10 tuzatishi: `hydrate_last_fired_from_rules()` — Scheduler'dagi
`ScheduleRule.last_run_at` (persistent) qiymatidan minute-key dict'ni
to'ldiradi. Restart'dan keyin AYNAN o'sha daqiqada `is_due` mos
kelsa ham, dedup ishlaydi.
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


def _at(y: int, mo: int, d: int, hh: int, mm: int) -> datetime:
    return datetime(y, mo, d, hh, mm, 0, tzinfo=UTC)


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


def _make_daemon(
    engine: AutomationEngine, agents: AgentRegistry, tmp_path: Path
) -> AutomationDaemon:
    return AutomationDaemon(
        engine=engine,
        agent_registry=agents,
        tool_registry=build_default_registry(notes_dir=tmp_path),
        permission_policy=PermissionPolicy(),
        core_state=CoreState(),
        killswitch=KillSwitchState(),
        timezone="UTC",
    )


class TestHydrateOnInit:
    async def test_rule_never_fired_no_hydration(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        """Yangi qoida — last_run_at=None — hydrate hech narsa qilmaydi."""
        engine = AutomationEngine()
        engine.add_schedule(
            ScheduleRule(
                name="Kunlik",
                agent_name="ceo",
                cron_expr="0 9 * * *",
                command="ish",
            )
        )
        daemon = _make_daemon(engine, agent_registry, tmp_path)

        # Ichki dict bo'sh — hech qanday qoida hali ishga tushmagan.
        assert daemon._last_fired_minute == {}

    async def test_rule_with_last_run_at_populates_minute_key(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        """Persist qilingan last_run_at — restart'dan keyin minute-key'da
        muhrlangan bo'lishi kerak."""
        engine = AutomationEngine()
        rule = engine.add_schedule(
            ScheduleRule(
                name="Kunlik",
                agent_name="ceo",
                cron_expr="0 9 * * *",
                command="ish",
            )
        )
        # Simulyatsiya: `record_run` chaqirilgan (fire bo'lgan).
        engine.scheduler.record_run(rule.id)
        stored = engine.scheduler.get_rule(rule.id)
        assert stored is not None
        assert stored.last_run_at is not None

        # YANGI daemon (restart) — hydrate ichki dict'ni to'ldirishi kerak.
        daemon = _make_daemon(engine, agent_registry, tmp_path)

        # Minute-key sifatida DAQIQAgacha aniqlikda muhrlangan.
        expected_key = stored.last_run_at.astimezone(daemon._tz).strftime("%Y-%m-%d %H:%M")
        assert daemon._last_fired_minute.get(rule.id) == expected_key


class TestRestartDoubleFire:
    """Asosiy xavfsizlik dalili: restart mid-minute → dublikat fire yo'q.

    NEGA `last_run_at`ni to'g'ridan-to'g'ri o'rnatamiz: `record_run()`
    `datetime.now(UTC)` chaqiradi (mock qilinmagan), test-mocked
    "tick" vaqti bilan mos kelmaydi. Restart senariysida DB'dan
    `last_run_at` real fire vaqti bilan keladi — bu yerda ham shuni
    simulyatsiya qilamiz.
    """

    def _engine_with_prefired_rule(self, fire_time: datetime) -> AutomationEngine:
        """`last_run_at`si oldindan berilgan qoida bilan engine — restart
        holatini soxta qilamiz (DB'dan tiklandi degan gap)."""
        engine = AutomationEngine()
        engine.add_schedule(
            ScheduleRule(
                name="Har daqiqa",
                agent_name="ceo",
                cron_expr="* * * * *",
                command="ish",
                last_run_at=fire_time,
                run_count=1,
            )
        )
        return engine

    async def test_no_double_fire_after_restart_same_minute(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        fire_time = _at(2026, 8, 12, 14, 33)
        engine = self._engine_with_prefired_rule(fire_time)

        # Restart simulyatsiyasi: YANGI daemon (`last_run_at`ni ko'radi
        # va `_last_fired_minute` ni to'ldiradi).
        daemon = _make_daemon(engine, agent_registry, tmp_path)

        # AYNAN o'sha daqiqada tick — dublikat fire bo'lmasligi kerak.
        fired = await daemon.tick(now=fire_time)

        # KRITIK DALIL: hydrate ishlaganini isbotlaydi.
        assert fired == [], "restart mid-minute — dublikat fire mumkin emas"

    async def test_fires_normally_next_minute_after_restart(
        self, agent_registry: AgentRegistry, tmp_path: Path
    ) -> None:
        """Hydrate faqat SO'NGGI daqiqani bloklaydi — keyingi tick normal."""
        fire_time = _at(2026, 8, 12, 14, 33)
        engine = self._engine_with_prefired_rule(fire_time)

        daemon = _make_daemon(engine, agent_registry, tmp_path)
        # Bir daqiqa keyin — qayta fire QILINISHI kerak.
        fired = await daemon.tick(now=_at(2026, 8, 12, 14, 34))
        assert len(fired) == 1
