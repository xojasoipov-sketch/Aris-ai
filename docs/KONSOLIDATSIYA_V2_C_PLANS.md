# BO'LIM C — Yangi xususiyatlar: PLAN (kod YO'Q)

**Holat:** faqat tekshiruv + reja. Ushbu hujjatdagi hech bir bo'lim
implementatsiya qilinmagan — foydalanuvchi "PLAN ONLY, DO NOT IMPLEMENT"
deb aniq belgilagan (KONSOLIDATSIYA v2, BO'LIM C).

**Metodologiya:** har bir reja mavjud kod bazasini (`apps/core/src/zet/`)
haqiqiy grep/read orqali tekshirib chiqilgan — taxmin emas. Har joyda aniq
fayl:qator ko'rsatilgan. Noaniq qolgan joylar "Ochiq savollar"da alohida
ro'yxatlangan, ular ega qaroriga qoldirilgan.

---

## C1 — Ingestion Router

**Maqsad:** ega istalgan formatda (matn/fayl/skrinshot/ovoz transkripti)
material yuborganda, tizim avtomatik qaysi biznesga tegishli ekanini
aniqlaydi, faktlarni ajratadi va to'g'ri Obsidian joyiga yozadi.

### Business Registry (C2'ga bog'liq — protokol orqali izolyatsiya)

`grep -rn "class.*Business"` — repo bo'ylab HECH QANDAY Business Registry
kodi yo'q (na jadval, na config ro'yxat). C1 buni **Protocol** orqali
iste'mol qiladi — `core/mission.py:128-186`dagi
`CapabilityRegistryLike`/`MemoryStoreLike` naqshini takrorlab:

```python
class BusinessRegistryLike(Protocol):
    def list_businesses(self) -> Sequence[BusinessProfile]: ...
```

Bu C1 ishlab chiqilishini C2 haqiqiy DB implementatsiyasi tayyor
bo'lishini kutmasdan boshlash imkonini beradi (test double bilan).

### Klassifikator — confidence/ask-don't-guess

`core/intent.py`dagi `IntentRecognizer` arxitekturasi to'liq takrorlanadi
(tool_use + Pydantic validatsiya): yangi `BusinessMatch` modeli —

```python
business_id: str | None
confidence: float           # 0..1
ambiguity: Literal["low","medium","high"]   # Intent bilan bir xil 3-daraja
candidates: list[tuple[business_id, score]]  # YANGI — "qaysi biznes" ko'p tanlovli
clarification_question: str | None
```

**Ask-don't-guess qoidasi** — `intent.py:115-119`dagi AYNAN shu shart
takrorlanadi: `ambiguity == "high" and clarification_question` bo'lsa
`AmbiguousBusinessError` (AmbiguousCommandError'ning to'g'ridan-to'g'ri
egizagi) ko'tariladi — Telegram'da nomzod ro'yxati inline keyboard bilan
ko'rsatiladi (raqamli chegara emas, ambiguity-bucket asosida, chunki
tizimda yagona shu naqsh bor).

### Extractor sxemasi

Yangi maydon to'plami emas — **ZET_ASS_MASTER.md PART 4'ning mavjud
"Project Profile" sxemasi** ishlatiladi (project_name, description,
purpose, owner, business, products, services, contact_information,
va h.k.). Yangi Pydantic model `ExtractedFact`:

```python
business_id: str
fields: dict[str, Any]       # Project Profile'ning ishonchli to'ldirilgan qismi
freeform_notes: str          # mos kelmagan hech narsa YO'QOTILMAYDI
source_hash: str             # dedup kaliti (sha256)
extraction_method: Literal["text","stt+llm","ocr+llm","document+llm"]
source_trust_level: TrustLevel   # OCR → UNTRUSTED (A-05), matn → SYSTEM
```

### Duplicate prevention — 2 bosqich

1. **Aniq dublikat:** `sha256(normalized_text)` — `context.py:581,1396`da
   ALLAQACHON ishlatiladigan primitiv (yangi emas).
