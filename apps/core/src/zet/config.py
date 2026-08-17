"""ZET konfiguratsiyasi.

Qatlamlar: default -> `.env` -> environment o'zgaruvchilari.
Barcha sirlar `SecretStr` tipida — ular `repr()` va log'da hech qachon ochilmaydi.

Bog'liq qarorlar:
    ADR-0006 — model tier'lari va budjet chegaralari
    ADR-0007 — local-first deployment
"""

from __future__ import annotations

import functools
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zet.domain.enums import RiskLevel


def _find_repo_root() -> Path:
    """Loyiha ildizini topadi — papka chuqurligiga bog'liq bo'lmagan holda.

    Ilgari `parents[4]` qat'iy yozilgan edi: repo ichida
    (`apps/core/src/zet/config.py`) to'g'ri ishlardi, lekin Docker
    konteynerida (`/app/src/zet/config.py`) yo'l qisqaroq bo'lib
    `IndexError` bilan yiqilardi.

    Marker fayl (`pyproject.toml` yoki `.git`) bo'yicha yuqoriga
    ko'tariladi; topilmasa — paket ota-papkasiga qaytadi. `data_dir`/
    `vault_dir` odatda `ZET_*` env orqali beriladi, shuning uchun bu
    faqat lokal dev uchun oqilona default.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            # apps/core/pyproject.toml topilsa — monorepo ildizi bir pog'ona
            # yuqorida bo'lishi mumkin; .git bor joyni afzal ko'ramiz.
            if (parent / ".git").exists():
                return parent
            for outer in parent.parents:
                if (outer / ".git").exists():
                    return outer
            return parent
    return here.parents[min(2, len(here.parents) - 1)]


_REPO_ROOT = _find_repo_root()


class Env(StrEnum):
    """Ishga tushirish muhiti."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    """ZET yadrosining to'liq konfiguratsiyasi.

    `ZET_` prefiksli environment o'zgaruvchilaridan o'qiladi.
    """

    model_config = SettingsConfigDict(
        env_prefix="ZET_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # ── Ilova ──────────────────────────────────────────────────────
    env: Env = Env.DEV
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    timezone: str = "Asia/Tashkent"

    # ── Ma'lumotlar bazasi / navbat ────────────────────────────────
    database_url: SecretStr = SecretStr("postgresql+asyncpg://zet:zet@localhost:5432/zet")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # ── LLM provayderlar (ADR-0006: T0 -> T1 -> T2 -> T3) ──────────
    # T0 — lokal (bepul)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_embed_model: str = "bge-m3"

    embedding_provider: Literal["auto", "ollama", "gemini", "mistral", "none"] = "auto"
    """Semantik qidiruv uchun vektor manbasi.

    `auto` — muhitga qarab tanlaydi:
        prod'da Ollama YO'Q (Railway konteynerida mahalliy model ishlamaydi),
        shuning uchun Gemini → Mistral → none tartibida kalit bo'yicha;
        dev'da esa Ollama (ADR-0007 local-first, pulsiz, offline).

    Aniq qiymat berilsa — shu provayder ishlatiladi. Provayderni
    ALMASHTIRISH eski vektorlarni yaroqsiz qilmaydi, lekin ular boshqa
    fazoda bo'lgani uchun qidiruvda hisobga olinmaydi (`pg_store`).
    """

    gemini_embed_model: str = "gemini-embedding-001"
    """Gemini embedding modeli (3072 o'lcham, ko'p tilli).

    `text-embedding-004` eskirgan — jonli tekshiruvda 404 qaytardi."""

    mistral_embed_model: str = "mistral-embed"
    """Mistral embedding modeli (1024 o'lcham)."""

    gemini_video_model: str = "gemini-flash-latest"
    """`video.learn` uchun model — YouTube havolasini to'g'ridan-to'g'ri o'qiydi.

    Bepul qatlamda har model uchun kunlik limit alohida (~20 so'rov).
    Limit tugasa `gemini-flash-lite-latest` ga o'tish mumkin — u
    tezroq va arzonroq, sifati biroz pastroq."""
    # T1 — free tier
    google_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None
    """Cohere — `command-r` oilasi. Jonli tasdiqlangan (2026-08-12)."""

    # Kalit bor, lekin hisob to'ldirilmagan bo'lsa provayder ro'yxatga
    # olinadi va marshrutning OXIRIDA turadi. Router `is_configured`ni
    # tekshiradi, circuit breaker esa ketma-ket xatodan keyin uni yopadi —
    # ya'ni pulsiz provayder har so'rovni sekinlashtirmaydi. Hisob
    # to'ldirilgach kod o'zgarmasdan ishlay boshlaydi.
    cerebras_api_key: SecretStr | None = None
    """Cerebras — juda tez inferens. 2026-08-12: kalit yaroqli, balans yo'q."""

    deepseek_api_key: SecretStr | None = None
    """DeepSeek — arzon reasoning. 2026-08-12: kalit yaroqli, balans yo'q."""

    kimi_api_key: SecretStr | None = None
    """Moonshot Kimi — uzun kontekst. 2026-08-12: kalit yaroqli, balans yo'q."""

    # T2 / T3 — to'lovli
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # ── Budjet chegaralari (ADR-0006 §4, fail-closed) ──────────────
    budget_monthly_usd: float = Field(default=10.0, ge=0)
    budget_daily_usd: float = Field(default=0.50, ge=0)
    run_max_usd: float = Field(default=0.10, ge=0)
    tier3_daily_calls: int = Field(default=5, ge=0)
    autonomous_budget_share: float = Field(default=0.40, ge=0, le=1)

    # ── Run chegaralari (A-07: avtomatlashtirish tormozlari) ───────
    run_max_steps: int = Field(default=20, ge=1)
    run_max_depth: int = Field(default=3, ge=1)
    run_timeout_s: int = Field(default=600, ge=1)

    # ── Ruxsat siyosati (V-32, risk o'qi) ──────────────────────────
    auto_approve_medium_risk: bool = Field(default=True)
    """MEDIUM xavfli toollar tasdiqsiz o'tsinmi (`TOOL_RISK_LEVELS`).

    MEDIUM = qaytarib bo'ladigan biznes yozuvlari: `note.write`,
    `task.create`, `crm.*`, `order.set_status`. Default `True` — ilgarigi
    xatti-harakat: Executor risk jadvalini umuman ko'rmasdi, bu yozuvlar
    avtomatik ketardi. Ularni endi majburiy tasdiqqa o'tkazish har bir
    "vazifa qo'sh" uchun Telegram tugmasini talab qilardi.

    `False` qilsangiz — har MEDIUM amal ega tasdig'ini kutadi (fail-closed,
    yuqoriroq nazorat, sekinroq oqim).

    MUHIM: bu sozlama HIGH darajaga TA'SIR QILMAYDI. `shell.exec`,
    `file.delete`, `telegram.channel_post`, `github.write`,
    `instagram.publish_photo`, `youtube.publish`, `desktop.*` — har doim
    tasdiq so'raydi va hech qanday sozlama buni chetlab o'tolmaydi (V-32).
    """

    # ── Agent Factory provisioning (JB-6, V-10/V-32) ────────────────
    agent_auto_provisioning_enabled: bool = Field(default=True)
    """Task Graph'da CapabilityGap topilganda avtomatik agent provisioning
    yoqilganmi. `False` — JB-5 xatti-harakati (gap faqat hisobotga
    yoziladi, hech narsa "tuzatib qo'ymaydi"). Bu — ochiq/yopiq kalit;
    aniq qaysi risk darajasi avtomatik ketishini ikkita quyidagi sozlama
    belgilaydi."""

    agent_auto_provision_max_risk: RiskLevel = Field(default=RiskLevel.LOW)
    """Bu darajagacha (shu bilan birga) — yangi agent AVTOMATIK yaratiladi
    VA (eval o'tsa) faollashtiriladi, inson aralashuvisiz."""

    agent_provision_disabled_min_risk: RiskLevel = Field(default=RiskLevel.HIGH)
    """Bu darajadan boshlab (shu bilan birga) — provisioning UMUMAN
    taqiqlanadi (V-32: hech qanday sozlama buni avtomatik chetlab
    o'tolmaydi). Oralig'idagi darajalar (masalan default bo'yicha
    MEDIUM) — agent yaratiladi, lekin ACTIVE emas: inson
    `PATCH /agents/{name}/status {activate}` orqali tasdiqlashi kerak."""

    # ── Ijro rejimi klassifikatori (JB-8) ────────────────────────────
    brain_execution_mode_enabled: bool = Field(default=True)
    """Brain har so'rov uchun `ExecutionMode` (DIRECT_RESPONSE/DIRECT_TOOL/
    MISSION/TASK_GRAPH/WORKFLOW/BACKGROUND_WORKFLOW/WORKFLOW_COMMAND)
    hisoblasinmi. `False` — JB-7'gacha bo'lgan xatti-harakat
    (`BrainResult.execution_mode` doim bo'sh, marshrutlash o'zgarmaydi)."""

    # ── Mission restart recovery (JB-10) ─────────────────────────────
    mission_restart_recovery_enabled: bool = Field(default=True)
    """JB-10: startup'da uzilib qolgan Mission'larni topib qayta
    yuritsinmi (`core/mission_recovery.py::load_incomplete_missions`).

    `True` (default): non-terminal (EXECUTING/PLANNING/DISCOVERING/
    VERIFYING/RECOVERING/UNDERSTANDING) mission'lar startup'da spawn
    qilinadi. WAITING_APPROVAL mission'lar ATAYLAB tashlab yuboriladi —
    ular mavjud approval oqimi orqali (load_pending_approvals +
    /approvals/{id}/approve) qayta ishga tushiriladi.

    `False`: JB-9 xatti-harakati (mission'lar DB'da qoladi lekin qayta
    yuritilmaydi). MUHIM: COMPLETED/FAILED/CANCELLED mission'lar `True`
    bo'lganda ham HECH QACHON qayta ishga tushirilmaydi (spec §20/§21
    xavfsizlik qoidasi)."""

    # ── Workflow/Scheduler integratsiyasi (JB-9) ─────────────────────
    brain_workflow_integration_enabled: bool = Field(default=True)
    """JB-9: BACKGROUND_WORKFLOW → HAQIQIY `ScheduleRule` yaratsinmi va
    WORKFLOW_COMMAND → HAQIQIY Scheduler amali (list/pause/resume/cancel)
    chaqirsinmi.

    `True` (default):
        - "Har kuni soat 9 da telegramimni tekshir" — haqiqiy
          `ScheduleRule` yaratiladi (`automation_state`da saqlanadi,
          `AutomationDaemon` cron vaqtida ishga tushiradi).
        - "Workflowlarimni ko'rsat" — Scheduler'dan ro'yxat qaytariladi.
        - "Workflowni to'xtat" — Scheduler.pause_rule chaqiriladi.
    `False`:
        - JB-8 xatti-harakati (rejim aniqlanadi va loglanadi, lekin
          haqiqiy hech narsa o'zgarmaydi — WORKFLOW_COMMAND Run yo'liga
          tushadi, BACKGROUND_WORKFLOW — Mission yo'liga).

    MUHIM (halol chegara — JB-9): flag `True` bo'lganda ham `ExecutionMode
    .WORKFLOW` (bir martalik aniq so'ralgan persistent jarayon) — HALI
    Mission yo'liga tushadi. Mission allaqachon DB-persistent "ko'p
    qadamli, saqlanadigan, retryable" ijro qatlami, shuning uchun bu —
    "fake" emas; lekin alohida `WorkflowChain` obyekti YARATILMAYDI."""

    # ── Brain-level Model Routing (JB-7, V-29) ──────────────────────
    brain_model_routing_enabled: bool = Field(default=True)
    """Task Graph'da har task uchun ALOHIDA, kontent-asoslangan `TaskClass`
    tanlansinmi (`core.model_routing.BrainModelRouter`). `False` — JB-5/6
    xatti-harakati (agent.model_policy statik tieri, task mazmunidan
    qat'i nazar)."""

    # ── Brain marshrutlash (JB-2) ──────────────────────────────────
    brain_goal_missions: bool = Field(default=True)
    """Ko'p qadamli MAQSAD (`request_kind=goal`) Mission qatlamiga ketsinmi.

    `True` (default): "biznesimni tekshir va nimaga e'tibor berishim
    kerakligini ayt" kabi so'rov saqlanadigan, qayta uriniladigan va
    xotiraga yoziladigan Mission bo'ladi. Oddiy savol/topshiriq
    ilgarigidek Run pipeline'idan o'tadi.

    `False`: hamma narsa Run yo'lidan ketadi (JB-2'gacha bo'lgan
    xatti-harakat) — triaj uchun LLM chaqiruvi ham qilinmaydi.

    Regressiya xavfi yo'q: mission birorta run boshlamasdan yiqilsa
    (masalan capability mos kelmasa), `Brain` so'rovni avtomatik Run
    yo'liga qaytaradi — `core/brain.py`ga qarang."""

    # ── Kuzatuv (3-xususiyat, Bo'lim 9) ────────────────────────────
    watcher_poll_interval_s: float = Field(default=60.0, ge=1)
    """Watcher daemon ikki o'lchov orasida kutadigan vaqt (soniya).

    Minut aniqligi yetarli — watcher metrikalari (agent xatolari, budjet
    sarfi) sekundlik tebranish emas, trend. Qisqartirsangiz metrika
    problar shunchalik tez-tez o'qiladi — tashqi API'li metrika uchun
    kvota sarfini hisobga oling. `WatchRule.cooldown_s` signal
    yog'ilishini alohida tormozlaydi — bu sozlama faqat O'LCHOV
    chastotasi."""

    # ── Telegram (Bo'lim 5, V-17) ───────────────────────────────────
    telegram_bot_token: SecretStr | None = None
    """Telegram bot token. `.env` faylida saqlang — hech qachon kodda emas."""

    telegram_owner_ids: str = ""
    """Vergul bilan ajratilgan Telegram user ID lar (owner allowlist, R-04).

    Misol: "123456789,987654321"
    Bo'sh bo'lsa — hech kimga ruxsat yo'q (fail-closed).
    """

    # ── Mijoz do'kon boti (Z51, #42) ─────────────────────────────────
    #
    # ATAYIN alohida token/bot — `ZetBot` OwnerMiddleware bilan
    # fail-closed qurilgan (faqat egaga javob beradi). Bu bot esa
    # aksincha — HAR QANDAY mijozga javob berishi kerak, lekin HECH
    # QANDAY tool'ga (fayl, terminal, boshqa Telegram xabar) ruxsati
    # yo'q — faqat mahsulot qidiruvi + LLM javob generatsiyasi
    # (`telegram/shop_bot.py`dagi izohga qarang).
    shop_bot_token: SecretStr | None = None
    """Alohida BotFather tokeni — `telegram_bot_token`dan BOSHQA bot bo'lishi shart."""

    # ── Kanal moderatsiyasi (Z51, #44) ────────────────────────────────
    telegram_moderated_chat_ids: str = ""
    """Vergul bilan ajratilgan guruh/kanal ID lar (moderatsiya allowlist).

    Misol: "-1001234567890,-1009876543210"
    Bo'sh bo'lsa — hech qanday xabar o'chirilmaydi (fail-closed, owner
    allowlist bilan bir xil qoida). `telegram_bot_token`dagi bot shu
    chat'larda ADMINISTRATOR + "Delete Messages" ruxsatiga ega bo'lishi
    shart, aks holda Telegram API `deleteMessage`ni rad etadi."""

    # ── GitHub (Bo'lim 7) ────────────────────────────────────────────
    github_token: SecretStr | None = None
    """GitHub Personal Access Token. Bo'lsa — `github.read`/`github.write`
    haqiqiy API'ga chiqadi; bo'lmasa — stub rejimda ishlaydi."""

    # ── Web qidiruv (Bo'lim 7) ────────────────────────────────────────
    web_search_api_key: SecretStr | None = None
    """Brave Search API kaliti (bepul qatlam: 2000 so'rov/oy). Bo'lsa —
    `web.search` haqiqiy qidiradi; bo'lmasa — stub rejimda ishlaydi."""

    # ── Jonli manbalar (Z50) ──────────────────────────────────────────
    #
    # Hammasi KALITSIZ manbalarga tayanadi — ega yana to'rtta API
    # kalitini boshqarmasin. Sukut qiymatlar Toshkentga sozlangan.
    feed_latitude: float = 41.3111
    """Ob-havo uchun kenglik (sukut: Toshkent)."""

    feed_longitude: float = 69.2797
    """Ob-havo uchun uzunlik (sukut: Toshkent)."""

    feed_news_url: str = "https://www.gazeta.uz/uz/rss/"
    """Yangiliklar RSS manzili. O'zbekcha manba — ega shu tilda o'qiydi."""

    feed_stock_symbols: str = "NVDA,AAPL,MSFT"
    """Kuzatiladigan aksiyalar (vergul bilan)."""

    feed_sports_league_id: str = "4328"
    """TheSportsDB liga ID (4328 — Angliya Premer-ligasi)."""

    feed_currency_codes: str = "USD,EUR,RUB"
    """Markaziy bank kursi uchun valyutalar."""

    # ── Kamera (Bo'lim 8) ─────────────────────────────────────────────
    hikvision_host: str = ""
    """Hikvision kamera/NVR manzili (masalan '192.168.1.64' yoki '...:80').
    Bo'lsa (username/password bilan birga) — `camera.snapshot` haqiqiy
    ISAPI snapshot'ga chiqadi; bo'lmasa — StubCamera ishlaydi."""

    hikvision_username: str = ""
    """Hikvision ISAPI foydalanuvchi nomi (odatda 'admin')."""

    hikvision_password: SecretStr | None = None
    """Hikvision ISAPI paroli."""

    hikvision_channel: int = Field(default=1, ge=1)
    """Kamera kanal raqami (NVR uchun 101, 201, ...; yagona kamera uchun 1)."""

    rtsp_camera_url: SecretStr | None = None
    """Umumiy RTSP kamera havolasi (`rtsp://user:pass@host/stream`).

    Bo'lsa — `camera.snapshot` RTSP orqali kadr oladi (Hikvision emas,
    Dahua/Tapo/Uniview va boshqa RTSP standartini qo'llovchi har qanday
    kamera uchun). `opencv-python-headless` alohida o'rnatilgan bo'lishi
    kerak (loyihaning majburiy bog'liqligi emas — Dockerfile'da
    o'rnatilmagan). Bir vaqtda RTSP va Hikvision berilsa — RTSP ustunlik
    qiladi (aniqroq generik yo'l). URL parolini log'ga yozmaymiz.
    """

    rtsp_camera_timeout_s: int = Field(default=10, ge=1)
    """RTSP oqim ochish/kadr olish uchun vaqt chegarasi."""

    # ── Instagram Graph API (Bo'lim 7, C-04) ──────────────────────────
    instagram_access_token: SecretStr | None = None
    """Instagram Business/Creator uchun long-lived access token (Meta App
    Dashboard). Scope: instagram_basic, instagram_content_publish,
    pages_show_list. Bo'lmasa — `instagram.*` tool'lar stub rejim."""

    instagram_business_account_id: str = ""
    """Instagram Business Account ID (17-raqamli). Meta Graph API Explorer'da
    `me/accounts` → `instagram_business_account` orqali olinadi. Bo'sh
    bo'lsa — stub rejim (token bor bo'lsa ham)."""

    # ── YouTube Data API v3 (Bo'lim 7, C-03 #2) ────────────────────────
    youtube_api_key: SecretStr | None = None
    """YouTube Data API v3 kaliti (Google Cloud Console → APIs & Services →
    Credentials → API key). Bepul kvota 10 000 unit/kun. Kalit bo'lmasa —
    `youtube.search`/`youtube.channel_stats`/`youtube.video_stats` stub rejim."""

    # ── YouTube Publish (OAuth 2.0, Bo'lim 7 — WRITE) ──────────────────
    youtube_oauth_client_id: SecretStr | None = None
    """OAuth 2.0 Client ID (Google Cloud Console → Credentials → OAuth Client)."""

    youtube_oauth_client_secret: SecretStr | None = None
    """OAuth 2.0 Client Secret (Desktop app type)."""

    youtube_oauth_refresh_token: SecretStr | None = None
    """Refresh token — `scripts/youtube_oauth.py` orqali bir marta olinadi.
    Uchtasi ham bo'lmasa — `youtube.publish` stub rejimda ishlaydi."""

    # ── Ovoz (Bo'lim 5, V-18) ─────────────────────────────────────────
    stt_language: str = "uzb"
    """Ovozni qaysi tilda o'qish (ElevenLabs Scribe kodi).

    Default AVTOMATIK ANIQLASH EMAS. Scribe o'zbek nutqini avtomatik
    rejimda ozarbayjoncha deb o'qiydi (jonli sinov, 88% ishonch) va
    matn butunlay buziladi — ikkala til lotin yozuvida juda yaqin.

    ZET bitta egaga tegishli (V-02), ega esa o'zbekcha gapiradi, shuning
    uchun tilni taxmin qilishning ma'nosi yo'q. Boshqa tilda ishlash
    kerak bo'lsa shu qiymat o'zgartiriladi (masalan `rus`, `eng`).
    """

    azure_speech_key: SecretStr | None = None
    """Azure Speech kaliti — HAQIQIY o'zbek neyron ovozi uchun.

    ElevenLabs'da o'zbek TTS yo'q (jonli tekshirilgan): u o'zbek matnini
    chet el aksenti bilan o'qiydi. Azure'da esa `uz-UZ-SardorNeural` va
    `uz-UZ-MadinaNeural` — o'zbek fonetikasiga o'rgatilgan ovozlar.
    Bepul qatlam: oyiga 500 000 belgi.

    Bu kalit bo'lsa TTS Azure'ga o'tadi; bo'lmasa ElevenLabs'da qoladi.
    """

    azure_speech_region: str = ""
    """Azure Speech resursi regioni (masalan `westeurope`, `eastus`).

    Endpoint URL'ining bir qismi, shuning uchun kalit bilan birga
    MAJBURIY — bittasi yetishmasa TTS Azure'ni ishlatmaydi.
    """

    azure_voice: str = "uz-UZ-SardorNeural"
    """Azure ovozi. Ayol ovozi uchun: `uz-UZ-MadinaNeural`."""

    elevenlabs_api_key: SecretStr | None = None
    """ElevenLabs API kaliti (Scribe STT + Multilingual v2 TTS). Bo'lmasa —
    `StubSTT`/`StubTTS` ishlatiladi (Telegram ovozli xabar qotgan matn qaytadi)."""

    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"
    """TTS uchun ovoz ID. Default — Sarah (bepul rejada mavjud, ayol, ko'p
    tilli, o'zbekcha aniq o'qiydi — real hisob bilan tasdiqlangan). Rachel
    (`21m00Tcm4TlvDq8ikWAM`) bepul rejaviy hisoblar uchun mavjud emas, 402
    qaytaradi. Boshqasini tanlash uchun elevenlabs.io → Voice Library'dan
    ovoz ID'sini nusxa oling."""

    whisper_model_path: str | None = "/data/voice-models/whisper-uz-ct2"
    """LOKAL, self-hosted STT (`zet.voice.whisper_stt.WhisperSTT`) uchun
    CTranslate2-konvertatsiya qilingan model katalogi yo'li.

    `/data/voice-models` — `Dockerfile`dagi doimiy hajm (`/data/vault`
    naqshiga o'xshab), `scripts/prepare_voice_models.py` bir martalik
    ishga tushirilib to'ldiriladi. Katalog HALI mavjud bo'lmasa
    (birinchi deploy, skript ishga tushirilmagan) — `WhisperSTT.
    is_configured` `False` qaytaradi va `get_stt()` ElevenLabs/Stub'ga
    tushadi (fail-open, boshqa provayderlar bilan bir xil naqsh).

    `None` qilib qo'ysangiz — lokal STT butunlay o'chiriladi.
    """

    navoiy_tts_base_url: str | None = None
    """Hetzner GPU serveridagi Navoiy TTS (CosyVoice2) mikroservisi manzili
    (masalan `http://203.0.113.10:8100`) — `zet.voice.navoiy_tts.NavoiyTTS`.

    Default `None` — GPU serveri ATAYLAB avtomatik yoqilmaydi (operator
    uni qo'lda joylashtirishi va manzilini shu yerga yozishi kerak,
    `infra/hetzner/navoiy-tts-service/README.md`ga qarang). Bo'lsa —
    `get_tts()`da ENG BIRINCHI tekshiriladi (MmsTTS'dan ham oldin):
    litsenziyasi Apache-2.0 (MmsTTS'ning CC-BY-NC-4.0'idan farqli,
    tijoratga to'liq ochiq) va CosyVoice2 asosida sifat yuqoriroq deb
    kutiladi (GPU'da maxsus o'zbekcha fine-tune).

    Ismlar/o'zlashma so'zlar/kam uchraydigan raqam formatlarini noto'g'ri
    talaffuz qilishi mumkin — `zet/voice/navoiy_tts.py` docstring'iga
    qarang. Xizmat o'chiq/erishib bo'lmasa — fail-open bilan MmsTTS'ga
    tushadi, hech narsa qulamaydi."""

    mms_tts_model_path: str | None = "/data/voice-models/mms-tts-uz"
    """LOKAL, self-hosted TTS (`zet.voice.mms_tts.MmsTTS`) uchun
    HuggingFace `facebook/mms-tts-uzb-script_cyrillic` og'irligi saqlangan
    katalog yo'li — `whisper_model_path` bilan bir xil naqsh (doimiy hajm,
    `prepare_voice_models.py`, fail-open).

    OGOHLANTIRISH: `facebook/mms-tts-uzb-*` **CC-BY-NC-4.0** (FAQAT
    NOTIJORAT) litsenziyali — `zet/voice/mms_tts.py` modul docstring'iga
    qarang. ZET tijorat mahsulotiga aylansa, bu yo'l ALMASHTIRILISHI yoki
    yuridik tekshirilishi kerak.

    `None` qilib qo'ysangiz — lokal TTS butunlay o'chiriladi (Azure/
    ElevenLabs/Stub'ga tushadi).
    """

    # ── Xavfsizlik ─────────────────────────────────────────────────
    owner_id: str = "owner"
    api_token: SecretStr | None = None
    approval_ttl_minutes: int = Field(default=30, ge=1)
    enable_shell: bool = False
    """`shell.exec` tooli. Default o'chirilgan — Z1.10 dagi eng xavfli komponent."""

    # ── CLI → API ──────────────────────────────────────────────────
    api_url: str = "http://localhost:8000"
    """`z approve`/`z reject` CLI komandalari HTTP orqali shu bazaga
    murojaat qiladi. Ilgari `z run` da approval kerakligi paydo bo'lsa,
    CLI o'z jarayonida `RunStore` bilan qolar, API buni ko'rmasdi
    (GAP_ANALYSIS BROKEN #1). Endi `z approve <id>` shu URL'ga
    `POST /api/v1/approvals/{id}/approve` yuboradi — bitta manba.

    Prod'da (Hetzner) `ZET_API_URL=http://backend:8000` yoki jamoat URL."""

    # ── Yo'llar ────────────────────────────────────────────────────
    data_dir: Path = _REPO_ROOT / "data"

    vault_dir: Path = _REPO_ROOT / "vault"
    """Obsidian vault papkasi — `note.write`/`note.read`/`note.list` shu yerda
    ishlaydi. `ZET_VAULT_DIR` orqali o'z vault'ingizga yo'naltiriladi."""

    sites_dir: Path = _REPO_ROOT / "sites"
    """`deploy.push` tooli statik sayt fayllarini shu papkaga yozadi (F8,
    BLOCK-3 audit — MINIMAL: faqat lokal fayl generatsiya, real hosting
    hali yo'q). `ZET_SITES_DIR` orqali o'zgartiriladi."""

    @model_validator(mode="before")
    @classmethod
    def _blank_paths_use_default(cls, data: object) -> object:
        """Bo'sh `ZET_VAULT_DIR=` ni `Path('.')` ga aylantirmaslik uchun.

        Aks holda vault butun repo bo'lib qolardi — `note.list` manba
        daraxtidagi har bir `.md` ni ko'rar, `note.write` esa kodning
        ichiga yozardi. Bo'sh qiymat butunlay olib tashlanadi, shunda
        maydonning o'z default'i qo'llanadi.
        """
        if not isinstance(data, dict):
            return data
        return {
            key: value
            for key, value in data.items()
            if not (
                key.lower().removeprefix("zet_") in {"data_dir", "vault_dir", "sites_dir"}
                and isinstance(value, str)
                and not value.strip()
            )
        }

    @field_validator("database_url", "redis_url")
    @classmethod
    def _not_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().strip():
            raise ValueError("bo'sh bo'lishi mumkin emas")
        return v

    @model_validator(mode="after")
    def _check_budget_coherence(self) -> Settings:
        if self.budget_daily_usd > self.budget_monthly_usd:
            raise ValueError(
                f"budget_daily_usd ({self.budget_daily_usd}) "
                f"budget_monthly_usd ({self.budget_monthly_usd}) dan katta bo'lishi mumkin emas"
            )
        if self.run_max_usd > self.budget_daily_usd:
            raise ValueError(
                f"run_max_usd ({self.run_max_usd}) "
                f"budget_daily_usd ({self.budget_daily_usd}) dan katta bo'lishi mumkin emas"
            )
        return self

    @model_validator(mode="after")
    def _check_prod_requirements(self) -> Settings:
        if self.env is Env.PROD:
            missing: list[str] = []
            if self.api_token is None:
                missing.append("ZET_API_TOKEN")
            if not self.has_any_llm_provider:
                missing.append("kamida bitta LLM provayder kaliti yoki Ollama")
            if missing:
                raise ValueError(f"prod muhitida majburiy: {', '.join(missing)}")
        return self

    @property
    def has_any_llm_provider(self) -> bool:
        """Kamida bitta LLM yo'li mavjudmi (lokal Ollama ham hisoblanadi)."""
        return any(
            [
                self.google_api_key,
                self.groq_api_key,
                self.mistral_api_key,
                self.openrouter_api_key,
                self.cohere_api_key,
                self.cerebras_api_key,
                self.deepseek_api_key,
                self.kimi_api_key,
                self.anthropic_api_key,
                self.openai_api_key,
                bool(self.ollama_base_url),
            ]
        )

    @property
    def is_prod(self) -> bool:
        return self.env is Env.PROD

    @property
    def telegram_owner_id_set(self) -> set[int]:
        """Telegram owner ID larni set ga o'girish."""
        if not self.telegram_owner_ids.strip():
            return set()
        result: set[int] = set()
        for part in self.telegram_owner_ids.split(","):
            part = part.strip()
            if part.isdigit():
                result.add(int(part))
        return result

    @property
    def telegram_moderated_chat_id_set(self) -> set[int]:
        """Moderatsiya qilinadigan chat ID larni set ga o'girish.

        `telegram_owner_id_set`dan farqi: guruh/kanal ID lari odatda
        MANFIY (`-100...`), shuning uchun `isdigit()` yetarli emas —
        ixtiyoriy `-` prefiksga ruxsat beriladi."""
        if not self.telegram_moderated_chat_ids.strip():
            return set()
        result: set[int] = set()
        for part in self.telegram_moderated_chat_ids.split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                result.add(int(part))
        return result

    @property
    def autonomous_daily_budget_usd(self) -> float:
        """Jadval bo'yicha ishlaydigan run'larga ajratilgan kunlik ulush (ADR-0006 §4)."""
        return self.budget_daily_usd * self.autonomous_budget_share


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Keshlangan sozlamalar (protsess davomida bir marta o'qiladi)."""
    return Settings()
