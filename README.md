<p align="center">
  <img src="docs/img/logo.png" alt="mureo" width="300">
</p>

<p align="center">
  Marketing orchestration framework for AI agents.
</p>

<p align="center">
  <a href="README.ja.md">日本語</a>
</p>

## What is mureo?

**mureo** is a marketing orchestration framework that helps AI agents achieve real business goals — awareness, leads, sales, retention — not just execute API calls. It combines strategy context, workflow commands, and built-in domain knowledge to guide agents through marketing operations across multiple platforms.

Ad platform APIs will increasingly be exposed through official MCPs from Google, Meta, and others. mureo's value is not in wrapping those APIs. It is in the **orchestration layer on top**: knowing *what* to do, *when* to do it, and *why* — informed by your business strategy.

- **Strategy-driven** -- `STRATEGY.md` defines your persona, USP, brand voice, goals, and operation mode. Every decision the agent makes is grounded in your strategy, not just raw metrics.
- **Workflow commands** -- 10 slash commands (`/daily-check`, `/rescue`, `/creative-refresh`, etc.) guide agents through complete marketing operations, connecting strategy context with the right tools in the right order.
- **Cross-platform** -- orchestrates across Google Ads, Meta Ads, Search Console, and GA4 (with more platforms planned), enabling coordinated decisions that no single-platform tool can make.
- **Built-in domain knowledge** -- analysis, diagnostics, and optimization logic that turns raw API data into actionable insights. Campaign diagnostics with 30+ reason codes, search term intent analysis, budget efficiency scoring, RSA validation, and more.
- **MCP + CLI interface** -- 169 MCP tools for AI agents (Claude Code, Cursor, etc.) plus a CLI for scripting and quick checks.
- **No DB, no LLM dependency** -- mureo is the "hands" of your agent, not the "brain." All state lives in local files (`STRATEGY.md`, `STATE.json`) or the ad platforms themselves. All reasoning stays on the agent side.

### Analysis & Diagnostics

| Capability | Description |
|------------|-------------|
| **Campaign diagnostics** | Delivery status analysis with 30+ reason codes, learning period detection, smart bidding strategy classification |
| **Performance analysis** | Period-over-period comparison, cost increase investigation, cross-campaign health checks |
| **Search term analysis** | N-gram distribution, intent pattern detection, automated add/exclude candidate scoring |
| **Budget efficiency** | Cross-campaign budget allocation analysis, reallocation recommendations |
| **RSA ad validation** | Prohibited expression detection, character width calculation, auto-correction, ad strength prediction |
| **RSA asset audit** | Asset-level performance analysis, replacement/addition recommendations |
| **Device analysis** | CPA gap detection, zero-conversion device identification |
| **Auction insights** | Competitive landscape analysis, impression share trends |
| **B2B optimization** | Industry-specific campaign checks and recommendations |

### Creative & Landing Page

| Capability | Description |
|------------|-------------|
| **Landing page analysis** | HTML parsing with SSRF protection, structured data extraction, industry estimation, CTA/feature/price detection |
| **Creative research** | Aggregates LP analysis + existing ads + search terms + keyword suggestions into a unified research package |
| **Message match evaluation** | Framework for scoring ad copy ↔ landing page alignment (screenshot capture via Playwright) |

### Monitoring & Goal Evaluation

| Capability | Description |
|------------|-------------|
| **Delivery goal evaluation** | Integrates campaign status + diagnostics + performance into critical/warning/healthy classification |
| **CPA goal tracking** | Compares actual CPA against targets with trend analysis |
| **CV goal tracking** | Daily conversion volume monitoring against targets |
| **Zero-conversion diagnosis** | Root cause analysis for campaigns with no conversions |

### Meta Ads Analysis

| Capability | Description |
|------------|-------------|
| **Placement analysis** | Performance breakdown by publisher platform (Facebook, Instagram, Audience Network) |
| **Cost investigation** | CPA degradation root cause analysis |
| **Ad comparison** | A/B performance comparison within ad sets |
| **Creative suggestions** | Data-driven creative improvement recommendations |
| **PII hashing** | SHA-256 hashing with field-specific normalization for Conversions API compliance |

