# SCOPED FIX HISOBOTI — 4 punkt (2026-08-13)

Foydalanuvchi so'rovi: aynan quyidagi 4 blocker yopilsin, boshqa hech
narsaga tegilmasin. Har biri kod + test bilan tasdiqlangan.

---

## 1. Mission Orchestrator wire gap (mission_orchestrator.py:173)

**Muammo.** mypy quyidagini topgan:
```
apps/core/src/zet/core/mission_orchestrator.py:173: error:
    Item "CapabilityRegistry" of "_CapabilityRegistryLike | CapabilityRegistry"
    has no attribute "compose"  [union-attr]
```

**Sabab.** Type hint noto'g'ri edi: raw `CapabilityRegistry` faqat
`resolve()` metodini ochib beradi; `.compose()` `CapabilityRegistryComposer`
adapter'ida. Runtime'da `deps.py` allaqachon raw registry'ni
`CapabilityRegistryComposer` bilan o'raydi — ya'ni mypy noto'g'ri
xato beryapti edi (false-positive union yordamida), lekin type-safety
gap real edi.

**Yechim.**
- `mission_orchestrator.py` — `capability_registry` parametri uchun
  `CapabilityRegistry` uniondan olib tashlandi. Endi faqat
  `_CapabilityRegistryLike` (Protocol with `compose()`) qabul qilinadi.
- `TYPE_CHECKING` import ham tozalandi.

**Test.** `tests/test_mission_orchestrator.py::TestCapabilityInterfaceContract::test_registry_composer_provides_compose`
regression testi qo'shildi. mypy toza (`uv run mypy src/zet/core/mission_orchestrator.py`).

---

## 2. AR-01 (BLOCK-4) — Run/Approval DB persistence

**Muammo.** Restart/crash paytida quyidagilar yo'qolar edi:
- `RunStore._runs: dict` — barcha aktiv run holatlar
- `ApprovalService._requests: dict` — barcha pending tasdiqlar
- Ega approve URL'iga qayta kelsa 404 chiqar edi
- "Kecha boshlagan mission"ga qayta ulanib bo'lmasdi

Killswitch holati esa allaqachon persist qilinardi (V-33).

**Yechim (minimal, fail-open).**

Yangi modul: `apps/core/src/zet/core/run_checkpoint.py` (263 qator, 4 funksiya):
- `persist_run(factory, record, *, owner_external_id)` — UPSERT `run` jadvaliga
- `load_pending_runs(factory, store)` — startup'da AWAITING_APPROVAL run'lar
- `persist_approval(factory, request)` — UPSERT `approval` jadvaliga
- `load_pending_approvals(factory, service)` — muddati o'tmagan PENDING

Har biri `SQLAlchemyError` va umumiy `Exception`'ni ushlab, jimgina
`log.warning` yozadi — asosiy oqim to'xtamaydi (fail-open).

