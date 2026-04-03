# External Tool Integration Guide

mureo's core value is orchestration -- knowing *what* to do, *when*, and *why* across multiple marketing platforms. For analytics, SEO, and CRM data that mureo does not cover directly, you can connect third-party MCP servers alongside mureo in the same client. This guide explains how.

## How It Works

MCP clients (Claude Code, Cursor, Claude Desktop) can connect to multiple MCP servers simultaneously. Each server exposes its own set of tools. When mureo's workflow commands run, the AI agent can call tools from any connected MCP server in the same session. This means a `/daily-check` can pull Google Ads data via mureo *and* conversion data from a GA4 MCP, combining both into a single analysis.

**Key principle**: mureo workflow commands check for external tool availability opportunistically. If a GA4 MCP is configured and responds, the agent uses that data to enrich its analysis. If not, the command proceeds normally with mureo's own data. There is no hard dependency on any external MCP server.

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
| `/daily-check` | LP conversion rates, bounce rates, session quality metrics for richer health assessment |
| `/creative-refresh` | Landing page engagement data (time on page, scroll depth) to inform ad copy decisions |
| `/goal-review` | Traffic source attribution, user behavior flows, assisted conversions for goal progress |
| `/budget-rebalance` | E-commerce metrics (revenue, ROAS by channel) and cross-channel attribution for budget decisions |
| `/competitive-scan` | Organic vs paid traffic mix to understand full competitive landscape |

### Authentication

GA4 MCP servers typically require Google Cloud service account credentials or OAuth tokens. Refer to the GA4 MCP documentation for setup instructions. These credentials are separate from mureo's Google Ads credentials.

## Google Search Console

### Status: Not yet available as MCP

No official or widely-adopted MCP server exists for Google Search Console at the time of writing.

### What It Would Add

- **Organic vs paid keyword overlap** -- identify keywords where you rank organically and can reduce paid spend
- **SEO/SEM coordination** -- adjust bidding strategy based on organic ranking changes
- **Search appearance data** -- understand how your pages appear in organic results alongside paid ads

### When Available

Once a Search Console MCP becomes available, add it to `.mcp.json` alongside mureo and GA4. The `/search-term-cleanup` and `/competitive-scan` commands would benefit most from this data.

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