### Infrastructure

| Capability | Description |
|------------|-------------|
| **Rate limiting** | Token bucket + hourly cap prevents API bans from high-speed agent requests |
| **Token auto-refresh** | Meta Ads Long-Lived Tokens automatically refreshed before 60-day expiry |
| **Strategy context** | Markdown-based strategy persistence (STRATEGY.md) + JSON campaign state (STATE.json) |
| **Image/video validation** | Path traversal prevention, extension allowlists, size limits on uploads |

## Workflow Commands

Beyond individual MCP tools, mureo provides **10 slash commands** for Claude Code that connect your strategy (`STRATEGY.md`) with the 169 MCP tools to enable strategy-driven ad operations.

### How it works

Commands are **platform-agnostic orchestration instructions**. They do not hardcode which tools to call. Instead, each command tells the AI agent:

1. **Discover platforms** — check STATE.json to see which platforms are configured
2. **Choose tools** — select appropriate MCP tools for each discovered platform
3. **Correlate data sources** — combine ad platform data with Search Console (organic search) and GA4 (on-site behavior) when available
4. **Synthesize insights** — produce unified cross-platform recommendations
5. **Ask before acting** — get user approval for any write operation

This means adding a new platform (e.g., TikTok Ads) requires no command changes. The agent automatically adapts based on what is configured.

Three layers work together:

| Layer | Role | Example (`/creative-refresh`) |
|-------|------|-------------------------------|
| **mureo (MCP tools)** | Data retrieval, analysis, validation | Creative audit, LP analysis, text validation across all platforms |
| **AI agent (LLM)** | Platform discovery, tool selection, creative generation | Detects configured platforms, drafts platform-appropriate creatives from Persona + USP |
| **You (human)** | Final approval | Review and approve before any changes are made |

### Commands

| Command | Purpose | Data sources |
|---------|---------|--------------|
| `/onboard` | Discover platforms, generate STRATEGY.md, initialize STATE.json | All configured |
| `/daily-check` | Cross-platform health monitoring with organic pulse and on-site correlation | Ad platforms + Search Console + GA4 |
| `/rescue` | Emergency performance fix with site-side vs platform-side diagnosis | Ad platforms + GA4 |
| `/search-term-cleanup` | Keyword hygiene with paid/organic overlap analysis | Ad platforms + Search Console + GA4 |
| `/creative-refresh` | Multi-platform creative refresh with organic keyword insights | Ad platforms + Search Console + GA4 |
| `/budget-rebalance` | Cross-platform budget optimization with organic coverage awareness | Ad platforms + Search Console + GA4 |
| `/competitive-scan` | Paid + organic competitive landscape analysis | Ad platforms + Search Console + GA4 |
| `/goal-review` | Multi-source goal progress evaluation | All platforms + all data sources |
| `/weekly-report` | Cross-platform weekly operations report | All platforms + all data sources |
| `/sync-state` | Multi-platform STATE.json synchronization | All configured |

### Getting started

Run `/onboard` first to set up your account and generate STRATEGY.md. Then use `/daily-check` for routine monitoring:

```
# In Claude Code
/onboard          # First time: set up strategy + state
/daily-check      # Routine: check all campaigns
/rescue           # When performance drops
```

### Example: `/creative-refresh` flow

