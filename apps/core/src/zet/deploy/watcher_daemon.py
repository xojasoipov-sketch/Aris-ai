"""Watcher Daemon — 3-xususiyat (kuzatuv)ni haqiqiy fon protsessga ulaydi.

Ilgari `AutomationEngine.poll_watchers()` FAQAT qo'lda HTTP endpoint
(`POST /api/v1/automation/watchers/poll`) orqali chaqirilardi — hech
qanday fon tsikli metrikalarni o'zi o'lchamasdi. Ya'ni "kuzatuv —
metrikani kuzatib turadi, o'zgarganda uyg'onadi" va'dasi faqat ega
qo'lda poll bosganda ishlardi — proaktivlik o'lik edi.

Bu daemon `AutomationDaemon` bilan bir xil naqsh: har tikda
`engine.poll_watchers()` chaqiradi va qaytgan `actions`ni HTTP route
(`_run_action`) bilan bir xil yo'l — `run_agent_command()` orqali
haqiqatan bajaradi. Watcher'lar bo'lmasa poll bo'sh ro'yxatda darhol
qaytadi (`WatcherRegistry.poll` bo'sh dict ustida aylanadi) — tsikl
arzon.

Xavfsizlik:
    - `CoreState.is_sleeping` / `KillSwitch` — `AutomationDaemon` bilan bir xil
    - Har bir amal xatosi YUTILADI (log + davom) — bitta yomon trigger
      butun kuzatuv tsiklini o'ldirmasin
    - Cooldown/max_fires tormozlari `WatchRule` darajasida (A-07)

LLM: `session_factory`/`llm_providers`/`settings` berilsa — har bir amal
uchun yangi DB sessiya bilan real `ModelRouter` quriladi (`RoutedLLMProvider`
orqali, `is_autonomous=True`). Berilmasa (default, testlar) —
`run_agent_command()` o'zining `FakeProvider()` orqaga moslik yo'liga tushadi.

Bog'liq qarorlar:
    Yangi zip — 3-xususiyat (kuzatuv)
    Bo'lim 9 — Automation Engine
    A-07 — run tormozlari
    ADR-0006 — avtonom budjet ulushi
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.agents.registry import AgentRegistry
from zet.automation.engine import AutomationAction, AutomationEngine, WatcherPollResult
from zet.automation.executor import AgentUnavailableError, run_agent_command
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

DEFAULT_TICK_SECONDS = 60.0
"""Daemon o'lchov oralig'i — watcher'lar minut aniqligida yetarli.

Haqiqiy qiymat `Settings.watcher_poll_interval_s`dan keladi (lifespan
wiring) — bu faqat mustaqil qurilish uchun default."""


class WatcherDaemon:
    """`WatcherRegistry`dagi qoidalarni fon rejimida o'lchab bajaruvchi tsikl.

    `run_forever()` — asyncio task sifatida ishga tushiriladi (FastAPI
    lifespan orqali). `tick()` — bitta o'lchov, testlarda to'g'ridan-to'g'ri
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
        tick_seconds: float = DEFAULT_TICK_SECONDS,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        llm_providers: dict[str, LLMProvider] | None = None,
        settings: Settings | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        self._engine = engine
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._permission_policy = permission_policy
        self._core_state = core_state
        self._killswitch = killswitch
        self._tick_seconds = tick_seconds
        self._session_factory = session_factory
        self._llm_providers = llm_providers
        self._settings = settings
        self._notifier = notifier
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Doimiy tsikl — `stop()` chaqirilmaguncha ishlaydi."""
        log.info("watcher_daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("watcher_daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("watcher_daemon.stopped")

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def tick(self) -> WatcherPollResult:
        """Bitta o'lchov — signal bergan qoidalarning amallarini bajaradi.

        Returns:
            Dvigatel poll natijasi (diagnostika/test uchun). Killswitch
            yoki uyqu rejimida — bo'sh natija, o'lchov o'tkazilmaydi.
        """
        if self._killswitch.is_engaged:
            log.debug("watcher_daemon.tick_skipped", reason="killswitch")
            return WatcherPollResult()
        if self._core_state.is_sleeping:
            log.debug("watcher_daemon.tick_skipped", reason="sleeping")
            return WatcherPollResult()

        poll = await self._engine.poll_watchers()

        for action in poll.actions:
            await self._execute(action)

        if poll.events:
            # Signal `fire_count`/`last_fired_at`ni O'ZGARTIRDI — yozmasak,
            # qayta ishga tushishdan keyin `max_fires` chegarali qoida
            # hisobni noldan boshlab ortiqcha signal berib ketardi
            # (AutomationDaemon bilan bir xil sabab).
            await self._persist_state()

        return poll

    async def _execute(self, action: AutomationAction) -> None:
        """Bitta trigger amalini bajarish — xato butun tsiklni to'xtatmaydi.

        HTTP route (`_run_action`) bilan bir xil semantika: `poll_watchers`
        amallarni O'ZI bajarmaydi, faqat qaytaradi — bajarish chaqiruvchining
        ishi. FAIL-OPEN: bitta amal yiqilsa qolganlari baribir bajariladi.
        """
        try:
            result = await self._run_action(action)
        except AgentUnavailableError as exc:
            log.warning(
                "watcher_daemon.agent_unavailable",
                trigger_id=action.trigger_id,
                agent=action.agent_name,
                error=str(exc),
            )
            return
        except Exception:
            log.exception(
                "watcher_daemon.action_error",
                trigger_id=action.trigger_id,
                agent=action.agent_name,
            )
            return

        if result.success:
            log.info(
                "watcher_daemon.action_done",
                trigger_id=action.trigger_id,
                agent=action.agent_name,
            )
            await self._deliver(action, result.output)
        else:
            log.error(
                "watcher_daemon.action_failed",
                trigger_id=action.trigger_id,
                agent=action.agent_name,
                error=result.error,
            )

    async def _run_action(self, action: AutomationAction) -> AgentRunResult:
        """Amalni bir marta bajaradi — sozlangan bo'lsa yangi DB sessiya bilan real LLM."""
        if self._session_factory is None:
            return await run_agent_command(
                action.agent_name,
                action.command,
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
                action.agent_name,
                action.command,
                agent_registry=self._agent_registry,
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
                provider=provider,
            )

    async def _deliver(self, action: AutomationAction, output: str) -> None:
        """Natijani EGAGA yetkazadi (AutomationDaemon bilan bir xil sabab).

        Ega ko'rmaydigan joyga tushgan kuzatuv natijasi kuzatuv emas —
        shunchaki sarflangan token. Xato YUTILADI: xabar yetmagani uchun
        amal "bajarilmadi" bo'lmaydi — ish HAQIQATAN bajarilgan.
        """
        if self._notifier is None or not output.strip():
            return
        try:
            await self._notifier.send_text(f"{action.trigger_name}\n\n{output.strip()}")
        except Exception:
            log.warning("watcher_daemon.notify_failed", trigger_id=action.trigger_id)

    async def _persist_state(self) -> None:
        """Kuzatuv holatini bazaga yozadi (fail-open).

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


__all__ = ["DEFAULT_TICK_SECONDS", "WatcherDaemon"]