2. **Semantik yaqin-dublikat:** `PgMemoryStore.search()`
   (`memory/pg_store.py:204-258`) `MemoryLayer.BUSINESS` bo'yicha —
   `note.write`ning mavjud "shadow" mexanizmi (`note_write.py:60-76`)
   bu indeksni BEPUL to'ldiradi, faqat YANGI o'qish (search-before-write)
   kerak. Yaqin-dublikat topilsa: **APPEND yoki so'rash — HECH QACHON
   jimgina qayta yozib yuborish emas** (Master Spec Part 4 qoidasi,
   ContextEngine'ning konflikt-hal qilish falsafasi bilan bir xil).

### Audit log formati

Yangi ustun kerak emas — `AuditLog.detail` allaqachon erkin JSON
(`db/models/security.py:64-79`). Yangi `action` qiymatlari:

```
ingestion.received | ingestion.classified | ingestion.ambiguous_asked
ingestion.classified_by_owner | ingestion.extracted
ingestion.duplicate_skipped | ingestion.written
```

`target` = business_id yoki note yo'li; `permission_level` = WRITE (xuddi
`note.write` kabi); `detail` = {source_type, confidence, candidates,
note_path, source_hash, similarity_score}.

### Nimaga bog'liq (mavjud, o'zgarmaydi)

- `tools/builtin/note_write.py` — vault yozuvi, path-safety, shadow bridge
- `memory/pg_store.py::PgMemoryStore.search()` — semantik dedup
- `core/context.py::ContextEngine` — "avval qidir, keyin so'ra" grounding
- `core/intent.py` — klassifikator arxitekturasi shabloni
- `core/mission.py:306-375` — risk-based approval zanjiri (ingestion
  yozuvi HAM shu orqali o'tadi — yangi approval tizimi YO'Q)
- `security/risk.py` — `note.write` allaqachon MEDIUM (qo'shimcha
  klassifikatsiya kerak emas)
- `voice/stt.py`, `tools/builtin/vision_ocr.py` — voice/screenshot kirish

### Nima haqiqatan yangi

- `IngestionClassifier` (yangi modul, `core/ingestion.py`)
- `AmbiguousBusinessError`, `BusinessMatch`, `ExtractedFact` (yangi domen)
- `extract_facts` tool_use ToolSpec
- `document.extract` tool — HECH QANDAY generic fayl/PDF/docx extractor
  hozir yo'q (faqat vision.ocr rasm uchun, STT ovoz uchun bor)
- Telegram nomzod-tanlash inline keyboard + callback resume
- `telegram/handlers.py:493-517`dagi `_handle_photo`/`_handle_document`
  hozir literal stub ("⏳ Bo'lim 8 da ulanadi") — shu pipeline'ga ulanishi

### Bosqichma-bosqich qurilish tartibi (eng kichigidan)

