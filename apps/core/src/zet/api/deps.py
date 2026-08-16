"""FastAPI dependency'lari (Z1.14).

Singleton va per-request dependency'lar.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from zet.agents.registry import AgentRegistry
from zet.agents.repository import AgentRepository
from zet.automation.engine import AutomationEngine
from zet.automation.executor import WorkflowExecutor
from zet.automation.goal import GoalRegistry
from zet.business.pg_crm import PgCRM
from zet.commerce.repository import CommerceRepository
from zet.config import Settings, get_settings
from zet.core.agent_provisioning import AgentProvisioningPolicy, AgentProvisioningService
from zet.core.executor import Executor
from zet.core.model_routing import BrainModelRouter
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.recovery import RecoveryEngine
from zet.core.state import CoreState
from zet.core.task_graph import TaskGraphExecutor
from zet.core.verifier import Verifier
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import create_engine, create_session_factory, session_scope
from zet.deploy.schedule import DailyScheduleManager
from zet.deploy.selfimprove import SelfImproveEngine
from zet.devices.repository import DeviceDBRepository
from zet.domain.command import Command, ConversationTurn
from zet.domain.enums import MessageRole, TaskClass
from zet.domain.memory import MemoryQuery, MemorySearchResult
from zet.llm.base import ChatMessage, LLMError, LLMProvider
from zet.llm.factory import build_providers
from zet.llm.routed_provider import RoutedLLMProvider
from zet.llm.router import ModelRouter
from zet.memory.conversation import ConversationStore
from zet.memory.embeddings import (
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    MistralEmbeddingProvider,
    NullEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from zet.memory.manager import MemoryManager
from zet.memory.pg_store import PgMemoryStore
from zet.monitoring.alerts import AlertManager
from zet.monitoring.notify_bridge import AlertNotificationBridge
from zet.security.approvals import ApprovalService
from zet.security.killswitch import KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.telegram.notifier import Notifier, StubNotifier
from zet.tools.builtin import build_default_registry
from zet.tools.registry import ToolRegistry
from zet.voice.azure_tts import AzureTTS
from zet.voice.elevenlabs import ElevenLabsSTT, ElevenLabsTTS
from zet.voice.stt import STTProvider, StubSTT
from zet.voice.tts import StubTTS, TTSProvider
from zet.workspace.repository import WorkspaceRepository

if TYPE_CHECKING:
    # JB-2: `Brain`/`Mission` faqat tip uchun — ish vaqtida lokal import
    # qilinadi (aylanma importdan qochish: core.brain → core.mission →
    # core.orchestrator zanjiri).
    from zet.core.brain import Brain, MissionRunner
    from zet.core.mission import Mission
    from zet.memory.store import MemoryStore

    MemoryStoreLike = MemoryStore | PgMemoryStore
else:
    MemoryStoreLike = object
"""`MemoryStore` (in-memory, testlarda) yoki `PgMemoryStore` (DB-backed,
produksiyada) — ikkalasi ham `api/routes/memory.py`da qo'llab-quvvatlanadi."""

log = structlog.get_logger(__name__)


@lru_cache(maxsize=1)
def get_killswitch() -> KillSwitchState:
    """Global killswitch holati (singleton)."""
    return KillSwitchState()


@lru_cache(maxsize=1)
def get_core_state() -> CoreState:
    """Global AI Core rejimi — Sleep/Active (singleton)."""
    return CoreState()


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


async def _memory_search_fn(
    query: str, limit: int, min_similarity: float
) -> list[MemorySearchResult]:
    """`memory.search` tooli uchun qidiruv — o'z sessiyasini ochadi.

    Tool registry global singleton, xotira esa DB sessiyasiga bog'liq.
    Shu sabab sessiya bu yerda, chaqiruv payti ochiladi — registry
    qurilganda emas.
    """
    async with session_scope(get_session_factory()) as session:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)
        memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
        return await memory.search(
            MemoryQuery(text=query, limit=limit, min_similarity=min_similarity)
        )


async def _note_memory_shadow_fn(*, title: str, path: str, preview: str, tags: list[str]):  # type: ignore[no-untyped-def]
    """A-03: `note.write` chaqirilganda memory'ga qisqa shadow yozuvi.

    Naqsh `_memory_search_fn`/`_memory_write_fn` bilan bir xil: qisqa
    DB sessiya, PgMemoryStore.add(). Fail-open — istisno chaqiruvchida
    yutiladi, note baribir yoziladi.
    """
    async with session_scope(get_session_factory()) as session:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)
        memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
        # KNOWLEDGE layer: ega o'zi yozgan eslatma → doimiy bilim manba.
        # Content — path + preview, LLM `note.read`ni ochsin.
        from zet.domain.memory import MemoryLayer

        return await memory.add(
            layer=MemoryLayer.KNOWLEDGE,
            content=f"Obsidian eslatma: {title}\nYo'l: {path}\n\n{preview}",
            summary=f"Eslatma: {title}",
            tags=tags,
            source=f"obsidian:{title}",
            trust_level="owner",  # ega o'zi yozgan, KNOWLEDGE'ga ruxsat bor
        )


async def _memory_write_fn(
    *,
    layer,  # type: ignore[no-untyped-def]  # MemoryLayer, but avoid extra import at top
    content: str,
    summary: str | None = None,
    tags: list[str] | None = None,
    trust_level: str = "system",
    ttl_hours: int | None = None,
):  # type: ignore[no-untyped-def]
    """`memory.write` tooli uchun yozish — o'z sessiyasini ochadi.

    `PgMemoryStore.add()` chaqiradi. `ttl_hours` hozircha `LAYER_TTL`
    defaultini bekor qilmaydi (repository interfeysida bunday param yo'q)
    — kelajakda per-write TTL kerak bo'lsa `add()` kengaytiriladi.

    Naqsh `_memory_search_fn` bilan bir xil: sessiya chaqiruv paytida
    ochiladi, tool registry qurilganda emas.
    """
    async with session_scope(get_session_factory()) as session:
        settings = get_settings()
        owner = await get_or_create_owner(session, external_id=settings.owner_id)
        memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
        entry = await memory.add(
            layer=layer,
            content=content,
            summary=summary,
            tags=tags,
            trust_level=trust_level,
        )
        # ttl_hours: hozircha e'tibordan chetda. Zaruratda `add()` kengaytiriladi.
        _ = ttl_hours
        return entry


@asynccontextmanager
async def _workspace_scope() -> AsyncIterator[WorkspaceRepository]:
    """`task.*`/`project.*`/`calendar.*` tool'lari uchun qisqa sessiya.

    `_memory_search_fn` bilan bir xil sabab: registry singleton, DB esa
    sessiyaga bog'liq. Sessiya chaqiruv PAYTIDA ochiladi, registry
    qurilganda emas — aks holda birinchi so'rovdagi sessiya butun jarayon
    davomida osilib qolardi.
    """
    async with session_scope(get_session_factory()) as session:
        owner = await get_or_create_owner(session, external_id=get_settings().owner_id)
        yield WorkspaceRepository(session, owner_id=owner.id)


@asynccontextmanager
async def _crm_scope() -> AsyncIterator[PgCRM]:
    """`crm.*` tool'lari uchun qisqa sessiya (Sales/Support agent uchun)."""
    async with session_scope(get_session_factory()) as session:
        owner = await get_or_create_owner(session, external_id=get_settings().owner_id)
        yield PgCRM(session, owner_id=owner.id)


@asynccontextmanager
async def _commerce_scope() -> AsyncIterator[CommerceRepository]:
    """`product.*`/`order.*`/`sales.*` tool'lari uchun qisqa sessiya."""
    async with session_scope(get_session_factory()) as session:
        owner = await get_or_create_owner(session, external_id=get_settings().owner_id)
        yield CommerceRepository(session, owner_id=owner.id)


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    """Global tool registry (singleton) — barcha builtin toollar bilan.

    Ilgari har bir so'rov bo'sh `ToolRegistry()` yaratardi — hech qanday
    tool ishlamas edi. Endi bitta joyda ro'yxatga olinadi.
    """
    settings = get_settings()
    camera_provider = None
    # RTSP umumiyroq drayver — Hikvision'dan ustun. Ega bir vaqtda
    # ikkalasini ham sozlab qo'ysa (masalan avval Hikvision'dan RTSP'ga
    # o'tayotganda) — RTSP tanlanadi, chunki generik yo'l.
    if settings.rtsp_camera_url:
        from zet.devices.rtsp import RtspCamera

        camera_provider = RtspCamera(
            rtsp_url=settings.rtsp_camera_url.get_secret_value(),
            timeout_s=settings.rtsp_camera_timeout_s,
        )
    elif settings.hikvision_host and settings.hikvision_username and settings.hikvision_password:
        from zet.devices.hikvision import HikvisionCamera

        camera_provider = HikvisionCamera(
            host=settings.hikvision_host,
            username=settings.hikvision_username,
            password=settings.hikvision_password.get_secret_value(),
            channel=settings.hikvision_channel,
        )
    return build_default_registry(
        notes_dir=settings.vault_dir,
        sites_dir=settings.sites_dir,
        enable_shell=settings.enable_shell,
        # web.read hech qanday kalit talab qilmaydi (faqat tarmoq) va
        # SSRF-himoyalangan (bloklangan host/ichki IP) — gap-analysis #12
        # topgan "default stub=True" muammosini yopish uchun doim real.
        web_reader_stub=False,
        github_token=(settings.github_token.get_secret_value() if settings.github_token else None),
        web_search_api_key=(
            settings.web_search_api_key.get_secret_value() if settings.web_search_api_key else None
        ),
        youtube_api_key=(
            settings.youtube_api_key.get_secret_value() if settings.youtube_api_key else None
        ),
        gemini_api_key=(
            settings.google_api_key.get_secret_value() if settings.google_api_key else None
        ),
        gemini_video_model=settings.gemini_video_model,
        youtube_oauth_client_id=(
            settings.youtube_oauth_client_id.get_secret_value()
            if settings.youtube_oauth_client_id
            else None
        ),
        youtube_oauth_client_secret=(
            settings.youtube_oauth_client_secret.get_secret_value()
            if settings.youtube_oauth_client_secret
            else None
        ),
        youtube_oauth_refresh_token=(
            settings.youtube_oauth_refresh_token.get_secret_value()
            if settings.youtube_oauth_refresh_token
            else None
        ),
        telegram_bot_token=(
            settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
        ),
        instagram_access_token=(
            settings.instagram_access_token.get_secret_value()
            if settings.instagram_access_token
            else None
        ),
        instagram_business_account_id=settings.instagram_business_account_id or None,
        camera_provider=camera_provider,
        memory_search_fn=_memory_search_fn,
        memory_write_fn=_memory_write_fn,
        note_memory_shadow_fn=_note_memory_shadow_fn,
        workspace_scope=_workspace_scope,
        crm_scope=_crm_scope,
        commerce_scope=_commerce_scope,
        # HR workforce management uchun (yangi talab): agent.list/pause/
        # resume/disable/stats tool'lari registry orqali ishlaydi.
        agent_registry=get_agent_registry(),
        timezone=settings.timezone,
        feed_latitude=settings.feed_latitude,
        feed_longitude=settings.feed_longitude,
        feed_news_url=settings.feed_news_url,
        feed_stock_symbols=settings.feed_stock_symbols,
        feed_currency_codes=settings.feed_currency_codes,
    )


