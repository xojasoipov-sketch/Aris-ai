# ZET — Arxitektura

> Shaxsiy AI operatsion tizim. Bitta ega, SaaS emas.

## Umumiy ko'rinish

```
┌──────────────────────────────────────────────────────────────┐
│                        FOYDALANUVCHI                         │
│                   CLI (z) · API · (Web — Bo'lim 10)          │
└──────────┬───────────────────────────────────────┬───────────┘
           │                                       │
     ┌─────▼─────┐                           ┌─────▼─────┐
     │  FastAPI   │                           │  z CLI    │
     │  REST API  │                           │  (typer)  │
     └─────┬──────┘                           └─────┬─────┘
           │                                        │
     ┌─────▼────────────────────────────────────────▼─────┐
     │                   CORE PIPELINE                     │
     │  Command → Intent → Plan → Approval → Execute →    │
     │                              Verify → Result        │
     └──┬──────┬───────┬────────┬───────┬───────┬─────────┘
        │      │       │        │       │       │
   ┌────▼──┐ ┌─▼───┐ ┌▼────┐ ┌─▼───┐ ┌▼────┐ ┌▼─────────┐
   │Intent │ │Plan │ │Appr.│ │Exec.│ │Veri.│ │Observa-  │
   │Recog. │ │ner  │ │Svc  │ │utor │ │fier │ │bility    │
   └───┬───┘ └──┬──┘ └──┬──┘ └──┬──┘ └─────┘ │trace/cost│
       │        │       │       │              └──────────┘
   ┌───▼────────▼───┐ ┌─▼───┐ ┌▼──────────┐
   │  LLM Router    │ │Perm.│ │ToolRegistry│
   │  T0→T1→T2→T3   │ │Pol. │ │  + Tools   │
   └───┬──┬──┬──┬───┘ └─────┘ └───────────┘
       │  │  │  │
   ┌───▼──▼──▼──▼───────────────────────────┐
   │  LLM Provayderlar                       │
   │  T0: Ollama (lokal, bepul)              │
   │  T1: Gemini/Groq/Mistral (free tier)    │
   │  T2: Haiku (arzon)                      │
   │  T3: Sonnet/Opus (kuchli)               │
   └─────────────────────────────────────────┘
```

## Modul tuzilishi

```
apps/core/src/zet/
├── __init__.py, config.py, cli.py, py.typed
│
├── domain/           # Domen modellari (Pydantic, frozen)
│   ├── enums.py      # 9 enum: PermissionLevel, TrustLevel, ...
│   ├── command.py    # Command, Intent
│   ├── plan.py       # Plan, PlanStep (DAG validatsiya)
│   ├── tool.py       # ToolResult, Verification
│   └── run.py        # RunState, RunLimits
│
├── core/             # Asosiy pipeline
│   ├── intent.py     # IntentRecognizer (LLM tool_use)
│   ├── planner.py    # Planner (LLM tool_use + repair loop)
│   ├── executor.py   # Executor (DAG + KillSwitch + Budget + Retry)
│   └── verifier.py   # Verifier (deterministic)
│
├── api/              # FastAPI REST API
│   ├── app.py        # create_app(), lifespan
│   ├── middleware.py  # TraceMiddleware (X-Trace-ID)
│   ├── deps.py       # Dependency injection
│   └── routes/       # health, run, killswitch
│
├── security/         # Xavfsizlik
│   ├── permissions.py  # PermissionPolicy (fail-closed)
│   ├── approvals.py    # ApprovalService (TTL, immutable)
│   └── killswitch.py   # KillSwitchState (emergency stop)
│
├── tools/            # Tool tizimi
│   ├── base.py       # Tool ABC + xatoliklar
│   ├── registry.py   # ToolRegistry (allowlist, JSON Schema)
│   └── builtin/      # time.now, note.write, shell.exec
│
├── observability/    # Kuzatuv
│   ├── logging.py    # structlog konfiguratsiyasi
│   ├── trace.py      # trace_id (UUID4, contextvars)
│   └── cost.py       # CostTracker (in-memory)
│
├── llm/              # LLM provayderlar va router
│   ├── base.py       # LLMProvider ABC
│   ├── router.py     # 4-tier Model Router (ADR-0006)
│   ├── budget.py     # BudgetGuard (5 qatlam)
│   ├── catalog.py    # Model katalogi
│   └── ...           # anthropic, openai_compat, fake, factory
│
├── prompts/          # LLM promptlar
│   ├── intent.py     # Intent aniqlash prompti + tool schema
│   └── planner.py    # Reja tuzish prompti + tool schema
│
└── db/               # Ma'lumotlar bazasi
    ├── base.py       # SQLAlchemy Base
    ├── session.py    # Engine + SessionFactory
    └── models/       # Owner, Run, Conversation, CostLedger, ...
```

