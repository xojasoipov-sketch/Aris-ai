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

from zet.api.middleware import TraceMiddleware
from zet.api.routes import agent, health, killswitch, memory, run
from zet.config import get_settings
from zet.observability.logging import configure_logging

log = structlog.get_logger(__name__)


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
    yield
    log.info("zet.shutdown")


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
    app.include_router(killswitch.router, prefix="/api/v1", tags=["killswitch"])
    app.include_router(memory.router, prefix="/api/v1", tags=["memory"])
    app.include_router(agent.router, prefix="/api/v1", tags=["agents"])

    return app
