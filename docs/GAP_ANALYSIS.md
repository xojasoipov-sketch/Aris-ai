# ZET — Gap Analysis (P0.2 — Post-Build Re-Audit)

> Sana: 2026-08-13 · Metod: 9 ta parallel, kod-darajasidagi audit (o'qish-only, hech qanday
> kod o'zgartirilmadi) · Qamrov: `apps/core/src/zet` (backend), `apps/web/src` (frontend),
> `infra/`, `.github/`.

---

## 📌 IMPLEMENTATSIYA HOLATI (2026-08-13 kechqurun yangilanish)

**Bu hujjatning §3–§13 auditidan keyin bir SESSIYA davomida quyidagilar YOPILDI:**

**Phase A** (BROKEN #2/#3/#4, backup):
- ✅ `DailyScheduleDaemon._deliver()` — kunlik avtonomiya natijasi egaga yetadi
- ✅ Telegram inline approval → haqiqiy `ApprovalService.approve()`+`orchestrator.resume()`
- ✅ Killswitch DB persistence (restart'da yoqilgan holat saqlanadi)
- ✅ Postgres kunlik `pg_dump` sidecar + retention (HR-02)
- ✅ Haftalik/oylik sotuv+faollik hisoboti daemon

**Phase B** (AR-02, SR-01/02/05, A-04/07):
- ✅ Trust-level dinamik oqim (`_propagate_trust`) — A-05 to'liq yopildi
- ✅ Injection skaner UNTRUSTED chiqishlarda ishlatiladi (SR-01)
- ✅ `web.read` SSRF redirect fix (`follow_redirects=False` + qo'lda hop tekshiruvi)
- ✅ Audit log INSERT — `Executor` WRITE/EXECUTE/HIGH_RISK amallarida yozadi (SR-02)
- ✅ Model Router `run_id` + `verified_ok` — A-04 feedback loop
- ✅ Run timeout + concurrency semafora (A-07)

**Phase C** (§5, SR-03):
- ✅ CRM tools (contact.*, lead.*, deal.*, crm.stats) Sales/Support agentlarga
- ✅ RateLimitMiddleware ulandi — token o'g'irlansa 60 req/min OWNER limiti

**Phase D** (§5, 4-xususiyat):
- ✅ HR agent → AI workforce manager (yangi asosiy talab: agent.list/pause/resume/disable/stats)
- ✅ QA agent yaratildi (github.read+write+web.read; static+dynamic quality guard)
- ✅ E-commerce agent yaratildi (product.*, order.*, sales.stats)
- ✅ HandoffDispatcher production oqimiga ulandi (AutomationDaemon → AGENT_HANDOFF)

**Qo'shimcha yakuniy tuzatishlar** (BROKEN #1, V-01, V-13, A-06):
- ✅ CLI `z approve`/`z reject`/`z approvals` — HTTP orqali API'ga (cross-process muammosi yopildi)
- ✅ Verifier LLM-judge tier — jonli-tildagi expected_outcome uchun T1_FREE model bilan real tekshiruv
- ✅ `memory.write` tool — trust_level+layer siyosati bilan (WRITE_POLICY tekshiriladi)
- ✅ DeviceRegistry DB persist + REST API + CapabilityToken tokenlari (SHA-256 hash)

**Hozirgi test soni: 2313** (auditda edi 2212 → +101 yangi test).

**Qolgan (P1/P2/P3):**
- ⏳ **Task #57 — AR-01**: Run/Approval DB persistence (systemic — eng katta refactor, keyingi sessiya)
- ⏳ Obsidian↔Postgres sync (A-03)
- ⏳ PWA/manifest/service-worker + frontend testlari
- ⏳ pgvector (past ustuvorlik — hozirgi ma'lumot hajmida shart emas)
- ⏳ Railway rasman o'chirilishi (HR-03)
- ⏳ Xususiy tarmoq (WireGuard) — Mac mini kelganda

---

## 0. Bu hujjat nima va nega yozildi

Egasi original "JARVIS master build prompt"ni (40-slaydli vision, keyin kengaytirilgan versiya)
qayta yubordi va **audit-birinchi** yondashuvni talab qildi: katta implementatsiyadan oldin
repository to'liq tekshirilishi kerak.

**Muhim nomlash izohi.** So'ralgan `docs/JARVIS_VISION.md` / `JARVIS_ARCHITECTURE.md` /
`JARVIS_ROADMAP.md` fayllari **mavjud emas** — bu repo boshidanoq **ZET** deb nomlangan.
`docs/00-AUDIT.md` (loyihaning eng birinchi hujjati, 2026-08-11) buni aniq qayd etgan:
original vision materiali "JARVIS" nomini ishlatgan, lekin F-05 topilmasi asosida barcha
hujjat/kod/UI matni **ZET / Z**ga o'tkazilgan (fictional Iron Man AI bilan chalkashmaslik
uchun). Shuning uchun bu audit ZET kodini original vision'ga (`00-AUDIT.md`,
`01-VISION-GAP.md`, `02-MASTER-PLAN.md` — V-01..V-45, A-01..A-08, R-01..R-12) va yangi
kengaytirilgan so'rovga (HR = AI workforce manager, qurilma registri lifecycle, WireGuard
xususiy tarmoq, PWA sleep/active/companion rejimlari, Mac mini kelajak maqsadi) nisbatan
solishtiradi.

**`01-VISION-GAP.md` ESKIRGAN.** U repo BO'SH bo'lganda yozilgan — barcha V-band'lar "0%"
belgilangan. Hozir **2,212 ta test** yig'iladi (`apps/core`, `pytest --collect-only`),
~180 backend modul, to'liq Next.js frontend. Quyidagi audit — HAQIQIY, HOZIRGI holat.

**Metod.** 9 ta mustaqil, parallel ravishda ishga tushirilgan o'qish-only agent har biri
o'z sohasini kod darajasida (fayl:qator citata bilan) tekshirdi, docstring/nom emas —
haqiqiy implementatsiya asosida REAL/PARTIAL/MOCK/MISSING/BROKEN deb belgiladi. Natijalar
quyida sintez qilingan.

---

## 1. Umumiy holat — bitta jumlada

**ZET vision'ning yadrosi (Core pipeline, Model Router, Automation Engine, Frontend
dashboard, Telegram bot, CRM/Commerce, Tool Registry, Agent lifecycle) haqiqatan ishlaydi
va yaxshi testlangan — lekin xavfsizlik va davomiylik (persistence) qatlamlarining aksariyati
"qurilgan, lekin ulanmagan" holatda: ma'lumotlar bazasi sxemalari mavjud, real ishlaydigan
runtime esa ularni umuman ishlatmay, xotirada (in-memory) davom etadi.** Bu — bitta joydagi
xato emas, **tizimli naqsh**: Run/Approval/KillSwitch/AuditLog/GoalRegistry/DeviceRegistry —
barchasi shu bitta muammoni takrorlaydi.

---

## 2. Ijro xulosasi — 12 bo'lim + yangi so'rovlar

| # | Soha | Holat | Bitta jumlada |
|---|---|---|---|
| 1 | Z Core pipeline (intent→plan→exec→verify) | ✅ **REAL** | Ishlaydi, testlangan (14+13+12+19 test); Verifier faqat deterministik (LLM-judge yo'q) |
| 1 | Run/Step holat mashinasi (A-01: DB'da saqlanishi kerak) | 🔴 **BROKEN** | Sxema real, runtime `RunStore` — **xotirada**. Restart = run yo'qoladi. CLI↔API approval **ishlamaydi** (boshqa jarayon) |
| 1 | Model Router (4 tier, budget, kvota, cost ledger) | ✅ **REAL** | Eng yaxshi qurilgan qism — DB-backed, testlangan (29 test). `verified_ok`/`run_id` ulanmagan (kichik gap) |
| 1 | Approval gate / Emergency stop | 🟡 **PARTIAL/MOCK** | Mantiq real va fail-closed, lekin **xotirada** (DB jadvali bor, ishlatilmaydi). Restart = pending approval yo'qoladi |
| 1 | Observability/trace/cost per-run | 🟡 **PARTIAL** | `trace_id` real; querylanadigan per-run cost/token izi yo'q (Run/CostLedger bog'lanmagan) |
| 1 | Loop-brake (depth/budget/timeout/concurrency, A-07) | 🟡 **PARTIAL** | `max_steps`+budget real; `max_depth`/`timeout_s`/concurrency — **e'lon qilingan, hech qayerda ishlatilmagan** |
| 2 | Xotira — 7 qatlam, semantik qidiruv | 🟡 **PARTIAL** | Real hybrid qidiruv + 4 embedding provayder, lekin **pgvector yo'q** (Python'da brute-force cosine — scale bo'lmaydi), reranking yo'q |
| 2 | Xotira 5 xossasi (search/edit/version/permission/delete) | 🟡 **PARTIAL** | 3/5 real; versiyalash = faqat counter (tarix yo'q); permission-aware = faqat owner-isolyatsiya (trust-level siyosati API'da tekshirilmaydi) |
| 2 | Obsidian (A-03: Postgres=asosiy, Obsidian=proyeksiya) | 🔴 **MISSING** (sync) | Real, ishlaydigan Obsidian-formatdagi note tool bor — lekin Postgres xotirasi bilan **hech qanday bog'liqlik yo'q** |
| 2 | Qaror/bilim xotirasi (V-16) | 🔴 **MISSING** | ZET faqat suhbatni yozadi, "qaror"/"bilim" konsepti yo'q; agentda memory-write tool yo'q |
| 3 | Tool Registry (interfeys, allowlist, permission) | ✅ **REAL** | 38 ta tool ro'yxatga olingan, real permission+schema tekshiruvi |
| 3 | Agent Runtime | ✅ **REAL** | Real tool-loop, brake'lar; "verify" bosqichi — faqat hujjatlashtirilgan, kodda yo'q |
| 3 | Agent = DB yozuv (A-02) | ✅ **REAL** | To'liq mos, write-through repository |
| 3 | Agent lifecycle (V-11) | ✅ **REAL** | State machine to'g'ri; registry o'zi xotirada, lekin repository orqali DB'ga yoziladi (yechilgan) |
| 4 | Agent Factory (V-10) | 🟡 **PARTIAL** | Pipeline real va ishlaydi, lekin "UNDERSTAND"/"DESIGN" = **kalit-so'z lookup**, LLM emas; "eval" = statik lint, xulq-atvor testi emas |
| 4 | 12 ta builtin agent | ✅ **REAL** | Barchasi ro'yxatdan o'tgan, ACTIVE, ishga tushadi |
| 4 | HR agent = AI workforce manager (yangi so'rov) | 🔴 **MISSING** | Mavjud HR agent — inson-HR tahlilchisi; boshqa agentni pause/resume/create qiladigan TOOL umuman yo'q |
| 4 | Agent-to-agent zanjir (V-08) | 🟡 **PARTIAL** | Statik `WorkflowExecutor` real va ulangan; reaktiv `HandoffDispatcher` qurilgan+testlangan, lekin **production oqimiga ulanmagan** |
| 5 | Telegram bot (asosiy, owner) | ✅ **REAL** | Real polling, owner allowlist, voice/photo (photo/document — stub javob) |
| 5 | Telegram inline approval tugmalari | 🔴 **BROKEN** | UI/parsing real, lekin ✅/❌ bosish **haqiqiy approve/resume'ni chaqirmaydi** — kosmetik |
| 5 | Voice STT/TTS | ✅ **REAL** (kalit bilan) | ElevenLabs+Azure real, fail-open stub |
| 5 | Shop bot (mijoz DM, #42) | ✅ **REAL** | Mustaqil, tool'siz, testlangan |
| 5 | Kanal moderatsiyasi (#44) | ✅ **REAL** | Deterministik, LLM emas, testlangan |
| 5 | Kargo xabari daemon (#43) | ✅ **REAL** | Eng toza avtomatlashtirish misoli — LLM'siz, idempotent |
| 6 | CRM (PgCRM) | ✅ **REAL** | DB+API to'liq, lekin **agentlarga tool sifatida ulanmagan** (Sales agent CRM'ga kira olmaydi) |
| 6 | Biznes agentlar (SMM/Sales/Finance/Support) | 🟡 **PARTIAL** | Spec'lar real; SMM kuchli qurilgan, qolgan 3tasi (`web.search`,`time.now`dan) ma'lumotiga yeta olmaydi |
| 6 | E-commerce agent | 🔴 **MISSING** | Fayl yo'q (vision hujjatida ham Bo'lim 12'ga qoldirilgan) |
| 7 | GitHub integratsiya | ✅ **REAL** | Real API, fail-open stub |
| 7 | Web search/read | ✅ **REAL** | Real, lekin `web.read` SSRF tekshiruvi **redirect'larda qayta qo'llanmaydi** (haqiqiy zaiflik) |
| 7 | Untrusted input chegarasi (A-05, R-01) | 🔴 **PARTIAL — eng katta xavfsizlik gap** | `TrustLevel` teglanadi, lekin **dinamik oqim bo'ylab tarqalmaydi** — UNTRUSTED tool natijasi keyingi WRITE qadamni avtomatik eskalatsiya qilmaydi |
| 7 | Prompt-injection skanери | 🟡 **PARTIAL** | 25+ pattern, 35 test — YAXSHI qurilgan, lekin **orchestrator/executor'da hech qachon chaqirilmaydi** |
| 7 | Developer agent | ✅ **REAL** | To'liq spec, GitHub bilan ishlaydi |
| 7 | QA agent | 🔴 **MISSING** | Umuman yo'q |
| 7 | Security agent | 🟡 **PARTIAL** | Spec bor, lekin tool_allowlist = `["time.now"]` — audit/killswitch/secret modullariga kira olmaydi |
| 8 | Kamera (Hikvision) | 🟡 **PARTIAL** | Bitta vendor (snapshot only) real; RTSP/EZVIZ/PTZ/motion/zone — faqat docstring |
| 8 | Vision Agent | 🟡 **PARTIAL/MOCK** | Spec real, lekin OCR tool yo'q, faqat camera.snapshot |
| 8 | Telefon boshqaruvi | 🔴 **MISSING** | 0% — pairing, companion app, IDeviceProvider yo'q |
| 8 | Kompyuter boshqaruvi | 🔴 **PARTIAL/MOCK** | `shell.exec` mavjud, lekin default OFF va **hech qanday agentga ulanmagan**; desktop control = stub-only (`PyAutoGUIDesktop` yozilmagan) |
| 8 | Qurilma registri + capability token (A-06) | 🔴 **MOCK** | Xotirada, DB modeli yo'q, hech qayerdan chaqirilmaydi, killswitch bilan bog'lanmagan |
| 9 | Automation Engine (trigger→action) | ✅ **REAL** | Kuchli — 5 wake mexanizmi, persistence, brake'lar, hammasi testlangan (~306 test) |
| 9 | Kunlik avtonomiya jadvali (V-35) | 🔴 **BROKEN** | Real jadval, real ishga tushadi, byudjet sarflaydi — **lekin natija egasiga HECH QACHON yetkazilmaydi** (delivery yo'q) |
| 9 | "TIZIM" retseptlari (T01-T06) | ✅ **REAL** | Halol modellashtirish — 2/6 READY, 4/6 to'g'ri MISSING_CAPABILITY |
| 9 | Self-improvement (V-36) | 🔴 **MOCK** | To'liq qurilgan, approval-gated data klass, lekin **hech kim `.suggest()` chaqirmaydi** — bo'sh qobiq |
| 9 | L0-L4 avtonomiya darajalari | ✅ **REAL** | Yaxshi qurilgan, testlangan, approval invariant tasdiqlangan |
| 10 | Frontend — dashboard sahifalar | ✅ **REAL** | 14/14 sahifa haqiqiy backend bilan, qattiq kodlangan massiv topilmadi |
| 10 | Assistant holat mashinasi (Sleep/Active) | 🟡 **PARTIAL** | Reducer+tovush real; global "faqat orb" sleep rejimi **yo'q** (chrome doim ko'rinadi); notification kontenti soxta |
| 10 | NEXUS immersiv dashboard | ✅ **REAL** | Eng yaxshi qism — real qo'l harakati, real ma'lumot, halol bo'sh holatlar |
| 10 | Telegram Mini App | 🟡 **PARTIAL** | 3/6 real, 2/6 (Camera/Settings) qattiq kodlangan, Projects tab yo'q |
| 10 | PWA/companion rejim (yangi so'rov) | 🔴 **MISSING** | manifest/service-worker/`public/` — umuman yo'q |
| 10 | Frontend testlari | 🔴 **MISSING** | Bitta ham yo'q (unit/component/e2e) |
| 11 | Auth (`ZET_API_TOKEN`) | ✅ **REAL** | Constant-time compare, default-deny |
| 11 | Permission modeli (READ/WRITE/EXECUTE/ADMIN) | ✅ **REAL** | Ikki mustaqil joyda tekshiriladi |
| 11 | Killswitch — restart'dan keyin | 🔴 **BROKEN** | Docstring "DB'da saqlanadi" deydi — **yolg'on**. Restart = killswitch o'chadi. Telegram orqali yoqib bo'lmaydi |
| 11 | Audit log | 🔴 **MISSING** (deyarli) | Ikki marta qurilgan (hash-chain + Postgres trigger), lekin **hech qayerda `.append()`/INSERT chaqirilmaydi** — jadval doim bo'sh |
| 11 | Rate limiting | 🔴 **MISSING** | To'liq qurilgan `RateLimiter`, lekin middleware'ga **ulanmagan** — token o'g'irlansa cheklov yo'q |
| 11 | Secrets boshqaruvi | ✅ **REAL** | 28 `SecretStr`, gitleaks pre-commit+CI, `.env` hech qachon commit qilinmagan |
| 12 | Hetzner deploy skriptlari | ✅ **REAL** | `setup.sh`/`update.sh` mustahkam, idempotent, halol tekshiruv bilan |
| 12 | Railway o'chirilganmi | 🔴 **YO'Q, xato taxmin edi** | `railway.json` fayllar HALI HAM mavjud (2026-08-12 sanasida yangilangan), kodda Railway-branch'lar hali ham bor |
| 12 | CI/CD | ✅ **REAL** | lint+mypy+pytest+coverage(70%)+gitleaks+docker build |
| 12 | Backup/restore | 🔴 **MISSING** | Faqat konfiguratsiya bayrog'i bor, hech narsa amalga oshirmaydi |
| 12 | Xususiy tarmoq (WireGuard, yangi so'rov) | 🔴 **MISSING** | Kod, reja, hujjat — hech narsa yo'q (hozircha kutilgan, Mac mini yo'q) |

---

## 3. Nima ISHLAYDI (REAL, ishonch bilan qurish mumkin)

- **Z Core pipeline** — intent→plan→execute pipeline haqiqiy, yaxshi testlangan.
- **Model Router** — 4-tier marshrutlash, circuit breaker, DB-backed budget/kvota — repo'ning
  eng yaxshi qurilgan qismi.
- **Tool Registry + Agent Runtime + 12 builtin agent** — hammasi ishlaydi, DB'ga yoziladi.
- **Automation Engine** (trigger→action, persistence, brake'lar, TIZIM retseptlari) — kuchli,
  ~306 test.
- **Telegram owner bot** (matn/ovoz), **Shop bot**, **kanal moderatsiyasi**, **kargo xabari
  daemon** — barchasi Z50/Z51 sessiyasida qurilgan, real va testlangan.
- **CRM, Commerce/Order tizimi** — DB-backed, testlangan (faqat agentlarga ulanmagan).
- **Frontend dashboard** (14 sahifa) va **NEXUS** — g'ayrioddiy halol: har bir sahifada
  "avval qattiq kodlangan massiv edi, olib tashlandi" degan izoh bor.
- **Auth, Permission modeli, Secrets boshqaruvi, CI/CD, Hetzner deploy skriptlari** —
  xavfsizlik poydevorining bu qismi mustahkam.

## 4. Nima QISMAN (PARTIAL — ishlaydi, lekin to'liq emas)

- Xotira: hybrid qidiruv real, pgvector yo'q (scale muammosi).
- Agent Factory: pipeline real, "tushunish" kalit-so'z, LLM emas.
- Biznes agentlar: spec real, ko'plari o'z ma'lumot bazasiga (CRM) kira olmaydi.
- Kamera: bitta vendor, snapshot-only.
- Loop-brake'lar: ba'zilari (steps, budget) ishlaydi, ba'zilari (depth, timeout, concurrency)
  e'lon qilingan-u ishlatilmagan.

## 5. Nima SOXTA (MOCK — kod bor, lekin ulanmagan yoki hech narsa qilmaydi)

- `RateLimiter`, `SecretManager`, `AuditLog` (ikkala implementatsiya), `CostTracker`,
  `HandoffDispatcher`, `DeviceRegistry`, `CapabilityToken`, `SelfImproveEngine`,
  `MemoryManager`/policy engine — **barchasi to'liq yozilgan va o'z testlarida yashil, lekin
  production kodidan hech qachon chaqirilmaydi.** Bu — "qurilgan-lekin-ulanmagan" texnik
  qarzning eng aniq ko'rinishi.
- Desktop control (`PyAutoGUIDesktop`) — faqat docstringda, klass yozilmagan.

## 6. Nima YO'Q (MISSING — hatto mock ham yo'q)

- Telefon boshqaruvi (pairing, companion app) — 0%.
- QA agent, E-commerce agent — fayl yo'q.
- Obsidian↔Postgres sinxronizatsiyasi (A-03).
- Qaror/bilim xotirasi (faqat suhbat saqlanadi).
- Backup/restore mexanizmi.
- PWA/companion rejim, frontend testlari.
- Xususiy tarmoq (WireGuard) — kutilgan, chunki Mac mini hali yo'q.
- HR agentning boshqa AI agentlarni boshqarishi (yangi so'rovning markaziy g'oyasi).

## 7. Nima BUZILGAN (BROKEN — ishlaydi deb da'vo qilinadi, lekin amalda ishlamaydi)

Bu eng muhim ro'yxat — chunki bular "hech narsa yo'q" emas, **"bor deb ko'rinadi, lekin
ishlamaydi"** holatlar:

1. **Run holat mashinasi cross-process approval'i buzilgan.** `z run` CLI orqali
   `AWAITING_APPROVAL`ga tushgan run — API serverning `RunStore`si (alohida jarayon,
   alohida xotira) buni **hech qachon ko'rmaydi**. CLI chop etgan "approve URL" 404 beradi.
   `z approve` CLI komandasi ham umuman yo'q.
2. **Telegram inline approval tugmalari kosmetik.** ✅/❌ bosish chiroyli javob matnini
   qaytaradi, lekin haqiqiy `ApprovalService.approve()`/`orchestrator.resume()`ni
   **hech qachon chaqirmaydi**. Bu V-17 ("Telegram = asosiy boshqaruv paneli") va V-32
   (approval gate) ikkalasini ham buzadi — egasi eng ko'p ishlatadigan interfeysda.
3. **Killswitch restart'da o'chib qoladi.** Docstring "DB'da saqlanadi" deydi; amalda
   `@lru_cache` orqali xotirada. Hetzner'dagi `update.sh` — konteynerni qayta qurish —
   RUTIN amal, ya'ni har yangilanishda favqulodda to'xtatish holati yo'qoladi.
4. **Kunlik avtonomiya (V-35, 08:00/09:00/12:00/18:00/21:00) natijasi hech kimga
   yetmaydi.** `DailyScheduleDaemon` haqiqiy ishlaydi, byudjet/token sarflaydi, lekin
   `AutomationDaemon`dagi kabi `_deliver()` mexanizmi yo'q — natija loglanadi va yo'qoladi.

---

## 8. ARCHITECTURE RISKS

| ID | Xavf | Ta'sir | Yechim yo'nalishi |
|---|---|---|---|
| AR-01 | In-memory↔DB ikkilanishi (Run/Approval/KillSwitch/Audit/Goal/Device) — bitta naqsh, 6 joyda takrorlangan | 🔴 Kritik — restart = ma'lumot yo'qotish, cross-process buzilish | Bitta umumiy "state-store" abstraksiyasi: DB birinchi, xotira faqat cache sifatida (yoki aksincha, lekin **bittasi**) |
| AR-02 | A-05 trust-level dinamik tarqalmaydi — statik Run/Agent darajasida qotib qolgan | 🔴 Kritik xavfsizlik | `ToolResult.trust_level`ni keyingi qadam kontekstiga o'tkazish, `PermissionPolicy.check()`ga real qiymat berish |
| AR-03 | Ko'plab "ikkinchi implementatsiya" (AuditLog x2, RateLimiter, SecretManager, CostTracker) — birinchisi hech qachon ulanmagan, ikkinchisi qurilgan, lekin ham ulanmagan | 🟡 O'rta — texnik qarz, chalkashtiruvchi | Duplikatlardan birini o'chirish, qolganini production yo'liga ulash |
| AR-04 | `GoalRegistry` persistence yo'q (5-xususiyat — self-planning) | 🟡 O'rta | `AutomationState` snapshot'iga qo'shish (naqsh allaqachon mavjud) |
| AR-05 | Agent Factory "tushunish" bosqichi LLM emas — kalit-so'z lookup, kengaymaydi | 🟡 O'rta | LLM-based intent extraction qo'shish (Model Router allaqachon bor) |

## 9. SECURITY RISKS

| ID | Xavf | Ta'sir | Yechim yo'nalishi |
|---|---|---|---|
| SR-01 | Prompt injection skaneri (25+ pattern, 35 test) production yo'liga **ulanmagan** | 🔴 Kritik — R-01 amalda yopilmagan | `core/executor.py`da UNTRUSTED tool natijasini keyingi promptga qo'shishdan oldin skanerdan o'tkazish |
| SR-02 | Audit log jadvali doim bo'sh — forensika/incident-response imkonsiz | 🔴 Yuqori — R-04/R-11 mitigatsiyasi ishlamaydi | `tools/registry.py::execute()` va permission-check nuqtalarida `AuditLog` INSERT qo'shish |
| SR-03 | Rate limiting yo'q — token o'g'irlansa cheksiz so'rov | 🟡 O'rta | `RateLimiter`ni ASGI middleware sifatida ulash |
| SR-04 | Killswitch Telegram orqali yoqilmaydi (asosiy boshqaruv kanali) | 🟡 O'rta | `/killswitch` komandasini haqiqiy `KillSwitchState`ga ulash |
| SR-05 | `web.read` SSRF tekshiruvi redirect zanjirida qayta qo'llanmaydi | 🟡 O'rta | Har bir redirect hop uchun `_validate_url`ni qayta chaqirish yoki `follow_redirects=False` + qo'lda tekshiruv |
| SR-06 | Capability token (A-06) killswitch bilan bog'lanmagan — favqulodda to'xtatish qurilma tokenlarini bekor qilmaydi | 🟢 Past (qurilma boshqaruvi hali minimal) | Killswitch engage → `DeviceRegistry.revoke_all()` |

## 10. HETZNER RISKS

| ID | Xavf | Ta'sir |
|---|---|---|
| HR-01 | Killswitch/Approval/Run holatlari — `update.sh` orqali RUTIN konteyner qayta qurish har safar ularni yo'qotadi | 🔴 Yuqori — AR-01 bilan bir xil, lekin ishlab chiqarishda muntazam sodir bo'ladi |
| HR-02 | Backup/restore mexanizmi yo'q — Postgres volume yagona nusxa | 🔴 Yuqori — server yo'qolsa barcha CRM/xotira/buyurtma ma'lumoti yo'qoladi |
| HR-03 | Railway hali ham parallel ishlaydi (kod ichida branch'lar bor) — ikki muhit sinxronsiz o'sishi mumkin | 🟡 O'rta |
| HR-04 | Xususiy tarmoq yo'q — kelajakdagi Mac mini/qurilma tugunlari uchun xavfsiz kanal hali loyihalashtirilmagan | 🟢 Past (hozircha talab yo'q) |

## 11. INTEGRATION RISKS

- **CRM ↔ agentlar**: `PgCRM` real, lekin `Sales`/`Support` agentlarining `tool_allowlist`ida
  yo'q — bu ikkalasi ham CRM'ga to'g'ridan-to'g'ri kira olmaydi.
- **Obsidian ↔ Postgres xotira**: ikkalasi ham real, lekin bir-biridan butunlay mustaqil.
- **`HandoffDispatcher` ↔ production run oqimi**: qurilgan va testlangan, lekin hech qachon
  chaqirilmaydi — reaktiv agent-zanjiri ishlamaydi.
- **Model Router ↔ CostLedger.run_id**: `run_id` uzatilmagani uchun real trafik uchun
  per-run xarajat hisobi ishlamaydi (jamlanma bo'yicha to'g'ri, run darajasida yo'q).

## 12. TECHNICAL DEBT — "qurilgan, lekin ulanmagan" inventar

Bu ro'yxat alohida ahamiyatga ega: har biri **to'liq yozilgan va o'z birlik testida
yashil**, lekin **hech qanday production chaqiruvchisi yo'q**:

| Modul | Fayl | Nima qiladi | Nega ulanmagan |
|---|---|---|---|
| `RateLimiter` | `security/ratelimit.py` | Tier bo'yicha so'rov cheklash | ASGI middleware'ga qo'shilmagan |
| `SecretManager` | `security/secrets.py` | Sirlarni maskalash/rotatsiya | Config `SecretStr`lar to'g'ridan-to'g'ri ishlatiladi |
| `AuditLog` (xotira) | `security/audit.py` | Hash-chain audit yozuvi | Hech qayerdan chaqirilmaydi |
| `AuditLog` (DB) | `db/models/security.py` | Postgres trigger bilan immutable jadval | INSERT nuqtasi yo'q |
| `CostTracker` | `observability/cost.py` | Ikkinchi, mustaqil xarajat hisoblagichi | `CostLedger` allaqachon shu vazifani bajaradi — dublikat |
| `HandoffDispatcher` | `automation/handoff.py` | Reaktiv agent-zanjiri | Production run oqimiga ulanmagan (faqat testda) |
| `DeviceRegistry` | `devices/registry.py` | Qurilma ro'yxati + token | DB modeli yo'q, API route yo'q, hech qayerda instantiatsiya qilinmaydi |
| `CapabilityToken` | `devices/registry.py` | Scoped, TTL'li ruxsat | Hech bir tool tekshirmaydi |
| ~~`SelfImproveEngine`~~ | `deploy/selfimprove.py` | Taklif/tasdiq CRUD | ✅ ULANGAN — `SelfImproveDaemon` haftalik CostLedger/ToolCall signallari asosida `.suggest()` chaqiradi va notifier'ga xulosa yuboradi |
| `MemoryManager`/policy | `memory/manager.py`, `memory/policy.py` | Qatlam bo'yicha o'qish/yozish siyosati | Production `PgMemoryStore` yo'lidan chetlab o'tiladi |
| `RunState`/`RunLimits` | `domain/run.py` | Run chuqurligi/limitlari domeni | Hech qachon instantiatsiya qilinmaydi |
| `PyAutoGUIDesktop` | (yo'q) | — | Faqat docstringda nomlangan, klass yozilmagan |

**Tavsiya:** har bir modul uchun ikkita variant — (a) production yo'liga ulash, yoki
(b) modulni o'chirish va testini olib tashlash. Hozirgi holat — "yashil test, o'lik kod" —
false-confidence yaratadi.

## 13. DUPLICATED SYSTEMS

- `AuditLog` — ikki marta yozilgan (xotira + DB), ikkalasi ham ishlamaydi.
- Cost tracking — `CostLedger` (DB, real, ishlatiladi) vs `CostTracker` (xotira,
  ishlatilmaydi) — bittasi keraksiz.
- Run holati — `RunStore`/`RunRecord` (xotira, ishlatiladi) vs `Run`/`Step` DB modellari
  (ishlatilmaydi) — bular **raqobatchi emas, komplementar bo'lishi kerak edi**, lekin
  hozir ikkinchisi shunchaki o'lik.

## 14. RECOMMENDED ARCHITECTURE — nima o'zgarishi kerak

1. **Bitta "durable state" qoidasi.** Har qanday holat (Run, Approval, KillSwitch, Goal,
   Device) — DB'ga YOZILADI, xotira esa faqat so'rov-ichi keshi. Yangi state uchun bu
   qoidadan chetga chiqish PR review'da rad etilishi kerak.
2. **Trust-level oqimini ulash.** `ToolResult.trust_level` keyingi step kontekstiga
   uzatilishi va `PermissionPolicy.check()`ga REAL qiymat sifatida berilishi kerak —
   bu A-05'ning butun ma'nosi.
3. **Delivery-first daemon shabloni.** Har qanday avtonom fon vazifasi — natijani
   yetkazish bosqichisiz "done" hisoblanmaydi (`AutomationDaemon._deliver()` naqshini
   `DailyScheduleDaemon`ga ham qo'llash).
4. **O'lik kodni tozalash sprinti** — 12-bo'limdagi ro'yxatni ulash yoki o'chirish.

## 15. DEPENDENCIES — nima nimaga bog'liq

```
Run/Approval DB-persistence (AR-01)
    → Telegram approval tugmalari tuzatilishi (BROKEN #2)
    → Killswitch restart-durability (BROKEN #3)
    → Kunlik avtonomiya delivery (BROKEN #4, mustaqil — alohida qilish mumkin)

Trust-level oqimi (AR-02)
    → Prompt-injection skaneri ulanishi (SR-01)
    → Untrusted-input arxitekturasi to'liq yopilishi (A-05)

CRM tool sifatida ochilishi
    → Sales agent haqiqiy ishlashi

pgvector qo'shilishi
    → Xotira scale muammosi yechilishi (hozircha kichik ma'lumot hajmida muhim emas)
```

## 16. TEST PLAN

Mavjud **2,212 test** (backend) — saqlanadi, hech biri o'chirilmaydi. Qo'shilishi kerak:

- **Integratsiya testi**: CLI `z run` → approval → API `resume` — bitta jarayonda
  ishlaydimi tekshiruvchi test (hozir yo'q, aynan shu yo'q joy BROKEN #1'ni yashirgan).
- **Telegram callback → real resume** — hozirgi testlar faqat javob matnini tekshiradi,
  `ApprovalService.approve()` chaqirilganini emas.
- **Killswitch restart-simulyatsiyasi** — `KillSwitchState()` yangi instansiya yaratib,
  oldingi holat yo'qolganini aniq ko'rsatuvchi test (regression himoyasi sifatida, tuzatish
  qilinmaguncha).
- **Frontend testlari** — hozir NOL. Kamida NEXUS va Dashboard uchun component/smoke test.
- **Audit log yozilishi** — kamida bitta integratsiya testi: tool chaqiruvi → `AuditLog`
  jadvalida qator paydo bo'lishi.

## 17. DEPLOYMENT PLAN

1. Hetzner skriptlari (`setup.sh`/`update.sh`) — real va ishlatishga tayyor, o'zgarishsiz.
2. **Railway rasman o'chirilishi kerak** — hozir "ikkalasi ham jonli" holati chalkash va
   xavfli (ikki muhit divergensiyasi). Yoki: Railway'ni rasman "backup/staging" deb qayta
   belgilash, kodni tozalash.
3. Backup mexanizmi qo'shilmaguncha — production ma'lumoti (CRM, buyurtmalar, xotira)
   yagona nusxa xavfida qoladi. Bu keyingi implementatsiya bosqichida P0 bo'lishi kerak.

## 18. TOP PRIORITIES — keyingi implementatsiya uchun tavsiya etilgan tartib

**P0 — Ishonchni tiklovchi tuzatishlar (kichik, yuqori ta'sir):**
1. `DailyScheduleDaemon`ga delivery qo'shish (BROKEN #4) — bitta funksiya chaqiruvi, katta
   foyda.
2. Telegram approval tugmalarini haqiqiy `resume()`ga ulash (BROKEN #2).
3. Postgres backup (`pg_dump` + restic yoki oddiy kunlik cron) — operatsion xavfsizlik.

**P1 — Arxitekturaviy qarz (o'rta hajm, yuqori ta'sir):**
4. Run/Approval/KillSwitch uchun DB-persistence (AR-01) — bu bitta ish, chunki naqsh bir
   xil uchtasiga ham.
5. Trust-level dinamik oqimi + injection-skaner ulanishi (AR-02, SR-01).
6. Audit log INSERT nuqtalarini qo'shish (SR-02).

**P2 — Foydalanish qiymatini oshiruvchi (o'rta hajm):**
7. CRM'ni Sales agent tool sifatida ochish.
8. RateLimiter'ni middleware sifatida ulash.
9. O'lik kod tozalash sprinti (12-bo'lim).

**P3 — Kengaytirish (katta hajm, yangi imkoniyat):**
10. HR agent → AI workforce manager (yangi so'rov markazi).
11. pgvector + reranking (xotira scale).
12. Telefon/kompyuter boshqaruvi — companion app, real desktop provider.
13. PWA/companion rejim, frontend testlari.
14. Xususiy tarmoq (WireGuard) — Mac mini kelganda.

---

## 19. Audit metodologiyasi (izchillik uchun)

9 ta parallel agent quyidagi sohalarni tekshirdi: (1) Core+Model Router, (2) Xotira+Obsidian,
(3) Tool Registry+Agent Runtime+Factory+HR, (4) Telegram+Voice+Biznes agentlar+Commerce,
(5) Developer/GitHub+Web+Untrusted-input, (6) Qurilmalar (kamera/telefon/kompyuter),
(7) Automation Engine+kunlik avtonomiya, (8) Frontend UI, (9) Xavfsizlik+Monitoring+Hetzner.
Har biri kodni to'g'ridan-to'g'ri o'qib, fayl:qator citata bilan tasdiqladi — docstring yoki
nomlarga ishonmadi. To'liq xom natijalar sessiya tarixida saqlangan.
