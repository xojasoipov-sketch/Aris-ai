# public-apis Catalog Integration

**Status:** production, MVP scope (3 enabled adapters, ~1584 discoverable
catalog entries). Part of JB-18.

This document explains what the integration *is*, what it *isn't*, how an
operator runs it day to day, and — the part every future contributor needs —
**how to add a new adapter without touching the Brain/Planner/execution
core.**

---

## 1. What this is

ZET can now do two distinct things with the [`public-apis/public-apis`](
https://github.com/public-apis/public-apis) GitHub repository:

1. **Discover.** Sync its README into a searchable, ranked local catalog
   (~1584 entries across 50 categories) that both an operator (REST/CLI)
   and the Brain (`public_apis.search` tool) can query. This is
   **read-only cataloguing** — nothing in the catalog is called.
2. **Execute (for a curated few).** Three hand-written, hand-reviewed
   `Tool` adapters — `location.geocode`, `location.reverse_geocode`,
   `ip.lookup` — are real, registered, callable ZET tools, exactly like
   `weather.now` or `crm.lead_list`.

**These two are structurally separate collections** (`CatalogRepository` vs.
`ToolRegistry`) and nothing auto-promotes an entry from one to the other.
Being *listed* in the catalog never means *callable* — see §5.

## 2. What this is not

- **Not** an auto-importer. The catalog holding 1584 entries does not mean
  ZET has 1584 new capabilities — it means ZET has 1584 things it can *tell
  you exist*, and 3 of them it can actually use.
- **Not** a trust signal. `public-apis` is a community-maintained list;
  entries are unverified third-party claims about auth/HTTPS/CORS. Nothing
  from the catalog is trusted until a human writes and reviews an adapter
  for it.
- **Not** a second tool system. Adapters are `zet.tools.base.Tool`
  subclasses registered in the same `ToolRegistry` as everything else.

## 3. The 3 enabled adapters

| Tool | Provider | Auth | What it does |
|---|---|---|---|
| `location.geocode` | Open-Meteo Geocoding (`geocoding-api.open-meteo.com`) | none | place name → lat/lon |
| `location.reverse_geocode` | BigDataCloud (`api.bigdatacloud.net`) | none | lat/lon → place name |
| `ip.lookup` | ipwho.is | none | IP → approximate geolocation |

All three: keyless, HTTPS, READ permission, LOW risk, auto-approved (same
tier as `weather.now`). All three raise a real `ToolError` subtype on
failure — never fabricated data (see `docs/security/EXTERNAL_API_SECURITY.md`
§"No fabrication").

**Why these three and not more:** see the audit
(`docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md` §6) — this sandbox cannot
register for paid/keyed accounts, and the task's own instruction is to
start with a small, curated, keyless set rather than "activate the entire
catalog." `ip.lookup`'s provider was switched from the originally-planned
`ipapi.co` to `ipwho.is` after live testing showed `ipapi.co` returning
HTTP 429 from this environment's shared egress IP — a real reliability
signal, documented in `ip_lookup.py`'s module docstring.

## 4. Operator workflows

### Sync the catalog

The catalog starts **empty** — nothing runs this automatically
(`config.py::public_apis_auto_enable` exists as a switch for a future
background job, but today there is no scheduled sync; an operator triggers
it explicitly):

```bash
z api refresh
# or
curl -X POST $ZET_API_URL/api/v1/public-apis/refresh -H "Authorization: Bearer $ZET_API_TOKEN"
```

Re-syncing **merges**, it does not overwrite: descriptive fields (name,
description, auth, HTTPS, CORS) update; evaluation fields (`status`,
`trust_score`, `health_score`, `capabilities`) are preserved for entries
that already existed. An operator's "I reviewed this" decision on an entry
survives every future sync.

### Search the catalog

```bash
z api search "currency conversion" --limit 5
# or
curl "$ZET_API_URL/api/v1/public-apis/search?q=currency&limit=5"
```

Returns ranked candidates with `status` (`discovered`/`enabled`/…) —
**always check `status`**; only `enabled` entries are real ZET tools.

### Check adapter health

```bash
z api health
```

Real, jarayon-lifetime call statistics per provider (`ipwho.is`,
`open-meteo-geocoding`, `bigdatacloud-reverse-geocode-client`) — success
count, failure count, timeouts, rate-limits, average latency. A provider
that has never been called simply doesn't appear (never a fabricated
"100% healthy").

### Catalog stats

```bash
z api stats
```

Total entries, categories, how many are `enabled`, last sync time/result.

## 5. The Brain's view: `public_apis.search`

