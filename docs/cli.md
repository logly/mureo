# CLI Guide

mureo provides a command-line interface for interacting with Google Ads and Meta Ads accounts directly from the terminal.

## Installation

```bash
# CLI requires the cli extra
pip install "mureo[cli]"
```

This installs [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/) as additional dependencies.

## Command Structure

```
mureo <subcommand-group> <command> [options]
```

Subcommand groups:

| Group | Description |
|-------|-------------|
| `google-ads` | Google Ads operations |
| `meta-ads` | Meta Ads operations |
| `auth` | Authentication management |

Run `mureo --help` to see all available groups. Run `mureo <group> --help` to see commands within a group.

## Authentication Commands

```bash
# Show authentication status for all platforms
mureo auth status

# Check Google Ads credentials (masked output)
mureo auth check-google

# Check Meta Ads credentials (masked output)
mureo auth check-meta

# Interactive setup wizard (OAuth flow + MCP config placement)
mureo auth setup
```

The `mureo auth setup` wizard walks you through:

1. Google Ads OAuth setup (optional) -- opens a browser for OAuth consent and saves the refresh token.
2. Meta Ads token setup (optional) -- prompts for access token, app ID, and app secret.
3. MCP configuration placement -- offers to write the MCP server config to either `~/.claude/settings.json` (global) or `.mcp.json` (project-level).

See [authentication.md](authentication.md) for details on setting up credentials.

## Google Ads Commands

All Google Ads commands require `--customer-id` (your 10-digit Google Ads customer ID).

### List Campaigns

```bash
mureo google-ads campaigns-list --customer-id 1234567890
```

### Get Campaign Details

```bash
mureo google-ads campaigns-get --customer-id 1234567890 --campaign-id 111222333
```

### List Ads

```bash
mureo google-ads ads-list --customer-id 1234567890 --ad-group-id 444555666
```

### List Keywords

```bash
mureo google-ads keywords-list --customer-id 1234567890 --ad-group-id 444555666
```

### Get Campaign Budget

```bash
mureo google-ads budget-get --customer-id 1234567890 --campaign-id 111222333
```

### Performance Report

```bash
# Default: last 7 days
mureo google-ads performance-report --customer-id 1234567890

# Custom period
mureo google-ads performance-report --customer-id 1234567890 --days 30
```

## Meta Ads Commands

All Meta Ads commands require `--account-id` (your Meta Ads account ID in `act_XXXX` format).

### List Campaigns

```bash
mureo meta-ads campaigns-list --account-id act_1234567890
```

### Get Campaign Details

```bash
mureo meta-ads campaigns-get --account-id act_1234567890 --campaign-id 23851234567890
```

### List Ad Sets

```bash
mureo meta-ads ad-sets-list --account-id act_1234567890
```

### List Ads

```bash
mureo meta-ads ads-list --account-id act_1234567890
```

### Insights Report

```bash
# Default: last 7 days
mureo meta-ads insights-report --account-id act_1234567890

# Custom period (1 = yesterday, 7 = last 7 days, 30 = last 30 days)
mureo meta-ads insights-report --account-id act_1234567890 --days 30
```

## Output Format

All commands output JSON to stdout. This makes it easy to pipe results to other tools:

```bash
# Pretty-print with jq
mureo google-ads campaigns-list --customer-id 1234567890 | jq .

# Extract campaign names
mureo google-ads campaigns-list --customer-id 1234567890 | jq '.[].name'

# Save to file
mureo meta-ads insights-report --account-id act_1234567890 > report.json
```

Example output:

```json
[
  {
    "id": "111222333",
    "name": "Brand - Search",
    "status": "ENABLED",
    "bidding_strategy_type": "TARGET_CPA",
    "budget": {
      "amount_micros": 50000000,
      "delivery_method": "STANDARD"
    }
  }
]
```

## Error Handling

If credentials are missing, the CLI prints an error to stderr and exits with code 1:

```bash
$ mureo google-ads campaigns-list --customer-id 1234567890
Error: Google Ads authentication credentials not found
```

API errors are propagated as runtime exceptions with a descriptive message.
