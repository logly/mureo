<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/logo-dark.png">
    <img src="docs/img/logo.png" alt="mureo" width="300">
  </picture>
</p>

<p align="center">
  <a href="README.ja.md">日本語</a>
</p>

## What is mureo?

mureo is a framework for AI agents to autonomously operate ad accounts. Once installed, AI agents (Claude Code, Cursor, etc.) can work across Google Ads, Meta Ads, Search Console, and GA4 -- running campaign diagnostics, search term analysis, budget evaluation, ad validation, and more. Every operation is grounded in your business strategy (`STRATEGY.md`), so the agent makes decisions based on your persona, USP, goals, and brand voice -- not just raw metrics.

mureo also learns. When you correct the agent's analysis or share an operational insight, `/learn` saves it to a persistent knowledge base. That knowledge is automatically loaded in every future session, so the agent gets increasingly attuned to your account's specific patterns and makes better decisions over time.


## Features

### Strategy-driven decisions

Every operation starts from `STRATEGY.md` -- your persona, USP, brand voice, goals, and operation mode. The agent doesn't just optimize metrics; it optimizes toward your business objectives.

```
/creative-refresh reads your Persona and USP before drafting a single headline.
/budget-rebalance checks your Operation Mode before shifting a single dollar.
/rescue cross-references your Goals before recommending what to fix first.
```

### Cross-platform analysis

mureo orchestrates across Google Ads, Meta Ads, Search Console, and GA4 in a single workflow:

- `/daily-check` -- pulls delivery status, ad performance, organic search trends, and site behavior across all platforms, then correlates them into one health report.
- `/search-term-cleanup` -- compares paid keywords against organic rankings to eliminate wasteful overlap.
- `/competitive-scan` -- combines auction insights with organic position data for a complete competitive picture.

The agent auto-discovers your configured platforms. Add Meta Ads later? Every command adapts automatically.

### Built-in marketing expertise

Campaign diagnostics that pinpoint *why* ads aren't delivering -- budget constraints, bidding misconfiguration, policy disapprovals, and more. Search term intent classification. Budget efficiency scoring. RSA ad validation and asset auditing. Landing page analysis. Device-level CPA gap detection. The kind of knowledge experienced ad operators carry in their heads -- built into every workflow.

### Learnable operational know-how

When you correct the agent or share an operational insight, `/learn` saves it to a persistent knowledge base. That knowledge is loaded at the start of every future session, so the agent doesn't repeat the same mistakes and applies what it learned to similar situations across your account.

```
You: "That's not a real CPA spike -- this industry always dips in Golden Week."
Agent: Saved. I'll flag this as seasonal next time.

→ Written to the diagnostic knowledge base.
→ Every future /daily-check and /rescue will factor this in.
```

### Security by design

Marketing accounts are a high-value target. mureo is built with defense-in-depth for AI-driven operations:

- **Credential guard** — `mureo setup claude-code` installs a PreToolUse hook that blocks AI agents from reading `~/.mureo/credentials.json`, `.env`, and similar secrets, so a prompt-injection payload cannot exfiltrate tokens via the file-system tools.
- **GAQL input validation** — every ID, date, date-range constant, and string literal that enters a Google Ads query flows through one whitelist-based surface (`mureo/google_ads/_gaql_validator.py`), and `BETWEEN` clauses pattern-match and revalidate their dates instead of passing raw caller input into GAQL.
- **Anomaly detection** — `mureo/analysis/anomaly_detector.py` compares current campaign metrics against a median-based baseline from the action log and emits prioritized alerts for zero spend, CPA spikes, and CTR drops, with sample-size gates that suppress single-day noise. Exposed to agents via the `analysis.anomalies.check` MCP tool; `state_file` is sandboxed inside the MCP server's CWD so a prompt-injected agent cannot redirect it at an attacker-crafted `STATE.json`.
- **Rollback with allow-list gating** — `mureo/rollback/` turns agent-authored `reversible_params` hints into concrete `RollbackPlan` records. Only operations on an explicit allow-list are planned; destructive verbs (`.delete`, `.remove`, `.transfer`) and unexpected parameter keys are refused, so a compromised agent cannot smuggle a privileged call through the rollback path. `mureo rollback list` / `show` let operators preview plans, and the `rollback.apply` MCP tool executes them by re-dispatching through the same handler used for forward actions so the reversal re-enters the full policy gate (auth, rate limit, validation). Apply requires `confirm=true` (literal boolean), refuses `rollback.*` self-recursion, records the reversal as an append-only `action_log` entry tagged with `rollback_of=<index>`, and refuses a second apply of the same index.
- **Immutable data models** — every state object (`StateDocument`, `ActionLogEntry`, `CampaignSnapshot`, `Anomaly`, `RollbackPlan`) is a `frozen=True` dataclass; an agent cannot silently mutate its own record of what happened.
- **Local-only credentials** — tokens are loaded from `~/.mureo/credentials.json` or environment variables and transmitted only to the official ad-platform APIs. mureo itself has no telemetry.

