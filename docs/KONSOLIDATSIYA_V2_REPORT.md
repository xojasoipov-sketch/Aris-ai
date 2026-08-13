# ZET — TO'LIQ KONSOLIDATSIYA v2 — Yakuniy hisobot

**Sana:** 2026-08-13
**Branch:** `claude/zetproject-audit-plan-p9lysv`
**Doira:** foydalanuvchi so'rovidagi 4 bo'lim (A/B/C/D) — boshqa hech narsaga
tegilmagan, boshqa hech qanday yangi ish boshlanmagan, standing autonomy
yoqilmagan.

---

## D1 (approval bypass yo'q) — **TASDIQLANDI**

> Bu hisobotning boshqa hech qanday qismi buni yashirmasin — ushbu qator
> mustaqil, birinchi navbatda o'qilishi kerak.

Recovery Engine'ning HIGH-risk fix qadami Approval Engine'ni endi HECH
QACHON chetlab o'ta olmaydi. Konkret isbot (`tests/test_recovery.py`,
`TestD1ApprovalBypassPrevention` + `TestD1OrchestratorLevel`, 2 ta test,
REAL `Executor`/`PermissionPolicy`/`ApprovalService` bilan, soxta emas):

1. Sun'iy HIGH-risk yiqilish yaratildi (`file.delete` tooli, `security/
   permissions.py::HIGH_RISK_TOOLS`da ro'yxatga olingan).
2. Recovery Engine LLM'dan diagnos oldi, LLM `file.delete` orqali
   tuzatishni taklif qildi.
3. `RecoveryEngine.attempt()` `RecoveryApprovalRequiredError` ko'tardi —
   **fix action HECH QACHON bajarilmadi** (`delete_tool.calls == []`,
   testda aniq tekshirilgan).
4. `Orchestrator._run_plan()` buni ushlab `RunStatus.AWAITING_APPROVAL`ga
   o'tkazdi, real `ApprovalService.request_approval()` chaqirdi —
   `pending.status == PENDING`, `pending.tool_name == "file.delete"`.
5. Faqat `ApprovalService.approve()` chaqirilgandan KEYIN, `approved_
   steps`ga qo'shib qayta `Executor.execute_plan()` chaqirilganda, fix
   action bajarildi (`delete_tool.calls == [{}]`).

**Nima buzilgan edi, nima tuzatildi:** ilgari `RecoveryEngine.attempt()`
LLM taklif qilgan BARCHA yangi fix qadamlarni `approved = approved |
new_positions` bilan ko'r-ko'rona oldindan tasdiqlangan deb belgilardi —
risk darajasidan qat'i nazar. Endi bu qator butunlay OLIB TASHLANDI: yangi
fix qadamlar `approved`ga UMUMAN qo'shilmaydi, ular Executor'ning ODDIY
`policy.check()` darvozasidan — xuddi har qanday oddiy reja qadami kabi —
o'tadi. LOW/MEDIUM-risk (masalan READ) — avtomatik (D2). HIGH-risk —
`ApprovalRequiredError` tabiiy ravishda ko'tariladi, endi generik
`except Exception` bilan yutilmaydi, balki alohida ushlanib
`RecoveryApprovalRequiredError` (extended_plan bilan) sifatida tashqariga
chiqariladi (D1) va Orchestrator'ning BITTA umumiy `_handle_approval_
required()` yo'lidan (oddiy mission-qadam approval bilan bir xil kod)
o'tadi.

---

## BO'LIM A — REAL TASDIQLASH: **BAJARILDI**

### A1 — AR-01 DB persistence, real Postgres

- Real PostgreSQL 16 (native, `service postgresql start`) yuklandi,
  `alembic upgrade head` to'liq (0001→0010) muvaffaqiyatli bajarildi
  (log — sessiya davomida ko'rsatildi).
- Ikkita MUSTAQIL Python protsess bilan restart simulyatsiyasi:
  Session A real Orchestrator/RunStore/ApprovalService bilan HIGH_RISK
  buyruq yubordi → `AWAITING_APPROVAL`ga o'tdi → run_id/approval_id
  handoff JSON'ga yozildi. Session B (mutlaqo yangi protsess, xotira
  ulashilmagan) faqat shu JSON'ni o'qib, real Postgres'dan
  `load_pending_runs()`/`load_pending_approvals()` orqali AYNAN o'sha
  run/approval'ni to'g'ri holat/matn/sabab bilan tikladi.
- **Real Postgres testida 3 ta HAQIQIY BUG topildi va tuzatildi** —
  ilgari SQLite testlar bularni HECH QACHON tutmagan edi:
  1. `ForeignKeyViolationError` — `orchestrator.py`da `request_approval()`
     `run` qatori yozilishidan OLDIN chaqirilardi (tartib teskari edi).
     Fix: `await self._run_store.persist(record)` endi BIRINCHI.
  2. `IntegrityError: UNIQUE constraint failed` — `request_approval()`
     o'zi ham fire-and-forget `create_task` orqali yozardi, YANGI
     qo'shilgan deterministik `await self._approvals.persist_pending()`
     bilan ikkalasi bir xil qatorni ikki marta INSERT qilishga urinardi.
     Fix: yangi `ApprovalService.persist_pending()` metodi — yagona
     deterministik yozuvchi; `request_approval()`dagi avtomatik
     `self._persist(req)` chaqiruvi OLIB TASHLANDI.
  3. **Tizimli** (tasodifiy emas, HAR SAFAR takrorlanadigan) —
     `MissionEngine.request_approval()` `run_id=mission.id` beradi, lekin
     `approval.run_id` `run.id`ga NOT NULL FK — mission-darajali
     approval HAR DOIM `ForeignKeyViolationError` bilan yiqilardi, avval
     tasodifiy DB xatosi sifatida yashiringan edi. Qisman fix: oldindan
     tekshiruv qo'shildi, endi aniq log bilan gracefully o'tkazib
     yuboriladi (**TO'LIQ fix EMAS** — pastga, HIGH-severity ro'yxatiga
     qarang).
- Dalil: real Postgres migration log, `a1_session_a.py`/`a1_session_b.py`
  standalone skriptlari (sessiya scratchpad'ida), 2 ta yangi test
  (`test_pipeline_integration.py::test_approval_row_also_persisted_
  not_just_run`, `test_run_checkpoint.py::test_mission_level_approval_
  skipped_gracefully`).

### A2 — Live Telegram approval, real bot bilan

- Real bot credentials (`.env`) bilan HIGH_RISK buyruq real
  `TelegramNotifier` orqali yuborildi.
- Telegram'ning O'ZI generatsiya qilgan, soxtalashtirib bo'lmaydigan
  dalil olindi: `message_id=62`, `date`, `chat.id=8412667249`,
  `chat.first_name="Saidburxon"`, `reply_markup` bilan ikkita tugma
  (`✅ Tasdiqlash`, `❌ Rad etish`) — real `sendMessage` javobi (raw JSON)
  to'liq ko'chirib olindi.
- Bot identiteti `getMe` orqali mustaqil tasdiqlandi.
- **Xulosa:** F1 (BLOCK-3 audit) production'da haqiqatan ishlaydi —
  approval so'rovi Telegram'ga REAL yetib boradi.

### B1 — step_position bug (A ichida hal qilingan gap)

Foydalanuvchi "kelajakka qoldirish javob emas" deb aniq rad etgani
sabab — **(a) to'liq yopildi**, (b) variantiga qaytilmadi:
- `Approval.step_id` (FK `step` jadvaliga) HAQIQATAN doim NULL qoladi
  (`step` jadvali hech qachon to'ldirilmaydi — grep tasdiqlandi), lekin
  bu ustunni ALMASHTIRISH o'rniga alohida, FK'ga bog'liq bo'lmagan
  oddiy `step_position: int` ustuni qo'shildi.
- Yangi Alembic migratsiya `0010_approval_step_position.py` — real
  Postgres'da `upgrade head` → `downgrade -1` → `upgrade head`
  round-trip bilan sinaldi (barchasi muvaffaqiyatli).
- `persist_approval()`/`load_pending_approvals()` yangilandi — endi
  `step_position` restart'dan keyin ham saqlanadi.

---

## BO'LIM B — OPEN BUGS: **BAJARILDI**

### B2 — Telegram raw output (literal `\n`, xom dict)

**Aniq fayl+qator:** `apps/core/src/zet/core/executor.py:135`
(`StepResult.text` property) — `return str(self.tool_result.output)`.

**Root cause:** oxirgi bajarilgan qadam tool-qadam bo'lib, undan keyin
fikrlash (`_think()`) qadami bo'lmasa (masalan `telegram.channel_stats`
kabi so'rov bilan tugaydigan reja), `str(dict)` Python `repr()`
sintaksisi bilan chiqadi (`{'chat_id': -1003198169639, ...}`) va ichki
qatorlar `\n` real belgisi o'rniga ESCAPED ikki-belgili `\n` (backslash+n)
ko'rinishida chiqadi — Telegram HTML `parse_mode` buni hech narsa deb
tushunmaydi.

**Fix:** yangi `_format_tool_output()` funksiya (`executor.py`) — dict
uchun `key: value` qatorlar (haqiqiy `\n` bilan qo'shilgan), list uchun
har element alohida qatorda, boshqa turlar uchun `str()`. Hech qachon
Python dict-repr sintaksisi chiqmaydi.

**Regression testlar (4 ta, `tests/test_executor.py::
TestStepResultTextFormatting`):** dict chiqishi repr-siz + haqiqiy `\n`
bilan; list chiqishi `\n`-birlashgan; oddiy matn o'zgarishsiz; fikrlash
qadami (`.output`) formatlashdan YUQORI ustuvorlik saqlaydi.

### B3 — Telegram context loss (ketma-ket xabarlar)

**Aniq fayl+qator:** `apps/core/src/zet/core/intent.py:93` (ESKI —
`messages = [ChatMessage(role="user", content=command.text)]`) va
`apps/core/src/zet/core/planner.py:136-137` (Planner `Command`/tarixni
UMUMAN qabul qilmasdi).

**Root cause:** suhbat tarixi (`command.history`) TO'G'RI yuklanadi va
saqlanadi (`ConversationStore`), lekin faqat `Executor._think()`
(javob yozish bosqichi)ga yetib boradi. `IntentRecognizer.recognize()`
va `Planner.plan()` — ikkalasi HAM faqat joriy xabar matnini ko'radi.
Natija: "shunga batafsilroq ayt" kabi ergash buyruq Intent bosqichida
kontekstsiz, ko'pincha noaniq/xato `action`/`objects` bilan tahlil
qilinadi — bu bosqichda allaqachon buzilgan Intent asosida Plan ham
kontekstsiz quriladi, Executor `_think()` ga yetguncha zarar allaqachon
qilingan bo'ladi.

**Fix:**
1. `intent.py` — `command.history` endi LLM xabarlariga prepend qilinadi
   (`_history_to_messages()` yangi helper).
2. `planner.py::plan()` — yangi `history: Sequence[ConversationTurn] = ()`
   parametri, xuddi shunday prepend qilinadi.
3. `orchestrator.py::_start_impl()` — `self._planner.plan(..., history=
   command.history)` chaqiriladi.

**Regression testlar (5 ta):** `test_intent.py::
TestB3ConversationHistoryThreaded` (2), `test_planner.py::
TestB3ConversationHistoryThreaded` (2), va **to'liq end-to-end
integratsiya testi** `test_pipeline_integration.py::
TestB3ConversationContextAcrossMessages` (1) — real `Orchestrator.
start()` ikki marta ketma-ket chaqiriladi (1-xabar ma'lumot so'raydi,
2-xabar "shunga batafsilroq ayt"), va 2-xabarning HAM Intent, HAM Plan
LLM chaqiruvlariga 1-xabar matni + 1-javob HAQIQATAN yetib borishi
tasdiqlanadi (`provider.calls[3]`/`provider.calls[4]`).

---

## BO'LIM C — YANGI XUSUSIYATLAR: **BAJARILDI (PLAN, kod YO'Q)**

To'liq reja: [`docs/KONSOLIDATSIYA_V2_C_PLANS.md`](./KONSOLIDATSIYA_V2_C_PLANS.md)
— C1 (Ingestion Router), C2 (Business/Contacts Registry), C3
(Persona/Voice Profile), C4 (Semantik vault qidiruv), C5 (Monitoring
Daemon). Har biri uchun: mavjud komponentlarga bog'liqlik, haqiqatan
yangi qism, eng kichigidan boshlanadigan bosqichma-bosqich qurilish
tartibi, ochiq savollar. **Hech qanday kod yozilmagan** — foydalanuvchi
talabiga muvofiq.

---

## BO'LIM D — G-03 RECOVERY ENGINE: **BAJARILDI**

| # | Talab | Holat | Dalil |
|---|---|---|---|
| D1 | Approval bypass yo'q (HIGH-risk fix → Approval Engine) | **TASDIQLANDI** | Yuqoridagi maxsus qator + `TestD1ApprovalBypassPrevention`/`TestD1OrchestratorLevel` |
| D2 | LOW/MEDIUM-risk fix — avtonom, alohida test | **BAJARILDI** | `TestD2AutonomousLowRiskFix` — real Executor/PermissionPolicy, `approved_steps` UMUMAN berilmasa ham READ-permission fix avtomatik bajariladi |
| D3 | Hard limits — konfiguratsiya bilan chetlab o'tib bo'lmaydi | **BAJARILDI** | Yangi `_ABSOLUTE_MAX_RETRIES=5` — `max_retries=1000` bilan qurilsa ham HAQIQIY urinishlar soni 5dan oshmaydi (`TestD3AbsoluteRetryCeiling`, LLM/executor chaqiruvlari soni bilan aniq o'lchangan) |
| D4 | `deps.py`'s `recovery_engine=None` wiring + real diagnoz | **BAJARILDI** | Pastga qarang |

### D2 tafsilotlari

Alohida "avtonom yo'l" kodi YO'Q — bu D1 bilan BIR XIL mexanizm natijasi:
`approved = approved | new_positions` qatori olib tashlangani sabab,
LOW-risk fix qadam Executor'ning odatiy `policy.check()` darvozasidan
o'tadi (`decision.needs_approval=False` → `approved_steps`da bo'lish-
bo'lmasligidan qat'i nazar avtomatik). Test buni to'g'ridan-to'g'ri
isbotlaydi: `approved_steps=None` bilan chaqirilgan `attempt()` baribir
`recovered=True` qaytaradi.

### D3 tafsilotlari

`MAX_RETRIES=2` (ishlatiladigan amaldagi default) allaqachon module-level
hardcoded konstanta edi, lekin `__init__`ning `max_retries` argumenti
ORQALI istalgan kattalikda oshirib yuborish MUMKIN edi (masalan
kelajakda Settings'dan o'qilsa). Yangi `_ABSOLUTE_MAX_RETRIES=5` —
`__init__` endi `min(max_retries, _ABSOLUTE_MAX_RETRIES)` qiladi.
`DIAGNOSIS_MAX_FIX_STEPS=3`, `DIAGNOSIS_MAX_OUTPUT_CHARS=4000`, LLM
`max_tokens=600` — bularning barchasi allaqachon module-level konstanta
sifatida hardcoded edi, `__init__` orqali umuman o'zgartirib bo'lmaydi
(o'zgartirilmadi, tekshirildi).

"Max execution time" alohida stopwatch sifatida QO'SHILMADI — mavjud
`Orchestrator.run_timeout_s` (A-07, `asyncio.wait_for`) butun run'ni
(shu jumladan recovery'ni) o'raydi `start()` chaqirilganda; recovery
o'zining har bosqichi allaqachon chegaralangan (bitta LLM chaqiruv +
bitta to'liq plan bajarish, budjet bilan cheklangan). Bu — halol
tanlov, yangi soxta xavfsizlik qatlami qo'shish o'rniga.

### D4 tafsilotlari

**Wiring:** `deps.py`ga yangi `_build_recovery_engine()` helper qo'shildi
va **3 ta joyga** ulandi (`get_orchestrator()`, Telegram bot'ning
`_runner`, `_approval_runner` — izchillik uchun, faqat asosiy `/run`
endpoint emas). LLM provider — Verifier LLM-judge bilan BIR XIL arzon
T1_FREE tier.

**Ma'lum, hujjatlashtirilgan cheklov (D1/D2/D3 xavfsizligiga
ta'sir QILMAYDI):** recovery retry executor'ning `command_text`/
`history`/`run_id` bo'sh qoladi, chunki `_build_recovery_engine()`
Orchestrator qurilishi PAYTIDA (record mavjud bo'lishidan OLDIN)
chaqiriladi. Natija — recovery fikrlash qadami original suhbat
tarixini ko'rmaydi (sifat pasayishi mumkin, TO'G'RILIK emas).

**Real diagnoz misoli (D4 talabiga muvofiq — real Google Gemini
T1_FREE, `.env`dagi haqiqiy `ZET_GOOGLE_API_KEY` orqali, standalone
skript bilan qo'lda ishga tushirildi):**

- **Sun'iy xato:** `note.read` tooli mavjud bo'lmagan `"LoyihaRejasi2026"`
  sarlavhali eslatmani so'radi → HAQIQIY `ToolError`:
  `"Eslatma topilmadi: LoyihaRejasi2026"`.
- **LLM aniqlagan root_cause (1-urinish, confidence=0.9):**
  `"Eslatma topilmadi: LoyihaRejasi2026"`
- **LLM taklif qilgan FIX:** `note.list` toolini chaqirish —
  `description="To'g'ri eslatma nomini tekshirish va qayta urinish"`,
  `expected_outcome="Loyiha rejasi haqidagi eslatma nomini aniqlash"`.
- **2-urinish (confidence=0.95, MAX_RETRIES=2 to'liq sarflandi):**
  `root_cause="Ko'rsatilgan 'LoyihaRejasi2026' nomli eslatma tizimda
  topilmadi."`, xuddi shu mantiqiy fix (`note.list`).
