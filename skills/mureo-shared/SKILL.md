---
name: mureo-shared
description: "mureo: Shared patterns for authentication, security rules, and output formatting."
metadata:
  version: 0.2.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
      python: ">=3.10"
    cliHelp: "mureo --help"
---

# mureo Shared Patterns
> This file covers authentication, security rules, output formatting, and MCP configuration
> shared across all mureo skills (Google Ads, Meta Ads, Strategy).

## Overview

**mureo** is a marketing orchestration framework for AI agents. It provides:
- **CLI** (`mureo`) for direct command-line usage
- **MCP Server** for integration with AI agent hosts (Claude Code, Cursor, etc.)
- **Python library** for programmatic access

All three interfaces share the same authentication, security rules, and output format.

## Installation

```bash
# Core library
pip install mureo

# With CLI support
pip install "mureo[cli]"

# With MCP server support
pip install "mureo[mcp]"

# Everything
pip install "mureo[cli,mcp]"
```

## Authentication Setup

### Interactive Setup (Recommended)

```bash
mureo auth setup
```

This launches a wizard that:
1. Asks which platforms to configure (Google Ads / Meta Ads)
2. Collects API credentials
3. Opens a browser for OAuth authorization
4. Lists accessible accounts for selection
5. Saves credentials to `~/.mureo/credentials.json`

### Manual Configuration

Create `~/.mureo/credentials.json`:

```json
{
  "google_ads": {
    "developer_token": "YOUR_DEVELOPER_TOKEN",
    "client_id": "YOUR_OAUTH_CLIENT_ID",
    "client_secret": "YOUR_OAUTH_CLIENT_SECRET",
    "refresh_token": "YOUR_REFRESH_TOKEN",
    "login_customer_id": "1234567890"
  },
  "meta_ads": {
    "access_token": "YOUR_LONG_LIVED_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET",
    "account_id": "act_XXXXXXXXXXXX"
  }
}
```

### Environment Variable Fallback

If `~/.mureo/credentials.json` is not found, mureo reads from environment variables:

| Platform | Variable | Required |
|----------|----------|----------|
| Google Ads | `GOOGLE_ADS_DEVELOPER_TOKEN` | Yes |
| Google Ads | `GOOGLE_ADS_CLIENT_ID` | Yes |
| Google Ads | `GOOGLE_ADS_CLIENT_SECRET` | Yes |
| Google Ads | `GOOGLE_ADS_REFRESH_TOKEN` | Yes |
| Google Ads | `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | No |
| Meta Ads | `META_ADS_ACCESS_TOKEN` | Yes |
| Meta Ads | `META_ADS_APP_ID` | No |
| Meta Ads | `META_ADS_APP_SECRET` | No |

### Verify Authentication

```bash
# Show auth status for all platforms
mureo auth status

# Check Google Ads credentials (masked output)
mureo auth check-google

# Check Meta Ads credentials (masked output)
mureo auth check-meta
```

## MCP Server Configuration

### Claude Code / Cursor

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

The MCP server exposes **42 tools** (28 Google Ads + 14 Meta Ads) over stdio.

### Verify MCP Connection

Once configured, the AI agent can call `google_ads.campaigns.list` or `meta_ads.campaigns.list` to verify the connection is working.

## Security Rules

> CRITICAL: AI agents MUST follow these rules when using mureo tools.

### 1. Confirm Before Write Operations

**Always confirm with the user** before executing any write operation:
- `create` (campaigns, ad groups, ads, keywords, audiences)
- `update` (settings, status, budgets, bids)
- `update_status` (enable, pause, remove)
- `add` / `remove` (keywords, negative keywords)

Example agent behavior:
```
User: "Pause campaign 123456"
Agent: "I'll pause campaign 123456 (Brand Search - Tokyo).
        Current status: ENABLED, 12 active ads, daily budget 5,000.
        Proceed? [y/n]"
```

### 2. Budget Changes Require Current Value Display

Before updating any budget, **always retrieve and display the current budget** first:
1. Call `google_ads.budget.get` or read campaign details
2. Show the user: current amount, new amount, and percentage change
3. Warn if the change exceeds 20% (significant impact on delivery)

### 3. Bulk Pause/Remove with Extra Caution

When pausing or removing multiple entities:
- List all affected entities with their current performance
- Show total impact (e.g., "This will pause 5 campaigns with 1,200 clicks/day")
- Require explicit confirmation

### 4. Never Expose Raw Credentials

- Never include token values from `credentials.json` in responses
- Use `mureo auth check-google` / `mureo auth check-meta` for masked output
- If a user asks to see credentials, show masked values only

### 5. Keyword Operations: Execute in Stages

When adding or removing large numbers of keywords:
- Batch into groups of 20 or fewer
- Show progress after each batch
- Allow the user to stop between batches

### 6. Learning Period Awareness

For Google Ads campaigns using smart bidding:
- Warn before making changes that reset the learning period
- Affected operations: bidding strategy changes, budget changes > 20%, conversion setting changes
- Display the current bidding system status if available

## Output Format

All tools return structured JSON via `TextContent`. The format depends on the tool category:

### Success Response

```json
{
  "campaigns": [
    {
      "campaign_id": "12345",
      "name": "Brand Search",
      "status": "ENABLED",
      "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
      "daily_budget": 5000.0
    }
  ]
}
```

### Error Response

```json
{
  "error": "Campaign not found: 99999",
  "error_code": "NOT_FOUND"
}
```

### Authentication Error

```json
{
  "error": "No credentials found. Set environment variables (GOOGLE_ADS_DEVELOPER_TOKEN, ...) or ~/.mureo/credentials.json"
}
```

## CLI Quick Reference

| Command | Description |
|---------|-------------|
| `mureo auth setup` | Interactive authentication wizard |
| `mureo auth status` | Show authentication status |
| `mureo auth check-google` | Verify Google Ads credentials |
| `mureo auth check-meta` | Verify Meta Ads credentials |
| `mureo google-ads campaigns-list` | List Google Ads campaigns |
| `mureo google-ads campaigns-get` | Get campaign details |
| `mureo google-ads ads-list` | List ads |
| `mureo google-ads keywords-list` | List keywords |
| `mureo google-ads budget-get` | Get campaign budget |
| `mureo google-ads performance-report` | Performance report |
| `mureo meta-ads campaigns-list` | List Meta Ads campaigns |
| `mureo meta-ads campaigns-get` | Get campaign details |
| `mureo meta-ads ad-sets-list` | List ad sets |
| `mureo meta-ads ads-list` | List ads |
| `mureo meta-ads insights-report` | Performance report |

All CLI commands output JSON to stdout for easy piping and parsing.
