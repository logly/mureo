# AGENTS.md

Guidelines for AI agents contributing to the mureo codebase.

## Project Overview

mureo is a Python CLI/MCP toolkit for managing Google Ads and Meta Ads accounts.
It is designed to be used by AI agents — no database, no LLM SDK, no web framework.

## Build & Test

```bash
pip install -e ".[dev,cli,mcp]"
pytest tests/ -v
pytest tests/ --cov=mureo --cov-report=term-missing
```

## Architecture

```
mureo/
├── google_ads/          # Google Ads API client (7 Mixin composition)
│   ├── client.py        # GoogleAdsApiClient (main entry)
│   ├── mappers.py       # Response mapping to structured dicts
│   ├── _ads.py          # AdsMixin (create/update/status/list)
│   ├── _keywords.py     # KeywordsMixin (add/remove/suggest/diagnose)
│   ├── _analysis.py     # AnalysisMixin (auction/CPC/device/BtoB/RSA)
│   ├── _diagnostics.py  # DiagnosticsMixin (campaign diagnosis)
│   ├── _extensions.py   # ExtensionsMixin (sitelinks/callouts/conversions/targeting)
│   ├── _monitoring.py   # MonitoringMixin (anomaly detection/reporting)
│   ├── _creative.py     # CreativeMixin (LP analysis/message match)
│   ├── _rsa_validator.py     # RSA ad validator
│   ├── _rsa_insights.py      # RSA asset performance insights
│   ├── _intent_classifier.py # Search term intent classification
│   └── _message_match.py     # Message match evaluator
├── meta_ads/            # Meta Ads API client (8 Mixin composition)
│   ├── client.py        # MetaAdsApiClient (main entry)
│   ├── mappers.py       # Response mapping
│   ├── _campaigns.py    # CampaignsMixin
│   ├── _ad_sets.py      # AdSetsMixin
│   ├── _ads.py          # AdsMixin
│   ├── _creatives.py    # CreativesMixin
│   ├── _audiences.py    # AudiencesMixin
│   ├── _pixels.py       # PixelsMixin
│   ├── _insights.py     # InsightsMixin
│   └── _analysis.py     # AnalysisMixin
├── mcp/                 # MCP server (42 tools: 28 Google Ads + 14 Meta Ads)
│   ├── server.py        # MCP Server entry point (stdio-based)
│   ├── tools_google_ads.py       # Google Ads tool definitions (28)
│   ├── tools_meta_ads.py         # Meta Ads tool definitions (14)
│   ├── _handlers_google_ads.py   # Google Ads handler implementations
│   └── _helpers.py               # Shared handler utilities
├── cli/                 # Typer CLI wrapper
│   ├── main.py          # CLI entry point (`mureo` command)
│   ├── google_ads.py    # `mureo google-ads` subcommands
│   ├── meta_ads.py      # `mureo meta-ads` subcommands
│   └── auth_cmd.py      # `mureo auth` subcommands
├── context/             # File-based strategy context (no DB)
│   ├── strategy.py      # STRATEGY.md parser/writer
│   ├── state.py         # STATE.json parser/writer
│   ├── models.py        # StrategyEntry, StateDocument, CampaignSnapshot
│   └── errors.py        # Context-specific errors
├── analysis/            # Analysis utilities
│   └── lp_analyzer.py   # Landing page analyzer
├── auth.py              # Credentials management (~/.mureo/credentials.json + env vars)
└── auth_setup.py        # Interactive setup wizard (browser OAuth flow)
```

## MCP Tools (42 total)

### Google Ads (28 tools)

| Category | Tools |
|----------|-------|
| Campaigns (6) | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update`, `campaigns.update_status`, `campaigns.diagnose` |
| Ad Groups (3) | `ad_groups.list`, `ad_groups.create`, `ad_groups.update` |
| Ads (4) | `ads.list`, `ads.create`, `ads.update`, `ads.update_status` |
| Keywords (5) | `keywords.list`, `keywords.add`, `keywords.remove`, `keywords.suggest`, `keywords.diagnose` |
| Negative Keywords (2) | `negative_keywords.list`, `negative_keywords.add` |
| Budget (2) | `budget.get`, `budget.update` |
| Analysis (6) | `performance.report`, `search_terms.report`, `search_terms.review`, `auction_insights.analyze`, `cpc.detect_trend`, `device.analyze` |

### Meta Ads (14 tools)

| Category | Tools |
|----------|-------|
| Campaigns (4) | `campaigns.list`, `campaigns.get`, `campaigns.create`, `campaigns.update` |
| Ad Sets (3) | `ad_sets.list`, `ad_sets.create`, `ad_sets.update` |
| Ads (3) | `ads.list`, `ads.create`, `ads.update` |
| Insights (2) | `insights.report`, `insights.breakdown` |
| Audiences (2) | `audiences.list`, `audiences.create` |

## Design Constraints

- **No database dependencies** — no SQLAlchemy, no ORM. File-based context only (STRATEGY.md / STATE.json).
- **No LLM dependencies** — no OpenAI SDK, no Anthropic SDK. Tools return structured data for agents to interpret.
- **No web framework dependencies** — no FastAPI, no Flask. CLI (Typer) and MCP (stdio) only.
- **Tools return structured JSON data only** — no formatted text, no Markdown in tool responses.
- **All data models use frozen dataclasses** — immutable by default.
- **Credentials via file or env vars** — `~/.mureo/credentials.json` with environment variable fallback.

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

- 25+ test files, 92% coverage
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
