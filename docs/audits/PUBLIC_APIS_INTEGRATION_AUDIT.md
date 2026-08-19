# PUBLIC-APIS Catalog Integration — Pre-Implementation Audit

**Status:** Phase 0 (mandatory, read-only) — written *before* any integration
code exists. Per the task's own rule: "Do not start by coding."

**Scope of this document:** map the existing ZET/JARVIS architecture against
the 25-phase spec, identify exactly what to reuse vs. build, flag risks, and
commit to a concrete (deliberately non-overengineered) initial scope.

---

## 1. Existing architecture — what's already there

ZET already has a working, tested Tool System. This integration is an
**extension of it**, not a parallel system.

### 1.1 Tool contract (`zet/tools/base.py`)

`Tool` is an ABC every tool implements: `name`, `description`,
`input_schema` (JSON Schema), `permission_level` (READ/WRITE/EXECUTE/ADMIN),
`risk_level` (defaults to a central table lookup, overridable per-tool),
`output_trust_level` (SYSTEM/UNTRUSTED — external data is UNTRUSTED, A-05),
`idempotent`, `timeout_s`, and `_execute(params) -> Any` (public `execute()`
wraps it in `asyncio.wait_for`, catches `ToolError`/`ToolQuotaError`/
`ToolTimeoutError`/`ToolValidationError`, and always returns a `ToolResult`
— never raises out to the caller). **This is the adapter contract the spec
asks for in Phase 6/7** — `PublicAPIAdapter` will simply *be* a `Tool`
subclass, not a new abstraction sitting beside it.

### 1.2 ToolRegistry (`zet/tools/registry.py`)

Single registry: `register()`, `get()`, `list_tools()`, `tool_names()`,
`tool_signatures()` (name + description + required/optional params — this
is the *only* thing the Planner LLM ever sees; `permission_level`/
`risk_level` are **not** rendered into the prompt, which is why tool
*descriptions* carry the read/write signal explicitly — see JB-16/JB-17
work earlier in this session). `build_default_registry()`
(`tools/builtin/__init__.py`) is the single place all builtin tools are
constructed and registered. **New adapters register here — no second
registry.**

### 1.3 Existing external-API tool pattern (already established, to mirror)

`tools/builtin/feed_tools.py` + `zet/feeds/providers.py` is the closest
existing precedent to what Phases 1–13 ask for, and it already encodes the
spec's own philosophy independently:

- **Keyless-first.** Weather → Open-Meteo (no key), stocks → Yahoo Finance
  (no key), news → RSS. Explicit rationale in the module docstring: *"ega
  allaqachon o'nlab API kalitini boshqarayapti"* (the owner already manages
  dozens of API keys) — adding more raises the risk every card sits
  "unconfigured" forever. **This directly validates Phase 21's "start
  keyless" instinct** and is the deciding factor in this integration's
  initial adapter selection (§6).
- **No fabrication.** `FeedError` is raised on any failure; callers show
  "source unavailable," never a stale/guessed value.
- **`TTLCache`** — in-process, no Redis, TTL tuned per data volatility.
  Reusable as-is for adapters whose data changes slowly (geocoding results
  are effectively static).
- Other external tools (`telegram_tools.py`, `github.py`, `instagram.py`,
  `youtube.py`, `vision_ocr.py`, `video_learn.py`) all share one more
  pattern worth preserving: **real-vs-stub** — a tool with no configured
  credential stays registered (visible to the Planner, listed by
  `system.capabilities`) but raises a clear `ToolError` on execution,
  rather than being silently absent. New adapters follow the same rule.

### 1.4 Capability system (`zet/core/capability.py`, `mission_orchestrator.py`)

`CapabilityRegistry` is a *separate* concept from `ToolRegistry`: a
`Capability` bundles `default_tools` + `permission_level` + `risk_level`
+ `default_agents` and is what `CapabilityRegistryComposer.compose()`
keyword-searches to scope tools for **Mission** (multi-step "goal")
execution only — plain "command" requests go straight to the full
`ToolRegistry` via `Orchestrator`/`Planner` (established in this session's
JB-16 work). New adapters are tools first; they only need a `Capability`
entry if a Mission-level multi-step objective should be able to pull them
in as part of a bundle (e.g. a `location` capability). This audit adds
capability entries only where it clearly helps (§7); it does not force one
per adapter.

### 1.5 Risk / Permission (`zet/security/risk.py`, `zet/security/permissions.py`)

