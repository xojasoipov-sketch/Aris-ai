# BO'LIM 1 — Poydevor + Z Core (P0 + P1)

> Umumiy baho: **15–20 ish kuni (3–4 hafta)** · 18 ta task
> Bo'lim maqsadi: **buyruqni tushunadigan, reja tuzadigan, xavfli amalda to'xtab tasdiq
> so'raydigan, bajaradigan, natijani tekshiradigan va har bir qadamni xarajati bilan
> yozib qo'yadigan ishlaydigan yadro.**

## Bo'lim 1 Definition of Done

1. `z run "Ertaga 10:00 uchrashuv haqida eslatma yoz"` → to'liq sikl → natija + trace ID.
2. `z run "loyihadagi barcha fayllarni o'chir"` → `EXECUTE` daraja → **approval kutiladi**, avtomatik bajarilmaydi.
3. `GET /v1/runs/{id}` → intent, plan, har bir step, tool call, verification, token, USD, davomiylik.
4. `z stop --emergency` → barcha faol run'lar bir zumda to'xtaydi.
5. CI yashil: ruff + mypy(strict) + pytest (qamrov ≥ 70%) + gitleaks.
6. `docs/ARCHITECTURE.md` + 5 ta ADR yozilgan.

## Bog'liqlik grafi

```
Z1.0 ─┬─ Z1.1 ─ Z1.2 ─┬─ Z1.3 ─ Z1.4 ─┬─ Z1.6 ─┬─ Z1.7 ─ Z1.8 ─ Z1.9 ─ Z1.10 ─ Z1.11
      │               │               │        └─ Z1.12
      │               └─ Z1.5 ────────┘
      └─ Z1.16 (CI, erta) ─ Z1.13 ─ Z1.14 ─ Z1.15 ─ Z1.17
```

## Yakuniy papka strukturasi

```
apps/core/
├── src/zet/
│   ├── config.py            api/            db/
│   ├── main.py              cli.py          domain/
│   ├── core/  intent.py planner.py router.py executor.py verifier.py orchestrator.py
│   ├── llm/   base.py anthropic.py openai.py model_router.py
│   ├── tools/ base.py registry.py builtin/
│   ├── security/ permissions.py approvals.py killswitch.py
│   └── observability/ logging.py tracing.py cost.py
├── alembic/   tests/   pyproject.toml
infra/docker-compose.yml · .github/workflows/ci.yml · docs/
```

---

# TASKLAR

---

## Z1.0 — Repo skeleti, nomlash va konvensiyalar

**1. Nima qilinadi**
Monorepo strukturasi yaratiladi (`apps/core`, `apps/web`, `infra`, `docs`).
Loyiha `ZET`, package `zet`, CLI `z` deb rasmiylashtiriladi (F-03, F-05).
`.gitignore`, `LICENSE` (proprietary/private), `README.md`, `CONTRIBUTING.md`,
`CODEOWNERS`, PR/issue shablonlari qo'shiladi.
**F-02 hal qilinadi:** brend rang palitrasi bitta qilib qaror qilinadi va
`docs/adr/ADR-0005-design-tokens.md` da qayd etiladi.

**2. Fayllar**
`README.md` (yangilash) · `.gitignore` · `LICENSE` · `CONTRIBUTING.md` ·
`.github/CODEOWNERS` · `.github/PULL_REQUEST_TEMPLATE.md` ·
`.editorconfig` · `apps/core/` · `apps/web/.gitkeep` · `infra/.gitkeep` ·
`docs/adr/ADR-0005-design-tokens.md`

**3. Dependency** — yo'q

**4. Test** — `git status` toza; `tree -L 3` kutilgan strukturani beradi; README dagi
har bir yo'l mavjudligini tekshiruvchi kichik skript (`scripts/check_layout.sh`).

**5. Acceptance Criteria**
- [ ] Repoda "JARVIS" so'zi qolmagan (`grep -ri jarvis` → faqat tarixiy izohlarda)
- [ ] `.gitignore` da `.env`, `*.key`, `__pycache__`, `node_modules`, `.venv` bor
- [ ] ADR-0005 da bitta primary accent rang tanlangan va sabab yozilgan

**6. Risklar** — Repo nomini GitHub'da o'zgartirish eski URL'larni buzadi
(GitHub redirect beradi, lekin CI/secret sozlamalarini qayta tekshirish kerak).

**7. Vaqt** — 0.5 kun

---

## Z1.1 — Python toolchain va sifat darvozalari

**1. Nima qilinadi**
`uv` bilan paket boshqaruvi, `ruff` (lint+format), `mypy --strict`, `pytest`,
`pytest-asyncio`, `pytest-cov`, `pre-commit` (+`gitleaks`) sozlanadi.

