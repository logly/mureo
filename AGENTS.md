# AGENTS.md

Guidelines for AI agents contributing to the mureo codebase.

## Project Overview

mureo is a marketing orchestration framework for AI agents. It combines strategy
context, workflow commands, and domain knowledge to help agents achieve marketing
goals across platforms. Currently supports Google Ads, Meta Ads, and Google Search Console, with more
platforms planned. Provides MCP tools for direct platform operations and
workflow commands for strategy-driven ad operations via Claude Code slash commands.
Designed for AI agents — no database, no LLM SDK, no web framework.

## Build & Test

```bash
pip install -e ".[dev]"
pytest tests/ -v
pytest tests/ --cov=mureo --cov-report=term-missing
```

## Architecture

```
mureo/
├── google_ads/          # Google Ads API client (8 Mixin composition)
│   ├── client.py        # GoogleAdsApiClient (main entry)
│   ├── mappers.py       # Response mapping to structured dicts
│   ├── _ads.py          # AdsMixin (create/update/status/list)
│   ├── _keywords.py     # KeywordsMixin (add/remove/suggest/diagnose)
│   ├── _analysis.py     # AnalysisMixin (auction/CPC/device/BtoB/RSA)
│   ├── _diagnostics.py  # DiagnosticsMixin (campaign diagnosis)
│   ├── _extensions.py   # ExtensionsMixin (sitelinks/callouts/conversions/targeting)
│   ├── _monitoring.py   # MonitoringMixin (anomaly detection/reporting)
│   ├── _creative.py     # CreativeMixin (LP analysis/message match)
│   ├── _media.py        # MediaMixin (image asset upload)
│   ├── _rsa_validator.py     # RSA ad validator
│   ├── _rsa_insights.py      # RSA asset performance insights
│   ├── _intent_classifier.py # Search term intent classification
│   └── _message_match.py     # Message match evaluator
├── meta_ads/            # Meta Ads API client (15 Mixin composition)
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
│   └── _ad_rules.py     # AdRulesMixin (automated rules)
├── search_console/      # Google Search Console API client (reuses Google OAuth2 credentials)
│   └── client.py        # SearchConsoleApiClient
├── mcp/                 # MCP server (Google Ads + Meta Ads + Search Console)
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
│   └── _handlers_search_console.py        # Search Console handlers
├── cli/                 # Typer CLI (setup + auth only; ad operations are via MCP)
│   ├── main.py          # CLI entry point (`mureo` command)
│   ├── setup_cmd.py     # `mureo setup claude-code` / `mureo setup cursor`
│   └── auth_cmd.py      # `mureo auth setup` / `status` / `check-*`
├── context/             # File-based strategy context (no DB)
│   ├── strategy.py      # STRATEGY.md parser/writer
│   ├── state.py         # STATE.json parser/writer
│   ├── models.py        # StrategyEntry, StateDocument, CampaignSnapshot
│   └── errors.py        # Context-specific errors
├── analysis/            # Analysis utilities
│   └── lp_analyzer.py   # Landing page analyzer
.claude/commands/            # Workflow slash commands (11 orchestration commands)
│   ├── onboard.md           # Platform discovery + strategy setup
│   ├── daily-check.md       # Cross-platform health monitoring (ad platforms + SC + GA4)
│   ├── rescue.md            # Multi-platform emergency rescue (with GA4 site-side diagnosis)
│   ├── search-term-cleanup.md # Cross-platform keyword hygiene (with paid/organic overlap)
│   ├── creative-refresh.md  # Multi-platform creative refresh (with organic keyword insights)
│   ├── budget-rebalance.md  # Cross-platform budget optimization (with organic intelligence)
│   ├── competitive-scan.md  # Paid + organic competitive landscape analysis
│   ├── goal-review.md       # Multi-source goal evaluation
│   ├── weekly-report.md     # Cross-platform weekly operations report
│   ├── sync-state.md        # Multi-platform STATE.json synchronization
│   └── learn.md   # Save diagnostic insights to knowledge base
skills/mureo-workflows/      # Workflow skill reference
│   └── SKILL.md             # Orchestration paradigm + Operation Mode reference
skills/mureo-learning/       # Evidence-based decision framework
│   └── SKILL.md             # Statistical thinking for marketing decisions
skills/mureo-pro-diagnosis/  # Learnable diagnostic knowledge base
│   └── SKILL.md             # Diagnostic insights (grows with /learn)
docs/integrations.md         # Platform discovery + external MCP integration guide
├── auth.py              # Credentials management (~/.mureo/credentials.json + env vars + Meta token auto-refresh)
├── auth_setup.py        # Interactive setup wizard (browser OAuth flow)
└── throttle.py          # Rate limiting (token bucket + rolling hourly cap)
```

## MCP Tools

### Google Ads

