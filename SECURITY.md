# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.3.x   | :white_check_mark: |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in mureo, please report it responsibly.

**Do NOT open a public GitHub issue.**

Instead, please use [GitHub's private vulnerability reporting](https://github.com/logly/mureo/security/advisories/new) to submit your report.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 5 business days
- **Fix release**: depends on severity, but we aim for:
  - Critical: within 7 days
  - High: within 14 days
  - Medium/Low: next scheduled release

### Scope

The following are in scope:

- `mureo` Python package (PyPI)
- MCP server implementation
- CLI tool
- Credential storage and handling
- OAuth flow implementation

### Out of scope

- Vulnerabilities in upstream dependencies (please report those to the respective maintainers)
- Issues in the managed/SaaS components (not part of this OSS project)

## Built-in Security Controls

mureo ships several layers of defense-in-depth designed for the
reality that AI agents drive marketing operations. Each layer
addresses a concrete class of attack that has been observed in the
wild against AI-assisted ad management.

### Credential guard (PreToolUse hook)

`mureo setup claude-code` writes a PreToolUse hook into
`~/.claude/settings.json` that blocks AI agents from reading
`~/.mureo/credentials.json`, `.env`, and similar secret files. This
prevents a prompt-injection payload from tricking the agent into
exfiltrating OAuth tokens or developer tokens via the file-system
tools.

### GAQL input validation

Every string that enters a Google Ads Query Language (GAQL) query
flows through a single whitelist-based validator
(`mureo/google_ads/_gaql_validator.py`). IDs must be numeric and
≤ 20 characters, dates must match `YYYY-MM-DD`, date-range
constants must be one of the 12 known Google values (`ALL_TIME` is
deliberately excluded to preserve the period-days guard), and
free-text literals are escape-sanitized with backslashes processed
before quotes. `_period_to_date_clause`'s `BETWEEN` branch
pattern-matches and revalidates both dates, so a caller passing
`BETWEEN '2024-01-01' AND '2024-01-31' OR 1=1` is rejected.

### Anomaly detection

`mureo/analysis/anomaly_detector.py` compares a live
`CampaignMetrics` snapshot against a median-based baseline built
from historical `action_log` entries and emits prioritized anomalies
for three high-signal failure modes:

- Zero spend on a previously-spending campaign (CRITICAL) — catches
  account lockouts, policy suspensions, and stopped campaigns.
- CPA spike ≥ 1.5× baseline (critical at 2×) — catches rogue
  bidding, broken landing pages, and unintended mass-negative-keyword
  removals.
- CTR drop ≤ 0.5× baseline (critical at 0.3×) — catches creative
  rotation failures and audience drift.

Sample-size gates (30+ conversions for CPA, 1000+ impressions for
CTR) follow the `mureo-learning` skill's statistical-thinking rules
to suppress single-day noise.

Agents invoke the detector via the `analysis.anomalies.check` MCP
tool, which composes `baseline_from_history` with `detect_anomalies`
behind a single call. Safety properties of the MCP surface:

- `current.campaign_id` and `current.cost` are required, so a
  zero-spend alert is always an intentional zero rather than the
  product of an omitted field.
- Numeric fields accept int / float / numeric-string and reject
  non-numeric strings (`"N/A"`) and booleans, so a malformed
  current-snapshot fails loudly instead of silently disabling
  detection.
- `state_file` resolves strictly inside the MCP server's current
  working directory. Absolute paths that escape, `..`-traversal, and
  symlinks that cross CWD boundaries are all refused, so a
  prompt-injected agent cannot redirect the tool at an
  attacker-crafted history.
- A parse-error on STATE.json does not silence live zero-spend
  detection; the response carries a `baseline_warning` so the agent
  can flag the unreliable baseline to the operator.

### Rollback with allow-list gating

`mureo/rollback/` turns agent-authored `reversible_params` hints in
the action log into concrete `RollbackPlan` records. Because the
agent writes those hints, they are untrusted input for the rollback
executor; without hardening, a prompt-injected agent could log a
"reversal" that points to a destructive tool.

The planner enforces:

- An explicit allow-list of operations (budget update + status
  toggles across Google / Meta Ads). Anything outside it is refused.
- Destructive verbs (`.delete`, `.remove`, `.destroy`, `.purge`,
  `.transfer`) are refused even if they lexically match.
- `params` keys must be a subset of the per-operation allowed key
  set, so a budget-update reversal cannot smuggle keys like
  `login_customer_id`.

`mureo rollback list` / `mureo rollback show` let operators preview
plans before any execution. The CLI is read-only — executing a
plan stays with the MCP dispatcher so it re-enters the same policy
gate as forward actions. Control characters from STATE.json are
stripped before terminal output to prevent ANSI-escape spoofing by
a compromised agent.

Execution is exposed to agents via two MCP tools:

- `rollback.plan.get` returns the planner's verdict (`supported` /
  `partial` / `not_supported`), the operation that would be
  dispatched, its parameters, and any caveats. Read-only.