See [SECURITY.md](SECURITY.md) for the full threat model and vulnerability reporting process.

<details>
<summary>Full capability list</summary>

| Area | Capabilities |
|------|-------------|
| **Diagnostics** | Automatic root cause identification for delivery issues (budget, bidding, policy, structure), learning period detection, smart bidding classification, zero-conversion analysis |
| **Performance** | Period-over-period comparison, cost spike investigation, cross-campaign health checks, CPA/CV goal tracking |
| **Search terms** | N-gram distribution, intent pattern detection, add/exclude candidate scoring, paid vs organic overlap analysis |
| **Creative** | RSA validation (prohibited expressions, character width, ad strength prediction), asset-level performance audit, LP analysis, message match scoring |
| **Budget** | Cross-campaign allocation analysis, reallocation recommendations, efficiency scoring |
| **Competitive** | Auction insights, impression share trends, organic position correlation |
| **Meta Ads** | Placement analysis (Facebook/Instagram/Audience Network), cost investigation, A/B comparison, creative suggestions |
| **Monitoring** | Delivery goal evaluation, CPA/CV goal tracking, device analysis, B2B-specific checks |

</details>

## Workflow Commands

| Command | What it does |
|---------|-------------|
| `/onboard` | Discover your platforms, generate STRATEGY.md, initialize STATE.json |
| `/daily-check` | Cross-platform health monitoring + organic pulse + site behavior correlation |
| `/rescue` | Emergency performance fix: platform-side vs site-side root cause diagnosis |
| `/search-term-cleanup` | Keyword hygiene with paid/organic overlap elimination |
| `/creative-refresh` | Multi-platform ad copy refresh using your Persona, USP, and organic keyword data |
| `/budget-rebalance` | Cross-platform budget optimization informed by organic coverage |
| `/competitive-scan` | Paid + organic competitive landscape analysis |
| `/goal-review` | Multi-source goal progress evaluation with operation mode recommendations |
| `/weekly-report` | Cross-platform weekly operations summary |
| `/sync-state` | Refresh STATE.json from live platform data |
| `/learn` | Save a diagnostic insight to the knowledge base for future sessions |

### Getting started

```
pip install mureo
mureo setup claude-code

# Then in Claude Code:
/onboard          # First time: set up strategy + state
/daily-check      # Daily: check all campaigns
/rescue           # When performance drops
```

### Example: `/creative-refresh` in action

```
You: /creative-refresh

Agent reads STRATEGY.md:
  Persona: "Budget-constrained SaaS marketer"
  USP: "AI reduces ad ops workload by 10h/week"
  Brand Voice: "Data-driven, no hype"

Agent discovers platforms from STATE.json:
  → Google Ads + Meta Ads configured

Agent pulls data across platforms and data sources:
  → Creative audit         → 3 underperforming Google Ads assets
  → Landing page analysis  → LP highlights: free trial, ROI improvement
  → Search Console         → "ad automation" has strong organic clicks
  → GA4                    → high bounce rate on pricing page

Agent generates platform-appropriate copy from your strategy:
  Google Ads: "Cut Ad Ops Time by 60% with AI"  ← Persona pain point
  Google Ads: "Free Trial | Ad Automation"       ← LP + organic keyword
  Meta Ads:   "Stop drowning in ad reports..."   ← Brand Voice + social format

Agent validates, then asks for approval:
  "I suggest replacing 3 Google Ads headlines and 2 Meta ads. Here's why..."

You approve → Agent updates each platform.
```

### Analysis & domain knowledge (built-in)

<details>
<summary>Click to expand full capability list</summary>

**Campaign Diagnostics & Performance**

| Capability | Description |
|------------|-------------|
| Campaign diagnostics | Automatic root cause identification for delivery issues, learning period detection, smart bidding classification |
| Performance analysis | Period-over-period comparison, cost increase investigation, cross-campaign health checks |
| Search term analysis | N-gram distribution, intent pattern detection, automated add/exclude candidate scoring |
| Budget efficiency | Cross-campaign budget allocation analysis, reallocation recommendations |
| Device analysis | CPA gap detection, zero-conversion device identification |
| Auction insights | Competitive landscape analysis, impression share trends |
| B2B optimization | Industry-specific campaign checks and recommendations |

**Creative & Landing Page**

