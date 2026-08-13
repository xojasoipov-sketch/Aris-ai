# ZET ASS — Autonomy Audit (Master-Spec Migration Bridge)

> Sana: 2026-08-13 · Ega tomonidan `docs/ZET_ASS_MASTER.md` yuborilgach zaruriy birinchi
> deliverable (Master Spec PART 10 "First deliverable" talab qiladi). Bu hujjat MASTER
> spec'ning target arxitekturasini HOZIRGI kod bilan solishtiradi va inkremental migratsiya
> rejasini beradi — Master Spec'ning "PART 10 GUARDRAILS": *blind rewrite yo'q, mavjud
> arxitektura ustiga o'sish.*

## 0. Ijro xulosasi — bir jumlada

**ZET vision'ning yadrosi (Intent→Plan→Execute→Verify, Model Router, Automation Engine,
Agent lifecycle, Tool Registry, Frontend) haqiqatan qurilgan va yashil (2359 test). Master
Spec taklif qilayotgan Mission Engine, Capability Registry, Context Discovery Engine, Task
Graph va Project Profile — hozirgi tizim ustiga *qo'shimcha qatlam* sifatida qurilishi
kerak, chunki mavjud `Command`/`Plan`/`RunRecord`/`AgentRegistry`/`PgMemoryStore` ular
uchun tayyor primitive'lar bilan xizmat qiladi.**

Ya'ni bu — 6 ta yangi katta modul qo'shish (mavjud kodni buzmasdan), 3 ta mavjud modulni
kengaytirish, hech qanday to'liq qayta yozish YO'Q. Ular allaqachon mavjud tuzilma bilan
o'zaro bog'lanadi (naqsh: `WorkspaceRepository`, `PgCRM`, `CommerceRepository` bilan bir xil
domain-slice pattern).

---

## 1. Master-spec'dagi 20 komponent — hozirgi holat