**Wire (haqiqiy ulanish, avvalgi commit'da faqat modul edi).**

`orchestrator.py` — `RunStore.__init__` optional `session_factory=` va
`owner_external_id=` oldi. `RunStore.persist(record)` async metod. Orchestrator
quyidagi joylarda avtomatik `await self._run_store.persist(record)` chaqiradi:
- `_start_impl` — intent/planner xato paytida (audit)
- `_run_plan` — AWAITING_APPROVAL (KRITIK checkpoint)
- `_run_plan` — BudgetExhausted (audit)
- `_run_plan` — terminal DONE/FAILED (audit)

`approvals.py` — `ApprovalService.__init__` optional `session_factory=`.
`_persist(req)` background task orqali (sync API'ni buzmaslik uchun).
`request_approval()`, `approve()`, `reject()` — har uchtasi persist chaqiradi.

`api/app.py` — startup lifespan quyidagini qo'shdi:
```python
restored_runs = await load_pending_runs(get_session_factory(), get_run_store())
restored_approvals = await load_pending_approvals(get_session_factory(),
                                                    get_approval_service())
```

`api/deps.py` — `get_run_store()` va `get_approval_service()` endi
`session_factory=get_session_factory()` bilan quriladi.

**Test (7 ta).**

`tests/test_run_checkpoint.py` — 6 ta modul-darajali:
1. `test_run_persist_then_load_restores_awaiting_approval`
2. `test_terminal_runs_not_restored` — DONE/FAILED tiklashga qarab bermaydi
3. `test_approval_persist_then_load_restores_pending`
4. `test_expired_approvals_not_restored` — TTL filter
5. `test_persist_is_idempotent` — ikki marta yozish = bitta qator
6. `test_fail_open_when_db_unreachable` — broken factory istisno tashlamaydi

`tests/test_pipeline_integration.py::TestOrchestratorAutoPersist` — 1 ta
end-to-end: `RunStore(session_factory=...)` bilan `POST /api/v1/run` chaqirilsa,
test HECH QANDAY `persist_run` chaqirmasdan ham DB'da row bo'lishini isbotlaydi.

**Cheklovlar (halol).**
- Approval `step_id` DB modeli UUID kutadi, domen esa `step_position: int` —
  restart'dan keyin `step_position` `None` bo'lib qoladi (approve/reject
  ishlaydi, qadam-daraja resume qisman yo'qoladi). Bu keyingi bosqichda
  DB schema o'zgartirilishi bilan hal qilinadi.
- Migration Alembic'siz avtomatik jadval yaratmaydi (test SQLite'da
  `Base.metadata.create_all` bilan ishlaydi; prod'da `alembic upgrade head`
  talab qilinadi).
- Postgres'da haqiqiy verifikatsiya qilinmadi — SQLite bilan sinash yetarli
  emas. F1-F12 manual checklist'da (§F) tekshirilishi kerak.

---

## 3. Real integration test — Mission → Task Graph → Approval → Recovery

**Muammo.** Auditga ko'ra:
> "Mission Engine → Task Graph → Approval Engine → Recovery Engine zanjiri
> birgalikda ishlaganda hech qanday test tomonidan tekshirilmagan."

**Yechim.** `tests/test_pipeline_integration.py` — 5 ta real integration
test yaratildi (`@pytest.mark.integration()`). Barchasi:
- Real `POST /api/v1/run` (starlette `TestClient`)
- Real `Orchestrator`, `Executor`, `Verifier`, `ApprovalService`, `RunStore`,
  `PermissionPolicy`, `KillSwitchState`
- Real `build_default_registry(notes_dir=tmp_path)` (haqiqiy note.write toolu)
- FAKE faqat LLM (`FakeProvider(name="ollama", scripted=[...])`)
- Sabab: real LLM narxi va deterministik reproduce; pipeline mantiqi
  tekshiriladi, model korrektligi emas.

**Testlar:**

1. `TestDAGParallelBatches::test_diamond_dag_executes_parallel_batch`
   — 3 qadam DAG: `time.now (0) → note.write("left") (1)`, `time.now (0) → note.write("right") (2)`.
   Kutish: `status=done`, `steps_done=3`, `tmp_path/left.md` va `tmp_path/right.md` yozilgan.
2. `TestApprovalRoundTrip::test_execute_step_blocks_then_approve_resumes`
   — POST /run → `awaiting_approval` → `POST /approvals/{id}/approve` →
   `run_status=done`. Cross-endpoint shared state.
3. `TestKillswitchBlocksRun::test_killswitch_blocks_new_run` — 503.
4. `TestRunPersistenceRoundTrip::test_awaiting_run_restored_after_restart`
   — POST /run → explicit persist → yangi bo'sh store → `load_pending_runs()` → run tiklangan.
5. `TestOrchestratorAutoPersist::test_awaiting_run_auto_persisted_by_orchestrator`
   — RunStore session_factory bilan → POST /run → DB'da row (orchestrator o'zi yozdi).

**Diagnostika (nima ushlab qoldi).**

Boshida 3 test ishlamadi. Sabab:
- `FakeProvider(name="fake", ...)` — ModelRouter'ning `simple` tier'i
  faqat real provayder ismlarini (ollama, google, groq, cohere, ...) chaqiradi;
  `"fake"` navbatga tushmaydi va "provayder topilmadi" xatosi qaytadi.
  **Yechim:** `name="ollama"` (test_api.py naqshi).
- `get_killswitch()` — `@lru_cache` singleton. Bir test global KS'ni engage
  qilsa, keyingi testlar 503 oladi.
  **Yechim:** `_client_with()` `get_killswitch` overrideni yo'q bo'lsa
  har testga toza `KillSwitchState()` beradi.

**Yakuniy natija:** `uv run pytest tests/test_pipeline_integration.py -v`
→ **5 passed in 1.70s**. Butun suite: **2524 passed in 106s** (avvalgi
2512 dan 12 ta yangi test).

---

## 4. Capability table — REAL / MOCK / PARTIAL

Har capability sub-agent tomonidan alohida audit qilindi. Verdict `file:line`
manbalari bilan.

| Capability | Tool | Verdict | Real endpoint | Fallback | Env var(s) |
|---|---|---|---|---|---|
| **Website (Web)** | `web.search` | **PARTIAL** | Brave Search API (`api.search.brave.com/res/v1/web/search`) via `httpx` — `web_search.py:109-139` | Silent 3-natija stub (source: "web.search (stub)") — `web_search.py:141-151` | `ZET_WEB_SEARCH_API_KEY` |
| | `web.read` | **REAL** | Manual redirect loop + SSRF validation — `web_reader.py:211-256` | Prod DI `stub=False` — konstruktorda `stub=True` default lekin `deps.py:247` uni yopib qo'yadi | Yo'q (network only) |
| **Instagram** | `instagram.account_stats` | **PARTIAL** | Meta Graph API v21.0 `GET /{ig-user-id}` — `instagram.py:187-190` | `_stub_account()` zeros bilan — `instagram.py:408-418` | `ZET_INSTAGRAM_ACCESS_TOKEN`, `ZET_INSTAGRAM_BUSINESS_ACCOUNT_ID` |
| | `instagram.recent_media` | **PARTIAL** | `GET /{ig-user-id}/media?fields=...` — `instagram.py:270-279` | `{media: [], source: "(stub)"}` — `instagram.py:263-268` | (yuqoridagilar) |
| | `instagram.publish_photo` | **PARTIAL** | 2-bosqichli real: `POST /{ig-user-id}/media` → `POST /media_publish` — `instagram.py:385-397` (WRITE + V-32 approval) | Stub `{posted: false}` — `instagram.py:376-382` | (yuqoridagilar) |
| **Telegram** | `telegram.channel_stats` | **PARTIAL** | `POST api.telegram.org/bot{token}/getChat` + `getChatMemberCount` — `telegram_tools.py:144-146` | Stub — `telegram_tools.py:339-349` | `ZET_TELEGRAM_BOT_TOKEN`, `ZET_TELEGRAM_OWNER_IDS` |
| | `telegram.channel_post` | **PARTIAL** | `POST .../sendMessage` HTML parse_mode — `telegram_tools.py:238-249` | Stub `posted=false` — `telegram_tools.py:230-236` | (yuqoridagilar) |
| | `telegram.delete_message` | **PARTIAL** | `POST .../deleteMessage` — `telegram_tools.py:330` | Stub — `telegram_tools.py:322-328` | (yuqoridagilar) |
| | Bot polling + inline approval | **REAL** | Custom `httpx` long-polling (aiogram YO'Q, faqat raw HTTP) — `polling.py:122`; V-32 inline ✅/❌ approve/reject butun oqim ishlaydi — `keyboards.py:40-97`, `polling.py:189-211`, `handlers.py:44-51` | Stub notifier/bot tokensiz — `notifier.py:130-153`, `bot.py:224-228` | (yuqoridagilar) |
| **GitHub** | `github.read` | **PARTIAL** | `api.github.com/repos/{repo}/issues|pulls|contents` via `httpx` — `github.py:193, 206, 219, 240` | Hardcoded fake issue/PR/file body (source: "(stub)") — `github.py:256-301` | `ZET_GITHUB_TOKEN` (PAT `repo` scope) |
| | `github.write` | **PARTIAL** | `POST .../pulls`, `.../issues/{n}/comments`, `.../issues` — `github.py:418, 435, 449` | Fake `number: 42`, `comment_id: 12345`, sinth html_url — `github.py:461-497` | (yuqoridagi) |
| **Obsidian** | `note.write` | **REAL** | `Path.write_text(...)` real disk yozuv, YAML frontmatter + `[[wikilink]]` qo'llab-quvvatlanadi, 100 KB cap — `note_write.py:165` | Yo'q — vault yo'q bo'lsa xato | `ZET_VAULT_DIR` (default: repo/vault) |
| | `note.read` | **REAL** | Disk read, frontmatter split, wikilink resolve — `note_read.py:93` | Yo'q | (yuqoridagi) |
| | `note.list` | **REAL** | `Path.rglob("*.md")`, hidden folder'lar skip qilinadi — `note_list.py:83`, `_vault.py:136` | Yo'q | (yuqoridagi) |
| | Obsidian ↔ Postgres bridge | **PARTIAL** | `note.write` → `PgMemoryStore.add(layer=KNOWLEDGE, ...)` shadow yozuv (fail-open) — `note_write.py:172-187` | Yo'q — one-way (Aris → Postgres) only. Obsidian'da qo'lda tahrirlangan notelar bridge'ga tushmaydi (no file watcher, no reverse sync) | (yuqoridagi) |

**Vault haqida kalitli haqiqat.** Aris "Obsidian vault"'ni maxsus API yoki
plugin bilan ishlatmaydi — bu shunchaki katalog. Agar `ZET_VAULT_DIR`
haqiqiy Obsidian vault'ga ko'rsatilsa (masalan `/home/user/Documents/MyVault`),
Aris va Obsidian bir xil fayllarni ko'radi — dialekt (Markdown + YAML +
`[[wikilink]]`) mos tushadi. Default `_REPO_ROOT/vault` esa toza katalog,
haqiqiy Obsidian vault emas.

**Umumiy naqsh:** barcha "PARTIAL" bir xil sxemani ishlatadi — token/ID bo'lsa
real API, bo'lmasa `source` maydonida `"(stub)"` yozuvi bilan zararsiz fake.
Bu chaqiruvchi (Executor/Verifier) uchun ochiq belgi — `if "stub" in source`
tekshiruvi bilan real vs fake ayirtirish mumkin.

---

## HIGH severity recount

**Avval (FINAL_READINESS_AUDIT.md §G-01/H-01/BLOCK-3/BLOCK-4):**

| ID | Muammo |
|---|---|
| G-01 (HIGH) | AR-01 Run/Approval DB persistence yo'q |
| H-01 (HIGH) | AR-01 durability gap (G-01 aksi) |
| BLOCK-3 (HIGH) | Manual verification checklist bajarilmagan |
| BLOCK-4 (HIGH) | AR-01 — restart'da run/approval yo'qoladi |

**Jami: 4 HIGH item.**

**Endi:**

| ID | Muammo | Yangi holat |
|---|---|---|
| G-01 | AR-01 Run/Approval DB persistence yo'q | **✅ HAL QILINDI** (`run_checkpoint.py` + orchestrator wiring + 7 test) |
| H-01 | AR-01 durability gap | **✅ HAL QILINDI** (aynan G-01 bilan bir xil root, birga yopildi) |
| BLOCK-4 | AR-01 — restart'da run/approval yo'qoladi | **✅ HAL QILINDI** — orchestrator avtomatik persist chaqiradi, startup restore ishlaydi |
| BLOCK-3 | Manual verification checklist (F1-F12) bajarilmagan | **🟡 QOLDI** — bu jonli tekshiruv talab qiladi (Telegram bot, backup/restore, mission full run), ega yoki DevOps tomonidan qo'lda o'tkazilishi kerak |

**Jami: 1 HIGH item qoldi (BLOCK-3).**

Bu HIGH item avtomatik yopilib bo'lmaydi — u aynan **eganing qo'lda
tekshirishini** talab qiladi (production Telegram token bilan bot polling,
Postgres backup/restore drill, mission full end-to-end run). Kod tayyor,
qolgan narsa — jonli sinash.

---

## Nima o'zgardi (fayllar)

**Yaratildi:**
- `apps/core/src/zet/core/run_checkpoint.py` (263 qator) — DB checkpoint modul
- `apps/core/tests/test_run_checkpoint.py` (6 test) — modul birligi
- `apps/core/tests/test_pipeline_integration.py` (5 test) — end-to-end
- `docs/SCOPED_FIX_REPORT.md` (bu hujjat)

**Modifikatsiyalandi:**
- `apps/core/src/zet/core/mission_orchestrator.py` — union type fix
- `apps/core/src/zet/core/orchestrator.py` — RunStore.persist() + wiring
- `apps/core/src/zet/security/approvals.py` — background persist + wiring
- `apps/core/src/zet/api/app.py` — startup restore
- `apps/core/src/zet/api/deps.py` — singleton'lar session_factory bilan
- `apps/core/tests/test_mission_orchestrator.py` — regression test

**Test hisobi:** 2512 → **2524 passed** (12 ta yangi, 0 ta regression).
`uv run pytest --tb=short` yashil.

**Boshqa hech narsaga tegilmadi.** Yangi feature yo'q, refactor yo'q,
mypy tozalash yo'q (H-05 LOW qoldi), yangi capability yo'q.
