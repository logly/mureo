# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (BREAKING for some operators)
- **MCP tool names switched from dot to underscore separators** to comply with the MCP spec regex `^[a-zA-Z0-9_-]{1,64}$`. Without this, Claude Desktop's chat (and any other spec-strict MCP host) rejected the entire mureo MCP server at registration time with errors like `tools.42.FrontendRemoteMcpToolDefinition.name: String should match pattern '^[a-zA-Z0-9_-]{1,64}$'`. Claude Code accepted dotted names through lenient validation, which is why the bug went undetected. **Migration impact**:
  - **Claude Code users**: no action required. Slash commands (`/daily-check`, etc.) and natural-language tool calls are unaffected.
  - **Claude Desktop / claude.ai web users**: this fix unblocks registration; the server now appears in the tool surface as expected.
  - **Operators with custom `excludeTools` lists** (e.g. Gemini CLI extension config at `~/.gemini/extensions/mureo/gemini-extension.json`): rename entries in your `excludeTools` array to the new underscore form. Example: `"google_ads.budget.update"` -> `"google_ads_budget_update"`. Otherwise your previous exclusion list silently stops blocking those tools after upgrade.
  - **Anyone with code or scripts referencing tool names directly**: rename `prefix.X.Y` -> `prefix_X_Y` (173 tools across `google_ads`, `meta_ads`, `search_console`, `rollback`, `analysis` prefixes).
- New regression test `tests/test_mcp_tool_name_spec.py::test_all_registered_tools_match_mcp_spec` enforces the spec regex in CI for every future tool addition.

## [0.7.1] - 2026-04-29

PyPI re-publish of v0.7.0 with the post-#54 fixes folded in. The original `0.7.0` is on PyPI but predates these patches; PyPI does not allow re-uploading the same version, so the same change set ships as `0.7.1`.

### Added
- **Currency-agnostic Meta Ads spend column** — Meta exports the spend header as `Amount spent (XXX)` where `XXX` is the account's ISO currency code (`JPY` / `USD` / `EUR` / `GBP` / `KRW` / `INR` / etc.). The previous JPY-only path rejected non-JPY accounts with `UnsupportedFormatError`, blocking every non-JP user. New `_resolve_spend_idx` strips the trailing `(XXX)` suffix before alias matching; `_to_float` strips a leading currency symbol from a known set (¥ / $ / € / £ / ₩ / ₹ / ¢ / etc.) from cell values. Cost values are stored raw in the account's own currency — cross-account currency conversion is out of scope. Regression tests cover USD / EUR / GBP / KRW / INR header + cell-prefix combinations.

### Fixed
- **Meta Ads adapter alias corrections for de_DE / es_ES / fr_FR** — 7 mismatched header strings (best-effort guesses in 0.7.0) replaced with strings observed in real Ads Manager exports across 9 locales. Notable: French uses U+2019 right single quotation mark (`'`) not ASCII (`'`); German "Name der Anzeige(ngruppe)" not the compound forms; Spanish plural "clics" not singular. All 14 mureo-recognized columns now resolve in all 9 locales (126/126 column matches verified against user-provided exports).
- **BYOD Google Ads zero-impressions/zero-clicks regression** — `_to_int` in `mureo/byod/clients.py` rejected float-formatted strings like `"98.0"`, which is exactly what the bundled Apps Script writes for impressions / clicks per day. The strict `int("98.0")` raised `ValueError` and the helper silently returned the default `0`, so every Google Ads BYOD `get_performance_report` row reported `impressions=0 / clicks=0 / ctr=0 / average_cpc=0` even when the underlying CSV was complete. `_to_int` now falls back to `int(float(v))` before returning the default. Regression tests in `tests/test_byod.py`.
- **BYOD Meta `get_performance_report` now surfaces `result_indicator`** — the per-campaign output dict gained a `result_indicator` field (e.g. `actions:link_click`, `actions:offsite_conversion.fb_pixel_lead`, or empty when the campaign carries no conversion-event optimization). The value was already written to `metrics_daily.csv` by the Phase 3 importer but was being dropped before reaching the agent, so `/daily-check` could see "42 results vs 3 results" across two campaigns with no signal that the units were incomparable. The first non-empty indicator seen for each campaign across the period's daily rows is exposed.