## Asosiy qarorlar (ADR)

| ADR | Mavzu | Fayl |
|---|---|---|
| 0001 | Tech Stack | `docs/adr/ADR-0001-tech-stack.md` |
| 0002 | Security Model | `docs/adr/ADR-0002-security-model.md` |
| 0003 | Run Lifecycle | `docs/adr/ADR-0003-run-lifecycle.md` |
| 0004 | Tool System | `docs/adr/ADR-0004-tool-system.md` |
| 0005 | Design Tokens | `docs/adr/ADR-0005-design-tokens.md` |
| 0006 | Model Strategy & Budget | `docs/adr/ADR-0006-model-strategy-and-budget.md` |
| 0007 | Local-First Deployment | `docs/adr/ADR-0007-deployment-local-first.md` |

## Xavfsizlik modeli

### Permission darajalari

```
READ < WRITE < EXECUTE < ADMIN
```

- **READ**: har doim avtomatik
- **WRITE**: sozlanadigan (default: avtomatik, UNTRUSTED → tasdiq)
- **EXECUTE**: **har doim tasdiq**
- **ADMIN**: **har doim tasdiq**

### Trust darajalari

| Daraja | Manba |
|---|---|
| OWNER | Eganing to'g'ridan-to'g'ri buyrug'i |
| SYSTEM | Jadval vazifalar |
| UNTRUSTED | Tashqi manba (email, webhook) |

### Emergency Stop (KillSwitch)

Global bayroq — yoqilganda barcha run'lar CANCELLED.
Faqat ega qaytaradi: `z killswitch disengage`.

## Budjet tizimi (ADR-0006 §4)

5 qatlamli fail-closed budjet:

| # | Chegara | Default |
|---|---|---|
| 1 | Bitta run | $0.10 |
| 2 | T3 kunlik chaqiruvlar | 5 ta |
| 3 | Kunlik budjet | $0.50 |
| 4 | Avtonom ulush | 40% |
| 5 | Oylik budjet | $10.00 |

## LLM Router (ADR-0006)

4 tier — tez va arzon modeldan kuchli va qimmatga:

| Tier | Model | Narx | Qachon |
|---|---|---|---|
| T0 | Ollama (lokal) | $0 | Oddiy so'rovlar |
| T1 | Gemini/Groq/Mistral | $0 | Free API tier |
| T2 | Haiku | ~$0.001 | O'rta murakkablik |
| T3 | Sonnet/Opus | ~$0.01+ | Murakkab, ahamiyatli |

## Bo'lim 1 holati

✅ Barcha 18 vazifa (Z1.0–Z1.17) bajarildi:

- Domain modellari (enums, command, plan, tool, run)
- Core pipeline (intent, planner, executor, verifier)
- LLM (router, budget, providers, catalog, fake)
- Security (permissions, approvals, killswitch)
- Tools (base ABC, registry, 3 ta builtin)
- Observability (logging, trace, cost)
- API (FastAPI, middleware, 6 endpoint)
- CLI (`z` buyrug'i, 8 subcommand)
- DB (SQLAlchemy models, migrations)
- Test infra (366 test, 94% qamrov)
- CI (ruff, mypy, pytest, gitleaks, docker)
- Dokumentatsiya (7 ADR, ARCHITECTURE.md)

## Ishga tushirish

```bash
# Deveopment
cd apps/core
uv sync --all-extras
uv run z status          # CLI
uv run uvicorn zet.api.app:create_app --factory --reload  # API

# Testlar
uv run pytest
uv run ruff check src tests
uv run mypy src
```
