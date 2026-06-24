---
name: _mureo-shared
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

**mureo** is a local-first control plane for AI ad ops. It sits on top of the official ad-platform MCPs (Meta Ads MCP, Google Ads MCP, etc.) and provides the layer they cannot — strategy enforcement, outcome correlation, and an auditable decision log. It provides:
- **CLI** (`mureo`) for direct command-line usage
- **MCP Server** for integration with AI agent hosts (Claude Code, Cursor, Codex, Gemini, etc.)
- **Python library** for programmatic access

All three interfaces share the same authentication, security rules, and output format.

## Installation

```bash
pip install mureo
```

## Setup

### Claude Code (Recommended)

```bash
mureo setup claude-code
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

## Tool Selection (host-portable patterns)

Skills and commands describe "Read STRATEGY.md", "Update STATE.json", and "Append to action_log" in prose. These map to **different tools depending on the host**, but the intent is identical:

| Action | Claude Code | Claude Desktop chat / Cowork / claude.ai web |
|--------|-------------|-----------------------------------------------|
| Read STRATEGY.md | `Read` tool | `mureo_strategy_get` MCP tool |
| Replace STRATEGY.md | `Write` / `Edit` tool | `mureo_strategy_set` MCP tool |
| Read STATE.json | `Read` tool | `mureo_state_get` MCP tool |
| Append action_log entry | `Edit` tool (modify JSON) | `mureo_state_action_log_append` MCP tool |
| Upsert campaign snapshot | `Edit` tool (modify JSON) | `mureo_state_upsert_campaign` MCP tool |

When you don't have direct filesystem tools (Desktop / Cowork / web), always reach for the corresponding `mureo_*` MCP tool — they encode the same atomic-write semantics so you can't corrupt the file mid-edit.

The platform tools (`google_ads_*`, `meta_ads_*`, `search_console_*`) are the same across all hosts because they only exist as MCP tools.

## Plugin platforms (third-party providers)

Beyond the built-in platforms, an entry-point provider installed as a mureo plugin can expose its own operations as `mcp__mureo__<plugin>_*` tools. When a workflow enumerates "all configured platforms", **also enumerate these plugin tools** and include each plugin platform on a **best-effort, clearly-labelled** line (e.g. `Acme Ads (plugin) — …`), driving it with the plugin's own tools as their names/descriptions imply.

Honest scope for a plugin platform:

- **Include** the basic listing / performance / health its tools support.
- **Skip** mureo-only value-adds — anomaly detection, `result_indicator` CV-mismatch, RSA-asset audit, rule-based scoring. These are platform-specific to the built-ins and do not exist for plugins; say so in the output.
- Plugin tool calls are already audited by mureo, and successful mutations promoted into `action_log` (`platform="plugin:<dist>"`) when run in a strategy workspace (a `STATE.json` exists). Treat plugin **read** findings as **advisory**; do not assume mureo's strategy/rollback guarantees beyond what `action_log` records (an arbitrary plugin operation is not auto-reversible).
- Plugin tool-name mapping is **best-effort** (infer from the live tool list), not deterministic. Never fail the whole workflow because a plugin tool is missing — report it and continue with the built-ins.

### Mutating plugin tools — structural strategy parity

A **mutating** plugin tool (anything not declared `readOnlyHint`) is subject to the *same structural strategy handling as a built-in write*, even though mureo has no platform-specific analytics for it:

- **Confirm before the call.** The *Security Rules → Confirm Before Write Operations* requirement applies to plugin write tools exactly as it does to `google_ads_*` / `meta_ads_*` writes — show the user what will change and get explicit approval first.
- **Gate against strategy.** Before the call, read STRATEGY.md (Operation Mode, Goals, brand/rules) and STATE.json. If the mutation conflicts with the current Operation Mode or a Goal, do **not** run it — surface the conflict and let the user decide, the same as you would for a built-in write.
- **Outcome review is automatic.** The promoted `action_log` entry carries an `observation_due` window, so daily-check's evidence step reviews its outcome like a built-in. There is no `metrics_at_action` baseline (platform-specific analytics do not exist for a plugin) — evaluate that entry **qualitatively/advisory** and never attribute metric movement to it without an independent check.

What does **not** reach parity (by design, state it in output): mureo's platform-specific analytics — anomaly detection, `result_indicator` CV-mismatch, RSA-asset audit, rule-based scoring — and automatic rollback (only built-in allow-listed operations are auto-reversible; a plugin reversal hint is recorded for visibility, not executed).

### Optional: analytics-module parity (Issue #120)

A plugin author OR an official-MCP wrapper can opt into mureo's analytics surface by registering an `AnalyticsModule` (entry-point group `mureo.analytics`; see `docs/plugin-authoring.md` → *Shipping analytics with your plugin*). When a module is registered:

- The MCP tool `mureo_analytics_modules_list` reports which platforms have analytics and which capabilities each advertises (`detect_anomalies`, `diagnose_performance`, `audit_creative`, `analyze_budget_efficiency`).
- Workflow skills (daily-check, rescue, …) consult that list **before** running deep diagnostics on an external-integration platform: if the platform has no module or the needed capability is missing, the skill must say `analytics_not_available_for_<platform>` in its output rather than invent heuristics from the integration's tool schemas. Auto-deriving analytics is unsafe (would produce plausible-but-wrong analysis) and is explicitly out of scope.
- Built-in google_ads and meta_ads ship analytics modules for the capabilities they support today; new platforms get parity by **hand-authoring** a module, not by code generation.

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

The MCP server exposes tools for Google Ads, Meta Ads, and Search Console over stdio.

### Verify MCP Connection

Once configured, the AI agent can call `google_ads_campaigns_list` or `meta_ads_campaigns_list` to verify the connection is working.

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
1. Call `google_ads_budget_get` or read campaign details
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

## STATE.json Schema (when writing on Code via `Write`)

> **Tool output ≠ STATE.json.** The *Success Response* above is what a vendor
> MCP tool *returns* — a campaign there is `{"campaign_id", "name", "status", …}`.
> STATE.json's `CampaignSnapshot` is a **different** shape: it requires
> **`campaign_name`**, not `name`. When you hand-write STATE.json with `Write`
> on Code, **map** the tool-output `name` → `campaign_name` (and `id` →
> `campaign_id`), and always set the platform's **`account_id`**. On Desktop /
> Cowork the `mureo_state_*` MCP tools serialize this canonical shape for you,
> so the mapping only matters on the Code `Write` path.

A campaign or platform missing a required field below is silently **dropped**
by the read-only Reports view (and rejected by a strict read), so the dashboard
shows fewer campaigns than you wrote — get these exact names right:

- **Campaign snapshot** (root `campaigns[]` and `platforms[<p>].campaigns[]`) —
  required: `campaign_id` (str), `campaign_name` (str), `status` (str).
  Optional: `bidding_strategy_type`, `daily_budget`, `campaign_goal`, `notes`,
  `device_targeting`, and `metrics` (the per-campaign performance object:
  `spend` / `impressions` / `clicks` / `conversions` / `cpa` / `ctr` / …).
- **Platform entry** (`platforms[<platform>]`) — required: `account_id` (str;
  use `""` only if genuinely unknown). Plus `campaigns[]` and the rollups the
  dashboard actually renders: `totals`, `metrics_period`, `periods[<window>]`.

Canonical STATE.json shape (note `campaign_name` and `account_id`):

```json
{
  "version": "2",
  "platforms": {
    "google_ads": {
      "account_id": "123-456-7890",
      "campaigns": [
        {
          "campaign_id": "12345",
          "campaign_name": "Brand Search",
          "status": "ENABLED",
          "daily_budget": 5000.0,
          "metrics": {"spend": 4200.0, "clicks": 310, "conversions": 12}
        }
      ],
      "totals": {"spend": 4200.0, "clicks": 310, "conversions": 12},
      "metrics_period": "LAST_30_DAYS",
      "periods": {"LAST_30_DAYS": {"spend": 4200.0, "clicks": 310, "conversions": 12}}
    }
  }
}
```

## CLI Quick Reference

> **The `mureo` CLI covers setup, auth, and service management only — it has NO
> ad-operation subcommands.** Listing campaigns, pulling insights, editing
> budgets, etc. are done through the **MCP tools** (`google_ads_*`,
> `meta_ads_*`, `search_console_*`) — there is **no** `mureo google-ads …` /
> `mureo meta-ads …` shell command. Never run or suggest one (it will error with
> "no such command"); call the corresponding MCP tool instead.

| Command | Description |
|---------|-------------|
| `mureo auth setup` | Interactive auth wizard — records the Google Ads `customer_id` / Meta `account_id` |
| `mureo auth status` | Show authentication status |
| `mureo auth check-google` | Verify Google Ads credentials (masked) |
| `mureo auth check-meta` | Verify Meta Ads credentials (masked) |
| `mureo configure` | Launch the local configuration / Reports UI |
| `mureo service {install,status,restart,uninstall}` | Manage the always-on daemon |
| `mureo upgrade [--all]` | Upgrade mureo (also refreshes deployed skills + restarts the service) |
| `mureo providers {list,add,remove}` | Manage official-MCP / plugin providers |
| `mureo rollback {list,show}` | Inspect reversible actions in the `action_log` (apply a reversal via the `rollback_apply` MCP tool) |

To **list Google Ads campaigns**, call the MCP tool `google_ads_campaigns_list`
(it resolves `customer_id` from the stored credentials). If you hit
`customer_id is required`, do **not** ask the operator to read it from the
Google Ads UI or hand over a CSV — call `google_ads_accounts_list` to discover
the accessible accounts and set it. See `../_mureo-google-ads/SKILL.md` →
*No customer_id? (recovery)*.