```
You: /creative-refresh

Agent reads STRATEGY.md:
  Persona: "Budget-constrained SaaS marketer"
  USP: "AI reduces ad ops workload by 10h/week"
  Brand Voice: "Data-driven, no hype"
  Data Sources: Google Ads, Meta Ads, Search Console, GA4

Agent discovers configured platforms from STATE.json:
  → Google Ads + Meta Ads

Agent calls tools across platforms and data sources:
  → Creative audit on each ad platform → 3 underperforming assets
  → Landing page analysis → LP highlights: free trial, ROI improvement
  → Search Console top queries → "ad automation" has strong organic clicks
  → GA4 LP engagement → high bounce rate on pricing page

Agent (LLM) generates platform-appropriate copy:
  Google Ads (search): "Cut Ad Ops Time by 60% with AI"  ← Persona pain point
  Google Ads (search): "Free Trial | Ad Automation"       ← LP + organic keyword
  Meta Ads (social):   "Stop drowning in ad reports..."   ← Brand Voice + social format

Agent calls validation tools for each platform.

Agent presents recommendations grouped by platform for approval:
  "I suggest replacing 3 Google Ads headlines and 2 Meta ads. Here's why..."

You approve → Agent calls each platform's update tools.
```

Commands use the strategy context (Operation Mode, Persona, USP, Brand Voice, Market Context) to tailor their behavior. See [skills/mureo-workflows/SKILL.md](skills/mureo-workflows/SKILL.md) for the full Operation Mode reference.

## Quick Start

### Claude Code (recommended)

```bash
pip install mureo
mureo setup claude-code
```

This single command handles everything:
1. Google Ads / Meta Ads authentication (OAuth)
2. MCP server configuration for Claude Code
3. Credential guard (blocks AI agents from reading secrets)
4. 10 workflow commands (`/daily-check`, `/rescue`, etc.)
5. 6 skills (tool references, strategy guide, evidence-based decisions)

After setup, run `/onboard` in Claude Code to get started.

### Cursor

```bash
pip install mureo
mureo setup cursor
```

Cursor supports MCP tools (169 tools) but does not support workflow commands or skills.

### CLI only (authentication management)

```bash
pip install mureo
mureo auth setup
mureo auth status
```

### What gets installed

| Component | `mureo setup claude-code` | `mureo setup cursor` | `mureo auth setup` |
|-----------|:---:|:---:|:---:|
| Authentication (~/.mureo/credentials.json) | Yes | Yes | Yes |
| MCP configuration | Yes | Yes | Yes |
| Credential guard (PreToolUse hook) | Yes | N/A | Yes |
| 10 workflow commands (~/.claude/commands/) | Yes | N/A | No |
| 6 skills (~/.claude/skills/) | Yes | N/A | No |

### Skills reference

| Skill | Purpose |
|-------|---------|
| `mureo-google-ads` | Google Ads tool reference (82 tools, parameters, examples) |
| `mureo-meta-ads` | Meta Ads tool reference (77 tools, parameters, examples) |
| `mureo-shared` | Authentication, security rules, output formatting |
| `mureo-strategy` | STRATEGY.md / STATE.json format and usage guide |
| `mureo-workflows` | Orchestration paradigm, Operation Mode matrix, KPI thresholds, command reference |
| `mureo-learning` | Evidence-based marketing decision framework (observation windows, sample sizes, noise guards) |

### Connecting Additional MCP Servers

mureo works alongside other MCP servers (GA4, CRM tools) in the same client session. Add them to your `.mcp.json` and workflow commands will incorporate their data opportunistically. See [docs/integrations.md](docs/integrations.md) for details.

## Authentication

### Interactive Setup (Recommended)

```bash
mureo auth setup
```

The setup wizard walks you through:

1. **Google Ads** -- Enter Developer Token + Client ID/Secret, open browser for OAuth, select a Google Ads customer account
2. **Meta Ads** -- Enter App ID/Secret, open browser for OAuth, obtain a Long-Lived Token, select an ad account
3. **MCP config** -- Automatically writes `.mcp.json` (project-level) or `~/.claude/settings.json` (global) so Claude Code / Cursor can discover the server

Credentials are saved to `~/.mureo/credentials.json`. Search Console reuses the same Google OAuth2 credentials as Google Ads -- no additional authentication is required.

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

### Tool list (169 tools)

#### Google Ads (82 tools)

<details>
<summary>Click to expand Google Ads tools</summary>

**Campaigns (6)**