| Spec komponenti | Hozirgi implementatsiya (bor bo'lsa) | Status | Migratsiya harakati |
|---|---|---|---|
| Intent Engine | `core/intent.IntentRecognizer` (LLM-based) | ✅ REAL | Kengaytirish shart emas |
| Context Engine | `_recall` yopilmasi (memory only) | 🟡 QISMAN | Multi-source aggregator qo'shish (yangi modul) |
| Memory Engine | `PgMemoryStore` + 7 qatlam + policy | ✅ REAL | `MemoryManager` policy'ni API'ga chiqarish (Phase 1 workflow'da) |
| Mission Engine | (yo'q) | 🔴 MISSING | Yangi `zet.core.mission.Mission` + `MissionEngine` |
| Planner | `core/planner.Planner` (LLM-based) | ✅ REAL | Task Graph output'ini qo'llab-quvvatlash uchun kengaytirish |
| Task Graph | `domain/plan.Plan` (linear list) | 🟡 QISMAN | DAG'ga o'tkazish — dependencies, parallel guruhlar, sequential zanjirlar |
| Agent Registry | `agents/registry.AgentRegistry` (14 agent) | ✅ REAL | Kengaytirish shart emas |
| Agent Runtime | `agents/runtime.AgentRuntime` | ✅ REAL (partial) | `verify` bosqichini qo'shish (docstring'da bor, kodda yo'q) |
| Agent Factory | `agents/factory.AgentFactory` | 🟡 QISMAN | UNDERSTAND/DESIGN LLM-based bo'lishi kerak (hozir kalit-so'z lookup) |
| Tool Registry | `tools/registry.ToolRegistry` (~40 tool) | ✅ REAL | Kengaytirish shart emas |
| Permission Engine | `security/permissions.PermissionPolicy` | ✅ REAL | Risk-level kengaytirish (LOW/MEDIUM/HIGH mapping) |
| Approval Engine | `security/approvals.ApprovalService` | ✅ REAL | AR-01 DB persistence (Task #57 alohida) |
| Execution Engine | `core/executor.Executor` | ✅ REAL | Trust-level oqim allaqachon ulangan (AR-02 yopildi) |
| Verification Engine | `core/verifier.Verifier` + LLM-judge | ✅ REAL | Cheklovsiz mission'lar uchun retry orchestrator loop kerak (recovery) |
| Recovery Engine | (yo'q) | 🔴 MISSING | Yangi modul: `zet.core.recovery.RecoveryEngine` (FAIL→DIAGNOSE→FIX→RETRY→VERIFY) |
| Integration Providers | `telegram/`, `voice/`, `commerce/`, `business/`, `devices/` | ✅ REAL | Master Spec PART 9 kengroq capability oqimlarini talab qiladi |
| Device Registry | `devices/repository.DeviceDBRepository` + REST + tokens | ✅ REAL | Kengaytirish shart emas |
| Automation Engine | `automation/engine.AutomationEngine` + HandoffDispatcher | ✅ REAL | Standing missions (competitor monitoring, morning report) uchun mission-triggered rules |
| Notification Engine | `telegram/notifier.Notifier` + alerts | ✅ REAL | Kengaytirish shart emas |
| Audit Engine | `security/audit_writer.write_audit` + DB | ✅ REAL | Kengaytirish shart emas |
| **Capability Registry** | (yo'q) | 🔴 MISSING | Yangi modul: `zet.core.capability.CapabilityRegistry` |
| **Project Profile** | `WorkspaceRepository.Project` (nom+description) | 🟡 QISMAN | Model kengaytirish: brand, contacts, products, repository, etc. |
| **Reference Resolution** | (yo'q) | 🔴 MISSING | Yangi modul: `zet.core.references.ReferenceResolver` |

---

## 2. Yangi qatlam — nima qurilishi kerak

Master Spec quyidagi **implementatsiya tartibini** talab qiladi (PART 10):

```
1. CAPABILITY REGISTRY  ←── boshlash nuqtasi
2. MISSION ENGINE
3. CONTEXT ENGINE
4. TASK GRAPH
5. AGENT SELECTION
6. TOOL SELECTION
7. PERMISSION ENGINE (allaqachon bor)
8. APPROVAL ENGINE (allaqachon bor)
9. VERIFICATION ENGINE (allaqachon bor)
10. MEMORY INTEGRATION (allaqachon qisman bor)
```

### 2.1 Capability Registry

**Fayl:** `apps/core/src/zet/core/capability.py` (yangi)

Har bir capability metadata bilan e'lon qilinadi:

```python
class Capability(BaseModel, frozen=True):
    name: str                                    # 'website', 'instagram', 'sales'
    description: str
    supported_outcomes: list[str]                # 'build_website', 'audit_site'
    required_context_sources: list[str]          # 'obsidian', 'github', 'files'
    actions: list[str]                           # 'plan', 'design', 'develop', 'deploy'
    default_agents: list[str]                    # ['developer', 'qa', 'security']
    default_tools: list[str]                     # ['github.write', 'note.write']
    permission_level: PermissionLevel            # eng past yetarli
    risk_level: RiskLevel                        # LOW/MEDIUM/HIGH
    verification_strategy: VerificationStrategy  # HTTP_CHECK, LINK_CHECK, VISUAL, ...
    failure_strategies: list[str]                # 'rollback_deploy', 'notify_owner'
    dependencies: list[str]                      # boshqa capability nomlari
```

**Registry:** `CapabilityRegistry` (singleton) — mission engine capability'larni dinamik
tarzda tanlaydi. Hard-coded phrase matching YO'Q.

**Composition:** bir request bir necha capability birlashtirishi mumkin — Master Spec PART 2
misoli: "Prepare my business for online launch" → Business + Branding + Website + Instagram
+ Telegram + Sales + Analytics + Automation.

### 2.2 Mission Engine

**Fayl:** `apps/core/src/zet/core/mission.py` (yangi)

```python
class MissionStatus(StrEnum):
    RECEIVED, UNDERSTANDING, DISCOVERING, PLANNING, WAITING_APPROVAL,
    EXECUTING, VERIFYING, RECOVERING, COMPLETED, FAILED, CANCELLED

class Mission(BaseModel):
    id: uuid.UUID
    objective: str                       # ega yozgan tabiiy tildagi maqsad
    outcome_criteria: str                # nima 'done' hisoblanadi
    context: dict[str, Any]              # context discovery natijasi
    constraints: list[str]
    tasks: list[Task]                    # Task Graph node'lari
    agents: list[str]
    tools: list[str]
    capabilities: list[str]
    permissions_required: list[PermissionLevel]
    risk_level: RiskLevel
    approval_requirements: list[str]
    deadline: datetime | None
    verification_rules: list[str]
    memory_updates: list[str]            # completion'da qanday xotira yozuvi
    status: MissionStatus
    priority: int
    created_at: datetime
    updated_at: datetime
```

**Naqsh:** existing `Run`/`RunRecord` bilan raqobat qilmaydi — Mission YUQORIDA turadi,
bir Mission bir yoki bir necha Run yaratadi (Mission=strategy, Run=execution).

**Persistence:** `db/models/mission.py` + Alembic migration. `MissionRepository` — mavjud
`WorkspaceRepository`/`PgCRM` naqshiga o'xshash.

### 2.3 Context Discovery Engine

**Fayl:** `apps/core/src/zet/core/context.py` (yangi)

Kirish: `UserRequest` (matn + kanal + owner_id + conversation history)
Chiqish: `RelevantContext` (targeted retrieval, hech qachon full dump)

Manbalar (Master Spec PART 4):
- Memory (`PgMemoryStore.search` — semantik)
- Obsidian (`_vault.iter_notes` — tag/name filter)
- Database (project/task/deal filter)
- GitHub (repository info via existing tool)
- Telegram (recent messages)
- Calendar (upcoming events)
- Files/assets (vault subdirectory scan)
- Recent activity (conversation history)

**Source-of-truth priority** (konflikt bo'lsa):
```
Current user instruction → Current project data → Authoritative source
→ Recent memory → Older memory → Inference (label "inferred")
```

### 2.4 Task Graph (Plan kengaytirish)

Hozirgi `PlanStep` — linear ro'yxat (`position: int` bilan tartib). Master Spec talab
qiladi: real DAG parallel guruhlar bilan.

**Kengaytirish:** `PlanStep`ga `depends_on: list[int]` (position'lar) qo'shildi (allaqachon
kod ichida bor — orchestrator hozir uni dedup uchun ishlatadi). Yangi funksiya:
`plan_to_dag()` — parallel guruhlarni topa oladi. Executor DAG bo'yicha oladi (topological
sort + parallel batches).

### 2.5 Recovery Engine

**Fayl:** `apps/core/src/zet/core/recovery.py` (yangi)

`FAIL → DIAGNOSE → FIX → RETRY → VERIFY` tsikli:
- Verifikatsiya `ok=False` bo'lsa: LLM'dan "nima yetishmadi, qanday tuzatish mumkin"
  so'raladi
- Yangi qadam(lar) plan'ga qo'shiladi (`Mission.status = RECOVERING`)
- Yangi qadam bajariladi va verifikatsiya qayta o'tkaziladi
- MAX_RETRIES cheklovi (default: 2)

### 2.6 Reference Resolution

**Fayl:** `apps/core/src/zet/core/references.py` (yangi)

Deictic references (Master Spec PART 4): `shu`, `bu`, `o'sha`, `mening loyiham`,
`biznesim`, `saytim`, `Telegramim`, `kechagi loyiha`, `oxirgi project`, `mana shu`.

Resolver:
1. Regex/keyword bilan reference tokenlarni topadi
2. Har bir uchun kandidat manba(lar)ni topadi (conversation history, recent tasks,
   projects, GitHub repos)
3. Bitta aniq kandidat bo'lsa — resolve qiladi
4. Bir nechta yoki 0 kandidat bo'lsa — clarification kerak degan bayroq qaytaradi

### 2.7 Project Profile

**Kengaytirish:** `db/models/workspace.py::Project` — Master Spec talab qiladigan
strukturaga kengaytirish:

```python
class Project:  # kengaytirilgan
    name, description, purpose, owner_id, business_id,
    target_audience, products, services,
    brand: {logo, colors, typography, tone},
    contact_information: {phone, email, address, social_links},
    website_url, repository_url,
    assets: list[str],           # vault yo'llari
    competitors: list[dict],
    pricing: dict,
    business_goals: list[str],
    marketing_goals: list[str],
    technical_requirements: dict,
    current_status: str,         # existing 'status' bilan uyg'un
    tasks, deadlines             # existing bilan bir xil
```

`ProjectProfileService` — barcha manbalardan (Obsidian tag search, GitHub read, files
scan) profil ma'lumotlarini avtomatik to'ldiradi va 'missing' bayroqlarini beradi.

### 2.8 Risk-based Approval

**Kengaytirish:** `security/permissions.py`ga `RiskLevel` va risk→approval mapping:

```python
class RiskLevel(StrEnum):
    LOW = "low"         # research, draft, analyze, summarize, private files
    MEDIUM = "medium"   # sozlash mumkin (default: approval)
    HIGH = "high"       # delete, publish, financial, credential, permission

RISK_TO_APPROVAL = {
    RiskLevel.LOW: False,      # avtomatik
    RiskLevel.MEDIUM: True,    # sozlanadigan
    RiskLevel.HIGH: True,      # HAR DOIM
}
```

Har bir Tool `risk_level: RiskLevel` maydoni bilan e'lon qiladi (default: LOW). Bu
`permission_level`ga ortogonal — permission "kim qila oladi", risk "tasdiq kerakmi".

### 2.9 Autonomy Level 5

Hozirgi levels: 0-4. Yangi:

```python
class AutonomyLevel(IntEnum):
    OBSERVE = 0
    RECOMMEND = 1
    PREPARE = 2
    EXECUTE = 3
    EXECUTE_VERIFY = 4
    EXECUTE_VERIFY_MONITOR = 5   # yangi: continuous monitoring
```

Level 5 uchun standing mission (`Automation Engine` orqali) qo'shiladi — mission tugagach
periodic check + notification.

---

## 3. Yangi modul → mavjud kod xaritasi

| Yangi modul | Foydalanadi | Foydalanuvchi |
|---|---|---|
| CapabilityRegistry | AgentRegistry, ToolRegistry | MissionEngine |
| Mission | Plan, RunRecord, ApprovalService, KillSwitchState | Orchestrator (yangi entrypoint) |
| ContextEngine | PgMemoryStore, note_list, GitHubReadTool, WorkspaceRepository, PgCRM | MissionEngine, IntentRecognizer |
| ReferenceResolver | ConversationStore, WorkspaceRepository, GitHubReadTool | ContextEngine, IntentRecognizer |
| ProjectProfileService | WorkspaceRepository, note_list, GitHubReadTool | ContextEngine, CapabilityRegistry |
| RecoveryEngine | Verifier, Executor, ModelRouter | Orchestrator (Mission tsikli) |
| Risk-based Approval | ApprovalService, PermissionPolicy | Orchestrator, Executor |
| Autonomy Level 5 | AutomationEngine, Scheduler | MissionEngine |

**Konflikt yo'q** — barcha yangi modullar mavjud primitives'dan foydalanadi, hech biri
qayta yozilmaydi.

---

## 4. Duplikatlar (Master Spec PART 10 "duplication" talabi)

Auditda topilgan duplikatlar — Phase 1 workflow (hozirda ishlab turibdi) hal qiladi:

| Duplikat | Yechim |
|---|---|
| `security/audit.py` (in-memory) vs DB AuditLog | In-memory versiya deprecated qilinadi |
| `security/secrets.py::SecretManager` vs `Settings SecretStr` | SecretManager over-engineered — deprecated |
| `observability/cost.py::CostTracker` vs `CostLedger` (DB) | CostTracker o'chiriladi |
| Old `devices/registry.DeviceRegistry` (in-memory) | DEPREKATSIYA belgisi qo'yildi, `DeviceDBRepository` ishlatiladi |

---

## 5. Xavflar (Master Spec PART 10 "risks")

| ID | Xavf | Ta'sir | Yechim |
|---|---|---|---|
| MSR-01 | Mission modeli mavjud Run modelidan yuqorida — chalkashlik xavfi | O'rta | Aniq hujjatlashtirish: Mission = strategy, Run = execution |
| MSR-02 | Task Graph DAG'ga o'tish parallel bug'lariga olib kelishi mumkin | O'rta | Har parallel guruh mustaqil bo'lishini executor tekshiradi (existing `depends_on` bilan) |
| MSR-03 | Context Engine katta LLM prompt'lariga olib kelishi mumkin | O'rta | Targeted retrieval + `MAX_CONTEXT_TOKENS` cheklovi |
| MSR-04 | Recovery loop cheksiz bo'lishi | O'rta | MAX_RETRIES=2 default, budget cheklovi |
| MSR-05 | Reference resolver LLM'ga bog'liq bo'lsa arzon T1 modelini ishlatishi shart | Past | T1_FREE tier bilan RoutedLLMProvider (Verifier judge'idagi kabi) |

---

## 6. Implementatsiya rejasi — kichik qadamlar (Master Spec PART 10 "incremental migration")

**Sprint 1** (bu sessiyada, mavjud kod bilan uyg'un):
1. Phase 1 cleanup workflow (hozirda ishlab turibdi) — dead code + policy + alerts +
   killswitch security. Bu Mission Engine qurilishidan OLDIN tozalab qo'yiladi.
2. `docs/ZET_ASS_AUTONOMY_AUDIT.md` (bu fayl) — deliverable ✅

**Sprint 2** (yangi qatlam — audit-first tartibda):
3. `zet.core.capability.py` + `CapabilityRegistry` — 20 tanlangan capability metadata
4. `zet.core.mission.py` + `db/models/mission.py` + Alembic migration
5. `zet.core.context.py` + `ProjectProfileService`
6. `zet.core.references.py`
7. `PlanStep.depends_on` haqiqiy DAG executor'i (parallel batches)
8. `zet.core.recovery.py`
9. Risk-level + Autonomy Level 5 — kengaytirish
10. Yangi entrypoint: `MissionOrchestrator` — eski `Orchestrator` bilan raqobat qilmaydi,
    mission oqimi uchun alohida yo'l.

**Sprint 3** (integration + test):
11. Master Spec PART 9 misollari uchun end-to-end smoke test'lar
12. Frontend: Mission progress ko'rsatkichi (existing NEXUS'da kengaytirish)
13. Master Spec PART 11 Definition of Done: "Build a website for this project" — bitta
    jumla tugagunga qadar avtomatik oqim

**Har sprint** oxirida:
- `ruff check + format + pytest -q` 100% yashil
- GAP_ANALYSIS + AUTONOMY_AUDIT yangilanishi
- Har mission uchun audit log qatorlari

---

## 7. Definition of Done — Master Spec PART 11 dan

ZET ASS to'g'ri arxitekturada deyiladi qachonki:

> "Build a website for this project." / "Menga shu loyiham uchun professional sayt kerak."

natijasida ZET mustaqil ravishda:
1. Loyihani aniqlaydi (ReferenceResolver)
2. Kontekstini oladi (ContextEngine: Obsidian + GitHub + files + memory)
3. Biznesni tushunadi (ProjectProfileService)
4. Aktiv va kontakt ma'lumotlarini topadi (ProjectProfileService)
5. Talablarni tushunadi (Mission constraint discovery)
6. Saytni rejalashtiradi (Planner + TaskGraph)
7. Ishni delegasiya qiladi (Agent selection dynamic)
8. Quradi (Developer agent + tools)
9. Test qiladi (QA agent + Verifier)
10. Muammolarni tuzatadi (RecoveryEngine)
11. Natijani tekshiradi (Verifier LLM-judge tier)
12. Faqat ruxsat berilgan bo'lsa deploy qiladi (HIGH_RISK approval)
13. Muhim loyiha ma'lumotlarini xotiraga saqlaydi (memory_updates)
14. Nima sodir bo'lganini xabar qiladi (Notifier)

— **faqat haqiqatan kerakli yo'qolgan ma'lumot yoki tasdiqlar so'raladi.**

Bir xil standart har boshqa bitta jumlali mission uchun: Instagram carousel, project fix,
business management, competitor monitoring, launch prep va h.k.

---

## 8. Yakuniy: "over-engineering" qarshi kafolatlar

Master Spec PART 10 aniq talab qiladi: **hech qanday keraksiz mikroservis, hech qanday
"chiroyli ovoz" texnologiya**. Bu audit reja shu qoidaga rioya qiladi:

- Yangi 6 modul — barchasi `zet.core/*` ichida (yangi service EMAS)
- DB'ga faqat 1 yangi jadval: `mission` (Task Graph node'lari `Plan`/`Step` bilan mavjud
  jadvallarga bog'lanadi)
- Yangi package/library YO'Q — mavjud SQLAlchemy async, Pydantic v2, FastAPI ishlatiladi
- Frontend'ga faqat 1 yangi sahifa (`/missions`) — kengaytirish sifatida, alohida SPA
  emas
- Test yozish naqshi mavjud (`session_factory`, `TestClient`) — o'zgartirilmaydi

Ya'ni **20+ yangi modul kutilmaydi — 6 tasi kutiladi**, hech biri > 500 qator, har biri
mavjud primitives'dan foydalanadi.

---

## 9. Keyingi qadam

Phase 1 workflow (hozirda ishlab turibdi) tugagach:
- Sprint 2 boshlanadi: Capability Registry → Mission Engine → ... implementatsiya order
  bo'yicha
- Har modul quriladi + testlanadi + committed
- Har commit'da GAP_ANALYSIS + AUTONOMY_AUDIT yangilanadi
- Sessiya oxirida to'liq end-to-end demo: bitta tabiiy jumla → to'liq oqim

---

**Bog'liq hujjatlar:**
- `docs/ZET_ASS_MASTER.md` — asosiy spec (627 qator, egadan)
- `docs/GAP_ANALYSIS.md` — mavjud kod gap-analizi (yakuniy yangilanish 2026-08-13)
- `docs/00-AUDIT.md` — birinchi kod audit (2026-08-11)
- `docs/02-MASTER-PLAN.md` — V-01..V-45, A-01..A-08, R-01..R-12 arxitektura tamoyillari
