<p align="center">
  <img src="docs/img/logo.png" alt="mureo" width="300">
</p>

<p align="center">
  Marketing operations toolkit for AI agents — CLI & MCP.
</p>

## What is mureo?

**mureo** is an open toolkit that lets AI agents (Claude Code, Cursor, etc.) operate marketing platforms directly. Currently supports **Google Ads** and **Meta Ads**, with more platforms planned.

- **MCP server** -- expose marketing-operation tools over the Model Context Protocol so agents can read, create, update, and analyze campaigns directly.
- **CLI** -- the same operations available as shell commands for scripting and quick checks.
- **No DB, no LLM** -- mureo is the "hands" of your agent, not the "brain." It wraps platform APIs and returns structured JSON. All reasoning stays on the agent side.
- **File-based context** -- optional `STRATEGY.md` and `STATE.json` files let agents persist strategy notes and campaign state without a database.

## Quick Start

```bash
pip install mureo

# Interactive setup wizard (OAuth + MCP config)
mureo auth setup

# MCP server (for Claude Code / Cursor)
python -m mureo.mcp

# CLI
mureo google-ads campaigns-list --customer-id 1234567890
mureo meta-ads campaigns-list --account-id act_1234567890
```

Install only the pieces you need:

```bash
pip install mureo            # core (API clients only)
pip install "mureo[cli]"     # + CLI (typer, rich)
pip install "mureo[mcp]"     # + MCP server
pip install "mureo[cli,mcp]" # everything
```

## Authentication

### Interactive Setup (Recommended)

```bash
mureo auth setup
```

The setup wizard walks you through:

1. **Google Ads** -- Enter Developer Token + Client ID/Secret, open browser for OAuth, select a Google Ads customer account
2. **Meta Ads** -- Enter App ID/Secret, open browser for OAuth, obtain a Long-Lived Token, select an ad account
3. **MCP config** -- Automatically writes `.mcp.json` (project-level) or `~/.claude/settings.json` (global) so Claude Code / Cursor can discover the server

Credentials are saved to `~/.mureo/credentials.json`.

### credentials.json

```json
{
  "google_ads": {
    "developer_token": "YOUR_DEVELOPER_TOKEN",
    "client_id": "YOUR_CLIENT_ID",
    "client_secret": "YOUR_CLIENT_SECRET",
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "login_customer_id": "1234567890"
  },
  "meta_ads": {
    "access_token": "YOUR_ACCESS_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET"
  }
}
```

### Environment variables (fallback)

| Platform   | Variable                          | Required |
|------------|-----------------------------------|----------|
| Google Ads | `GOOGLE_ADS_DEVELOPER_TOKEN`      | Yes      |
| Google Ads | `GOOGLE_ADS_CLIENT_ID`            | Yes      |
| Google Ads | `GOOGLE_ADS_CLIENT_SECRET`        | Yes      |
| Google Ads | `GOOGLE_ADS_REFRESH_TOKEN`        | Yes      |
| Google Ads | `GOOGLE_ADS_LOGIN_CUSTOMER_ID`    | No       |
| Meta Ads   | `META_ADS_ACCESS_TOKEN`           | Yes      |
| Meta Ads   | `META_ADS_APP_ID`                 | No       |
| Meta Ads   | `META_ADS_APP_SECRET`             | No       |

Verify your setup:

```bash
mureo auth status
mureo auth check-google
mureo auth check-meta
```

## MCP Server

### Setup with Claude Code

**Project-level** (recommended) -- add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

**Global** -- add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

> Tip: `mureo auth setup` can write this configuration automatically.

### Setup with Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

### Tool list (81 tools)

#### Google Ads (29 tools)