`TOOL_RISK_LEVELS` is a flat `dict[str, RiskLevel]` keyed by tool name
(`_HIGH`/`_MEDIUM` frozensets, else LOW). `PermissionPolicy.requires_approval()`
resolves risk in order: explicit arg → `tool.risk_level` → table → LOW, then
applies fail-closed rules (HIGH always needs approval, EXECUTE/ADMIN always
needs approval, UNTRUSTED+WRITE+ needs approval, MEDIUM configurable,
READ+LOW auto). **All public-apis adapters in this integration's initial
scope are READ-only lookups → LOW risk, auto-approved, same as
`weather.now`/`currency.rate` today.** No change to the approval engine is
needed or made.

### 1.6 Model routing / Brain / Planner / AgentSelector

Out of scope for this integration — API *tool execution* never touches
`ModelRouter`; only the Planner's own LLM call (to *choose* a tool) does,
and that path is unchanged (tool descriptions are the only new surface,
per §1.2). `AgentSelector` assigns agents to tools it doesn't already know;
no change needed — new tools become selectable exactly like any existing
one (`AgentListTool`/`ResearchAgent`/etc. already reference generic
capability tags, not hardcoded tool lists, in the agents this session has
touched).

### 1.7 Credentials — real gap, but a shaped one

`zet/config.py::Settings` holds every current API key as a fixed
`SecretStr` pydantic field, sourced from env vars at boot — this is right
for a small number of *known-in-advance*, operator-configured services
(Anthropic, Telegram, GitHub, …), but wrong for a *dynamic, grow-over-time*
set of public-API provider credentials, since it would mean a code change
+ redeploy per new provider.

**Found and reusable:** `zet/security/secrets.py::SecretManager` — an
in-memory, already-unit-tested class with almost exactly Phase 8's wishlist
(`SecretMetadata`: id/name/status/created_at/expires_at/rotated_at/
rotation_count/masked_value; `register()`/`get_value()`/`rotate()`/
`revoke()`/`list_secrets()`/`expiring_soon()`; values are *never* exposed
outside `get_value()`, which is documented "internal use only, never log,
never return via API"). It is currently marked `.. deprecated::` with an
explicit note: *"ilgari sirlar bu klass orqali yuklanadi deb rejalashtirilgan
edi... bu modulni ishlatishdan oldin `Settings.load()` yo'liga ulash kerak"*
— i.e. it was shelved for being redundant with `Settings`, **not** because
it's unfit for purpose. Dynamic, runtime-registered provider credentials
are precisely the case `Settings` *can't* cover and `SecretManager` was
built for. This audit's decision: **un-deprecate `SecretManager` for this
one new purpose** (dynamic public-API provider credentials only;
`Settings`/env vars remain canonical for the fixed, operator-known
services) rather than inventing a parallel store. One field is genuinely
missing (`last_used_at`) and is added.

Persistence: `SecretManager` is in-memory only (matches its existing
tested contract). For this integration's initial scope (all enabled
adapters are keyless — §6), this is not a blocking gap; it is flagged as a
known limitation for when a key-requiring provider is enabled (§9,
"Not implemented").

### 1.8 Failure taxonomy (`zet/core/failure_classification.py`, JB-14)

Already covers every case Phase 12 asks for — `FailureClass`: TRANSIENT,
MODEL, TOOL, AUTHENTICATION, AUTHORIZATION, RATE_LIMIT, NETWORK,
EXTERNAL_UNCERTAIN, INVALID_PLAN, VALIDATION, USER_REQUIRED, SYSTEM,
UNKNOWN. `classify_exception()` maps `ToolQuotaError`→RATE_LIMIT,
`ToolTimeoutError`→NETWORK, `ToolPermissionDeniedError`→AUTHORIZATION,
`ToolValidationError`→VALIDATION, generic `ToolError`→TOOL; falls back to
`classify_text()`, a deterministic keyword heuristic (no LLM call) that
already recognizes phrases like "rate limit", "timeout", "unauthorized".
**Conclusion: adapters just need to raise the *existing* exception types
with clear messages — no new `API_*` taxonomy is created,** exactly per
the task's explicit instruction not to duplicate failure semantics that
already exist.

### 1.9 Verification, Recovery (`core/verifier.py`, `core/recovery.py`)

