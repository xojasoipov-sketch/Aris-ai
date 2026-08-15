"""WatcherDaemon testlari — 3-xususiyat (kuzatuv)ning fon tsikli.

Audit topilmasi: `AutomationEngine.poll_watchers()` FAQAT qo'lda HTTP
endpoint orqali chaqirilardi — hech qanday fon tsikli metrikani o'zi
o'lchamasdi, ya'ni "o'zgarganda uyg'onadi" va'dasi amalda o'lik edi.
Bu testlar daemon tsiklining haqiqatan o'lchashini va signal bergan
qoidaning agentini ishga tushirishini tekshiradi (loop kutmasdan,
`tick()` orqali — `test_automation_daemon.py` naqshi).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationEngine
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.automation.watcher import WatchComparison, WatchRule
from zet.core.state import CoreState
from zet.deploy.watcher_daemon import WatcherDaemon
from zet.domain.enums import AgentStatus
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import Notification, Notifier, StubNotifier
from zet.tools.builtin import build_default_registry

METRIC = "test.metric"


class _Probe:
    """O'zgaruvchan metrika manbasi — birinchi o'lchov baza, keyingisi signal."""

    def __init__(self, *, values: list[float]) -> None:
        self._values = values
        self.reads = 0

    async def __call__(self) -> float | None:
        # Ro'yxat tugasa oxirgi qiymat qaytadi — tsikl cheksiz o'qiy oladi.
        value = self._values[min(self.reads, len(self._values) - 1)]
        self.reads += 1
        return value


@pytest.fixture()
def agent_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(CEO_AGENT_SPEC, status=AgentStatus.ACTIVE)
    return reg


@pytest.fixture()
def probe() -> _Probe:
    # 10.0 — baza (signal bermaydi), 20.0 — o'zgarish (signal beradi).
    return _Probe(values=[10.0, 20.0])


@pytest.fixture()
def automation_engine(probe: _Probe) -> AutomationEngine:
    engine = AutomationEngine()
    engine.metrics.register(METRIC, probe)
    engine.add_watch(
        WatchRule(
            name="Metrika o'zgardi",
            metric=METRIC,
            comparison=WatchComparison.CHANGED,
            # Testda ikkita tick ketma-ket chaqiriladi — cooldown 0
            # bo'lmasa ikkinchi signal tormozlanardi.
            cooldown_s=0,
        )
    )
    engine.add_trigger(
        EventTrigger(
            name="Kuzatuv → CEO",
            trigger_type=TriggerType.WATCHER,
            agent_name="ceo",
            conditions=[TriggerCondition(field="event_type", value=f"watch.{METRIC}")],
            command_template="Metrika o'zgardi, tekshir",
        )
    )
    return engine


def _daemon(
    engine: AutomationEngine,
    agent_registry: AgentRegistry,
    tmp_path: Path,
    *,
    core_state: CoreState | None = None,
    killswitch: KillSwitchState | None = None,
    notifier: Notifier | None = None,
) -> WatcherDaemon:
    return WatcherDaemon(
        engine=engine,
        agent_registry=agent_registry,
        tool_registry=build_default_registry(notes_dir=tmp_path),
        permission_policy=PermissionPolicy(),
        core_state=core_state or CoreState(),
        killswitch=killswitch or KillSwitchState(),
        notifier=notifier,
    )


class TestTick:
    async def test_first_tick_only_sets_baseline(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        probe: _Probe,
        tmp_path: Path,
    ) -> None:
        """Birinchi o'lchov baza o'rnatadi — soxta signal bermaydi."""
        daemon = _daemon(automation_engine, agent_registry, tmp_path)

        poll = await daemon.tick()

        assert probe.reads == 1
        assert poll.events == []
        assert poll.actions == []

    async def test_changed_metric_fires_agent(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """Ikkinchi o'lchovda qiymat o'zgargan — trigger agentni uyg'otadi."""
        daemon = _daemon(automation_engine, agent_registry, tmp_path)

        await daemon.tick()  # baza
        poll = await daemon.tick()  # 10.0 → 20.0

        assert len(poll.events) == 1
        assert poll.events[0].event_type == f"watch.{METRIC}"
        assert len(poll.actions) == 1
        assert poll.actions[0].agent_name == "ceo"
        # Agent HAQIQATAN ishga tushgan — registry hisobi buni tasdiqlaydi.
        assert agent_registry.get("ceo").total_runs == 1

    async def test_result_delivered_to_owner(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """Natija egaga yetadi — aks holda kuzatuv shunchaki sarflangan token."""
        notifier = StubNotifier()
        daemon = _daemon(automation_engine, agent_registry, tmp_path, notifier=notifier)

        await daemon.tick()
        await daemon.tick()

        assert len(notifier.sent) == 1
        assert "Kuzatuv → CEO" in notifier.sent[0].text


class TestBrakes:
    async def test_killswitch_skips_measurement(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        probe: _Probe,
        tmp_path: Path,
    ) -> None:
        killswitch = KillSwitchState()
        killswitch.engage()
        daemon = _daemon(automation_engine, agent_registry, tmp_path, killswitch=killswitch)

        poll = await daemon.tick()

        # Metrika UMUMAN o'qilmagan — killswitch o'lchovdan oldin to'xtatadi.
        assert probe.reads == 0
        assert poll.actions == []

    async def test_sleeping_skips_measurement(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        probe: _Probe,
        tmp_path: Path,
    ) -> None:
        core_state = CoreState()
        core_state.sleep()
        daemon = _daemon(automation_engine, agent_registry, tmp_path, core_state=core_state)

        poll = await daemon.tick()

        assert probe.reads == 0
        assert poll.actions == []


class TestFailOpen:
    async def test_action_error_does_not_kill_tick(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """Bitta yomon trigger butun kuzatuv tsiklini o'ldirmasin."""
        # Agent ro'yxatdan olib tashlanadi — `_run_action` AgentUnavailable
        # otadi, lekin `tick()` baribir normal natija qaytarishi kerak.
        empty_registry = AgentRegistry()
        daemon = _daemon(automation_engine, empty_registry, tmp_path)

        await daemon.tick()
        poll = await daemon.tick()

        assert len(poll.actions) == 1  # signal bergan, bajarish yiqilgan

    async def test_notifier_error_does_not_kill_tick(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """Xabar yetmagani uchun amal 'bajarilmadi' bo'lmaydi — ish bajarilgan."""

        class _BrokenNotifier(StubNotifier):
            async def send(self, notification: Notification) -> bool:
                raise RuntimeError("tarmoq yo'q")

        daemon = _daemon(
            automation_engine, agent_registry, tmp_path, notifier=_BrokenNotifier()
        )

        await daemon.tick()
        await daemon.tick()

        assert agent_registry.get("ceo").total_runs == 1


class TestLifecycle:
    async def test_stop_ends_run_forever(
        self,
        automation_engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tmp_path: Path,
    ) -> None:
        """`stop()` tsiklni keyingi oraliqda tugatadi (osilib qolmaydi)."""
        daemon = _daemon(automation_engine, agent_registry, tmp_path)
        daemon.stop()

        # Allaqachon to'xtatilgan — `run_forever` darhol qaytadi.
        await daemon.run_forever()
