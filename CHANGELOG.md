# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `mureo setup codex` now installs bundled workflow commands as Codex **skills** at `~/.codex/skills/<command>/SKILL.md` (with YAML frontmatter — `name:` / `description:`) instead of as custom prompts at `~/.codex/prompts/*.md`. Codex CLI 0.117.0 (2026-03) [stopped rendering the custom-prompts directory](https://github.com/openai/codex/issues/15941) in its slash-command menu, so `mureo setup codex` was silently installing ten files that Codex no longer picked up. Users invoke the workflows with `$daily-check` (explicit) or the `/skills` picker. Re-running `mureo setup codex` also removes the stale `~/.codex/prompts/<bundled>.md` files left behind by prior installs; user-authored prompts with names outside mureo's bundled set are preserved.

### Changed
- Docs refreshed for the browser-based wizard: `README.md` / `README.ja.md` "Claude Code Desktop" section now points at `mureo auth setup --web` and no longer instructs operators to open `Terminal.app`. `docs/cli.md` documents both terminal and `--web` modes of `mureo auth setup`. `SECURITY.md` gains a "Browser-based auth wizard" section enumerating every hardening layer (localhost bind, DNS-rebinding guard, CSRF rotation, OAuth `state` validation, redirect-origin pinning, generic error surface, session zero-out, POST size cap, CSP/X-Frame-Options/Referrer-Policy headers, stdlib-only implementation).

### Added
- Meta Ads support in the browser-based OAuth wizard. The home page now offers both "Configure Google Ads" and "Configure Meta Ads" buttons; `/meta-ads` renders an App ID / App Secret form with inline deep links to Meta for Developers; the submit handler redirects to Facebook's OAuth dialog and the same wizard server receives the callback on `/meta-ads/callback`. After token exchange (short-token → 60-day long-lived token) the server writes `~/.mureo/credentials.json` (`meta_ads` block) and marks the wizard complete. All security guarantees from P2-2 apply symmetrically: CSRF rotation after submit, `state` validated with `secrets.compare_digest` on callback, Host-header check for DNS-rebinding, redirect origin pinned to `https://www.facebook.com/`, POST size capped at 16 KiB, session secrets zeroed after save, and graceful handling of Facebook's `error=` / `error_reason=` user-decline callbacks.
- Public `build_meta_auth_url(app_id, redirect_uri, state)` and async `exchange_meta_code(code, app_id, app_secret, redirect_uri)` helpers in `mureo/auth_setup.py` so the CLI and web paths share the same Facebook OAuth scaffolding. Localhost-only redirect URI validation mirrors the Google path. The legacy `_generate_meta_auth_url(port, state=None)` wrapper is kept for backward compatibility with existing tests.
- `mureo auth setup --web` — browser-based OAuth wizard for non-technical users. Starts a short-lived localhost HTTP server on a random port, opens the browser to a simple HTML form for Developer Token / OAuth Client ID / Client Secret, redirects to Google's own sign-in, receives the callback on the same wizard server, and writes `~/.mureo/credentials.json` — all without the operator opening a terminal. Inline deep links point at Google Cloud Console / Google Ads API Center so users know where to fetch each secret.
- Security hardening for the wizard: CSRF token rotates after every successful submit (replay guard); OAuth `state` parameter is stored at submit time and re-validated with `secrets.compare_digest` on callback; `Host` header must match `127.0.0.1:<port>` or `localhost:<port>` (DNS-rebinding guard); redirect URL is verified to start with `https://accounts.google.com/` before emitting 302 (open-redirect guard); session secret fields are zeroed after `save_credentials` succeeds; CSP includes `default-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`, `object-src 'none'`, and `form-action 'self' https://accounts.google.com`; responses also set `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`; POST bodies over 16 KiB are refused with 413; exception messages from OAuth failures are logged server-side only — the browser sees a generic retry hint.

