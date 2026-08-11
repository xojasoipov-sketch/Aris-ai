"""FastAPI dependency'lari (Z1.14).

Singleton va per-request dependency'lar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from zet.agents.registry import AgentRegistry
from zet.config import Settings, get_settings
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.state import CoreState
from zet.db.session import create_engine, create_session_factory, session_scope
from zet.deploy.schedule import DailyScheduleManager
from zet.llm.base import LLMProvider
from zet.llm.factory import build_providers
from zet.llm.router import ModelRouter
from zet.memory.store import MemoryStore
from zet.monitoring.alerts import AlertManager
from zet.monitoring.notify_bridge import AlertNotificationBridge
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import Notifier, StubNotifier
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry


@lru_cache(maxsize=1)
def get_killswitch() -> KillSwitchState:
    """Global killswitch holati (singleton)."""
    return KillSwitchState()


@lru_cache(maxsize=1)
def get_core_state() -> CoreState:
    """Global AI Core rejimi — Sleep/Active (singleton)."""
    return CoreState()


@lru_cache(maxsize=1)
def get_memory_store() -> MemoryStore:
    """Global in-memory xotira do'koni (singleton).

    Produksiyada PgMemoryStore bilan almashtiriladi.
    """
    return MemoryStore()


@lru_cache(maxsize=1)
def get_agent_registry() -> AgentRegistry:
    """Global agent registry (singleton).

    Produksiyada DB-backed versiyaga almashtiriladi.
    """
    return AgentRegistry()


def get_config() -> Settings:
    """Konfiguratsiya."""
    return get_settings()


# ── Tool Registry ──────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    """Global tool registry (singleton) — barcha builtin toollar bilan.

    Ilgari har bir so'rov bo'sh `ToolRegistry()` yaratardi — hech qanday
    tool ishlamas edi. Endi bitta joyda ro'yxatga olinadi.
    """
    settings = get_settings()
    return build_default_registry(
        notes_dir=settings.vault_dir,
        enable_shell=settings.enable_shell,
    )


# ── Xavfsizlik ────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_permission_policy() -> PermissionPolicy:
    """Global ruxsat siyosati (singleton)."""
    return PermissionPolicy()


@lru_cache(maxsize=1)
def get_approval_service() -> ApprovalService:
    """Global tasdiq xizmati (singleton) — run so'rovlari orasida saqlanadi."""
    settings = get_settings()
    return ApprovalService(ttl_minutes=settings.approval_ttl_minutes)


@lru_cache(maxsize=1)
def get_run_store() -> RunStore:
    """Global run holatlari do'koni (singleton)."""
    return RunStore()


@lru_cache(maxsize=1)
def get_daily_schedule_manager() -> DailyScheduleManager:
    """Global kunlik jadval (singleton) — V-35."""
    return DailyScheduleManager()


# ── Monitoring / Alerts ───────────────────────────────────────────


@lru_cache(maxsize=1)
def get_notifier() -> Notifier:
    """Global bildirishnoma yuboruvchi (singleton).

    Hozircha `StubNotifier` — real Telegram transport ulanguncha
    (`ZetBot`/aiogram) xabarlar faqat xotirada saqlanadi va log qilinadi.
    """
    return StubNotifier()


@lru_cache(maxsize=1)
def get_alert_manager() -> AlertManager:
    """Global ogohlantirish qoidalari va tarixi (singleton)."""
    return AlertManager()


def get_alert_bridge(
    alerts: AlertManager = Depends(get_alert_manager),
    notifier: Notifier = Depends(get_notifier),
) -> AlertNotificationBridge:
    """AlertManager'ni Notifier'ga ulaydigan ko'prik."""
    return AlertNotificationBridge(alerts=alerts, notifier=notifier)


# ── Ma'lumotlar bazasi ────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Global async DB engine (singleton, ilova hayoti davomida bitta)."""
    settings = get_settings()
    return create_engine(settings.database_url.get_secret_value())


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Sessiya fabrikasi (engine'ga bog'liq)."""
    return create_session_factory(get_engine())


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """So'rov chegarasidagi DB sessiyasi — muvaffaqiyatda commit, xatoda rollback."""
    async with session_scope(get_session_factory()) as session:
        yield session


# ── LLM ────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_llm_providers() -> dict[str, LLMProvider]:
    """Global LLM provayderlar to'plami (singleton — HTTP klientlar qayta ishlatiladi)."""
    return build_providers(get_settings())


def get_model_router(
    session: AsyncSession = Depends(get_db_session),
    providers: dict[str, LLMProvider] = Depends(get_llm_providers),
    settings: Settings = Depends(get_config),
) -> ModelRouter:
    """So'rov chegarasidagi Model Router (DB sessiyasi so'rovga bog'langan)."""
    return ModelRouter(providers, session, settings)


# ── Orchestrator ──────────────────────────────────────────────────


def get_orchestrator(
    router: ModelRouter = Depends(get_model_router),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    approval_service: ApprovalService = Depends(get_approval_service),
    killswitch: KillSwitchState = Depends(get_killswitch),
    run_store: RunStore = Depends(get_run_store),
    settings: Settings = Depends(get_config),
) -> Orchestrator:
    """So'rov chegarasidagi Orchestrator — Intent→Plan→Execute→Verify oqimi."""
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        approval_service=approval_service,
        killswitch=killswitch,
        run_store=run_store,
        budget_usd=settings.run_max_usd,
        max_steps=settings.run_max_steps,
    )


@lru_cache(maxsize=1)
def get_telegram_bot() -> object:
    """Global Telegram bot (singleton).

    ZetBot qaytaradi — turini `object` qilish tsiklik importdan saqlanish uchun.
    """
    from zet.telegram.bot import ZetBot
    from zet.voice.stt import StubSTT

    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""

    return ZetBot(
        token=token,
        owner_ids=settings.telegram_owner_id_set,
        stt=StubSTT(),
    )
