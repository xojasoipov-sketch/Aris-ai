# OpenClaw vs. JARVIS — Architecture Comparison (JB-19)

**Status:** deep audit, informational + recommendations. No OpenClaw code was
copied into JARVIS; per the task's explicit rule, this document classifies
what to reuse, adapt, improve, or ignore — implementation of any
non-trivial, security-sensitive item is deliberately deferred to its own
dedicated, reviewed task (see §6).

**Method:** a research agent cloned `github.com/openclaw/openclaw` directly
(`git clone --depth 1`) and read real source files, real SQL schema files
(`CREATE TABLE` statements, not prose descriptions), `LICENSE`,
`SECURITY.md`, `package.json`, and the full documentation tree — not just
the README or marketing copy. Confidence is marked per section in the
underlying research; everything below is HIGH confidence unless noted.
OpenClaw is real: `openclaw/openclaw`, MIT license, ~387k stars, created
2025-11-24, actively developed (last push same day as this audit).

---

## 1. What OpenClaw is

A TypeScript, Node.js, multi-channel (30+ platforms: Telegram, Discord,
Slack, WhatsApp, Signal, iMessage, Matrix, …) personal AI-assistant
gateway. Single embedded agent runtime with persona-per-`agentId`
composition, channel→agent routing via **bindings**, an unusually deep
5-tier memory architecture, a multi-layer tool-execution safety stack
(policy → exec-approvals → sandbox → elevated-mode escape hatch), an
open cross-vendor skill format, and a 4-axis (provider/model/
agent-runtime/channel) provider architecture with 2-stage failover.

**Explicitly, by its own `SECURITY.md`**: *"local-first agent
infrastructure for trusted operators; not designed as a shared
multi-tenant boundary between adversarial users."* Native plugins are
unsandboxed, in-process, full-trust code (openly stated to be
"equivalent to arbitrary code execution"). Sandboxing exists but is
**off by default**.

## 2. What JARVIS/ZET is (for this comparison's purposes)

A Python/FastAPI, single-owner personal AI operations system — Brain
(`core/brain.py`) → Planner (`core/planner.py`) → Executor
(`core/executor.py`) → `ToolRegistry` (`tools/registry.py`), with
`PermissionPolicy`/`ApprovalService`/`KillSwitch` (`security/`) gating
every write/execute action, `Verifier`/`RecoveryEngine` closing the loop,
`AgentSelector`/`AgentRegistry` for task-specialized (not
channel-specialized) agents, Postgres-backed persistence throughout
(sessions, runs, memory, approvals — not SQLite), and a single primary
channel (Telegram) plus Instagram DM automation. Single API bearer token
(`ZET_API_TOKEN`), not a multi-scope operator system.

This difference in **scope and trust model** — OpenClaw is a general
multi-channel bot platform for potentially many humans/clients connecting
to one gateway; JARVIS is a single-owner assistant — explains most of the
"IGNORE" verdicts below. A pattern solving a problem JARVIS doesn't have
is not a gap.

---

## 3. Component-by-component classification

