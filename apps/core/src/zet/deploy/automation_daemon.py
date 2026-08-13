"""Automation Daemon — Bo'lim 9 `AutomationEngine`ni haqiqiy fon protsessga ulaydi.

Ilgari `Scheduler`/`AutomationEngine` faqat ma'lumot modeli va amal (Action)
generatori edi — hech qanday event loop ularni HAQIQATDA bajarmasdi
(gap-analysis: "AutomationEngine produces actions but nothing executes
them"). Bu daemon `DailyScheduleDaemon` bilan bir xil naqsh — har tikda
`Scheduler`dagi faol qoidalarni tekshiradi, `is_due()` orqali vaqti
kelganlarini `run_agent_command()` bilan haqiqiy ishga tushiradi.

Bu `DailyScheduleDaemon`ning o'rnini bosmaydi — u fiksirlangan 5 slotli
kunlik jadval (V-35) uchun; bu daemon esa erkin foydalanuvchi cron
qoidalari (Bo'lim 9, `POST /api/v1/automation/schedules`) uchun.

Xavfsizlik:
    - `CoreState.is_sleeping` / `KillSwitch` — `DailyScheduleDaemon` bilan bir xil
    - Muvaffaqiyatsiz bo'lsa `MAX_ATTEMPTS` marta qayta uriniladi (tiklanish, Bo'lim 9 DoD)
    - Bitta qoida bir daqiqada faqat bir marta ishga tushadi (xotirada dedup)

LLM: `session_factory`/`llm_providers`/`settings` berilsa — har bir fire
uchun yangi DB sessiya bilan real `ModelRouter` quriladi (`RoutedLLMProvider`
orqali, `is_autonomous=True`). Berilmasa (default, testlar) — `run_agent_command()`
o'zining `FakeProvider()` orqaga moslik yo'liga tushadi.

Bog'liq qarorlar:
    Bo'lim 9 — Automation Engine
    A-07 — run tormozlari
    ADR-0006 — 4 darajali Model Router
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.agents.registry import AgentRegistry
from zet.automation.cron import is_due
from zet.automation.engine import AutomationEngine
from zet.automation.executor import AgentUnavailableError, run_agent_command
from zet.automation.handoff import HandoffDispatcher
from zet.automation.scheduler import ScheduleRule
from zet.config import Settings
from zet.core.state import CoreState
from zet.db.session import session_scope
from zet.domain.agent import AgentRunResult
from zet.llm.base import LLMProvider
from zet.llm.routed_provider import RoutedLLMProvider
from zet.llm.router import ModelRouter
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import Notifier
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 60
"""Daemon tekshirish oralig'i — minut aniqligi yetarli (cron minut darajasida)."""

MAX_ATTEMPTS = 2
"""Bitta ishga tushish uchun jami urinishlar (1 asosiy + 1 qayta urinish — tiklanish)."""