| Tool | Description |
|------|-------------|
| `google_ads.campaigns.list` | List campaigns |
| `google_ads.campaigns.get` | Get campaign details |
| `google_ads.campaigns.create` | Create a campaign |
| `google_ads.campaigns.update` | Update campaign settings |
| `google_ads.campaigns.update_status` | Change campaign status (ENABLED/PAUSED/REMOVED) |
| `google_ads.campaigns.diagnose` | Diagnose campaign delivery status |
| `google_ads.ad_groups.list` | List ad groups |
| `google_ads.ad_groups.create` | Create an ad group |
| `google_ads.ad_groups.update` | Update an ad group |
| `google_ads.ads.list` | List ads |
| `google_ads.ads.create` | Create a responsive search ad (RSA) |
| `google_ads.ads.update` | Update an ad |
| `google_ads.ads.update_status` | Change ad status |
| `google_ads.keywords.list` | List keywords |
| `google_ads.keywords.add` | Add keywords |
| `google_ads.keywords.remove` | Remove a keyword |
| `google_ads.keywords.suggest` | Get keyword suggestions (Keyword Planner) |
| `google_ads.keywords.diagnose` | Diagnose keyword quality scores |
| `google_ads.negative_keywords.list` | List negative keywords |
| `google_ads.negative_keywords.add` | Add negative keywords |
| `google_ads.budget.get` | Get campaign budget |
| `google_ads.budget.update` | Update budget |
| `google_ads.performance.report` | Get performance report |
| `google_ads.search_terms.report` | Get search terms report |
| `google_ads.search_terms.review` | Review search terms and suggest additions/exclusions |
| `google_ads.auction_insights.analyze` | Analyze auction insights |
| `google_ads.cpc.detect_trend` | Detect CPC trend (rising/stable/falling) |
| `google_ads.device.analyze` | Analyze device-level performance |
| `google_ads.assets.upload_image` | Upload an image asset |

#### Meta Ads (52 tools)

**Campaigns (4)**

| Tool | Description |
|------|-------------|
| `meta_ads.campaigns.list` | List campaigns |
| `meta_ads.campaigns.get` | Get campaign details |
| `meta_ads.campaigns.create` | Create a campaign |
| `meta_ads.campaigns.update` | Update a campaign |

