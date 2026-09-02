# System Design Primer — JARVIS Architecture Review (JB-19)

**Status:** deep audit, informational + recommendations. Per the task's
explicit instruction: *"Do NOT blindly convert JARVIS into microservices.
Use the simplest architecture that satisfies actual requirements."* This
review's conclusion, stated up front: **JARVIS's current architecture is
already close to appropriately scoped for its actual scale** (single
owner, not "web scale") — the primer's own anti-overengineering logic
(diagnose a bottleneck before applying a pattern) argues *against* most of
the patterns it documents being applied to JARVIS today, and this review
says so explicitly rather than manufacturing gaps to fill.

**Method:** a research agent fetched the actual
`donnemartin/system-design-primer` repository content (not generic
system-design knowledge) and extracted, per topic, exactly what the
primer recommends, what concrete failure it prevents, and — critically,
since the primer itself documents this — when each pattern is *overkill*.
Two of eleven requested topics (failure handling, observability) are
thin-to-absent in the primer itself; this is noted rather than silently
filled with unsourced generic advice. License: CC BY 4.0.

---

## 1. Scalability — the one real, concrete finding

**Primer's guidance:** horizontal scaling requires stateless servers
(*"servers should not contain any user-related data like sessions"*);
vertical scaling is the cheaper, simpler default until a *measured*
bottleneck says otherwise.

**JARVIS's current state, verified against the actual codebase:**
JARVIS's **critical, durable state is already correctly externalized** —
missions, runs, approvals, and the killswitch are Postgres-backed
(JB-10/JB-11 persistent mission recovery; killswitch DB persistence).
This is the hard part, and it's already done right.

