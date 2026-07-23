# AGENTS.md

Guidelines for AI agents contributing to the mureo codebase.

## Project Overview

**mureo** — your local-first AI ad ops crew. Find waste, audit changes, run ad accounts safely.

Works with Claude Code, Cursor, Codex & Gemini. mureo sits on top of the official ad-platform MCPs and gives your AI a strategy to follow, an outcome to be measured against, and an audit trail you can show to anyone — credentials never leave your machine.

mureo combines strategy context, workflow commands, and domain knowledge to help AI agents achieve marketing goals across platforms. Provides MCP tools for direct platform operations and workflow commands for strategy-driven ad operations via Claude Code slash commands. Designed for AI agents — no database, no LLM SDK, no web framework.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v
pytest tests/ --cov=mureo --cov-report=term-missing
```

## Architecture

```
mureo/
├── google_ads/          # Google Ads API client (Mixin composition)
│   ├── client.py        # GoogleAdsApiClient (main entry)
│   ├── mappers.py       # Response mapping to structured dicts
│   ├── _ads.py          # AdsMixin (RSA create/update/status/list)
│   ├── _ads_display.py  # DisplayAdsMixin (RDA create + RDAUploadError)
│   ├── _keywords.py     # KeywordsMixin (add/remove/suggest/diagnose)
│   ├── _analysis.py     # AnalysisMixin aggregator, composing the split modules below
│   ├── _analysis_auction.py / _analysis_btob.py / _analysis_budget.py    # + _analysis_constants.py
│   ├── _analysis_keywords.py / _analysis_performance.py / _analysis_rsa.py / _analysis_search_terms.py
│   ├── _diagnostics.py  # DiagnosticsMixin (campaign diagnosis)
│   ├── _extensions.py   # ExtensionsMixin aggregator, composing the split modules below
│   ├── _extensions_callouts.py / _extensions_conversions.py / _extensions_sitelinks.py / _extensions_targeting.py
│   ├── _monitoring.py   # MonitoringMixin (anomaly detection/reporting)
│   ├── _creative.py     # CreativeMixin (LP analysis/message match)
│   ├── _media.py        # MediaMixin (image asset upload)
│   ├── _rsa_validator.py     # RSA ad text validator
│   ├── _rda_validator.py     # RDA input validator (display ads)
│   ├── _rsa_insights.py      # RSA asset performance insights
│   ├── _intent_classifier.py # Search term intent classification
│   ├── _message_match.py     # Message match evaluator
│   ├── _gaql_validator.py    # GAQL input validators (ASCII-only ID/date whitelists — see below)
│   └── accounts.py           # Accessible-customer / account listing
├── meta_ads/            # Meta Ads API client (Mixin composition)
│   ├── client.py        # MetaAdsApiClient (main entry)
│   ├── mappers.py       # Response mapping
│   ├── _campaigns.py    # CampaignsMixin
│   ├── _ad_sets.py      # AdSetsMixin
│   ├── _ads.py          # AdsMixin
│   ├── _creatives.py    # CreativesMixin (image/carousel/collection/dynamic)
│   ├── _audiences.py    # AudiencesMixin
│   ├── _pixels.py       # PixelsMixin
│   ├── _insights.py     # InsightsMixin
│   ├── _analysis.py     # AnalysisMixin
│   ├── _catalog.py      # CatalogMixin (product catalogs/feeds)
│   ├── _conversions.py  # ConversionsMixin (Conversions API / CAPI)
│   ├── _hash_utils.py   # SHA-256 PII hashing for CAPI
│   ├── _leads.py        # LeadsMixin (lead forms/leads)
│   ├── _page_posts.py   # PagePostsMixin (page posts/boost)
│   ├── _instagram.py    # InstagramMixin (accounts/media/boost)
│   ├── _split_test.py   # SplitTestMixin (A/B split tests)
│   ├── _ad_rules.py     # AdRulesMixin (automated rules)
│   ├── _conversion_count.py  # Conversion-count parsing helper
│   ├── _period.py       # Date-period resolution helper
│   └── accounts.py      # Ad-account listing
├── search_console/      # Google Search Console API client (reuses Google OAuth2 credentials)
│   └── client.py        # SearchConsoleApiClient
├── mcp/                 # MCP server (Google/Meta/Search Console + Rollback/Analysis + Analytics registry, Creative Studio, Learning, mureo Context)
│   ├── server.py                          # MCP Server entry point (stdio-based)
│   ├── _helpers.py                        # Shared handler utilities
│   ├── tools_google_ads.py                # Google Ads tool definitions (aggregator)
│   ├── _tools_google_ads_*.py             # Tool definition sub-modules
│   ├── _handlers_google_ads.py            # Google Ads base handlers
│   ├── _handlers_google_ads_extensions.py # Extensions handlers
│   ├── _handlers_google_ads_analysis.py   # Analysis handlers
│   ├── tools_meta_ads.py                  # Meta Ads tool definitions (aggregator)
│   ├── _tools_meta_ads_*.py               # Tool definition sub-modules
│   ├── _handlers_meta_ads.py              # Meta Ads base handlers
│   ├── _handlers_meta_ads_extended.py     # Extended handlers
│   ├── _handlers_meta_ads_other.py        # Other handlers
│   ├── tools_search_console.py            # Search Console tool definitions
│   ├── _handlers_search_console.py        # Search Console handlers
│   ├── tools_rollback.py                  # rollback_plan_get / rollback_apply
│   ├── _handlers_rollback.py              # Rollback handlers (lazy-resolve dispatcher)
│   ├── tools_analysis.py                  # analysis_anomalies_check
│   ├── _handlers_analysis.py              # Anomaly detector composition handler
│   ├── tools_analytics_registry.py        # mureo_analytics_modules_list / mureo_analytics_run (#440)
│   ├── tools_creative_studio.py           # creative_studio_* (visual generation + compose)
│   ├── tools_learning.py                  # mureo_learning_insights_get / mureo_consult_advisor
│   ├── tools_mureo_context.py             # STRATEGY.md / STATE.json + mureo_outcome_evaluate tools
│   ├── _handlers_mureo_context.py         # Context (STRATEGY/STATE) handlers
│   ├── _client_factory.py                 # Per-platform BYOD-vs-live client factory
│   └── tool_provider.py                   # Third-party plugin → MCP tool exposure layer (#89)
├── cli/                 # Typer CLI (setup + auth + configure + BYOD + providers + rollback; ad ops are via MCP)
│   ├── main.py          # CLI entry point (`mureo` command)
│   ├── setup_cmd.py     # `mureo setup claude-code` / `cursor` / `codex` / `gemini`
│   ├── setup_codex.py   # Codex install-kit: MCP, credential guard, operational + foundation skills
│   ├── setup_gemini.py  # Gemini extension manifest at ~/.gemini/extensions/mureo/
│   ├── native_skills.py # Deploy/remove plugin native slash skills via `mureo.native_skills` group (#439)
│   ├── configure_cmd.py # `mureo configure` — open the local web configuration UI
│   ├── byod_cmd.py      # `mureo byod import` / `status` / `remove` / `clear`
│   ├── providers_cmd.py # `mureo providers list` / `install` / `uninstall` (official MCP catalog)
│   ├── service_cmd.py   # `mureo service` — install/restart the auto-start configure daemon (#241)
│   ├── upgrade_cmd.py   # `mureo upgrade` — pipx venv-aware bulk upgrade of mureo + plugins
│   ├── auth_cmd.py      # `mureo auth setup` / `status` / `check-*` / `upgrade-google`
│   ├── rollback_cmd.py  # `mureo rollback list` / `show` (inspection only; apply routes through MCP)
│   ├── _tty.py          # TTY-safe helpers for non-interactive setup
│   └── web_auth.py      # Browser-based OAuth wizard spawned by `mureo configure` (per-platform creds)
├── context/             # File-based strategy context (no DB)
│   ├── strategy.py      # STRATEGY.md parser/writer
│   ├── state.py         # STATE.json parser/writer
│   ├── models.py        # StrategyEntry, StateDocument, CampaignSnapshot, ActionLogEntry (rollback_of)
│   └── errors.py        # Context-specific errors
├── analysis/            # Analysis utilities
│   ├── lp_analyzer.py   # Landing page analyzer
│   └── anomaly_detector.py  # Zero-spend / CPA-spike / CTR-drop detection (pure, sample-size-gated)
├── rollback/            # Rollback feature (allow-list gated, append-only audit trail)
│   ├── models.py        # RollbackStatus enum + RollbackPlan dataclass
│   ├── planner.py       # plan_rollback(ActionLogEntry) -> RollbackPlan | None
│   └── executor.py      # execute_rollback(...) -> appends ActionLogEntry(rollback_of=index)
├── adapters/            # Provider adapters wrapping each ad-platform client as a registry Protocol
├── analytics/           # Analytics-module registry for external MCP / plugin platforms (#120)
├── core/                # Extension Protocols + file-backed impls + RuntimeContext; provider & skill discovery
├── providers/           # Official MCP provider catalog + one-command install helpers (#86)
├── policy/              # Built-in policy gates (strategy_gate) — ship with OSS, run by default
├── learning/            # Read-side /learn companion: insight federation across configured sources
├── creative_studio/     # Creator-grade ad-creative (image) generation via pluggable providers
├── byod/                # Bring Your Own Data — CSV-backed offline analysis (see BYOD Mode below)
├── web/                 # Local `mureo configure` UI — stdlib http.server on 127.0.0.1 (no web framework)
├── demo/                # `mureo demo init` synthetic-bundle bootstrap (round-trips through BYOD)
├── auth.py              # Credentials management (~/.mureo/credentials.json + env vars + Meta token auto-refresh)
├── auth_setup.py        # Interactive setup wizard (browser OAuth flow)
├── credential_guard.py  # Blocks AI agents from reading ~/.mureo/credentials.json
└── throttle.py          # Rate limiting (token bucket + rolling hourly cap)