**Ad Sets (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.ad_sets.list` | List ad sets |
| `meta_ads.ad_sets.create` | Create an ad set |
| `meta_ads.ad_sets.update` | Update an ad set |

**Ads (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.ads.list` | List ads |
| `meta_ads.ads.create` | Create an ad |
| `meta_ads.ads.update` | Update an ad |

**Creatives (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.creatives.create_carousel` | Create a carousel creative (2-10 cards) |
| `meta_ads.creatives.create_collection` | Create a collection creative |
| `meta_ads.images.upload_file` | Upload an image from local file |

**Insights (2)**

| Tool | Description |
|------|-------------|
| `meta_ads.insights.report` | Get performance report |
| `meta_ads.insights.breakdown` | Get breakdown report (age, gender, placement, etc.) |

**Audiences (2)**

| Tool | Description |
|------|-------------|
| `meta_ads.audiences.list` | List custom audiences |
| `meta_ads.audiences.create` | Create a custom audience |

**Conversions API (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.conversions.send` | Send a conversion event (generic) |
| `meta_ads.conversions.send_purchase` | Send a purchase event |
| `meta_ads.conversions.send_lead` | Send a lead event |

**Product Catalog (11)**

| Tool | Description |
|------|-------------|
| `meta_ads.catalogs.list` | List product catalogs |
| `meta_ads.catalogs.create` | Create a product catalog |
| `meta_ads.catalogs.get` | Get catalog details |
| `meta_ads.catalogs.delete` | Delete a catalog |
| `meta_ads.products.list` | List products in a catalog |
| `meta_ads.products.add` | Add a product to a catalog |
| `meta_ads.products.get` | Get product details |
| `meta_ads.products.update` | Update a product |
| `meta_ads.products.delete` | Delete a product |
| `meta_ads.feeds.list` | List catalog feeds |
| `meta_ads.feeds.create` | Create a catalog feed (URL + scheduled import) |

**Lead Ads (5)**

| Tool | Description |
|------|-------------|
| `meta_ads.lead_forms.list` | List lead forms (per Page) |
| `meta_ads.lead_forms.get` | Get lead form details |
| `meta_ads.lead_forms.create` | Create a lead form |
| `meta_ads.leads.get` | Get leads (per form) |
| `meta_ads.leads.get_by_ad` | Get leads (per ad) |

**Videos (2)**

| Tool | Description |
|------|-------------|
| `meta_ads.videos.upload` | Upload a video from URL |
| `meta_ads.videos.upload_file` | Upload a video from local file |

**Split Tests (4)**

| Tool | Description |
|------|-------------|
| `meta_ads.split_tests.list` | List A/B tests |
| `meta_ads.split_tests.get` | Get A/B test details and results |
| `meta_ads.split_tests.create` | Create an A/B test |
| `meta_ads.split_tests.end` | End an A/B test |

**Ad Rules (5)**

| Tool | Description |
|------|-------------|
| `meta_ads.ad_rules.list` | List automated rules |
| `meta_ads.ad_rules.get` | Get automated rule details |
| `meta_ads.ad_rules.create` | Create an automated rule (CPA alerts, auto-pause, etc.) |
| `meta_ads.ad_rules.update` | Update an automated rule |
| `meta_ads.ad_rules.delete` | Delete an automated rule |

**Page Posts (2)**

| Tool | Description |
|------|-------------|
| `meta_ads.page_posts.list` | List Facebook Page posts |
| `meta_ads.page_posts.boost` | Boost a Page post |

**Instagram (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.instagram.accounts` | List connected Instagram accounts |
| `meta_ads.instagram.media` | List Instagram posts |
| `meta_ads.instagram.boost` | Boost an Instagram post |

## CLI

```
mureo [google-ads|meta-ads|auth] <command> [options]
```

### Google Ads examples

```bash
# List campaigns
mureo google-ads campaigns-list --customer-id 1234567890

# Get campaign details
mureo google-ads campaigns-get --customer-id 1234567890 --campaign-id 111222333

# Performance report
mureo google-ads performance-report --customer-id 1234567890 --period LAST_7_DAYS
```

### Meta Ads examples

```bash
# List campaigns
mureo meta-ads campaigns-list --account-id act_1234567890

# Get insights
mureo meta-ads insights-report --account-id act_1234567890 --period last_7d
```

## Strategy Context

mureo supports two optional local files that let agents persist context across sessions.

### STRATEGY.md

A Markdown file containing strategic context for ad operations. Agents can read this to understand business goals before making changes.

```markdown
# Strategy

## Persona
B2B SaaS decision-makers, 30-50 years old, IT managers and CTOs.

## USP
Only platform that integrates AI agents with ad operations.

## Target Audience
Small-to-mid size marketing teams running Google Ads and Meta Ads.

## Brand Voice
Professional but approachable. Data-driven recommendations.

## Market Context
Competitive CPC rising 15% YoY in the SaaS category.

## Custom: Q1 Goals
Reduce CPA by 20% while maintaining conversion volume.
```

### STATE.json

A JSON snapshot of current campaign state. Updated automatically when agents read campaigns via tools.

```json
{
  "version": "1",
  "last_synced_at": "2025-01-15T10:30:00Z",
  "customer_id": "1234567890",
  "campaigns": [
    {
      "campaign_id": "111222333",
      "campaign_name": "Brand - Search",
      "status": "ENABLED",
      "bidding_strategy_type": "TARGET_CPA",
      "daily_budget": 5000
    }
  ]
}
```

## Architecture

```
mureo/
├── __init__.py              # Package root
├── auth.py                  # Credential loading (~/.mureo/credentials.json + env vars)
├── auth_setup.py            # Interactive setup wizard (OAuth + MCP config)
├── _image_validation.py     # Image file validation utilities
├── google_ads/              # Google Ads API client (google-ads SDK wrapper)
│   ├── client.py            # GoogleAdsApiClient (5 Mixin: Analysis, Creative, Diagnostics, Media, Monitoring)
│   ├── mappers.py           # Response mapping to structured dicts
│   ├── _ads.py              # Ad CRUD operations
│   ├── _keywords.py         # Keyword management
│   ├── _analysis.py         # Performance analysis, auction insights, CPC trends, device analysis
│   ├── _analysis_*.py       # Analysis sub-modules (auction, btob, budget, keywords, performance, rsa, search_terms)
│   ├── _creative.py         # LP analysis + creative research
│   ├── _diagnostics.py      # Campaign/keyword diagnostics
│   ├── _extensions.py       # Sitelinks, callouts, conversions, targeting
│   ├── _media.py            # Image asset upload
│   ├── _monitoring.py       # Anomaly detection, reports, goal tracking
│   ├── _rsa_validator.py    # RSA ad validator
│   ├── _rsa_insights.py     # RSA asset performance insights
│   ├── _message_match.py    # Message match evaluation (Vision LLM)
│   └── _intent_classifier.py # Search term intent classification
├── meta_ads/                # Meta Ads API client (httpx-based, Meta Marketing API)
│   ├── client.py            # MetaAdsApiClient (15 Mixin: Campaigns, AdSets, Ads, Creatives, Audiences,
│   │                        #   Pixels, Insights, Analysis, Catalog, Conversions, Leads, PagePosts,
│   │                        #   Instagram, SplitTest, AdRules)
│   ├── mappers.py           # Response mapping to structured dicts
│   ├── _campaigns.py        # Campaign CRUD
│   ├── _ad_sets.py          # Ad set CRUD
│   ├── _ads.py              # Ad CRUD
│   ├── _creatives.py        # Carousel, collection creatives + image upload
│   ├── _audiences.py        # Custom audience management
│   ├── _pixels.py           # Pixel management
│   ├── _insights.py         # Performance reports + breakdowns
│   ├── _analysis.py         # Cross-cutting analysis utilities
│   ├── _catalog.py          # Product catalog + feeds + products
│   ├── _conversions.py      # Conversions API (CAPI)
│   ├── _leads.py            # Lead forms + lead data retrieval
│   ├── _page_posts.py       # Facebook Page post management + boosting
│   ├── _instagram.py        # Instagram accounts, media, boosting
│   ├── _split_test.py       # A/B test management
│   └── _ad_rules.py         # Automated rules (CPA alerts, auto-pause)
├── analysis/                # Cross-platform analysis utilities
│   └── lp_analyzer.py       # Landing page analysis engine
├── context/                 # File-based context (STRATEGY.md, STATE.json)
│   ├── models.py            # Immutable dataclasses (StrategyEntry, StateDocument)
│   ├── strategy.py          # STRATEGY.md parser / renderer
│   ├── state.py             # STATE.json parser / renderer
│   └── errors.py            # Context-related errors
├── cli/                     # Typer CLI commands
│   ├── main.py              # Entry point (mureo command)
│   ├── auth_cmd.py          # mureo auth * (status, check-google, check-meta, setup)
│   ├── google_ads.py        # mureo google-ads *
│   └── meta_ads.py          # mureo meta-ads *
└── mcp/                     # MCP server
    ├── __main__.py           # python -m mureo.mcp entry point
    ├── server.py             # MCP server setup (stdio transport)
    ├── _helpers.py           # Shared handler utilities
    ├── tools_google_ads.py   # 29 Google Ads tool definitions
    ├── _handlers_google_ads.py # Google Ads tool handlers
    ├── tools_meta_ads.py     # 52 Meta Ads tool definitions
    └── _handlers_meta_ads.py # Meta Ads tool handlers
```

**Design principles:**

- **No database** -- all state is either in the ad platform APIs or in local files (`STRATEGY.md`, `STATE.json`).
- **No LLM dependency** -- mureo is a pure API toolkit. Inference, planning, and decision-making are the agent's responsibility.
- **Immutable data models** -- all dataclasses use `frozen=True` to prevent accidental mutation.
- **Credentials stay local** -- loaded from `~/.mureo/credentials.json` or environment variables. Never sent anywhere except the official ad platform APIs.

## Development

```bash
git clone https://github.com/logly/mureo.git
cd mureo-core

# Install with all extras
pip install -e ".[dev,cli,mcp]"

# Run tests
pytest tests/ -v

# With coverage
pytest --cov=mureo --cov-report=term-missing

# Lint & format
ruff check mureo/
black mureo/
mypy mureo/
```

### Requirements

- Python 3.10+
- For Google Ads: a Google Ads developer token and OAuth 2.0 credentials
- For Meta Ads: a Meta (Facebook) access token

## License

Apache License 2.0
