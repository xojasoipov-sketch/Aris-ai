"""FastAPI dependency'lari (Z1.14).

Singleton va per-request dependency'lar.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import TYPE_CHECKING

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from zet.agents.registry import AgentRegistry
from zet.agents.repository import AgentRepository
from zet.automation.engine import AutomationEngine
from zet.automation.executor import WorkflowExecutor
from zet.automation.goal import GoalRegistry
from zet.business.pg_crm import PgCRM
from zet.config import Settings, get_settings
from zet.core.orchestrator import Orchestrator, RunStore
from zet.core.state import CoreState
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import create_engine, create_session_factory, session_scope
from zet.deploy.schedule import DailyScheduleManager
from zet.llm.base import LLMProvider
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


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    """Global tool registry (singleton) — barcha builtin toollar bilan.

    Ilgari har bir so'rov bo'sh `ToolRegistry()` yaratardi — hech qanday
    tool ishlamas edi. Endi bitta joyda ro'yxatga olinadi.
    """
    settings = get_settings()
    camera_provider = None
    if settings.hikvision_host and settings.hikvision_username and settings.hikvision_password:
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
    from zet.core.orchestrator import Orchestrator
    from zet.db.session import session_scope
    from zet.domain.command import Command
    from zet.domain.enums import MessageRole
    from zet.telegram.bot import ZetBot
    from zet.telegram.handlers import OrchestratorRunResult

    settings = get_settings()
    token = settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else ""

    async def _runner(text: str) -> OrchestratorRunResult:
        async with session_scope(get_session_factory()) as session:
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
            )
            # Suhbat tarixi — ZET oldingi gapni eslab qolishi uchun.
            # Ilgari har xabar mustaqil run edi va "Tushuntir" kabi
            # ergash buyruqlar kontekstsiz qolardi.
            owner = await get_or_create_owner(session, external_id=settings.owner_id)
            store = ConversationStore(session, owner_id=owner.id)
            conversation = await store.get_or_create(channel="telegram")
            history = await store.recent_history(conversation)

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

    return ZetBot(
        token=token,
        owner_ids=settings.telegram_owner_id_set,
        stt=get_stt(),
        tts=get_tts(),
        notifier=get_notifier(),
        orchestrator_runner=_runner,
    )
