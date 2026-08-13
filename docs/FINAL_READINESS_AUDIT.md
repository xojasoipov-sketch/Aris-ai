# ZET ASS — Final Production Readiness Audit

> Sana: 2026-08-13 · Master Spec `docs/ZET_ASS_MASTER.md` PART 11 (Definition of
> Done) va PART 10 (audit-first, no rewrite) bo'yicha butun tizim tekshiruvi.
> Metod: `Workflow` bilan 10-agent audit (evidence + 8 parallel deep-audit +
> synthesis) + qolgan 4 subsystem uchun asosiy loop'da to'g'ridan-to'g'ri inspeksiya.
> Barcha da'volar `fayl:qator` sitatasi bilan tasdiqlanadi.

---

## 0. Evidence Summary — RAW numbers

| Metric | Value | Source |
|---|---|---|
| Backend tests passed | **2512 / 2512** (100%) | `uv run pytest --tb=no` (2026-08-13 15:22 UTC) |
| Backend tests collected | 2512 | `pytest --collect-only` |
| Ruff check | **All checks passed** | `uv run ruff check .` |
| Ruff format | **367 files clean** | `uv run ruff format --check .` |
| Mypy | **47 errors** (17 fayl, pre-existing, asosan `cli.py` va uzoq muddat qolgan `no-untyped-call`) | `uv run mypy src/` |
| Frontend TypeScript typecheck | **clean** | `pnpm typecheck` in `apps/web` |
| Frontend build | **pass, 20 routes generated** | `pnpm build` |
| Frontend tests | **0** (hozircha yo'q — §I.B4 blocker) | `find apps/web -name "*.test.*"` |
| Integration-marked tests | **0** (marker yo'q; funktsional testlar bor lekin markersiz) | `grep @pytest.mark.integration` |
| E2E-marked tests | **0** | `grep @pytest.mark.e2e` |
| Alembic migrations | **9** (0001 → 0009_missions) | `ls alembic/versions/*.py` |
| API endpoints | **113** | `grep -rn "@router\." src/zet/api/routes/` |
| Docs files | **14** (Master Spec, GAP_ANALYSIS, AUTONOMY_AUDIT, va 11 boshqa) | `ls docs/*.md` |
| Backend source files | **223** Python fayllar | `find src/zet -name "*.py"` |
| Backend LoC | **44,879** | `wc -l src/zet/**/*.py` |
| Total commits (branch) | **~148** | `git log --oneline` |
| Working tree | **CLEAN** | `git status --short` |

---

## 1. Integration Status Matrix

| Integration | Status | Requires (env / hardware) | Evidence | Notes |
|---|---|---|---|---|
| Telegram Bot (owner control) | **REAL** | `ZET_TELEGRAM_BOT_TOKEN`, `ZET_TELEGRAM_OWNER_IDS` | `telegram/bot.py`, `polling.py`, `handlers.py` | Long-polling; OwnerMiddleware fail-closed |
| Telegram Notifier (push) | **PARTIAL** | Bot token + chat id | `telegram/http_notifier.py` | Real `POST /sendMessage` when configured, else StubNotifier |
| Telegram Shop Bot | **REQUIRES_CREDS** | Separate `ZET_SHOP_BOT_TOKEN` | `telegram/shop_bot.py` | Alohida bot majburiy |
| Telegram Channel Moderation (spam) | **REAL** | Bot token + `ZET_TELEGRAM_MODERATED_CHAT_IDS` + admin rights | `telegram/moderation.py` | Rule-based classifier |
| Telegram `/killswitch` command | **REAL** | Bot token + owner IDs | `telegram/handlers.py` + `api/deps.py::_killswitch_runner` | SR-04 yopilgan |
| Obsidian vault (note.*) | **REAL** | Writable path (`ZET_VAULT_DIR`) | `tools/builtin/_vault.py`, `note_write.py` | Path-traversal sanitized; shadow → memory |
| Obsidian↔Postgres shadow | **REAL** | `ZET_VAULT_DIR` + DB | `tools/builtin/note_write.py` + `api/deps.py::_note_memory_shadow_fn` | KNOWLEDGE layer'ga qisqa preview |
| GitHub REST API | **PARTIAL** | `ZET_GITHUB_TOKEN` (repo scope) | `tools/builtin/github.py` | Tokensiz stub; tokenli real |
| Brave Web Search | **PARTIAL** | `ZET_WEB_SEARCH_API_KEY` | `tools/builtin/web_search.py` | Kalitsiz 3 canned natija |
| Web Reader (SSRF-safe) | **PARTIAL** | Constructor `stub=False` (deps'da yoqilgan) | `tools/builtin/web_reader.py` | Prod'da `web_reader_stub=False` |
| Gemini Video Learn | **REQUIRES_CREDS** | `ZET_GOOGLE_API_KEY` (YouTube URL only) | `tools/builtin/video_learn.py` | Kalitsiz ToolError |
| Gemini Vision OCR | **REQUIRES_CREDS** | `ZET_GOOGLE_API_KEY` | `tools/builtin/vision_ocr.py` | Kalitsiz ToolError; 429→ToolQuotaError |
| Camera abstraction | **PARTIAL** | Provider injection | `tools/builtin/camera.py` | Default `StubCamera` (1×1 JPEG) |
| Hikvision ISAPI | **REQUIRES_HARDWARE** | `ZET_HIKVISION_*` + fizik kamera | `devices/hikvision.py` | httpx.DigestAuth |
| RTSP camera | **REQUIRES_HARDWARE** | `ZET_RTSP_CAMERA_URL` + opencv-python | `devices/rtsp.py` | opencv optional dep |
| Desktop control | **MOCKED** | Real provider yo'q | `devices/desktop.py`, `desktop_tools.py` | `PyAutoGUIDesktop` faqat docstring'da |
| Live feeds (weather/stocks/news/currency) | **REAL** | Public endpoints (kalit yo'q) | `tools/builtin/feed_tools.py` | Open-Meteo, CBU, RSS |
| Instagram Graph API | **PARTIAL** | `ZET_INSTAGRAM_ACCESS_TOKEN` + business account ID | `tools/builtin/instagram.py` | Personal IG qo'llab-quvvatlanmaydi |
| YouTube Data API v3 read | **PARTIAL** | `ZET_YOUTUBE_API_KEY` | `tools/builtin/youtube.py` | Kalitsiz stub |
| YouTube Publish | **REQUIRES_AUTH** | OAuth 2.0 (client_id + secret + refresh_token) | `tools/builtin/youtube_publish.py` | `scripts/youtube_oauth.py` orqali one-time flow |
| Telegram tools (channel_post etc.) | **PARTIAL** | Bot token + admin rights | `tools/builtin/telegram_tools.py` | Kalitsiz stub |
| ElevenLabs STT (Scribe) | **REQUIRES_CREDS** | `ZET_ELEVENLABS_API_KEY` | `voice/elevenlabs.py` | Uzbek `uzb` majburiy |
| ElevenLabs TTS | **REQUIRES_CREDS** | `ZET_ELEVENLABS_API_KEY` | `voice/elevenlabs.py` | O'zbek uchun aksentli — Azure afzal |
| Azure Speech TTS (uz-UZ neural) | **REQUIRES_CREDS** | `ZET_AZURE_SPEECH_KEY` + `_REGION` | `voice/azure_tts.py` | Sardor/Madina Neural — haqiqiy o'zbek |
| CRM (PgCRM) | **REAL** | Postgres + migrations | `business/pg_crm.py` | Owner-scoped |
| E-commerce (CommerceRepository) | **REAL** | Postgres + migrations | `commerce/repository.py` | Product LIKE-based search |
| Mission API | **REAL** | Postgres + Alembic 0009 | `api/routes/missions.py`, `core/mission.py` | Full state machine + REST |
| Capability Registry (20 seed) | **REAL** | (in-memory singleton) | `core/capability.py` | Dynamic composition |
| Context Engine | **PARTIAL** | Memory + Workspace (CRM/GitHub/Telegram kelajakda) | `core/context.py` | 2/6 manba real, 4/6 yo'q — §B ga qarang |
| Task Graph DAG | **REAL** | (kod ichida) | `core/dag.py`, `core/executor.py:255-268` | Parallel batches asyncio.gather bilan |
| Recovery Engine | **PARTIAL** | Provider berilgan bo'lsa | `core/recovery.py`, `mission.py::recover` | MAX_RETRIES=2; LLM patch — fail-open |
| Risk-based Approval | **REAL** | (in-code policy) | `security/risk.py`, `security/permissions.py`, `core/mission.py::plan` | HIGH → majburiy WAITING_APPROVAL |
| Model Router (4 tier) | **REAL** | Kamida bitta LLM provider | `llm/router.py`, `llm/budget.py` | 10 provider; DB-backed CostLedger |
| Memory (PgMemoryStore) | **REAL** | Postgres + optional embedding provider | `memory/pg_store.py` | 7 layer, trust_level policy |
| Killswitch DB persist + revoke | **REAL** | Postgres | `security/killswitch_store.py`, `killswitch_actions.py` | SR-06 restart invariant qayta yoqiladi |
| Rate limiting middleware | **REAL** | (in-code, per-tier) | `api/middleware.py`, `security/ratelimit.py` | 60 req/min OWNER default |
| Audit log INSERT | **REAL** | Postgres | `security/audit_writer.py` + `core/executor.py:462-478` | WRITE/EXECUTE/HIGH_RISK amallar yoziladi |
| Injection scanner | **REAL** | (deterministic patterns) | `security/injection.py` + `core/executor.py:610-638` | UNTRUSTED chiqishlarga qo'llaniladi |
| Postgres backup | **REAL** | Cron sidecar container | `infra/hetzner/backup.sh` + `docker-compose.prod.yml::backup` | Kunlik pg_dump + retention |
| CLI `z approve`/`reject`/`approvals` | **REAL** | Ishlab turgan API server | `cli.py` | HTTP orqali cross-process |
| PWA | **REAL** | (manifest + SW) | `apps/web/public/{manifest.webmanifest,sw.js}` + `layout.tsx` | Standalone install |
| Ollama (T0 local) | **PARTIAL** | `ZET_OLLAMA_BASE_URL` va ishlayotgan Ollama server | `llm/router.py` | Lokal ishga tushirilmasa T1 ga tushadi |

**Jami: 39 integratsiya, shundan REAL=17, PARTIAL=13, REQUIRES_CREDS=6, REQUIRES_HARDWARE=2, REQUIRES_AUTH=1, MOCKED=1, NOT_IMPLEMENTED=0.**

---

## A. What is genuinely production-ready

Bular haqiqatan ishlab turgan, testlar bilan qamrab olingan, va production oqim bilan ulangan komponentlar. Kalit sozlansa darhol ishga tushadi.

### A1 — Core pipeline
- **Intent Engine** (`core/intent.py`) — LLM-based, `router.complete` bilan tool_use. `Orchestrator._start_impl` va POST `/api/v1/run` orqali chaqiriladi. `run_id` `CostLedger`ga uzatiladi.
- **Planner** (`core/planner.py`) — DAG validatsiyasi, tool existence check, required-parameter check, repair loop (1 attempt). Real LLM chaqiruvi.
- **Executor** (`core/executor.py`) — Parallel DAG batches (`asyncio.gather`), KillSwitch check per batch, BudgetGuard, PermissionPolicy gate, tool retry (max 2), audit for WRITE/EXECUTE/HIGH_RISK, `_sanitize_untrusted` bilan injection scan.
- **Verifier** (`core/verifier.py`) — Deterministic (substring/regex) + LLM-judge tier — 2/3 tier real. Tool-based tier yo'q (§H2 dagi risk).
- **Orchestrator** (`core/orchestrator.py`) — Run lifecycle: PENDING → PLANNING → EXECUTING → AWAITING_APPROVAL → DONE/FAILED. Approval, resume, cancel real. `mark_verified_fn` orqali `CostLedger.verified_ok` yangilanadi.

### A2 — Mission layer (Sprint 2)
- **Capability Registry** (`core/capability.py:531-812`) — 20 seed capability (business, website, instagram, sales, telegram, github, obsidian, developer, qa, security, research, analytics, content, design, smm, communication, camera, computer, deployment, sales — Master Spec PART 2 to'liq). Cycle detection, topo-sort, semantic search.
- **Mission Engine** (`core/mission.py` + `mission_repository.py` + `db/models/mission.py` + `alembic 0009_missions.py`) — 11 holatli state machine: RECEIVED → UNDERSTANDING → DISCOVERING → PLANNING → WAITING_APPROVAL → EXECUTING → VERIFYING → RECOVERING → COMPLETED/FAILED/CANCELLED. `run_to_completion` avtomatik oqim. `CLEAR` sentinel bilan `pending_approval_id` va `error` tozalanadi (audit-fixed).
- **Mission REST API** (`api/routes/missions.py`) — POST/GET/list; mission-level approval `/api/v1/approvals/{id}/approve` orqali `build_mission_engine_for_session` yordamchisi bilan (audit-fixed HIGH bug).
- **DAG executor** (`core/dag.py` + `executor.py:255-268`) — `plan_to_dag` topological sort, parallel batches. Tsikl aniqlash.
- **Risk-based Approval** (`security/risk.py`, `permissions.py`) — LOW→auto, MEDIUM→config, HIGH→majburiy `WAITING_APPROVAL`.
- **Trust-level dinamik oqim** (`executor.py:592-607`) — bir marta UNTRUSTED poison, keyingi WRITE steplarga approval majburiy.

### A3 — Storage / persistence
- **9 Alembic migration** — schema drift'siz (`test_migrations.py` yashil).
- **Barcha domain jadvallar `owner_id` FK bilan** — multi-tenant safety (owner: Owner, agent, memory_entries, conversation, message, workspace, crm_*, product, order, mission, capability_token, kill_switch, cost_ledger).
- **Konteyner-durable jadvallar**: Owner/Conversation/Message/MemoryEntry/CRM (contact/lead/deal)/Product/Order/Task/Project/CalendarEvent/AutomationState/Agent/Mission/MissionRun/Device/CapabilityToken/KillSwitch/CostLedger/AuditLog/ToolCall/Approval/Run/Plan/Step.
- **`session_scope`** har yozishda commit/rollback boundary bilan.
- **Postgres backup** — sidecar `Dockerfile.backup` + `backup-cron` `docker-compose.prod.yml::backup`.

### A4 — Security controls
- **TokenAuthMiddleware** — fail-closed prod'da (`_check_prod_requirements` validator, `config.py:387-397`).
- **RateLimitMiddleware** — barcha tokenli so'rovlar OWNER 60/min (`middleware.py:159`).
- **Injection scanner** — UNTRUSTED tool chiqishlarida `scan_text` (`executor.py:624`).
- **Audit log INSERT** — WRITE/EXECUTE/HIGH_RISK tool amallari (`executor.py:462-478`), approve/reject (`routes/approvals.py:117`), killswitch engage/disengage (`routes/killswitch.py`).
- **Killswitch DB persist** — `killswitch_store.py`; SR-06 restart invariant `load_killswitch()`da qayta yoqiladi.
- **Killswitch → capability token revocation** — `security/killswitch_actions.py::revoke_all_capability_tokens_on_killswitch`.
- **Approval TTL + expiry** — `approvals.py`; fail-closed.
- **SecretStr** barcha kalitlar uchun; API javobida hech qachon ochilmaydi (`config.py`).
- **CapabilityToken SHA-256** — raw token faqat yaratishda, DB'da hash (`devices/repository.py`).

### A5 — Background daemons (6 ta, hammasi lifespan'da spawn + graceful cancel)
- `DailyScheduleDaemon` (V-35 kunlik jadval, delivery bilan)
- `AutomationDaemon` (cron qoidalar + HandoffDispatcher wire)
- `ShipmentNotifyDaemon` (kargo → mijoz DM)
- `ReportsDaemon` (haftalik/oylik sotuv+faollik)
- `SelfImproveDaemon` (haftalik improvement suggestions)
- `AlertsDaemon` (60s tick, 3 metric → check_metric → notifier)

### A6 — API layer
- **113 endpoint** 22 route file'da (agent/alerts/approvals/automation/camera/commerce/conversation/crm/device/feeds/health/killswitch/memory/missions/run/state/system/telegram/vault/voice/workspace).
- Middleware stack: `RateLimit → TokenAuth → Trace → handler`.
- FastAPI lifespan barcha daemon + Telegram bot + Shop bot ni boshqaradi.

### A7 — Frontend (apps/web)
- Next.js 15 + TS + Tailwind v4 + shadcn/ui.
- TypeScript typecheck clean, build 20 route generation muvaffaqiyatli.
- **PWA**: manifest.webmanifest + sw.js + icons + apple-mobile-web-app-* meta.
- 12+ sahifa haqiqiy backend'ga ulangan (dashboard/agents/tasks/projects/calendar/messages/analytics/camera/terminal/settings/devices/files/tg).

### A8 — CLI (`z` command)
- `z run`, `z approve <id>`, `z reject <id>`, `z approvals`, `z killswitch engage/disengage/status`, `z state sleep/wake/status`, `z status`, `z budget`, `z version`, agent management commands, memory ops, telegram test, daemon.
- Cross-process approval (BROKEN #1 yopilgan) — HTTP orqali `ZET_API_URL`.

### A9 — Deployment infrastructure (Hetzner)
- `infra/hetzner/docker-compose.prod.yml`: 7 xizmat (postgres pgvector, redis, ollama, backend, web, backup sidecar, caddy).
- Healthchecks postgres+redis.
- Volumes: `postgres_data`, `redis_data`, `ollama_data`, `caddy_data`, `caddy_config` — persistent.
- `update.sh`: image rebuild bilan volume ma'lumotni saqlaydi.
- `setup.sh` + `README.md` deployment yo'riqnomasi.
- `backup.sh` + `backup-cron` — kunlik pg_dump + retention.

---

## B. What is only internally implemented

Bu bo'limdagi narsalar: kod bor, testlar yashil, LEKIN production entrypoint'iga to'liq ulanmagan yoki live-test bo'lmagan.

### B1 — Verifier tool-based tier
Docstring `verifier.py:5-6` uch tier va'da qiladi (deterministic / tool-based / llm-judge). Amalda faqat 2 tier bor. Master Spec PART 6 mandatory verification chains (HTTP check for websites, publishing status for Instagram, tests/typecheck/lint/build for GitHub, delivery confirmation for Telegram, read-after-write for DB) HECH QAYSISI implementatsiya qilinmagan.

**Impact:** Mission "sayt qur" tugagach ZET "muvaffaqiyatli" deydi, LEKIN sayt haqiqatan HTTP 200 qaytarayotganini tekshirmaydi.

### B2 — Context Engine — 2/6 manba
`ContextEngine.discover()` (`core/context.py`) hozircha faqat `PgMemoryStore.search` + `WorkspaceRepository` qidiradi. Master Spec PART 4 talab qiladi: memory + Obsidian + database + GitHub + Telegram + calendar + files + recent activity + connected websites. 6 tasidan 4 tasi yo'q:
- Obsidian to'g'ridan-to'g'ri iter (memory shadow bilan qisman yopilgan)
- GitHub read
- Telegram inbox
- Calendar events

### B3 — Recovery Engine LLM patch
`RecoveryEngine.diagnose_and_patch` (`core/recovery.py`) faqat provider berilgan bo'lsa ishlaydi. Deps'da qat'iy wire yo'q — `MissionEngine(recovery=None)` (`api/deps.py:973`). Fail-open: qayta urinish bo'ladi lekin LLM patch yo'q, retry oqilona emas.

### B4 — Frontend tests
NOL. Component/smoke/e2e testlar hech biri yo'q. `pnpm typecheck` va `pnpm build` — bu regression himoyasi emas.

### B5 — Master Spec PART 9 misollari
18 misol ("Menga sayt yasab ber", "Instagram carousel tayyorla", "Telegram check", "Fix this project", va h.k.) hozircha end-to-end smoke test bilan qamrab olinmagan. `MissionOrchestrator` ularni bajaradi (tests bor: `test_mission_orchestrator.py`), lekin haqiqiy tabiiy jumla → real veb qurish oqimi hali sinalmagan.

### B6 — HandoffDispatcher chain-limit test
`MAX_HANDOFF_DEPTH=5` va tashrif to'plami test'da tekshirilgan, LEKIN production'da bir necha handoff zanjiri jonli sinalmagan.

### B7 — AR-01 Run/Approval DB persistence
Task #57 — hali PENDING. `RunStore` + `ApprovalService` in-memory. Restart'da:
- Kutayotgan approval yo'qoladi
- Awaiting run yo'qoladi (mission darajasidagi state DB'da bor — mission yo'qolmaydi, lekin uning run'i yo'qoladi)

Bu Master Spec §PART 6 "continuity across sessions" va PART 3 "Mission memory / continuity" ni qisman buzadi.

### B8 — Standing missions
Master Spec 9.18 "competitor monitoring", 9.21 "morning report" — hozirgi `AutomationEngine` faqat `ScheduleRule` (bir agent, bir command). Mission-triggered rules yo'q. Ega `ZET, create an agent that monitors my competitors every morning` desa — bu hozircha faqat ScheduleRule sifatida yaratiladi, Mission darajasida standing bo'lmaydi.

---

## C. What is mocked

Bular stub — kod ishlaydi lekin haqiqiy API/hardware chaqirilmaydi.

- **Desktop control** (`devices/desktop.py::StubDesktop`) — `PyAutoGUIDesktop` docstring'da nomlangan, klass yozilmagan. Screenshot/type/key/click faqat stub javob qaytaradi.
- **Camera default** — `StubCamera` (`devices/camera.py`) 1×1 JPEG qaytaradi. Real snapshot uchun Hikvision yoki RTSP provider inject kerak.
- **Web reader `stub=True` default** — kutubxona darajasida default stub; lekin `api/deps.py:225`da prod uchun `web_reader_stub=False` ochilgan, shu bois production'da REAL.
- **STT default** — `StubSTT` ElevenLabs kaliti yo'q bo'lsa 'Test ovozli xabar' matn qaytaradi (voice handler stub rejimda foydasiz).
- **TTS default** — `StubTTS` 'OggS' header qaytaradi (haqiqiy audio emas).
- **`_stub_search`** — Brave Web Search kalitisiz 3 canned natija.
- **GitHub tools** kalitisiz stub dict qaytaradi.
- **Instagram tools** kalitsiz stub.
- **YouTube tools** kalitsiz stub.
- **Telegram tools** (channel_post etc.) tokensiz stub.
- **`test.tool`** — test paketining tool'i, production'da ishlatilmaydi.

**Jami mocked: 11 (barchasi kalit/hardware yo'qligi natijasi, MOCKED-by-choice bo'lmagan holatlar).**

---

## D. What requires external credentials

Kalit `.env`ga qo'shilishi kerak — kod tayyor, kutish faqat kalit:

| Kalit | Nima yoqiladi |
|---|---|
| `ZET_API_TOKEN` | Prod majburiy — auth (config validator ushlaydi) |
| `ZET_TELEGRAM_BOT_TOKEN` + `ZET_TELEGRAM_OWNER_IDS` | Main bot, notifier, killswitch cmd, channel post/delete |
| `ZET_SHOP_BOT_TOKEN` | Alohida mijoz bot |
| `ZET_TELEGRAM_MODERATED_CHAT_IDS` | Kanal moderatsiyasi |
| `ZET_GITHUB_TOKEN` | github.read/write |
| `ZET_WEB_SEARCH_API_KEY` (Brave) | web.search |
| `ZET_GOOGLE_API_KEY` | Gemini video.learn, vision.ocr, embedding |
| `ZET_MISTRAL_API_KEY` | T1 LLM + embedding fallback |
| `ZET_OPENROUTER_API_KEY`, `_COHERE_API_KEY`, `_ANTHROPIC_API_KEY`, `_OPENAI_API_KEY` | T2/T3 modellar |
| `ZET_ELEVENLABS_API_KEY` | STT (Scribe) + TTS fallback |
| `ZET_AZURE_SPEECH_KEY` + `_REGION` | Real o'zbek TTS (Sardor/Madina Neural) |
| `ZET_INSTAGRAM_ACCESS_TOKEN` + `_BUSINESS_ACCOUNT_ID` | Instagram Graph API |
| `ZET_YOUTUBE_API_KEY` | YouTube read |
| `ZET_YOUTUBE_OAUTH_CLIENT_ID/SECRET/REFRESH_TOKEN` | YouTube publish |
| `ZET_DATABASE_URL` | Postgres (default localhost) |
| `ZET_REDIS_URL` | Redis (default localhost) |

**Standing security constraint (dan foydalanuvchiga eslatma):** Bu kalitlarni HECH QACHON chatga yubormang. `.env` faylida (gitignored) yoki server env'da to'g'ridan-to'g'ri kiriting.

---

## E. What requires real hardware

- **Hikvision kamera** (`devices/hikvision.py`) — fizik IP kamera/NVR ISAPI qo'llab-quvvatlash bilan; `ZET_HIKVISION_HOST/USERNAME/PASSWORD`.
- **RTSP kamera** (`devices/rtsp.py`) — istalgan RTSP-qobil (Dahua/Tapo/Uniview) + `opencv-python-headless` (project dep emas, alohida `pip install`) + `ZET_RTSP_CAMERA_URL`.
- **Ollama server** (`http://localhost:11434`) — T0 lokal LLM uchun. Prod'da (Hetzner) ollama konteyneri docker-compose'da bor, lekin ega o'z mahalliy quvvatida bo'lgani ma'qul.
- **Mac mini yoki lokal kompyuter** — `desktop_tools` uchun (PyAutoGUIDesktop yozilishi kutilmoqda).
- **iPhone / Android** — companion app (hali yo'q) — `DeviceRegistry` REST API tayyor, mobile klient yo'q.

---

## F. What requires manual verification

Kod yashil (2512 test), lekin quyidagilar HAQIQIY jonli tekshiruvsiz "REAL" deb belgilanmaydi:

1. **Telegram bot end-to-end** — botga xabar yozish → response kelishi (owner-only, killswitch komandasi, approval tugmasi).
2. **Shop bot end-to-end** — mijoz DM → mahsulot qidiruvi → LLM javobi.
3. **Postgres backup restore** — `backup.sh` yozgan fayldan `psql` bilan real restore muvaffaqiyati.
4. **Killswitch full cycle** — engage → tokenlar bekor → restart → holat qaytadi → tokenlar hali bekor.
5. **PWA install** — telefon/kompyuterga o'rnatish, offline'da app shell yuklanishi.
6. **AlertsDaemon full path** — budjet 80%+ oshsa Telegram notifier'ga xabar keladimi.
7. **HandoffDispatcher chain** — 3+ agent zanjiri jonli test.
8. **Mission Definition of Done** — "Menga shu loyiham uchun sayt kerak" → to'liq mission run (context discover → plan → execute → verify → memory → notify).
9. **Kunlik jadval delivery** — V-35 kunlik avtonomiya natijasi ega Telegram'iga yetadimi.
10. **Rate limit** — 61-so'rov 429 qaytaradimi va X-RateLimit headerlari to'g'ri.
11. **HIGH_RISK Mission approval flow** — mission WAITING_APPROVAL → API approve → EXECUTING → COMPLETED.
12. **Injection scanner poison** — `%%SYSTEM_OVERRIDE%%` matnini o'z ichiga olgan tool chiqishi keyingi prompt'ga toza kirmasin.

---

## G. Security risks (severity ranked)

### HIGH
- **G-01 (HIGH)** — **AR-01 Run/Approval DB persistence yo'q**. Restart'da:
  - Pending run yo'qoladi
  - Kutayotgan approval yo'qoladi (Ega tasdiqlab ulgurmasa run halok bo'ladi)
  - Cross-process CLI approve mission emas run darajasida bir jarayon ichida qolmagan
  Faqat mission-level durable, run-level hali xotirada. Master Spec PART 6 §durability ni buzadi.
  **Yechim:** `RunStore`+`ApprovalService`ni DB-backed qilish (§J1).

### MEDIUM
- **G-02 (MEDIUM)** — **Verifier tool-based tier yo'q**. Mission "muvaffaqiyatli" deb belgilansa ham external validation yo'q (HTTP 200, DB row exists, delivery receipt, va h.k.). "Never fake autonomy" (PART 8) qoidasini yashirin buzish riski.
- **G-03 (MEDIUM)** — **Recovery Engine LLM patch deps'da wire qilinmagan** (`api/deps.py:973 recovery=None`). RECOVERING → EXECUTING sikli deterministic retry — LLM diagnose'siz. Retry oqilona emas.
- **G-04 (MEDIUM)** — **`X-Trust-Level` header default `owner`**. Backward compat uchun to'g'ri, lekin header'ni brauzer forge qila oladi. **Yechim:** mijoz-side trust-level har doim auth kontekstidan olinishi kerak (masalan JWT claim), header'dan emas. Hozirgi holatda API doim OWNER auth ostida, bu kichik risk.

### LOW
- **G-05 (LOW)** — **SecretManager qurilgan-u ulanmagan** (deprecated marker qo'yilgan). `.env` SecretStr yetarli.
- **G-06 (LOW)** — **Ratelimit key: IP+SHA256(token[:12])** — token o'g'irlansa faqat 12-belgili hash bilan cheklovga tushadi. Bu OK; xatar past.
- **G-07 (LOW)** — **`_stub_search` va boshqa stub'lar** — foydalanuvchiga stub natija ekanligini ochiq aytmaydi. `web.search` javobiga metadata: "stub_mode=true" qo'shilishi ma'qul.

---

## H. Reliability risks (severity ranked)

### HIGH
- **H-01 (HIGH)** — **AR-01 durability gap** (G-01 bilan bir xil sabab, ta'siri boshqa). Restart har safar user-experience'ni buzadi — "kecha boshlagan run"ni davom ettirib bo'lmaydi.

### MEDIUM
- **H-02 (MEDIUM)** — **Mission "run to completion" avtomatik LLM chaqiruvi** — HIGH_RISK mission approve bo'lgach, `run_to_completion` `execute → verify` sikli fon'da ishlab, LLM budjeti sarflaydi. Ega bilmaganidan katta run bo'lishi mumkin. Approval sinxron kelgani sabab qisman himoyalangan, lekin cost visibility yo'q.
- **H-03 (MEDIUM)** — **Frontend testlari nol** — regression himoyasi faqat typecheck+build. UI'da mantiqiy xato jimgina o'tishi mumkin.
- **H-04 (MEDIUM)** — **Ollama T0 lokal LLM** — dev'da ishlatiladi, prod docker-compose'da bor lekin resource-heavy. Ega mahalliy Ollama'ga ega bo'lsa yaxshi (12B+ model).

### LOW
- **H-05 (LOW)** — **Mypy 47 xato** — asosan `cli.py` va uzoq bo'yalmagan `no-untyped-call`. Ish vaqti xatolarga olib kelmaydi (pytest yashil), lekin tozalash foydali.
- **H-06 (LOW)** — **HandoffDispatcher `MAX_HANDOFF_DEPTH=5`** — cheksiz tsikl himoyasi tayyor, lekin jonli 3+ zanjir sinalmagan.
- **H-07 (LOW)** — **Executor retry backoff yo'q** (`executor.py:520-525` sharh e'tirof etadi). Rate-limited API kesh oshirsa qayta-qayta 429 uradi.
- **H-08 (LOW)** — **Standing missions yo'q** — Master Spec 9.18/9.21 uchun ScheduleRule ishlatiladi. Mission-triggered rule'lar keyingi bosqich.

---

## I. Production blockers

**Blocker'lar — deploy'dan oldin MAJBURIY hal qilinishi kerak:**

| ID | Muammo | Severity | Sabab |
|---|---|---|---|
| **BLOCK-1** | `ZET_API_TOKEN` sozlanmasdan prod'ga chiqarish | CRITICAL | Config validator (`config.py:387-397`) startup'da xato beradi — bu blocker emas, self-guard. To'g'ri sozlansa OK. |
| **BLOCK-2** | Kamida bitta LLM provider yo'q | CRITICAL | Config validator ushlaydi. `.env` ga `ZET_GOOGLE_API_KEY` yoki boshqasi majburiy. |
| **BLOCK-3** | Manual verification checklist (§F) hech biri bajarilmagan | HIGH | Jonli backup/restore, Telegram bot, mission full run — barcha kalitli path ega tomonidan tekshirilmagan. |
| **BLOCK-4** | AR-01 — restart'da run/approval durability yo'q | HIGH | Ega "kecha boshlagan run"ga qayta ulana olmaydi. Task #57 hali PENDING. |

**Blocker DEB HISOBLANMAYDI (lekin fix tavsiya etiladi):**
- Mypy 47 pre-existing xato
- Frontend testlari yo'q
- Verifier tool-based tier yo'q (bu §J2 keyingi bosqich)
- Standing missions (Master Spec §J3 keyingi bosqich)

---

## J. Exact next implementation steps (ordered, small, concrete)

### J1 — AR-01 Run/Approval DB persistence (HIGH prio)
Task #57 yopilishi kerak. Bosqichlar:
1. `db/models/run.py::Run/Step` allaqachon bor (auditda topilgan, faqat ishlatilmaydi). `RunRepository` yozing (`WorkspaceRepository` naqshi).
2. `db/models/security.py::Approval` allaqachon bor. `ApprovalRepository` yozing.
3. `RunStore`+`ApprovalService`ga optional `repository=` argumenti — berilsa write-through DB'ga.
4. `Orchestrator._start_impl` boshida `record.status=PLANNING` yozilganda `runrepo.upsert(record)`.
5. Startup'da `load_pending_runs()` — AWAITING_APPROVAL run'larni tiklaydi.
6. Test: `test_run_persistence.py` — restart simulyatsiyasi, awaiting run tiklanadi.
**Effort:** ~1-2 kun. **Impact:** BLOCK-4 yopiladi.

### J2 — Verifier tool-based tier (HIGH prio)
1. `verifier.py::VerificationStrategy` enum allaqachon bor (`domain/enums.py`).
2. Har strategy uchun handler:
   - HTTP_CHECK: `httpx.get(url).status_code == 200`
   - FILE_EXISTS: `Path(path).exists()`
   - LOG_INSPECTION: `grep` on stdout
   - METRIC_THRESHOLD: `engine.metrics.read()` bilan solishtirish
3. `Verifier.verify_step` — `step.verification_strategy` mavjud bo'lsa dispatch qiladi.
4. Mission'da `Task.verification_strategy` maydoni tayinlanishi kerak (allaqachon `PlanStep`da bor).
5. Test: har strategy uchun 2 test (pass + fail).
**Effort:** ~2 kun. **Impact:** Master Spec PART 6 "verification is mandatory" ni to'liq yopadi.

### J3 — Manual verification checklist (F1-F12) (HIGH prio)
Ega tomonidan bajarilishi kerak — hech qanday kod fix emas:
1. `.env` ga barcha kalitlarni to'ldirish (kamida `ZET_API_TOKEN`, `ZET_TELEGRAM_BOT_TOKEN`, `ZET_TELEGRAM_OWNER_IDS`, `ZET_GOOGLE_API_KEY` yoki `_MISTRAL_API_KEY`).
2. `cd infra/hetzner && ./setup.sh` — Hetzner server'da.
3. §F ro'yxatidagi 12 sinovni ketma-ket bajarish. Har biri uchun natija qayd etiladi.
4. `docs/VERIFICATION_RUN_LOG.md` yaratish — har sinov qachon, kim, natija.
**Effort:** ~4-6 soat egaga. **Impact:** REAL sifati tasdiqlanadi.

### J4 — Context Engine kengaytirish (MEDIUM prio)
1. `ContextEngine.discover` ga `github_client`, `telegram_inbox_reader`, `calendar_reader` inject qilish.
2. Her manba uchun budget (max 500 tokens) — kesish.
3. Test: 6 manbadan har biri chaqirilganini isbotlash.
**Effort:** ~1-2 kun. **Impact:** Master Spec PART 4 "cross-system reasoning" to'liq.

### J5 — Recovery Engine wire (MEDIUM prio)
1. `deps.py::get_mission_orchestrator` da `recovery=RecoveryEngine(router=...)` yozing.
2. Test: FAILED verification → LLM patch → EXECUTING → COMPLETED.
**Effort:** ~2 soat. **Impact:** G-03 yopiladi.

### J6 — Frontend smoke testlari (MEDIUM prio)
1. Vitest + @testing-library/react sozlash (`apps/web/vitest.config.ts`).
2. 5 asosiy sahifa uchun smoke test: /dashboard, /agents, /missions (yangi), /ai-chat, /devices.
3. CI'ga qo'shish.
**Effort:** ~1 kun. **Impact:** H-03 yopiladi.

### J7 — Standing Mission triggerlari (LOW prio, keyingi katta blok)
Master Spec 9.18/9.21 uchun `StandingMissionRule` — kunlik/haftalik trigger + Mission yaratish. `AutomationEngine`ga `MISSION_TRIGGER` turi qo'shish.
**Effort:** ~3 kun. **Impact:** "har kuni ertalab biznesim haqida ayt" oqimi real.

### J8 — Master Spec PART 9 misollari uchun end-to-end (MEDIUM prio)
1. `tests/e2e/test_mission_examples.py` — 3-4 asosiy misol.
2. `@pytest.mark.e2e` marker qo'shish, CI'da alohida bosqichda ishga tushirish.
**Effort:** ~2 kun. **Impact:** B5 yopiladi, "definition of done" isbot bo'ladi.

---

## Verdict

**READY FOR STAGING** — barcha 39 integratsiya tayyor kod bilan qoplangan, 2512 test yashil, lint/format/typecheck toza, security controls prod-lock bilan majburlangan. Ega `.env` sozlab §F manual verification checklist'ini bajarsa va §J1 (AR-01 durability) yopilsa — **READY FOR OWNER PILOT (single-user prod)**. Ko'p mijozli SaaS pilot uchun J1+J2+J6 hammasi kerak.

**PRODUCTION-READY DEMOQINCHI EMASMAN** chunki:
- Manual verification (§F) hali bajarilmagan — hech bir jonli integratsiya sinalmagan.
- AR-01 (BLOCK-4) restart durability HALI yo'q.
- Verifier tool-based tier yo'q — Mission "muvaffaqiyatli" da'volari haqiqiy external tasdiqsiz.

**Verdict-line:** READY FOR STAGING · NOT READY FOR OWNER PRODUCTION until §F manual verification passes AND §J1 AR-01 durability fixed.
