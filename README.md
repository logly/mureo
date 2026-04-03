<p align="center">
  <img src="docs/img/logo.png" alt="mureo" width="300">
</p>

<p align="center">
  Marketing orchestration framework for AI agents.
</p>

## What is mureo?

**mureo** is a marketing orchestration framework that helps AI agents achieve real business goals — awareness, leads, sales, retention — not just execute API calls. It combines strategy context, workflow commands, and built-in domain knowledge to guide agents through marketing operations across multiple platforms.

Ad platform APIs will increasingly be exposed through official MCPs from Google, Meta, and others. mureo's value is not in wrapping those APIs. It is in the **orchestration layer on top**: knowing *what* to do, *when* to do it, and *why* — informed by your business strategy.

- **Strategy-driven** -- `STRATEGY.md` defines your persona, USP, brand voice, goals, and operation mode. Every decision the agent makes is grounded in your strategy, not just raw metrics.
- **Workflow commands** -- 10 slash commands (`/daily-check`, `/rescue`, `/creative-refresh`, etc.) guide agents through complete marketing operations, connecting strategy context with the right tools in the right order.
- **Cross-platform** -- orchestrates across Google Ads, Meta Ads, and GA4 (with more platforms planned), enabling coordinated decisions that no single-platform tool can make.
- **Built-in domain knowledge** -- analysis, diagnostics, and optimization logic that turns raw API data into actionable insights. Campaign diagnostics with 30+ reason codes, search term intent analysis, budget efficiency scoring, RSA validation, and more.
- **MCP + CLI interface** -- 159 MCP tools for AI agents (Claude Code, Cursor, etc.) plus a CLI for scripting and quick checks.
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

Beyond individual MCP tools, mureo provides **10 slash commands** for Claude Code that connect your strategy (`STRATEGY.md`) with the 159 MCP tools to enable strategy-driven ad operations.

### How it works

Each command orchestrates three layers working together:

| Layer | Role | Example (`/creative-refresh`) |
|-------|------|-------------------------------|
| **mureo (MCP tools)** | Data retrieval, analysis, validation | RSA asset audit, LP analysis, ad text validation |
| **AI agent (LLM)** | Strategic judgment, creative generation | Drafts new headlines from Persona + USP + Brand Voice |
| **You (human)** | Final approval | Review and approve before any changes are made |

mureo does not embed an LLM. Instead, it provides structured data and clear instructions so that the AI agent (Claude Code, Cursor, etc.) can make informed, strategy-aligned decisions. The commands tell the agent *what tools to use*, *what strategy context to consider*, and *what to ask you before acting*.

### Commands

| Command | What mureo does (tools) | What the AI agent decides (LLM) |
|---------|------------------------|--------------------------------|
| `/onboard` | Fetch accounts, campaigns, init STATE.json | Interview you to build Persona, USP, Brand Voice into STRATEGY.md |
| `/daily-check` | Health check, performance analysis, goal evaluation | Judge which metrics matter based on Operation Mode, generate report |
| `/rescue` | Search term review, cost investigation, zero-CV diagnosis | Prioritize actions, explain why each change is needed |
| `/search-term-cleanup` | N-gram analysis, scoring, exclude candidates | Judge if a search term matches the Persona/USP or not |
| `/creative-refresh` | RSA audit, LP analysis, text validation | Write new headlines/descriptions from Persona + USP + Brand Voice |
| `/budget-rebalance` | Budget efficiency analysis, performance reports | Decide which campaigns deserve more/less budget and why |
| `/competitive-scan` | Auction insights, CPC trend detection | Compare with Market Context, propose strategic response |
| `/sync-state` | Fetch all campaign data, update STATE.json | Summarize changes since last sync in plain language |

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

Agent calls mureo tools:
  → rsa_assets.audit     → 3 headlines rated LOW
  → landing_page.analyze → LP highlights: free trial, ROI improvement
  → search_terms.review  → "ad automation" has high CVR

