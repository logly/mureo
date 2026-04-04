# External Tool Integration Guide

mureo's core value is orchestration — knowing *what* to do, *when*, and *why* across multiple marketing platforms. mureo includes built-in integrations for Google Ads (82 tools), Meta Ads (77 tools), and Google Search Console (10 tools). For analytics and CRM data that mureo does not cover directly, you can connect third-party MCP servers alongside mureo in the same client. This guide explains how.

## How It Works

MCP clients (Claude Code, Cursor, Claude Desktop) can connect to multiple MCP servers simultaneously. Each server exposes its own set of tools. When mureo's workflow commands run, the AI agent **discovers all configured platforms at runtime** and adapts its behavior accordingly — calling tools from any connected MCP server in the same session.

### Platform Discovery

Every mureo workflow command follows this pattern:

1. Read STATE.json `platforms` dict to find configured ad platforms
2. Check for built-in data sources (Search Console credentials)
3. Probe for external MCP availability (GA4, CRM) by checking tool namespaces
4. Execute operations across all discovered platforms — no hardcoded assumptions

**Key principle**: No mureo command requires any specific platform. Commands adapt to whatever is configured. At minimum, one ad platform is needed. All additional data sources (Search Console, GA4, CRM) are additive, never blocking.

## GA4 (Google Analytics 4)

### Status: Community MCP available

A community-maintained GA4 MCP server exists at https://github.com/nicholasf/ga4-mcp. Google may release an official MCP in the future.

> **Note**: The exact package name and installation method may change. Check the repository or official Google documentation for the latest instructions before configuring.

### Configuration

Add both mureo and the GA4 MCP to your `.mcp.json` (project-level) or `~/.claude/settings.json` (global):

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    },
    "ga4": {
      "command": "npx",
      "args": ["@anthropic-ai/ga4-mcp"]
    }
  }
}
```

> **Important**: The `@anthropic-ai/ga4-mcp` package name above is a placeholder. Check the official GA4 MCP documentation for the correct package name and any required environment variables (e.g., service account credentials, property ID).

### What GA4 Data Adds to mureo Workflows

| mureo Command | GA4 Data Value |
|---------------|----------------|
| `/daily-check` | LP conversion rates, bounce rates, session quality — correlate with ad performance |
| `/search-term-cleanup` | LP bounce rates for keyword quality signals |
| `/creative-refresh` | LP engagement metrics (time on page, scroll depth) to inform creative direction |
| `/goal-review` | Website conversion data for holistic goal tracking |
| `/budget-rebalance` | Conversion quality by traffic source to inform allocation decisions |
| `/competitive-scan` | Brand/direct traffic trends — competitor mind share signals |
| `/rescue` | Site-side vs platform-side diagnosis before making ad changes |
| `/weekly-report` | Website-level metrics for holistic cross-platform reporting |
| `/onboard` | Site conversion metric baseline |
| `/sync-state` | Connectivity verification |

### Authentication

GA4 MCP servers typically require Google Cloud service account credentials or OAuth tokens. Refer to the GA4 MCP documentation for setup instructions. These credentials are separate from mureo's Google Ads credentials.

## Google Search Console

### Status: Built into mureo

Search Console is built into mureo as a first-party integration (10 MCP tools). It reuses the same Google OAuth2 credentials as Google Ads -- no additional authentication or configuration is required.

### What It Provides

- **Organic vs paid keyword overlap** -- identify keywords where you rank organically and can reduce paid spend
- **SEO/SEM coordination** -- adjust bidding strategy based on organic ranking changes
- **Search appearance data** -- understand how your pages appear in organic results alongside paid ads
- **Indexing status** -- inspect URLs for indexing issues via the URL Inspection API
- **Sitemap management** -- list and submit sitemaps

### Tools

| Tool | Description |
|------|-------------|
| `search_console.sites.list` | List verified sites |
| `search_console.sites.get` | Get site details |
| `search_console.analytics.query` | Query search analytics data |
| `search_console.analytics.top_queries` | Get top search queries |
| `search_console.analytics.top_pages` | Get top pages by clicks/impressions |
| `search_console.analytics.device_breakdown` | Get performance breakdown by device |
| `search_console.analytics.compare_periods` | Compare search performance across time periods |
| `search_console.sitemaps.list` | List sitemaps for a site |
| `search_console.sitemaps.submit` | Submit a sitemap |
| `search_console.url_inspection.inspect` | Inspect a URL for indexing status |

### Workflow Integration

All 10 mureo workflow commands can leverage Search Console data. Key use cases:

| Command | Search Console Value |
|---------|---------------------|
| `/daily-check` | Organic ranking drops needing paid coverage |
| `/search-term-cleanup` | Paid/organic keyword overlap matrix — reduce paid spend on strong organic terms |
| `/competitive-scan` | Organic competitive landscape alongside paid auction insights |
| `/creative-refresh` | Top organic queries as ad copy inspiration |
| `/budget-rebalance` | Organic coverage data to inform paid budget allocation |
| `/rescue` | Identify terms better served by organic instead of paid |
| `/goal-review` | Organic metrics for SEO-related goals |
| `/weekly-report` | Organic trend summary (WoW changes) |
| `/onboard` | Organic baseline establishment |
| `/sync-state` | Site access verification |

## CRM / Marketing Automation (HubSpot, Salesforce)

### Status: Community MCPs available

Community-maintained MCP servers exist for HubSpot and Salesforce. Quality and completeness vary.

### What They Would Add

- **Lead quality tracking** -- connect ad campaigns to downstream lead quality (MQL/SQL rates)
- **LTV data** -- inform `/goal-review` and `/budget-rebalance` with actual customer lifetime value
- **Pipeline attribution** -- map ad spend to revenue pipeline for B2B accounts
- **Audience sync** -- verify that ad targeting audiences match CRM segments

### Configuration Example

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    },
    "hubspot": {
      "command": "npx",
      "args": ["@hubspot/mcp-server"],
      "env": {
        "HUBSPOT_ACCESS_TOKEN": "your-token-here"
      }
    }
  }
}
```

> **Note**: The HubSpot package name above is a placeholder. Check the official HubSpot or community MCP documentation for the correct package name and configuration.

## Future Platforms

The following platforms are planned for integration as their official or community MCP servers mature:

| Platform | Status | Expected Value |
|----------|--------|----------------|
| TikTok Ads | Planned | Cross-platform creative performance, younger demographic insights |
| LinkedIn Ads | Planned | B2B audience targeting coordination, ABM campaign alignment |
| Amazon Ads | Planned | E-commerce ad spend coordination, product-level ROAS |
| Microsoft Ads | Planned | Search campaign coordination alongside Google Ads |

**Pattern**: As official MCPs become available from these platforms, add them to your `.mcp.json` alongside mureo. mureo's workflow commands will incorporate the additional data opportunistically -- no code changes required.

## Best Practices

### Start with mureo alone

You do not need any external MCP to use mureo effectively. The workflow commands work fully with Google Ads and Meta Ads data alone. Add external MCPs only when you need the additional data.

### One server per platform

Each MCP server should cover one platform. Do not try to combine multiple platforms into a single custom MCP server. The MCP protocol is designed for multiple specialized servers working together.

### Credential isolation

Each MCP server manages its own credentials independently. mureo credentials (`~/.mureo/credentials.json`) are never shared with other MCP servers.

### Validate before trusting

When an external MCP returns data, the AI agent should cross-reference it with mureo's own data where possible. For example, compare GA4 conversion counts with Google Ads conversion counts to identify tracking discrepancies.