# ── Xavfsizlik ────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_permission_policy() -> PermissionPolicy:
    """Global ruxsat siyosati (singleton).

    `auto_approve_medium` sozlamadan keladi (`ZET_AUTO_APPROVE_MEDIUM_RISK`).
    NEGA: Executor endi risk jadvalini enforce qiladi (audit fix) —
    sozlamasiz MEDIUM biznes yozuvlari (`note.write`, `task.create`,
    `crm.*`) birdan majburiy tasdiqqa o'tib, har "vazifa qo'sh" uchun
    Telegram tugmasini talab qilardi. Default `True` ilgarigi oqimni
    saqlaydi; ega bir o'zgaruvchi bilan qattiqroq rejimga o'tadi.
    HIGH darajaga bu ta'sir qilmaydi — u har doim tasdiq (V-32).
    """
    return PermissionPolicy(
        auto_approve_medium=get_settings().auto_approve_medium_risk,
    )


@lru_cache(maxsize=1)
def get_approval_service() -> ApprovalService:
    """Global tasdiq xizmati (singleton) — run so'rovlari orasida saqlanadi.

    AR-01: `session_factory` berilsa har `request_approval`/`approve`/`reject`
    DB'ga background task orqali yozib qo'yiladi (fail-open). Startup'da
    `load_pending_approvals()` PENDING approval'larni tiklaydi.
    """
    settings = get_settings()
    return ApprovalService(
        ttl_minutes=settings.approval_ttl_minutes,
        session_factory=get_session_factory(),
    )


@lru_cache(maxsize=1)
def get_run_store() -> RunStore:
    """Global run holatlari do'koni (singleton).

    AR-01: `session_factory` berilsa `persist()` orqali DB'ga write-through
    yoziladi (fail-open). Startup'da `load_pending_runs()` AWAITING_APPROVAL
    run'larni tiklaydi.
    """
    settings = get_settings()
    return RunStore(
        session_factory=get_session_factory(),
        owner_external_id=settings.owner_id,
    )


@lru_cache(maxsize=1)
def get_rate_limiter() -> object:
    """Global rate limiter (singleton) — API middleware ishlatadi.

    Ilgari `RateLimiter` qurilgan-u ASGI stack'ga ulanmagan edi
    (GAP_ANALYSIS SR-03). Endi singleton sifatida `RateLimitMiddleware`
    dan foydalaniladi."""
    from zet.security.ratelimit import RateLimiter

    return RateLimiter()


@lru_cache(maxsize=1)
def get_run_semaphore() -> asyncio.Semaphore:
    """A-07 concurrency brake: bir vaqtda ishlayotgan run'lar chegarasi.

    `deploy/config.DeployConfig.max_concurrent_runs` (default 3) ni
    ishlatadi. Singleton — barcha Orchestrator instansiyalari bir xil
    semafora ostida ishlaydi, ya'ni haqiqatan global chegara.

    Diqqat: `asyncio.Semaphore()` event loop bo'lishini talab qiladi
    (Python 3.10+), shuning uchun bu funksiya faqat aktiv loop ichida
    (endpoint handler) chaqirilishi kerak."""
    from zet.deploy.config import load_config

    limit = load_config().max_concurrent_runs
    return asyncio.Semaphore(limit)


@lru_cache(maxsize=1)
def get_daily_schedule_manager() -> DailyScheduleManager:
    """Global kunlik jadval (singleton) — V-35."""
    return DailyScheduleManager()


@lru_cache(maxsize=1)
def get_selfimprove_engine() -> SelfImproveEngine:
    """Global takomillashtirish tavsiyalari do'koni (singleton) — V-36.

    `SelfImproveDaemon` shu instansiyaga `.suggest()` yozadi. Ilgari
    engine faqat testda yashardi va prod'da hech qachon chaqirilmasdi
    (GAP_ANALYSIS §12); endi singleton — daemon va (kelajakdagi) API
    route'lari bir xil holatga tayanadi.
    """
    return SelfImproveEngine()


@lru_cache(maxsize=1)
def get_automation_engine() -> AutomationEngine:
    """Global Automation Engine (singleton) — Bo'lim 9.

    `Scheduler`/`TriggerRegistry`/`WorkflowRunner` — hozircha in-memory
    (`AgentRegistry` bilan bir xil boshlang'ich naqsh; DB-persistensiya
    keyingi bosqich). `AutomationDaemon` va API route'lari shu orqali
    bir xil holatga ulanadi.
    """
    return AutomationEngine()


@lru_cache(maxsize=1)
def get_goal_registry() -> GoalRegistry:
    """Global maqsadlar registri (singleton) — 5-xususiyat (mustaqillik).

    `AutomationEngine` bilan bir xil naqsh: hozircha in-memory,
    DB-persistensiya keyingi bosqich.
    """
    return GoalRegistry()


# `get_workflow_executor()` — pastda, `get_model_router()`dan keyin (Depends
# bog'liqligi sabab: RoutedLLMProvider request-scoped router talab qiladi).


# ── Monitoring / Alerts ───────────────────────────────────────────


@lru_cache(maxsize=1)
def get_notifier() -> Notifier:
    """Global bildirishnoma yuboruvchi (singleton).

    Telegram token va kamida bitta owner ID sozlangan bo'lsa — haqiqiy
    `TelegramNotifier` (Bot API orqali yuboradi). Aks holda `StubNotifier`
    (xotirada saqlaydi, hech qayerga yubormaydi) — masalan testlarda yoki
    hali sozlanmagan o'rnatishda.
    """
    settings = get_settings()
    owner_ids = settings.telegram_owner_id_set
    if settings.telegram_bot_token is not None and owner_ids:
        from zet.telegram.http_notifier import TelegramNotifier

        return TelegramNotifier(
            token=settings.telegram_bot_token.get_secret_value(),
            owner_chat_id=next(iter(owner_ids)),
        )
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


# ── Xotira ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Global embedding provayder (singleton) — muhitga qarab tanlanadi.

    Ilgari bu doim `OllamaEmbeddingProvider` qaytarardi. Lokal ishlarda
    to'g'ri (ADR-0007 local-first), lekin **Railway'da Ollama yo'q** —
    ya'ni produksiyada `embed()` har safar `None` qaytarardi va semantik
    qidiruv jimgina o'chiq turardi. Z39.2 bulut provayderlarini qo'shdi.

    Fail-open o'zgarmaydi: provayder ishlamasa `embed()` xato ko'tarmasdan
    `None` qaytaradi, qidiruv/yozish kalit-so'z rejimida davom etadi.
    """
    settings = get_settings()
    provider = _resolve_embedding_provider(settings)
    log.info(
        "embeddings.provider_selected",
        configured=settings.embedding_provider,
        resolved=provider.model_id,
    )
    return provider


def _resolve_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Sozlama va mavjud kalitlarga qarab embedding provayderini tanlash.

    `auto` qoidasi bitta haqiqatdan kelib chiqadi: **bulutda Ollama yo'q**.
    Railway konteynerida mahalliy model ishlamaydi, shu sabab prod'da
    bulut kaliti qidiriladi; dev'da esa Ollama (ADR-0007 local-first).

    Tanlov TARMOQQA BOG'LIQ EMAS — faqat konfiguratsiyaga qaraydi.
    Shunday bo'lgani uchun bir ishga tushishda provayder o'zgarmaydi va
    barcha yozuvlar bitta vektor fazosida qoladi.
    """
    choice = settings.embedding_provider
    google = settings.google_api_key
    mistral = settings.mistral_api_key

    if choice == "auto":
        if not settings.is_prod:
            choice = "ollama"
        elif google is not None:
            choice = "gemini"
        elif mistral is not None:
            choice = "mistral"
        else:
            log.warning("embeddings.no_cloud_key_in_prod")
            choice = "none"

    if choice == "gemini" and google is not None:
        return GeminiEmbeddingProvider(
            api_key=google.get_secret_value(),
            model=settings.gemini_embed_model,
        )
    if choice == "mistral" and mistral is not None:
        return MistralEmbeddingProvider(
            api_key=mistral.get_secret_value(),
            model=settings.mistral_embed_model,
        )
    if choice == "ollama":
        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embed_model,
        )

    if choice not in {"none", "ollama"}:
        # Provayder so'ralgan, lekin kaliti yo'q — jimgina boshqasiga
        # o'tib ketmaymiz, chunki bu vektor fazosini bildirmasdan
        # almashtirardi. Semantik qidiruv ochiq ravishda o'chadi.
        log.warning("embeddings.key_missing", requested=choice)
    return NullEmbeddingProvider()