| Capability | Description |
|------------|-------------|
| RSA ad validation | Prohibited expression detection, character width calculation, auto-correction, ad strength prediction |
| RSA asset audit | Asset-level performance analysis, replacement/addition recommendations |
| Landing page analysis | HTML parsing with SSRF protection, CTA/feature/price detection, industry estimation |
| Creative research | Aggregates LP + existing ads + search terms + keyword suggestions into a unified research package |
| Message match evaluation | Ad copy <-> landing page alignment scoring (screenshot capture via Playwright) |

**Monitoring & Goals**

| Capability | Description |
|------------|-------------|
| Delivery goal evaluation | Campaign status + diagnostics + performance -> critical/warning/healthy classification |
| CPA goal tracking | Actual vs target CPA with trend analysis |
| CV goal tracking | Daily conversion volume monitoring against targets |
| Zero-conversion diagnosis | Root cause analysis for campaigns with no conversions |

**Meta Ads Analysis**

| Capability | Description |
|------------|-------------|
| Placement analysis | Performance breakdown by Facebook, Instagram, Audience Network |
| Cost investigation | CPA degradation root cause analysis |
| Ad comparison | A/B performance comparison within ad sets |
| Creative suggestions | Data-driven creative improvement recommendations |

</details>

## Quick Start

### Prerequisites

