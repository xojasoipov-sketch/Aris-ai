# JB-16 — REAL JARVIS PRODUCTION BEHAVIOR AUDIT & REPAIR — Yakuniy hisobot

Sana: 2026-08-18
Ko'lam: `apps/core/src/zet` (ZET Brain/Mission/Tool pipeline)

Bu hisobot spec'ning o'zi talab qilgan tartibda yozilgan: audit → real
nosozliklarni qayta hosil qilish → arxitektura ildiz sababi → FAQAT ildiz
sababni tuzatish → tekshiruv → regressiya → halol hisobot. **"TRUE JARVIS
BRAIN COMPLETE" bu yerda da'vo QILINMAYDI** — quyida aniq nima
IMPLEMENTED, nima PARTIAL va nima hali NOT IMPLEMENTED ekani ochiq
yozilgan.

---

## 1. Audit (READ-ONLY, kod o'zgartirilmasdan)

3 ta parallel read-only audit (ikkitasi subagent orqali, bittasi — CASE
B — bevosita men tomonimdan) quyidagilarni tasdiqladi:

- **Real Telegram trafigi Brain orqali o'tadi**: `zet/api/deps.py`dagi
  `_runner` closure `Brain.handle()`ni chaqiradi; `telegram/handlers.py`
  production'da `HandlerContext(orchestrator_runner=_runner, ...)` bilan
  ulanadi.
- **Mavjud Telegram unit testlari HAQIQIY Brain'ni sinamaydi**:
  `tests/test_telegram.py` `orchestrator_runner=None` bilan qoladi
  (dataclass default) — bu hardcoded echo-stub tarmog'ini ("Core
  pipeline ulangan emas") ishga tushiradi, `Brain`/`IntentRecognizer`/
  `Orchestrator`/`Planner` UMUMAN chaqirilmaydi. **Bu — bugungacha
  mavjud, tuzatilmagan test-qamrov bo'shlig'i (pastga qarang, §7).**
- **`telegram.channel_stats` (READ) va `telegram.channel_post` (WRITE)
  IKKALASI HAM to'liq `ToolRegistry` orqali Planner'ga har doim
  ko'rinadi** — mission-darajasidagi `CapabilityRegistryComposer`
  keyword-preflight scoping FAQAT `goal`-klassifikatsiya qilingan
  ko'p bosqichli missiyalarga tegishli; bitta aniq-qamrovli so'rov
  ("kanal postini ol") `command` sifatida to'g'ridan-to'g'ri
  `Orchestrator._plan_and_run()` → `Planner.plan(tool_specs=full
  registry)` yo'liga tushadi (`core/orchestrator.py:568-570`).