### Changed
- `mureo setup claude-code` / `cursor` / `codex` / `gemini` are now TTY-safe. When run from an AI agent's subprocess (Claude Code's Bash tool, Codex, etc.) without a controlling TTY, they auto-imply `--skip-auth` and print a banner instructing the operator to finish authentication in Terminal.app. Previously they hung forever on the first `typer.confirm` prompt.
- Each setup subcommand gained explicit `--google-ads/--no-google-ads` and `--meta-ads/--no-meta-ads` flags so choices can be specified without any prompt. Passing them together with `--skip-auth` (or under a non-TTY) emits a warning explaining they were ignored.
- New helper `mureo/cli/_tty.py` (`is_tty`, `confirm_or_default`) centralizes the TTY + fallback logic. Both stdin and stdout must be terminals for `is_tty()` to return true. `confirm_or_default` catches `EOFError` / `click.Abort` if the TTY disappears mid-prompt and falls back to the caller-supplied default.

### Added
- README + README.ja: "From inside Claude Code Desktop" section with a natural-language install phrase that non-technical users can paste into the Code tab. Notes that OAuth (Developer Token, App ID/Secret input) still requires a one-time Terminal.app session for safety.

## [0.5.0] - 2026-04-19

### Added
- `mureo setup codex` — new subcommand that installs the full mureo kit for OpenAI Codex CLI: tagged `[mcp_servers.mureo]` block in `~/.codex/config.toml` (append-only, idempotent, refuses to proceed if an untagged `[mcp_servers.mureo]` already exists), Read + Bash PreToolUse credential guard in `~/.codex/hooks.json`, workflow prompts in `~/.codex/prompts/*.md`, and skills in `~/.codex/skills/mureo-*/`. Config and hooks are written atomically via temp-file + rename so a mid-install crash cannot defeat the tag-based idempotency check. Corrupt `hooks.json` and non-list `PreToolUse` values are refused rather than silently clobbered.
- `mureo setup gemini` — new subcommand that registers mureo as a Gemini CLI extension at `~/.gemini/extensions/mureo/gemini-extension.json` with `mcpServers.mureo` and `contextFileName: CONTEXT.md`. Merges into an existing manifest instead of overwriting, so operator-added top-level keys (`excludeTools`, renamed `contextFileName`) and extra `mcpServers` entries are preserved across reinstall. Hooks and `.md` workflow commands are not installed because Gemini CLI does not support those surfaces.
- Rollback execution path — closes the rollback feature that previously landed as planner + CLI inspection only. Introduces `mureo/rollback/executor.py` (`execute_rollback`) and two MCP tools: `rollback.plan.get` (inspect the reversal plan for any `action_log` entry) and `rollback.apply` (execute the plan, re-dispatching through the same MCP handler used for forward actions so the reversal re-enters the forward-action policy gate — auth, rate limiting, input validation). `ActionLogEntry` gains an optional `rollback_of: int | None` field so the applied rollback is append-only in `STATE.json` and a second apply of the same index is refused. Safety: `confirm=True` must be the literal `True` (truthy integers / non-empty strings are refused), the planner is re-invoked at execution time rather than cached, destructive verbs are refused twice (planner allow-list + executor guard against `rollback.*` self-recursion), the appended rollback entry carries `reversible_params=None` so rollbacks of rollbacks do not chain by default, dispatch-time API failures never mutate `action_log`, `state_file` resolves strictly inside the MCP server's current working directory (no traversal or symlink escape), and downstream SDK exception messages are logged server-side only while the MCP response returns a generic message so tokens / account identifiers cannot leak into model context.
- Added `mureo/analysis/anomaly_detector.py`, a pure I/O-free module that compares a `CampaignMetrics` snapshot against a median-based baseline built from historical `action_log` entries and returns a prioritized list of `Anomaly` records with recommended actions. Detects zero spend on a previously-spending campaign (CRITICAL), CPA spike ≥ 1.5× baseline (critical at 2×, gated by 30+ conversions), and CTR drop ≤ 0.5× baseline (critical at 0.3×, gated by 1000+ impressions). Sample-size gates follow the `mureo-learning` skill's statistical-thinking rules to suppress single-day noise. Baselines tolerate malformed `metrics_at_action` rows (string numerics, `"N/A"`, missing keys) so one bad entry cannot silently disable detection; CPA/CTR are medianed per-entry (never `median(cost) / median(conversions)`) so baseline values reflect a real historical day.
- Wired `anomaly_detector` behind the new MCP tool `analysis.anomalies.check` (`mureo/mcp/tools_analysis.py` + `_handlers_analysis.py`). The handler takes a `current` metrics payload plus an optional `state_file`, builds a median baseline from `action_log` history, and returns severity-ordered anomalies as JSON. `current.campaign_id` and `current.cost` are required so a zero-spend alert is always an intentional zero. Numeric fields accept int / float / numeric-string and reject the rest (`"N/A"`, bools, etc.), so a JSON client that stringifies numerics works but garbage does not silently pass. `state_file` is sandboxed against the MCP server's current working directory — paths that resolve outside or traverse a symlink are refused so a prompt-injected agent cannot redirect the read to an attacker-crafted STATE.json. A malformed history file does not silence live zero-spend detection; the response includes a `baseline_warning` so the agent can flag the unreliable baseline to the operator.
- Added `mureo/rollback/`, the data-model and planning half of the rollback feature. `ActionLogEntry` gains an optional `reversible_params` field (shape: `{"operation": "<allow-listed>", "params": {...}, "caveats": [...]}`); `STATE.json` round-trips it. `plan_rollback(entry) -> RollbackPlan | None` returns a concrete reversal plan, tagged `supported`, `partial` (reversible configuration but irreversible side effects like spend), or `not_supported`. The planner enforces an explicit operation allow-list (budget update + status toggles across Google/Meta Ads), refuses destructive verbs (`.delete` / `.remove` / `.destroy` / `.purge` / `.transfer`), and rejects unexpected parameter keys so a compromised agent cannot smuggle a privileged call through the rollback path.
- Added `mureo rollback list` and `mureo rollback show <index>` CLI commands for inspecting reversible actions in `STATE.json`. Intentionally read-only — execution continues to route through MCP so it re-enters the same policy gate as forward actions. String fields from the agent-writable STATE.json are sanitized of C0/C1 control characters before terminal output to prevent ANSI-escape injection.