Already wired per-step: `Verifier.verify_step()` checks `tool_result.success`
first (a `success=True` with a provider-level `{"error": true}` body would
currently slip through only if the adapter itself returns `success=True` —
this is exactly why Phase 11 matters: **adapters must treat a provider
error payload as a tool failure**, not rely on the generic verifier to
catch it after the fact). `expected_outcome` text/regex/LLM-judge tiers
apply unchanged. `RecoveryEngine`'s FAIL→DIAGNOSE→FIX→RETRY→VERIFY loop
already applies to any tool step, no adapter-specific wiring required.

### 1.10 HTTP / retry conventions

Every existing external-API tool constructs its own `httpx.AsyncClient(timeout=N)`
lazily and does a **single** request attempt per call — no per-call retry
today. `tenacity` is a declared dependency (`pyproject.toml`) but is
**currently unused anywhere in `src/`** — this is a real, available,
already-installed tool for adapter-level retry (network blips only, never
retrying a non-idempotent write) that nothing currently uses. This audit's
decision: use `tenacity.AsyncRetrying` inside the new adapter base class
for transient connection errors only (2 attempts, short exponential
backoff) — a fast local retry layered *under* `RecoveryEngine`'s slower,
LLM-diagnosed step-level retry, not a replacement for it.

### 1.11 CLI (`zet/cli.py`)

`typer`-based; existing admin commands (`approve`/`reject`/`agent_*`/
`telegram_status`) go through `_api_call()` — a thin wrapper hitting the
running API server's REST endpoints, not the DB directly. New admin
commands (Phase 17) follow the same shape: a new `/api/v1/public-apis/*`
route group + thin `z api ...` CLI commands calling it.

### 1.12 Tests

Convention (established throughout this session — `test_vision_ocr.py`,
`test_crm_tools.py`, `test_telegram_tools.py`): `respx` mocks the HTTP
layer, one test class per behavior group, a `test_registered_in_default_registry`
check, and description/disambiguation-locking tests. `pytest.ini`'s
`live` marker (*"haqiqiy LLM API chaqiradi... default o'chirilgan"*) is the
existing precedent for opt-in tests against a real external endpoint — this
integration reuses the same marker name/spirit for real (but free/keyless)
HTTP calls to the chosen providers, default-skipped in CI.

---

## 2. What's missing (and being built, minimally)

| Component | Status | Plan |
|---|---|---|
| Normalized public-API catalog model | Missing | New (`integrations/public_apis/catalog/`) |
| Catalog sync from `public-apis/public-apis` | Missing | New, real fetch+parse (not fabricated data) |
| Discovery/ranking engine | Missing | New, mirrors `CapabilityRegistry.search()`'s scoring style |
| Capability→provider mapping | Missing | New, small deterministic keyword map (not LLM) |
| Adapter base class | Missing | New `Tool` subclass — reuses existing contract |
| Concrete adapters | Missing | 3 new tools, keyless, real (§6) |
| Dynamic credential store | Partially exists | Reuse+extend `SecretManager` |
| Health/scoring | Missing | New, small, in-memory counters (mirrors `TTLCache` simplicity) |
| Fallback-provider selection | Missing | New, mirrors `ModelRouter.candidates_for()`'s proven pattern |
| Admin CLI/API | Missing | New route + CLI commands, existing patterns |
| Observability | Existing pattern, needs a schema | Structured `structlog` fields, no new sink |
| Cost/budget tracking | N/A for this scope | Deferred — all initial adapters are free (§9) |

---

## 3. Risks

- **Catalog trust.** The GitHub list is a *discovery index*, not a security
  authority (Phase 22) — every entry defaults to `status=DISCOVERED`,
  never auto-promoted to an executable tool. Only adapters explicitly
  written and reviewed in this repo become callable tools.
- **Credential exposure.** Mitigated by reusing `SecretManager`'s existing
  "value never leaves `get_value()`" contract; adapters receive a resolved
  string at construction time (same pattern `TelegramChannelPostTool`
  already uses for its bot token), never a live handle the LLM can read.
- **Runaway calls.** Mitigated by the *existing* `Executor` step budget,
  `timeout_s` per tool, and `RecoveryEngine`'s bounded retries — no agent
  loop can call a tool an unbounded number of times without those already
  triggering.
- **Duplicating `weather.now`/`currency.rate`/`news.headlines`/`stocks.quote`.**
  These are explicitly **not** re-implemented — the initial adapter set
  (§6) is chosen to be entirely non-overlapping with `feed_tools.py`.
