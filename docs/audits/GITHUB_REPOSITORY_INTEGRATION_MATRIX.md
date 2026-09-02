# GitHub Repository Integration Matrix (JB-19)

One table, all 9 repositories the task named — replacing what would
otherwise have been nine separate integration write-ups, per the task's
own explicit "unified GitHub Intelligence Layer, not nine separate
integrations" rule. `public-apis`, `openclaw`, and `system-design-primer`
got deep, component-level audits (multiple rows each); the remaining six
are uniformly-treated knowledge sources (one row each — deeper
per-component breakdown would be disproportionate for pure reference
material, consistent with §"Knowledge sources should not unnecessarily
increase production complexity").

**Legend — Action:** KEEP (JARVIS's own is already better/sufficient) ·
ADAPT (pattern learned, reimplemented in ZET's own code — not copied) ·
IMPROVE (an existing JARVIS component gets a targeted enhancement) ·
INTEGRATE (a real, executable integration was built) · REFERENCE_ONLY
(knowledge source, queried via `web.search`/`web.read`, no code
extraction) · IGNORE (considered, not adopted, reasoned explicitly).

**Legend — Status:** SHIPPED (real code, merged, tested this pass) ·
RECOMMENDED (concrete, ready-to-implement, deliberately deferred to its
own reviewed task) · N/A (no implementation implied by the action).

---

## public-apis/public-apis

| Component | JARVIS equivalent | Quality comparison | Useful? | Risk | License | Action | Priority | Status |
|---|---|---|---|---|---|---|---|---|
| Full catalog (1584 APIs) | *(new)* `integrations/public_apis/catalog/` | N/A — new capability | Yes | Low (discovery only, no auto-execution) | MIT | INTEGRATE | P0 | **SHIPPED** (JB-18) |
| Discovery/ranking engine | *(new)* `integrations/public_apis/discovery/` | N/A — new | Yes | Low | MIT | INTEGRATE | P0 | **SHIPPED** (JB-18) |
| 3 curated adapters (geocode ×2, IP lookup) | *(new)* `integrations/public_apis/adapters/` | N/A — new tools | Yes | Low (READ, keyless) | MIT (catalog); provider ToS separately reviewed | INTEGRATE | P0 | **SHIPPED** (JB-18) |
| Credential management | `security/secrets.py::SecretManager` (reused, not duplicated) | JARVIS's existing, tested class was sufficient | Yes | Low | N/A | ADAPT (reuse) | P0 | **SHIPPED** (JB-18) |
| The other ~1581 catalog entries | N/A | N/A | Discovery-only, not executable | N/A — never executed | MIT | REFERENCE_ONLY | — | SHIPPED (as discovery data) |

Full detail: `docs/audits/PUBLIC_APIS_INTEGRATION_FINAL.md`.

## openclaw/openclaw

| Component | JARVIS equivalent | Quality comparison | Useful? | Risk of adopting | License | Action | Priority | Status |
|---|---|---|---|---|---|---|---|---|
| Memory provenance-first write security | `memory/store.py`, `TrustLevel` enum (exists, unused for this) | OpenClaw's is more complete; JARVIS has the primitive (`TrustLevel`) but doesn't gate `memory.write` with it yet | Yes — high value | Low (additive, uses existing enum) | MIT | ADAPT | **P0** | RECOMMENDED |
| Session/history redaction before read | `memory.search`, conversation-history tools | OpenClaw explicitly redacts; JARVIS's redaction depth unconfirmed | Yes | Low (additive) | MIT | ADAPT | P1 | RECOMMENDED |
| Desktop-control TOCTOU frame binding | `desktop.*` tools | OpenClaw has explicit staleness rejection; JARVIS's does not appear to | Yes | Low-Medium (touches an EXECUTE-risk tool) | MIT | IMPROVE | P1 | RECOMMENDED |
| Exec allowlist, stricter-of-two-configs | `security/permissions.py`, `shell.exec` (always-approve, no allowlist) | Different tradeoff, not strictly "better" — JARVIS is more conservative by default | Yes, but risky to add carelessly | **High** (any allowlist is an approval-skip mechanism) | MIT | ADAPT | P2 | RECOMMENDED, needs own audit first |
| Agent system (channel-binding personas) | `AgentRegistry`/`AgentSelector` (task-specialized) | Different axis, not comparable | No — solves a problem JARVIS doesn't have | N/A | MIT | ALREADY_EXISTS | — | N/A |
| Automation (Automations/Heartbeat/Tasks) | `AutomationDaemon`, DailyScheduleDaemon ("Kunlik puls") | Functionally equivalent already | No new gap | N/A | MIT | ALREADY_EXISTS | — | N/A |
| Background execution durability | `run_checkpoint.py`, `mission_recovery.py` | JARVIS arguably ahead (OpenClaw's exec sessions are explicitly non-durable) | No | N/A | MIT | ALREADY_EXISTS | — | N/A |
| State management (SQLite, single-writer) | Postgres throughout | JARVIS already ahead (client-server RDBMS vs. embedded single-machine) | No | N/A | MIT | ALREADY_EXISTS | — | N/A |
| Plugin architecture (in-process, unsandboxed) | No third-party plugin loader | JARVIS's closed model is safer; OpenClaw's own docs call native plugins "RCE-equivalent" | No — do not adopt | N/A | MIT | IGNORE (deliberate) | — | N/A |
| 30+ channel integrations | Telegram + Instagram DM | Deliberate scope difference, not a gap | No | N/A | MIT | IGNORE | — | N/A |
| Operator scopes (multi-client permission tiers) | Single `ZET_API_TOKEN` | Solves multi-tenant problem JARVIS doesn't have | No, for now | N/A | MIT | IGNORE | — | N/A |
| 4-axis provider/model/runtime routing + failover | `ModelRouter`, `core/model_routing.py` | Not evaluated for adoption | N/A | N/A | MIT | OUT OF SCOPE | — | Explicit prior instruction (JB-17): routing untouched |

Full detail: `docs/audits/OPENCLAW_JARVIS_COMPARISON.md`.

## donnemartin/system-design-primer

| Component | JARVIS equivalent | Quality comparison | Useful? | Risk | License | Action | Priority | Status |
|---|---|---|---|---|---|---|---|---|
| Observability (metrics/dashboard) | `structlog` + `ProviderHealthTracker` (narrow) + `/api/v1/system` | Real gap — no cross-system aggregate view | Yes | Low (additive endpoint extension) | CC BY 4.0 | IMPROVE | P1 | RECOMMENDED |
| Binary-artifact storage durability | Camera snapshots, TTS/STT audio, voice models | Not independently re-verified this pass | Unconfirmed | Unconfirmed | CC BY 4.0 | VERIFY (not yet classified) | P1 | RECOMMENDED (verify first) |
| Scalability (stateless horizontal scaling) | `api/deps.py` in-memory singletons | Real, named, **not urgent** structural constraint | Informational | N/A (no change without a real need) | CC BY 4.0 | KEEP (documented constraint) | — | N/A |
| Caching (cache-aside) | `TTLCache`, `ProviderHealthTracker`, `CatalogRepository` | Already correctly applied | No new gap | N/A | CC BY 4.0 | ALREADY_EXISTS | — | N/A |
| Queues/async | Native `asyncio`, mission checkpoint/recovery | JARVIS's approach is arguably better-fit than a generic queue for its actual need | No | N/A | CC BY 4.0 | ALREADY_EXISTS | — | N/A |
| CAP/consistency | Single Postgres, strongly consistent | Correct as-is for safety-critical data | No | N/A | CC BY 4.0 | KEEP (validated correct) | — | N/A |
| Failure handling | `Tool.timeout_s`, tenacity retry, `RecoveryEngine` | Appropriately scoped for current dependency count | No | N/A | CC BY 4.0 | ALREADY_EXISTS | — | N/A |
| Reliability/availability, load balancing, networking | Single instance, Railway-managed edge | Correctly not over-built (no SLA to justify it) | No | N/A | CC BY 4.0 | IGNORE (correctly) | — | N/A |
| Databases (replication/sharding) | Single Postgres, no replicas | Appropriately scoped; replica-first if ever needed | No | N/A | CC BY 4.0 | KEEP | — | N/A |

Full detail: `docs/audits/SYSTEM_DESIGN_JARVIS_REVIEW.md`.

## The GitHub Intelligence Layer itself (this pass's actual shipped code)

| Component | JARVIS equivalent | Quality comparison | Useful? | Risk | License | Action | Priority | Status |
|---|---|---|---|---|---|---|---|---|
| Source Registry (`KnowledgeSource`, trust levels) | *(new)* `integrations/github_intel/registry/` | N/A — new | Yes | Low (in-memory, no execution) | N/A | INTEGRATE | P1 | **SHIPPED** |
| Repository analyzer (`analyze_repository()`) | *(new)* `integrations/github_intel/analyzer/` | N/A — new, deliberately fact-only (no fabricated "design pattern" judgments) | Yes | Low (READ-only GitHub API calls) | N/A | INTEGRATE | P1 | **SHIPPED** |
| 3 Brain-facing tools (`github.search_repository`/`.analyze_repository`/`.compare_repositories`) | *(new)*, reuses existing `_GitHubHttpMixin` from `github.read`/`.write` | N/A — new, zero duplicate HTTP plumbing | Yes | Low (READ, LOW risk, never executes discovered code) | N/A | INTEGRATE | P1 | **SHIPPED** |

## Six reference-only knowledge sources (uniform treatment — see §"Why one row each")

| Repository | Category | License | Useful as | Risk of code reuse | Action | Priority | Status |
|---|---|---|---|---|---|---|---|
| codecrafters-io/build-your-own-x | Engineering reference | CC0-1.0 | Research Agent background reading for low-level-systems questions | N/A — never executed | REFERENCE_ONLY | P2 | SHIPPED (registered as a `KnowledgeSource`) |
| freeCodeCamp/freeCodeCamp | Learning resources | BSD-3-Clause | Same, for web-dev/algorithms questions | N/A | REFERENCE_ONLY | P2 | SHIPPED |
| EbookFoundation/free-programming-books | Knowledge base | CC-BY-4.0 | Book/documentation discovery (links/metadata only, never redistributed) | N/A | REFERENCE_ONLY | P2 | SHIPPED |
| nilbuild/developer-roadmap | Learning resources | **CC BY-NC-ND 3.0 + extra restrictions** (verified live — content reuse explicitly prohibited) | Roadmap topic references, link-only | **Would be a license violation to extract content** — flagged prominently in the seed data itself | REFERENCE_ONLY (strict) | P2 | SHIPPED |
| jwasham/coding-interview-university | Algorithms/CS | CC-BY-SA-4.0 | Developer Agent background for algorithm/complexity questions | Share-alike obligation if content were extracted (it isn't) | REFERENCE_ONLY | P2 | SHIPPED |
| practical-tutorials/project-based-learning | Learning resources | MIT | "Find a similar project" answers — link/description only, never cloned/executed | N/A | REFERENCE_ONLY | P2 | SHIPPED |

**Why one row each, not a deep per-component audit:** the task's own
text is explicit — *"Knowledge sources should not unnecessarily increase
production complexity"* and *"Do not turn JARVIS into an educational
website."* These six are queried, when relevant, through the **already
real and working** `web.search`/`web.read` tools (Research Agent) — no
bespoke per-repo scraper, downloader, or indexer was built for any of
them, deliberately avoiding six near-duplicate integrations for what is
functionally the same capability (point the LLM at a URL when the
question calls for it).

---

## Cross-cutting totals

- **Repositories audited:** 9/9 (all named in the task).
- **Deep, component-level audits:** 3 (public-apis, openclaw,
  system-design-primer) — the three flagged P0 in the task's own
  priority ordering.
- **Real, executable integrations shipped:** public-apis catalog+3
  adapters (JB-18) + the GitHub Intelligence Layer itself (this pass,
  3 tools + registry + analyzer).
- **Concrete, scoped recommendations for future work:** 4 (memory
  provenance gating, history redaction, desktop TOCTOU, observability
  extension) — all additive, all low-risk, all deliberately *not*
  implemented in this already-large pass; one flagged higher-risk item
  (exec allowlist) explicitly deferred pending its own dedicated audit.
- **Patterns explicitly considered and rejected:** third-party plugin
  loading, 30+ channel breadth, multi-operator permission scopes,
  microservices/sharding/queue infrastructure — each with a stated
  reason, not silently skipped.
- **License violations avoided:** one confirmed live (developer-roadmap's
  NC-ND terms) — caught by verification, not assumed.
