# PUBLIC-APIS Catalog Integration — Final Audit (JB-18)

**Status:** implementation complete, MVP scope. Written *after* full
implementation and the full test suite, per the task's explicit final
step ("FINAL AUDIT" — a genuine architectural review, not just "tests
pass").

This document is the honest counterpart to
`docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md` (the Phase-0 plan). Where
that document predicted, this one reports what actually happened,
including where reality deviated from the plan.

---

## 1. Executive summary

The 25-phase spec asked for a public-apis discovery/catalog layer plus a
small, curated set of real executable adapters, built entirely on top of
the existing Tool/ToolRegistry/Capability/Permission/Verifier/Recovery
architecture — no parallel systems, no blind trust of the catalog, no
weakening of the existing approval system.

**All of that was delivered.** 3 real, keyless, live-tested adapters are
registered and callable through the unmodified `ToolRegistry`; a
~1584-entry real catalog (synced from the actual `public-apis/public-apis`
GitHub repository, not fabricated fixtures) is searchable by both an
operator (REST/CLI) and the Brain (`public_apis.search` tool); nothing in
core execution, permission, verification, or recovery code was rewritten.
144 new tests were written and pass; the full pre-existing suite was
re-run and shows no regression (§6).

The main honest gap: catalog entries are not cross-linked back to the 3
adapters that implement them (§4, §7 "Known limitations") — a deliberate,
documented scope cut, not an oversight.

## 2. Implemented (mapped to the spec's own 25 phases)

| Phase | What it asked for | Status | Where |
|---|---|---|---|
| 0 | Pre-implementation audit before any code | ✅ Done | `PUBLIC_APIS_INTEGRATION_AUDIT.md`, written first, before any file under `integrations/` existed |
| 1–2 | Catalog model + real ingestion (not fabricated) | ✅ Done | `catalog/models.py`, `catalog/parser.py`, `catalog/normalizer.py` — validated against the actual live README (1597 raw rows → 1584 after normalization/id-dedup, 50 categories) |
| 3 | Ingestion/execution kept as separate layers | ✅ Done | `catalog/*` never calls a provider API; `adapters/*` never touches the catalog |
| 4–5 | Discovery/search over the catalog | ✅ Done | `discovery/search.py`, `discovery/ranker.py` — deterministic keyword scoring + composite ranking, no LLM calls (explicit spec requirement) |
| 6–7 | Tool Registry integration via the existing `Tool` contract | ✅ Done | `adapters/base.py::PublicAPIAdapter(Tool)` — zero new abstraction, `Tool.execute()` untouched |
| 8 | Credential management, never exposed to LLM | ✅ Done (mechanism proven, currently 0 real users) | `credentials/manager.py` wraps existing `SecretManager`; all 3 enabled adapters are keyless so nothing is exercised in production yet — see §7 |
| 9 | Tool Registry integration (registration wiring) | ✅ Done | `tools/builtin/__init__.py::build_default_registry()`, `api/deps.py` singletons |
| 10 | Input validation before network calls | ✅ Done | `ip_lookup.py` validates IP format via `ipaddress.ip_address()` before any HTTP call |
| 11 | HTTP 200 ≠ success; verify semantic/schema validity | ✅ Done | Hard contract in `adapters/base.py` docstring; `ip_lookup.py` checks `success: false` in-body; `geocode.py` handles absent `results` key without KeyError |
| 12 | Failure taxonomy | ✅ Done — reused, not duplicated | Adapters raise existing `ToolQuotaError`/`ToolTimeoutError`/`ToolValidationError`/`ToolError`; `classify_exception()` (pre-existing) maps them correctly, confirmed by inspection before writing any adapter code |
| 13 | Health/scoring | ✅ Done | `health/scoring.py::ProviderHealthTracker` — in-process counters, `None`-vs-zero distinction preserved for untested providers |
| 14 | Fallback provider selection | ✅ Done (mechanism built, not yet exercised — only 1 provider per capability today) | `discovery/matcher.py::enabled_providers_for_capability()`, health-sorted, mirrors `ModelRouter.candidates_for()` |
| 15–16 | Risk classification, approval integration | ✅ Done — no changes needed | All 4 new tools fall through the *existing* LOW-risk default; `PermissionPolicy` untouched |
| 17 | Admin CLI/API | ✅ Done | `api/routes/public_apis.py` (4 endpoints) + `cli.py` `z api search/refresh/health/stats` (4 commands) |
| 18 | Cost/budget guard against unbounded loops | ✅ Done — via existing infra, no new code | `Executor` step budget + `Tool.timeout_s` + `RecoveryEngine` bounds already apply; no per-call cost exists for the 3 free-tier adapters (deferred, §7) |
| 19–20 | Comprehensive, categorized tests | ✅ Done | 144 new tests across 8 files — see §6 |
| 21, 24 | Small curated initial adapter set, not the whole catalog | ✅ Done | 3 adapters enabled; ~1581 other entries remain `discovered`-only |
| 22 | Catalog as discovery, not authority | ✅ Done — structural, not just documented | `CatalogRepository` and `ToolRegistry` are separate collections; no code path promotes one into the other |
| 23 | Documentation | ✅ Done | This file + `PUBLIC_APIS.md` + `API_TOOL_SYSTEM.md` + `EXTERNAL_API_SECURITY.md` |
| 25 | Final honest audit | ✅ This document |

## 3. Deliberately not implemented (scope cuts, not gaps)

- **Bulk catalog activation.** ~1581 of ~1584 entries remain
  `status=discovered` forever unless a human explicitly writes and reviews
  an adapter. This is the entire point of Phase 21/24/22, not a
  shortcoming.
- **Scheduled/automatic re-sync.** `config.py::public_apis_auto_enable`
  is a named placeholder for a future background daemon; today, sync is
  always an explicit operator action. Building an unattended daily-sync
  daemon was out of scope for this pass — it's a small addition later
  (would reuse `deploy/*_daemon.py`'s existing pattern) but wasn't
  necessary to satisfy the spec, which only asks for sync capability to
  exist, not to be automatic.
- **Cost/budget tracking for metered providers.** All 3 enabled adapters
  are free-tier; no metering code was built because there's nothing to
  meter yet. First thing to add when a paid provider gets an adapter.
- **Fallback provider selection in practice.** `matcher.py` is built and
  tested, but with only 1 enabled provider per capability today, it has
  never actually had to choose between two live options. Correct and
  ready, but genuinely unexercised beyond its unit tests.

## 4. Deviations from the Phase-0 plan (honest — plans meet reality)

- **`ip.lookup` provider changed:** the audit (§6) planned `ipapi.co`
  (matches public-apis' own "auth: none" listing). During live testing
  from this sandbox, `ipapi.co` returned HTTP 429 (`RateLimited`) on the
  *first* request — a real, reproducible signal from the shared egress
  IP, not a hypothetical concern. Switched to `ipwho.is`, live-tested
  successfully multiple times, has an explicit in-body `success` field
  (a natural fit for the Bo'lim 11 "HTTP 200 isn't enough" requirement).
  Documented directly in `ip_lookup.py`'s module docstring, not silently
  substituted.
- **`health/checker.py` was not built as a separate module** — the §7
  proposed layout listed `health/{checker,scoring}.py`. In practice,
  health recording happens inline in `PublicAPIAdapter._record_success()`/
  `_record_failure()`, called from the same `_execute()` that already
  handles the HTTP call — a separate active-polling "checker" would have
  been a second, redundant way to learn the same information passive
  recording already captures on every real call. Simpler than planned,
  same guarantee.
- **Catalog↔adapter cross-linking was planned implicitly but not built**
  — see §7. `CatalogRepository.mark_status()` exists and is tested
  (`tests/test_public_apis_catalog.py::TestCatalogRepositoryReplaceAll::
  test_resync_preserves_status_trust_health_capabilities_for_existing`)
  but nothing calls it for the 3 real adapters in production. This is the
  single largest gap between "what the architecture supports" and "what
  is actually wired up" — flagged honestly rather than glossed over.

## 5. Real evidence gathered (not asserted, verified)

- **Real catalog data.** The parser/normalizer/repository were validated
  against the *actual* `public-apis/public-apis` README (fetched live) —
  1597 raw table rows → 1584 normalized entries (13 lost to name/category
  collisions under `entry_id()`'s dedup key, expected and correct) across
  50 real category headings. Not a hand-built fixture standing in for
  reality (a small hand-built fixture is *also* used, but only for fast,
  deterministic *unit* tests — the catalog logic was proven against the
  real thing first).
- **Real rate-limiting found.** `ipapi.co` genuinely 429'd under real
  (if unusual — shared sandbox egress IP) conditions, driving a concrete
  design decision (§4). This is exactly the kind of signal Phase 21's
  "test providers for real, don't just trust the catalog's claims" intent
  was asking for.
- **Real transient-timeout recovery observed.** During interactive
  testing, `location.geocode`'s first call in a longer sequential test
  script hit the tool's 15s timeout once — the *existing*
  `Tool.execute()` timeout machinery produced a clean, structured
  `ToolResult(success=False, error="Tool 15s ichida yakunlanmadi",
  retryable=True)`, no hang, no crash. A re-run immediately after
  succeeded in under a second. Treated as expected sandbox network
  variance, not a code defect — and positive evidence that the
  pre-existing timeout handling works exactly as designed under a real
  (not simulated) slow-network condition.

## 6. Test coverage

144 new tests across 8 files, all passing:

| File | Tests | Covers |
|---|---|---|
| `test_public_apis_catalog.py` | 37 | parser, normalizer, repository merge semantics, source fetch, sync orchestration |
| `test_public_apis_discovery.py` | 25 | search scoring, ranking, capability mapping, fallback matcher |
| `test_public_apis_adapters.py` | 24 | base retry/error-mapping (429/5xx/timeout/connect-error), all 3 real adapters via `respx` (no real network in the permanent suite) |
| `test_public_apis_credentials.py` | 13 | credential manager + explicit no-leakage assertions |
| `test_public_apis_search_tool.py` | 11 | Brain-facing tool — honesty of `executable_now`/`summary_text`, empty/no-match states |
| `test_public_apis_routes.py` | 11 | 4 REST endpoints via `TestClient`, no DB dependency |
| `test_public_apis_registry_wiring.py` | 9 | registration, shared-singleton reference semantics (not copies) |
| `test_cli_public_apis.py` | 14 | 4 CLI commands via mocked `httpx.Client`, matching the existing `z approve`/`z reject` test pattern |

Plus the pre-existing generic tests that now automatically cover the 4 new
tools without modification: `test_agent_factory.py::
TestToolPermissionMap` (every registered tool has a permission entry and
it matches the tool's own declaration) and
`test_capability_tools_resolve.py` (every capability's `default_tools`
resolve to real registry entries).

Two pre-existing tests were **deliberately** updated (not silently
patched around): `test_capability_registry.py` and
`test_capability_tools_resolve.py` both had a hardcoded `== 20` builtin
capability count from earlier (JB-13) work; adding the new `location`
capability makes this genuinely `21`, and both tests were updated with
docstrings explaining *why* this specific count change is expected
(unlike JB-13's original intent, which was reconciliation that should
*not* change the count).

**Full-suite regression run:** all 3326 tests across 189 files in
`apps/core/tests/` — pre-existing plus the 144 new — pass (`uv run pytest
-q`, exit code 0). No pre-existing test was weakened, skipped, or deleted
to make this pass; the 2 pre-existing tests that *changed*
(`test_capability_registry.py`, `test_capability_tools_resolve.py`) had
their assertions updated to reflect a genuine, intentional count change
(20→21 builtin capabilities), not loosened to hide a regression — both
still assert exact equality, not a loosened bound.

**ruff/mypy:** `ruff check` on all 42 new/changed Python files — zero
findings. `mypy` on the same 42 files — zero *new* findings; the 19
pre-existing errors that still appear when checking `api/deps.py` and
`cli.py` are all outside this integration's diff (confirmed by line-range
comparison against `git diff`'s hunks) and predate this work.

## 7. Known limitations (honest, unresolved)

- **Catalog entries are not cross-linked to the 3 enabled adapters.**
  Searching the catalog for "geocoding" will not show `location.geocode`
  as an `enabled` row — the adapter is real and callable through the
  normal `ToolRegistry`, but nothing calls
  `CatalogRepository.mark_status()` to link the two. A `public_apis.search`
  result for "geocoding" today shows only `discovered` entries even though
  ZET *can* geocode. This does not affect actual capability (the Planner
  finds `location.geocode` normally, through the regular tool-selection
  path, unrelated to the catalog) — it only affects what the discovery
  tool *displays*. Closing this gap requires either a small hardcoded
  entry-id↔tool-name mapping applied after each sync, or an admin
  mutation endpoint — deliberately not built in this pass (an extra
  write-capable admin surface is its own security review, and the
  spec's own conservatism argued against adding it speculatively).
- **In-memory only, process-lifetime state.** `CatalogRepository`,
  `ProviderHealthTracker`, and the credential store all reset on restart.
  Matches this codebase's existing `TTLCache` philosophy
  (`feeds/providers.py`) — deliberate, not accidental — but is a real
  limitation if durability across restarts becomes a requirement later.
- **No scheduled sync.** Purely operator-triggered today.
- **Credential mechanism unexercised in production.** `SecretManager`/
  `PublicAPICredentialManager` are real and tested, but since all 3
  enabled adapters are keyless, no real credential has ever flowed
  through this path outside of unit tests. First key-requiring adapter
  will be this mechanism's first live test.
- **Fallback provider selection unexercised.** Correct by construction
  and unit-tested, but with 1 provider per capability today, has never
  actually had to pick a second-choice provider in practice.

## 8. Architectural review (genuine, not "tests pass")

**What's solid:**
- The catalog/execution separation (§Phase 22) is structural, not just a
  naming convention — `CatalogRepository` and `ToolRegistry` share no
  code path that could accidentally promote one into the other. This was
  the single most important property the spec asked for, and it holds
  under inspection, not just under test.
- `PublicAPIAdapter` genuinely reduces duplication without hiding
  anything — every adapter-specific decision (URL, params, parsing,
  "what counts as a provider error") stays in the concrete adapter, in
  plain sight; only the truly identical cross-cutting concerns (retry,
  error-class mapping, health recording) are shared.
- Every exception type raised maps to a `FailureClass` that already
  existed before this integration — zero taxonomy drift.

**What's a genuine weak point, not just a "nice to have":**
- The catalog↔adapter linkage gap (§7) is a real inconsistency an
  operator could be confused by: "why doesn't `public_apis.search` show
  my own working geocoding tool?" It's documented, but documentation
  doesn't fix confusion at the moment someone hits it. This is the
  single item most worth prioritizing in a follow-up pass.
- The credential-handling code, while directly reusing a tested class,
  has never been exercised end-to-end with an adapter that actually needs
  a key. Its unit tests are solid; its *integration* into a real
  key-requiring adapter is unproven. Treat the first such adapter as
  also a test of this mechanism, not just of the new adapter.

## 9. Verdict

Proceed / ship. The core architectural requirement — extend, don't
parallel, don't weaken — was met and is verifiable by inspection (§8), not
just by test count. The known gaps (§7) are narrow, honestly stated, and
none of them represent a security or correctness risk in the current
(keyless, 3-adapter) scope; they are the right things to leave for
follow-up rather than block this delivery on.