### Changed
- **All bundled command skills now name the specific MCP tools to call** — `mureo/_data/commands/{daily-check,search-term-cleanup,budget-rebalance,competitive-scan,creative-refresh,rescue,sync-state,weekly-report,onboard}.md` previously instructed the agent to "use the platform's analysis tools" without naming them. Real BYOD sessions hit a reproducible failure mode where the agent looked for raw CSVs in the project directory and aborted when it couldn't find any (BYOD data lives under `~/.mureo/byod/`, not in the project). Skill bodies now list the concrete tool names per platform plus an explicit reminder that BYOD data is centralized under `~/.mureo/byod/`. Each command also documents which BYOD tools return `[]` by design (auction insights, RSA asset ratings, etc.). Markdown skill bodies only — no code changes.
- **Japanese BYOD walkthrough** (`docs/byod.ja.md`) added — native Japanese counterpart of `docs/byod.md`. Section flow restructured for Japanese readability rather than direct translation; all 9 verified Meta export locales named explicitly. Cross-link added at the top of the English `byod.md`. `README.ja.md` deep links repointed from `docs/byod.md` to `docs/byod.ja.md`.

### Security
- **Resolved 8 CodeQL Code Scanning alerts** in OAuth + GAQL paths:
  - `py/http-response-splitting` (error) — `mureo/cli/web_auth.py` `Location` header now constructed from a CR/LF-stripped URL via `_validate_oauth_url`, blocking response-splitting injection.
  - `py/clear-text-logging-sensitive-data` (4 errors) — OAuth URL-rejection logs and GAQL `_search` start/done logs no longer echo any value derived from the URL or query string. The terminal `print` of the Meta OAuth URL in `run_meta_oauth` was removed entirely.
  - `py/incomplete-url-substring-sanitization` (3 warnings) — `tests/test_web_auth.py` deep-link substring assertions tightened to match the full URL path, not the host alone.
  - The OAuth-URL validation now runs **before** any wizard session mutation, so a rejected redirect cannot leave the wizard with half-populated auth material.

## [0.7.0] - 2026-04-29

### Added
- **BYOD Meta Ads adapter** — `mureo/byod/adapters/meta_ads.py` consumes the user's Ads Manager Excel export (Reports → Customize → Export → Excel) and normalizes it to CSVs under `~/.mureo/byod/meta_ads/`. Identity (campaign_id / ad_set_id / ad_id) is synthesized from name via deterministic SHA-256 hash so re-imports keep stable IDs. **Multilingual header support** — recognizes column names in English / 日本語 / Español / Português / 한국어 / 繁體中文 / 简体中文 / Français / Deutsch (e.g. キャンペーン名, インプレッション, 消化金額 (JPY), 結果), verified against actual exports in each locale. Multiple rows per (day, campaign) — typical when Ad-set or Ad breakdown is enabled — are summed before write. Pivot subtotal rows (date cell = `All` or locale equivalent) are skipped automatically. Currency is JPY-only; non-JPY symbol prefix (`$`, `€`, `£`, …) raises `UnsupportedFormatError` to prevent silent over/under-reporting. (Restriction lifted in 0.7.1 — see above.) Disjoint from the Google Ads adapter via the long-form vs short-form campaign header distinction, so a single workbook can carry both adapters' data.
  - **Phase 3 schema (richer analytics):** `metrics_daily.csv` extended with `reach`, `frequency`, `result_indicator` columns (frequency falls back to impressions/reach when not directly exported). New per-grain CSVs are written when the export carries the relevant columns: `ad_set_metrics_daily.csv` ((date, campaign_id, ad_set_id) × metrics+reach), `ad_metrics_daily.csv` ((date, campaign_id, ad_set_id, ad_id) × metrics+reach), `demographics_daily.csv` (one row per (date, campaign_id, dimension, value) for age / gender / region / placement breakdowns — these rows are excluded from `metrics_daily` to avoid double-counting), and `creatives.csv` (best-effort: ad_id, name, image_url, video_url, headline, body, cta — only written when those columns are present in the export). Each new CSV is suppressed when the source export lacks the corresponding columns, so existing campaign-only exports import unchanged.