0. `BusinessRegistryLike` Protocol + xotiradagi fixture double
1. Faqat kalit-so'z/alias klassifikatsiya (LLM'siz, deterministik)
2. LLM-based klassifikatsiya (noaniq holatlar uchun) + `AmbiguousBusinessError`
3. Audit logging ulanishi
4. Extraction qadami (`extract_facts`)
5. Dedup Tier-1 (aniq hash)
6. Dedup Tier-2 (semantik)
7. `note.write` orqali yozish (mavjud tool, o'zgarishsiz)
8. Approval gating end-to-end isbot (unapproved → fayl yo'q; approved → bor)
9. Ovozli kirish ulanishi (STT — mavjud)
10. Rasm/skrinshot kirish ulanishi (vision.ocr — mavjud, trust=UNTRUSTED)
11. `document.extract` — yagona haqiqiy YANGI tashqi tool
12. Telegram noaniqlik UX (inline keyboard + resume)
13. `_handle_photo`/`_handle_document` stub'larini pipeline'ga ulash

**Baholash:** ~10-14 kichik PR/qadam, ko'pi yarim kun-1 kun (mavjud
komponentlarni composition qilish). Faqat 11-qadam (document.extract)
haqiqatan yangi tashqi integratsiya — `vision_ocr.py` hajmida.

### Ochiq savollar (ega hal qilishi kerak)

1. C2 (Business Registry) haqiqatan qurilishi kerakmi shu ish doirasida,
   yoki alohida boshqa branch/PR'da bor deb taxmin qilinsinmi?
2. Ingestion to'liq `MissionEngine` orqali o'tsinmi (Task Graph, to'liq
   audit/verify bilan) yoki yengilroq to'g'ridan-to'g'ri yo'l?
3. Dedup Tier-1 TTL oynasi (1 soat? 24 soat?) va Tier-2 semantik chegara
   (0.90? 0.95?) — raqamli qiymatlar ega tomonidan berilishi kerak.
4. Past OCR/STT ishonch darajasi o'zi `ambiguity=high`ni majburlashi
   kerakmi (garbled matn ishonchli-noto'g'ri natija berishi mumkin)?
5. Dedup indeksi: `audit_log` qatorlarini skanerlash yetarlimi, yoki
   alohida indekslangan jadval kerakmi?

---

## C2 — Business/Contacts Registry

**Qaror (repo tekshiruvi asosida):** odamlar uchun MAVJUD `crm_contact`
jadvali qayta ishlatiladi; bizneslar uchun YANGI, kichik `business`
jadvali qo'shiladi. **Obsidian PRIMARY manba sifatida ISHLATILMAYDI**
(sabab quyida) — faqat ixtiyoriy, DB'dan generatsiya qilinadigan ko'zgu.

### Nega Obsidian emas (foydalanuvchi taklifini rad etish sababi)

`db/models/crm.py:24-48`dagi `CRMContact` allaqachon `name` +
`telegram` (@username) + **`telegram_chat_id` (BigInteger, indekslangan)**
maydonlarini olib yuradi — bu aynan "ism → Telegram chat_id/username"
xaritasi, allaqachon mavjud va ishlatilyapti (shop bot avtomatik
to'ldiradi). Obsidian'da parallel odam-indeksi qurish ikkita manba
o'rtasida drift muammosi tug'diradi (Telegram DM kelganda qaysi biri
haqiqat manbai?). Repo'da allaqachon o'rnatilgan qoida: Postgres —
strukturaviy haqiqat manbai, Obsidian — inson uchun ko'zgu (`note_write.py`
"shadow" mexanizmi bilan bir xil falsafa). Ingestion Router — yuqori
chastotali, tez qidiruv talab qiladigan iste'molchi — markdown fayl
parsing bunga mos emas.

### Qayerda saqlanadi

- **Odamlar:** mavjud `crm_contact` (o'zgarishsiz).
- **Bizneslar:** YANGI `business` jadvali —
  `id, owner_id, name, aliases (JSON), vault_folder, telegram_channel_ids
  (JSON), keywords (JSON), is_active, notes` + `TimestampMixin`.
- **Bog'lanish:** `crm_contact.business_id` (nullable FK, `ON DELETE
  SET NULL` — `workspace.py`dagi `Task.project_id` bilan bir xil naqsh,
  biznes o'chirilsa kontakt yo'qolmasin).
- **Ixtiyoriy Obsidian ko'zgu:** DB'dan generatsiya qilinadigan,
  qo'lda tahrirlanMAYDIGAN har-biznes-uchun-bitta-note (`note.write`
  orqali) — faqat inson ko'rish uchun, hech qachon o'qilmaydi/query
  qilinmaydi.

### Qanday yangilanadi

- **Qo'lda:** DB to'g'ridan-to'g'ri (admin) yoki mavjud CRM API'lari.
- **Suhbat orqali:** yangi `business.create`/`business.contact_link`
  tool'lari — "yangi biznes qo'sh" kabi buyruq bilan (xuddi
  `crm.contact_create` bugun ishlagani kabi).

### Nimaga bog'liq / nima yangi

Bog'liq: `db/models/crm.py`, `business/pg_crm.py`, `tools/base.py` (Tool
ABC), `tools/builtin/crm_tools.py` (_CRMTool naqshi nusxa ko'chiriladi).
Yangi: `Business` model, migratsiya 0011, 3 ta tool
(`BusinessCreateTool`/`BusinessListTool`/`BusinessContactLinkTool`),
`risk.py`ga `business.create`/`business.contact_link` → MEDIUM.

### Bosqichma-bosqich

1. `Business` model + `crm_contact.business_id` FK → migratsiya 0011
2. `PgCRM`ga `add_business`/`find_business`/`list_businesses`/`link_contact_to_business`
3. 3 ta yangi Tool (`crm_tools.py` naqshi)
4. Registratsiya (`tools/builtin/__init__.py`)
5. Risk darajasi (`security/risk.py` — MEDIUM)
6. (Ixtiyoriy, keyinroq) Obsidian ko'zgu generator
7. Ingestion Router (C1) uchun qidiruv tartibini hujjatlashtirish:
   avval `crm_contact.telegram_chat_id` (aniq), keyin
   `business.keywords` (fallback)

**Baholash:** kichik-o'rta, 1 kun atrofida (crm_tools.py hajmidagi ish).

### Ochiq savollar

- `telegram_channel_ids` — JSON ro'yxatmi yoki alohida indekslangan
  jadval (agar kanal hajmi katta bo'lsa)?
- Alias qidiruv — oddiy substring (CRM qidiruvi bugun ham shunday) yoki
  embedding-based?

---

## C3 — Persona/Voice Profile

**Qaror:** ega qo'lda yozgan uslub tavsifi (namunalardan "o'rganish"
EMAS) — chunki bu ALLAQACHON tugallangan "Ega profilini xotiraga
yuklash" (V-13, `scripts/ingest_profile.py`) ishining bevosita
kengaytmasi, yangi infratuzilma talab qilmaydi.

### Qanday tuziladi

Bitta `MemoryEntry` yozuvi: `layer=PERSONAL`, `tags=["voice-profile"]`
(mavjud "boss-profile" tegidan farqli, deterministik qidirish uchun),
`source="voice-profile"`, `content=erkin matn uslub tavsifi`,
`trust_level="owner"`.

### Qayerda saqlanadi

`PgMemoryStore` / `MemoryLayer.PERSONAL` (`domain/memory.py`) — Settings
(env-var, redeploy talab qiladi) EMAS, Obsidian (keyword-match,
kafolatlanmagan) HAM EMAS. Xotira qatlami — yagona variant, ham
ega-tahrirlanadigan, ham deterministik tag-based olinadigan.

### Qanday qo'llaniladi

Yangi `get_voice_profile()` — `MemoryQuery(layers=[PERSONAL],
tags=["voice-profile"], min_similarity=0.0)` — **mavjud
`RECALL_MIN_SIMILARITY=0.35` chegarasidan CHETLAB o'tadi** (bu chegara
aynan profil matni HAR so'rovga yopishmasin deb qo'yilgan — bu yerda esa
teskarisi kerak: persona SHART, har outbound xabarga). Har chaqiruv
joyiga (`_shop_answer_fn`, `reports_daemon.py::_suggest_growth`) olingan
matn hardcoded `system` promptining boshiga qo'shiladi.

### Nimaga bog'liq / nima yangi

Bog'liq: `memory/pg_store.py`, `domain/memory.py::MemoryLayer.PERSONAL`,
`api/deps.py::_build_recall`/`_shop_answer_fn`, `scripts/ingest_profile.py`
naqshi. Yangi: `get_voice_profile()` helper (~10 qator), 2 ta chaqiruv
joyiga integratsiya.

### Bosqichma-bosqich

1. (kod yo'q) Ega qo'lda uslub tavsifi yozadi
2. Mavjud `POST /api/v1/memory` orqali bitta yozuv kiritiladi
3. `get_voice_profile()` implementatsiyasi + unit test
4. `_shop_answer_fn`ga ulash (eng kichik blast radius)
5. Qo'lda tekshirish — yozib, o'chirib solishtirib ko'rish
6. `reports_daemon.py::_suggest_growth`ga kengaytirish
7. (keyinroq) tahrirlash qulayligi — PATCH endpoint
8. (keyinroq, kattaroq) "namunalardan o'rganish" muallif rejimi — FAQAT
   matn qanday yozilishini o'zgartiradi, saqlash/qo'llash mexanizmi
   BIR XIL qoladi

**Baholash:** 1-4 qadam — yarim kun-1 kun. 5-qadam — soatlar. 7-8 — alohida.

### Ochiq savollar

- Bu shaxsning uslubi FAQAT tashqi (mijoz/hisobot) xabarlarga tegishlimi,
  yoki ega bilan ZetBot suhbatiga ham?
- Yozuvga uzunlik chegarasi qo'yilsinmi (har outbound promptga SHARTSIZ
  qo'shilgani uchun)?

---

## C4 — Semantik (embedding) qidiruv Obsidian vault ustida

**Qaror:** yangi embedding pipeline/vector store QURILMAYDI — mavjud
`PgMemoryStore` + `EmbeddingProvider` (Gemini/Mistral/Ollama, allaqachon
tugallangan #29-vazifa) note **kontentiga** kengaytiriladi.

### Qanday model/kutubxona

Hech narsa yangi — `memory/embeddings.py` (Ollama/Gemini/Mistral/Null),
`api/deps.py::get_embedding_provider()` (auto-tanlov: prod'da bulut,
dev'da Ollama) TO'LIQ QAYTA ISHLATILADI.

### Indeks yangilash strategiyasi

- `memory_entries` jadvali (`layer=KNOWLEDGE`, `tags=["note", ...]`)
  — HAR NOTE UCHUN BITTA QATOR, `source` bo'yicha **upsert** (hozir
  `_note_memory_shadow_fn` har `note.write` chaqiruvida yangi qator
  QO'SHADI — bu HAQIQIY BUG, mavjud kod bazasida topilgan: bir xil
  note'ni ikki marta tahrirlash ikkita mustaqil embedded qator qoldiradi).
- Kontent — to'liq (cheklangan, masalan 8-16KB), hozirgi 500-belgili
  preview EMAS (`note_write.py::_SHADOW_PREVIEW_CHARS`) — aynan shu
  cheklov haqiqiy semantik qidiruvni bugun IMKONSIZ qilyapti (embedding
  hisoblanadi, lekin faqat 500 belgidan).
- To'g'ridan-to'g'ri Obsidian'da (note.write'siz) tahrirlangan fayllar
  uchun — **mtime-based reconciliation** skani (`vault_dir` bo'ylab
  yurish, fayl vaqtini shadow qator bilan solishtirish, o'zgargan
  bo'lsa upsert). Live file watcher (watchdog) — MVP uchun KERAK EMAS,
  keyingi bosqichga qoldiriladi.

### Context Engine bilan integratsiya

`core/context.py::ContextEngine._query_obsidian` (738-787-qatorlar)
HOZIR `NoteListTool` orqali FAQAT kalit-so'z substring skani qiladi —
`PgMemoryStore`/embeddinglarga UMUMAN ULANMAGAN. Bundan tashqari, ikkita
production `ContextEngine(...)` qurilish joyi (`deps.py` ~971, ~1026)
`note_list`/`note_read` PARAMETRLARINI HECH QACHON UZATMAYDI — natijada
`_query_obsidian` BUGUN HAR DOIM BO'SH qaytadi (kod: `context.py:745-746`
guard). Reja: `_query_obsidian`ni `self._memory.search()` (ALLAQACHON
constructor parametri, `context.py:530/545`) chaqiradigan qilib qayta
yozish — bu ham "semantik qidiruv" ni qo'shadi, ham wiring bug'ini
YON TA'SIR sifatida tuzatadi.

### Nimaga bog'liq / nima yangi

Bog'liq (o'zgarishsiz): `memory/embeddings.py`, `memory/pg_store.py`,
`memory/scoring.py` (hybrid keyword+vector, fail-open), `deps.py`ning
provider tanlash mantiqi. Yangi: `PgMemoryStore.upsert_by_source()`,
`(owner_id, source)` indeksi, vault reconciliation moduli, `zet vault
reindex` CLI buyrug'i, `_query_obsidian`ning qayta yozilishi.

### Bosqichma-bosqich

1. Regression test: bugungi wiring bug'ini hujjatlashtiruvchi (0 ta
   OBSIDIAN fragment doim qaytishini isbotlaydi)
2. `PgMemoryStore.find_by_source()`
3. `PgMemoryStore.upsert_by_source()` (dublikat qator bug'ini yopadi)
4. Shadow bridge'ni upsert'ga o'tkazish + preview cap'ni oshirish
5. Vault reconciliation moduli (mtime asosida)
6. `zet vault reindex` CLI
7. `_query_obsidian`ni `self._memory.search()`ga qayta yozish
8. ContextEngine qurilish joylarini soddalashtirish/tuzatish
9. `_query_memory`/`_query_obsidian` orasidagi dublikat qoidasini qo'shish
10. End-to-end test: to'g'ridan-to'g'ri fayl tahriri → reconcile →
    semantik discover() ishlashi
11. (keyinroq, ixtiyoriy) live file watcher

**Baholash:** ~3-5 kun (testlar bilan), ~70% mavjud infratuzilmani
qayta ishlatish (task o'zi taxmin qilganidek).

### Ochiq savollar

- Kontent chegarasi (8-16KB) yetarlimi, yoki uzun note'lar bo'lish
  (chunking) kerakmi?
- `_query_memory` va `_query_obsidian` orasidagi dublikatni qanday
  hal qilish — chiqarib tashlashmi, `discover()`ning o'z konflikt
  mexanizmimi?
- Reconciliation nima trigger qiladi — cron, CLI, yoki lazy check?

---

## C5 — Monitoring Daemon

**Maqsad:** fon jarayoni Telegram/GitHub/boshqa manbalardan yangi
ma'lumotni davriy ravishda Obsidian'ga tortib kiritadi.

### Manbalar (MVP → kengaytma)

1. **GitHub** (birinchi, eng oson) — `tools/builtin/github.py`ning
   `github.read` tooli (`list_issues`/`get_pr`/`get_file`) QAYTA
   ISHLATILADI, `output_trust_level=UNTRUSTED` allaqachon to'g'ri (A-05).
2. **Telegram** (ikkinchi, MUROSASIZ ochiq savol) — `telegram/polling.py`
   ning `TelegramPoller`si FAQAT botga yo'naltirilgan yangilanishlarni
   ko'radi (`allowed_updates=["message","callback_query"]`) — **kanal
   tarixini o'qish imkoniyati HOZIR YO'Q**. Ikki variant, ega tanlashi
   kerak: (a) botni kanalga a'zo/admin qilib `channel_post`ni ham
   ushlash (kichik o'zgarish, lekin faqat qo'shilgan lahzadan keyin,
   backfill yo'q) yoki (b) userbot mijoz (Telethon/Pyrogram) — to'liq
   tarix, lekin repo'da hech qachon ishlatilmagan, YANGI va JIDDIY
   xavfsizlik chegarasi (ega akkaunti nomidan autentifikatsiya).

### Chastota

`AlertsDaemon`dagi `DEFAULT_TICK_SECONDS=60` naqshiga o'xshab, lekin
GitHub/Telegram daqiqama-daqiqa muhim emas — **5-15 daqiqa** taklif
qilinadi (API kvota va DB yukini past ushlash uchun).

### Resurs chegaralari

`core/orchestrator.py`dagi A-07 falsafasi (`run_timeout_s`,
`concurrency_semaphore`) — Orchestrator klassining o'zi EMAS, balki
FALSAFASI takrorlanadi: har manba tekshiruvi
`asyncio.wait_for(..., timeout=source_timeout_s)` bilan o'raladi (bitta
sekin GitHub chaqiruvi butun tick'ni ushlab qolmasin), har manba
alohida try/except (`AlertsDaemon` naqshi — bitta manba yiqilsa
qolganlari davom etadi).

### Yozish mexanizmi

**LLM YO'Q MVP bosqichida** — `ShipmentNotifyDaemon`ning "mexanik,
deterministik amal" falsafasi takrorlanadi (`DailyScheduleDaemon`/
`AutomationDaemon`ning AgentRuntime yo'li EMAS): GitHub issue-diff —
deterministik, model chaqiruvi kerak emas. Yozish — mavjud `note.write`
tool (path-safety, 100KB chegara, shadow bridge BEPUL keladi). Har
yozuv `Finding` (source-agnostik, kelajakda C1'ga to'g'ridan-to'g'ri
uzatish mumkin bo'ladigan) shaklda: `source_type, source_ref, title,
url, body_preview, discovered_at, trust=UNTRUSTED (har doim)`.

### Dedup/holat

MVP — xotiradagi `seen` to'plam (`DailyScheduleDaemon._last_fired`
naqshi, hujjatlashtirilgan cheklov bilan bir xil), lekin **bu yerda
DB-backed holatga ERTAROQ o'tish tavsiya etiladi** — chunki dublikat
bu yerda DOIMIY vault note (Daily Schedule'ning o'tkazib yuborilgan
bir martalik eslatmasidan farqli, restart'da qayta yozilaversa jamg'arib
boradi).

### Nimaga bog'liq / nima yangi

Bog'liq: `deploy/daemon.py`/`shipment_daemon.py`/`alerts_daemon.py`
(skelet naqshi), `tools/builtin/github.py`, `tools/builtin/note_write.py`,
`api/app.py:168-245` (lifespan DI-wiring naqshi), `config.py` (Settings
kengaytmasi).
Yangi: `deploy/monitoring_daemon.py`, `Settings.monitoring_github_repos`/
`monitoring_tick_seconds`/`monitoring_enabled`, `monitoring_seen`
jadvali (yoki xotiradagi MVP), `tests/test_monitoring_daemon.py`.

### Bosqichma-bosqich

0. (loyihalash, kod yo'q) `Finding` shaklini qotirish — C1'ga
   kelajakdagi almashtirish shu kontraktga tayanadi
1. Bitta hardcoded GitHub repo, xotiradagi dedup, bitta fixed vault
   yo'l, klassifikatsiyasiz
2. Ko'p repo + PR/commit qamrovi
3. DB-backed dedup (restart-durable)
4. Resurs chegaralari (timeout + tick oralig'i)
5. `app.py` lifespan'ga ulash (default o'chiq, konfiguratsiya bilan yoqiladi)
6. (alohida yo'l, ega qarori kerak) Telegram manba
7. (C1'ga bog'liq, hozircha yo'q) `note.write`ni Ingestion Router
   chaqiruviga almashtirish

**Baholash:** 1-qadam — yarim kun-1 kun (`shipment_daemon.py` hajmida).
2-5-qadamlar — yana 2-3 kun. 6-qadam alohida va xavfsizlik ko'rib
chiqishi kerak. 7-qadam C1 mavjud bo'lgach — bir necha soat.

### Ochiq savollar (MUROSASIZ — ega qarori kerak)

1. Telegram kanal o'qish: bot-a'zo (kam imkoniyat, kam xavf) yoki
   userbot (to'liq, lekin YANGI xavfsizlik chegarasi)?
2. Bildirishnoma UX — har topilma uchun alohida push, yoki kunlik
   digest (tavsiya: digest, spam bo'lmasin)?
3. Necha repo/qancha Telegram hajmi kutilyapti — GitHub 5000 so'rov/soat
   chegarasi va tanlangan tick oralig'i yetarlimi?

---

## Umumiy xulosa (C1-C5)

| # | Xususiyat | Yangi jadval/migratsiya | Asosiy yangi kod | Baholash |
|---|---|---|---|---|
| C1 | Ingestion Router | yo'q (C2'ga bog'liq) | classifier + extractor + document.extract | ~10-14 qadam |
| C2 | Business Registry | ha (`business`, 1 migratsiya) | 1 model + 3 tool | ~1 kun |
| C3 | Voice Profile | yo'q (mavjud memory) | 1 helper funksiya | ~1 kun |
| C4 | Semantik vault qidiruv | yo'q (indeks) | upsert + reconciliation + query rewrite | ~3-5 kun |
| C5 | Monitoring Daemon | ixtiyoriy (dedup jadval) | 1 daemon klass | ~2-4 kun (+Telegram alohida) |

**Tavsiya etilgan qurilish tartibi (bog'liqliklarga ko'ra):** C2 → C3 →
C4 → C5 (GitHub qismi) → C1 (C2'ga tayanadi, lekin Protocol orqali
mustaqil boshlanishi mumkin) → C5 (Telegram qismi, C1 tugagach
`note.write`ni Ingestion Router bilan almashtirish uchun).
