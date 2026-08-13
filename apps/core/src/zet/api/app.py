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
    get_alert_manager,
    get_automation_engine,
    get_core_state,
    get_daily_schedule_manager,
    get_embedding_provider,
    get_engine,
    get_killswitch,
    get_llm_providers,
    get_notifier,
    get_permission_policy,
    get_rate_limiter,
    get_selfimprove_engine,
    get_shop_bot,
    get_stt,
    get_telegram_bot,
    get_tool_registry,
    get_tts,
)
from zet.api.middleware import RateLimitMiddleware, TokenAuthMiddleware, TraceMiddleware
from zet.api.routes import (
    agent,
    alerts,
    approvals,
    automation,
    camera,
    commerce,
    conversation,
    crm,
    device,
    feeds,
    health,
    killswitch,
    memory,
    run,
    state,
    system,
    telegram,
    vault,
    voice,
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
    from zet.automation.handoff import HandoffDispatcher
    from zet.automation.persistence import load_automation
    from zet.db.session import session_scope
    from zet.deploy.alerts_daemon import AlertsDaemon, default_rules
    from zet.deploy.automation_daemon import AutomationDaemon
    from zet.deploy.bootstrap import bootstrap_agents, load_persisted_agents
    from zet.deploy.daemon import DailyScheduleDaemon
    from zet.deploy.reports_daemon import ReportsDaemon
    from zet.deploy.selfimprove_daemon import SelfImproveDaemon
    from zet.deploy.shipment_daemon import ShipmentNotifyDaemon
    from zet.monitoring.notify_bridge import AlertNotificationBridge
    from zet.security.killswitch_actions import register_killswitch_engage_callback
    from zet.security.killswitch_store import load_killswitch

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

    # Killswitch DB'dan tiklash — restart'da yoqilgan holat yo'qolmasin
    # (V-33, GAP_ANALYSIS BROKEN #3). Fail-open: DB yetib bo'lmasa
    # startup'ni to'xtatmaydi.
    try:
        await load_killswitch(get_killswitch(), get_session_factory())
    except Exception:
        log.warning("zet.killswitch_restore_failed")

    # SR-06: `engage()` chaqirilishi bilan barcha faol capability
    # tokenlarni bekor qiladigan hook. REST route ham, Telegram runner
    # ham revocation'ni AWAIT bilan alohida chaqiradi — bu callback
    # esa CLI (`z killswitch on`) yoki `check()`ni ichkaridan trigger
    # qiluvchi boshqa kod yo'lini yopadi (fon vazifasi sifatida).
    # `get_killswitch` singleton bo'lgani uchun testlarda hooklar
    # to'planib qolmasin deb har startup'da tozalab qayta qo'yamiz.
    _ks_singleton = get_killswitch()
    _ks_singleton.clear_engage_callbacks()
    register_killswitch_engage_callback(_ks_singleton, get_session_factory())

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
        # V-35 kunlik avtonomiyaning natijasi egaga yetkazilsin
        # (AutomationDaemon bilan bir xil naqsh; GAP_ANALYSIS BROKEN #4).
        notifier=get_notifier(),
    )
    daemon_task = asyncio.create_task(daemon.run_forever())

    # Saqlangan avtomatlashtirishlarni tiklash — daemon ISHGA TUSHISHDAN
    # OLDIN. Aks holda birinchi tick bo'sh jadval ko'rib o'tib ketardi va
    # ega yoqqan retsept o'sha daqiqada ishlamay qolardi.
    await load_automation(
        get_automation_engine(),
        get_session_factory(),
        owner_external_id=settings.owner_id,
    )

    # 4-xususiyat (navbat) — Bo'lim 9 chala qolgan bo'g'in.
    # `HandoffDispatcher` qurilgan-u ishlab chiqarish oqimiga hech qachon
    # ulanmasdi. Endi tugagan agent AGENT_HANDOFF trigger'lariga yetadi.
    # Zanjir chuqurligi (`MAX_HANDOFF_DEPTH=5`) va tashrif to'plami
    # cheksiz tsikldan himoya qiladi (A-07 ruhida).
    handoff_dispatcher = HandoffDispatcher(
        engine=get_automation_engine(),
        agent_registry=get_agent_registry(),
        tool_registry=get_tool_registry(),
        permission_policy=get_permission_policy(),
        killswitch=get_killswitch(),
    )

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
        # Natija egaga yetib borsin — aks holda "Kunlik puls" har kuni
        # ishlab, hech kimga hech narsa aytmasdi.
        notifier=get_notifier(),
        handoff_dispatcher=handoff_dispatcher,
    )
    automation_daemon_task = asyncio.create_task(automation_daemon.run_forever())

    # Telegram bot polling — token bo'lsa haqiqiy long-polling boshlanadi.
    # `ZetBot.start()` ichida TelegramPoller task yaratiladi va darhol qaytadi
    # (lifespan'ni bloklamaydi). Tokensiz — stub rejim, hech qanday tarmoq
    # chaqiruvi yo'q (test/dev bilan orqaga mos).
    telegram_bot = get_telegram_bot()
    await telegram_bot.start()  # type: ignore[attr-defined]

    # Mijoz do'kon boti — ZetBot'dan MUSTAQIL polling (Z51, #42).
    # `shop_bot_token` sozlanmagan bo'lsa stub rejimda qoladi, hech
    # qanday tarmoq chaqiruvi bo'lmaydi.
    shop_bot = get_shop_bot()
    await shop_bot.start()  # type: ignore[attr-defined]

    # Kargo chiqishi bilan mijozga avtomatik xabar (Z51, #43). LLM/agent
    # kerak emas — mexanik tekshiruv, shuning uchun boshqa daemon'lardan
    # ALOHIDA, eng oddiy tsikl.
    shipment_daemon = ShipmentNotifyDaemon(
        session_factory=get_session_factory(),
        settings=settings,
    )
    shipment_daemon_task = asyncio.create_task(shipment_daemon.run_forever())

    # Haftalik (dushanba) va oylik (1-sana) sotuv+faollik hisoboti (#45).
    # Notifier yo'q bo'lsa mantiqiy — hech kimga yubora olmaymiz, daemon
    # ishga tushmaydi.
    reports_daemon = ReportsDaemon(
        session_factory=get_session_factory(),
        settings=settings,
        notifier=get_notifier(),
        llm_providers=get_llm_providers(),
    )
    reports_daemon_task = asyncio.create_task(reports_daemon.run_forever())

    # Self-improvement (V-36, GAP_ANALYSIS §12). `SelfImproveEngine` ilgari
    # faqat testda yashardi — endi dushanba ertalab CostLedger/ToolCall
    # signallarini o'qib, tavsiya qo'shadi va yig'ilganini egaga yuboradi.
    # Fail-open: tahlil xato bo'lsa daemon jimgina o'tib ketadi.
    selfimprove_daemon = SelfImproveDaemon(
        engine=get_selfimprove_engine(),
        session_factory=get_session_factory(),
        settings=settings,
        notifier=get_notifier(),
    )
    selfimprove_daemon_task = asyncio.create_task(selfimprove_daemon.run_forever())

    # AlertManager avtomatik ishga tushiruvchi (AUDIT #14 davomi). Qoidalar
    # HTTP orqali yaratilardi, biroq hech kim ularni haqiqiy metrikalar
    # bilan chaqirmasdi ("dead wiring"). Endi har 60 sekundda cost/tool/
    # verifier signallari o'lchanadi va bridge orqali Notifier'ga uzatiladi.
    # Standart 3 ta qoida ega ko'rmasdanoq trafik olsin — HTTP orqali
    # o'chirilishi mumkin.
    alert_manager = get_alert_manager()
    if not alert_manager.list_rules():
        for rule in default_rules():
            alert_manager.add_rule(rule)
    alerts_bridge = AlertNotificationBridge(alerts=alert_manager, notifier=get_notifier())
    alerts_daemon = AlertsDaemon(
        bridge=alerts_bridge,
        session_factory=get_session_factory(),
        settings=settings,
    )
    alerts_daemon_task = asyncio.create_task(alerts_daemon.run_forever())

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
    shipment_daemon.stop()
    shipment_daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await shipment_daemon_task
    with contextlib.suppress(Exception):
        await shipment_daemon.aclose()
    reports_daemon.stop()
    reports_daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await reports_daemon_task
    selfimprove_daemon.stop()
    selfimprove_daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await selfimprove_daemon_task
    alerts_daemon.stop()
    alerts_daemon_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await alerts_daemon_task
    with contextlib.suppress(Exception):
        await telegram_bot.stop()  # type: ignore[attr-defined]
    with contextlib.suppress(Exception):
        await shop_bot.stop()  # type: ignore[attr-defined]
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
    # Rate limit token tekshiruvidan KEYIN kelsin — birinchi tekshiruv
    # token bo'lishi, so'ng rate limit; auth muvaffaqiyatsiz bo'lsa rate
    # limit hisobi buzilmasin.
    #
    # Aslida: `add_middleware`da tartib teskari — oxirgi qo'shilgan
    # birinchi ishlaydi. Shunday tuzganda tashqi zanjir:
    #   RateLimit → TokenAuth → Trace → handler
    # Rate limit 429ni token check'dan OLDIN qaytaradi (chunki auth
    # 401ni oldindan bilib, resurs sarflashdan ham himoyalanamiz).
    app.add_middleware(TokenAuthMiddleware, settings=settings)
    app.add_middleware(RateLimitMiddleware, limiter=get_rate_limiter())
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
    app.include_router(voice.router, prefix="/api/v1")
    app.include_router(conversation.router, prefix="/api/v1")
    app.include_router(vault.router, prefix="/api/v1")
    app.include_router(camera.router, prefix="/api/v1")
    app.include_router(feeds.router, prefix="/api/v1")
    app.include_router(commerce.router, prefix="/api/v1")
    app.include_router(device.router, prefix="/api/v1")

    return app