- `rollback.apply` executes the plan by re-dispatching
  `plan.operation` with `plan.params` through the same
  `handle_call_tool` used for forward actions, so the reversal call
  re-enters the full policy gate (auth, rate limit, GAQL validation,
  planner allow-list).

Additional hardening on the executor:

- `confirm` must be the literal boolean `True`. Truthy non-booleans
  (`1`, `"true"`, non-empty lists) are refused, so an agent that
  bypasses the MCP schema validator still cannot smuggle an apply
  call with a coerced affirmative.
- The planner is re-invoked at execution time rather than cached, so
  a stale allow-list decision can never be smuggled in via the log.
- `plan.operation` starting with `rollback.` is refused as
  defense-in-depth, preventing recursion into the rollback surface
  even if a future allow-list entry accidentally names a rollback
  tool.
- A successful apply is recorded as an append-only `ActionLogEntry`
  tagged with `rollback_of=<index>`. The appended entry carries
  `reversible_params=None` so rollbacks of rollbacks do not chain by
  default; a second apply of the same index is refused.
- `state_file` resolves strictly inside the MCP server's current
  working directory (same sandbox as `analysis.anomalies.check`) so
  an attacker-controlled `STATE.json` outside the project cannot be
  used as the reversal source.
- Dispatch-time API failures never mutate `action_log`; the
  downstream exception is logged server-side only, and the MCP
  response returns a generic message (only `type(exc).__name__`) so
  tokens and account identifiers cannot leak into model context.

### Browser-based auth wizard (`mureo auth setup --web`)

Non-technical operators completing OAuth setup use the browser
wizard, which runs its own short-lived HTTP server on the machine.
Because the server accepts the operator's raw secrets (Developer
Token, OAuth Client Secret, App Secret) before forwarding the OAuth
leg, the wizard is hardened layer-by-layer:

- **Localhost-only bind.** The listening socket is always
  `127.0.0.1` on a random OS-assigned port. The `redirect_uri` fed
  to `google_auth_oauthlib` and `build_meta_auth_url` is validated
  against an allow-list (`127.0.0.1` / `localhost`), so a compromised
  call site cannot redirect OAuth grants to a remote host.
- **DNS-rebinding guard.** Every POST / callback handler inspects
  the `Host:` header and rejects anything that isn't
  `127.0.0.1:<port>` or `localhost:<port>`, defeating browsers that
  resolve `attacker.com` to `127.0.0.1`.
- **CSRF protection.** Each form POST carries a hidden `csrf_token`
  compared with `secrets.compare_digest`. The token rotates after
  every successful submit so the same value cannot be replayed from
  another tab or a Back-button resubmission.
- **OAuth `state` verification.** `state` is generated at submit
  time, stashed in the in-memory session, and compared with
  `secrets.compare_digest` when Google / Meta redirects back. A
  third-party link trick that sends a victim's browser to
  `/<provider>/callback?code=ATTACKER_CODE` is refused.
- **Redirect-origin pinning.** The wizard refuses to emit a 302
  unless the destination starts with `https://accounts.google.com/`
  (Google flow) or `https://www.facebook.com/` (Meta flow), so the
  wizard can never become an open redirect.
- **Generic error surface.** `except Exception` paths log the full
  traceback via `logger.exception` server-side and render a
  templated error page in the browser. Raw SDK error text never
  reaches the operator's browser.
- **Session zero-out.** After `save_credentials` succeeds, the
  wizard clears `developer_token` / `client_id` / `client_secret`
  / `app_id` / `app_secret` / OAuth state from its in-memory
  session dataclass so the values don't linger through the rest of
  the process lifetime.
- **POST size cap.** Request bodies over 16 KiB are refused with
  413 to prevent a local attacker from OOM-ing the process.
- **Defensive HTTP headers.** Responses carry
  `Content-Security-Policy: default-src 'none'; style-src
  'unsafe-inline'; base-uri 'none'; frame-ancestors 'none';
  object-src 'none'; form-action 'self' https://accounts.google.com`,
  plus `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  and `X-Content-Type-Options: nosniff`.
- **Stdlib only.** The wizard uses `http.server` + `urllib` — no
  external web framework — eliminating supply-chain exposure for
  the install path.

### Immutable data models

All dataclasses that represent campaign state, action log entries,
strategy context, and anomalies use `frozen=True`. Mutation attempts
fail fast with `FrozenInstanceError`, preventing an agent from
silently altering its own record of what happened or what was
decided.

### Local-only credential storage

Credentials are loaded from `~/.mureo/credentials.json` or
environment variables and never transmitted anywhere except the
official Google Ads, Meta Ads, and Search Console APIs. mureo itself
has no telemetry or phone-home behavior.

## Security Best Practices for Users

- Never commit `~/.mureo/credentials.json` to version control
- Use environment variables for CI/CD environments
- Rotate OAuth tokens periodically
- Keep mureo updated to the latest version
- Run `mureo setup claude-code` (not a bare `mureo auth setup`) so
  the credential guard hook is installed alongside your MCP config