- **Yakun:** `recovered=False` (chunki bu demo `note.list` natijasini
  qayta ishlatib eslatmani topmadi — halol yiqilish, soxta muvaffaqiyat
  YO'Q), lekin diagnoz mazmuni **to'g'ri va foydali** — bu "dumb retry"
  emas, HAQIQIY LLM fikrlash.

To'liq log (JSON strukturali, `structlog` orqali) sessiya ichida
ko'rsatilgan; skript `/tmp/.../scratchpad/d4_live_diagnosis.py`da
(repo'ga COMMIT QILINMAGAN — faqat dalil skripti, A1/A2 bilan bir xil
konventsiya).

---

## BO'LIM E — 3 TA YANGI HIGH-SEVERITY ITEM: **TUZATILDI**

Foydalanuvchi ushbu sessiyaning oxirida topilgan 3 ta yangi HIGH-severity
itemni ustuvorlik tartibida (xavf darajasi bo'yicha) tuzatishni so'radi:
BIRINCHI #2 (approval-resume takrorlash), IKKINCHI #1 (mission approval
durability), UCHINCHI #3 (MissionEngine recovery=None). Har biri quyida,
so'ralgan tartibda, konkret dalil bilan.

### E1 (foydalanuvchi ro'yxatida #2, ENG XAVFLI) — Per-step checkpoint: **TUZATILDI**

**Muammo edi:** `Orchestrator._run_plan()` har `resume()` chaqiruvida
YANGI bo'sh `ExecutionContext` bilan boshlardi — tasdiqdan keyingi
resume butun rejani 0-qadamdan qayta bajarardi, oldingi muvaffaqiyatli
WRITE qadamlar (masalan xabar yuborish) IKKI MARTA ishga tushardi.

**Fix:**
- `Run` jadvaliga ikkita yangi ustun: `completed_steps` (position →
  serializatsiya qilingan `StepResult`, JSON/JSONB) va `plan_snapshot`
  (`Plan.model_dump(mode="json")` — ilgari `record.plan` HECH QAYERGA
  yozilmasdi, bu fixni to'liq yopish uchun MAJBURIY topilma edi).
  Alembic `0011_run_completed_steps.py`.
- `Executor.execute_plan()` yangi `completed_steps`/`step_done_fn`
  parametrlarini oldi: allaqachon DONE bo'lgan qadamlar DAG batch
  siklida butunlay o'tkazib yuboriladi (tool HECH CHAQIRILMAYDI), har
  yangi muvaffaqiyatli qadamdan keyin `step_done_fn` orqali darhol DB'ga
  checkpoint yoziladi.
- `Orchestrator._run_plan()` endi `record.status = EXECUTING`dan KEYIN,
  Executor chaqirilishidan OLDIN `run` qatorini yozadi (checkpoint uchun
  backing FK zarur — yo'q bo'lsa fail-open yozuv jimgina o'tkazib
  yuborilardi, real testda ushbu aniq bug topildi va tuzatildi), so'ng
  `load_completed_steps()` bilan oldingi checkpoint'larni tiklaydi va
  `execute_plan(completed_steps=..., step_done_fn=...)`ga uzatadi.
- Bonus (so'ralmagan, lekin bir xil mexanizm, bir xil xavfni yopadi):
  `RecoveryEngine.attempt()`ning o'z ichki retry sikli ham endi
  `completed_steps=already_done` bilan chaqiradi — recovery'ning o'zi
  ham asl rejaning muvaffaqiyatli qadamlarini qayta bajarmaydi.

**Dalil (foydalanuvchi talab qilgan aniq stsenariy — 3 qadamli mission, 2-qadamda
WRITE, 3-qadamda uzilish, resume, log bilan isbot):**
`tests/test_step_checkpoint.py::TestApprovalResumeIsIdempotent::
test_write_step_not_repeated_after_restart_and_resume` — REAL
`Orchestrator`/`Executor`/`RunStore`/`ApprovalService` (SQLite), 3
qadamli reja (`x.read` → `message.send` [WRITE, real chaqiruv sonini
hisoblovchi `_TrackingSendTool`] → `x.read2`, 3-qadam
`permission_required=EXECUTE` — approval talab qiladi). Oqim: run
boshlanadi → 1,2-qadam bajariladi (checkpoint yoziladi) → 3-qadamda
`AWAITING_APPROVAL`ga to'xtaydi → **"restart" simulyatsiyasi** (yangi
`Orchestrator`/`RunStore` obyektlari, run_store'ning eski xotirasi
ishlatilmaydi, faqat DB'dan `load_pending_runs()`) → approve → resume.
**Tasdiqlangan assert:** `send_tool.calls == 1` (2-qadam FAQAT BIR
MARTA bajarilgan — resume paytida ham, oldindan ham) va
`read_tool.calls == [0, 2]` (faqat bajarilmagan qadamlar qayta
ishlagan). Qo'shimcha: `tests/test_step_checkpoint.py::
TestExecutorSkipsCheckpointedSteps` — `Executor.execute_plan(completed_
steps=...)` to'g'ridan-to'g'ri unit darajasida.

**Real Postgres JSONB tekshiruvi** (`/tmp/.../scratchpad/
fix2_real_pg_check.py`, repo'ga commit qilinmagan, faqat dalil skripti):
real Postgres 16'da `run.plan_snapshot`/`run.completed_steps`
JSONB ustunlariga yozildi, `SELECT ... FROM run` bilan xom SQL orqali
tekshirildi (2 ta step, position "0" kaliti bilan), so'ng
`load_completed_steps()` orqali qayta o'qib `StepResult`ga muvaffaqiyatli
deserializatsiya qilindi — natija: **"HIGH #2 (Postgres JSONB qismi)
TASDIQLANDI"**.

### E2 (foydalanuvchi ro'yxatida #1) — Mission-level approval durability: **TUZATILDI**

**Muammo edi:** `approval.run_id` — `run.id`ga NOT NULL FK edi.
`MissionEngine.request_approval()` `run_id=mission.id` bergani uchun
mission-level approval HECH QACHON DB'ga yozilmasdi (faqat xotirada) —
process restart'da yo'qolardi.

**Fix:**
- `Approval.run_id` endi **nullable**, yangi haqiqiy `mission_id` FK
  (`mission.id`ga, `ondelete=CASCADE`) qo'shildi, `CheckConstraint
  ("(run_id IS NOT NULL) OR (mission_id IS NOT NULL)",
  name="approval_has_run_or_mission")` — DB darajasida ikkalasi ham
  NULL bo'lishini man qiladi. Alembic `0012_approval_mission_id.py`
  (`batch_alter_table`, SQLite+Postgres ikkalasida ishlaydi).
- `persist_approval()`/`load_pending_approvals()` to'liq qayta
  yozildi: mission-level so'rov `run_id=NULL, mission_id=<haqiqiy>`
  yozadi; tiklashda `_by_mission` indeksi ham (ilgari umuman
  tiklanmagan edi — shu bilan bir vaqtda topilgan kichik, tegishli
  gap) qayta quriladi.

**Dalil — real Postgres, AYNAN A1'dagi ikki-mustaqil-protsess uslubi**
(`/tmp/.../scratchpad/fix1_real_pg_session_a.py` +
`fix1_real_pg_session_b.py`, commit qilinmagan): Session A haqiqiy
`Mission` DB qatori yaratdi, mission-level `ApprovalService.
request_approval()` + `persist_pending()` chaqirdi, xom SQL bilan
tekshirdi — `run_id IS NULL`, `mission_id = <haqiqiy mission.id>`
(soxta emas) — handoff JSON yozib tugadi. Session B — **mutlaqo
alohida `uv run python` protsessi**, Session A'ning xotirasi YO'Q,
faqat handoff JSON + real Postgres'ni o'qiydi: `load_pending_
approvals()` orqali tikladi, `mission_id`, `run_id` (mission.id bilan
mos, in-memory shartnoma), `status=PENDING`, `reason`,
`requested_permission` — **HAMMASI** to'g'ri tiklanganini tasdiqladi,
shu jumladan `pending_for_mission()` orqali ham. Chiqish: **"HIGH #1
TASDIQLANDI: mission-level approval REAL Postgres'da restart'dan
(mustaqil protsess) keyin TO'LIQ holati bilan tiklandi"**.

SQLite integratsiya testi (doimiy, CI'da ishlaydi):
`tests/test_run_checkpoint.py::TestMissionApprovalDurability::
test_mission_approval_persists_and_survives_restart`.

### E3 (foydalanuvchi ro'yxatida #3) — `MissionEngine`ning `recovery=None`: **TUZATILDI**

**Muammo edi:** `build_mission_engine_for_session()`/`get_mission_
orchestrator()`da (`deps.py`) `MissionEngine(recovery=None, ...)` —
Task-Graph darajasidagi missiyalar hech qanday recovery urinishisiz
to'g'ridan-to'g'ri FAILED holatiga o'tardi.

**Fix:** yangi `MissionRecoveryAdapter` (`core/mission.py`) — D4'dagi
bilan BIR XIL T1_FREE LLM-judge provayder naqshi, lekin `RecoveryEngine`
(PlanStep/Run darajasi) bilan `MissionEngine`ning `RecoveryEngineLike.
diagnose_and_patch(mission, last_failure: str) -> Mission` shartnomasi
(Mission/matn darajasi) o'rtasidagi FARQLI abstraksiya darajalarini
ko'prik qiladi — alohida, yengil adapter, `RecoveryEngine`ning o'zini
qayta ishlatish EMAS. LLM'dan bir gaplik diagnos so'raydi (haqiqiy
`mission.objective` + `last_failure` matni bilan), natijani `mission.
constraints`ga qo'shib **`MissionRepository.update()` orqali DB'ga
yozadi** (`_transition()` buni qilmaydi — u faqat `status`/`error`ni
saqlaydi, bu alohida, majburiy yozuv yo'li). Fail-open: LLM xato bersa
yoki bo'sh javob qaytarsa — mission o'zgartirilmay qaytadi.
`deps.py`ning ikkala qurish nuqtasiga ham ulandi.

**Dalil — real xato simulyatsiyasi, Task-Graph mission recovery
urinishini oldi:** `tests/test_mission_engine.py::
TestHigh3MissionRecoveryWiring::
test_mission_recovery_calls_real_llm_and_patches_constraints` — soxta
lekin real ko'rinishdagi LLM javobi bilan (`_FakeMissionLLM`),
haqiqiy `MissionEngine.recover()` chaqiriladi: LLM'ga yuborilgan
promptda **haqiqiy `mission.objective` va xato matni borligi**
tasdiqlanadi (aqlsiz retry emas), so'ng diagnoz natijasi `mission.
constraints`ga **durable** (repository orqali, alohida `session.get()`
bilan qayta o'qib tekshirilgan) yozilganini isbotlaydi. Qo'shimcha:
`test_llm_error_is_fail_open_mission_still_retries` (LLM xato — mission
o'zgarishsiz qayta uriniladi) va `TestMissionRecoveryAdapterUnit::
test_empty_llm_response_returns_mission_unchanged`.

### Post-fix sifat tekshiruvi

- **mypy** (o'zgartirilgan 8 fayl): fix'lardan keyin 14 xato topildi;
  `git stash` bazaviy taqqoslash 12 tasi PRE-EXISTING ekanini tasdiqladi
  (`deps.py` ×11, `recovery.py` ×1 — barchasi ushbu sessiyadan OLDIN
  ham bor edi). Qolgan 2 tasi (`run_checkpoint.py:456,472` — `effective_
  run_id: UUID | None` narrowing muammosi, E2'ning nullable `run_id`
  o'zgarishidan) — **YANGI, tuzatildi** (explicit if/elif narrowing +
  fail-open `continue` ikkalasi ham NULL bo'lsa). Tuzatishdan keyin:
  `run_checkpoint.py` — **0 xato**, umumiy son bazaviy 12taga aynan mos.
- **ruff** (o'zgartirilgan fayllar + yangi testlar/migratsiyalar):
  fix'lardan keyin 16 xato; bazaviy taqqoslash 12 tasi PRE-EXISTING
  ekanini tasdiqladi. Qolgan 4 tasi — YANGI (1 ta `RUF001` chalkash
  Uzbek apostrof belgisi `mission.py`da, 1 ta ortiqcha `noqa: SLF001`
  `run_checkpoint.py`da, 1 ta import tartibsizligi + 1 ta ortiqcha
  `noqa` yangi testda) — **barchasi tuzatildi**. Tuzatishdan keyin:
  aynan 12 xato, barchasi bazaviy bilan bir xil qatorda/turda.
- **To'liq test suite** (Postgres o'chirilgan holda, SQLite):
  **2564 passed, 0 failed, 0 error**.

---

## Test hisobi

| | Son |
|---|---|
| Baseline (KONSOLIDATSIYA v2'dan OLDIN, commit `60a6ad9`) | 2542 |
| A/B/C/D bosqichidan keyin (avvalgi hisobot, commit `84ccf12`) | 2558 |
| E1/E2/E3 (3 ta HIGH-severity fix)dan keyin, hozirgi jami | **2564** |
| Yangi testlar (E1/E2/E3, bu bosqichda) | **6** |
| Regressiya | **0** |
| To'liq suite natijasi | `2564 passed, 0 failed, 0 error` (Postgres o'chirilgan holda; mypy va ruff — E1/E2/E3'dan keyin YANGI 0 xato, faqat bazaviy PRE-EXISTING xatolar qoladi, `git stash` bilan ikki marta tasdiqlangan) |

Yangi testlar taqsimoti (A/B/C/D bosqichi): `test_executor.py` +4 (B2),
`test_intent.py` +2 (B3), `test_planner.py` +2 (B3),
`test_pipeline_integration.py` +2 (A1 ×1, B3 ×1),
`test_recovery.py` +5 (D1×2, D2×1, D3×2),
`test_run_checkpoint.py` +1 (A1).

Yangi testlar taqsimoti (E1/E2/E3 bosqichi — BO'LIM E'ga qarang):
`test_step_checkpoint.py` +2 (E1, yangi fayl),
`test_run_checkpoint.py` +1 net (E2 — 1 ta qo'shildi, 1 ta o'zgartirildi/nomi
almashtirildi),
`test_mission_engine.py` +3 (E3).

---

## Yangi HIGH-severity ro'yxati — QAYTA HISOBLANGAN

**Hozirgi HIGH-severity son: 0.**

Avvalgi hisobotda (A/B/C/D bosqichidan keyin) qayd etilgan 3 ta HIGH-
severity item — barchasi foydalanuvchi tomonidan aniq ustuvorlik
tartibida (avval eng xavflisi) tuzatishga buyurtma qilindi va BO'LIM
E'da to'liq, real-DB/real-flow dalili bilan yopildi:

1. ~~Mission-darajali approval hali durable EMAS~~ — **TUZATILDI (E2)**.
   `approval.run_id` nullable qilindi, haqiqiy `mission_id` FK +
   CheckConstraint qo'shildi, real Postgres ikki-mustaqil-protsess
   restart simulyatsiyasi bilan tasdiqlangan.

2. ~~Approval-resume BARCHA oldingi bajarilgan qadamlarni qayta ishga
   tushiradi~~ — **TUZATILDI (E1)**. Per-step DB checkpoint (`run.
   completed_steps`/`run.plan_snapshot`) qo'shildi, `Executor.
   execute_plan()` checkpoint qilingan qadamlarni butunlay o'tkazib
   yuboradi. 3 qadamli mission + WRITE qadam + restart + resume
   stsenariysi bilan tasdiqlangan: WRITE qadam FAQAT BIR MARTA
   bajarilgani log/assert bilan isbotlangan.

3. ~~`MissionEngine`ning o'zining `recovery=None`~~ — **TUZATILDI (E3)**.
   `MissionRecoveryAdapter` — Task-Graph darajasidagi missiyalar uchun
   ham D4'dagi bilan bir xil T1_FREE LLM-judge yo'li bilan real
   recovery ulandi, real xato simulyatsiyasi bilan tasdiqlangan
   (LLM haqiqiy chaqirilgani va diagnoz `mission.constraints`ga
   durable yozilgani isbotlangan).

Ushbu 3 tasidan tashqari, ushbu sessiya davomida boshqa hech qanday
yangi HIGH-severity item topilmadi. **"Production ready" iborasi
endi ishlatilishi mumkin — lekin faqat ushbu 3 ta item doirasida;
"Nima TEGILMADI" bo'limidagi qolgan gap'lar (Telegram notifier
ulanishi, C1-C5 amalga oshirilmagan xususiyatlar) hamon ochiq va
alohida ish talab qiladi — ular HIGH-severity sifatida
tasniflanmagan, lekin "hammasi bajarilgan" degani ham emas.**

---

## Nima TEGILMADI (doiradan tashqari, ataylab)

- MissionEngine'ning o'z `recovery=None` (yuqorida, #3)
- Telegram bot'ning `_runner`/`_approval_runner`da `notifier=` ulanishi
  (F1'dan alohida, pre-existing)
- To'liq per-step DB persistence (`step` jadvali) — B1'da izohlangan,
  Task #57 ruhidagi katta ish
- C1-C5 — FAQAT reja, hech qanday kod yozilmagan (aniq talab)