- **Ikkita alohida, ATAYLAB ortiqcha (redundant) approval darvozasi
  mavjud**: (a) Mission-darajasidagi PLANNING-bosqich preflight
  (`CapabilityBundle.risk_level` — capability'ning o'zi e'lon qilgan
  `risk_level`ining MAX'i), va (b) har-tool bajarish-vaqtidagi
  fail-closed tekshiruv (`AgentRuntime._execute_tool()` →
  `PermissionPolicy.requires_approval()` → `risk_for(tool_name)`
  markazlashtirilgan jadvaldan). Bu ikkalasi `task_graph.py:1108-1110`da
  ATAYLAB izohlangan — V-32 baribir fail-closed ta'minlanadi.
- **Capability discovery ("nima qila olasiz") HECH QAYERDA mavjud
  emas edi** — na Brain, na Mission, na alohida tool darajasida.
  `/agents` Telegram buyrug'i ham hardcoded stub ("Bo'lim 7 da
  ulanadi").

---

## 2. CASE B — "Kanalning oxirgi 10 ta postini olish" noto'g'ri HIGH-risk approval

### 2.1 Qayta hosil qilish (haqiqiy komponentlar bilan)

`tests/test_jb16_telegram_case_a_case_b.py` — haqiqiy `Planner` +
`FakeProvider` (LLM'ga chiqmasdan, lekin `Planner.plan()`ning HAQIQIY
kodi ishlaydi) + haqiqiy `build_default_registry()` bilan:
- Ikkala Telegram tool ham (`channel_stats`, `channel_post`) HAR DOIM
  bir vaqtda LLM'ga yuboriladigan `tool_specs`da ko'rinadi — bu
  reachability muammosi EMAS.
- Haqiqiy `PermissionPolicy.requires_approval()` + `risk_for()` bilan
  tasdiqlangan: `telegram.channel_post` HAR DOIM tasdiq talab qiladi
  (HIGH), `telegram.channel_stats` HECH QACHON (LOW, READ).

### 2.2 Arxitektura ildiz sababi

**Tool ≠ Action konfliqti emas** (bu boshlang'ich gipoteza edi) —
haqiqiy sabab: **ikkala tool NOM jihatidan bir-biriga juda o'xshash
("channel_post" — "kanal posti"), va ularning `description` maydoni
(Planner LLM ko'radigan YAGONA semantik signal) bu farqni yetarlicha
KUCHLI ajratmagan edi.** Bot API'ning haqiqiy, hujjatlashtirilgan
cheklovi (kanal xabar TARIXINI o'qish uchun UMUMAN metod yo'q — faqat
`getUpdates`/webhook orqali YANGI xabarlar) buni yanada yomonlashtiradi:
hech qanday tool "oxirgi N ta post"ni haqiqatan bajara olmaydi, shuning
uchun LLM eng "nom jihatidan yaqin" tool'ga (`channel_post`) tortiladi.

**Capability-registry darajasida** (`core/capability.py`dagi `telegram`
Capability) alohida, kichikroq muammo ham tasdiqlandi: `default_tools`
FAQAT `telegram.channel_post`ni o'z ichiga oladi — bu Mission/`goal`
yo'liga tegishli (bitta aniq-qamrovli so'rov uchun emas). Bu ATAYLAB
TUZATILMADI (pastga, §2.4).

### 2.3 Tuzatish (root cause, keyword patch EMAS)

1. **`telegram_tools.py`**: ikkala tool tavsifi ("O'QISH"/"YOZISH" so'zi
   bilan) va Bot API'ning haqiqiy cheklovi ANIQ, halol e'lon qilindi
   (modul docstring + har bir tool `description`).
2. **`prompts/planner.py`**: Planner tizim promptiga IKKI UMUMIY (faqat
   Telegram'ga xos EMAS, har qanday tool juftligiga tegishli) qoida
   qo'shildi: (a) tool NOMI so'rov so'ziga o'xshashligi mos kelish
   DEGANI EMAS — tavsifni o'qi; (b) hech qanday tool haqiqatan mos
   kelmasa, tool tanlama, halol tushuntir.
3. **Xavfsizlik ZAIFLASHTIRILMADI**: `telegram.channel_post`ning
   `risk_level`/`TOOL_RISK_LEVELS` yozuvi HECH QAYERDA o'zgartirilmadi
   — `tests/test_jb16_telegram_case_a_case_b.py::TestCaseBRiskSeparationNotWeakened`
   buni haqiqiy `PermissionPolicy` bilan tasdiqlaydi.

### 2.4 Ochiq qoldirilgan, HALOL e'lon qilingan qism

- **"Kanalning oxirgi N ta postini olish" o'zi — Bot API orqali UMUMAN
  bajarib bo'lmaydi** (MTProto client kerak, bu kodbaza ATAYLAB
  ishlatmaydi). Bu KOD BILAN "tuzatilmagan" — chunki bu haqiqiy,
  o'zgarmas platform cheklovi. Tuzatilgan narsa — LLM endi bu holatda
  noto'g'ri `channel_post`ni TANLAMASLIGI kerak (yangi qoida §2.3.2) va
  buning o'rniga halol "bu imkonsiz" javobini berishi kerak (§2.3.2,
  qoida 2a). **Bu LLM xatti-harakati — deterministik unit test bilan
  100% kafolatlab bo'lmaydi** (real LLM chaqiruvi kerak), shuning uchun
  status: **PARTIAL** — prompt/tool-tavsif darajasida tuzatilgan,
  production LLM'ning haqiqiy javobi orqali TASDIQLANMAGAN (spec §18
  "6-qadamli Telegram stsenariysi" — quyida §6ga qarang).