async def get_memory_store(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
    embedder: EmbeddingProvider = Depends(get_embedding_provider),
) -> PgMemoryStore:
    """So'rov chegarasidagi DB-backed xotira do'koni.

    Ilgari bu funksiya doim in-memory `MemoryStore()` qaytarardi —
    ma'lumotlar restart'da yo'qolardi (gap-analysis #5). Endi har bir
    so'rov `PgMemoryStore` orqali haqiqiy jadvalga yozadi/o'qiydi;
    ma'lumotlar restart'dan keyin ham saqlanadi. `embedder` orqali
    semantik (vektor) qidiruv ham qo'shiladi — Ollama ulanmagan bo'lsa
    kalit-so'z rejimiga tushadi.

    Testlarda `app.dependency_overrides[get_memory_store]` orqali
    sinxron `MemoryStore()` bilan almashtirilishi mumkin — routerlar
    ikkalasini ham qo'llab-quvvatlaydi (`_maybe_await`).
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    return PgMemoryStore(session, owner_id=owner.id, embedder=embedder)


async def get_memory_manager(
    store: MemoryStoreLike = Depends(get_memory_store),
) -> MemoryManager:
    """So'rov chegarasidagi `MemoryManager` — REST route policy'ni chetlab o'tmasin uchun.

    NEGA. Ilgari `api/routes/memory.py::add_memory` `store.add()`ni to'g'ridan-
    to'g'ri chaqirib `check_write` policy'ni o'tkazib yuborardi — faqat
    `memory.write` tooli qoidani majbur qilardi (`docs/AUDIT_GAPS` #4). Endi
    HTTP yozuvlari ham `MemoryManager.aremember()` orqali yagona policy
    darvozasidan o'tadi. Store dependency (`get_memory_store`) o'zgarmadi —
    testlar hali ham `MemoryStore()` bilan override qila oladi.
    """
    return MemoryManager(store=store)


# ── Trust level (xotira siyosati uchun) ───────────────────────────

# `memory/policy.py::WRITE_POLICY`/`READ_POLICY` kalitlari — API qatlami
# faqat shu qiymatlarni qabul qiladi (yasama qiymat 400 qaytaradi).
_ALLOWED_TRUST_LEVELS: frozenset[str] = frozenset({"owner", "system", "untrusted"})


def get_caller_trust_level(
    x_trust_level: str | None = Header(default=None, alias="X-Trust-Level"),
) -> str:
    """So'rov mualifining trust_level'ini qaytaradi.

    Manba — `X-Trust-Level` header (kelajakda auth kontekstidan ham
    olinishi mumkin). Header berilmasa — default `"owner"`: bu
    backward-compat uchun, ya'ni ilgari policy'ni bilmagan mijozlar va
    testlar avvalgidek OWNER huquqi bilan ishlaydi.

    Noto'g'ri qiymatda 400 qaytariladi — jimgina `frozenset().get(x)` yo'q
    deb qaytish policy'ni bypass qilardi (xotira allaqachon yozib bo'lgan
    bo'lardi, faqat 403 emas 200 tushib).
    """
    if x_trust_level is None or x_trust_level == "":
        return "owner"
    normalized = x_trust_level.strip().lower()
    if normalized not in _ALLOWED_TRUST_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"noto'g'ri X-Trust-Level: {x_trust_level!r} "
                f"(ruxsat etilgan: {sorted(_ALLOWED_TRUST_LEVELS)})"
            ),
        )
    return normalized


# ── Agentlar ──────────────────────────────────────────────────────


def get_agent_repository(
    session: AsyncSession = Depends(get_db_session),
) -> AgentRepository:
    """So'rov chegarasidagi agent DB-persistensiya qatlami.

    Ilgari `db/models/agent.py`dagi jadval hech qachon ishlatilmasdi —
    Agent Factory orqali yaratilgan agentlar faqat `AgentRegistry`
    (in-memory) da yashardi, restart'da yo'qolardi (gap-analysis #1).
    `AgentRegistry`ning o'zi (runtime uchun yagona manba) o'zgarmaydi —
    bu faqat write-through: har bir o'zgarish shu orqali ham DB'ga yoziladi.
    """
    return AgentRepository(session)


# ── Qurilmalar ────────────────────────────────────────────────────


async def get_device_repository(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> DeviceDBRepository:
    """So'rov chegarasidagi qurilma repozitoriysi (Bo'lim 8, GAP_ANALYSIS #12).

    Ilgari `DeviceRegistry` (in-memory) hech qanday route/tool bilan
    bog'lanmagan edi — iPhone/Mac boshqaruvi mumkin bo'lgani ma'lum
    edi-yu, bunga tayanadigan hech nima yo'q edi (fixture'lardan boshqa).
    Bu funksiya API va tool qatlami uchun DB-backed variantni ulaydi;
    eski `DeviceRegistry` deprekatsiya belgisi bilan ham qoladi (orqaga
    moslik).
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    return DeviceDBRepository(session, owner_id=owner.id)


# ── CRM ───────────────────────────────────────────────────────────


async def get_crm(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> PgCRM:
    """So'rov chegarasidagi DB-backed CRM (Bo'lim 6, C-03).

    Ilgari `business/crm.py`dagi `CRM` hech qanday DB jadvali, route yoki
    tool bilan bog'lanmagan edi — butunlay o'lik kod (gap-analysis).
    `docs/04-CONSTRAINTS.md` C-03 CRM'ni birinchi biznes ustuvorlik deb
    belgilagan; endi shu orqali haqiqiy jadvallarga yoziladi/o'qiladi.
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    return PgCRM(session, owner_id=owner.id)


async def load_conversation_history(channel: str) -> list[ConversationTurn]:
    """Kanal suhbatining oxirgi almashuvlari (Z47.1).

    FAIL-OPEN: baza yetib bo'lmasa BO'SH ro'yxat qaytadi va ZET
    javob berishda davom etadi — tarixsiz, lekin jim qolmasdan.
    Xotira nosozligi eganing savolini javobsiz qoldirmasligi kerak.

    Sessiya bu yerda, chaqiruv paytida ochiladi. `Depends` orqali
    ulash butun `/run` route'ini DB'ga bog'lab qo'yardi: baza
    o'chganda so'rov handler'gacha ham yetib bormay 500 bo'lardi.
    """
    try:
        async with session_scope(get_session_factory()) as session:
            settings = get_settings()
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            store = ConversationStore(session, owner_id=owner.id)
            conversation = await store.get_or_create(channel=channel)
            return await store.recent_history(conversation)
    except Exception:
        log.warning("conversation.history_unavailable", channel=channel)
        return []


async def save_conversation_turn(channel: str, *, user_text: str, reply: str) -> None:
    """Almashuvni saqlaydi — FAIL-OPEN (yuqoridagi izohga qarang)."""
    try:
        async with session_scope(get_session_factory()) as session:
            settings = get_settings()
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            store = ConversationStore(session, owner_id=owner.id)
            conversation = await store.get_or_create(channel=channel)
            await store.append(conversation, role=MessageRole.USER, content=user_text)
            await store.append(conversation, role=MessageRole.ASSISTANT, content=reply)
    except Exception:
        log.warning("conversation.save_failed", channel=channel)


async def get_workspace(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> WorkspaceRepository:
    """So'rov chegarasidagi ish maydoni repozitoriysi (Z46).

    `/projects`, `/tasks`, `/calendar` sahifalari ortida hech narsa
    yo'q edi — uchalasi frontend fayli ichidagi qotirilgan massivdan
    chizilardi. Endi shu orqali haqiqiy jadvallar bilan ishlanadi.
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    return WorkspaceRepository(session, owner_id=owner.id)


# ── Savdo ─────────────────────────────────────────────────────────


async def get_commerce(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> CommerceRepository:
    """So'rov chegarasidagi savdo repozitoriysi (Z51).

    `get_workspace` bilan bir xil naqsh: mahsulot/buyurtma sahifalari
    ortida hech narsa yo'q edi — endi shu orqali haqiqiy jadvallarga
    yoziladi/o'qiladi.
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    return CommerceRepository(session, owner_id=owner.id)


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


def get_workflow_executor(
    engine: AutomationEngine = Depends(get_automation_engine),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    router: ModelRouter = Depends(get_model_router),
) -> WorkflowExecutor:
    """So'rov chegarasidagi Workflow Executor — workflow zanjirini haqiqiy LLM bilan bajaradi.

    Ilgari `FakeProvider()` qattiq kodlangan edi — endi `RoutedLLMProvider`
    orqali real `ModelRouter`ga ulanadi (agent.model_policy → TaskClass).
    """
    return WorkflowExecutor(
        workflows=engine.workflows,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        provider=RoutedLLMProvider(router),
    )


# ── Uzoq muddatli xotirani eslash ─────────────────────────────────

RECALL_LIMIT = 4
"""Javobga qo'shiladigan xotira yozuvlari soni.

Ko'paytirish kontekstni boyitadi, lekin har so'rov narxini oshiradi va
mavzudan uzoq yozuvlarni ham tortadi."""

RECALL_MIN_SIMILARITY = 0.35
"""Shu chegaradan pastdagi yozuv qo'shilmaydi.

Past chegara "hamma narsa tegishli" degan shovqin beradi va LLM'ni
chalg'itadi — ega profilining butun matni har savolga ilashib chiqardi."""


def _build_recall(memory: PgMemoryStore) -> Callable[[str], Awaitable[list[str]]]:
    """So'rov matnidan tegishli xotira yozuvlarini topuvchi funksiya.

    `Executor` xotira implementatsiyasini bilmaydi — unga faqat shu
    funksiya beriladi (test uchun oddiy lambda bilan almashtiriladi).
    """

    async def recall(query: str) -> list[str]:
        results = await memory.search(
            MemoryQuery(text=query, limit=RECALL_LIMIT, min_similarity=RECALL_MIN_SIMILARITY)
        )
        return [r.entry.content for r in results]

    return recall


def get_recall(
    settings: Settings = Depends(get_config),
) -> Callable[[str], Awaitable[list[str]]]:
    """Xotira qidiruvini **kech** ochiladigan sessiya bilan bog'laydi.

    NEGA `Depends(get_memory_store)` EMAS. U so'rov boshlanishidayoq DB
    sessiyasi ochadi va bu `get_orchestrator`ga bog'liq HAR bir endpoint'ni
    DB'ga bog'lab qo'yardi — `GET /run/{id}` (404) va bo'sh xabar (422)
    kabi DB talab qilmaydigan yo'llar ham 500 qaytara boshlagan edi.

    Bu yerdagi yopilma sessiyani faqat haqiqatan qidiruv kerak bo'lganda
    ochadi; DB yo'q bo'lsa istisno `Executor._think` ichida ushlanadi va
    javob xotirasiz yoziladi (fail-open).
    """

    async def recall(query: str) -> list[str]:
        async with session_scope(get_session_factory()) as session:
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
            return await _build_recall(memory)(query)

    return recall


# ── Orchestrator ──────────────────────────────────────────────────


async def _default_audit(**kwargs: object) -> None:
    """Executor'dan chaqiriladigan audit yozuvchi (SR-02).

    `write_audit`ni `get_session_factory()` bilan yopadi — Executor DB'ni
    to'g'ridan-to'g'ri bilmaydi (naqsh `_memory_search_fn`/`_workspace_scope`
    bilan bir xil)."""
    from zet.security.audit_writer import write_audit

    await write_audit(get_session_factory(), **kwargs)  # type: ignore[arg-type]


async def _default_mark_verified(run_id: uuid.UUID, verified_ok: bool) -> None:
    """A-04 feedback loop: Router'dan mark_run_verified'ni chaqiradi."""
    import uuid as _uuid  # noqa: F401 — global uuid shadowing xato bermasin

    from zet.llm.router import mark_run_verified

    await mark_run_verified(get_session_factory(), run_id, verified_ok=verified_ok)


class _VerifierJudgeProvider:
    """Verifier LLM-judge uchun yengil adapter — ModelRouter'ga TaskClass.SIMPLE
    (T1_FREE) bilan chaqiradi.

    V-01: uzun jonli-tildagi expected_outcome uchun arzon LLM'dan
    "OK / FAIL" so'raladi. `RoutedLLMProvider` `model` argumentini talab
    qiladi, Verifier esa uni bilmaydi (ATOMic .complete(messages=, system=)
    interfeysi). Shu sabab yengil adapter — chaqiruvni router'ga qaytaradi.
    Fail-open: router yiqilsa Verifier eski xatti-harakatga tushadi."""

    def __init__(self, router: ModelRouter) -> None:
        self._router = router

    async def complete(self, *, messages, system=None, max_tokens=120, **_):  # type: ignore[no-untyped-def]
        from zet.domain.enums import TaskClass

        result = await self._router.complete(
            task_class=TaskClass.SIMPLE,
            messages=messages,
            system=system,
            max_tokens=max_tokens,
        )
        return result.response


def _build_verifier_judge(router: ModelRouter) -> object:
    return _VerifierJudgeProvider(router)


def _build_brain(
    *,
    orchestrator: Orchestrator,
    settings: Settings,
) -> Brain:
    """`Brain` quradi — barcha kanallar uchun bir xil wiring (JB-2).

    NEGA yordamchi: Telegram `_runner` va HTTP `get_brain` bir xil
    marshrutlashga ega bo'lishi SHART. Ikki joyda alohida qurilsa
    kanallar orasida xatti-harakat sekin-asta farqlanib ketardi —
    bu repoda allaqachon bir marta yuz bergan (Telegram recovery/
    notifier'siz qolgan edi, D4 va F1 tuzatishlari).

    NEGA sessiya ARGUMENT EMAS: `Brain` oddiy suhbat uchun DB'ga
    umuman tegmasligi kerak. Sessiya faqat HAQIQATAN goal kelganda,
    mission runner ichida ochiladi — aks holda har bir "salom" xabari
    Postgres ulanishini talab qilardi.

    Mission runner sozlama o'chirilganda UMUMAN qurilmaydi: bunda
    Brain triajga LLM ham sarflamaydi.
    """
    from zet.core.agent_selector import AgentSelector
    from zet.core.background_workflow import BackgroundWorkflowBridge
    from zet.core.brain import Brain
    from zet.core.execution_mode import ExecutionModeClassifier
    from zet.core.workflow_command import WorkflowCommandExecutor

    mission_runner: MissionRunner | None = None
    if settings.brain_goal_missions:

        async def _run_mission(command: Command) -> Mission:
            from zet.db.session import session_scope

            # Kechiktirilgan qurilish: MissionOrchestrator og'ir
            # (repository + context engine + capability composer) va
            # DB sessiya talab qiladi — faqat goal kelganda quramiz.
            async with session_scope(get_session_factory()) as session:
                mission_orchestrator = await get_mission_orchestrator(
                    session=session,
                    orchestrator=orchestrator,
                    approval_service=get_approval_service(),
                    permission_policy=get_permission_policy(),
                    killswitch=get_killswitch(),
                    notifier=get_notifier(),
                    router=ModelRouter(get_llm_providers(), session, settings),
                    settings=settings,
                )
                # `get_mission_orchestrator` forward-ref sabab tipsiz
                # (Any) — natijani aniq tipga bog'laymiz.
                mission: Mission = await mission_orchestrator.run(
                    command, owner_id=mission_orchestrator.owner_id
                )
                return mission

        mission_runner = _run_mission

    # ── JB-9: Scheduler/AutomationEngine integratsiyasi ────────────
    workflow_command_executor: WorkflowCommandExecutor | None = None
    background_workflow_bridge: BackgroundWorkflowBridge | None = None
    schedule_persister: Callable[[], Awaitable[None]] | None = None
    if settings.brain_workflow_integration_enabled:
        engine = get_automation_engine()
        workflow_command_executor = WorkflowCommandExecutor(engine.scheduler)
        background_workflow_bridge = BackgroundWorkflowBridge(
            automation_engine=engine,
            # `AgentSelector` Protocol contravariance (JB-5/JB-6 bilan bir xil
            # naqsh) — concrete `AgentRegistry.list_agents(status: AgentStatus)`
            # va Protocol'ning `status: object` orasidagi mypy nomuvofiqligi.
            agent_selector=AgentSelector(get_agent_registry()),  # type: ignore[arg-type]
        )

        async def _persist_engine_state() -> None:
            # Mavjud `automation/persistence.py` naqshi bilan bir xil:
            # fail-open, owner shu process settings'idan.
            from zet.automation.persistence import persist_automation

            await persist_automation(
                engine,
                get_session_factory(),
                owner_external_id=settings.owner_id,
            )

        schedule_persister = _persist_engine_state

    return Brain(
        orchestrator=orchestrator,
        # AYNAN orchestrator'ning recognizer'i — bir run doirasidagi
        # barcha LLM chaqiruvlari bitta router (bitta budjet hisobi,
        # testlarda bitta provayder) orqali o'tishi kerak.
        intent_recognizer=orchestrator.intent_recognizer,
        tool_names=get_tool_registry().tool_names(),
        mission_runner=mission_runner,
        # Mission javobining MATNI oxirgi run yozuvidan olinadi.
        run_lookup=orchestrator.run_store.get,
        goal_missions_enabled=settings.brain_goal_missions,
        execution_mode_classifier=(
            ExecutionModeClassifier() if settings.brain_execution_mode_enabled else None
        ),
        workflow_command_executor=workflow_command_executor,
        background_workflow_bridge=background_workflow_bridge,
        schedule_persister=schedule_persister,
    )


def _build_world_state_provider(settings: Settings) -> Callable[[], Awaitable[str]]:
    """Muhit holatini yig'uvchi (JB-3) — Orchestrator'ga uzatiladi.

    Har chaqiruvda O'Z sessiyasini ochadi: `Orchestrator` so'rov
    chegarasidagi sessiyaga bog'lanib qolmasligi kerak (Telegram
    daemon oqimlarida u umuman bo'lmasligi mumkin). Sessiya faqat
    run boshida, bir marta ochiladi.

    To'liq fail-open: manba o'qilmasa `WorldStateBuilder` uni
    `unavailable`ga yozadi, butun blok yiqilsa bo'sh matn qaytadi.
    """

    async def _provider() -> str:
        from zet.core.mission_repository import MissionRepository
        from zet.core.world_state import WorldStateBuilder, build_world_state_text
        from zet.db.session import session_scope
        from zet.llm.budget import BudgetGuard

        async with session_scope(get_session_factory()) as session:
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            ledger = BudgetGuard(session, settings)
            builder = WorldStateBuilder(
                core_state=get_core_state(),
                killswitch=get_killswitch(),
                agent_registry=get_agent_registry(),
                approvals=get_approval_service(),
                workspace=WorkspaceRepository(session, owner_id=owner.id),
                mission_repo=MissionRepository(session, owner_id=owner.id),
                budget_snapshot=ledger.snapshot,
            )
            return await build_world_state_text(builder)

    return _provider


def _build_task_graph_executor(
    router: ModelRouter,
    *,
    session: AsyncSession,
) -> TaskGraphExecutor:
    """JB-5: `MissionEngine`ga ulanadigan Task Graph Executor — har mission-task
    HAQIQIY LLM (`RoutedLLMProvider`) orqali, o'ziga tayinlangan agent va
    FAQAT o'ziga ruxsat etilgan tool bilan ishlaydi.

    NEGA global singleton'lar (`get_agent_registry()`, `get_tool_registry()`,
    `get_permission_policy()`): `MissionEngine`ning qolgan qismlari
    (Orchestrator, Executor, mission-level `tool_registry.subset()`) ham
    AYNAN shu singleton'larga tayanadi — Task Graph tasklari boshqa
    tool/agent "olamida" ishlasa, mission-level tanlov bilan nomuvofiqlik
    yuzaga kelardi.

    `is_autonomous=True` — `RoutedLLMProvider`ning kost/kvota hisoblash
    yorlig'i (har task ega kutmasdan ishlaydi), XAVFSIZLIK GATE'I EMAS:
    V-32 (majburiy tasdiq) baribir `AgentRuntime._execute_tool()` orqali
    fail-closed enforce qilinadi (`task_graph.py` docstring'iga qarang).

    JB-6: `agent_auto_provisioning_enabled` yoqilgan bo'lsa (default —
    `_build_agent_provisioning_service()`ga qarang), CapabilityGap'lar
    endi mavjud `AgentFactory` pipeline'iga ulanadi — `session` shu
    sabab talab qilinadi (Factory yaratgan agent DB'ga yozilishi uchun,
    `AgentRepository` orqali — restart'da yo'qolmasin).

    JB-7: `brain_model_routing_enabled` yoqilgan bo'lsa, har task uchun
    `BrainModelRouter` orqali ALOHIDA `TaskClass` tanlanadi (agentning
    statik tieridan mustaqil) — `core/model_routing.py`ga qarang.
    """
    settings = get_settings()
    return TaskGraphExecutor(
        agent_registry=get_agent_registry(),
        tool_registry=get_tool_registry(),
        permission_policy=get_permission_policy(),
        llm_provider=RoutedLLMProvider(router, is_autonomous=True),
        agent_provisioner=_build_agent_provisioning_service(session),
        model_router=BrainModelRouter() if settings.brain_model_routing_enabled else None,
        # JB-12: Mission/TaskGraph — asosiy ijro dvigateli — endi
        # killswitch'ni real tekshiradi (ilgari butunlay "ko'r" edi).
        killswitch=get_killswitch(),
    )


def _build_agent_provisioning_service(session: AsyncSession) -> AgentProvisioningService | None:
    """JB-6: CapabilityGap → AgentFactory ulanishi — `Settings` orqali
    o'chirilishi mumkin (fail-safe: `False` bo'lsa JB-5 xatti-harakatiga
    qaytadi, `TaskGraphExecutor(agent_provisioner=None)` bilan bir xil).
    """
    settings = get_settings()
    if not settings.agent_auto_provisioning_enabled:
        return None
    return AgentProvisioningService(
        agent_registry=get_agent_registry(),
        agent_repository=AgentRepository(session),
        killswitch=get_killswitch(),
        policy=AgentProvisioningPolicy(
            auto_create_max_risk=settings.agent_auto_provision_max_risk,
            disabled_min_risk=settings.agent_provision_disabled_min_risk,
        ),
    )


def _build_recovery_engine(
    *,
    router: ModelRouter,
    tool_registry: ToolRegistry,
    permission_policy: PermissionPolicy,
    killswitch: KillSwitchState,
    budget_usd: float,
    recall: Callable[[str], Awaitable[list[str]]],
) -> RecoveryEngine:
    """PART 6 Recovery Engine quradi — D4 (KONSOLIDATSIYA v2): `Orchestrator`
    doim `recovery_engine=None` bilan ishga tushirilgan wiring gap'ini yopadi.

    NEGA HOZIRGACHA `None` edi: `RecoveryEngine` (`core/recovery.py`, 47+
    testi bilan sinalgan, FAIL→DIAGNOSE→FIX→RETRY→VERIFY sikli to'liq
    implementatsiya qilingan) hech qachon bu yerda QURILMAGAN — natijada
    PART 6 KOD DARAJASIDA mavjud bo'lsa ham ISHLAB CHIQARISHDA hech qachon
    chaqirilmagan: har muvaffaqiyatsiz `verify_run` darhol `FAILED`ga
    o'tgan, ega HECH QANDAY tuzatish urinishini ko'rmagan
    (AUTONOMY_AUDIT §2.5 talabiga zid).

    LLM provider — Verifier LLM-judge bilan BIR XIL arzon T1_FREE tier
    (`_build_verifier_judge`) — diagnos chaqiruvi qimmat model talab
    qilmaydi (`recovery.py`da `max_tokens=600` hardcoded).

    MA'LUM CHEKLOV (documented, D1/D2/D3 xavfsizlik talablariga TA'SIR
    QILMAYDI): retry executor'ning `command_text`/`history`/`run_id`
    bo'sh/`None` qoladi, chunki bu funksiya Orchestrator QURILISHI
    PAYTIDA chaqiriladi — `record` (demak uning `command.text`/`history`/
    `run_id`) hali mavjud emas (`_run_plan()` bosqichigacha yo'q). Natija:
    recovery RETRY qadamidagi fikrlash (`_think()`) original suhbat
    tarixini KO'RMAYDI — javob sifati pasayishi mumkin (lekin NOTO'G'RI
    emas — bo'sh tarix bilan ishlaydi), xarajat esa CostLedger'da
    run_id'ga bog'lanmay qoladi (jamlanma summasi baribir to'g'ri).
    Approval gate va hard-limit'lar (D1/D2/D3) `Executor.policy.check()`
    va `RecoveryEngine._max_retries` darajasida — kontekstdan MUSTAQIL,
    shuning uchun bu cheklov xavfsizlikka ta'sir qilmaydi.
    """
    judge = _build_verifier_judge(router)

    def _executor_factory() -> Executor:
        return Executor(
            registry=tool_registry,
            policy=permission_policy,
            killswitch=killswitch,
            budget_usd=budget_usd,
            router=router,
            recall=recall,
        )

    return RecoveryEngine(
        llm_provider=judge,  # type: ignore[arg-type]
        executor_factory=_executor_factory,
        verifier=Verifier(llm_judge_provider=judge),  # type: ignore[arg-type]
        audit_fn=_default_audit,
        tool_names=set(tool_registry.tool_names()),
    )


@lru_cache(maxsize=1)
def get_capability_registry() -> object:
    """Global CapabilityRegistry (singleton) — builtin capability'lar bilan.

    Registry pastdan yuqoriga bir marta qurilishi shart (aylanma dep
    hosil qilmaslik uchun) — shu sabab lru_cache ostida singleton.
    """
    from zet.core.capability import CapabilityRegistry, builtin_capabilities

    registry = CapabilityRegistry()
    registry.register_many(builtin_capabilities())
    return registry


async def build_orchestrator_for_session(
    session: AsyncSession, settings: Settings
) -> Orchestrator:
    """FastAPI DI'siz, berilgan sessiya ustida to'liq `Orchestrator` quradi.

    MUHIM (JB-11 bug fix): `get_orchestrator()` FastAPI `Depends(...)`
    marker obyektlariga tayanadi — HAR BIR parametri
    `Depends(get_xxx)` bilan default qilingan. FastAPI DI konteksti
    TASHQARISIDA (masalan `api/app.py`ning `lifespan()` funksiyasida)
    uni bare (`get_orchestrator()`) chaqirish `settings` parametrini
    `Depends`ning O'ZIGA bog'laydi — keyingi `settings.run_max_usd`
    o'qish `AttributeError` beradi. JB-10 mission-recovery wiring'i
    aynan shu xatoga tushib, `except Exception` orqali JIMGINA
    yutilgan edi — ya'ni mission recovery HECH QACHON ishlamagan.

    Bu funksiya — Telegram `_orchestrator_runner`/`_approval_runner`
    (`get_telegram_bot()` ichida) allaqachon ishlatib kelayotgan QO'LDA
    QURISH naqshining, endi qayta ishlatiladigan versiyasi. Har
    chaqiruvda YANGI `Orchestrator` quradi (session-scoped — Telegram
    bilan bir xil sabab: `ModelRouter` sessiyaga bog'langan).
    """
    router = ModelRouter(get_llm_providers(), session, settings)
    tool_registry = get_tool_registry()
    permission_policy = get_permission_policy()
    killswitch = get_killswitch()
    memory = PgMemoryStore(
        session,
        owner_id=(await get_or_create_owner(session, external_id=settings.owner_id)).id,
        embedder=get_embedding_provider(),
    )
    recall = _build_recall(memory)
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        approval_service=get_approval_service(),
        killswitch=killswitch,
        run_store=get_run_store(),
        budget_usd=settings.run_max_usd,
        max_steps=settings.run_max_steps,
        recall=recall,
        audit_fn=_default_audit,
        mark_verified_fn=_default_mark_verified,
        run_timeout_s=settings.run_timeout_s,
        concurrency_semaphore=get_run_semaphore(),
        verifier_judge_provider=_build_verifier_judge(router),
        recovery_engine=_build_recovery_engine(
            router=router,
            tool_registry=tool_registry,
            permission_policy=permission_policy,
            killswitch=killswitch,
            budget_usd=settings.run_max_usd,
            recall=recall,
        ),
        notifier=get_notifier(),
        world_state_provider=_build_world_state_provider(settings),
    )


async def build_brain_for_session(session: AsyncSession, settings: Settings) -> Brain:
    """FastAPI DI'siz, berilgan sessiya ustida to'liq `Brain` quradi (JB-12).

    `build_orchestrator_for_session()`ning to'g'ridan-to'g'ri davomi —
    `_build_brain()` (barcha kanallar — Telegram, HTTP — uchun BIR XIL
    wiring, `_build_brain` docstring'iga qarang) FastAPI `Depends(...)`ga
    tayanmaydi (faqat `orchestrator`/`settings` — aniq argumentlar), shuning
    uchun uni ham request kontekstidan tashqarida (masalan
    `AutomationDaemon`ning scheduled-fire yo'lida, JB-12 §2) xavfsiz
    chaqirish mumkin — xuddi JB-11 `build_orchestrator_for_session()` kabi.

    NEGA KERAK: Scheduler → Brain integratsiyasi (JB-12) uchun
    `AutomationDaemon` — FastAPI request emas, fon tsikli — HAR fire
    uchun o'zining sessiyasi ustida to'liq, HAQIQIY Brain qurishi kerak
    (Mission/Task Graph/AgentSelector/ModelRouter — hammasi SHU orqali).
    Bu yordamchisiz daemon Brain'ni FAQAT `api.deps`ning ichki
    (`_build_brain`) yoki noto'g'ri (bare `Depends(...)`) chaqiruvi bilan
    qurishga majbur bo'lardi — JB-11 aynan shu turdagi xatoni topgan edi.
    """
    orchestrator = await build_orchestrator_for_session(session, settings)
    return _build_brain(orchestrator=orchestrator, settings=settings)


def get_orchestrator(
    router: ModelRouter = Depends(get_model_router),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    approval_service: ApprovalService = Depends(get_approval_service),
    killswitch: KillSwitchState = Depends(get_killswitch),
    run_store: RunStore = Depends(get_run_store),
    settings: Settings = Depends(get_config),
    recall: Callable[[str], Awaitable[list[str]]] = Depends(get_recall),
) -> Orchestrator:
    """So'rov chegarasidagi Orchestrator — Intent→Plan→Execute→Verify oqimi.

    `recall` — uzoq muddatli xotira. Telegram oqimi bilan bir xil bo'lishi
    uchun bu yerda ham ulanadi: aks holda web/API orqali savol berilganda
    ZET ega profilini ko'rmasdi, Telegram orqali esa ko'rardi.
    """
    return Orchestrator(
        router=router,
        tool_registry=tool_registry,
        permission_policy=permission_policy,
        approval_service=approval_service,
        killswitch=killswitch,
        run_store=run_store,
        budget_usd=settings.run_max_usd,
        max_steps=settings.run_max_steps,
        recall=recall,
        audit_fn=_default_audit,
        mark_verified_fn=_default_mark_verified,
        run_timeout_s=settings.run_timeout_s,
        concurrency_semaphore=get_run_semaphore(),
        verifier_judge_provider=_build_verifier_judge(router),
        # D4 (KONSOLIDATSIYA v2): PART 6 Recovery Engine — ilgari doim
        # `None` edi (verify FAIL → darhol FAILED, tuzatish urinishisiz).
        # `_build_recovery_engine()`ning "ma'lum cheklov" izohiga qarang.
        recovery_engine=_build_recovery_engine(
            router=router,
            tool_registry=tool_registry,
            permission_policy=permission_policy,
            killswitch=killswitch,
            budget_usd=settings.run_max_usd,
            recall=recall,
        ),
        # F1 (BLOCK-3 audit): AWAITING_APPROVAL'ga o'tganda Telegram inline
        # tugmali xabar. Token/owner sozlanmasa get_notifier() StubNotifier
        # qaytaradi — hech qanday tarmoq chaqiruvi bo'lmaydi (fail-open).
        # JB-3: muhit holati (ochiq vazifalar, loyihalar, kutilayotgan
        # tasdiqlar, budjet) reja va javob promptlariga qo'shiladi —
        # ilgari model bularning hech birini ko'rmasdi.
        world_state_provider=_build_world_state_provider(settings),
        notifier=get_notifier(),
    )


async def build_mission_engine_for_session(
    session: AsyncSession,
    orchestrator: Orchestrator,
    approvals: ApprovalService,
    *,
    killswitch: KillSwitchState | None = None,
):  # type: ignore[no-untyped-def]  # local imports return non-exported types
    """Approve/reject endpoint uchun kichik yordamchi: sessiya ustida MissionEngine.

    Adversarial verify topgan HIGH bug'ni tuzatish uchun kerak: mission-level
    approval'lar `Orchestrator.approve()` orqali o'ta olmasdi (RunStore'da
    mission.id yo'q). Endi approvals endpoint mission_id ni ko'rgach shu
    yordamchi orqali MissionEngine ochib `approve()`/`run_to_completion()`
    ni chaqiradi. Sessiya ochilgan kontekstda saqlanadi (chaqiruvchi
    `async with session_scope(...)` bloki ichida).

    `killswitch` (JB-12, ixtiyoriy): berilsa `MissionEngine.run_to_completion()`
    har faza o'tishidan oldin tekshiradi — chaqiruvchi (`app.py` restart
    recovery, `approvals.py` approve endpoint) `get_killswitch()`ni uzatishi
    tavsiya etiladi. Berilmasa — eski xatti-harakat (tekshiruvsiz).
    """
    from zet.core.capability import CapabilityRegistry
    from zet.core.context import ContextEngine
    from zet.core.mission import MissionEngine, MissionRecoveryAdapter
    from zet.core.mission_orchestrator import (
        CapabilityRegistryComposer,
        ContextEngineAdapter,
    )
    from zet.core.mission_repository import MissionRepository
    from zet.workspace.repository import WorkspaceRepository

    settings = get_settings()
    owner = await get_or_create_owner(session, external_id=settings.owner_id)

    memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
    workspace = WorkspaceRepository(session, owner_id=owner.id)
    context_engine = ContextEngine(
        owner_id=owner.id,
        memory_store=memory,
        workspace_repo=workspace,
    )
    capability_registry: CapabilityRegistry = get_capability_registry()  # type: ignore[assignment]
    composer = CapabilityRegistryComposer(
        capability_registry, agent_registry=get_agent_registry()
    )
    repo = MissionRepository(session, owner_id=owner.id)
    return MissionEngine(
        repository=repo,
        capability_registry=composer,
        context_engine=ContextEngineAdapter(context_engine),
        planner=orchestrator._planner,
        orchestrator=orchestrator,
        approvals=approvals,
        # HIGH #3 audit fix (KONSOLIDATSIYA v2): ilgari doim `None` edi —
        # Task-Graph mission'lar HECH QANDAY recovery diagnos olmasdi,
        # faqat "shunchaki qayta urin". D4 bilan bir xil T1_FREE tier
        # yondashuvi (`_build_verifier_judge` naqshi).
        recovery=MissionRecoveryAdapter(
            llm_provider=_build_verifier_judge(orchestrator._router),  # type: ignore[arg-type]
            repository=repo,
        ),
        memory_store=memory,
        # JB-5: 2+ taskli mission Task Graph yo'li orqali (parallel/
        # dependency-aware, per-task agent) bajariladi; 0-1 taskli mission
        # eski single-Command yo'lida qoladi (o'zgarishsiz).
        task_graph_executor=_build_task_graph_executor(orchestrator._router, session=session),
        max_retries=2,
        killswitch=killswitch,
    )


async def get_mission_orchestrator(
    session: AsyncSession = Depends(get_db_session),
    orchestrator: Orchestrator = Depends(get_orchestrator),
    approval_service: ApprovalService = Depends(get_approval_service),
    permission_policy: PermissionPolicy = Depends(get_permission_policy),
    killswitch: KillSwitchState = Depends(get_killswitch),
    notifier: Notifier = Depends(get_notifier),
    router: ModelRouter = Depends(get_model_router),
    settings: Settings = Depends(get_config),
):  # type: ignore[no-untyped-def]  # forward-ref, MissionOrchestrator local import
    """So'rov chegarasidagi `MissionOrchestrator` — 6 ta yangi qatlamni birlashtiradi.

    Har mission uchun yangi `MissionEngine` va `MissionRepository`
    quriladi (sessiya scoped). Global qismlar (Orchestrator, Killswitch,
    CapabilityRegistry, Notifier) singleton'lardan qayta ishlatiladi.
    """
    from zet.core.capability import CapabilityRegistry
    from zet.core.context import ContextEngine
    from zet.core.mission import MissionEngine, MissionRecoveryAdapter
    from zet.core.mission_orchestrator import (
        CapabilityRegistryComposer,
        ContextEngineAdapter,
        MissionOrchestrator,
    )
    from zet.core.mission_repository import MissionRepository
    from zet.workspace.repository import WorkspaceRepository

    # NEGA `router` endi ishlatiladi: HIGH #3 audit fix (KONSOLIDATSIYA
    # v2) — `MissionRecoveryAdapter`ning T1_FREE LLM judge provider'i
    # shu router orqali quriladi. Kelajakda `understand_fn` (LLM) uchun
    # ham qayta ishlatilishi mumkin.

    owner = await get_or_create_owner(session, external_id=settings.owner_id)

    # ContextEngine — memory + workspace bilan (arzon so'rovlar).
    memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
    workspace = WorkspaceRepository(session, owner_id=owner.id)
    context_engine = ContextEngine(
        owner_id=owner.id,
        memory_store=memory,
        workspace_repo=workspace,
    )

    # Capability composer — singleton registry ustidan compose() beradi.
    capability_registry: CapabilityRegistry = get_capability_registry()  # type: ignore[assignment]
    composer = CapabilityRegistryComposer(
        capability_registry, agent_registry=get_agent_registry()
    )

    # MissionEngine — Bo'lim 2 §2.2 asosiy driver.
    repo = MissionRepository(session, owner_id=owner.id)
    engine = MissionEngine(
        repository=repo,
        capability_registry=composer,
        context_engine=ContextEngineAdapter(context_engine),
        planner=orchestrator._planner,
        orchestrator=orchestrator,
        approvals=approval_service,
        # HIGH #3 audit fix — ilgari doim `None` (D4 bilan bir xil naqsh).
        recovery=MissionRecoveryAdapter(
            llm_provider=_build_verifier_judge(router),  # type: ignore[arg-type]
            repository=repo,
        ),
        memory_store=memory,
        # JB-5: 2+ taskli mission Task Graph yo'li orqali (parallel/
        # dependency-aware, per-task agent) bajariladi; 0-1 taskli mission
        # eski single-Command yo'lida qoladi (o'zgarishsiz).
        task_graph_executor=_build_task_graph_executor(router, session=session),
        max_retries=2,
        killswitch=killswitch,
    )

    return MissionOrchestrator(
        capability_registry=composer,
        context_engine=context_engine,
        mission_engine=engine,
        planner=orchestrator._planner,
        executor=None,  # Executor per-run yaratilib bo'lgan Orchestrator ichida
        verifier=orchestrator._verifier,
        recovery_engine=orchestrator._recovery_engine,
        approval_service=approval_service,
        permission_policy=permission_policy,
        notifier=notifier,
        killswitch=killswitch,
    )


def get_brain(
    orchestrator: Orchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_config),
) -> Brain:
    """So'rov chegarasidagi `Brain` — barcha kanallar uchun yagona kirish (JB-2).

    Brain so'rovni chat/command/goal deb ajratadi va goal bo'lsa Mission
    qatlamiga yuboradi. Ilgari Mission'ga faqat `POST /api/v1/missions`
    orqali yetsa bo'lardi — ya'ni Telegram'dan ham, web chatidan ham
    hech qachon mission tug'ilmasdi.

    Wiring `_build_brain()`da — Telegram oqimi bilan AYNAN bir xil
    (kanallar orasida xatti-harakat farqlanmasin).
    """
    return _build_brain(orchestrator=orchestrator, settings=settings)


@lru_cache(maxsize=1)
def get_stt() -> STTProvider:
    """Global STT provayder (singleton).

    ElevenLabs API kaliti bo'lsa — Scribe orqali haqiqiy transkripsiya.
    Bo'lmasa — `StubSTT` (Telegram ovozli xabar qotgan matn qaytadi).

    Til `settings.stt_language` dan olinadi (default `uzb`) va Scribe'ga
    MAJBURAN uzatiladi — avtomatik aniqlash o'zbekni ozarbayjoncha deb
    o'qib matnni buzadi (`voice/elevenlabs.py` dagi izohga qarang).
    """
    settings = get_settings()
    if settings.elevenlabs_api_key is not None:
        return ElevenLabsSTT(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            default_language=settings.stt_language,
        )
    return StubSTT()


@lru_cache(maxsize=1)
def get_tts() -> TTSProvider:
    """Global TTS provayder (singleton). Tartib: Azure → ElevenLabs → Stub.

    Azure BIRINCHI, chunki faqat unda HAQIQIY o'zbek neyron ovozi bor
    (`uz-UZ-SardorNeural`). ElevenLabs'da o'zbek TTS umuman yo'q — u
    o'zbek matnini chet el aksenti bilan o'qiydi (2026-08-12 jonli
    tekshiruvi: `eleven_v3` 74 tilida ham o'zbek yo'q).

    ElevenLabs zaxira sifatida qoladi: Azure sozlanmagan bo'lsa ovoz
    butunlay yo'qolgandan ko'ra aksentli bo'lgani ma'qul.
    """
    settings = get_settings()
    if settings.azure_speech_key is not None and settings.azure_speech_region:
        return AzureTTS(
            api_key=settings.azure_speech_key.get_secret_value(),
            region=settings.azure_speech_region,
            voice=settings.azure_voice,
        )
    if settings.elevenlabs_api_key is not None:
        return ElevenLabsTTS(
            api_key=settings.elevenlabs_api_key.get_secret_value(),
            voice_id=settings.elevenlabs_voice_id,
        )
    return StubTTS()


@lru_cache(maxsize=1)
def get_telegram_bot() -> object:
    """Global Telegram bot (singleton).

    ZetBot qaytaradi — turini `object` qilish tsiklik importdan saqlanish
    uchun. STT/TTS `get_stt()`/`get_tts()` orqali ulanadi (ElevenLabs yoki
    Stub*). `orchestrator_runner` — har xabar uchun yangi DB sessiya bilan
    yangi `Orchestrator` quradi (`Orchestrator` request-scoped, ega bir
    vaqtda faqat bitta chatga xabar yozadi, konkurrentlik muammosi yo'q).
    """
    import uuid as _uuid

    # NEGA faqat RunNotFoundError: `Orchestrator` modul darajasida allaqachon
    # import qilingan — lokal qayta-import closure'larni alohida bindingga
    # qulflab, testlarda `zet.api.deps.Orchestrator`ni monkeypatch qilishni
    # imkonsiz qilardi.
    from zet.core.orchestrator import RunNotFoundError
    from zet.db.session import session_scope
    from zet.domain.enums import MessageRole
    from zet.security.approvals import ApprovalError, ApprovalExpiredError
    from zet.security.audit_writer import write_audit
    from zet.security.killswitch_actions import revoke_owner_tokens
    from zet.security.killswitch_store import persist_killswitch
    from zet.telegram.bot import ZetBot
    from zet.telegram.handlers import (
        ApprovalRunResult,
        KillSwitchRunResult,
        OrchestratorRunResult,
    )

    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""

    async def _runner(text: str) -> OrchestratorRunResult:
        async with session_scope(get_session_factory()) as session:
            # Suhbat tarixi — ZET oldingi gapni eslab qolishi uchun.
            # Ilgari har xabar mustaqil run edi va "Tushuntir" kabi
            # ergash buyruqlar kontekstsiz qolardi.
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            store = ConversationStore(session, owner_id=owner.id)
            conversation = await store.get_or_create(channel="telegram")
            history = await store.recent_history(conversation)

            # Uzoq muddatli xotira — ega profili va oldingi bilimlar.
            # Ilgari `memory_entries` jadvaliga yozilardi, lekin javob
            # yozishda HECH KIM o'qimasdi: profil saqlanib, ishlatilmasdi.
            memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())

            router = ModelRouter(get_llm_providers(), session, settings)
            tool_registry = get_tool_registry()
            permission_policy = get_permission_policy()
            killswitch = get_killswitch()
            recall = _build_recall(memory)
            orchestrator = Orchestrator(
                router=router,
                tool_registry=tool_registry,
                permission_policy=permission_policy,
                approval_service=get_approval_service(),
                killswitch=killswitch,
                run_store=get_run_store(),
                budget_usd=settings.run_max_usd,
                max_steps=settings.run_max_steps,
                recall=recall,
                audit_fn=_default_audit,
                mark_verified_fn=_default_mark_verified,
                run_timeout_s=settings.run_timeout_s,
                concurrency_semaphore=get_run_semaphore(),
                verifier_judge_provider=_build_verifier_judge(router),
                # D4 (KONSOLIDATSIYA v2): Telegram oqimi ham PART 6 recovery
                # oladi — API va Telegram orasida xatti-harakat farqlanib
                # qolmasin (get_orchestrator() bilan bir xil wiring).
                recovery_engine=_build_recovery_engine(
                    router=router,
                    tool_registry=tool_registry,
                    permission_policy=permission_policy,
                    killswitch=killswitch,
                    budget_usd=settings.run_max_usd,
                    recall=recall,
                ),
                # F1 (BLOCK-3 audit): AWAITING_APPROVAL'ga o'tganda Telegram
                # inline ✅/❌ xabar. NEGA: aynan Telegram-boshlangan run'da
                # notifier uzatilmasdi — `_notify_awaiting_approval` jimgina
                # chiqib ketib, ega "(bo'sh natija)" ko'rardi.
                # `get_orchestrator()` bilan bir xil wiring.
                notifier=get_notifier(),
                # JB-3: Telegram oqimi ham muhit holatini ko'rsin —
                # API bilan bir xil wiring.
                world_state_provider=_build_world_state_provider(settings),
            )

            command = Command(text=text, channel="telegram", history=history)

            # JB-2: Telegram ham endi Brain orqali — ko'p qadamli MAQSAD
            # ("biznesimni tekshir...") Mission bo'ladi, oddiy savol/
            # topshiriq ilgarigidek Run. Ilgari Telegram kodida "mission"
            # so'zi umuman uchramasdi: eng ko'p ishlatiladigan kanal
            # avtonom qatlamdan butunlay uzilgan edi.
            brain = _build_brain(orchestrator=orchestrator, settings=settings)
            result = await brain.handle(command)
            answer = result.text

            await store.append(conversation, role=MessageRole.USER, content=text)
            await store.append(conversation, role=MessageRole.ASSISTANT, content=answer)

            return OrchestratorRunResult(
                text=answer,
                ok=result.ok,
                # Approval tugmalari run darajasida ishlaydi — mission
                # yo'lida ham oxirgi run ID qaytadi (`BrainResult.run_id`).
                run_id=result.run_id or "",
            )

    async def _approval_runner(action: str, run_id_str: str) -> ApprovalRunResult:
        """Inline ✅/❌ → haqiqiy `ApprovalService`+`Orchestrator.resume()` (GAP_ANALYSIS BROKEN #2).

        Ilgari Telegram callback faqat kosmetik "tasdiqlandi" matnini
        qaytarardi — run pauza holatida qolib ketardi. Endi tugma bosish
        API'dagi `/approvals/{id}/approve` bilan bir xil zanjirni chaqiradi:
            1) `pending_for_run(run_id)` — kutilayotgan tasdiqni topish
            2) `orchestrator.approve(approval_id)` — tasdiq qayd etish
            3) `orchestrator.resume(run_id)` — bajarilishni davom ettirish
        `reject` — 3-qadam o'rniga `orchestrator.reject()`.

        JB-12 (audit topilmasi — HIGH funksional bug): Mission-level
        approval'lar `request_approval(run_id=mission.id, mission_id=mission.id)`
        orqali yoziladi (core/mission.py) — haqiqiy Run yo'q. Ilgari bu
        funksiya buni HECH TEKSHIRMASDAN doim `orchestrator.approve()`/
        `.resume()`ni chaqirardi, ya'ni `RunStore.get(mission_id)` —
        RunStore'da mission.id HECH QACHON topilmaydi — `RunNotFoundError`
        otardi, u pastdagi `except` bloki jimgina `ApprovalRunResult(
        ok=False, text=f"Xato: {exc}")`ga aylantirardi. Natija: Telegram'da
        ✅/❌ bosilganda — mission-darajali tasdiq bo'lsa — foydalanuvchi
        umumiy "Xato: ..." xabarini ko'rardi, mission esa abadiy
        WAITING_APPROVAL holatida qolib ketardi (xuddi ✅ hech bosilmagandek).
        Bir xil so'rov REST `/api/v1/approvals/{id}/approve` orqali esa
        TO'G'RI ishlagan (`api/routes/approvals.py` allaqachon shu
        tarmoqlanishga ega edi) — ya'ni AYNAN BIR XIL amal kanaliga qarab
        ISHLAYDIGAN yoki ISHLAMAYDIGAN edi. Endi Telegram ham REST bilan
        AYNAN bir xil naqshni ishlatadi: mission-level bo'lsa
        `MissionEngine.approve()`/`run_to_completion()` (yoki rad etishda
        `MissionEngine.cancel()`), aks holda eski klassik Run yo'li.
        """
        try:
            run_id = _uuid.UUID(run_id_str)
        except ValueError:
            return ApprovalRunResult(ok=False, text=f"Noto'g'ri run ID: {run_id_str}")

        approvals = get_approval_service()
        pending = approvals.pending_for_run(run_id)
        if not pending:
            return ApprovalRunResult(
                ok=False,
                text="Kutilayotgan tasdiq topilmadi — run allaqachon bajarilgan yoki eskirgan.",
            )
        approval_id = pending[0].id
        mission_id = pending[0].mission_id

        if mission_id is not None:
            async with session_scope(get_session_factory()) as session:
                orch_for_mission = await build_orchestrator_for_session(session, settings)
                mission_engine = await build_mission_engine_for_session(
                    session,
                    orch_for_mission,
                    approvals,
                    killswitch=get_killswitch(),
                )
                try:
                    if action == "approve":
                        mission = await mission_engine.approve(mission_id, approval_id)
                        mission = await mission_engine.run_to_completion(mission.id)
                    else:  # "reject"
                        approvals.reject(approval_id)
                        mission = await mission_engine.cancel(
                            mission_id, "Ega tomonidan Telegram orqali rad etildi"
                        )
                except ApprovalExpiredError as exc:
                    return ApprovalRunResult(ok=False, text=f"Tasdiq eskirgan: {exc}")
                except (ApprovalError, KeyError) as exc:
                    return ApprovalRunResult(ok=False, text=f"Xato: {exc}")

                mission_answer = mission.error or (
                    "Rad etildi." if action == "reject" else "Bajarildi."
                )
                return ApprovalRunResult(
                    ok=mission.error is None,
                    text=mission_answer,
                    run_status=mission.status.value,
                )

        async with session_scope(get_session_factory()) as session:
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
            router = ModelRouter(get_llm_providers(), session, settings)
            tool_registry = get_tool_registry()
            permission_policy = get_permission_policy()
            killswitch = get_killswitch()
            recall = _build_recall(memory)
            orchestrator = Orchestrator(
                router=router,
                tool_registry=tool_registry,
                permission_policy=permission_policy,
                approval_service=approvals,
                killswitch=killswitch,
                run_store=get_run_store(),
                budget_usd=settings.run_max_usd,
                max_steps=settings.run_max_steps,
                recall=recall,
                # D4 (KONSOLIDATSIYA v2): `resume()` — masalan owner
                # Recovery Engine'ning HIGH-risk fix qadamini tasdiqlagandan
                # keyin — ham PART 6 recovery zanjiriga ega bo'lishi kerak
                # (bir xil wiring, `get_orchestrator()`/`_runner` bilan mos).
                recovery_engine=_build_recovery_engine(
                    router=router,
                    tool_registry=tool_registry,
                    permission_policy=permission_policy,
                    killswitch=killswitch,
                    budget_usd=settings.run_max_usd,
                    recall=recall,
                ),
                # F1 (BLOCK-3 audit): `resume()` davomida YANGI approval
                # paydo bo'lishi mumkin (masalan, navbatdagi HIGH_RISK qadam)
                # — u ham Telegram inline xabarini olishi shart.
                # `get_orchestrator()`/`_runner` bilan bir xil wiring.
                notifier=get_notifier(),
                # JB-3: Telegram oqimi ham muhit holatini ko'rsin —
                # API bilan bir xil wiring.
                world_state_provider=_build_world_state_provider(settings),
            )

            try:
                if action == "approve":
                    record = orchestrator.approve(approval_id)
                    record = await orchestrator.resume(record.run_id)
                else:  # "reject"
                    record = orchestrator.reject(approval_id)
            except ApprovalExpiredError as exc:
                return ApprovalRunResult(ok=False, text=f"Tasdiq eskirgan: {exc}")
            except (ApprovalError, RunNotFoundError, KeyError) as exc:
                return ApprovalRunResult(ok=False, text=f"Xato: {exc}")

            answer = (
                record.result_summary
                or record.error
                or ("Rad etildi." if action == "reject" else "Bajarildi.")
            )
            return ApprovalRunResult(
                ok=record.error is None,
                text=answer,
                run_status=record.status.value,
            )

    async def _killswitch_runner(action: str, reason: str | None) -> KillSwitchRunResult:
        """Telegram `/killswitch` — HAQIQIY `KillSwitchState` (SR-04).

        REST route (`/api/v1/killswitch/engage`) bilan bir xil zanjir:
            1) `ks.engage`/`ks.disengage` — flag'ni o'zgartirish
            2) `persist_killswitch` — DB'ga yozib qo'yish (V-33, restart-durable)
            3) capability tokenlarni bekor qilish (SR-06)
            4) `write_audit` — kim/qachon amal qilgani jadvalga
        """
        ks = get_killswitch()

        missing_reason = "(ko'rsatilmagan)"

        if action == "status":
            state = ks.to_dict()
            engaged = bool(state["engaged"])
            if engaged:
                reason_text = state["reason"] or missing_reason
                body = (
                    "🚨 KillSwitch YOQILGAN\n"
                    f"Sabab: {reason_text}\n"
                    f"Vaqt: {state['engaged_at']}\n"
                    f"Kim: {state['engaged_by']}"
                )
            else:
                body = "✅ KillSwitch o'chirilgan (tizim faol)"
            return KillSwitchRunResult(text=body, ok=True, engaged=engaged)

        if action == "engage":
            if ks.is_engaged:
                reason_text = ks.reason or missing_reason
                return KillSwitchRunResult(
                    text=(f"KillSwitch allaqachon yoqilgan.\nSabab: {reason_text}"),
                    ok=True,
                    engaged=True,
                )
            engage_reason = reason or "Telegram orqali qo'lda yoqilgan"
            ks.engage(reason=engage_reason, by="telegram")
            await persist_killswitch(ks, get_session_factory())
            revoked = await revoke_owner_tokens(
                get_session_factory(), owner_external_id=settings.owner_id
            )
            await write_audit(
                get_session_factory(),
                actor="owner",
                action="killswitch.engaged",
                detail={
                    "reason": engage_reason,
                    "channel": "telegram",
                    "revoked_token_count": revoked,
                },
            )
            body = (
                f"KillSwitch yoqildi.\nSabab: {engage_reason}\nBekor qilingan tokenlar: {revoked}"
            )
            return KillSwitchRunResult(text=body, ok=True, engaged=True)

        # action == "disengage"
        if not ks.is_engaged:
            return KillSwitchRunResult(
                text="KillSwitch allaqachon o'chirilgan.",
                ok=False,
                engaged=False,
            )
        ks.disengage(by="telegram")
        await persist_killswitch(ks, get_session_factory())
        await write_audit(
            get_session_factory(),
            actor="owner",
            action="killswitch.disengaged",
            detail={"channel": "telegram"},
        )
        return KillSwitchRunResult(
            text=(
                "KillSwitch o'chirildi. Tizim yangi run'larni qabul qiladi.\n"
                "Diqqat: capability tokenlar tiklanmagan — har qurilmani qayta "
                "ro'yxatga olishingiz kerak."
            ),
            ok=True,
            engaged=False,
        )

    return ZetBot(
        token=token,
        owner_ids=settings.telegram_owner_id_set,
        stt=get_stt(),
        tts=get_tts(),
        notifier=get_notifier(),
        orchestrator_runner=_runner,
        approval_runner=_approval_runner,
        killswitch_runner=_killswitch_runner,
        moderated_chat_ids=frozenset(settings.telegram_moderated_chat_id_set),
    )