| Tool | Description |
|------|-------------|
| `google_ads.campaigns.list` | List campaigns |
| `google_ads.campaigns.get` | Get campaign details |
| `google_ads.campaigns.create` | Create a campaign |
| `google_ads.campaigns.update` | Update campaign settings |
| `google_ads.campaigns.update_status` | Change campaign status (ENABLED/PAUSED/REMOVED) |
| `google_ads.campaigns.diagnose` | Diagnose campaign delivery status |

**Ad Groups (3)**

| Tool | Description |
|------|-------------|
| `google_ads.ad_groups.list` | List ad groups |
| `google_ads.ad_groups.create` | Create an ad group |
| `google_ads.ad_groups.update` | Update an ad group |

**Ads (5)**

| Tool | Description |
|------|-------------|
| `google_ads.ads.list` | List ads |
| `google_ads.ads.create` | Create a responsive search ad (RSA) |
| `google_ads.ads.update` | Update an ad |
| `google_ads.ads.update_status` | Change ad status |
| `google_ads.ads.policy_details` | Get ad policy approval details |

**Keywords (8)**

| Tool | Description |
|------|-------------|
| `google_ads.keywords.list` | List keywords |
| `google_ads.keywords.add` | Add keywords |
| `google_ads.keywords.remove` | Remove a keyword |
| `google_ads.keywords.suggest` | Get keyword suggestions (Keyword Planner) |
| `google_ads.keywords.diagnose` | Diagnose keyword quality scores |
| `google_ads.keywords.pause` | Pause a keyword |
| `google_ads.keywords.audit` | Audit keyword performance and quality |
| `google_ads.keywords.cross_adgroup_duplicates` | Find duplicate keywords across ad groups |

**Negative Keywords (5)**

| Tool | Description |
|------|-------------|
| `google_ads.negative_keywords.list` | List negative keywords |
| `google_ads.negative_keywords.add` | Add negative keywords to a campaign |
| `google_ads.negative_keywords.remove` | Remove a negative keyword |
| `google_ads.negative_keywords.add_to_ad_group` | Add negative keywords to an ad group |
| `google_ads.negative_keywords.suggest` | Suggest negative keywords based on search terms |

**Budget (3)**

| Tool | Description |
|------|-------------|
| `google_ads.budget.get` | Get campaign budget |
| `google_ads.budget.update` | Update budget |
| `google_ads.budget.create` | Create a new campaign budget |

**Accounts (1)**

| Tool | Description |
|------|-------------|
| `google_ads.accounts.list` | List accessible Google Ads accounts |

**Search Terms (2)**

| Tool | Description |
|------|-------------|
| `google_ads.search_terms.report` | Get search terms report |
| `google_ads.search_terms.analyze` | Analyze search terms with intent classification |

**Sitelinks (3)**

| Tool | Description |
|------|-------------|
| `google_ads.sitelinks.list` | List sitelink extensions |
| `google_ads.sitelinks.create` | Create a sitelink extension |
| `google_ads.sitelinks.remove` | Remove a sitelink extension |

**Callouts (3)**

| Tool | Description |
|------|-------------|
| `google_ads.callouts.list` | List callout extensions |
| `google_ads.callouts.create` | Create a callout extension |
| `google_ads.callouts.remove` | Remove a callout extension |

**Conversions (7)**

| Tool | Description |
|------|-------------|
| `google_ads.conversions.list` | List conversion actions |
| `google_ads.conversions.get` | Get conversion action details |
| `google_ads.conversions.performance` | Get conversion performance metrics |
| `google_ads.conversions.create` | Create a conversion action |
| `google_ads.conversions.update` | Update a conversion action |
| `google_ads.conversions.remove` | Remove a conversion action |
| `google_ads.conversions.tag` | Get conversion tracking tag snippet |

**Targeting (11)**

