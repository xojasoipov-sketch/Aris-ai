# External API Security — public-apis integration (JB-18)

Credential handling, risk classification, failure taxonomy, and the
no-fabrication guarantees for the public-apis discovery/adapter layer.
Read alongside `docs/architecture/API_TOOL_SYSTEM.md` for how these pieces
are wired.

---

## 1. Credentials

**Current state: all 3 enabled adapters are keyless.** No credential
currently flows through any of the mechanisms below in production — this
section describes the *mechanism that exists and is tested*, for the day a
key-requiring provider gets its own adapter.

### 1.1 Storage

`integrations/public_apis/credentials/manager.py::PublicAPICredentialManager`
wraps the existing `security/secrets.py::SecretManager` — **not** a new
credential store. `SecretManager` was already built, tested
(`tests/test_security_bolim11.py`), and unused in production; this
integration is its first real caller. Provider credentials are namespaced
under a `public_apis:` key prefix so they can never collide with (or be
confused for) the fixed, `Settings`-backed service keys (Anthropic,
Telegram, GitHub, …) that live in the same underlying `SecretManager`
instance space.

### 1.2 What never happens

- A raw credential value is **never** returned from any REST endpoint —
  `api/routes/public_apis.py` has no route that could; `SecretMetadata`
  (the only structure exposed) has no field capable of holding one, only
  `masked_value` (last 4 characters).
- A raw credential value is **never** put in a prompt, in agent memory, or
  passed to the LLM. `get_value()` is the only way to obtain the real
  string, it is documented "internal use only," and the *only* legitimate
  caller is an adapter's `__init__` (resolve once, hold as an instance
  attribute, never re-fetch per-request, never expose the attribute).
- A raw credential value is **never** logged. `SecretManager.register()`
  logs the *name*, never the *value* (`log.info("secret.registered",
  name=name, id=meta.id)` — no `value=` kwarg exists anywhere in the
  class). Adapter error messages are built from `self.provider_name`
  (a static string) and the provider's response, never from the request
  URL/headers that might contain the credential.
- A raw credential value is **never** committed to git — it only ever
  exists in the in-process `SecretManager._values` dict, populated at
  runtime from an env var or an operator action, never from a file
  tracked by version control.

### 1.3 Tests

`tests/test_public_apis_credentials.py::TestCredentialValueNeverLeaksThroughMetadata`
locks this down directly: registers a real-looking secret value, then
asserts it does not appear anywhere in `status().model_dump()` or
`list_providers()` output — including as a substring (catches accidental
partial leaks, not just exact-match ones).

## 2. Risk classification

All 4 new tools (3 adapters + `public_apis.search`) are **READ, LOW risk**:

| Tool | Mutates state? | Permission | Risk |
|---|---|---|---|
| `location.geocode` | No | READ | LOW |
| `location.reverse_geocode` | No | READ | LOW |
| `ip.lookup` | No | READ | LOW |
| `public_apis.search` | No (reads in-memory catalog only) | READ | LOW |

This is the **existing** default (`security/risk.py::risk_for()` — no
entry needed in `TOOL_RISK_LEVELS`, since untabled tools already default to
LOW) — confirmed correct, not assumed: the audit checked this before
implementation (§1.5), and no change was made to `security/risk.py`. If a
future adapter *mutates* remote state (posts something, changes a
subscription, etc.), it must **not** inherit this default — it needs an
explicit `MEDIUM`/`HIGH` entry in `TOOL_RISK_LEVELS`, same as any other
write-capable tool in this codebase (e.g. `deploy.push`, `memory.write`).

`PermissionPolicy.requires_approval()` — completely unmodified —
auto-approves READ+LOW tools exactly as it already did for `weather.now`/
`currency.rate`. **No approval-engine code was touched by this
integration.**

## 3. HTTP execution safety

Implemented once, in `adapters/base.py::PublicAPIAdapter`, shared by every
adapter (see `docs/architecture/API_TOOL_SYSTEM.md` §4 for the full table):