skills/                       # Native slash skills — one `<name>/SKILL.md` per skill (migrated from
│                             #   .claude/commands in #439; invocable as `/<name>`). Plugins contribute
│                             #   more via the `mureo.native_skills` entry-point group, deployed/removed
│                             #   by `mureo/cli/native_skills.py`.
├── onboard/, daily-check/, rescue/, budget-rebalance/, …   # ~20 operational (workflow) skills
│   └── SKILL.md
└── _mureo-*/                 # 6 foundation skills: _mureo-shared / _mureo-strategy / _mureo-google-ads /
    └── SKILL.md              #   _mureo-meta-ads / _mureo-learning / _mureo-pro-diagnosis
docs/integrations.md          # Platform discovery + external MCP integration guide
```

## MCP Tools

### Google Ads

| Category | Tools |
|----------|-------|
| Campaigns | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update`, `campaigns.update_status`, `campaigns.diagnose` |
| Ad Groups | `ad_groups.list`, `ad_groups.create`, `ad_groups.update` |
| Ads | `ads.list`, `ads.create`, `ads.create_display`, `ads.update`, `ads.update_status`, `ads.policy_details` |
| Keywords | `keywords.list`, `keywords.add`, `keywords.remove`, `keywords.suggest`, `keywords.diagnose`, `keywords.pause`, `keywords.audit`, `keywords.cross_adgroup_duplicates` |
| Negative Keywords | `negative_keywords.list`, `negative_keywords.add`, `negative_keywords.remove`, `negative_keywords.add_to_ad_group`, `negative_keywords.suggest` |
| Budget | `budget.get`, `budget.update`, `budget.create` |
| Accounts | `accounts.list` |
| Search Terms | `search_terms.report`, `search_terms.analyze` |
| Sitelinks | `sitelinks.list`, `sitelinks.create`, `sitelinks.remove` |
| Callouts | `callouts.list`, `callouts.create`, `callouts.remove` |
| Conversions | `conversions.list`, `conversions.get`, `conversions.performance`, `conversions.create`, `conversions.update`, `conversions.remove`, `conversions.tag` |
| Targeting | `recommendations.list`, `recommendations.apply`, `device_targeting.get`, `device_targeting.set`, `bid_adjustments.get`, `bid_adjustments.update`, `location_targeting.list`, `location_targeting.update`, `schedule_targeting.list`, `schedule_targeting.update`, `change_history.list`, `demographic_targeting.list`, `audience_targeting.list` |
| Analysis | `performance.report`, `performance.analyze`, `cost_increase.investigate`, `health_check.all`, `ad_performance.compare`, `ad_performance.report`, `network_performance.report`, `budget.efficiency`, `budget.reallocation`, `auction_insights.get`, `rsa_assets.analyze`, `rsa_assets.audit`, `search_terms.review` |
| B2B | `btob.optimizations` |
| Creative | `landing_page.analyze`, `creative.research` |
| Monitoring | `monitoring.delivery_goal`, `monitoring.cpa_goal`, `monitoring.cv_goal`, `monitoring.zero_conversions` |
| Capture | `capture.screenshot` |
| Device | `device.analyze` |
| CPC | `cpc.detect_trend` |
| Assets | `assets.upload_image`, `image_assets.list` |