- **BYOD Sheet bundle pipeline (Google Ads only)** — XLSX-in, Google-Ads-out import. Users run the mureo Google Ads Script (`scripts/sheet-template/google-ads-script.js`) inside Google Ads → Tools → Bulk actions → Scripts, which populates a Google Sheet with `campaigns / ad_groups / search_terms / keywords / auction_insights` tabs. They download the sheet as XLSX and run `mureo byod import bundle.xlsx`. The bundle importer (`mureo/byod/bundle.py`) opens the XLSX with openpyxl read-only, dispatches the workbook to the Google Ads adapter, writes per-platform CSVs to `~/.mureo/byod/google_ads/`, and updates `manifest.json` atomically with rollback on partial failure. New `openpyxl>=3.1,<4` runtime dependency.
- **Richer Google Ads adapter** — surfaces `search_terms.csv`, `keywords.csv`, and `auction_insights.csv` alongside the previous `campaigns.csv` / `ad_groups.csv` / `metrics_daily.csv`, giving `/daily-check` access to query-level and competitor-level data the v0.6 CSV path could not.
- **Google Ads Script** under `scripts/sheet-template/google-ads-script.js`. **No mureo-managed OAuth client, no GCP project, no developer token** — Ads Scripts run under the user's Google Ads identity on Google's infrastructure, including on Google Workspace organization accounts where Apps Script auto-GCP-creation is blocked.
- **Richer Google Ads analysis from BYOD bundles**: `ByodGoogleAdsClient.get_search_terms_report` is now backed by the bundle's `search_terms.csv` (was `return []`), and new `get_auction_insights` / `analyze_auction_insights` methods read `auction_insights.csv`. Together these surface query-level performance and competitor share metrics through the existing `google_ads_search_terms_report` / `google_ads.auction_insights.{get,analyze}` MCP tools — turning the v0.6 BYOD path's "Campaign × Day rollup only" into something `/daily-check` can actually reason about.

### Changed
- `mureo byod` CLI — `mureo byod import <file>` now requires an XLSX (Sheet bundle). The previous per-platform CSV path is gone; flags `--google-ads / --meta-ads / --search-console / --as` were removed from `import` because the workbook tab names determine which adapter runs. `status` and `remove` cover the BYOD-supported platforms (`--google-ads` / `--meta-ads`); GA4 and Search Console remain on the existing Live API OAuth path and are not part of the bundle pipeline.
- MCP tool descriptions rewritten for 49 tools across Google Ads and Meta Ads — `google_ads.campaigns.*`, `google_ads.ad_groups.*`, `google_ads.ads.*`, `google_ads.budget.*`, `google_ads.accounts.*`, `google_ads.keywords.*`, `google_ads.negative_keywords.*`, `meta_ads.campaigns.*`, `meta_ads.ad_sets.*`, `meta_ads.ads.*`. Each description now covers verb + resource + returned fields + side effects (read-only / mutating / reversible via `rollback_apply`) + sibling tool differentiation, following the new `docs/tdqs-style-guide.md`. Targets improving Glama's Tool Definition Quality Score from C (3.1 avg) toward B+. No behavioral changes — descriptions and parameter hints only.
- MCP tool descriptions rewritten for the remaining ~51 Meta Ads tools — `meta_ads.creatives.*` (including the TDQS lowest-scoring `meta_ads_creatives_list`), `meta_ads.images.*`, `meta_ads.videos.*`, `meta_ads.audiences.*`, `meta_ads.pixels.*`, `meta_ads.insights.*`, `meta_ads.analysis.*`, `meta_ads.catalogs.*`, `meta_ads.products.*`, `meta_ads.feeds.*`, `meta_ads.conversions.*`, `meta_ads.lead_forms.*`, `meta_ads.leads.*`, `meta_ads.split_tests.*`, `meta_ads.ad_rules.*`, `meta_ads.page_posts.*`, `meta_ads.instagram.*`. Same TDQS template as PR #43. No behavioral changes.
  - The OAuth-URL validation now runs **before** any wizard session mutation, so a rejected redirect cannot leave the wizard with half-populated auth material.