| OpenClaw area | JARVIS equivalent | Verdict | Why |
|---|---|---|---|
| Agent system (persona-per-channel-binding) | `AgentRegistry`/`AgentSelector`/`agents/builtin/*` (task-specialized, not channel-specialized) | **ALREADY_EXISTS** (different axis) | Different problem: OpenClaw routes *channels* to *personas*; JARVIS routes *tasks* to *specialists*. Not directly comparable, no gap. |
| Tool system — policy/approval stack | `PermissionPolicy` + `ApprovalService` + `KillSwitch` | **ADAPT** (future) | See §4.1 — exec-allowlist pattern, not implemented this pass. |
| Memory — provenance-first write security | `memory/store.py`+`pg_store.py`, existing `TrustLevel` enum | **ADAPT** (recommended, concrete) | See §4.2 — highest-value, lowest-risk recommendation in this audit. |
| Memory — "dreaming" consolidation | `memory/summarizer.py`, `memory/scoring.py` | **REFERENCE_ONLY** (too large for this pass) | Genuinely interesting; a multi-week feature on its own, not a JB-19-scope item. |
| Message handling — dedupe/debounce | `core/orchestrator.py`, Telegram polling | **IMPROVE** (verify, low confidence) | Worth confirming JARVIS dedupes redelivered Telegram updates after reconnect; not confirmed missing, not confirmed present. |
| Message handling — session history redaction | `memory.search`, conversation history tools | **ADAPT** (recommended, concrete) | See §4.3. |
| Channels (30+ platforms) | Telegram + Instagram DM | **IGNORE** | JARVIS is intentionally single-owner, not a multi-channel bot platform. Building 30 channel integrations is explicit scope creep the task's own philosophy warns against. |
| Automation (Automations/Heartbeat/Tasks split) | `AutomationDaemon`, `automation/scheduler.py`, DailyScheduleDaemon ("Kunlik puls"), workspace task board | **ALREADY_EXISTS** | JARVIS's existing daily-pulse feature is functionally OpenClaw's Heartbeat concept; task/project board is a comparable audit ledger. No action needed. |
| Execution model — container sandboxing (opt-in, hardened) | `shell.exec` — EXECUTE permission, approval required on **every** call | **ADAPT** (future hardening) | JARVIS's default posture (always-approve) is already stricter than OpenClaw's default (full-trust, sandbox off). Container-level sandboxing would be defense-in-depth, not urgent. |
| Computer interaction — TOCTOU frame verification | `desktop.*` tools (`PyAutoGUIDesktop`) | **IMPROVE** (concrete, recommended) | See §4.4 — a specific, nameable vulnerability class. |
| Skills (SKILL.md, dynamically loaded) | Tools + agent system prompts (static, code-defined) | **IGNORE** (for now) | Functional need already covered by the Tool/Capability system; building a dynamic skill-loading marketplace is disproportionate effort for this pass. |
| Permissions — operator scopes (read/write/admin/pairing/…) | Single `ZET_API_TOKEN` bearer token | **IGNORE** | Solves "multiple humans/clients on one gateway" — not JARVIS's current deployment shape. Revisit only if JARVIS adds multiple operators. |
| Sessions — multi-user DM isolation | N/A (single owner) | **IGNORE** | No multi-user problem to solve. |
| Background execution — task ledger | `run_checkpoint.py`, `mission_recovery.py` (JB-10/11) | **ALREADY_EXISTS** (JARVIS arguably ahead) | JARVIS's persistent mission/run recovery is durable by design; OpenClaw's backgrounded exec sessions are explicitly non-durable (in-memory, restart-fragile). |
| State management (SQLite, single-writer, single-machine) | Postgres throughout | **ALREADY_EXISTS** (JARVIS already ahead) | JARVIS's client-server RDBMS choice is the more scalable option OpenClaw's own docs frame as a real ceiling of their SQLite-only design. |
| Plugin architecture (in-process, unsandboxed native plugins) | No third-party plugin loader — all tools reviewed, committed to the ZET repo | **IGNORE** (deliberately) | OpenClaw's own `SECURITY.md` calls native plugins "equivalent to RCE." JARVIS's closed-tool-registry model is *already* the safer choice — do not add a third-party plugin-loading mechanism to chase this "feature." |
| Provider architecture — 4-axis routing + 2-stage failover | `ModelRouter` (`llm/router.py`, `core/model_routing.py`, JB-7) | **OUT OF SCOPE** (explicit prior instruction) | The user explicitly said "leave model/tier routing untouched" earlier this session (JB-17 clarification, real-money cost) — noted here for completeness, not touched. |

---

## 4. Concrete recommendations (not implemented this pass — see §6)

### 4.1 Exec allowlist with stricter-of-two-configs semantics

OpenClaw's `tools.exec.mode` (`deny`/`allowlist`/`ask`/`auto`/`full`) with
glob+argv-regex per-command allowlisting, where the *effective* policy is
always the **stricter** of declared config and a separate host-local
document (config alone cannot loosen host policy), is a genuinely good
pattern for reducing approval fatigue on known-safe command patterns
(`git status`, `ls`, read-only `kubectl get`) while keeping everything
else gated exactly as today.

**Why not implemented now:** JARVIS's current model — every `shell.exec`
call requires human approval, no exceptions — is a deliberately
conservative default that the task's own "Do NOT weaken existing
approval logic" instruction protects. An allowlist mechanism, even a
well-designed one, is by definition a way to *skip* approval for some
calls — this needs its own dedicated audit, threat model, and test suite
before touching `security/permissions.py` or `tools/builtin/shell_exec.py`,
not a bolt-on at the tail of an unrelated task.

### 4.2 Provenance-first memory writes (highest-value, lowest-risk)

OpenClaw's memory system's core security property, stated verbatim in
their docs: *"the write path is the security boundary, not content
scanning."* Every memory entry carries a structural **origin class**
(`owner`/`agent`/`untrusted`/`system`) the model cannot write through
prose, and untrusted-origin content is **structurally excluded before any
promotion scoring runs** — no amount of "this got recalled a lot" can
promote content that originated from an untrusted source into curated,
always-injected memory. This directly implements OWASP Agentic
Applications ASI06 and defends against the MINJA memory-poisoning attack
class (arXiv:2503.03704).