# ── Mijoz do'kon boti ─────────────────────────────────────────────

SHOP_BOT_MAX_TOKENS = 400
"""Javob uzunligi chegarasi — mijoz DM'i qisqa savol-javob, insho emas."""

SHOP_BOT_PRODUCT_LIMIT = 5
"""LLM'ga uzatiladigan mos mahsulotlar soni — katalog kontekstini shishirmaslik uchun."""


async def _shop_answer_fn(
    *, chat_id: int, user_id: int, text: str, username: str, display_name: str
) -> str:
    """Mijoz DM'iga javob — `CommerceRepository` qidiruvi + tool'siz LLM (Z51, #42).

    `shop_bot.py` docstringidagi qarorning amalga oshirilishi: model
    hech qanday tool ko'rmaydi (`tools=()` — bo'sh, umuman uzatilmaydi),
    faqat bazadan HAQIQATAN topilgan mahsulotlar matnini ko'radi va shu
    asosda tabiiy javob yozadi. Narx/mavjudlikni LLM o'zi o'ylab topa
    olmaydi — ro'yxatda yo'q narsa haqida so'ralsa buni ochiq aytadi.
    """
    settings = get_settings()
    async with session_scope(get_session_factory()) as session:
        owner = await get_or_create_owner(session, external_id=settings.owner_id)
        commerce = CommerceRepository(session, owner_id=owner.id)

        # Yozgan har kim CRM kontaktga aylanadi — #43 (kargo xabari)
        # keyinchalik shu kontakt orqali mijozni topadi.
        await commerce.get_or_create_contact_by_chat_id(
            chat_id=chat_id,
            display_name=display_name or f"Mijoz {user_id}",
            username=username,
        )

        products = await commerce.search_products(text, limit=SHOP_BOT_PRODUCT_LIMIT)
        if products:
            catalog_lines = [
                f"- {p.name}: {p.price_uzs:,.0f} so'm"
                f"{' — TUGAGAN' if p.stock_qty <= 0 else ''}"
                f"{f' ({p.description})' if p.description else ''}"
                for p in products
            ]
            catalog_text = "\n".join(catalog_lines)
        else:
            catalog_text = "(mos mahsulot topilmadi)"

        system = (
            "Sen — do'kon egasining Telegram savdo yordamchisisan. "
            "Mijozga QISQA, samimiy, o'zbek tilida javob ber.\n\n"
            "QOIDA: narx va mavjudlik haqida FAQAT quyidagi ro'yxatdan "
            "foydalan — hech qachon o'zingdan o'ylab topma. Agar "
            "ro'yxatda mijoz so'ragan narsa bo'lmasa, buni ochiq ayt va "
            "do'kon egasi bilan bog'lanishni taklif qil.\n\n"
            f"Topilgan mahsulotlar:\n{catalog_text}"
        )

        router = ModelRouter(get_llm_providers(), session, settings)
        try:
            result = await router.complete(
                task_class=TaskClass.SIMPLE,
                messages=[ChatMessage(role="user", content=text)],
                system=system,
                max_tokens=SHOP_BOT_MAX_TOKENS,
            )
        except LLMError:
            log.warning("shop_bot.llm_unavailable", chat_id=chat_id)
            return "Kechirasiz, hozir javob bera olmayapman — birozdan so'ng qayta urinib ko'ring."
        return result.response.text


@lru_cache(maxsize=1)
def get_shop_bot() -> object:
    """Global mijoz do'kon boti (singleton) — `ZetBot`dan MUSTAQIL (Z51, #42).

    Turini `object` qilish `get_telegram_bot` bilan bir xil sabab —
    tsiklik importdan saqlanish. Tokensiz sozlanganda stub rejimda
    ishlaydi (hech qanday tarmoq chaqiruvi yo'q)."""
    from zet.telegram.shop_bot import ShopBot

    settings = get_settings()
    token = settings.shop_bot_token.get_secret_value() if settings.shop_bot_token else ""
    return ShopBot(token=token, answer_fn=_shop_answer_fn)