### Removed (BREAKING)
- **Single-CSV BYOD import path** (`mureo byod import <file>.csv`, the auto-detection logic, the 15-locale Google Ads Report Editor alias dictionary, preamble handling, PII column rejection, and the `--google-ads / --meta-ads / --search-console / --as` flags on `import`). Users who imported a CSV under v0.6.x must re-run the Sheet flow described in `docs/byod.md`. Public symbols removed: `mureo.byod.installer.import_csv`, `mureo.byod.adapters.google_ads.GoogleAdsAdapter.detect()`, `mureo.byod.adapters.google_ads.GoogleAdsAdapter.normalize()`, `mureo.byod.adapters.google_ads.PIIDetectedError`. The `source_format` manifest key changes from `"google_ads_report_editor_v1"` to `"mureo_sheet_bundle_google_ads_v1"`.

## [0.6.0] - 2026-04-20

First production PyPI release (`pip install mureo`). Supersedes the internal `0.6.0.dev1` preview that was published to TestPyPI during colleague beta testing.

### Security
- `mureo setup codex` command-skill generation now escapes all control characters and unicode line separators (U+2028 / U+2029) in the skill `description:` frontmatter field, so a future bundled command whose first line contains a tab, CR, LF, NEL, or other byte that YAML treats as a line break cannot silently truncate the description or corrupt the frontmatter block. Today's bundled commands don't trigger the old behavior — this is a defense-in-depth guard against a future maintainer adding a command with an unusual first line.
- The legacy `~/.codex/prompts/<bundled>.md` cleanup in `install_codex_command_skills` now skips symlinks. Previously a user who had symlinked a bundled filename at their own file (e.g. via a dotfiles repo) would see the symlink silently removed on every `mureo setup codex` re-run, even though the target stayed intact. The symlink now survives so the operator's intentional link-over-bundled-name is preserved.