- **Hard timeout, always.** `Tool.execute()` (unchanged, pre-existing)
  wraps every call in `asyncio.wait_for(timeout_s)`; `PublicAPIAdapter`
  sets `timeout_s = 15`. A hang cannot block the agent loop indefinitely.
- **Bounded retry for transient failures only.** `tenacity.AsyncRetrying`,
  `MAX_ATTEMPTS = 2` (1 + 1), exponential backoff (0.4s → max 2s).
  "Transient" is narrowly defined (`_is_transient()`): connection
  errors, connect/read timeouts, and HTTP 5xx. **Never** retried: HTTP 429
  (deterministic — retrying wastes another call against an already-hit
  quota) and other 4xx (deterministic — a malformed request doesn't
  become valid on retry).
- **429 → `ToolQuotaError`** (existing exception type,
  `retryable=False` — the `Executor` will not retry it either).
- **This local retry sits *underneath* `RecoveryEngine`'s slower,
  LLM-diagnosed step-level retry** — not a replacement for it. The local
  retry handles sub-second network blips; `RecoveryEngine` handles
  "this whole approach isn't working, try something else."

## 4. No fabrication — the hard contract

Bo'lim 11's explicit requirement, and this codebase's existing philosophy
(`feeds/providers.py::FeedError` — "source unavailable" beats a guessed
number). Applied here as a **hard contract each adapter must honor**,
stated directly in `adapters/base.py`'s docstring:

> If the provider responds HTTP 200 with an error marker in the response
> *body* (e.g. `{"success": false}`), `_call_provider()` itself must raise
> — an HTTP status code alone is not sufficient evidence of success.

Concretely: `ip_lookup.py` checks `data.get("success") is False` and
raises `ToolError` **before** returning anything — the generic `Verifier`
downstream never sees a fabricated "success" result. Every response field
that might be `None`/absent (e.g. `results` key missing entirely, `city`/
`isp` absent) is handled with `.get(...)`, never assumed present —
verified against the *real* live API responses during development (not
guessed from documentation), see `docs/audits/PUBLIC_APIS_INTEGRATION_FINAL.md`.

## 5. Failure taxonomy — reused, not duplicated

`core/failure_classification.py::FailureClass` already covered every case
Bo'lim 12 asks for. No new taxonomy was created. Adapters raise the
*existing* exception subtypes, which `classify_exception()` already maps
correctly:

| Adapter raises | → `FailureClass` |
|---|---|
| `ToolQuotaError` (429) | `RATE_LIMIT` |
| `ToolTimeoutError` (timeout, incl. after retry) | `NETWORK` |
| `ToolValidationError` (bad input, e.g. malformed IP — caught *before* any network call) | `VALIDATION` |
| generic `ToolError` (5xx after retry, other 4xx, malformed/error-marked body) | `TOOL` |

## 6. Logging discipline

`structlog` fields on every adapter call: `tool` (name), `latency_ms`,
success/failure — **never** the request URL with query params (which for
`ip.lookup` includes the queried IP but never a credential; for the 2
keyless geocode adapters there is no credential to leak in the first
place). No adapter logs a full response body — only counts and booleans
via `ProviderHealthTracker`.

## 7. Cost / budget

All 3 enabled adapters are free-tier, keyless services — no per-call cost
today, so no budget tracking was built for this MVP scope (explicitly
deferred in the audit, §"Cost/budget tracking: N/A for this scope"). The
**existing** bounds still apply and are sufficient for the current scope:
`Executor`'s per-run step budget, `Tool.timeout_s`, and
`RecoveryEngine`'s bounded retry count already prevent an unbounded loop of
calls to any tool, public-apis or otherwise. If a paid/metered provider is
added later, this is the first gap to close — see
`docs/integrations/PUBLIC_APIS.md` §7 "Known limitations."

## 8. See also

- `docs/architecture/API_TOOL_SYSTEM.md` — structural diagram, request
  paths.
- `docs/integrations/PUBLIC_APIS.md` — operator guide, how to add an
  adapter.
- `tests/test_public_apis_adapters.py`,
  `tests/test_public_apis_credentials.py` — the tests backing every claim
  in this document.
