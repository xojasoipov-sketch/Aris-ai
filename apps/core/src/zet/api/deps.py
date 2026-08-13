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
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.state import CoreState
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import create_engine, create_session_factory, session_scope
from zet.deploy.schedule import DailyScheduleManager
from zet.deploy.selfimprove import SelfImproveEngine
from zet.devices.repository import DeviceDBRepository
from zet.domain.command import ConversationTurn
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
    """Global ruxsat siyosati (singleton)."""
    return PermissionPolicy()


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
    )


async def build_mission_engine_for_session(
    session: AsyncSession,
    orchestrator: Orchestrator,
    approvals: ApprovalService,
):  # type: ignore[no-untyped-def]  # local imports return non-exported types
    """Approve/reject endpoint uchun kichik yordamchi: sessiya ustida MissionEngine.

    Adversarial verify topgan HIGH bug'ni tuzatish uchun kerak: mission-level
    approval'lar `Orchestrator.approve()` orqali o'ta olmasdi (RunStore'da
    mission.id yo'q). Endi approvals endpoint mission_id ni ko'rgach shu
    yordamchi orqali MissionEngine ochib `approve()`/`run_to_completion()`
    ni chaqiradi. Sessiya ochilgan kontekstda saqlanadi (chaqiruvchi
    `async with session_scope(...)` bloki ichida).
    """
    from zet.core.capability import CapabilityRegistry
    from zet.core.context import ContextEngine
    from zet.core.mission import MissionEngine
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
    composer = CapabilityRegistryComposer(capability_registry)
    repo = MissionRepository(session, owner_id=owner.id)
    return MissionEngine(
        repository=repo,
        capability_registry=composer,
        context_engine=ContextEngineAdapter(context_engine),
        planner=orchestrator._planner,
        orchestrator=orchestrator,
        approvals=approvals,
        recovery=None,
        memory_store=memory,
        max_retries=2,
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
    from zet.core.mission import MissionEngine
    from zet.core.mission_orchestrator import (
        CapabilityRegistryComposer,
        ContextEngineAdapter,
        MissionOrchestrator,
    )
    from zet.core.mission_repository import MissionRepository
    from zet.workspace.repository import WorkspaceRepository

    del router  # kelajakda understand_fn (LLM) uchun

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
    composer = CapabilityRegistryComposer(capability_registry)

    # MissionEngine — Bo'lim 2 §2.2 asosiy driver.
    repo = MissionRepository(session, owner_id=owner.id)
    engine = MissionEngine(
        repository=repo,
        capability_registry=composer,
        context_engine=ContextEngineAdapter(context_engine),
        planner=orchestrator._planner,
        orchestrator=orchestrator,
        approvals=approval_service,
        recovery=None,
        memory_store=memory,
        max_retries=2,
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

    from zet.core.orchestrator import Orchestrator, RunNotFoundError
    from zet.db.session import session_scope
    from zet.domain.command import Command
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
            orchestrator = Orchestrator(
                router=router,
                tool_registry=get_tool_registry(),
                permission_policy=get_permission_policy(),
                approval_service=get_approval_service(),
                killswitch=get_killswitch(),
                run_store=get_run_store(),
                budget_usd=settings.run_max_usd,
                max_steps=settings.run_max_steps,
                recall=_build_recall(memory),
                audit_fn=_default_audit,
                mark_verified_fn=_default_mark_verified,
                run_timeout_s=settings.run_timeout_s,
                concurrency_semaphore=get_run_semaphore(),
                verifier_judge_provider=_build_verifier_judge(router),
            )

            command = Command(text=text, channel="telegram", history=history)
            record = await orchestrator.start(command)
            answer = record.result_summary or record.error or "(bo'sh natija)"

            await store.append(conversation, role=MessageRole.USER, content=text)
            await store.append(conversation, role=MessageRole.ASSISTANT, content=answer)

            return OrchestratorRunResult(
                text=answer,
                ok=record.error is None,
                run_id=str(record.run_id),
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

        async with session_scope(get_session_factory()) as session:
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            memory = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
            router = ModelRouter(get_llm_providers(), session, settings)
            orchestrator = Orchestrator(
                router=router,
                tool_registry=get_tool_registry(),
                permission_policy=get_permission_policy(),
                approval_service=approvals,
                killswitch=get_killswitch(),
                run_store=get_run_store(),
                budget_usd=settings.run_max_usd,
                max_steps=settings.run_max_steps,
                recall=_build_recall(memory),
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