**2. Fayllar**
`apps/core/pyproject.toml` · `apps/core/uv.lock` · `.pre-commit-config.yaml` ·
`apps/core/src/zet/__init__.py` · `apps/core/tests/__init__.py` · `Makefile`

**3. Dependency**
`python>=3.12`, `uv`, `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`,
`pre-commit`, `gitleaks`

**4. Test** — `make lint`, `make type`, `make test` — uchalasi ham 0 exit code;
`pre-commit run --all-files` toza; qasddan sir qo'yilgan test fayli `gitleaks` ni ishga tushiradi.

**5. Acceptance Criteria**
- [ ] `mypy --strict` `src/` da 0 xato
- [ ] `ruff check` va `ruff format --check` toza
- [ ] pre-commit hook lokal commitda avtomatik ishlaydi
- [ ] `make` bitta buyruq bilan hamma darvozani yuritadi

**6. Risklar** — `mypy --strict` boshidan qattiq; keyinroq yumshatish qiyin bo'lgani uchun
**hozir** qattiq qo'yiladi (R-08 ga qarshi eng arzon investitsiya).

**7. Vaqt** — 0.5 kun

---

## Z1.2 — Konfiguratsiya va sirlar

**1. Nima qilinadi**
`pydantic-settings` asosida qatlamli konfiguratsiya: default → `.env` → environment.
Barcha sirlar (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_URL`,
`LANGFUSE_*`, `OWNER_ID`) tipiklashtirilgan `Settings` obyektida.
Ishga tushishda validatsiya: yetishmayotgan sir → aniq xato bilan to'xtaydi.
`.env.example` yoziladi (haqiqiy qiymatsiz).

**2. Fayllar**
`apps/core/src/zet/config.py` · `apps/core/.env.example` · `apps/core/tests/test_config.py`

**3. Dependency** — `pydantic-settings`

**4. Test** — birlik testlar: to'liq env → yuklanadi; sir yo'q → `ValidationError`;
`SecretStr` `repr()` da qiymat ko'rinmaydi.

**5. Acceptance Criteria**
- [ ] Barcha sirlar `SecretStr` tipida
- [ ] `.env.example` da har bir kalit izoh bilan
- [ ] Log'da hech qachon sir chop etilmaydi (test bilan isbotlangan)
- [ ] `ZET_ENV` = `dev|test|prod` qiymatlari qo'llab-quvvatlanadi

**6. Risklar** — R-11 (sir repoga tushishi). `.env` `.gitignore` da + gitleaks CI da.

**7. Vaqt** — 0.5 kun

---

## Z1.3 — Docker dev muhiti

**1. Nima qilinadi**
`docker compose up` bilan to'liq lokal muhit: PostgreSQL 16 (`pgvector` bilan),
Redis 7, Langfuse (self-hosted), `core` xizmati (hot-reload).
Healthcheck'lar va `depends_on: condition: service_healthy`.

**2. Fayllar**
`infra/docker-compose.yml` · `infra/postgres/init.sql` (pgvector extension) ·
`apps/core/Dockerfile` · `apps/core/.dockerignore` · `Makefile` (up/down/logs/psql)

**3. Dependency** — Docker ≥ 24, Docker Compose v2, `pgvector/pgvector:pg16`,
`redis:7-alpine`, `langfuse/langfuse:latest`

**4. Test** — `make up` → 4 konteyner `healthy`; `make psql -c "SELECT 1"` ishlaydi;
`SELECT * FROM pg_extension WHERE extname='vector'` qator qaytaradi;
`curl localhost:3000` (Langfuse) 200.

**5. Acceptance Criteria**
- [ ] Toza mashinada `git clone && cp .env.example .env && make up` → 5 daqiqada ishlaydi
- [ ] Ma'lumotlar named volume'da saqlanadi (restart'da yo'qolmaydi)
- [ ] Konteynerlar `root` bo'lmagan foydalanuvchi ostida ishlaydi

**6. Risklar** — Langfuse resurs talab qiladi; kuchsiz mashinada uni ixtiyoriy profil
(`--profile obs`) ga chiqarish.

**7. Vaqt** — 1 kun

---

## Z1.4 — Ma'lumotlar bazasi poydevori va yadro sxemasi

**1. Nima qilinadi**
SQLAlchemy 2.0 async engine + session factory + Alembic. **A-01** ga muvofiq
davomli holat mashinasi jadvallarini yaratish.

Yadro jadvallari:
| Jadval | Maqsad |
|---|---|
| `owner` | yagona ega, ruxsat darajasi |
| `session` | suhbat sessiyasi |
| `message` | kirish/chiqish xabarlari |
| `run` | bitta buyruq sikli; `status`, `depth`, `budget_usd`, `trace_id` |
| `plan` / `step` | reja va qadamlar; `status`, `permission_required` |
| `tool_call` | chaqiruv: input, output, `trust_level`, latency, xato |
| `approval` | so'rov, sabab, holat, kim/qachon tasdiqladi |
| `audit_log` | append-only; har bir imtiyozli amal |
| `cost_ledger` | `(run_id, model, task_class, in_tok, out_tok, usd, latency_ms, verified_ok)` |
| `kill_switch` | global emergency stop holati |

**2. Fayllar**
`src/zet/db/base.py` · `src/zet/db/session.py` · `src/zet/db/models/*.py` ·
`src/zet/db/repositories/*.py` · `alembic.ini` · `alembic/env.py` ·
`alembic/versions/0001_core_schema.py` · `tests/test_db_schema.py` · `tests/conftest.py`

**3. Dependency** — `sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic`, `pgvector`,
`pytest-postgresql` yoki `testcontainers`

**4. Test**
- `alembic upgrade head` → `downgrade base` → `upgrade head` xatosiz
- Har bir repository uchun CRUD testi (izolyatsiyalangan tranzaksiyada)
- `audit_log` ga `UPDATE`/`DELETE` urinishi DB darajasida rad etiladi (rule/trigger)
- `run.status` uchun noto'g'ri o'tish (`DONE → PLANNING`) rad etiladi

**5. Acceptance Criteria**
- [ ] Migratsiya ikki tomonlama ishlaydi
- [ ] Barcha FK, index, `CHECK` constraintlar mavjud
- [ ] `audit_log` amalda append-only
- [ ] Vaqt maydonlari `timestamptz`, UTC

**6. Risklar** — Sxemani keyin o'zgartirish qimmat. Shuning uchun `run/step/tool_call`
uchun `metadata JSONB` maydoni qoldiriladi (kelajakdagi kengaytmalar migratsiyasiz).

**7. Vaqt** — 2 kun

---

## Z1.5 — LLM provayder abstraksiyasi + Model Router v1

**1. Nima qilinadi**
`LLMProvider` protokoli: `complete()`, `stream()`, `count_tokens()`, native tool-calling.
Implementatsiyalar: `AnthropicProvider` (asosiy), `OpenAIProvider` (fallback),
`FakeProvider` (testlar uchun, deterministik).
**Model Router v1 (V-29):** `task_class → model` jadvali + narx katalogi + fallback
zanjiri + retry/circuit breaker. Har bir chaqiruv `cost_ledger` ga yoziladi (**A-04**).

`task_class`: `simple` · `normal` · `complex` · `coding` · `vision` · `speech`

**2. Fayllar**
`src/zet/llm/base.py` · `anthropic.py` · `openai.py` · `fake.py` ·
`model_router.py` · `pricing.py` · `tests/test_model_router.py` · `tests/test_llm_*.py`

**3. Dependency** — `anthropic`, `openai`, `tenacity`, `httpx`

**4. Test**
- `FakeProvider` bilan router jadvali testlari (har bir task_class → kutilgan model)
- Asosiy provayder 429/5xx → fallbackga o'tadi (mock transport)
- Xarajat hisobi: ma'lum token soni → kutilgan USD (±0.0001)
- Circuit breaker: 5 ketma-ket xato → ochiladi, `cooldown` dan keyin yopiladi
- Integratsiya testi (ixtiyoriy marker `@pytest.mark.live`) — real API bilan 1 chaqiruv

**5. Acceptance Criteria**
- [ ] Provayderni almashtirish faqat konfiguratsiya orqali (R-06)
- [ ] Har bir chaqiruvdan keyin `cost_ledger` da yozuv bor
- [ ] Kunlik budjet limitiga yetganda chaqiruv `BudgetExceeded` bilan rad etiladi (R-02)
- [ ] Streaming ishlaydi va bo'lak-bo'lak token hisobi to'g'ri

**6. Risklar** — Narx katalogi eskiradi → `pricing.py` da sana va manba izohi;
CI da oyda bir eslatma issue.

**7. Vaqt** — 2 kun

---

## Z1.6 — Domen kontraktlari (Pydantic)

**1. Nima qilinadi**
Yadro tiplari bitta joyda, immutable Pydantic modellar sifatida:
`Command`, `Intent`, `Plan`, `Step`, `ToolSpec`, `ToolCall`, `ToolResult`,
`Verification`, `RunState`, `PermissionLevel`, `TrustLevel`, `TaskClass`, `Budget`.
`TrustLevel` (**A-05**): `OWNER` · `SYSTEM` · `UNTRUSTED`.
`PermissionLevel` (V-31): `READ` · `WRITE` · `EXECUTE` · `ADMIN`.

**2. Fayllar**
`src/zet/domain/__init__.py` · `command.py` · `plan.py` · `tool.py` ·
`security.py` · `run.py` · `tests/test_domain.py`

**3. Dependency** — `pydantic>=2.7`

**4. Test** — noto'g'ri o'tish/qiymat `ValidationError` beradi; JSON serializatsiya
round-trip; `frozen=True` mutatsiyani bloklaydi; enum tartibi (`READ < WRITE < EXECUTE < ADMIN`) taqqoslanadi.

**5. Acceptance Criteria**
- [ ] Barcha modellar `frozen=True`
- [ ] Har bir model DB modeliga `to_db()/from_db()` bilan bog'lanadi
- [ ] `PermissionLevel` taqqoslanuvchi (`>=` ishlaydi)

**6. Risklar** — Domen va DB modellarining ikkilanishi. Qabul qilinadi: domen toza qoladi,
DB sxemasi mustaqil evolyutsiya qiladi.

**7. Vaqt** — 1 kun

---

## Z1.7 — Intent Recognizer

**1. Nima qilinadi**
Kirish matnini strukturalangan `Intent` ga aylantirish:
`{action, objects[], constraints[], urgency, task_class, requires_tools, ambiguity}`.
Noaniqlik yuqori bo'lsa → aniqlashtiruvchi savol qaytariladi (bajarishga o'tmaydi).
`task_class` shu yerda aniqlanadi va Model Router'ga uzatiladi.

**2. Fayllar**
`src/zet/core/intent.py` · `src/zet/prompts/intent.md` ·
`tests/test_intent.py` · `tests/fixtures/intents.yaml` (30+ misol, o'zbek va ingliz tilida)

**3. Dependency** — Z1.5, Z1.6

**4. Test**
- Fixture asosidagi eval: 30+ buyruq → kutilgan `action` va `task_class` (≥ 90% aniqlik)
- `FakeProvider` bilan deterministik birlik testlar
- Noaniq buyruq ("uni tuzat") → `ambiguity=high` + savol
- Prompt injection namunalari ("oldingi ko'rsatmalarni unut") → intent buzilmaydi

**5. Acceptance Criteria**
- [ ] O'zbek va ingliz tilidagi buyruqlar bir xil ishlaydi
- [ ] Eval to'plamida ≥ 90%
- [ ] Chiqish har doim valid `Intent` (LLM buzilsa — retry, keyin aniq xato)

**6. Risklar** — LLM chiqishi nostabil → `response_format`/tool-call orqali majburiy sxema.

**7. Vaqt** — 1.5 kun

---

## Z1.8 — Planner

**1. Nima qilinadi**
`Intent` → `Plan` (tartiblangan `Step[]`). Har bir qadamda:
`description, tool_name?, agent?, permission_required, expected_outcome, depends_on[]`.
Reja **executable** bo'lishi shart: faqat registry'da mavjud toollar.
`complex` sinf uchun `complex` model ishlatiladi (Model Router orqali).
Reja limitlari (**A-07**): `max_steps`, `max_depth`, `max_budget_usd`.

**2. Fayllar**
`src/zet/core/planner.py` · `src/zet/prompts/planner.md` ·
`tests/test_planner.py` · `tests/fixtures/plans.yaml`

**3. Dependency** — Z1.7, Z1.6, Z1.10 (ToolRegistry interfeysi)

**4. Test**
- Mavjud bo'lmagan tool nomi → reja rad etiladi va qayta so'raladi (max 2 marta)
- `depends_on` sikl → `PlanValidationError`
- `max_steps` oshib ketsa → rad etiladi
- Golden testlar: 10 ta tipik buyruq → kutilgan qadamlar shakli

**5. Acceptance Criteria**
- [ ] Har bir qadamda `permission_required` to'ldirilgan
- [ ] Reja DAG (siklsiz) ekanligi tekshiriladi
- [ ] Reja bazaga to'liq saqlanadi (`plan` + `step` jadvallari)
- [ ] Rejani bajarishdan oldin foydalanuvchiga ko'rsatish mumkin (`--dry-run`)

**6. Risklar** — LLM "xayoliy" tool o'ylab topadi → validatsiya + repair halqasi (2 urinish),
keyin insonga eskalatsiya.

**7. Vaqt** — 2 kun

---

## Z1.9 — Agent Router v0 (stub)

**1. Nima qilinadi**
Marshrutlash interfeysi va `general` agentga yo'naltiruvchi minimal implementatsiya.
To'liq agent runtime — **Bo'lim 3**. Bu yerda faqat **chegara** to'g'ri qo'yiladi,
keyin interfeys o'zgarmasin.

**2. Fayllar**
`src/zet/core/router.py` · `src/zet/agents/general.py` · `tests/test_router.py`

**3. Dependency** — Z1.6, Z1.8

**4. Test** — har qanday `Step` → `general` agent; noma'lum agent so'ralsa → aniq xato;
interfeys kontrakti testi (kelajakdagi agentlar shu protokolga mos kelishi uchun).

**5. Acceptance Criteria**
- [ ] `AgentRouter` protokoli hujjatlashtirilgan
- [ ] Bo'lim 3 da faqat implementatsiya qo'shiladi, interfeys o'zgarmaydi
- [ ] `ADR-0003-agent-as-data.md` yozilgan (**A-02**)

**6. Risklar** — Stub'ni "vaqtinchalik" deb qoldirib ketish. Oldini olish:
`TODO(Bo'lim-3)` markerlari + CI da marker inventarizatsiyasi.

**7. Vaqt** — 0.5 kun

---

## Z1.10 — Tool interfeysi, registry va 3 ta built-in tool

**1. Nima qilinadi**
`Tool` bazaviy interfeysi: `name`, `description`, `input_schema` (JSON Schema),
`permission_level`, `output_trust_level`, `idempotent`, `timeout_s`, `execute()`.
`ToolRegistry`: ro'yxatga olish, qidirish, allowlist, JSON Schema validatsiyasi,
timeout, rate limit, `dry_run`.

Bo'lim 1 uchun 3 ta xavfsiz tool:
| Tool | Ruxsat | Trust | Maqsad |
|---|---|---|---|
| `time.now` | READ | SYSTEM | vaqt/vaqt mintaqasi |
| `note.write` | WRITE | SYSTEM | lokal markdown eslatma (Bo'lim 2 da Obsidian'ga ulanadi) |
| `shell.exec` | **EXECUTE** | SYSTEM | allowlist'dagi buyruqlar — approval gate'ni sinash uchun |

**2. Fayllar**
`src/zet/tools/base.py` · `registry.py` · `builtin/time_now.py` ·
`builtin/note_write.py` · `builtin/shell_exec.py` · `tests/test_tools_*.py`

**3. Dependency** — Z1.6, Z1.4

**4. Test**
- Sxemaga mos kelmaydigan input → chaqiruvgacha rad etiladi
- `timeout_s` oshsa → `ToolTimeout`, `tool_call` da qayd etiladi
- `shell.exec` allowlist'dan tashqari buyruq → `PermissionDenied`
- `note.write` path traversal (`../../etc/passwd`) → rad etiladi
- `dry_run=True` da hech qanday nojo'ya ta'sir yo'q

**5. Acceptance Criteria**
- [ ] Har bir tool chaqiruvi `tool_call` jadvaliga yoziladi (input/output/trust/latency)
- [ ] Registry allowlist'siz tool ishga tushmaydi
- [ ] `shell.exec` default holatda **o'chirilgan** (`ZET_ENABLE_SHELL=false`)

**6. Risklar** — 🔴 `shell.exec` eng xavfli komponent. Yumshatish: default off,
qattiq allowlist, argument sanitizatsiyasi, majburiy approval, audit, timeout.

**7. Vaqt** — 2 kun

---

## Z1.11 — Executor va Verifier

**1. Nima qilinadi**
**Executor:** rejani DAG tartibida bajaradi; har bir qadamda ruxsat tekshiradi,
kerak bo'lsa approval kutadi, toolni chaqiradi, natijani saqlaydi, xatolikda
`retry` (eksponensial) yoki `FAILED`. `run.status` bazada yangilanadi (**A-01**),
shuning uchun protsess qayta ishga tushsa ish davom etadi.

**Verifier (V-01 ning "Verification" qismi):** natija `expected_outcome` ga
mos kelganini tekshiradi. Uch xil verifikator: `deterministic` (schema/regex/exit code),
`tool-based` (masalan, fayl yozildimi), `llm-judge` (faqat oxirgi chora, arzon model).
Natija: `verified_ok: bool` + sabab → `cost_ledger` va hisobotga.

**2. Fayllar**
`src/zet/core/executor.py` · `verifier.py` · `orchestrator.py` ·
`tests/test_executor.py` · `tests/test_verifier.py` · `tests/test_resume.py`

**3. Dependency** — Z1.8, Z1.10, Z1.12, Z1.4

**4. Test**
- To'liq happy-path: buyruq → natija (FakeProvider bilan, tarmoqsiz)
- Qadam o'rtasida protsess "o'ldiriladi" → qayta ishga tushirilganda **davom etadi**
- Tool 2 marta xato → 3-urinishda muvaffaqiyat (retry siyosati)
- `verified_ok=False` → run `FAILED`, sabab yozilgan
- `max_depth`/`budget` oshsa → to'xtaydi (**A-07**, R-02)

**5. Acceptance Criteria**
- [ ] Resume testi o'tadi (holat DB da, xotirada emas)
- [ ] Har bir run oxirida `verified_ok` va `total_usd` mavjud
- [ ] Parallel bajarilishi mumkin bo'lgan qadamlar parallel ishlaydi (`depends_on` bo'yicha)

**6. Risklar** — Retry idempotent bo'lmagan toolda ikki marta yozadi.
Yumshatish: `tool.idempotent` bayrog'i; idempotent bo'lmasa retry qilinmaydi,
`idempotency_key` talab qilinadi.

**7. Vaqt** — 2.5 kun

---

## Z1.12 — Ruxsat modeli, Approval Gate va Emergency Stop

**1. Nima qilinadi**
V-31/V-32/V-33 ning yadrosi:
- `PermissionPolicy`: qaysi daraja avtomatik, qaysi biri tasdiq talab qiladi
  (default: `READ` avtomatik; `WRITE` sozlanadigan; `EXECUTE` va `ADMIN` — **har doim tasdiq**)
- Yuqori xavfli amallar ro'yxati (V-32) qattiq kodlangan va **hech qachon** avtomatik emas
- `ApprovalService`: so'rov yaratadi, run'ni `AWAITING_APPROVAL` ga qo'yadi,
  javob kelguncha kutadi (TTL bilan, default 30 daqiqa → `EXPIRED`)
- **A-05:** `UNTRUSTED` kontekstdan kelib chiqqan qadam avtomatik bajarilmaydi
- `KillSwitch`: `z stop --emergency` → global bayroq → barcha faol run to'xtaydi,
  yangi run boshlanmaydi; `z resume` bilan qaytariladi
- Har bir qaror `audit_log` ga

**2. Fayllar**
`src/zet/security/permissions.py` · `approvals.py` · `killswitch.py` ·
`policy.yaml` · `tests/test_permissions.py` · `test_approvals.py` · `test_killswitch.py`

**3. Dependency** — Z1.4, Z1.6

**4. Test**
- `READ` tool → tasdiqsiz o'tadi
- `EXECUTE` tool → `AWAITING_APPROVAL`, tasdiqsiz **hech qachon** bajarilmaydi
- Tasdiq TTL tugadi → `EXPIRED`, run `CANCELLED`
- `UNTRUSTED` manbadan kelgan `WRITE` qadam → majburiy tasdiq
- Emergency stop → 1 soniya ichida barcha faol run `CANCELLED`
- Har bir holat uchun `audit_log` yozuvi mavjud

**5. Acceptance Criteria**
- [ ] Tasdiqni chetlab o'tadigan yo'l yo'q (kod-review + testlar bilan isbot)
- [ ] `policy.yaml` o'zgarishi `audit_log` ga tushadi
- [ ] Emergency stop restart'dan keyin ham kuchda qoladi (DB da saqlanadi)

**6. Risklar** — 🔴 Bu — tizimning eng muhim xavfsizlik komponenti (R-01, R-05).
Yumshatish: fail-closed dizayn (shubha bo'lsa — rad etiladi), 100% test qamrovi shu modulda.

**7. Vaqt** — 2 kun

---

## Z1.13 — Observability: log, trace, xarajat

**1. Nima qilinadi**
V-34 ni to'liq bajarish: `structlog` bilan JSON strukturalangan log,
har bir run uchun `trace_id` (context var orqali barcha loglarga tarqaladi),
Langfuse integratsiyasi (LLM chaqiruvlari, promptlar, tokenlar, xarajat),
`cost_ledger` agregatlari (kunlik/oylik, model bo'yicha, task_class bo'yicha),
budjet alertlari (R-02).

**2. Fayllar**
`src/zet/observability/logging.py` · `tracing.py` · `cost.py` ·
`src/zet/api/routers/observability.py` · `tests/test_observability.py`

**3. Dependency** — `structlog`, `langfuse`, `opentelemetry-api` (ixtiyoriy)

**4. Test**
- Bitta run → barcha loglarda bir xil `trace_id`
- Log'da sir yo'q (`SecretStr` maskalash testi)
- `GET /v1/costs?period=today` to'g'ri yig'indi beradi
- Kunlik limit 80% ga yetganda alert hodisasi chiqadi

**5. Acceptance Criteria**
- [ ] `GET /v1/runs/{id}/trace` to'liq zanjirni qaytaradi:
      `USER → INTENT → PLAN → STEP → TOOL → RESULT → VERIFICATION → COST/DURATION`
- [ ] Langfuse UI da har bir LLM chaqiruvi ko'rinadi
- [ ] Xarajat hisoboti model va task_class kesimida

**6. Risklar** — Langfuse ishlamay qolsa asosiy oqim to'xtamasligi kerak →
tracing "best-effort", xatosi yutiladi va log qilinadi.

**7. Vaqt** — 1.5 kun

---

## Z1.14 — HTTP API (FastAPI + SSE)

**1. Nima qilinadi**
Yadro API yuzasi:
| Endpoint | Vazifa |
|---|---|
| `POST /v1/commands` | buyruq yuborish → `run_id` |
| `GET /v1/runs/{id}` | run holati va to'liq tafsiloti |
| `GET /v1/runs/{id}/stream` | SSE: real vaqtda qadamlar oqimi |
| `GET /v1/runs/{id}/trace` | to'liq iz |
| `GET /v1/approvals` · `POST /v1/approvals/{id}` | tasdiq ro'yxati / qaror |
| `POST /v1/emergency-stop` · `POST /v1/resume` | kill switch |
| `GET /v1/costs` | xarajat hisoboti |
| `GET /healthz` · `GET /readyz` | sog'liq |

Auth: Bo'lim 1 da oddiy **bearer token** (bitta ega) — WebAuthn Bo'lim 11 da.
Rate limit, request id, global exception handler, OpenAPI hujjati.

**2. Fayllar**
`src/zet/main.py` · `src/zet/api/deps.py` · `api/routers/{commands,runs,approvals,system,costs}.py` ·
`api/errors.py` · `tests/test_api_*.py`

**3. Dependency** — `fastapi`, `uvicorn`, `sse-starlette`, `slowapi`

**4. Test**
- Har bir endpoint uchun kontrakt testi (`httpx.AsyncClient`)
- Tokensiz so'rov → 401; noto'g'ri token → 401
- SSE oqimi qadamlarni tartib bilan yetkazadi
- Xato javoblari yagona formatda (`{error: {code, message, trace_id}}`)
- OpenAPI sxemasi generatsiya bo'ladi va valid

**5. Acceptance Criteria**
- [ ] `/docs` da to'liq OpenAPI
- [ ] Barcha javoblarda `trace_id` bor
- [ ] Rate limit ishlaydi (429)
- [ ] Hech bir endpoint sirni qaytarmaydi

**6. Risklar** — Bearer token zaif auth. Qabul qilinadi: Bo'lim 1 lokal muhitda;
internetga chiqarishdan oldin Bo'lim 11 majburiy.

**7. Vaqt** — 1.5 kun

---

## Z1.15 — `z` CLI

**1. Nima qilinadi**
Kundalik ishlatish uchun CLI:
```
z run "<buyruq>"        # sikl, jonli oqim bilan
z run --dry-run "<...>" # faqat rejani ko'rsat
z runs list | show <id> | trace <id>
z approve <id> | reject <id> [--reason]
z stop --emergency | z resume
z cost today | month
z doctor                # muhit va konfiguratsiya diagnostikasi
```

**2. Fayllar**
`src/zet/cli.py` · `src/zet/cli_render.py` · `tests/test_cli.py` ·
`pyproject.toml` (`[project.scripts] z = "zet.cli:app"`)

**3. Dependency** — `typer`, `rich`

**4. Test** — `typer.testing.CliRunner` bilan har bir buyruq; `z doctor` yetishmayotgan
konfiguratsiyani aniqlaydi; exit code'lar to'g'ri (0/1/2).

**5. Acceptance Criteria**
- [ ] `z run` jonli qadamlarni ko'rsatadi (spinner + qadam nomi)
- [ ] Tasdiq so'ralganda CLI kutadi va interaktiv so'raydi
- [ ] `z doctor` 8 ta tekshiruvni bajaradi (DB, Redis, API kalitlar, migratsiya, disk, kill switch, budjet, versiya)

**6. Risklar** — Past. CLI — Bo'lim 5 gacha asosiy interfeys.

**7. Vaqt** — 1 kun

---

## Z1.16 — Test infratuzilmasi va CI

**1. Nima qilinadi**
`pytest` konfiguratsiyasi: `unit` / `integration` / `live` markerlari,
`testcontainers` bilan izolyatsiyalangan Postgres, umumiy fixture'lar
(`FakeProvider`, `owner`, `session`, `clean_db`), qamrov chegarasi.
GitHub Actions: `lint → type → test → coverage → gitleaks → docker build`.
`main` branch himoyasi (F-04).

**2. Fayllar**
`apps/core/tests/conftest.py` · `tests/factories.py` · `pytest.ini` (yoki pyproject) ·
`.github/workflows/ci.yml` · `.github/dependabot.yml`

**3. Dependency** — `testcontainers[postgres]`, `pytest-cov`, `freezegun`, `respx`

**4. Test** — CI o'zini o'zi sinaydi: qasddan buzilgan PR (lint xatosi, tip xatosi,
sinmagan test, sir) — har biri CI ni qizartirishi kerak.

**5. Acceptance Criteria**
- [ ] CI < 6 daqiqa
- [ ] Qamrov ≥ 70% umumiy, `security/` modulida 100%
- [ ] `main` ga to'g'ridan-to'g'ri push bloklangan; PR + yashil CI majburiy
- [ ] `live` testlar default o'chirilgan (API xarajat qilmasin)

**6. Risklar** — Sekin CI odamni chetlab o'tishga majburlaydi → parallel job'lar + kesh.

**7. Vaqt** — 1 kun

---

## Z1.17 — Arxitektura hujjati va ADR'lar

**1. Nima qilinadi**
**F-01 ni yopish.** Yozma texnik arxitektura yaratiladi:
kontekst diagrammasi, komponentlar, ma'lumot oqimi, DB sxemasi (ER),
holat mashinasi diagrammasi, xavfsizlik modeli, kengaytirish nuqtalari.
Va 5 ta ADR:

| ADR | Qaror |
|---|---|
| 0001 | Tech stack (Python/FastAPI/Postgres/Redis) |
| 0002 | Framework emas, o'z orkestratori |
| 0003 | Agent = ma'lumot, kod emas (**A-02**) |
| 0004 | Untrusted input chegarasi (**A-05**) |
| 0005 | Design token'lar / brend rang (**F-02**) |

Shuningdek `SECURITY.md`, `RUNBOOK.md` (emergency stop, restore),
`docs/PHASE-1-REPORT.md`.

**2. Fayllar**
`docs/ARCHITECTURE.md` · `docs/adr/ADR-000{1..5}-*.md` ·
`docs/SECURITY.md` · `docs/RUNBOOK.md` · `docs/PHASE-1-REPORT.md` · `README.md` (yangilash)

**3. Dependency** — Z1.0–Z1.16 (haqiqiy holatni aks ettirishi uchun oxirida)

**4. Test** — Hujjatdagi har bir kod yo'li mavjudligini tekshiruvchi skript
(`scripts/check_docs_links.py`) CI da; Mermaid diagrammalar render bo'ladi.

**5. Acceptance Criteria**
- [ ] Yangi ishlab chiquvchi faqat `ARCHITECTURE.md` o'qib tizimni tushuna oladi
- [ ] Har bir muhim qaror ADR bilan asoslangan
- [ ] `RUNBOOK.md` da emergency stop va backup restore qadamma-qadam
- [ ] Barcha hujjat havolalari ishlaydi (CI tekshiradi)

**6. Risklar** — Hujjat kod bilan eskiradi → CI havola tekshiruvi + har bo'lim oxirida
hujjatni yangilash DoD ning bir qismi (V-45).

**7. Vaqt** — 1 kun

---

# Bo'lim 1 xulosasi

| Guruh | Tasklar | Kun |
|---|---|---|
| Poydevor | Z1.0 – Z1.3 | 2.5 |
| Ma'lumot + LLM | Z1.4 – Z1.6 | 5 |
| Yadro pipeline | Z1.7 – Z1.11 | 8.5 |
| Xavfsizlik + kuzatuv | Z1.12 – Z1.13 | 3.5 |
| Interfeys | Z1.14 – Z1.15 | 2.5 |
| Sifat + hujjat | Z1.16 – Z1.17 | 2 |
| **Jami** | **18 task** | **≈ 24 kun (buffer bilan 3–4 hafta)** |

## Bo'lim 1 dan keyin nima BOR va nima YO'Q

**Bor:** ishlaydigan yadro, ruxsat va tasdiq, to'liq iz va xarajat hisobi,
3 ta tool, CLI va API, testlar va CI, yozma arxitektura.

**Yo'q (ataylab):** xotira (Bo'lim 2), haqiqiy agentlar (Bo'lim 3),
Agent Factory (4), Telegram (5), qurilmalar/kamera (8),
avtomatlashtirish (9), dashboard (10).