- `telegram` Capability'ning `default_tools`iga `channel_stats`
  qo'shilmadi — mission-darajasidagi bundle bir tool = bir task
  semantikasi (`_bundle_to_tasks()`) buni qo'shsa, PURE READ missiya
  HAM `channel_post` task'ini majburan qo'shib qo'yardi (yomonroq
  natija). Bu ATAYLAB, sabab bilan qilingan tanlov — pastga §8ga qarang.

---

## 3. CASE A — `'str' object has no attribute 'get'`

### 3.1 Topilgan, TASDIQLANGAN, TUZATILGAN aniq bug

Butun `zet` paketida shu XATO MATNI'ni haqiqatan hosil qiladigan
YAGONA, aniq qayta-hosil-qilinadigan joy: `tools/builtin/vision_ocr.py`
va `tools/builtin/video_learn.py`dagi mustaqil-nusxalangan
`_extract_json()` funksiyalari LLM javobi top-darajada `dict` emasligini
(masalan LLM bitta JSON satr — `"rasmda matn topilmadi"` — qaytarsa)
TEKSHIRMAS EDI. `core/recovery.py`dagi UCHINCHI nusxa esa bu
tekshiruvni QILARDI — ya'ni bir xil naqsh 3 marta nusxalanib, faqat
BITTASI to'g'ri edi.

### 3.2 Ildiz sabab (tur-shartnoma nomuvofiqligi)

