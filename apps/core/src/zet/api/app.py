"""FastAPI ilova yaratish (Z1.14).

Lean versiya — SSE yo'q, faqat REST endpoint'lar.

Endpoint'lar:
    POST /api/v1/run     — yangi run boshlash
    GET  /api/v1/status   — tizim holati
    GET  /api/v1/health   — health check
    POST /api/v1/killswitch/engage   — emergency stop
    POST /api/v1/killswitch/disengage — emergency stop o'chirish
    GET  /api/v1/killswitch          — killswitch holati

Bog'liq qarorlar:
    A-01 — run holat mashinasi
    V-33 — favqulodda to'xtatish
    A-07 — budjet chegaralari
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from zet.api.deps import (
    get_agent_registry,
    get_automation_engine,
    get_core_state,
    get_daily_schedule_manager,
    get_embedding_provider,
    get_engine,
    get_killswitch,
    get_llm_providers,
    get_notifier,
    get_permission_policy,
    get_stt,
    get_telegram_bot,
    get_tool_registry,
    get_tts,
)
from zet.api.middleware import TokenAuthMiddleware, TraceMiddleware
from zet.api.routes import (
    agent,
    alerts,
    approvals,
    automation,
    crm,
    health,
    killswitch,
    memory,
    run,
    state,
    system,
    telegram,
    workspace,
)
from zet.automation.builtin_metrics import register_builtin_metrics
from zet.config import get_settings
from zet.observability.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ilova boshlanganda va tugaganda bajariladigan kod."""
    from zet.api.deps import get_session_factory
    from zet.db.session import session_scope
    from zet.deploy.automation_daemon import AutomationDaemon
    from zet.deploy.bootstrap import bootstrap_agents, load_persisted_agents
    from zet.deploy.daemon import DailyScheduleDaemon

    settings = get_settings()
    configure_logging(
        json_output=settings.is_prod,
        log_level=settings.log_level,
    )
    log.info(
        "zet.startup",
        env=settings.env.value,
        budget_daily=settings.budget_daily_usd,
        budget_monthly=settings.budget_monthly_usd,
    )
    bootstrap_agents()

    # Kuzatuv (3-xususiyat) uchun tayyor metrikalar — tashqi API'siz,
    # shuning uchun watcher birinchi kundan sinab ko'riladi.
    register_builtin_metrics(get_automation_engine(), get_agent_registry())

    # Agent Factory orqali ilgari yaratilgan (builtin bo'lmagan) agentlarni
    # DB'dan qayta tiklaydi — DB mavjud bo'lmasa ham ishga tushish davom
    # etadi (fail-open, gap-analysis #1).
    try:
        async with session_scope(get_session_factory()) as session:
            await load_persisted_agents(session)
    except Exception:
        log.warning("zet.agents_reload_failed")

    daemon = DailyScheduleDaemon(
        schedule=get_daily_schedule_manager(),
        agent_registry=get_agent_registry(),
        tool_registry=get_tool_registry(),
        permission_policy=get_permission_policy(),
        core_state=get_core_state(),
        killswitch=get_killswitch(),
        timezone=settings.timezone,
        session_factory=get_session_factory(),
        llm_providers=get_llm_providers(),
        settings=settings,
    )
    daemon_task = asyncio.create_task(daemon.run_forever())

    automation_daemon = AutomationDaemon(
        engine=get_automation_engine(),
        agent_registry=get_agent_registry(),
        tool_registry=get_tool_registry(),
        permission_policy=get_permission_policy(),
        core_state=get_core_state(),
        killswitch=get_killswitch(),
        timezone=settings.timezone,
        session_factory=get_session_factory(),
        llm_providers=get_llm_providers(),
        settings=settings,
    )
    automation_daemon_task = asyncio.create_task(automation_daemon.run_forever())

    # Telegram bot polling — token bo'lsa haqiqiy long-polling boshlanadi.
    # `ZetBot.start()` ichida TelegramPoller task yaratiladi va darhol qaytadi
    # (lifespan'ni bloklamaydi). Tokensiz — stub rejim, hech qanday tarmoq
    # chaqiruvi yo'q (test/dev bilan orqaga mos).
    telegram_bot = get_telegram_bot()
    await telegram_bot.start()  # type: ignore[attr-defined]

    yield

    log.info("zet.shutdown")
    daemon.stop()
    daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await daemon_task
    automation_daemon.stop()
    automation_daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await automation_daemon_task
    with contextlib.suppress(Exception):
        await telegram_bot.stop()  # type: ignore[attr-defined]
    providers = get_llm_providers()
    for provider in providers.values():
        await provider.aclose()
    notifier = get_notifier()
    if hasattr(notifier, "aclose"):
        await notifier.aclose()
    await get_embedding_provider().aclose()
    for closable in (get_stt(), get_tts()):
        if hasattr(closable, "aclose"):
            await closable.aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    """FastAPI ilova yaratish."""
    settings = get_settings()

    app = FastAPI(
        title="ZET",
        description="Shaxsiy AI operatsion tizim",
        version="0.1.0",
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Middleware — oxirgi qo'shilgan BIRINCHI ishlaydi (Starlette stack).
    # Token tekshiruvi trace'dan keyin qo'shiladi, ya'ni rad etilgan
    # so'rov ham trace_id oladi — 401'larni log'da kuzatish uchun.
    app.add_middleware(TokenAuthMiddleware, settings=settings)
    app.add_middleware(TraceMiddleware)

    # Routerlar
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(run.router, prefix="/api/v1", tags=["run"])
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(killswitch.router, prefix="/api/v1", tags=["killswitch"])
    app.include_router(state.router, prefix="/api/v1", tags=["state"])
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(agent.router, prefix="/api/v1", tags=["agents"])
    app.include_router(automation.router, prefix="/api/v1")
    app.include_router(crm.router, prefix="/api/v1")
    app.include_router(telegram.router, prefix="/api/v1", tags=["telegram"])
    app.include_router(workspace.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")

    return app