Agent (LLM) generates new copy:
  "Cut Ad Ops Time by 60% with AI"        ← addresses Persona pain point
  "Free Trial | Ad Automation Platform"    ← matches LP + high-CVR keyword
  "Data-Driven Ad Optimization for Teams"  ← fits Brand Voice

Agent calls mureo validation:
  → RSA validator → character count OK, no prohibited expressions

Agent presents to you for approval:
  "I suggest replacing 3 underperforming headlines. Here's why..."

You approve → Agent calls google_ads.ads.update
```

Commands use the strategy context (Operation Mode, Persona, USP, Brand Voice, Market Context) to tailor their behavior. See [skills/mureo-workflows/SKILL.md](skills/mureo-workflows/SKILL.md) for the full Operation Mode reference.

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

## Installing Commands & Skills

`pip install mureo` installs the Python package (API clients, MCP server, CLI), but **workflow commands and skills are not included** — they are configuration files for Claude Code. To use them, clone the repository and copy them to your environment.

```bash
git clone https://github.com/logly/mureo.git
```

### Workflow commands

Copy to the **user level** so they are available in all projects:

```bash
mkdir -p ~/.claude/commands
cp mureo/.claude/commands/* ~/.claude/commands/
```

After copying, `/onboard`, `/daily-check`, `/rescue`, etc. will appear in any Claude Code session.

### Skills

Skills provide reference knowledge that Claude Code uses to make better decisions. Copy to the **user level**:

```bash
cp -r mureo/skills/* ~/.claude/skills/
```

This installs 5 skills:

| Skill | Purpose |
|-------|---------|
| `mureo-google-ads` | Google Ads tool reference (82 tools, parameters, examples) |
| `mureo-meta-ads` | Meta Ads tool reference (77 tools, parameters, examples) |
| `mureo-shared` | Authentication, security rules, output formatting |
| `mureo-strategy` | STRATEGY.md / STATE.json format and usage guide |
| `mureo-workflows` | Operation Mode matrix, KPI thresholds, command reference |

> **Note:** If you cloned the mureo repository and run Claude Code from that directory, commands and skills are automatically available without copying.

### Connecting Additional MCP Servers

mureo works alongside other MCP servers (GA4, Search Console, CRM tools) in the same client session. Add them to your `.mcp.json` and workflow commands will incorporate their data opportunistically. See [docs/integrations.md](docs/integrations.md) for details.

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

### Tool list (159 tools)

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

A Markdown file containing strategic context: Persona, USP, Target Audience, Brand Voice, Market Context, and Operation Mode. Agents read this before making changes. Run `/onboard` to generate it interactively.

```markdown
# Strategy

## Persona
B2B SaaS decision-makers, 30-50 years old, IT managers and CTOs.

## USP
Only platform that integrates AI agents with ad operations.

## Brand Voice
Professional but approachable. Data-driven recommendations.

## Operation Mode
EFFICIENCY_STABILIZE
```

### STATE.json

A JSON snapshot of current campaign state. Updated automatically when agents read campaigns via tools. Contains campaign IDs, statuses, budgets, bidding strategies, and operational notes.

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
└── mcp/                     # MCP server (159 tools)
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
    └── _handlers_meta_ads_other.py        # Other handlers
```

**Design principles:**

- **No database** -- all state is either in the ad platform APIs or in local files (`STRATEGY.md`, `STATE.json`).
- **No LLM dependency** -- mureo does not embed an LLM. Inference, planning, and decision-making are the agent's responsibility.
- **Immutable data models** -- all dataclasses use `frozen=True` to prevent accidental mutation.
- **Credentials stay local** -- loaded from `~/.mureo/credentials.json` or environment variables. Never sent anywhere except the official ad platform APIs.

## Development

```bash
git clone https://github.com/logly/mureo.git && cd mureo
pip install -e ".[dev,cli,mcp]"
pytest tests/ -v                              # run tests
pytest --cov=mureo --cov-report=term-missing  # with coverage
ruff check mureo/ && black mureo/ && mypy mureo/  # lint & format
```

Python 3.10+ required. See [CONTRIBUTING.md](CONTRIBUTING.md) for full development guidelines.

## License

Apache License 2.0