### Security
- Added `mureo/google_ads/_gaql_validator.py`, a centralized whitelist-based validator for Google Ads Query Language (GAQL) string construction. Every ID, date, date-range constant, and string literal that enters a GAQL query now flows through one surface (`validate_id`, `validate_id_list`, `validate_date`, `validate_date_range_constant`, `escape_string_literal`, `validate_period_days`, `build_in_clause`). Hardened `_period_to_date_clause` so the `BETWEEN` branch pattern-matches and validates both dates instead of passing the raw caller string straight into GAQL, closing a trailing-injection path. Removed the unbounded `ALL_TIME` constant from the accepted date-range whitelist and added a 20-character length cap on numeric IDs to prevent absurd payloads reaching the upstream API.

## [0.4.3] - 2026-04-11

### Changed
- Google Ads mutate errors now include the specific API error detail in the raised `RuntimeError` message instead of the generic "An error occurred while processing X." Previously, when Google Ads rejected a mutation (e.g. a `cpc_bid_micros` value below the account's minimum bid, an invalid asset format, a policy rejection, etc.), the detail was only written to logs, so agents saw an opaque failure with no actionable information. The detail is now appended to the message for every tool decorated with `@_wrap_mutate_error` (campaigns.create/update/update_status/diagnose, ad_groups.create/update, ads.create/update/update_status, keywords, negative_keywords, budgets, conversions, extensions, and display ads). The existing RESOURCE_NOT_FOUND hint is preserved and now also carries the API detail.

## [0.4.2] - 2026-04-11

### Added
- `google_ads.ads.list` now returns Responsive Display Ad (RDA) text fields when the ad is a RDA: `headlines`, `descriptions`, `long_headline`, `business_name`, `marketing_images`, `square_marketing_images`, `logo_images`. Previously the response only populated these fields for Responsive Search Ads (RSA), so RDAs appeared with empty `headlines`/`descriptions` arrays.

### Fixed
- `google_ads.ad_groups.update` now rejects `cpc_bid_micros` with a clear error when the parent campaign uses an automated bidding strategy (MAXIMIZE_CLICKS / MAXIMIZE_CONVERSIONS / TARGET_CPA / TARGET_ROAS / etc.). Previously the Google Ads API returned the unhelpful "An error occurred while processing ad group update." message, and it was unclear that the root cause was a bidding-strategy mismatch. Manual ad-group-level bids are only supported under MANUAL_CPC, MANUAL_CPM, and MANUAL_CPV.
- `google_ads.ads.update` now fails fast with a clear message when the target ad is a Responsive Display Ad (RDA). The existing implementation only supports Responsive Search Ads (RSA), and attempting to update a RDA previously produced the cryptic "An error occurred while processing ad text update." error. RDA updates are still not implemented; recreate the ad via `create_display_ad` for text changes.

## [0.4.1] - 2026-04-11

### Fixed
- `google_ads.campaigns.create` silently ignored the `channel_type` parameter introduced in 0.4.0. The MCP handler forwarded only `name`, `bidding_strategy`, and `budget_id` to the client, so a request asking for a DISPLAY campaign produced a SEARCH campaign. `channel_type` is now passed through correctly, and `google_ads.ads.create_display` works end-to-end against live accounts.
- `google_ads.campaigns.list` / `google_ads.campaigns.get` now include the campaign's `channel_type` (SEARCH/DISPLAY/etc.) in the response, so agents can verify the channel type of an existing campaign without inferring it from other fields. `list_campaigns` and `get_campaign` GAQL queries were extended to select `campaign.advertising_channel_type`, and `map_campaign` surfaces it as `channel_type`.

## [0.4.0] - 2026-04-10

### Added
- Display Ads support: `google_ads.campaigns.create` now accepts a `channel_type` parameter (`"SEARCH"` or `"DISPLAY"`, defaults to `"SEARCH"`).
- New tool `google_ads.ads.create_display` for creating Responsive Display Ads (RDA). Marketing, square marketing, and (optional) logo image files are uploaded automatically from local paths before the ad is created.
- New module `mureo/google_ads/_rda_validator.py` with text and asset count validation for RDAs (headlines/long headline/descriptions/business name/image counts/URL).
- New `_DisplayAdsMixin` (`mureo/google_ads/_ads_display.py`) added to `GoogleAdsApiClient`.
- New exception type `RDAUploadError` that surfaces orphaned uploaded asset resource names when an RDA creation fails partway through, so callers can clean them up.
- Pre-check that the target ad group belongs to a DISPLAY campaign before any image upload happens, avoiding orphaned assets when the wrong ad group is selected.

### Changed
- `_AdsMixin` no longer contains display ad code; RSA-related operations remain in `_ads.py`, RDA operations live in `_ads_display.py`.

## [0.3.2] - 2026-04-10

### Added
- `customer_id` field in `GoogleAdsCredentials` (separate from `login_customer_id`) to support MCC-child account scenarios where the authentication context (MCC) and operation target (child account) differ.
- `GOOGLE_ADS_CUSTOMER_ID` environment variable support.

### Changed
- `mureo auth setup` now traverses the Manager (MCC) hierarchy to list child accounts. Previously it only showed accounts with direct login access, so users granted access only via an MCC would see only the MCC itself.
- When a child account reached via an MCC is selected, `login_customer_id` is set to the parent MCC while `customer_id` is set to the selected child.
- `mureo auth status` now shows both `customer_id` and `login_customer_id` when they differ.

## [0.3.1] - 2026-04-10

### Fixed
- Google Ads OAuth setup fails with "Address already in use" when port 8085 is occupied. The local OAuth callback server now picks an available port automatically (port=0), matching the Meta Ads setup behavior.

## [0.3.0] - 2026-04-06

### Added
- Evidence-based learning feedback loop with `mureo-learning` skill
- `ActionLogEntry.metrics_at_action` field for recording metrics at action time
- `ActionLogEntry.observation_due` field for scheduling outcome evaluation
- Statistical thinking framework: observation windows, minimum sample sizes, evidence lifecycle (OBSERVING → CANDIDATE → VALIDATED)
- Noise guards in all 10 workflow commands to prevent premature optimization
- Google Search Console API client with 10 MCP tools, bringing total to 169
- Japanese README (README.ja.md)

### Changed
- All 10 workflow commands transformed to platform-agnostic orchestration (no hardcoded tool names)
- Commands now discover platforms at runtime from STATE.json `platforms` dict
- Search Console and GA4 integrated as data sources across all commands
- STATE.json format updated to v2 with multi-platform `platforms` dict
- SKILL.md version bumped to 0.3.0 with orchestration paradigm
- Workflow skill count increased from 5 to 6

### Fixed
- CONTEXT.md tool count corrected from 42 to 169
- Search Console tool reference pointed to correct documentation file

## [0.2.0] - 2026-03-31

### Added
- 78 new MCP tools (53 Google Ads + 25 Meta Ads), bringing total from 81 to 159
- Google Ads: sitelinks, callouts, conversion tracking, device/location/schedule targeting, recommendations, bid adjustments, change history, performance analysis, budget analysis, RSA asset analysis, B2B optimizations, creative research, landing page analysis, monitoring & goal evaluation, screenshot capture
- Meta Ads: campaign/ad set/ad pause & enable, audience get/delete/lookalike, creative list/create/dynamic, pixel management, performance analysis, audience analysis, placement analysis, cost investigation, ad comparison, creative improvement suggestions
- Handler tests for all 159 MCP tools (92 new tests, 1257 total)
- Project logo in README

### Changed
- Broadened project description from "Ad operations" to "Marketing operations" for multi-platform future
- Default branch renamed from `master` to `main`
- Split MCP tool definitions into category-based sub-modules for maintainability
- Split MCP handler files by domain (extensions, analysis, extended, other)

### Fixed
- All ruff lint errors (A002, F541, TC002, TC003, SIM102, SIM103, SIM105, SIM401, E402, E741, F811, F841, I001, UP037)
- All mypy type checking errors across Python 3.10 and 3.12
- Black formatting applied to all source files
- Bandit security warning (false-positive B104 on SSRF blocklist)
- Input validation: customer_id format, account_id prefix, file path traversal protection, URL scheme validation

### Security
- Added file extension validation on image/video upload handlers
- Added URL scheme validation on screenshot capture handler
- Added customer_id numeric format validation
- Added account_id `act_` prefix validation

## [0.1.0] - 2026-03-31

### Added
- Google Ads API client with 29 MCP tools (campaigns, ad groups, ads, keywords, budget, performance analysis, diagnostics, image upload)
- Meta Ads API client with 52 MCP tools (campaigns, ad sets, ads, creatives, audiences, pixels, insights, Conversions API, Lead Ads, Product Catalog, A/B testing, Ad Rules, videos, carousel, collection, Instagram, page posts)
- MCP server (stdio transport) for integration with AI agents
- CLI (Typer-based) with 15 commands for Google Ads, Meta Ads, and auth management
- Interactive setup wizard (`mureo auth setup`) with browser-based OAuth and account selection
- File-based strategy context (STRATEGY.md / STATE.json)
- Credential management (~/.mureo/credentials.json + environment variable fallback)
- Automatic MCP configuration placement (global or project-level)
- Comprehensive documentation (architecture, authentication, MCP server, CLI, strategy context, contributing)
- SKILL.md files for AI agent integration