class AutomationDaemon:
    """`Scheduler`dagi faol qoidalarni fon rejimida bajaruvchi tsikl.

    `run_forever()` — asyncio task sifatida ishga tushiriladi (FastAPI
    lifespan orqali). `tick()` — bitta tekshiruv, testlarda to'g'ridan-to'g'ri
    chaqiriladi (loop kutmasdan).
    """

    def __init__(
        self,
        *,
        engine: AutomationEngine,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy,
        core_state: CoreState,
        killswitch: KillSwitchState,
        timezone: str = "Asia/Tashkent",
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        llm_providers: dict[str, LLMProvider] | None = None,
        settings: Settings | None = None,
        notifier: Notifier | None = None,
        handoff_dispatcher: HandoffDispatcher | None = None,
    ) -> None:
        self._engine = engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._core_state = core_state
        self._killswitch = killswitch
        self._tz = ZoneInfo(timezone)
        self._tick_seconds = tick_seconds
        self._session_factory = session_factory
        self._llm_providers = llm_providers
        self._settings = settings
        self._notifier = notifier
        # Ilgari `HandoffDispatcher` qurilgan-u, hech qanday agent tugash
        # nuqtasiga ulanmagan edi (Bo'lim 9 chala qolgan bo'g'in). Endi
        # muvaffaqiyatli fire'dan keyin AGENT_HANDOFF triggerlari uyg'onadi.
        self._handoff_dispatcher = handoff_dispatcher
        self._last_fired_minute: dict[str, str] = {}
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Doimiy tsikl — `stop()` chaqirilmaguncha ishlaydi."""
        log.info("automation_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("automation_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("automation_daemon.stopped")

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def tick(self, *, now: datetime | None = None) -> list[str]:
        """Bitta tekshiruv — vaqti kelgan qoida(lar)ni ishga tushiradi.

        Returns:
            Ishga tushirilgan qoida ID'lari ro'yxati (diagnostika/test uchun).
        """
        fired: list[str] = []

        if self._killswitch.is_engaged:
            log.debug("automation_daemon.tick_skipped", reason="killswitch")
            return fired
        if self._core_state.is_sleeping:
            log.debug("automation_daemon.tick_skipped", reason="sleeping")
            return fired

        current = now or datetime.now(tz=self._tz)
        minute_key = current.strftime("%Y-%m-%d %H:%M")

        for rule in self._engine.scheduler.active_rules:
            if not is_due(rule.normalized_cron, current):
                continue
            if self._last_fired_minute.get(rule.id) == minute_key:
                continue  # shu daqiqada allaqachon ishga tushgan

            self._last_fired_minute[rule.id] = minute_key
            await self._fire(rule)
            fired.append(rule.id)

        if fired:
            # `_fire()` ichida `record_run()` chaqiriladi — ya'ni ishga
            # tushish soni va `max_runs` qoldig'i O'ZGARDI. Buni yozmasak,
            # qayta ishga tushishdan keyin cheklangan qoida hisobni
            # noldan boshlab ortiqcha ishlab ketardi.
            await self._persist_state()

        return fired

    async def _dispatch_handoff(self, agent_name: str, result: AgentRunResult) -> None:
        """4-xususiyat (navbat): tugagan agentdan `agent.completed` chiqadi.

        Ega ta'rifi (yangi zip, slayd 10): tugagan agent keyingi agentga
        ishni "uzatishi" mumkin. HandoffDispatcher shu hodisani `AutomationEngine`
        orqali AGENT_HANDOFF triggerlariga solishtiradi va mos kelganlar
        uchun agent'ni ishga tushiradi.

        FAIL-OPEN: dispatcher berilmagan bo'lsa (test/dev) yoki xato
        chiqsa — daemon o'ziga tegishli asosiy ish (qoida bajarilishi)
        allaqachon amalga oshgan, faqat navbat qadami o'tkazib yuboriladi.
        """
        if self._handoff_dispatcher is None:
            return
        try:
            await self._handoff_dispatcher.dispatch(agent_name, result)
        except Exception:
            log.warning("automation_daemon.handoff_failed", agent=agent_name)

    async def _deliver(self, rule: ScheduleRule, output: str) -> None:
        """Natijani EGAGA yetkazadi.

        NEGA KERAK BO'LDI. Daemon agentni ishga tushirar, natijani esa
        faqat LOG'ga yozardi. Ya'ni T06 "Kunlik puls" har kuni 09:20 va
        18:40 da ishlab, hech kimga hech narsa AYTMASDI — slaydda esa
        va'da aniq: "Uch qatorli xabar: siljidi / qotdi / sizdan qaror
        kutmoqda".

        Ega ko'rmaydigan joyga tushgan avtomatlashtirish natijasi
        avtomatlashtirish emas — shunchaki sarflangan token.

        Xato YUTILADI: xabar yetkazilmagani uchun qoida "bajarilmadi"
        deb belgilanmaydi — ish HAQIQATAN bajarilgan.
        """
        if self._notifier is None or not output.strip():
            return
        try:
            await self._notifier.send_text(f"{rule.name}\n\n{output.strip()}")
        except Exception:
            log.warning("automation_daemon.notify_failed", rule_id=rule.id)

    async def _persist_state(self) -> None:
        """Jadval holatini bazaga yozadi (fail-open).

        Daemon fon tsikli — bu yerda istisno butun tsiklni to'xtatmasligi
        kerak, shuning uchun `persist_automation` xatoni yutadi."""
        if self._session_factory is None or self._settings is None:
            return
        from zet.automation.persistence import persist_automation

        await persist_automation(
            self._engine,
            self._session_factory,
            owner_external_id=self._settings.owner_id,
        )

    async def _run_once(self, rule: ScheduleRule) -> AgentRunResult:
        """Qoidani bir marta bajaradi — sozlangan bo'lsa yangi DB sessiya bilan real LLM."""
        if self._session_factory is None:
            return await run_agent_command(
                rule.agent_name,
                rule.command,
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
            )

        async with session_scope(self._session_factory) as session:
            provider: LLMProvider | None = None
            if self._llm_providers is not None and self._settings is not None:
                router = ModelRouter(self._llm_providers, session, self._settings)
                provider = RoutedLLMProvider(router, is_autonomous=True)
            return await run_agent_command(
                rule.agent_name,
                rule.command,
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
                provider=provider,
            )

    async def _fire(self, rule: ScheduleRule) -> None:
        """Bitta qoidani bajarish — muvaffaqiyatsiz bo'lsa qayta urinish bilan."""
        log.info("automation_daemon.fire", rule_id=rule.id, agent=rule.agent_name)
        last_error: str | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = await self._run_once(rule)
            except AgentUnavailableError as exc:
                log.warning("automation_daemon.agent_unavailable", rule_id=rule.id, error=str(exc))
                return

            if result.success:
                self._engine.scheduler.record_run(rule.id)
                log.info(
                    "automation_daemon.fired",
                    rule_id=rule.id,
                    attempt=attempt,
                    success=True,
                )
                await self._deliver(rule, result.output)
                await self._dispatch_handoff(rule.agent_name, result)
                return

            last_error = result.error
            log.warning(
                "automation_daemon.attempt_failed",
                rule_id=rule.id,
                attempt=attempt,
                error=last_error,
            )

        self._engine.scheduler.record_run(rule.id)
        log.error("automation_daemon.fire_failed", rule_id=rule.id, error=last_error)


__all__ = ["DEFAULT_TICK_SECONDS", "MAX_ATTEMPTS", "AutomationDaemon"]
