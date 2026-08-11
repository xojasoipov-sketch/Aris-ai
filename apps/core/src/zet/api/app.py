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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from zet.api.deps import get_agent_registry, get_engine, get_llm_providers
from zet.api.middleware import TraceMiddleware
from zet.api.routes import agent, approvals, health, killswitch, memory, run, state, telegram
from zet.config import get_settings
from zet.observability.logging import configure_logging

log = structlog.get_logger(__name__)


def _bootstrap_agents() -> None:
    """12 ta builtin agentni registry'ga (mavjud bo'lmasa) ACTIVE holatda qo'shadi.

    Ilgari `GET /api/v1/agents` startup'dan keyin bo'sh ro'yxat qaytarardi —
    hech kim builtin AgentSpec'larni registry'ga qo'ymas edi.
    """
    import zet.agents.builtin as builtin_module
    from zet.domain.enums import AgentStatus

    registry = get_agent_registry()
    for spec_name in builtin_module.__all__:
        spec = getattr(builtin_module, spec_name)
        if not registry.has(spec.name):
            registry.register(spec, status=AgentStatus.ACTIVE)
    log.info("zet.agents_bootstrapped", count=len(builtin_module.__all__))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Ilova boshlanganda va tugaganda bajariladigan kod."""
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
    _bootstrap_agents()
    yield
    log.info("zet.shutdown")
    providers = get_llm_providers()
    for provider in providers.values():
        await provider.aclose()
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

    # Middleware
    app.add_middleware(TraceMiddleware)

    # Routerlar
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(run.router, prefix="/api/v1", tags=["run"])
    app.include_router(approvals.router, prefix="/api/v1")
    app.include_router(killswitch.router, prefix="/api/v1", tags=["killswitch"])
    app.include_router(state.router, prefix="/api/v1", tags=["state"])
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(agent.router, prefix="/api/v1", tags=["agents"])
    app.include_router(telegram.router, prefix="/api/v1", tags=["telegram"])

    return app