### Fixed
- `mureo auth setup --web` — Google Ads now saves a real `customer_id` and `login_customer_id` instead of `null`. Previously the web wizard stopped at `refresh_token` and never reached `list_accessible_accounts()`, so every Google Ads credentials block shipped with null IDs and every subsequent API call failed. The wizard now has a `/google-ads/select-account` page rendered after OAuth callback: list is fetched via Google Ads API, rendered as radio picker, submit resolves MCC hierarchy (`login_customer_id = parent_id if parent_id else chosen_id`). Same treatment for Meta: `/meta-ads/select-account` calls `list_meta_ad_accounts` and saves `account_id`. If either list API fails or returns empty, credentials save with the null IDs and the wizard redirects to `/after-platform?warn=no_accounts` so the operator sees the warning and can fix manually instead of losing the refresh_token.
- `mureo auth setup --web` — wizard no longer quits after a single platform. Previously Google/Meta callback both redirected to `/done`, ending the wizard and preventing the user from configuring the second platform. Now the wizard redirects to a new `/after-platform` intermediate page after each platform completes, showing a "Configure [other] too" CTA (hidden when both are done) plus a Finish setup button. `/done` is reached only via explicit "Yes, finish" on a new `/done/confirm` confirmation page.
- `mureo auth setup --web` — Facebook "CSRF token invalid" 403 on re-submit from a cached page. Added `Cache-Control: no-store` and `Pragma: no-cache` to all wizard HTML responses so browsers never render a stale form with an outdated hidden token. Also removed premature `rotate_csrf()` from `/google-ads/submit` and `/meta-ads/submit` (OAuth-init steps that don't persist anything) — rotation now happens only at commit-point submits (`/google-ads/select-account`, `/meta-ads/select-account`). Back-button resubmissions and parallel tabs (one user on `/google-ads` while another is on `/meta-ads`) no longer wedge with a 403.
- `mureo auth setup --web` — "Continue to Facebook sign-in" button appeared unresponsive. Root cause: modern browsers enforce CSP `form-action` through the entire redirect chain, so a form posting to `/meta-ads/submit` that 302s to `facebook.com` was blocked by a `form-action` allow-list that only contained `accounts.google.com`. Widened the directive to `form-action 'self' https://accounts.google.com https://www.facebook.com`.
- `mureo auth setup --web` — Facebook "insecure connection" warning on Google/Meta OAuth redirect. The terminal flow used `http://localhost:<port>/callback`; the web wizard used `http://127.0.0.1:<port>/...`. Facebook treats the IP literal as non-dev and surfaces the scary "not secure" warning, while `localhost` is whitelisted as a dev origin. Switched all three web-wizard redirect_uri constructions to use `localhost` (host-header check already accepted both). Google accepts both transparently.
- `mureo auth setup --web` — `_configured_platforms` now requires `customer_id` / `account_id` to count a platform as "configured", not just `refresh_token` / `access_token`. Prevents the `/done` page from declaring a no-accounts partial save "complete". Paired with: `/after-platform` no longer bounces to `/` when `_configured_platforms` is empty, so a partial save reaches the Finish button instead of the user getting kicked home with no feedback.
- `mureo auth setup --web` — `_read_form` catches `UnicodeDecodeError` on malformed POST bodies and returns a 413 instead of a 500, matching the other boundary checks. Probe-error logging in the Google/Meta account-list paths no longer passes `exc_info=True` — the google-ads SDK occasionally embeds request arguments (developer_token / client_secret / access_token) in exception repr, and dumping the full traceback to stderr would leak them.
- `mureo auth setup --web` UX — Finish setup button is now green (`btn-finish`) and goes through a `/done/confirm` Yes/No confirmation page before terminating the wizard, so a user mistaking "Finish setup" for a primary continuation CTA (identical blue to "Configure X too" previously) can back out without losing the session.
- Skill-directory re-install now tolerates a symlink at the destination path. Previously, if an operator had symlinked `~/.claude/skills/<bundled>/` or `~/.codex/skills/<bundled>/` at their own dev copy (common during mureo development from an editable install), re-running `mureo setup claude-code` or `mureo setup codex` crashed with ``OSError: Cannot call rmtree on a symbolic link`` in `install_skills`, `install_codex_skills`, and `install_codex_command_skills`. The fix swaps the symlink for `unlink()` (the link itself is removed; the external target the link points at is left intact), then lays down a real copy of the bundled skill. Regular directories still go through `shutil.rmtree` unchanged.
- `install_commands` (`~/.claude/commands/*.md`) now also unlinks a symlinked destination before copying. Previously `shutil.copy2` followed the symlink and wrote through to the target file, so the symlink stayed in place. That silently broke **Claude Desktop slash commands** for any dev who had symlinked the bundled commands at their repo: Claude Desktop's sandboxed process tried to read the symlinked command file, followed the symlink into `~/Documents`, hit macOS TCC, got denied, and the slash command dispatched nothing. Real-file replacement fixes both Claude Desktop (no cross-sandbox read) and leaves the dev's external target file untouched.
- `mureo setup codex` now installs bundled workflow commands as Codex **skills** at `~/.codex/skills/<command>/SKILL.md` (with YAML frontmatter — `name:` / `description:`) instead of as custom prompts at `~/.codex/prompts/*.md`. Codex CLI 0.117.0 (2026-03) [stopped rendering the custom-prompts directory](https://github.com/openai/codex/issues/15941) in its slash-command menu, so `mureo setup codex` was silently installing ten files that Codex no longer picked up. Users invoke the workflows with `$daily-check` (explicit) or the `/skills` picker. Re-running `mureo setup codex` also removes the stale `~/.codex/prompts/<bundled>.md` files left behind by prior installs; user-authored prompts with names outside mureo's bundled set are preserved.

### Changed
- Internal documentation realigned to recent development. `docs/cli.md` now documents `mureo setup codex` (Codex skills migration + legacy-prompt cleanup, per [openai/codex#15941](https://github.com/openai/codex/issues/15941)), `mureo setup gemini`, and the per-platform `--google-ads/--meta-ads/--skip-auth` flags with their non-interactive auto-imply semantics. `docs/authentication.md` "Recommended Setup" lists all four setup subcommands plus `mureo auth setup --web`, and adds sections explaining `--skip-auth` TTY detection and the browser-based wizard (pointing at `SECURITY.md` → "Browser-based auth wizard"). `docs/architecture.md`, `AGENTS.md`, and `CONTEXT.md` code-tree / setup blocks now list `setup_codex.py`, `setup_gemini.py`, and the `--web` auth path. Bundled workflows skill (`mureo/_data/skills/mureo-workflows/SKILL.md` + top-level dev copy) gains a "Invocation syntax by host" note explaining that `/daily-check` on Claude Code reads as `$daily-check` on Codex CLI so a Codex user sees the same reference without confusion.
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
- Rollback execution path — closes the rollback feature that previously landed as planner + CLI inspection only. Introduces `mureo/rollback/executor.py` (`execute_rollback`) and two MCP tools: `rollback_plan_get` (inspect the reversal plan for any `action_log` entry) and `rollback_apply` (execute the plan, re-dispatching through the same MCP handler used for forward actions so the reversal re-enters the forward-action policy gate — auth, rate limiting, input validation). `ActionLogEntry` gains an optional `rollback_of: int | None` field so the applied rollback is append-only in `STATE.json` and a second apply of the same index is refused. Safety: `confirm=True` must be the literal `True` (truthy integers / non-empty strings are refused), the planner is re-invoked at execution time rather than cached, destructive verbs are refused twice (planner allow-list + executor guard against `rollback.*` self-recursion), the appended rollback entry carries `reversible_params=None` so rollbacks of rollbacks do not chain by default, dispatch-time API failures never mutate `action_log`, `state_file` resolves strictly inside the MCP server's current working directory (no traversal or symlink escape), and downstream SDK exception messages are logged server-side only while the MCP response returns a generic message so tokens / account identifiers cannot leak into model context.
- Added `mureo/analysis/anomaly_detector.py`, a pure I/O-free module that compares a `CampaignMetrics` snapshot against a median-based baseline built from historical `action_log` entries and returns a prioritized list of `Anomaly` records with recommended actions. Detects zero spend on a previously-spending campaign (CRITICAL), CPA spike ≥ 1.5× baseline (critical at 2×, gated by 30+ conversions), and CTR drop ≤ 0.5× baseline (critical at 0.3×, gated by 1000+ impressions). Sample-size gates follow the `_mureo-learning` skill's statistical-thinking rules to suppress single-day noise. Baselines tolerate malformed `metrics_at_action` rows (string numerics, `"N/A"`, missing keys) so one bad entry cannot silently disable detection; CPA/CTR are medianed per-entry (never `median(cost) / median(conversions)`) so baseline values reflect a real historical day.
- Wired `anomaly_detector` behind the new MCP tool `analysis_anomalies_check` (`mureo/mcp/tools_analysis.py` + `_handlers_analysis.py`). The handler takes a `current` metrics payload plus an optional `state_file`, builds a median baseline from `action_log` history, and returns severity-ordered anomalies as JSON. `current.campaign_id` and `current.cost` are required so a zero-spend alert is always an intentional zero. Numeric fields accept int / float / numeric-string and reject the rest (`"N/A"`, bools, etc.), so a JSON client that stringifies numerics works but garbage does not silently pass. `state_file` is sandboxed against the MCP server's current working directory — paths that resolve outside or traverse a symlink are refused so a prompt-injected agent cannot redirect the read to an attacker-crafted STATE.json. A malformed history file does not silence live zero-spend detection; the response includes a `baseline_warning` so the agent can flag the unreliable baseline to the operator.
- Added `mureo/rollback/`, the data-model and planning half of the rollback feature. `ActionLogEntry` gains an optional `reversible_params` field (shape: `{"operation": "<allow-listed>", "params": {...}, "caveats": [...]}`); `STATE.json` round-trips it. `plan_rollback(entry) -> RollbackPlan | None` returns a concrete reversal plan, tagged `supported`, `partial` (reversible configuration but irreversible side effects like spend), or `not_supported`. The planner enforces an explicit operation allow-list (budget update + status toggles across Google/Meta Ads), refuses destructive verbs (`.delete` / `.remove` / `.destroy` / `.purge` / `.transfer`), and rejects unexpected parameter keys so a compromised agent cannot smuggle a privileged call through the rollback path.
- Added `mureo rollback list` and `mureo rollback show <index>` CLI commands for inspecting reversible actions in `STATE.json`. Intentionally read-only — execution continues to route through MCP so it re-enters the same policy gate as forward actions. String fields from the agent-writable STATE.json are sanitized of C0/C1 control characters before terminal output to prevent ANSI-escape injection.

### Security
- Added `mureo/google_ads/_gaql_validator.py`, a centralized whitelist-based validator for Google Ads Query Language (GAQL) string construction. Every ID, date, date-range constant, and string literal that enters a GAQL query now flows through one surface (`validate_id`, `validate_id_list`, `validate_date`, `validate_date_range_constant`, `escape_string_literal`, `validate_period_days`, `build_in_clause`). Hardened `_period_to_date_clause` so the `BETWEEN` branch pattern-matches and validates both dates instead of passing the raw caller string straight into GAQL, closing a trailing-injection path. Removed the unbounded `ALL_TIME` constant from the accepted date-range whitelist and added a 20-character length cap on numeric IDs to prevent absurd payloads reaching the upstream API.

## [0.4.3] - 2026-04-11

### Changed
- Google Ads mutate errors now include the specific API error detail in the raised `RuntimeError` message instead of the generic "An error occurred while processing X." Previously, when Google Ads rejected a mutation (e.g. a `cpc_bid_micros` value below the account's minimum bid, an invalid asset format, a policy rejection, etc.), the detail was only written to logs, so agents saw an opaque failure with no actionable information. The detail is now appended to the message for every tool decorated with `@_wrap_mutate_error` (campaigns.create/update/update_status/diagnose, ad_groups.create/update, ads.create/update/update_status, keywords, negative_keywords, budgets, conversions, extensions, and display ads). The existing RESOURCE_NOT_FOUND hint is preserved and now also carries the API detail.

## [0.4.2] - 2026-04-11

### Added
- `google_ads_ads_list` now returns Responsive Display Ad (RDA) text fields when the ad is a RDA: `headlines`, `descriptions`, `long_headline`, `business_name`, `marketing_images`, `square_marketing_images`, `logo_images`. Previously the response only populated these fields for Responsive Search Ads (RSA), so RDAs appeared with empty `headlines`/`descriptions` arrays.

### Fixed
- `google_ads_ad_groups_update` now rejects `cpc_bid_micros` with a clear error when the parent campaign uses an automated bidding strategy (MAXIMIZE_CLICKS / MAXIMIZE_CONVERSIONS / TARGET_CPA / TARGET_ROAS / etc.). Previously the Google Ads API returned the unhelpful "An error occurred while processing ad group update." message, and it was unclear that the root cause was a bidding-strategy mismatch. Manual ad-group-level bids are only supported under MANUAL_CPC, MANUAL_CPM, and MANUAL_CPV.
- `google_ads_ads_update` now fails fast with a clear message when the target ad is a Responsive Display Ad (RDA). The existing implementation only supports Responsive Search Ads (RSA), and attempting to update a RDA previously produced the cryptic "An error occurred while processing ad text update." error. RDA updates are still not implemented; recreate the ad via `create_display_ad` for text changes.

## [0.4.1] - 2026-04-11

### Fixed
- `google_ads_campaigns_create` silently ignored the `channel_type` parameter introduced in 0.4.0. The MCP handler forwarded only `name`, `bidding_strategy`, and `budget_id` to the client, so a request asking for a DISPLAY campaign produced a SEARCH campaign. `channel_type` is now passed through correctly, and `google_ads_ads_create_display` works end-to-end against live accounts.
- `google_ads_campaigns_list` / `google_ads_campaigns_get` now include the campaign's `channel_type` (SEARCH/DISPLAY/etc.) in the response, so agents can verify the channel type of an existing campaign without inferring it from other fields. `list_campaigns` and `get_campaign` GAQL queries were extended to select `campaign.advertising_channel_type`, and `map_campaign` surfaces it as `channel_type`.

## [0.4.0] - 2026-04-10

### Added
- Display Ads support: `google_ads_campaigns_create` now accepts a `channel_type` parameter (`"SEARCH"` or `"DISPLAY"`, defaults to `"SEARCH"`).
- New tool `google_ads_ads_create_display` for creating Responsive Display Ads (RDA). Marketing, square marketing, and (optional) logo image files are uploaded automatically from local paths before the ad is created.
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
- Evidence-based learning feedback loop with `_mureo-learning` skill
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
