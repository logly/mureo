# CONTEXT.md

Instructions for AI agents that **use** mureo as a tool to operate ad accounts.

## What is mureo?

mureo is an ad operations toolkit for AI agents. It provides CLI commands and MCP tools
to manage Google Ads and Meta Ads accounts. All outputs are structured JSON — designed
for machine consumption.

## Security Rules

**Read these before calling any tool.**

1. **Always confirm before writing.** Any tool that creates, updates, or deletes
   an entity (campaigns, ads, keywords, budgets) modifies a live ad account.
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

The MCP server exposes 42 tools (28 Google Ads + 14 Meta Ads).

### Google Ads Tools (prefix: `google_ads.`)

| Tool | Description |
|------|-------------|
| `campaigns.list` | List campaigns (optional status filter) |
| `campaigns.get` | Get campaign details |
| `campaigns.create` | Create a campaign |
| `campaigns.update` | Update campaign settings |
| `campaigns.update_status` | Change campaign status (ENABLED/PAUSED/REMOVED) |
| `campaigns.diagnose` | Diagnose campaign delivery issues |
| `ad_groups.list` | List ad groups (optional campaign filter) |
| `ad_groups.create` | Create an ad group |
| `ad_groups.update` | Update ad group settings |
| `ads.list` | List ads (optional ad group filter) |
| `ads.create` | Create a responsive search ad (RSA) |
| `ads.update` | Update ad headlines/descriptions |
| `ads.update_status` | Change ad status |
| `keywords.list` | List keywords |
| `keywords.add` | Add keywords to an ad group |
| `keywords.remove` | Remove a keyword |
| `keywords.suggest` | Get keyword suggestions (Keyword Planner) |
| `keywords.diagnose` | Diagnose keyword quality scores |
| `negative_keywords.list` | List negative keywords |
| `negative_keywords.add` | Add negative keywords |
| `budget.get` | Get campaign budget |
| `budget.update` | Update daily budget |
| `performance.report` | Get performance report |
| `search_terms.report` | Get search terms report |
| `search_terms.review` | Review search terms with add/exclude suggestions |
| `auction_insights.analyze` | Analyze auction insights (competitor analysis) |
| `cpc.detect_trend` | Detect CPC trend direction (rising/stable/falling) |
| `device.analyze` | Analyze device-level performance (PC/mobile/tablet) |

### Meta Ads Tools (prefix: `meta_ads.`)

| Tool | Description |
|------|-------------|
| `campaigns.list` | List campaigns |
| `campaigns.get` | Get campaign details |
| `campaigns.create` | Create a campaign |
| `campaigns.update` | Update a campaign |
| `ad_sets.list` | List ad sets |
| `ad_sets.create` | Create an ad set |
| `ad_sets.update` | Update an ad set |
| `ads.list` | List ads |
| `ads.create` | Create an ad |
| `ads.update` | Update an ad |
| `insights.report` | Get performance report |
| `insights.breakdown` | Get breakdown report (age, gender, etc.) |
| `audiences.list` | List custom audiences |
| `audiences.create` | Create a custom audience |

## Using mureo via CLI

```bash
# Authentication setup (interactive wizard)
mureo auth setup

# Google Ads examples
mureo google-ads campaigns-list --customer-id 1234567890
mureo google-ads campaigns-get --customer-id 1234567890 --campaign-id 111
mureo google-ads performance-report --customer-id 1234567890 --days 7
mureo google-ads search-terms-report --customer-id 1234567890 --campaign-id 111
mureo google-ads keywords-list --customer-id 1234567890

# Meta Ads examples
mureo meta-ads campaigns-list --account-id act_123456
mureo meta-ads campaigns-get --account-id act_123456 --campaign-id 222
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

A Markdown file containing strategic context for the ad account.
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
```

Use `mureo.context.strategy` to parse and write STRATEGY.md programmatically.

### STATE.json

A JSON file tracking campaign state snapshots:

```json
{
  "version": "1",
  "customer_id": "1234567890",
  "last_synced_at": "2026-03-29T10:00:00Z",
  "campaigns": [
    {
      "campaign_id": "111",
      "campaign_name": "Brand Campaign",
      "status": "ENABLED",
      "bidding_strategy_type": "TARGET_CPA",
      "target_cpa_micros": 5000000
    }
  ]
}
```

Use `mureo.context.state` to parse and write STATE.json programmatically.

## Common Workflows

### 1. Daily Performance Check

```
1. google_ads.performance.report (period: LAST_7_DAYS)
2. Review CPA, CTR, conversions trends
3. google_ads.device.analyze (if CPA variance suspected)
4. google_ads.cpc.detect_trend (if CPC rising)
```

### 2. Keyword Management

```
1. google_ads.search_terms.report (last 7 days)
2. google_ads.search_terms.review (get add/exclude suggestions)
3. Confirm suggestions with user
4. google_ads.keywords.add (for good search terms)
5. google_ads.negative_keywords.add (for irrelevant terms)
```

### 3. Campaign Diagnosis

```
1. google_ads.campaigns.diagnose (overall health check)
2. google_ads.keywords.diagnose (quality score review)
3. google_ads.auction_insights.analyze (competitor landscape)
```

### 4. Meta Ads Performance Review

```
1. meta_ads.insights.report (period: last_7d)
2. meta_ads.insights.breakdown (by age, gender)
3. Review audience performance
```