- **Scope creep (Phase 24's own warning).** The catalog *can* hold
  thousands of entries; only a curated few become real tools. This is
  enforced structurally: `CatalogRepository` (discovery) and
  `ToolRegistry` (execution) are different collections, and nothing
  auto-promotes one into the other.

---

## 4. Files that will be changed

- `apps/core/src/zet/tools/builtin/__init__.py` — register new adapters.
- `apps/core/src/zet/security/secrets.py` — remove the "not used in
  production" framing for the one new caller; add `last_used_at`.
- `apps/core/src/zet/security/risk.py` — no change expected (new tools
  fall through to default LOW, matching their READ-only nature); will
  confirm during implementation.
- `apps/core/src/zet/cli.py` — add `api` command group.
- `apps/core/src/zet/api/routes/` — add a new route module for admin
  catalog/health endpoints.
- `apps/core/pyproject.toml` — no new dependencies (`httpx`, `tenacity`,
  `respx` all already present).
- `docs/` — this file, plus the three Phase 23 docs and the Phase 25
  final audit.

## 5. Files that must NOT be changed

- `zet/core/brain.py`, `zet/core/planner.py`'s planning algorithm,
  `zet/core/mission.py`'s approval gate, `zet/security/permissions.py`'s
  decision logic, `zet/core/verifier.py`'s verification tiers,
  `zet/core/recovery.py`'s retry loop, `zet/tools/registry.py`'s
  registration mechanics — all reused as-is, none rewritten.
- Any existing tool file, existing test file, or existing capability
  entry — no deletions, no behavior changes outside what's listed in §4.

---

## 6. Initial adapter set (deliberately small — Phase 21/24)

Chosen for: HTTPS, no signup/API key required (this session cannot
provision paid/keyed accounts, and Phase 21 explicitly prioritizes
keyless-simple-auth APIs first), non-overlap with existing `feed_tools.py`
capabilities, genuine usefulness, and — critically — **testable for real**
(an opt-in `live` test hits the actual endpoint, not just a mock):

1. **`location.geocode`** — Open-Meteo Geocoding API
   (`geocoding-api.open-meteo.com`) — same vendor ZET already trusts for
   `weather.now`, extending an existing relationship rather than adding a
   new one. Free, keyless, HTTPS.
2. **`location.reverse_geocode`** — BigDataCloud reverse-geocode-client
   API (`api.bigdatacloud.net`) — free, keyless, HTTPS, no rate-limit
   auth required for the client endpoint.
3. **`ip.lookup`** — ipapi.co — free tier, keyless, HTTPS.

Explicitly **not** enabled in this pass (catalog-discoverable, not
tool-registered): email/phone validation, flight info, screenshot,
finance beyond stocks — all realistically require a paid or signup-gated
key this session cannot obtain, so shipping them as "enabled" would
violate the "no fabricated capability" principle this whole codebase is
built around (`FeedError`, real-vs-stub). They remain visible via the
discovery/catalog layer as `NOT_AVAILABLE` candidates for an operator to
enable later by supplying a credential — the architecture supports this
without further code changes (§7).

---

## 7. Proposed integration points (concrete)

```
integrations/public_apis/
├── catalog/{models,source,parser,normalizer,repository}.py
├── discovery/{search,ranker,capability_mapper}.py
├── adapters/{base,geocode,ip_lookup}.py
├── credentials/manager.py      # thin wrapper over zet.security.secrets.SecretManager
├── health/{checker,scoring}.py
└── tests/...
```

- `adapters/base.py::PublicAPIAdapter(Tool)` — one shared base handling
  timeout/retry/health-recording/error-normalization; concrete adapters
  implement only `_call_provider()`.
- Adapters register into the *existing* `ToolRegistry` via
  `build_default_registry()`, exactly like every other builtin tool.
- A new `location` `Capability` entry (`core/capability.py`) is added so
  Mission-level (multi-step "goal") requests can discover geocoding —
  mirrors the existing `Capability` shape, `default_tools=["location.geocode",
  "location.reverse_geocode"]`, `risk_level=LOW`.
- Discovery (`discovery/search.py`) is queried by a new
  `public_apis.search` tool (same self-referential-registry pattern as
  `CapabilityDiscoveryTool` added earlier this session) so the Brain can
  answer "is there an API for X" from the real catalog, not a guess.

---

## 8. Decision: proceed

The existing architecture has *everything* Phases 6–12 assume already
exists (`Tool`, `ToolRegistry`, `PermissionPolicy`, `FailureClass`,
`Verifier`, `RecoveryEngine`) — this integration adds a **discovery and
adapter layer on top**, touching no core execution/security code paths.
Proceeding to implementation.