**Why this maps cleanly onto JARVIS:** `zet.domain.enums.TrustLevel`
(SYSTEM/UNTRUSTED) **already exists** and is already attached to every
`ToolResult` (A-05, this codebase's own long-standing decision). The gap
is narrower than it looks: `memory.write`
(`tools/builtin/memory_write.py`) does not currently appear to gate what
gets written based on the trust level of the content's origin. This is a
**small, surgical, high-value change** — reject or flag (never silently
promote) a `memory.write` call whose content traces back to an
UNTRUSTED-trust-level tool result, mirroring an existing, already-tested
codebase concept rather than importing a new one.

**Why not implemented now:** `memory.write` is a load-bearing, widely-used
tool (Obsidian bridge, note-write shadow, agent working memory) — a
change to its write-acceptance contract deserves its own audit-first pass
(mirroring how `public_apis` got a dedicated Phase-0 audit before any
code), not a rushed addition here. **This is the single most
recommended follow-up task from this entire audit.**

### 4.3 Redact credential-like content from history/memory reads

OpenClaw's `sessions_history` tool explicitly returns *"a bounded,
redacted view, not a raw transcript dump"* — stripping thinking-block
signatures, tool-result payload details, and credential/token-like text
before the model or an API client can read history.

**Recommendation:** verify (and if missing, add) the same discipline to
`memory.search`/conversation-history-reading tools and any REST endpoint
that returns transcript data — a simple regex/pattern scan for
`api_key`/`token`/`bearer`/`password`-shaped substrings before returning
history, on top of (not instead of) the existing "never log a raw
credential" discipline already established for `SecretManager`/
`PublicAPICredentialManager` (JB-18).

### 4.4 TOCTOU protection for desktop-control tools

OpenClaw's computer-use tools require every click/type action to echo
back the exact `frameId`/`screenIndex` from the most recently taken
screenshot; a display change between screenshot and action fails the
action closed rather than silently retargeting a click at whatever is now
on screen.

**Recommendation:** `desktop.mouse_click`/`desktop.type_text` should
carry (or be preceded by) a similar staleness check — e.g. a screenshot
hash/timestamp the action must reference, rejected if stale — closing a
real class of "the screen changed between planning and acting" bug that
`desktop.*` tools do not appear to currently guard against.

---

## 5. What was deliberately NOT adopted, and why

- **Third-party plugin loading.** OpenClaw's own security documentation
  frames in-process native plugins as equivalent to full RCE. JARVIS's
  closed, hand-reviewed tool registry is the safer design; adding a
  plugin loader to "catch up" on extensibility would be a regression, not
  an improvement.
- **Multi-channel platform breadth.** 30+ channels is OpenClaw solving a
  different product problem (universal bot hosting). Scope creep here
  directly contradicts this task's own "optimize for how much better
  JARVIS becomes, not how many repos/features we copy" closing rule.
  ZET's channel investment should stay proportional to what its single
  owner actually uses (Telegram, Instagram).
- **Multi-tenant permission scoping.** JARVIS is single-owner today, so
  OpenClaw's multi-user-DM-isolation and multi-operator-scope systems
  solve a problem that does not yet exist — worth revisiting only if
  JARVIS's deployment model changes to serve more than one human.
- **SQLite-only state.** JARVIS's Postgres choice is already the more
  scalable direction OpenClaw's own docs acknowledge as a structural
  ceiling of their design (single-writer, single-machine, explicit OS
  process lock). Nothing to adopt here.
- **Model/provider routing changes.** Explicitly out of scope per a
  standing instruction earlier this session (JB-17: "leave routing
  untouched, real-money cost").

## 6. Follow-up work (not this pass)

In priority order, for a dedicated future task:

1. **Memory provenance gating** (§4.2) — highest value, uses an existing
   concept (`TrustLevel`), narrowest surface (`memory.write`).
2. **History/memory-read redaction** (§4.3) — small, additive,
   low-risk.
3. **Desktop TOCTOU protection** (§4.4) — concrete, scoped to
   `desktop.*` tools.
4. **Exec allowlist** (§4.1) — highest value but also highest risk;
   needs its own full audit/threat-model/test pass before any code.
5. **Message dedupe verification** — confirm current behavior first;
   only build something if a real gap is confirmed.

None of these were implemented in this JB-19 pass — see
`docs/audits/GITHUB_TOP_REPOS_FINAL_AUDIT.md` for the honest final
accounting of what *was* shipped this pass (the GitHub Intelligence
Layer itself) versus what remains a researched, ready-to-scope
recommendation.

## 7. License

OpenClaw is MIT-licensed (confirmed by reading the actual `LICENSE` file,
not a badge — "Copyright (c) 2026 OpenClaw Foundation"). MIT permits code
reuse with attribution. This audit nonetheless recommends **pattern
adaptation, not code copying**, for every item above — consistent with
this task's explicit "do not blindly copy code" rule regardless of
license permissiveness; the value here is in the documented *design
reasoning* (provenance-first writes, stricter-of-two-configs, TOCTOU
frame binding), which is naturally reimplemented against JARVIS's own
types and conventions rather than ported verbatim.