`Tool._execute()` → `Any` qaytaradi (`tools/base.py:139`);
`ToolResult.output: Any` (`domain/tool.py:29`) — hech qanday narsa
buni majburlamaydi. Asosiy pipeline (`agents/runtime.py`,
`core/evidence.py`, `core/task_graph.py`) buni intizomli
`isinstance()` bilan qo'riqlaydi, LEKIN har bir modul o'z tekshiruvini
QAYTA yozadi (yagona manba yo'q edi) — aynan shu naqsh
`vision_ocr.py`/`video_learn.py`da bir marta unutildi.

### 3.3 Tuzatish (ildiz, isinstance-patch EMAS)

Yangi `zet/tools/json_extract.py::extract_json_object()` — BUTUN paket
uchun YAGONA vakolatli JSON-dan-dict-ajratish funksiyasi (dict
bo'lmasa `None`, hech qachon xato natijani jimgina dict sifatida
ko'rsatmaydi). `core/recovery.py`, `tools/builtin/vision_ocr.py`,
`tools/builtin/video_learn.py` — barchasi ENDI shu bitta funksiyani
import qiladi; 2 ta eski, nomukammal nusxa OLIB TASHLANDI (qayta
yozilmadi, o'chirildi).

### 3.4 Ochiq qoldirilgan, HALOL e'lon qilingan qism

- **Bu aniq mexanizm (`vision.ocr`/`video.learn`) matn-only "kanal
  tool'lari" so'rovidan TABIIY ravishda ishga tushmaydi** (ular
  `image_url`/`image_bytes_base64`/YouTube URL talab qiladi). Chuqur
  audit (3-agent, 67 tool-chaqiruv, to'liq `.get(` qidiruvi butun
  `zet/core`, `zet/agents`, `zet/tools/builtin` bo'ylab) shuni topdiki:
  bu — paket ichidagi ULARNI ISBOTLAB BO'LADIGAN YAGONA `'str' object
  has no attribute 'get'` manbai, lekin bu **aniq production
  hodisasining o'zi bilan 100% bog'liqligi ISBOTLANMAGAN** — chunki
  real ishlab chiqarish log'i/stack trace mavjud emas edi (faqat xato
  MATNI xabar qilindi). Status: **PARTIAL** — sinf sifatida topilgan va
  tuzatilgan aniq bug bor va real, lekin "aynan shu incident'ning aynan
  shu sababi" darajasida 100% tasdiqlanmagan; bu holat hisobotda
  YASHIRILMAYDI.

---

## 4. Capability discovery — "nima qila olasiz?"

**IMPLEMENTED** (yangi tool, arxitekturani rewrite qilmasdan):
`zet/tools/builtin/capability_discovery.py::CapabilityDiscoveryTool`
(`system.capabilities`, READ, LOW risk) — HAQIQIY `ToolRegistry`dan
(`list_tools()`) har bir tool holatini o'qiydi:

- `available` — `is_real=True` (yoki lokal, doim mavjud)
- `not_available` — stub (kalit/token yo'q)
- `requires_permission` — READ'dan yuqori
- `requires_approval` — haqiqiy `PermissionPolicy.requires_approval()`

`topic` ixtiyoriy parametri — bitta so'z bilan pastki-satr filtri
(YANGI kalit so'zlar ro'yxati EMAS — `CapabilityRegistry.search()`dagi
bilan bir xil oddiy mexanizm). Planner tizim promptiga ("ZET NIMA QILA
OLISHI HAQIDAGI SAVOLLAR") yangi bo'lim qo'shildi — bu tool'ni qachon
ishlatish semantik ravishda ko'rsatilgan.

9 ta test (`tests/test_capability_discovery.py`) — HAQIQIY
`build_default_registry()` bilan: stub/real ajratish, approval-belgisi
to'g'riligi, topic-filtr, crash-siz noma'lum mavzu, tool o'zini o'zi
ko'rishi (self-registration).

**Cheklov (halol e'lon qilinadi)**: bu tool `ToolRegistry`ni ko'radi,
lekin `CapabilityRegistry`ni (outcome/capability darajasidagi
tavsiflarni) EMAS — "nima qila olasiz" javobi tool-darajasida, biznes
capability-darajasida emas. `/agents` Telegram buyrug'ining hardcoded
stub holati ("Bo'lim 7 da ulanadi") — **NOT IMPLEMENTED**, bu JB-16
ko'lamidan tashqarida qoldirildi (alohida, kichikroq wiring vazifasi).

---

## 5. Boshqa spec bo'limlari — holat jadvali

| # | Talab | Holat |
|---|---|---|
| Audit (READ-ONLY, kod o'zgarishisiz) | §1 | **IMPLEMENTED** |
| CASE A/B haqiqiy komponentlar bilan qayta hosil qilish | §2.1, §3 | **IMPLEMENTED** (statik/deterministik daraja; real Telegram production orqali emas — pastga qarang) |
| Arxitektura ildiz sababi (Tool≠Action emas, real sabab topilgan) | §2.2, §3.2 | **IMPLEMENTED** |
| Faqat ildiz sababni tuzatish (keyword-patch/isinstance-patch emas) | §2.3, §3.3 | **IMPLEMENTED** |
| `telegram.channel_post` xavfsizligi zaiflashtirilmadi | §2.3.3 | **IMPLEMENTED** (testda tasdiqlangan) |
| Capability discovery — real registry, crash-siz | §4 | **IMPLEMENTED** (tool-darajasida) |
| 6-qadamli haqiqiy Telegram production stsenariysi (real LLM, real Brain, real Telegram) | spec §18 | **NOT IMPLEMENTED** — bu muhitda haqiqiy Telegram bot token/real LLM API kaliti va real xabar almashinuvi mavjud emas (avvalgi Navoiy-TTS ishida ham xuddi shunday cheklov ochiq e'lon qilingan edi). O'rniga: deterministik, real-komponentli (FakeProvider + real Planner/PermissionPolicy/ToolRegistry) reproduksiya testlari yozildi (§2.1) — bu HAQIQIY LLM qaroriga TENG EMAS. |
| Kontekst uzluksizligi (ko'p burilishli suhbat) | spec §11 | **NOT IMPLEMENTED** — JB-16 ko'lamida qo'l tegizilmadi (mavjud JB-3 World State mexanizmi allaqachon bor, lekin bu spec talab qilgan aniq 5-bosqichli kanal→o'qish→tahlil→yaratish→nashr zanjiri sinovdan o'tkazilmadi). |
| BrainResult javob sifati / verification / failure recovery — Telegram stsenariylari uchun maxsus audit | spec §15-17 | **NOT IMPLEMENTED** — mavjud JB-14/JB-15 mexanizmlari (umumiy) ishlaydi, lekin Telegram-maxsus chuqur audit/repair bu turda qilinmadi. |
| Observability (request_id/intent/action/tool/risk/approval/... trace maydonlari) | spec §20 | **NOT IMPLEMENTED** — mavjud `structlog` orqali tool-ro'yxat/permission-qaror log'lari bor (yuqoridagi test natijalarida ko'rinadi), lekin spec talab qilgan TO'LIQ, bitta joyga birlashtirilgan trace-maydon to'plami yangi qo'shilmadi. |
| JB-1...JB-15 kafolatlari saqlanishi | — | **IMPLEMENTED** — to'liq regressiya (pastga §6) hech qanday mavjud testni buzmadi; hech qanday ikkinchi Brain/ToolRegistry/PermissionSystem yaratilmadi. |

---

## 6. Regressiya va sifat

- **To'liq `pytest`** (butun `apps/core/tests/`) — **0 XATO, exit
  code 0** (2 marta ishga tushirildi: 1-safar `test_agent_factory.py`da
  YANGI, kutilmagan regressiya topildi — `system.capabilities` tool
  `TOOL_PERMISSIONS` jadvalida yo'q edi — DARHOL tuzatildi
  (`agents/eval.py`), 2-safar to'liq to'plam yashil).
- **`ruff check src tests`** — yangi/o'zgartirilgan fayllarda 0 xato
  (repo'dagi boshqa, JB-16'ga aloqasiz eski `test_run_checkpoint.py`
  xatolari o'zgartirilmadi/tegilmadi).
- **`mypy src/zet`** — 44 xato (BAZAVIY bilan BIR XIL son, `git
  stash` orqali tasdiqlandi) — yangi/o'zgartirilgan fayllarda 0 YANGI
  xato.
- **Yangi testlar (real komponentlar bilan)**: 7 (CASE A/B
  reproduksiya) + 9 (capability discovery) + 21 (json_extract) + 16
  (vision_ocr yangilash) + 14 (video_learn — YANGI, ilgari BUTUNLAY
  test qamrovisiz edi) = **67+ yangi test**, hech biri tool/Planner/
  PermissionPolicy/ToolRegistry KABI sinaladigan komponentni mock
  qilmaydi.

---

## 7. Bajarilmagan / ochiq e'lon qilingan qismlar (yashirilmagan)

1. **Real Telegram bot + real LLM orqali 6-qadamli acceptance
   stsenariysi ishga tushirilmadi** — bu muhitda real Telegram
   bot token va real (pullik) LLM API kaliti yo'q. Buning o'rniga
   deterministik, real-kod-yo'lli (lekin scripted LLM javobli)
   reproduksiya testlari yozildi.
2. **`tests/test_telegram.py`ning `orchestrator_runner=None` echo-stub
   muammosi TUZATILMADI** — bu ilgaridan mavjud, mustaqil arxitektura
   bo'shlig'i (mavjud Telegram unit testlari haqiqiy Brain'ni
   sinamaydi); JB-16'ning aniq ko'lami (CASE A/B) uchun bu bo'shliqni
   yopish shart emas edi, lekin bu HALI OCHIQ qoladi.
3. **Kontekst uzluksizligi, observability trace-maydonlari, capability-
   darajasidagi (Business capability, tool emas) discovery** — NOT
   IMPLEMENTED (yuqoridagi jadvalga qarang).
4. **CASE A'ning aynan production incident bilan bog'liqligi 100%
   isbotlanmagan** — eng kuchli, real, tuzatilgan nomzod topildi va
   tuzatildi, lekin aniq stack trace yo'qligi sababli mutlaq
   tasdiqlash mumkin emas edi.

**Xulosa**: JB-16 spec'ning yadrosi — arxitektura darajasidagi ildiz
sabab tahlili, keyword-patch/isinstance-patch bo'lmagan tuzatish, va
xavfsizlikni zaiflashtirmaslik — **bajarilgan va real testlar bilan
tasdiqlangan**. Lekin bu **"TRUE JARVIS BRAIN COMPLETE" DEGANI EMAS** —
real Telegram/LLM orqali end-to-end stsenariy, kontekst uzluksizligi va
observability kabi bir qancha bo'lim ATAYLAB, OCHIQ ravishda NOT
IMPLEMENTED holida qoldirildi.
