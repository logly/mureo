# CONTEXT.md

Instructions for AI agents that **use** mureo as a tool to operate marketing accounts.

## What is mureo?

mureo is a marketing orchestration framework for AI agents. It provides MCP tools, CLI commands,
and workflow commands to manage marketing operations across multiple platforms.
All outputs are structured JSON — designed for machine consumption.

**Supported platforms (built-in):**
- Google Ads (82 MCP tools)
- Meta Ads (77 MCP tools)
- Google Search Console (10 MCP tools)

**Companion data sources (external MCP):**
- GA4 (via Google's official MCP)
- CRM systems (via third-party MCP)

## Security Rules

**Read these before calling any tool.**

1. **Always confirm before writing.** Any tool that creates, updates, or deletes
   an entity (campaigns, ads, keywords, budgets) modifies a live account.
   Confirm the action with the user before calling write tools.

2. **Budget changes require extra caution.** A budget increase takes effect immediately
   and cannot be undone retroactively. Double-check amounts and currency units
   (Google Ads uses micros; Meta Ads uses cents).

3. **Pause before delete.** Prefer pausing campaigns/ads over deleting them.
   Deleted entities cannot be restored.

4. **Validate IDs.** Google Ads `customer_id` is a 10-digit numeric string (no hyphens).
   Meta Ads `account_id` must start with `act_`.

5. **Respect learning periods.** Smart Bidding campaigns have a learning period.
   Avoid changing bidding strategy, target CPA, or budget during learning.

## Platform Discovery

Before executing any workflow, discover which platforms and data sources are available:

1. Read STATE.json `platforms` dict to find configured ad platforms
2. Read STRATEGY.md `Data Sources` section for additional data sources
3. Check tool namespace availability for external MCPs (GA4, CRM)
4. Scope operations to only the configured/available platforms

**Never hardcode platform assumptions.** Iterate over discovered platforms instead.

## Using mureo via MCP

Add to your MCP client configuration:

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

The MCP server exposes 169 tools (82 Google Ads + 77 Meta Ads + 10 Search Console).

### Google Ads Tools (prefix: `google_ads.`)

82 tools covering campaigns, ad groups, ads, keywords, budget, accounts, search terms,
extensions, conversions, targeting, analysis, B2B, creative, monitoring, capture, and assets.

See `skills/mureo-google-ads/SKILL.md` for the full tool reference.

### Meta Ads Tools (prefix: `meta_ads.`)

77 tools covering campaigns, ad sets, ads, insights, analysis, audiences, pixels,
conversions API, creatives, images, catalogs, lead ads, videos, split tests, ad rules,
page posts, and Instagram.

See `skills/mureo-meta-ads/SKILL.md` for the full tool reference.

### Search Console Tools (prefix: `search_console.`)

10 tools covering site management, search analytics, URL inspection, sitemaps, and indexing.

See `docs/integrations.md` (Search Console section) for the full tool reference.

## Setup

```bash
# Claude Code users (recommended — does everything in one command)
mureo setup claude-code

# Cursor users
mureo setup cursor

# Authentication only
mureo auth setup
```

## Using mureo via CLI

```bash
mureo google-ads campaigns-list --customer-id 1234567890
mureo google-ads performance-report --customer-id 1234567890 --days 7
mureo meta-ads campaigns-list --account-id act_123456
mureo meta-ads insights-report --account-id act_123456 --days 7
```

## Output Format

All tools and CLI commands return structured JSON. Example:

```json
{
  "campaigns": [
    {
      "campaign_id": "123456789",
      "campaign_name": "Brand Campaign",
      "status": "ENABLED",
      "bidding_strategy_type": "TARGET_CPA",
      "budget_amount_micros": 50000000
    }
  ]
}
```

## Strategy Context (STRATEGY.md / STATE.json)

mureo uses file-based context instead of a database.

### STRATEGY.md

A Markdown file containing strategic context for the marketing account.
Sections correspond to context types:

```markdown
## Persona
B2B SaaS decision makers, IT managers at mid-size companies.

## USP
Only platform that integrates ad operations with AI agents.

## Target Audience
Companies with 50-500 employees running Google Ads campaigns.

## Brand Voice
Professional but approachable. Data-driven recommendations.

## Market Context
Competitive market with rising CPCs in SaaS vertical.

## Operation Mode
EFFICIENCY_STABILIZE

## Data Sources
- Google Ads: customer_id 1234567890
- Meta Ads: account_id act_123456
- Search Console: example.com
- GA4: available via external MCP

## Goal: CPA < 5,000
- Target: 5000
- Deadline: 2026-06-30
- Current: 5200
- Platform: Google Ads, Meta Ads
- Priority: P0
```

Use `mureo.context.strategy` to parse and write STRATEGY.md programmatically.

### STATE.json

A JSON file tracking campaign state snapshots across platforms:

```json
{
  "version": "2",
  "last_synced_at": "2026-03-29T10:00:00Z",
  "platforms": {
    "google_ads": {
      "customer_id": "1234567890",
      "campaigns": [...]
    },
    "meta_ads": {
      "account_id": "act_123456",
      "campaigns": [...]
    }
  },
  "action_log": [
    {
      "timestamp": "2026-04-01T10:30:00+09:00",
      "action": "Added 15 negative keywords",
      "platform": "google_ads",
      "campaign_id": "12345",
      "command": "/search-term-cleanup",
      "summary": "Excluded informational queries",
      "metrics_at_action": {"cpa": 5200, "conversions": 45, "clicks": 1200},
      "observation_due": "2026-04-15"
    }
  ]
}
```

The `metrics_at_action` and `observation_due` fields enable evidence-based outcome evaluation. See `skills/mureo-learning/SKILL.md` for the decision framework.

Use `mureo.context.state` to parse and write STATE.json programmatically.

## Common Workflows

### 1. Cross-Platform Health Check

```
1. Discover platforms from STATE.json
2. For each platform: run health check / performance analysis
3. If Search Console available: check organic search pulse
4. If GA4 available: correlate on-site behavior
5. Compare metrics across platforms
```

### 2. Search Term & Keyword Hygiene

```
1. For each platform with search term data: review search terms
2. If Search Console available: cross-reference paid vs organic keywords
3. Identify overlap (organic coverage → reduce paid spend)
4. Confirm suggestions with user
5. Execute approved changes on each platform
```

### 3. Multi-Source Diagnosis

```
1. Run platform-specific diagnostics on each configured platform
2. If GA4 available: check if issue is platform-side or site-side
3. If Search Console available: check organic performance context
4. Synthesize cross-platform and cross-source findings
```

### 4. Cross-Platform Reporting

```
1. Gather performance data from all platforms
2. If GA4 available: include website-level metrics
3. If Search Console available: include organic trends
4. Compare efficiency across platforms
5. Present unified Goal progress view
```