### Meta Ads

| Category | Tools |
|----------|-------|
| Campaigns | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update`, `campaigns.pause`, `campaigns.enable` |
| Ad Sets | `ad_sets.list`, `ad_sets.create`, `ad_sets.update`, `ad_sets.get`, `ad_sets.pause`, `ad_sets.enable` |
| Ads | `ads.list`, `ads.create`, `ads.update`, `ads.get`, `ads.pause`, `ads.enable` |
| Creatives | `creatives.create_carousel`, `creatives.create_collection`, `creatives.list`, `creatives.create`, `creatives.create_dynamic`, `creatives.upload_image` |
| Images | `images.upload_file` |
| Insights | `insights.report`, `insights.breakdown` |
| Audiences | `audiences.list`, `audiences.create`, `audiences.get`, `audiences.delete`, `audiences.create_lookalike` |
| Conversions API | `conversions.send`, `conversions.send_purchase`, `conversions.send_lead` |
| Pixels | `pixels.list`, `pixels.get`, `pixels.stats`, `pixels.events`, `pixels.create` |
| Analysis | `analysis.performance`, `analysis.audience`, `analysis.placements`, `analysis.cost`, `analysis.compare_ads`, `analysis.suggest_creative` |
| Product Catalog | `catalogs.list`, `catalogs.create`, `catalogs.get`, `catalogs.delete`, `products.list`, `products.add`, `products.get`, `products.update`, `products.delete`, `feeds.list`, `feeds.create` |
| Lead Ads | `lead_forms.list`, `lead_forms.get`, `lead_forms.create`, `leads.get`, `leads.get_by_ad` |
| Videos | `videos.upload`, `videos.upload_file` |
| Split Tests | `split_tests.list`, `split_tests.get`, `split_tests.create`, `split_tests.end` |
| Ad Rules | `ad_rules.list`, `ad_rules.get`, `ad_rules.create`, `ad_rules.update`, `ad_rules.delete` |
| Pages | `pages.list` |
| Page Posts | `page_posts.list`, `page_posts.boost` |
| Instagram | `instagram.accounts`, `instagram.media`, `instagram.boost` |

### Search Console

| Category | Tools |
|----------|-------|
| Sites | `sites.list`, `sites.get` |
| Analytics | `analytics.query`, `analytics.top_queries`, `analytics.top_pages`, `analytics.device_breakdown`, `analytics.compare_periods` |
| Sitemaps | `sitemaps.list`, `sitemaps.submit` |
| URL Inspection | `url_inspection.inspect` |

### mureo Core Tools (platform-independent)

These families are not tied to a single ad platform. Tool names are the exact MCP tool ids.

| Family | Tools |
|--------|-------|
| Analytics Registry (#440) | `mureo_analytics_modules_list`, `mureo_analytics_run` |
| Rollback | `rollback_plan_get`, `rollback_apply` |
| Analysis | `analysis_anomalies_check` |
| Creative Studio | `creative_studio_providers_list`, `creative_studio_generate_visual`, `creative_studio_edit_visual`, `creative_studio_compose`, `creative_studio_brand_kit_get` |
| Learning | `mureo_learning_insights_get`, `mureo_consult_advisor` |
| mureo Context | `mureo_strategy_get`, `mureo_strategy_set`, `mureo_state_get`, `mureo_state_action_log_append`, `mureo_state_upsert_campaign`, `mureo_state_report_set`, `mureo_state_platform_metrics_set`, `mureo_state_set_conversion_events`, `mureo_outcome_evaluate` |

## Design Constraints

- **Strategy-driven** — all operations are guided by STRATEGY.md context.
- **Workflow-first** — slash commands orchestrate multi-step operations.
- **Platform-agnostic** — designed to work with official platform MCPs as they become available.
- **No database dependencies** — no SQLAlchemy, no ORM. File-based context only (STRATEGY.md / STATE.json).
- **No LLM dependencies** — no OpenAI SDK, no Anthropic SDK. Tools return structured data for agents to interpret.
- **No web framework dependencies** — no FastAPI, no Flask. CLI (Typer) and MCP (stdio) only.
- **Tools return structured JSON data only** — no formatted text, no Markdown in tool responses.
- **All data models use frozen dataclasses** — immutable by default.
- **Credentials via file or env vars** — `~/.mureo/credentials.json` with environment variable fallback.
- **Built-in rate limiting** — token bucket throttling per platform prevents API bans from high-speed agent requests (Google Ads: 10 QPS, Meta Ads: 20 QPS + 50K/hr cap, Search Console: 5 QPS, Creative Studio: 1 QPS + 120/hr cap, Plugin tools: 5 QPS). See `mureo/throttle.py`.
- **Meta token auto-refresh** — Long-Lived Tokens are automatically refreshed when 53+ days old (requires `app_id` and `app_secret`). See `mureo/auth.py`.

## Coding Standards

- Python 3.10+
- PEP 8 compliance
- Type annotations on all function signatures
- `frozen=True` on all dataclasses
- File size limit: 800 lines
- Function size limit: 50 lines
- Formatter: **black** (line-length 88)
- Linter: **ruff** (select: E, F, I, N, W, UP, B, A, SIM, TCH)
- Type checker: **mypy** (strict mode)

## Commit Workflow

**Before EVERY code commit, run a code-review agent — no exceptions, including fixup and review-response commits.**

1. After `git add`, before `git commit`, invoke `python-reviewer` (or the language-appropriate `code-reviewer`) via the `Agent` tool.
2. For changes touching security boundaries (auth, OAuth, input validation, FS I/O of external input), also run `security-reviewer` in parallel.
3. If the reviewer reports HIGH or CRITICAL findings, fix them and **re-run the review** before committing — fixes can introduce new issues.
4. Only commit after the review is clean.

**A previous review on the same branch does NOT exempt a follow-up commit.** Each commit needs its own review pass — fixup commits, lint cleanups, and review-response commits all qualify.

**Exceptions (visual review is sufficient):**
- `docs/`, `README*`, or `CHANGELOG.md` only
- `pyproject.toml` version bump only
- Dependabot GitHub-Actions version bumps
- Pure typo fixes in comments / docstrings (no logic change)

**Not exceptions:**
- Any line of production code logic, even one line
- Any test file change (test correctness is reviewed too)
- Pure import-ordering edits

This rule was reinforced after PR #20 (2026-04-19, OAuth helper extraction — 6 issues including 2 HIGH found post-hoc) and PR #75 (2026-05-01, fixup commit pushed without re-review). "Tests green" and "lint clean" are NOT substitutes for code review.

## Test Coverage

- Target: 80% minimum (enforced by `tool.coverage.report.fail_under`)
- Framework: pytest + pytest-asyncio
- All external API calls (Google Ads, Meta Ads) **must** be mocked in tests
- Use `@pytest.mark.unit` / `@pytest.mark.integration` for categorization
- Async test mode: auto (`asyncio_mode = "auto"`)

## Credential Security

- Never hardcode API keys, tokens, or secrets in source code
- Credentials are loaded from `~/.mureo/credentials.json` (priority) or environment variables (fallback)
- Google Ads: `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`
- Meta Ads: `META_ADS_ACCESS_TOKEN`, `META_ADS_APP_ID`, `META_ADS_APP_SECRET`
- The `auth_setup.py` wizard writes credentials to `~/.mureo/credentials.json`

## BYOD Mode (Bring Your Own Data)

`mureo byod import <file>.xlsx` lets a user analyze their real ad-account data locally without OAuth. The bundle importer (`mureo/byod/bundle.py`) opens the workbook with openpyxl, dispatches recognized adapters by header signature, and writes per-platform CSVs under `~/.mureo/byod/<platform>/`. When `~/.mureo/byod/manifest.json` registers a platform, `mureo/mcp/_client_factory.py` routes that platform's MCP tool calls to a CSV-backed client (`mureo/byod/clients.py`) instead of the live API. Per-platform: imported platforms = BYOD; un-imported = Live API (or `_no_creds` error if no credentials). Supported BYOD platforms: `google_ads`, `meta_ads`. GA4 and Search Console remain on the Live API OAuth path.

When working on mureo:
- New ad-platform handlers MUST call `mureo/mcp/_client_factory.get_*_client(...)` for the BYOD path; real-mode dispatch can call `create_*_client` directly to keep test mocks at `mureo.mcp._handlers_*.create_*_client` working.
- BYOD clients are read-only. Mutation method name prefixes (`create_`, `update_`, `delete_`, `pause_`, `resume_`, `enable_`, `disable_`, `apply_`, `publish_`, `submit_`, `attach_`, `detach_`, `approve_`, `reject_`, `cancel_`, `set_`, `patch_`, `add_`, `remove_`, `send_`, `upload_`, `boost_`, `end_`, `duplicate_`, `export_`) return `{"status": "skipped_in_byod_readonly"}`. The authoritative list is `_MUTATION_PREFIXES` in `mureo/byod/clients.py` (25 prefixes).
- New bundle adapters live in `mureo/byod/adapters/<platform>.py` and must implement `has_tab(workbook)` (returns True when the workbook contains the adapter's required sheet/header signature) and `normalize_from_workbook(workbook, dst_dir)` (writes CSVs to `dst_dir`, returns an `ImportResult`). Both adapters (Google Ads and Meta Ads) import the shared helper `sanitize_cell` from `mureo/byod/adapters/_csv_safe.py` and apply it to every user-controlled cell against CSV injection (it prefixes formula triggers `=`, `+`, `-`, `@`, tab, CR with a single quote), then write to the mureo internal schema documented in `docs/byod.md`.
- Bundle imports MUST never escape `~/.mureo/byod/` — `bundle.py` and `installer.remove_platform` both enforce path-traversal guards.
- See `docs/byod.md` for the user-facing walkthrough and the recommended Saved Report configuration for Meta Ads (multilingual: 9 locales).

## GAQL Injection Prevention

Google Ads queries use GAQL (Google Ads Query Language). When constructing queries:
- Never interpolate user input directly into GAQL strings
- Use parameterized values for customer_id, campaign_id, etc.
- Validate ID formats before use (numeric strings only)
- Route all IDs/dates through the dedicated validator `mureo/google_ads/_gaql_validator.py`. Its ID pattern uses ASCII `[0-9]+` (not `\d`), so full-width / Unicode digits (e.g. `１２３`, `٣٤٥`) are rejected rather than silently accepted and interpolated (#441).