The gap: `api/deps.py` holds several `@lru_cache(maxsize=1)`
**process-local, in-memory singletons** — `ProviderHealthTracker`,
`CatalogRepository` (public-apis), the rate limiter, and others. These
are deliberately ephemeral, cache-aside-style state (§3) — losing them on
restart is by design safe (a catalog re-sync or a health-counter reset
costs nothing correctness-wise) — but it does mean **JARVIS cannot
currently run more than one application instance concurrently without
each instance showing different answers** (e.g. "has the public-apis
catalog been synced?" would differ per replica).

**Verdict:** this is a real, named **scaling risk** — not a bug, a
structural precondition. **Not urgent**: JARVIS runs as a single Railway
instance for one owner; nothing today requires horizontal scaling. If
that ever changes, the fix is well-understood and cheap (move these
specific caches to Redis or a shared Postgres table) — exactly the
primer's own "solve it when the constraint is real" discipline.

## 2. Reliability & availability

**Primer's guidance:** fail-over/replication costs real complexity;
chasing 99.99%+ availability is only worth it against an actual SLA
(the primer's own "nines" table exists precisely to make this
concrete).

**JARVIS's current state:** single instance, no fail-over. Railway's own
platform-level restart-on-crash is the only redundancy.

**Verdict: appropriate, not a gap.** JARVIS has no measured or required
uptime SLA — it's a personal assistant for one owner, not a paid service
with a support contract. Active-passive fail-over would add real
complexity (the primer's own disadvantage: data-loss window if the
active node dies before replication) for an availability target nobody
has asked for. This is the primer's own philosophy applied correctly:
*don't build for nines you don't need.*

## 3. Caching

**JARVIS's current state:** already uses cache-aside-style patterns
appropriately — `TTLCache` (`feeds/providers.py`, in-process, no Redis,
explicitly justified as "this data can always be re-fetched, a shared
cache adds a dependency for no correctness benefit"), `ProviderHealthTracker`
and `CatalogRepository` (JB-18, same philosophy). This matches the
primer's own cache-aside definition and its explicit disadvantage
awareness (cold-start burst, staleness without a TTL) — both are already
handled (TTL-bounded, and cold catalog state is honestly reported as
"not yet synced," never fabricated).

**Verdict: ALREADY_EXISTS, appropriately scoped.** No new caching
opportunity identified.

## 4. Queues / asynchronous processing

**Primer's guidance, explicit:** *"inexpensive calculations and realtime
workflows might be better suited for synchronous operations, as
introducing queues can add delays and complexity."*

**JARVIS's current state:** no separate task-queue infrastructure
(Celery/RQ/etc.). Concurrency is native `asyncio` within the single
FastAPI process; long-running background work (`AutomationDaemon`,
`DailyScheduleDaemon`) runs as async tasks in the same process. The one
case a queue would normally exist for — "a long agent Mission must
survive a process restart" — is **already solved**, and arguably better
than a generic queue would solve it: JB-10/JB-11's persistent mission
checkpoint/recovery durably resumes exactly where a mission left off,
which a generic task queue does not give you for free.

**Verdict: ALREADY_EXISTS / correctly not built.** At JARVIS's current
call volume, a dedicated queue would be exactly the primer's own named
overkill case — added latency and operational complexity for work that
is neither expensive enough nor blocked on decoupling. Revisit only if a
specific, measured background-work volume starts contending with
request-handling capacity.

## 5. Databases

**JARVIS's current state:** single Postgres instance, no read replicas,
no sharding/federation. Per the primer's own ordering (SQL tuning →
master-slave replication → federation/sharding, roughly increasing cost
and decreasing reversibility), JARVIS hasn't needed to reach past the
first rung.

**Verdict: appropriately scoped.** No data-volume or query-load evidence
suggests JARVIS is anywhere near a single Postgres instance's ceiling.
**For the record, if this changes:** the primer's own guidance is to add
a **read replica first** (cheap, low-regret) — long before considering
federation or sharding (expensive, hard to reverse, application-wide
routing logic). No action needed now.

## 6. Load balancing

**Primer's own disadvantage, verbatim-adjacent:** a load balancer in
front of a single backend just adds a hop and a new failure mode for no
net availability gain — it needs to be redundant itself, or it's just
relocated the single point of failure.

**Verdict: N/A at current scale.** JARVIS runs one instance; anything
resembling TLS termination/edge routing is Railway's platform
responsibility, not JARVIS application code. Nothing to build.

## 7. CAP theorem / consistency patterns

**Primer's guidance:** CP ("atomic reads/writes") fits when correctness
of a *specific* transaction genuinely matters; AP (eventual consistency)
is fine, and normal, for most other data (the primer's own examples:
DNS, email).

**JARVIS's current state:** mission/run/approval/killswitch state lives
in one Postgres instance — **strongly consistent by construction**
(single writer, no async replication lag to reason about). This is
exactly right for this data: a race where a Mission proceeds despite a
killswitch flip that "hasn't propagated yet" would be a real safety bug,
not an acceptable staleness window.

**Verdict: correct as-is — explicitly validated, not just unexamined.**
No consistency risk identified for JARVIS's safety-critical data. The
in-memory caches from §1/§3 are the one place staleness is possible, and
that's an intentional, low-stakes tradeoff (a stale health counter is
never a correctness bug).

## 8. Failure handling

**Honesty note:** the primer itself barely covers this topic (no
circuit-breaker, backoff-as-a-named-pattern, or chaos-engineering
content) — this section leans on general engineering judgment more than
the other ten.

**JARVIS's current state:** hard per-tool timeout (`Tool.timeout_s`,
enforced via `asyncio.wait_for`, unconditional), bounded local retry for
transient network errors (`tenacity`, public-apis adapters, JB-18), and
`RecoveryEngine`'s slower, LLM-diagnosed step-level retry as the outer
layer. This is a real, working three-tier defense — not hypothetical: a
genuine transient timeout was observed live during JB-18 testing, and the
*existing* timeout machinery produced a clean, structured failure with no
hang and no crash, confirmed by direct observation.

**Verdict: appropriately scoped, not a gap.** No circuit breaker exists,
and none is recommended yet — JARVIS has a small, mostly-read-only set of
external dependencies, well within what a human operator can watch via
logs and the existing error/retry counters (`ProviderHealthTracker`).
Circuit breakers earn their cost once dependency count and call volume
exceed what a human can reasonably monitor — not there yet.

## 9. Observability — the one genuine, worth-flagging gap