The Planner can call `public_apis.search` (READ, LOW risk) the same way it
calls any other tool — for "is there an API for X"-type questions. Its
result is **explicitly, repeatedly labeled as discovery-only**: every
candidate carries `executable_now: true/false`, and the tool's own
`summary_text` spells out in Uzbek that a non-`enabled` result is *not*
something ZET can act on right now — present it as a suggestion, never as
a completed capability.

This wording exists on purpose: an earlier production incident this
session (JB-16 CASE B) was exactly this failure shape — the LLM assuming
a capability existed because it appeared in a "what can you do" listing.
`public_apis.search`'s design is a direct, deliberate defense against
repeating that mistake with a much larger, external, less-trustworthy list.

## 6. How to add a new adapter (without touching the Brain)

This is the intended extension path — no core file changes required.

1. **Pick a real, live-tested candidate.** Search the catalog
   (`z api search <topic>`), or browse it directly. Prefer keyless/HTTPS.
   **Actually call the provider once** (curl/httpx) before writing code —
   this session found a catalog-listed "no auth" provider that was in fact
   rate-limited from a shared IP; the catalog is a *lead*, not a guarantee.
2. **Write the adapter**: a new file under
   `apps/core/src/zet/integrations/public_apis/adapters/`, a class
   extending `PublicAPIAdapter` (`adapters/base.py`), implementing only
   `name`, `description`, `input_schema`, and `_call_provider()`. Follow
   the **hard contract** in `adapters/base.py`'s docstring: if the
   provider returns HTTP 200 with an error marker in the body, raise
   `ToolError` yourself — don't let it look like success (see
   `ip_lookup.py` for the canonical example).
3. **Register it** in `tools/builtin/__init__.py::build_default_registry()`
   — one `registry.register(YourNewTool(health_tracker=health_tracker))`
   call, next to the existing three.
4. **Add its permission** to `agents/eval.py::TOOL_PERMISSIONS` — this is
   the single most common thing to forget (it happened twice in this
   session); a missing entry fails
   `test_agent_factory.py::test_every_registered_tool_has_a_permission`
   immediately, which is the intended safety net.
5. **(Optional)** add a `Capability` entry in `core/capability.py` if the
   new tool should be discoverable as part of a multi-step Mission goal,
   not just directly callable.
6. **Write tests** mirroring `tests/test_public_apis_adapters.py` — respx
   for the HTTP layer, no real network calls in the permanent suite.
7. **If it needs a credential**, use
   `integrations/public_apis/credentials/manager.py::PublicAPICredentialManager`
   (wraps the existing `SecretManager` — see
   `docs/security/EXTERNAL_API_SECURITY.md` §"Credentials"). Never read an
   env var directly in the adapter; resolve the credential once at
   construction time, same as `TelegramChannelPostTool` already does for
   its bot token.

**Nothing in this list touches `core/brain.py`, `core/planner.py`,
`core/orchestrator.py`, `security/permissions.py`'s decision logic, or
`tools/registry.py`'s mechanics** — the whole point of building
`PublicAPIAdapter` on top of the existing `Tool` contract.

## 7. Known limitations (honest, as of this writing)

- **Catalog entries are not cross-linked to the 3 enabled adapters.** A
  `public_apis.search` for "geocoding" will *not* show `location.geocode`
  as an `enabled` catalog row, because the 3 MVP adapters were hand-built
  directly rather than derived from (and linked back to) a specific catalog
  entry ID. `CatalogRepository.mark_status()` exists and is tested, but
  nothing currently calls it in production — this is a deliberate scope
  cut, not an oversight, documented here so it isn't mistaken for a bug.
  The Planner still finds these 3 tools normally (they're in the regular
  `ToolRegistry`, unrelated to the catalog) — this limitation only affects
  what `public_apis.search`'s results *display*.
- **No scheduled/automatic re-sync.** `public_apis_auto_enable` in
  `config.py` is a placeholder switch for a future background daemon; today
  syncing is always an explicit operator action (`z api refresh`).
- **In-memory only.** `CatalogRepository`, `ProviderHealthTracker`, and the
  credential store all reset on process restart — deliberate, matching
  `feeds/providers.py::TTLCache`'s "always re-syncable, no durability
  needed" philosophy. If durability becomes a real requirement, this is the
  first thing to revisit.
- **Only 3 of ~1584 catalog entries are executable.** By design (§3) — see
  the audit for the reasoning; this is expected to grow incrementally, one
  reviewed adapter at a time, never in bulk.

## 8. See also

- `docs/architecture/API_TOOL_SYSTEM.md` — how the pieces fit together.
- `docs/security/EXTERNAL_API_SECURITY.md` — credentials, risk
  classification, failure handling, no-fabrication guarantees.
- `docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md` — the pre-implementation
  audit (Phase 0).
- `docs/audits/PUBLIC_APIS_INTEGRATION_FINAL.md` — the final, honest,
  post-implementation review.
