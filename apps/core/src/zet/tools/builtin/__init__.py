"""Built-in toollar — Bo'lim 1, 3, 7 uchun ro'yxatga olinadigan toollar.

`build_default_registry()` — barcha builtin toollarni bitta `ToolRegistry`ga
yig'adi. API va CLI shu funksiyadan foydalanadi — har birida alohida-alohida
bo'sh registry yaratilmaydi (avvalgi xato: har so'rovda bo'sh `ToolRegistry()`
yaratilar edi, hech qanday tool ishlamas edi).

Bog'liq qarorlar:
    Bo'lim 1 — time.now, note.write
    Bo'lim 3 — web.search (stub)
    Bo'lim 7 — github.read/write, web.read
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from zet.devices.camera import CameraProvider

if TYPE_CHECKING:
    from zet.agents.registry import AgentRegistry
from zet.devices.desktop import DesktopProvider
from zet.integrations.public_apis.adapters import (
    GeocodeForwardTool,
    GeocodeReverseTool,
    IpLookupTool,
)
from zet.integrations.public_apis.catalog.repository import CatalogRepository
from zet.integrations.public_apis.health import ProviderHealthTracker
from zet.tools.builtin.business_tools import (
    BusinessContactLinkTool,
    BusinessCreateTool,
    BusinessListTool,
)
from zet.tools.builtin.camera import CameraSnapshotTool
from zet.tools.builtin.capability_discovery import CapabilityDiscoveryTool
from zet.tools.builtin.commerce_tools import (
    CommerceScope,
    OrdersListTool,
    OrderStatusUpdateTool,
    ProductCreateTool,
    ProductListTool,
    ProductSearchTool,
    SalesStatsTool,
)
from zet.tools.builtin.crm_tools import (
    CRMContactCreateTool,
    CRMContactSearchTool,
    CRMDealCreateTool,
    CRMDealListTool,
    CRMLeadCreateTool,
    CRMLeadListTool,
    CRMScope,
    CRMStatsTool,
)
from zet.tools.builtin.deploy_push import DeployPushTool
from zet.tools.builtin.desktop_tools import (
    DesktopKeyPressTool,
    DesktopMouseClickTool,
    DesktopScreenshotTool,
    DesktopTypeTextTool,
)
from zet.tools.builtin.feed_tools import (
    CurrencyRateTool,
    NewsHeadlinesTool,
    StockQuoteTool,
    WeatherNowTool,
)
from zet.tools.builtin.github import GitHubReadTool, GitHubWriteTool
from zet.tools.builtin.github_intel_tools import (
    GitHubAnalyzeRepositoryTool,
    GitHubCompareRepositoriesTool,
    GitHubSearchRepositoryTool,
)
from zet.tools.builtin.hr_tools import (
    AgentDisableTool,
    AgentListTool,
    AgentPauseTool,
    AgentResumeTool,
    AgentStatsTool,
)
from zet.tools.builtin.instagram import (
    InstagramAccountStatsTool,
    InstagramPublishPhotoTool,
    InstagramRecentMediaTool,
)
from zet.tools.builtin.memory_search import MemorySearchTool, SearchFn
from zet.tools.builtin.memory_write import MemoryWriteTool, WriteFn
from zet.tools.builtin.note_list import NoteListTool
from zet.tools.builtin.note_read import NoteReadTool
from zet.tools.builtin.note_write import NoteMemoryShadowFn, NoteWriteTool
from zet.tools.builtin.public_apis_search import PublicAPISearchTool
from zet.tools.builtin.shell_exec import ShellExecTool
from zet.tools.builtin.telegram_tools import (
    TelegramChannelPostTool,
    TelegramChannelStatsTool,
    TelegramDeleteMessageTool,
)
from zet.tools.builtin.time_now import TimeNowTool
from zet.tools.builtin.video_learn import DEFAULT_MODEL as DEFAULT_VIDEO_MODEL
from zet.tools.builtin.video_learn import VideoLearnTool
from zet.tools.builtin.vision_ocr import VisionOcrTool
from zet.tools.builtin.web_reader import WebReaderTool
from zet.tools.builtin.web_search import WebSearchTool
from zet.tools.builtin.workspace_tools import WORKSPACE_TOOL_CLASSES, WorkspaceScope
from zet.tools.builtin.youtube import (
    YouTubeChannelStatsTool,
    YouTubeSearchTool,
    YouTubeVideoStatsTool,
)
from zet.tools.builtin.youtube_publish import YouTubePublishTool
from zet.tools.registry import ToolRegistry


def build_default_registry(
    *,
    notes_dir: Path,
    sites_dir: Path | None = None,
    enable_shell: bool = False,
    web_reader_stub: bool = True,
    github_token: str | None = None,
    web_search_api_key: str | None = None,
    youtube_api_key: str | None = None,
    gemini_api_key: str | None = None,
    gemini_video_model: str | None = None,
    youtube_oauth_client_id: str | None = None,
    youtube_oauth_client_secret: str | None = None,
    youtube_oauth_refresh_token: str | None = None,
    telegram_bot_token: str | None = None,
    instagram_access_token: str | None = None,
    instagram_business_account_id: str | None = None,
    camera_provider: CameraProvider | None = None,
    desktop_provider: DesktopProvider | None = None,
    memory_search_fn: SearchFn | None = None,
    memory_write_fn: WriteFn | None = None,
    note_memory_shadow_fn: NoteMemoryShadowFn | None = None,
    workspace_scope: WorkspaceScope | None = None,
    crm_scope: CRMScope | None = None,
    commerce_scope: CommerceScope | None = None,
    agent_registry: AgentRegistry | None = None,
    public_apis_health_tracker: ProviderHealthTracker | None = None,
    public_apis_catalog_repository: CatalogRepository | None = None,
    timezone: str = "Asia/Tashkent",
    feed_latitude: float = 41.3111,
    feed_longitude: float = 69.2797,
    feed_news_url: str = "https://www.gazeta.uz/uz/rss/",
    feed_stock_symbols: str = "NVDA,AAPL,MSFT",
    feed_currency_codes: str = "USD,EUR,RUB",
) -> ToolRegistry:
    """Barcha builtin toollarni ro'yxatga olib, tayyor `ToolRegistry` qaytaradi.

    Args:
        notes_dir: `note.write` tooli uchun eslatmalar papkasi (odatda
            `Settings.vault_dir`).
        sites_dir: `deploy.push` tooli uchun sayt fayllari papkasi (odatda
            `Settings.sites_dir`). Berilmasa `notes_dir.parent / "sites"`
            ishlatiladi (test/lean wiring uchun qulay default).
        enable_shell: `shell.exec` toolini ro'yxatga qo'shish (default:
            o'chirilgan — eng xavfli komponent, faqat aniq yoqilganda).
        web_reader_stub: `web.read` stub rejimida ishlasinmi (default: ha).
            Haqiqiy tarmoq chaqiruvi uchun `False` bering.
        github_token: berilsa — `github.read`/`github.write` haqiqiy API'ga
            chiqadi; bo'lmasa (default) — stub rejim.
        web_search_api_key: berilsa — `web.search` haqiqiy qidiradi (Brave
            Search API); bo'lmasa (default) — stub rejim.
        youtube_api_key: berilsa — `youtube.search`/`.channel_stats`/`.video_stats`
            YouTube Data API v3'ga chiqadi; bo'lmasa (default) — stub rejim.
        gemini_api_key: berilsa — `video.learn` YouTube videosini to'liq ko'rib
            bilim ajratadi; bo'lmasa tool chaqirilganda tushunarli xato
            (soxta "bilim" qaytarish yolg'on bo'lardi, shuning uchun stub yo'q).
        telegram_bot_token: berilsa — `telegram.channel_stats`/`.channel_post`
            Telegram Bot API'siga chiqadi (bot kanaldan administrator bo'lishi
            shart); bo'lmasa — stub.
        instagram_access_token: berilsa (business_account_id bilan birga) —
            `instagram.*` tool'lar Meta Graph API'ga chiqadi; aks holda stub.
        instagram_business_account_id: Instagram Business Account ID
            (17-raqamli). Token bilan birga bo'lishi kerak.
        camera_provider: `camera.snapshot` uchun ulanish (default: `StubCamera`
            — real RTSP/EZVIZ hali ulanmagan).
        memory_search_fn: berilsa — `memory.search` uzoq muddatli xotiradan
            qidiradi. Berilmasa tool baribir ro'yxatda turadi, lekin
            chaqirilganda ochiq xato beradi: Planner uni ko'rib turgani
            ma'qul, aks holda ega haqidagi savolga yo'q eslatma fayllarini
            qidirib reja tuzadi (jonli tekshiruvda aynan shunday bo'ldi).
        workspace_scope: berilsa — `task.*`/`project.*`/`calendar.*` tool'lar
            haqiqiy doskaga yozadi va o'qiydi. Berilmasa tool'lar baribir
            ro'yxatda turadi, lekin chaqirilganda ochiq xato beradi (soxta
            bo'sh doska "hech qanday vazifa yo'q" degan YOLG'ON javobga
            olib kelardi). AYNAN shu argument `Capability.TASK_BOARD` va
            `Capability.CALENDAR`ni haqiqiy qiladi — `recipes.py`ga qarang.
        timezone: ega vaqt mintaqasi — kalendar va muddatlar shu mintaqada
            o'qiladi/yoziladi (baza doim UTC saqlaydi).
        feed_latitude/feed_longitude/feed_news_url/feed_stock_symbols/
        feed_currency_codes: jonli manba tool'lari uchun (`weather.now`,
            `stocks.quote`, `news.headlines`, `currency.rate`). Hammasi
            KALITSIZ manbalarga chiqadi — stub rejim YO'Q, chunki soxta
            ob-havo yoki soxta kurs ega uchun zararli bo'lardi.
        desktop_provider: `desktop.*` tool'lar uchun ulanish (default:
            `StubDesktop(available=False)` — headless server muhitida). ZET
            foydalanuvchining mahalliy Mac/Win kompyuterida ishga tushirilsa,
            `PyAutoGUIDesktop` bilan almashtiriladi.
        public_apis_health_tracker: `location.geocode`/`.reverse_geocode`/
            `ip.lookup` (public-apis integratsiyasi, `integrations/
            public_apis/`) ulashadigan sog'liq kuzatuvchisi. Berilmasa —
            har biri o'z, izolyatsiyalangan nusxasini oladi (test/lean
            xatti-harakat); production'da `api/deps.py`
            `get_public_apis_health_tracker()` orqali BITTA, jarayon
            umriga teng nusxani beradi (barcha so'rovlar bir xil
            statistikani ko'radi).
        public_apis_catalog_repository: `public_apis.search` tooli o'qiydigan
            katalog (`integrations/public_apis/catalog/`). Berilmasa — bo'sh,
            izolyatsiyalangan nusxa (test/lean xatti-harakat; tool honestligicha
            "hali sinxronlanmagan" javob beradi). Production'da `api/deps.py`
            `get_public_apis_catalog_repository()` orqali operator REST
            endpoint'lari (`api/routes/public_apis.py`) bilan BITTA, BIR XIL
            nusxa ulashiladi — ikkinchi mustaqil katalog YARATILMAYDI.

    Returns:
        Ro'yxatga olingan `ToolRegistry`.
    """
    registry = ToolRegistry()
    registry.register(TimeNowTool())
    registry.register(MemorySearchTool(search_fn=memory_search_fn))
    registry.register(MemoryWriteTool(write_fn=memory_write_fn))
    registry.register(NoteWriteTool(notes_dir=notes_dir, memory_shadow_fn=note_memory_shadow_fn))
    registry.register(NoteReadTool(notes_dir=notes_dir))
    registry.register(NoteListTool(notes_dir=notes_dir))
    # F8 (BLOCK-3 audit): `sites_dir` berilmasa `notes_dir`ning aka-uka
    # papkasi ishlatiladi — `website` capability'ning `deploy.push` gap'i
    # ilgari HECH QAYERDA ro'yxatdan o'tmagan edi.
    registry.register(
        DeployPushTool(sites_dir=sites_dir or (notes_dir.parent / "sites"))
    )
    registry.register(WebSearchTool(api_key=web_search_api_key))
    registry.register(WebReaderTool(stub=web_reader_stub))
    registry.register(GitHubReadTool(token=github_token))
    registry.register(GitHubWriteTool(token=github_token))
    # GitHub Intelligence (JB-19) — bitta MA'LUM repo'ning issue/PR bilan
    # ISHLASHDAN (yuqoridagi ikkitasi) farqli, YANGI repo QIDIRISH/TAHLIL
    # qilish uchun — bir xil token/HTTP infratuzilmasini ishlatadi
    # (`_GitHubHttpMixin`), ikkinchi mustaqil klient QURILMAYDI.
    registry.register(GitHubSearchRepositoryTool(token=github_token))
    registry.register(GitHubAnalyzeRepositoryTool(token=github_token))
    registry.register(GitHubCompareRepositoriesTool(token=github_token))
    registry.register(
        VideoLearnTool(api_key=gemini_api_key, model=gemini_video_model or DEFAULT_VIDEO_MODEL)
    )
    # `vision.ocr` ham `gemini_api_key` orqali ishlaydi — kalit yo'q
    # bo'lsa tool baribir ro'yxatda turadi (Planner ko'radi), lekin
    # chaqirilganda tushunarli xato beradi (video.learn bilan bir xil
    # naqsh). Vision agent'ning tool_allowlist'iga qo'shildi.
    registry.register(VisionOcrTool(api_key=gemini_api_key))
    registry.register(YouTubeSearchTool(api_key=youtube_api_key))
    registry.register(YouTubeChannelStatsTool(api_key=youtube_api_key))
    registry.register(YouTubeVideoStatsTool(api_key=youtube_api_key))
    registry.register(
        YouTubePublishTool(
            client_id=youtube_oauth_client_id,
            client_secret=youtube_oauth_client_secret,
            refresh_token=youtube_oauth_refresh_token,
        )
    )
    registry.register(TelegramChannelStatsTool(token=telegram_bot_token))
    registry.register(TelegramChannelPostTool(token=telegram_bot_token))
    registry.register(TelegramDeleteMessageTool(token=telegram_bot_token))
    registry.register(
        InstagramAccountStatsTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(
        InstagramRecentMediaTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(
        InstagramPublishPhotoTool(
            access_token=instagram_access_token,
            ig_user_id=instagram_business_account_id,
        )
    )
    registry.register(
        WeatherNowTool(latitude=feed_latitude, longitude=feed_longitude, timezone=timezone)
    )
    registry.register(
        StockQuoteTool(
            default_symbols=[s.strip() for s in feed_stock_symbols.split(",") if s.strip()]
        )
    )
    registry.register(NewsHeadlinesTool(feed_url=feed_news_url))
    registry.register(
        CurrencyRateTool(
            default_codes=[c.strip() for c in feed_currency_codes.split(",") if c.strip()]
        )
    )
    for workspace_tool in WORKSPACE_TOOL_CLASSES:
        registry.register(workspace_tool(scope=workspace_scope, tz=timezone))
    # CRM tool'lari (Sales/Support agent uchun) — scope berilmasa
    # chaqirilganda ochiq xato beradi, "jimgina bo'sh" bo'lmaydi.
    registry.register(CRMContactSearchTool(scope=crm_scope))
    registry.register(CRMContactCreateTool(scope=crm_scope))
    registry.register(CRMLeadCreateTool(scope=crm_scope))
    registry.register(CRMLeadListTool(scope=crm_scope))
    registry.register(CRMDealCreateTool(scope=crm_scope))
    registry.register(CRMDealListTool(scope=crm_scope))
    registry.register(CRMStatsTool(scope=crm_scope))
    # Business Registry (C2, KONSOLIDATSIYA v2) — bir xil `PgCRM` sessiyasi
    # (`crm_scope`) ham kontaktlarni, ham bizneslarni olib yuradi.
    registry.register(BusinessCreateTool(scope=crm_scope))
    registry.register(BusinessListTool(scope=crm_scope))
    registry.register(BusinessContactLinkTool(scope=crm_scope))
    # HR agent uchun workforce management tool'lari (yangi talab):
    # boshqa AI agentlarni pause/resume/disable qila oladi.
    registry.register(AgentListTool(registry=agent_registry))
    registry.register(AgentPauseTool(registry=agent_registry))
    registry.register(AgentResumeTool(registry=agent_registry))
    registry.register(AgentDisableTool(registry=agent_registry))
    registry.register(AgentStatsTool(registry=agent_registry))
    # E-commerce agent uchun mahsulot/buyurtma boshqaruvi (Z51):
    registry.register(ProductSearchTool(scope=commerce_scope))
    registry.register(ProductListTool(scope=commerce_scope))
    registry.register(ProductCreateTool(scope=commerce_scope))
    registry.register(OrdersListTool(scope=commerce_scope))
    registry.register(OrderStatusUpdateTool(scope=commerce_scope))
    registry.register(SalesStatsTool(scope=commerce_scope))
    registry.register(CameraSnapshotTool(provider=camera_provider))
    registry.register(DesktopScreenshotTool(provider=desktop_provider))
    registry.register(DesktopTypeTextTool(provider=desktop_provider))
    registry.register(DesktopKeyPressTool(provider=desktop_provider))
    registry.register(DesktopMouseClickTool(provider=desktop_provider))
    if enable_shell:
        registry.register(ShellExecTool(enabled=True))
    # public-apis integratsiyasi (JB-18) — keyless, HTTPS, bu sessiyada
    # jonli tekshirilgan adapterlar (`docs/audits/
    # PUBLIC_APIS_INTEGRATION_AUDIT.md` §6). Hech qanday kalit talab
    # qilmagani uchun "real-vs-stub" naqshi kerak emas — har doim real.
    health_tracker = public_apis_health_tracker or ProviderHealthTracker()
    registry.register(GeocodeForwardTool(health_tracker=health_tracker))
    registry.register(GeocodeReverseTool(health_tracker=health_tracker))
    registry.register(IpLookupTool(health_tracker=health_tracker))
    # `public_apis.search` — Brain'ga ENABLED bo'lmagan (hali adapter
    # yozilmagan) yozuvlarni ham KASHFIYOT sifatida ko'rsatadi (Bo'lim
    # 4/9). Katalog (yuqoridagi 3 ta ijro etuvchi adapterdan FARQLI
    # ravishda) faqat operator `POST /public-apis/refresh` chaqirganda
    # to'ladi — shuning uchun bo'sh bo'lishi kutilgan holat (tool o'zi
    # buni honestligicha aytadi, "hech narsa yo'q" deb taxmin qilmaydi).
    catalog_repository = public_apis_catalog_repository or CatalogRepository()
    registry.register(PublicAPISearchTool(repository=catalog_repository))
    # JB-16: "nima qila olasiz" so'roviga HAQIQIY registry'dan javob —
    # eng OXIRIDA ro'yxatga olinadi (o'zi ISHORA saqlagani uchun tartib
    # ahamiyatsiz, lekin "hammasidan keyin" logik ravishda to'g'ri).
    registry.register(CapabilityDiscoveryTool(registry=registry))
    return registry


__all__ = ["build_default_registry"]