| Tool | Description |
|------|-------------|
| `google_ads.recommendations.list` | List optimization recommendations |
| `google_ads.recommendations.apply` | Apply an optimization recommendation |
| `google_ads.device_targeting.get` | Get device targeting settings |
| `google_ads.device_targeting.set` | Set device targeting bid adjustments |
| `google_ads.bid_adjustments.get` | Get bid adjustment settings |
| `google_ads.bid_adjustments.update` | Update bid adjustments |
| `google_ads.location_targeting.list` | List location targeting criteria |
| `google_ads.location_targeting.update` | Update location targeting |
| `google_ads.schedule_targeting.list` | List ad schedule targeting |
| `google_ads.schedule_targeting.update` | Update ad schedule targeting |
| `google_ads.change_history.list` | List account change history |

**Analysis (13)**

| Tool | Description |
|------|-------------|
| `google_ads.performance.report` | Get performance report |
| `google_ads.performance.analyze` | Analyze performance trends and anomalies |
| `google_ads.cost_increase.investigate` | Investigate sudden cost increases |
| `google_ads.health_check.all` | Run a comprehensive account health check |
| `google_ads.ad_performance.compare` | Compare ad performance across variants |
| `google_ads.ad_performance.report` | Get detailed ad-level performance report |
| `google_ads.network_performance.report` | Get network-level performance breakdown |
| `google_ads.budget.efficiency` | Analyze budget utilization efficiency |
| `google_ads.budget.reallocation` | Suggest budget reallocation across campaigns |
| `google_ads.auction_insights.get` | Get auction insights (competitor analysis) |
| `google_ads.rsa_assets.analyze` | Analyze RSA asset performance |
| `google_ads.rsa_assets.audit` | Audit RSA assets for best practices |
| `google_ads.search_terms.review` | Review search terms and suggest additions/exclusions |

**B2B (1)**

| Tool | Description |
|------|-------------|
| `google_ads.btob.optimizations` | Get B2B-specific optimization suggestions |

**Creative (2)**

| Tool | Description |
|------|-------------|
| `google_ads.landing_page.analyze` | Analyze landing page relevance and quality |
| `google_ads.creative.research` | Research competitive creative strategies |

**Monitoring (4)**

| Tool | Description |
|------|-------------|
| `google_ads.monitoring.delivery_goal` | Monitor campaign delivery against goals |
| `google_ads.monitoring.cpa_goal` | Monitor CPA against target goals |
| `google_ads.monitoring.cv_goal` | Monitor conversion volume against goals |
| `google_ads.monitoring.zero_conversions` | Detect campaigns with zero conversions |

**Capture (1)**

| Tool | Description |
|------|-------------|
| `google_ads.capture.screenshot` | Capture a screenshot of a URL |

**Device (1)**

| Tool | Description |
|------|-------------|
| `google_ads.device.analyze` | Analyze device-level performance |

**CPC (1)**

| Tool | Description |
|------|-------------|
| `google_ads.cpc.detect_trend` | Detect CPC trend (rising/stable/falling) |

**Assets (1)**

| Tool | Description |
|------|-------------|
| `google_ads.assets.upload_image` | Upload an image asset |

</details>

#### Meta Ads (77 tools)

<details>
<summary>Click to expand Meta Ads tools</summary>

**Campaigns (6)**

| Tool | Description |
|------|-------------|
| `meta_ads.campaigns.list` | List campaigns |
| `meta_ads.campaigns.get` | Get campaign details |
| `meta_ads.campaigns.create` | Create a campaign |
| `meta_ads.campaigns.update` | Update a campaign |
| `meta_ads.campaigns.pause` | Pause a campaign |
| `meta_ads.campaigns.enable` | Enable a paused campaign |

**Ad Sets (6)**

| Tool | Description |
|------|-------------|
| `meta_ads.ad_sets.list` | List ad sets |
| `meta_ads.ad_sets.create` | Create an ad set |
| `meta_ads.ad_sets.update` | Update an ad set |
| `meta_ads.ad_sets.get` | Get ad set details |
| `meta_ads.ad_sets.pause` | Pause an ad set |
| `meta_ads.ad_sets.enable` | Enable a paused ad set |

**Ads (6)**