**JARVIS's current state:** structured logging (`structlog`) is used
consistently throughout the codebase — a real, solid foundation. A
narrow, DIY observability primitive already exists for public-apis
adapters specifically (`ProviderHealthTracker`: call counts, success/
failure, latency). A `/api/v1/system` endpoint already reports real
(not fabricated) CPU/memory/uptime metrics (confirmed:
`test_system_routes.py` explicitly locks this down — the endpoint used to
report hardcoded fake values before that fix).

**What's missing:** no aggregate view of request latency, tool-call
success rate, or LLM-call latency *across the whole system* — only the
public-apis-specific slice has this today. No metrics/dashboard layer
(Prometheus-style `/metrics`, Grafana, or equivalent).

**Recommendation, scoped to match the primer's own anti-overkill logic**
(*"reach for full tracing once you can no longer answer 'why was this
request slow' from logs and dashboards alone"*): **extend the existing
`/api/v1/system` pattern** with a few more real, aggregate metrics (tool
success rate, average tool/LLM latency) rather than introducing a new
observability stack. This is additive, low-risk, and matches the
codebase's own established "real numbers or nothing" discipline for that
endpoint. **Not implemented in this pass** — flagged for a dedicated
follow-up (see `docs/audits/GITHUB_TOP_REPOS_FINAL_AUDIT.md`).

## 10. Storage — object vs. block vs. file (low-confidence flag)

JARVIS handles some binary artifacts (camera snapshots, generated
TTS/STT audio, voice model files). Whether these currently live on an
ephemeral container filesystem (lost on redeploy unless explicitly
volume-mounted) or a durable, mounted volume was **not independently
re-verified in this pass** — earlier session work mounted a volume
specifically for voice models, but camera snapshots/generated media were
not re-confirmed. **Flagged as worth verifying, not asserted as a bug.**

## 11. Networking (DNS/CDN/reverse proxy)

**Verdict: N/A.** TLS termination and edge routing are Railway's
platform responsibility; JARVIS's application code has no networking
layer of its own to build here.

---

## Explicit findings (per the task's own requested checklist)

| Category | Finding |
|---|---|
| Current bottleneck | **None measured.** No load testing was performed; this review is structural, not empirical. If one had to name where a bottleneck would *first* appear under growth, it's the single Postgres instance (§5) — but there's no evidence today's load is anywhere near it. |
| Single point of failure | The single Railway app instance and the single Postgres instance are both real SPOFs today. **Accepted, not a gap** — no measured availability requirement justifies the fail-over complexity the primer itself warns about (§2). |
| Scaling risk | Process-local in-memory singletons (§1) block horizontal scaling without a shared-cache migration first. Real, named, **not urgent**. |
| Data consistency risk | None for critical (mission/run/approval/killswitch) data — correctly strongly consistent (§7). The only staleness-tolerant state is the intentionally-ephemeral caches from §1, which is safe by design. |
| Queue requirement | None justified at current scale (§4) — existing mission-checkpoint recovery already solves the one case a queue would normally exist for, and arguably better. |
| Worker requirement | None justified at current scale — single-process async concurrency is sufficient; a separate worker process is a future option if `AutomationDaemon`-class background load ever contends with request handling, not needed now. |
| Cache opportunity | None new identified — existing cache-aside usage (§3) is already appropriately scoped. |
| Observability gap | Real, concrete (§9) — no cross-system latency/success-rate aggregate view. Recommended fix: extend `/api/v1/system`, not a new stack. |
| Recovery gap | None identified — `RecoveryEngine` + mission checkpoint/recovery + tenacity retry + hard timeouts form a coherent, evidence-backed (JB-18 live test) recovery story appropriate to current scale. |

## Conclusion

Per the task's own instruction not to force microservices or apply
scaling patterns speculatively: **this review recommends exactly one
concrete, additive change** (extend `/api/v1/system` with a few more
real aggregate metrics, §9) and **one thing worth verifying** (binary
artifact durability, §10). Everything else is either already correctly
built (durable critical state, appropriate caching, working recovery) or
correctly *not* built yet, because the traffic/scale that would justify
it does not exist. This is the primer's own philosophy — *"identify and
address bottlenecks, given the constraints... everything is a
trade-off"* — applied to JARVIS as it actually is today, not as a
larger system it might hypothetically become.
