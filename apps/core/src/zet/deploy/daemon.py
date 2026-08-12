"""Background Daemon — kunlik avtonom jadvalni haqiqatan ishga tushiradi (V-35).

Ilgari `DailyScheduleManager` faqat data model edi — hech qanday event loop
yoki jarayon uni ishga tushirmasdi (gap-analysis #21: "data models only, no
daemon/process/event loop"). Bu modul minut-aniqligida tik qiladi; joriy
vaqt biror slot bilan mos kelsa (va shu kuni hali ishga tushmagan bo'lsa),
tegishli agentni ishga tushiradi.

Xavfsizlik:
    - `CoreState.is_sleeping` bo'lsa — hech narsa ishga tushmaydi
    - `KillSwitch` yoqilgan bo'lsa — hech narsa ishga tushmaydi
    - Bir kunda bir slot faqat bir marta ishga tushadi (xotirada — restart'da
      qayta tiklanadi, produksiyada DB-backed `last_fired`ga almashtiriladi)

LLM: `session_factory`/`llm_providers`/`settings` berilsa — har bir fire
uchun yangi DB sessiya bilan real `ModelRouter` quriladi (`RoutedLLMProvider`
orqali, `is_autonomous=True` — ADR-0006 §4 avtonom budjet ulushi). Berilmasa
(default, testlar) — avvalgidek `FakeProvider()` (orqaga mos).

Bog'liq qarorlar:
    V-35 — kunlik avtonom jadval
    Bo'lim 9 — Automation Engine
    Bo'lim 12 — Production + Scale
    ADR-0006 — 4 darajali Model Router
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.agents.registry import AgentNotActiveError, AgentNotFoundError, AgentRegistry
from zet.agents.runtime import AgentRuntime
from zet.config import Settings
from zet.core.state import CoreState
from zet.db.session import session_scope
from zet.deploy.schedule import DailyScheduleManager, DailyTask
from zet.llm.base import LLMProvider
from zet.llm.fake import FakeProvider
from zet.llm.routed_provider import RoutedLLMProvider, task_class_for_tier
from zet.llm.router import ModelRouter
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)

DEFAULT_TICK_SECONDS = 60
"""Daemon tekshirish oralig'i — minut aniqligi yetarli (slot'lar HH:MM)."""


class DailyScheduleDaemon:
    """Kunlik jadvalni fon rejimida bajaruvchi tsikl.

    `run_forever()` — asyncio task sifatida ishga tushiriladi (FastAPI
    lifespan yoki `z daemon` CLI komandasi orqali). `tick()` — bitta
    tekshiruv, testlarda to'g'ridan-to'g'ri chaqiriladi (loop kutmasdan).
    """

    def __init__(
        self,
        *,
        schedule: DailyScheduleManager,
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
    ) -> None:
        self._schedule = schedule
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
        self._last_fired: dict[str, date] = {}
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Doimiy tsikl — `stop()` chaqirilmaguncha ishlaydi."""
        log.info("daemon.started", tick_seconds=self._tick_seconds)
        while not self._stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("daemon.tick_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick_seconds)
        log.info("daemon.stopped")

    def stop(self) -> None:
        """Tsiklni keyingi tick oralig'ida to'xtatish."""
        self._stop_event.set()

    async def tick(self, *, now: datetime | None = None) -> list[str]:
        """Bitta tekshiruv — joriy vaqtga mos slot(lar)ni ishga tushiradi.

        Returns:
            Ishga tushirilgan slot qiymatlari ro'yxati (diagnostika/test uchun).
        """
        fired: list[str] = []

        if self._killswitch.is_engaged:
            log.debug("daemon.tick_skipped", reason="killswitch")
            return fired
        if self._core_state.is_sleeping:
            log.debug("daemon.tick_skipped", reason="sleeping")
            return fired

        current = now or datetime.now(tz=self._tz)
        current_hm = current.strftime("%H:%M")
        today = current.date()

        for task in self._schedule.list_enabled():
            if task.slot.value != current_hm:
                continue
            if self._last_fired.get(task.slot.value) == today:
                continue  # shu kuni allaqachon ishga tushgan

            self._last_fired[task.slot.value] = today
            await self._fire(task)
            fired.append(task.slot.value)

        return fired

    async def _fire(self, task: DailyTask) -> None:
        """Bitta vazifani bajarish — agent runtime orqali."""
        log.info("daemon.fire", slot=task.slot.value, agent=task.agent_name)
        try:
            state = self._agent_registry.get_active(task.agent_name)
        except (AgentNotFoundError, AgentNotActiveError) as exc:
            log.warning("daemon.agent_unavailable", agent=task.agent_name, error=str(exc))
            return

        if (
            self._session_factory is not None
            and self._llm_providers is not None
            and self._settings is not None
        ):
            async with session_scope(self._session_factory) as session:
                router = ModelRouter(self._llm_providers, session, self._settings)
                provider: LLMProvider = RoutedLLMProvider(router, is_autonomous=True)
                model = task_class_for_tier(state.spec.model_policy).value
                result = await AgentRuntime(
                    provider=provider,
                    tool_registry=self._tool_registry,
                    permission_policy=self._permission_policy,
                    model=model,
                ).run(state.spec, task.command)
        else:
            runtime = AgentRuntime(
                provider=FakeProvider(),
                tool_registry=self._tool_registry,
                permission_policy=self._permission_policy,
            )
            result = await runtime.run(state.spec, task.command)

        self._agent_registry.record_run(
            task.agent_name,
            success=result.success,
            tool_calls=result.tool_calls_count,
        )
        log.info(
            "daemon.fired",
            slot=task.slot.value,
            agent=task.agent_name,
            success=result.success,
        )


__all__ = ["DEFAULT_TICK_SECONDS", "DailyScheduleDaemon"]