| Tool | Description |
|------|-------------|
| `meta_ads.ads.list` | List ads |
| `meta_ads.ads.create` | Create an ad |
| `meta_ads.ads.update` | Update an ad |
| `meta_ads.ads.get` | Get ad details |
| `meta_ads.ads.pause` | Pause an ad |
| `meta_ads.ads.enable` | Enable a paused ad |

**Creatives (6)**

| Tool | Description |
|------|-------------|
| `meta_ads.creatives.create_carousel` | Create a carousel creative (2-10 cards) |
| `meta_ads.creatives.create_collection` | Create a collection creative |
| `meta_ads.creatives.list` | List ad creatives |
| `meta_ads.creatives.create` | Create a standard ad creative |
| `meta_ads.creatives.create_dynamic` | Create a dynamic product ad creative |
| `meta_ads.creatives.upload_image` | Upload an image for use in creatives |

**Images (1)**

| Tool | Description |
|------|-------------|
| `meta_ads.images.upload_file` | Upload an image from local file |

**Insights (2)**

| Tool | Description |
|------|-------------|
| `meta_ads.insights.report` | Get performance report |
| `meta_ads.insights.breakdown` | Get breakdown report (age, gender, placement, etc.) |

**Audiences (5)**

| Tool | Description |
|------|-------------|
| `meta_ads.audiences.list` | List custom audiences |
| `meta_ads.audiences.create` | Create a custom audience |
| `meta_ads.audiences.get` | Get audience details |
| `meta_ads.audiences.delete` | Delete a custom audience |
| `meta_ads.audiences.create_lookalike` | Create a lookalike audience |

**Conversions API (3)**

| Tool | Description |
|------|-------------|
| `meta_ads.conversions.send` | Send a conversion event (generic) |
| `meta_ads.conversions.send_purchase` | Send a purchase event |
| `meta_ads.conversions.send_lead` | Send a lead event |

**Pixels (4)**

| Tool | Description |
|------|-------------|
| `meta_ads.pixels.list` | List pixels |
| `meta_ads.pixels.get` | Get pixel details |
| `meta_ads.pixels.stats` | Get pixel firing statistics |
| `meta_ads.pixels.events` | List pixel events |

**Analysis (6)**

| Tool | Description |
|------|-------------|
| `meta_ads.analysis.performance` | Analyze overall performance trends |
| `meta_ads.analysis.audience` | Analyze audience performance and overlap |
| `meta_ads.analysis.placements` | Analyze placement performance breakdown |
| `meta_ads.analysis.cost` | Analyze cost trends and efficiency |
| `meta_ads.analysis.compare_ads` | Compare performance across ads |
| `meta_ads.analysis.suggest_creative` | Suggest creative improvements based on data |

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

</details>

#### Search Console (10 tools)

<details>
<summary>Click to expand Search Console tools</summary>

**Sites (2)**

| Tool | Description |
|------|-------------|
| `search_console.sites.list` | List verified sites |
| `search_console.sites.get` | Get site details |

**Analytics (4)**

| Tool | Description |
|------|-------------|
| `search_console.analytics.query` | Query search analytics data |
| `search_console.analytics.top_queries` | Get top search queries |
| `search_console.analytics.top_pages` | Get top pages by clicks/impressions |
| `search_console.analytics.device_breakdown` | Get performance breakdown by device |
| `search_console.analytics.compare_periods` | Compare search performance across time periods |

**Sitemaps (2)**

| Tool | Description |
|------|-------------|
| `search_console.sitemaps.list` | List sitemaps for a site |
| `search_console.sitemaps.submit` | Submit a sitemap |

**URL Inspection (1)**

| Tool | Description |
|------|-------------|
| `search_console.url_inspection.inspect` | Inspect a URL for indexing status |

</details>

## CLI

```bash
mureo setup claude-code    # One-command setup for Claude Code
mureo setup cursor         # Setup for Cursor
mureo auth status          # Check authentication status
mureo auth check-google    # Verify Google Ads credentials
mureo auth check-meta      # Verify Meta Ads credentials
```

