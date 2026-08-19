# API Tool System — Architecture (public-apis integration, JB-18)

How ZET's Tool System, Capability System, and the new public-apis
discovery/adapter layer fit together. Written for someone extending this
later, not just for this integration's own record.

---

## 1. Two collections, one boundary

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│   CatalogRepository          │        │   ToolRegistry                │
│   (discovery — read only)    │        │   (execution — the real thing)│
│                               │        │                                │
│   ~1584 PublicAPIEntry        │        │   ~60 Tool instances           │
│   status: discovered/         │  ✕ no  │   (built-ins + 3 public-apis   │
│   evaluated/enabled/rejected  │  auto  │    adapters, indistinguishable │
│                               │  link  │    from any other tool)        │
└─────────────────────────────┘        └──────────────────────────────┘
        ↑                                          ↑
   sync_catalog()                          build_default_registry()
   (operator action,                       (app startup, single
    GitHub README → parse                   process-wide registry)
    → normalize → merge)
```

This is the single most important structural decision in the whole
integration (spec Phase 22: *"treat the GitHub repository as a discovery
catalog, not a security authority"*). An entry existing in the left box
never implies anything about the right box. Only a human writing an
`adapters/*.py` file and registering it in `build_default_registry()`
creates a right-box tool. There is no code path — automatic, scheduled, or
LLM-triggered — that promotes a catalog entry into a registered tool.

## 2. Where public-apis code lives

```
apps/core/src/zet/integrations/public_apis/
├── catalog/          # ingestion — fetch, parse, normalize, store
│   ├── models.py       PublicAPIEntry, AuthType, PricingStatus, APIStatus
│   ├── parser.py        README.md → RawEntry (regex, no assumptions)
│   ├── normalizer.py    RawEntry → PublicAPIEntry (pricing ALWAYS "unknown")
│   ├── source.py        HTTP fetch of the raw README text
│   ├── repository.py    CatalogRepository — merge-not-overwrite store
│   └── sync.py          orchestrates the above, returns SyncReport
├── discovery/         # ranking/search over the catalog — no LLM calls
│   ├── search.py        keyword scoring (same style as CapabilityRegistry.search())
│   ├── ranker.py        composite score: relevance+https+auth+health+trust+enabled
│   ├── capability_mapper.py   category → ZET capability tags (static dict)
│   └── matcher.py       capability → ENABLED providers, health-sorted (fallback selection)
├── credentials/
│   └── manager.py       PublicAPICredentialManager — thin namespacing over SecretManager
├── health/
│   └── scoring.py        ProviderHealthTracker — in-process call counters
└── adapters/           # the ONLY part that is a real Tool / touches ToolRegistry
    ├── base.py           PublicAPIAdapter(Tool) — retry, error mapping, health recording
    ├── geocode.py         GeocodeForwardTool, GeocodeReverseTool
    └── ip_lookup.py       IpLookupTool
```

Everything under `catalog/`, `discovery/`, `credentials/`, `health/` is
inert with respect to the Brain — it's queried by the REST admin routes
(`api/routes/public_apis.py`) and by one Brain-facing tool
(`tools/builtin/public_apis_search.py::PublicAPISearchTool`), and that's
the entire surface. Only `adapters/` produces objects that `ToolRegistry`
holds.

## 3. Request paths

### 3.1 Operator syncs/inspects the catalog

```
z api refresh  ──HTTP──▶  POST /api/v1/public-apis/refresh
                              │
                              ▼
                    sync_catalog(repository, ...)
                    fetch_catalog_text()  (github raw README)
                    parse_readme()  →  normalize_entries()
                    repository.replace_all()  (merge semantics)
```

`z api search|health|stats` are thin `GET` wrappers over the same
`CatalogRepository`/`ProviderHealthTracker` singletons
(`api/deps.py::get_public_apis_catalog_repository()` /
`get_public_apis_health_tracker()`, both `@lru_cache(maxsize=1)` — the
same convention as every other process-wide singleton in `api/deps.py`).
**Why HTTP, not a direct DB/import call:** the CLI and the API server are
separate OS processes; an in-memory singleton in one process is invisible
to the other. `z api *` therefore always calls the *running* server, same
reasoning as the pre-existing `z approve`/`z reject` commands
(`cli.py::_api_call()`).

### 3.2 Brain discovers ("is there an API for X")

```
User/Planner  ──tool call──▶  public_apis.search
                                   │
                                   ▼
                    PublicAPISearchTool._execute()
                    reads repository.all()  (SAME singleton, in-process
                                              this time — Brain and API
                                              server run in the same
                                              FastAPI process)
                    search_catalog() → rank_candidates()
                    → summary_text explicitly marks non-enabled
                      results "ZET cannot do this yet"
```

### 3.3 Brain/user executes a real capability

```
User/Planner  ──tool call──▶  location.geocode / .reverse_geocode / ip.lookup
                                   │
                                   ▼
                    Tool.execute()  (base.py — UNCHANGED, existing contract)
                      → asyncio.wait_for(timeout_s)
                      → PublicAPIAdapter._execute()
                          → tenacity retry (transient only, 2 attempts)
                          → _call_provider()  (adapter-specific HTTP + parse)
                          → ToolError subtype on failure → mapped ToolResult
                      → ProviderHealthTracker.record_success/failure()
                    → normal Verifier / RecoveryEngine / approval path,
                      completely unaware this is a "public-apis" tool
```

This is the key non-negotiable from the audit: **execution never
special-cases these 3 tools.** `Verifier`, `RecoveryEngine`,
`PermissionPolicy`, `Orchestrator` treat `location.geocode` exactly like
`weather.now` — there is no `if tool.is_public_api:` branch anywhere in
core execution code.

## 4. Why a shared `PublicAPIAdapter` base class

Every external-API tool in this codebase already re-implements roughly the
same shape (lazy `httpx.AsyncClient`, single try, `raise_for_status()`,
map exception → message). `PublicAPIAdapter` factors the **cross-cutting**
concerns that are genuinely identical across all public-apis adapters —
and *only* those:

| Concern | Where it lives | Why factored here and not left per-adapter |
|---|---|---|
| Timeout | `Tool.execute()` (base, unchanged) | Already shared by every tool in the codebase |
| Transient retry (connect/5xx, 2 attempts) | `PublicAPIAdapter._execute()` | New for this integration — `tenacity` was a declared-but-unused dependency; every public-apis adapter needs the same short local retry *underneath* `RecoveryEngine`'s slower LLM-diagnosed retry |
| 429 → `ToolQuotaError`, 5xx/other 4xx → `ToolError`, timeout → `ToolTimeoutError` | `PublicAPIAdapter._execute()` | Maps to the *existing* `FailureClass` taxonomy (`core/failure_classification.py`) — no new taxonomy invented |
| Health recording | `PublicAPIAdapter._record_success/_failure()` | One `ProviderHealthTracker` call site instead of one per adapter |
| `output_trust_level = UNTRUSTED` | `PublicAPIAdapter` property | External data is never SYSTEM-trusted (A-05) |

What is **not** factored, and stays adapter-specific by design: URL
construction, request params, response parsing, and — critically — the
"HTTP 200 but body says error" check (Bo'lim 11's hard contract: each
adapter's `_call_provider()` must raise on a provider-level error marker
itself; the base class has no way to know a given provider's error-body
shape).

## 5. Risk / permission — no new logic

All 4 new tools (3 adapters + `public_apis.search`) fall through
`Tool.risk_level`'s existing default (`security/risk.py::risk_for()` — a
table lookup that defaults to `LOW` for anything not explicitly listed as
`MEDIUM`/`HIGH`). This is correct and intentional: all 4 are read-only
lookups with no side effects, same tier as `weather.now`. **No entry was
added to `TOOL_RISK_LEVELS`** — the audit confirmed this before
implementation (§1.5) and implementation confirmed it holds.
`PermissionPolicy.requires_approval()` — unchanged — auto-approves them
the same way it already auto-approves any other READ+LOW tool.

## 6. Extension point: capability discovery vs. capability execution

`core/capability.py`'s `location` `Capability` entry
(`default_tools=["location.geocode", "location.reverse_geocode",
"ip.lookup"]`) exists for **Mission-level** (multi-step goal) tool
scoping — a separate mechanism from `public_apis.search`, which exists for
**catalog discovery**. They answer different questions:

- `Capability("location").default_tools` → "if a Mission needs location
  capability, which *already-real* tools does it get?" (answer: exactly
  these 3, always real, always callable)
- `public_apis.search` → "does *any* API — real or merely catalogued —
  plausibly exist for what the user is asking?" (answer: ranked
  candidates, most of which are *not* callable — see §1)

Do not conflate the two when adding a new adapter — a new adapter always
needs the `ToolRegistry` registration (§6 of the integration doc); it only
sometimes needs a `Capability` entry (only if Mission-level multi-step
planning should be able to pull it in as a bundle).

## 7. See also

- `docs/integrations/PUBLIC_APIS.md` — operator/day-to-day guide, how to
  add an adapter.
- `docs/security/EXTERNAL_API_SECURITY.md` — credential handling, failure
  taxonomy mapping, no-fabrication guarantees, in depth.
- `docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md` /
  `PUBLIC_APIS_INTEGRATION_FINAL.md` — pre/post-implementation review.
