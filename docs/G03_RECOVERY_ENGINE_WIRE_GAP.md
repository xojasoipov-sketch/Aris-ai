# G-03 — Recovery Engine Wire Gap (investigation + plan, NO code changes)

> **YANGILANISH (2026-08-13, KONSOLIDATSIYA v2):** boss implementatsiyaga
> ruxsat berdi va D1-D4 (shu jumladan quyida "Approval bypass riski"
> deb belgilangan KRITIK gap) tuzatildi. To'liq natija:
> [`docs/KONSOLIDATSIYA_V2_REPORT.md`](./KONSOLIDATSIYA_V2_REPORT.md)
> (BO'LIM D). Ushbu hujjat TARIXIY tekshiruv sifatida o'zgarishsiz
> qoldirilgan.

**Holat:** faqat tekshiruv va reja. Hech qanday kod o'zgarishi qilinmagan
va qilinmaydi — ega o'zi qaror qilishi kerak.

**Sana:** 2026-08-13

---

## 1. Hozirgi holat — nima bor, nima yo'q

### Modul mavjud (711 qator) va to'liq test qilingan

Fayl: `apps/core/src/zet/core/recovery.py`

- `RecoveryEngine` klassi — FAIL→DIAGNOSE→FIX→RETRY→VERIFY sikli
  (Master Spec PART 6 va AUTONOMY_AUDIT §2.5 ta'rifi bo'yicha)
- `Diagnosis` frozen dataclass — LLM javobi + fix_steps + confidence + raw
- `RecoveryOutcome` frozen dataclass — recovered/attempts/diagnoses/extended_plan/final_verification
- 3 ta qattiq chegara: `MAX_RETRIES=2`, `DIAGNOSIS_MAX_OUTPUT_CHARS=4000`,
  `DIAGNOSIS_MAX_FIX_STEPS=3`
- Fail-open audit hook (`_emit_audit`)
- LLM/parse xato → Diagnosis empty `fix_steps` bilan qaytadi (urinish sarflanadi
  lekin dastur yiqilmaydi)

Testlar: `apps/core/tests/test_recovery.py` — 9 test klassi
(TestAttemptShortCircuit, TestSingleFixSucceeds, TestMaxRetriesEnforced,
TestParseErrorConsumesAttempt, TestDagValidityPreserved,
TestOrchestratorTransitionsToRecovering, TestLLMErrorTreatedAsParseError,
TestDiagnosisPromptIncludesContext, TestFixStepsCapped).

**Ya'ni modul ishlaydi — faqat production DI'ga ulanmagan.**

### Wire gap — 3 joyda `recovery_engine=None`

Fayl: `apps/core/src/zet/api/deps.py`

**Joy 1 — `get_orchestrator()` (asosiy /run endpoint uchun):**
```python
# deps.py:919-934 — Orchestrator konstruksiyasi
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
    # ← `recovery_engine=` YO'Q → default None → RecoveryEngine ishlamaydi
)
```

**Joy 2 — Mission approve helperi:**
```python
# deps.py:981
return MissionEngine(
    ...,
    recovery=None,  # ← aynan None
    ...,
)
```

**Joy 3 — `get_mission_orchestrator()`:**
```python
# deps.py:1040
engine = MissionEngine(
    ...,
    recovery=None,  # ← aynan None
    ...,
)
...
# deps.py:1052 — Mission Orchestrator recovery_engine ni Orchestrator'dan oladi
recovery_engine=orchestrator._recovery_engine,  # ← lekin bu ham None (Joy 1 sabab)
```

**Xulosa:** butun zanjir `None` bilan uziladi. `verify_run(FAIL)` sodir bo'lganda
`orchestrator._run_plan` recovery branch'iga tushmasdan darhol `RunStatus.FAILED`
ga o'tadi (orchestrator.py:407 else shoxi).

### Bevosita ta'sir

- Har `verify FAIL` — darhol `FAILED`, ega hech qanday tuzatish urinishini ko'rmaydi
- AUTONOMY_AUDIT §2.5 qoidasi buziladi ("halol avtonomiya: nima xato bo'lganini so'ra va urin")
- Auditda G-03 (MEDIUM) sifatida qayd qilingan

---

## 2. Fix uchun kerak bo'ladigan komponentlar

`RecoveryEngine.__init__` quyidagilarni kutadi:

| Parametr | Qayerdan olinadi | Muammo |
|---|---|---|
| `llm_provider: LLMProvider` | T1_FREE tier — ehtimol `_build_verifier_judge(router)` bilan bir xil | Ehtimol yangi provider factory `_build_recovery_llm(router)` kerak |
| `executor_factory: Callable[[], Executor]` | `Orchestrator._run_plan` ichida Executor per-run quriladi (executor.py:310) | **KRITIK:** Executor 12+ parametr bilan quriladi — factory shu 12tasini yopishi kerak. Orchestrator'ning `_run_plan`daga privat konstruksiya kodini takrorlash kerak yoki refactor qilish (Orchestrator method sifatida ochish) |
| `verifier: Verifier` | `orchestrator._verifier` (allaqachon bor) | Xavfsiz |
| `max_retries: int` | Default 2 (Settings'ga qo'shish maqsadga muvofiq) | Yangi Settings maydoni |
| `audit_fn: AuditFn` | `_default_audit` (allaqachon bor) | Xavfsiz |
| `tool_names: set[str]` | `tool_registry.tool_names()` | Xavfsiz |

**Circular dependency muammosi:** `RecoveryEngine` `Executor` factory'ini kutadi,
lekin `Executor` `Orchestrator._run_plan` ichida run_id/history/command_text bilan
quriladi — ya'ni recovery attempt'idagi executor ORIGINAL run_id bilan ishlashi
kerak. Factory closure bu ma'lumotlarni run boshlanganda olishi kerak, lekin
`RecoveryEngine` konstruksiyasi run boshlashdan oldin bo'ladi.

**Ehtimoliy yechim (spekulyatsiya):**
- Yo `Orchestrator.__init__`da `RecoveryEngine` shablonini qabul qilib, `_run_plan`
  boshida `executor_factory`ni `_make_executor(record)` bilan bog'lab uzatish
- Yo Orchestrator ichida ichki `_build_recovery_engine(record)` metod qo'shib,
  har run boshida yangi RecoveryEngine yaratish (per-run, xotira ozod)

Ikkinchisi tozaroq, chunki `RecoveryEngine` frozen holatga ega emas — arzon
qurilish. Lekin bu allaqachon MEDIUM'dan katta refactor.

---

## 3. Xavflar (biroz batafsil)

### Budjet portlashi

Maksimal narx bir run uchun:
- 1 verify FAIL → 2 recovery attempt
- Har attempt: 1 diagnose LLM chaqiruvi (max 600 output token, T1_FREE)
- Har attempt: 1-3 fix_step tool chaqiruvi (real tool cost)
- Har attempt: 1 re-verify (deterministic yoki LLM-judge, tier bo'yicha)

**Yomon holat:** T1_FREE bo'lmasa (masalan Anthropic Haiku), diagnose × 2 = ~$0.001,
fix_steps × 2 × 3 = 6 ta tool chaqiruvi (masalan har biri LLM-backed) = katta
o'zgaruvchan xarajat. `run_max_usd` qattiq chegara — lekin butun run
budjetdan ilk pass va recovery orasida taqsimlanadi, ega buni ko'rmaydi.

**Yumshatish:**
- Alohida `recovery_max_usd` Settings maydoni
- Yoki `budget_usd` ni recovery boshlagach 50%'ga tushirish
- Audit log'ga har attempt xarajatini yozish

### Approval bypass riski

`RecoveryEngine._parse_fix_steps` `permission_required` maydonini LLM'dan oladi
va default `READ` ga tushiradi. LLM taklif qilgan WRITE/EXECUTE qadamlar
`_extend_plan` orqali reja'ga qo'shilib, `approved` to'plamiga qo'shiladi
(`recovery.py:328`):

```python
new_positions = {...}
approved = approved | new_positions
```

**Muammo:** V-32 majburiy approval qoidasini recovery ATOMATIK CHETLAB O'TADI.
Agar LLM "hujjatni o'chir" degan fix taklif qilsa va uni WRITE deb yorliqlasa,
ega tasdig'isiz bajariladi.

**Yumshatish (KRITIK, ochiq gap):**
- Recovery fix_steps'ga faqat READ ruxsatiga ega qadamlar qo'shilishi kerak
- Yoki WRITE/EXECUTE bo'lsa approve talab qilinishi kerak (asl step approval'idan
  farqli — bu recovery, ega buni bilishi kerak)
- Buni test bilan yopish shart (regression: `test_recovery_never_bypasses_approval`)

Bu — G-03 fix'iga qo'shimcha, alohida ish. Fix'ni yopmasdan wire qilish esa
xavfsizlik gap ochish demakdir.

### Cheksiz tsikl himoyasi

`recovery.py:259` — `range(1, self._max_retries + 1)` qattiq chegara. Bu OK,
lekin agar RecoveryEngine muvaffaqiyat qaytarsa va Orchestrator TAG'IN
FAIL topsa (masalan ikkinchi qadam yiqilsa), yangi recovery attempt boshlanmaydi
(orchestrator.py:376-407 — bir marta recovery, keyin final status).

Xavfsiz.

---

## 4. Nima qilingani kerak (ega hal qilishi uchun)

Bosqichma-bosqich:

1. **Xavfsizlik gapini yopish** — `_parse_fix_steps` ichida WRITE/EXECUTE fix'lar
   uchun approval talab qilish (yoki READ'dan boshqa hech narsani qabul qilmaslik).
   Test: `test_recovery_never_bypasses_approval`.
2. **Executor factory naqshini tanlash** — Orchestrator per-run RecoveryEngine
   qurish yoki executor_factory closure bilan yashirin holat uzatish.
3. **`_build_recovery_llm(router)` qo'shish** — T1_FREE tier LLM provider factory
   (`_build_verifier_judge` naqshi).
4. **`get_orchestrator()` ni yangilash** — recovery_engine parametr uzatish.
5. **Integration test yozish** — verify FAIL → RECOVERING → DONE oqim
   (ilgari test_recovery.py'da bor, lekin real Orchestrator emas, mock bilan).
6. **Budjet audit** — `recovery.attempt` audit event'iga token_cost qo'shish.
7. **Settings maydoni** — `recovery_max_usd` (yoki `recovery_budget_ratio=0.5`).

**Effort:** ~1-2 kun ish (xavfsizlik gap tuzatish + factory refactor + testlar).
**Prioritet:** MEDIUM (auditda ham shu darajada). AR-01 bilan taqqoslaganda — kam
kritik, chunki hozir "verify FAIL → FAILED" halol yiqilish, faqat "urinib
ko'rilmadi" degan yashirin sekinlashuv.

**Alternativ:** avval BLOCK-3 (manual F1-F12 checklist) va Postgres Alembic
migration'lar (AR-01 to'liq yopish uchun) bajarish. G-03 keyingi sprint.

---

## 5. Nima QILINGANI YO'Q

- Kod o'zgartirilmadi (na `deps.py`, na `orchestrator.py`, na `recovery.py`)
- Yangi test qo'shilmadi
- Yangi commit yo'q
- Push yo'q

Bu hujjat faqat tekshiruv natijasi. Implementatsiya ega qarori bilan
boshlanishi kerak.