- **Google Ads** -- [Developer Token](https://developers.google.com/google-ads/api/docs/get-started/dev-token) and OAuth Client ID / Client Secret
- **Meta Ads** -- Create an app on [Meta for Developers](https://developers.facebook.com/) to obtain an App ID / App Secret (development mode is fine)

The `mureo auth setup` wizard walks you through both.

### Claude Code (recommended)

```bash
pip install mureo
mureo setup claude-code
```

This single command handles everything:
1. Google Ads / Meta Ads authentication (OAuth)
2. MCP server configuration for Claude Code
3. Credential guard (blocks AI agents from reading secrets)
4. Workflow commands (`/daily-check`, `/rescue`, `/learn`, etc.)
5. Skills (tool references, strategy guide, evidence-based decisions, diagnostic knowledge)

After setup, run `/onboard` in Claude Code to get started.

### Cursor

```bash
pip install mureo
mureo setup cursor
```

Cursor supports MCP tools but does not support workflow commands or skills.

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
| Workflow commands (~/.claude/commands/) | Yes | N/A | No |
| Skills (~/.claude/skills/) | Yes | N/A | No |

### Skills reference

| Skill | Purpose |
|-------|---------|
| `mureo-google-ads` | Google Ads tool reference (parameters, examples) |
| `mureo-meta-ads` | Meta Ads tool reference (parameters, examples) |
| `mureo-shared` | Authentication, security rules, output formatting |
| `mureo-strategy` | STRATEGY.md / STATE.json format and usage guide |
| `mureo-workflows` | Orchestration paradigm, Operation Mode matrix, KPI thresholds, command reference |
| `mureo-learning` | Evidence-based marketing decision framework (observation windows, sample sizes, noise guards) |
| `mureo-pro-diagnosis` | Learnable diagnostic knowledge base (grows with use via `/learn`) |

### Connecting GA4 (Google Analytics 4)

mureo's workflow commands can leverage GA4 data (conversion rates, user behavior, landing page performance) when a GA4 MCP server is configured alongside mureo. GA4 data is optional — all commands work without it.

Setup using [Google Analytics MCP](https://github.com/googleanalytics/google-analytics-mcp):

1. Enable the required APIs in your GCP project:
   - [Google Analytics Admin API](https://console.cloud.google.com/apis/library/analyticsadmin.googleapis.com) -- click "Enable"
   - [Google Analytics Data API](https://console.cloud.google.com/apis/library/analyticsdata.googleapis.com) -- click "Enable"

2. Install and authenticate:

   ```bash
   pipx install analytics-mcp

   gcloud auth application-default login \
     --scopes https://www.googleapis.com/auth/analytics.readonly,https://www.googleapis.com/auth/cloud-platform
   ```

3. Add to `~/.claude/settings.json` alongside mureo:

   ```json
   {
     "mcpServers": {
       "mureo": {
         "command": "python",
         "args": ["-m", "mureo.mcp"]
       },
       "analytics-mcp": {
         "command": "pipx",
         "args": ["run", "analytics-mcp"],
         "env": {
           "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/application_default_credentials.json",
           "GOOGLE_PROJECT_ID": "your-gcp-project-id"
         }
       }
     }
   }
   ```

### Connecting Other MCP Servers

mureo works alongside any MCP server in the same client session. Add them to your settings and workflow commands will incorporate their data when available. See [docs/integrations.md](docs/integrations.md) for details.

## Authentication

### Interactive Setup (Recommended)

```bash
mureo auth setup
```

The setup wizard walks you through:

1. **Google Ads** -- Enter Developer Token + Client ID/Secret, open browser for OAuth, select a Google Ads customer account
2. **Meta Ads** -- Enter App ID/Secret, open browser for OAuth, obtain a Long-Lived Token, select an ad account. Your Meta App can stay in **Development Mode** -- no App Review is needed since mureo operates your own ad account. You may see a permission warning for `business_management` during OAuth; this is safe to accept and required for accessing pages managed through Business Portfolio.
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

### Tool list

#### Google Ads

<details>
<summary>Click to expand Google Ads tools</summary>

**Campaigns**

| Tool | Description |
|------|-------------|
| `google_ads.campaigns.list` | List campaigns |
| `google_ads.campaigns.get` | Get campaign details |
| `google_ads.campaigns.create` | Create a campaign (search or display, via `channel_type`) |
| `google_ads.campaigns.update` | Update campaign settings |
| `google_ads.campaigns.update_status` | Change campaign status (ENABLED/PAUSED/REMOVED) |
| `google_ads.campaigns.diagnose` | Diagnose campaign delivery status |

**Ad Groups**

| Tool | Description |
|------|-------------|
| `google_ads.ad_groups.list` | List ad groups |
| `google_ads.ad_groups.create` | Create an ad group |
| `google_ads.ad_groups.update` | Update an ad group |

**Ads**

| Tool | Description |
|------|-------------|
| `google_ads.ads.list` | List ads |
| `google_ads.ads.create` | Create a responsive search ad (RSA) |
| `google_ads.ads.create_display` | Create a responsive display ad (RDA); image files are uploaded automatically |
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

#### Meta Ads

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

#### Search Console

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

#### Rollback

<details>
<summary>Click to expand rollback tools</summary>

Cross-platform tools that inspect and apply the reversal plan for a previously-recorded `action_log` entry. Apply re-dispatches through the same MCP handler used for forward actions, so the reversal re-enters the full policy gate (auth, rate limit, input validation, allow-list).

| Tool | Description |
|------|-------------|
| `rollback.plan.get` | Inspect the reversal plan for an `action_log` entry (`supported` / `partial` / `not_supported`), its `operation` + `params`, and any caveats. Read-only; does not execute. |
| `rollback.apply` | Execute the reversal plan for `action_log[index]`. Requires `confirm=true` as a literal boolean. Appends a new log entry tagged `rollback_of=<index>`; a second apply of the same index is refused. `state_file` is resolved strictly inside the MCP server's CWD — path traversal, symlink escape, and `rollback.*` self-recursion are all refused. |

</details>

#### Analysis

<details>
<summary>Click to expand analysis tools</summary>

Cross-platform detection tools that operate on STATE.json's `action_log` history rather than on platform APIs directly.

| Tool | Description |
|------|-------------|
| `analysis.anomalies.check` | Compare a campaign's current metrics against a median-based baseline built from `action_log` history. Returns severity-ordered anomalies — zero spend (CRITICAL), CPA spike (HIGH/CRITICAL, gated by 30+ conversions), CTR drop (HIGH/CRITICAL, gated by 1000+ impressions). Sample-size gates follow the `mureo-learning` skill's statistical-thinking rules. Returns `baseline=null` when history is shorter than `min_baseline_entries` (default 7); `baseline_warning` surfaces a parseable-but-corrupt `STATE.json` without silencing live zero-spend detection. |

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
├── cli/                     # Typer CLI (setup + auth only)
│   ├── main.py              # Entry point (mureo command)
│   ├── setup_cmd.py         # mureo setup claude-code / cursor
│   └── auth_cmd.py          # mureo auth setup / status / check-*
└── mcp/                     # MCP server
    ├── __main__.py                        # python -m mureo.mcp entry point
    ├── server.py                          # MCP server setup (stdio transport)
    ├── _helpers.py                        # Shared handler utilities
    ├── tools_google_ads.py                # Google Ads tool definitions (aggregator)
    ├── _tools_google_ads_*.py             # Tool definition sub-modules
    ├── _handlers_google_ads.py            # Google Ads base handlers
    ├── _handlers_google_ads_extensions.py # Extensions handlers
    ├── _handlers_google_ads_analysis.py   # Analysis handlers
    ├── tools_meta_ads.py                  # Meta Ads tool definitions (aggregator)
    ├── _tools_meta_ads_*.py               # Tool definition sub-modules
    ├── _handlers_meta_ads.py              # Meta Ads base handlers
    ├── _handlers_meta_ads_extended.py     # Extended handlers
    ├── _handlers_meta_ads_other.py        # Other handlers
    ├── tools_search_console.py            # Search Console tool definitions
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