## Strategy Context

Two local files drive strategy-aware operations. Run `/onboard` to generate them interactively.

- **STRATEGY.md** -- Persona, USP, Brand Voice, Goals, Operation Mode. See [docs/strategy-context.md](docs/strategy-context.md).
- **STATE.json** -- Campaign snapshots, action log. Updated automatically by workflow commands.

## Architecture

```
mureo/
├── __init__.py              # Package root
├── auth.py                  # Credential loading (~/.mureo/credentials.json + env vars + Meta token auto-refresh)
├── auth_setup.py            # Interactive setup wizard (OAuth + MCP config)
├── throttle.py              # Rate limiting (token bucket + rolling hourly cap)
├── _image_validation.py     # Image file validation utilities
├── google_ads/              # Google Ads API client (google-ads SDK wrapper)
│   ├── client.py            # GoogleAdsApiClient (8 Mixin: Ads, Keywords, Analysis, Creative, Diagnostics, Extensions, Media, Monitoring)
│   ├── mappers.py           # Response mapping to structured dicts
│   └── _*.py                # 8 Mixin modules (ads, keywords, analysis, extensions, diagnostics,
│                            #   creative, monitoring, media) + validators + classifiers
├── meta_ads/                # Meta Ads API client (15 Mixins, httpx-based)
│   ├── client.py            # MetaAdsApiClient (Campaigns, AdSets, Ads, Creatives, Audiences, Pixels,
│   │                        #   Insights, Analysis, Catalog, Conversions, Leads, PagePosts, Instagram,
│   │                        #   SplitTest, AdRules)
│   ├── mappers.py           # Response mapping to structured dicts
│   └── _*.py                # 15 Mixin modules (campaigns, ads, creatives, audiences, etc.)
├── search_console/          # Google Search Console API client (reuses Google OAuth2 credentials)
│   └── client.py            # SearchConsoleApiClient
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
└── mcp/                     # MCP server (169 tools)
    ├── __main__.py                        # python -m mureo.mcp entry point
    ├── server.py                          # MCP server setup (stdio transport)
    ├── _helpers.py                        # Shared handler utilities
    ├── tools_google_ads.py                # 82 Google Ads tool definitions (aggregator)
    ├── _tools_google_ads_*.py             # Tool definition sub-modules
    ├── _handlers_google_ads.py            # Google Ads base handlers
    ├── _handlers_google_ads_extensions.py # Extensions handlers
    ├── _handlers_google_ads_analysis.py   # Analysis handlers
    ├── tools_meta_ads.py                  # 77 Meta Ads tool definitions (aggregator)
    ├── _tools_meta_ads_*.py               # Tool definition sub-modules
    ├── _handlers_meta_ads.py              # Meta Ads base handlers
    ├── _handlers_meta_ads_extended.py     # Extended handlers
    ├── _handlers_meta_ads_other.py        # Other handlers
    ├── tools_search_console.py            # 10 Search Console tool definitions
    └── _handlers_search_console.py        # Search Console handlers
```

**Design principles:**

- **No database** -- all state is either in the ad platform APIs or in local files (`STRATEGY.md`, `STATE.json`).
- **No LLM dependency** -- mureo does not embed an LLM. Inference, planning, and decision-making are the agent's responsibility.
- **Immutable data models** -- all dataclasses use `frozen=True` to prevent accidental mutation.
- **Credentials stay local** -- loaded from `~/.mureo/credentials.json` or environment variables. Never sent anywhere except the official ad platform APIs.

## Development

```bash
git clone https://github.com/logly/mureo.git && cd mureo
pip install -e ".[dev]"
pytest tests/ -v                              # run tests
pytest --cov=mureo --cov-report=term-missing  # with coverage
ruff check mureo/ && black mureo/ && mypy mureo/  # lint & format
```

Python 3.10+ required. See [CONTRIBUTING.md](CONTRIBUTING.md) for full development guidelines.

## License

Apache License 2.0