| Category | Tools |
|----------|-------|
| Campaigns (6) | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update`, `campaigns.update_status`, `campaigns.diagnose` |
| Ad Groups (3) | `ad_groups.list`, `ad_groups.create`, `ad_groups.update` |
| Ads (5) | `ads.list`, `ads.create`, `ads.update`, `ads.update_status`, `ads.policy_details` |
| Keywords (8) | `keywords.list`, `keywords.add`, `keywords.remove`, `keywords.suggest`, `keywords.diagnose`, `keywords.pause`, `keywords.audit`, `keywords.cross_adgroup_duplicates` |
| Negative Keywords (5) | `negative_keywords.list`, `negative_keywords.add`, `negative_keywords.remove`, `negative_keywords.add_to_ad_group`, `negative_keywords.suggest` |
| Budget (3) | `budget.get`, `budget.update`, `budget.create` |
| Accounts (1) | `accounts.list` |
| Search Terms (2) | `search_terms.report`, `search_terms.analyze` |
| Sitelinks (3) | `sitelinks.list`, `sitelinks.create`, `sitelinks.remove` |
| Callouts (3) | `callouts.list`, `callouts.create`, `callouts.remove` |
| Conversions (7) | `conversions.list`, `conversions.get`, `conversions.performance`, `conversions.create`, `conversions.update`, `conversions.remove`, `conversions.tag` |
| Targeting (11) | `recommendations.list`, `recommendations.apply`, `device_targeting.get`, `device_targeting.set`, `bid_adjustments.get`, `bid_adjustments.update`, `location_targeting.list`, `location_targeting.update`, `schedule_targeting.list`, `schedule_targeting.update`, `change_history.list` |
| Analysis (13) | `performance.report`, `performance.analyze`, `cost_increase.investigate`, `health_check.all`, `ad_performance.compare`, `ad_performance.report`, `network_performance.report`, `budget.efficiency`, `budget.reallocation`, `auction_insights.get`, `rsa_assets.analyze`, `rsa_assets.audit`, `search_terms.review` |
| B2B (1) | `btob.optimizations` |
| Creative (2) | `landing_page.analyze`, `creative.research` |
| Monitoring (4) | `monitoring.delivery_goal`, `monitoring.cpa_goal`, `monitoring.cv_goal`, `monitoring.zero_conversions` |
| Capture (1) | `capture.screenshot` |
| Device (1) | `device.analyze` |
| CPC (1) | `cpc.detect_trend` |
| Assets (1) | `assets.upload_image` |

### Meta Ads

| Category | Tools |
|----------|-------|
| Campaigns (6) | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update`, `campaigns.pause`, `campaigns.enable` |
| Ad Sets (6) | `ad_sets.list`, `ad_sets.create`, `ad_sets.update`, `ad_sets.get`, `ad_sets.pause`, `ad_sets.enable` |
| Ads (6) | `ads.list`, `ads.create`, `ads.update`, `ads.get`, `ads.pause`, `ads.enable` |
| Creatives (6) | `creatives.create_carousel`, `creatives.create_collection`, `creatives.list`, `creatives.create`, `creatives.create_dynamic`, `creatives.upload_image` |
| Images (1) | `images.upload_file` |
| Insights (2) | `insights.report`, `insights.breakdown` |
| Audiences (5) | `audiences.list`, `audiences.create`, `audiences.get`, `audiences.delete`, `audiences.create_lookalike` |
| Conversions API (3) | `conversions.send`, `conversions.send_purchase`, `conversions.send_lead` |
| Pixels (4) | `pixels.list`, `pixels.get`, `pixels.stats`, `pixels.events` |
| Analysis (6) | `analysis.performance`, `analysis.audience`, `analysis.placements`, `analysis.cost`, `analysis.compare_ads`, `analysis.suggest_creative` |
| Product Catalog (11) | `catalogs.list`, `catalogs.create`, `catalogs.get`, `catalogs.delete`, `products.list`, `products.add`, `products.get`, `products.update`, `products.delete`, `feeds.list`, `feeds.create` |
| Lead Ads (5) | `lead_forms.list`, `lead_forms.get`, `lead_forms.create`, `leads.get`, `leads.get_by_ad` |
| Videos (2) | `videos.upload`, `videos.upload_file` |
| Split Tests (4) | `split_tests.list`, `split_tests.get`, `split_tests.create`, `split_tests.end` |
| Ad Rules (5) | `ad_rules.list`, `ad_rules.get`, `ad_rules.create`, `ad_rules.update`, `ad_rules.delete` |
| Page Posts (2) | `page_posts.list`, `page_posts.boost` |
| Instagram (3) | `instagram.accounts`, `instagram.media`, `instagram.boost` |

### Search Console

| Category | Tools |
|----------|-------|
| Sites (2) | `sites.list`, `sites.get` |
| Analytics (5) | `analytics.query`, `analytics.top_queries`, `analytics.top_pages`, `analytics.device_breakdown`, `analytics.compare_periods` |
| Sitemaps (2) | `sitemaps.list`, `sitemaps.submit` |
| URL Inspection (1) | `url_inspection.inspect` |

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
- **Built-in rate limiting** — token bucket throttling per platform prevents API bans from high-speed agent requests (Google Ads: 10 QPS, Meta Ads: 20 QPS + 50K/hr cap, Search Console: 5 QPS). See `mureo/throttle.py`.
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

## Test Coverage

- 95% coverage
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

## GAQL Injection Prevention

Google Ads queries use GAQL (Google Ads Query Language). When constructing queries:
- Never interpolate user input directly into GAQL strings
- Use parameterized values for customer_id, campaign_id, etc.
- Validate ID formats before use (numeric strings only)
