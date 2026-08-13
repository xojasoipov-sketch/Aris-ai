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

## Test hisobi

| | Son |
|---|---|
| Baseline (KONSOLIDATSIYA v2'dan OLDIN, commit `60a6ad9`) | 2542 |
| Hozirgi jami | **2558** |
| Yangi testlar (bu sessiyada) | **16** |
| Regressiya | **0** |
| To'liq suite natijasi | `2558 passed, 0 failed, 0 error` (Postgres o'chirilgan holda, mypy 12 ta xato — barchasi PRE-EXISTING, `git stash` bilan tasdiqlangan, yangi xato YO'Q) |

Yangi testlar taqsimoti: `test_executor.py` +4 (B2),
`test_intent.py` +2 (B3), `test_planner.py` +2 (B3),
`test_pipeline_integration.py` +2 (A1 ×1, B3 ×1),
`test_recovery.py` +5 (D1×2, D2×1, D3×2),
`test_run_checkpoint.py` +1 (A1).

---

## Yangi HIGH-severity ro'yxati

Ushbu sessiya davomida topilgan/qayta tasdiqlangan, **hali ochiq**
muammolar (foydalanuvchi ro'yxatiga kirmagani uchun tuzatilmadi —
faqat hisobot uchun oshkor qilinadi, "halol yiqilish" tamoyili
bo'yicha):

1. **Mission-darajali approval hali durable EMAS** (A1'da topilgan,
   qisman yumshatilgan). `approval.run_id` — `run.id`ga NOT NULL FK,
   mission-level approval (`run_id=mission.id`) HECH QACHON DB'ga
   yozilmaydi (faqat xotirada). Hozirgi holat: xato ko'tarilmaydi
   (gracefully skip, aniq log), lekin process restart'da mission-level
   pending approval YO'QOLADI. To'liq fix — `approval.run_id`ni
   nullable qilish + mission_id-based alohida saqlash yo'li — yangi
   Alembic migratsiya talab qiladi, bu sessiya doirasidan tashqarida.

2. **Approval-resume BARCHA oldingi bajarilgan qadamlarni qayta
   ishga tushiradi** (tizimli, bu sessiyadan OLDIN ham mavjud edi,
   lekin D1'ning yangi recovery-approval yo'li ham shu muammoni
   meros qilib oladi). `Orchestrator._run_plan()` har chaqiruvda YANGI
   bo'sh `ExecutionContext` yaratadi — `resume()` chaqirilganda
   REJANING BOSHIDAN (0-qadamdan) qayta bajaradi, oldingi
   muvaffaqiyatli WRITE/EXECUTE qadamlar HAM qayta ishga tushadi.
   Agar bunday qadam idempotent bo'lmasa (masalan xabar yuborish,
   to'lov), tasdiqdan keyingi `resume()` shu yon effektni IKKI MARTA
   qiladi. Per-step DB checkpointing (`step` jadvali) — B1'da
   aniqlangan, katta, alohida ish (Task #57 ruhida).

3. **`MissionEngine`ning O'ZINING `recovery=None`** parametri (D4'dan
   FARQLI — bu Mission/Task-Graph darajasidagi alohida recovery yo'li,
   `build_mission_engine_for_session`/`get_mission_orchestrator`da,
   `deps.py`) hali ulanmagan qoladi. Foydalanuvchi so'rovi aniq
   "`deps.py`'s `recovery_engine=None`" (Orchestrator konstruktor
   parametri nomi) deb ko'rsatgani uchun bu — boshqa, tegilmagan
   gap sifatida qoldirildi.

---

## Nima TEGILMADI (doiradan tashqari, ataylab)

- MissionEngine'ning o'z `recovery=None` (yuqorida, #3)
- Telegram bot'ning `_runner`/`_approval_runner`da `notifier=` ulanishi
  (F1'dan alohida, pre-existing)
- To'liq per-step DB persistence (`step` jadvali) — B1'da izohlangan,
  Task #57 ruhidagi katta ish
- C1-C5 — FAQAT reja, hech qanday kod yozilmagan (aniq talab)
