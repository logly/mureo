# CLI Guide

mureo provides a command-line interface for setup, authentication, and environment configuration. Ad platform operations are handled through MCP tools used by AI agents, not through the CLI.

## Installation

```bash
pip install mureo
```

## Command Structure

```
mureo <subcommand-group> <command> [options]
```

| Group | Description |
|-------|-------------|
| `setup` | Environment setup (Claude Code, Cursor, Codex, Gemini) |
| `auth` | Authentication management |
| `rollback` | Inspect reversible actions recorded in STATE.json |

Run `mureo --help` to see all available groups.

## Setup Commands

### Claude Code (recommended)

```bash
mureo setup claude-code
```

One-command setup that handles:
1. Google Ads / Meta Ads authentication (OAuth)
2. MCP server configuration (`~/.claude/settings.json`)
3. Credential guard (blocks AI agents from reading secrets)
4. Workflow commands (`~/.claude/commands/`)
5. Skills (`~/.claude/skills/`)

Use `--skip-auth` to install commands, skills, MCP config, and credential guard without running OAuth:

```bash
mureo setup claude-code --skip-auth
```

### Cursor

```bash
mureo setup cursor
```

Sets up authentication and MCP configuration for Cursor. Cursor does not support workflow commands or skills.

## Authentication Commands

```bash
# Show authentication status for all platforms
mureo auth status

# Check Google Ads credentials (masked output)
mureo auth check-google

# Check Meta Ads credentials (masked output)
mureo auth check-meta

# Interactive authentication wizard (OAuth flow)
mureo auth setup
```

`mureo auth setup` is also called as part of `mureo setup claude-code`. It walks you through:

1. Google Ads OAuth setup (optional) -- opens a browser for OAuth consent and saves the refresh token.
2. Meta Ads token setup (optional) -- prompts for access token, app ID, and app secret.
3. MCP configuration placement.

See [authentication.md](authentication.md) for details on credentials.

## Rollback Commands

`mureo rollback` lets an operator inspect reversible actions recorded in `STATE.json`. The commands are read-only — executing a rollback still goes through the MCP dispatcher so it re-enters the same policy gate as forward actions.

```bash
# List every state-changing action log entry with the planner's verdict.
mureo rollback list

# Limit to one platform.
mureo rollback list --platform google_ads

# Inspect a specific entry (index as shown by `list`).
mureo rollback show 3

# Point at a non-default STATE.json location.
mureo rollback list --state-file /path/to/STATE.json
```

`list` output:

```
  #  timestamp            platform    status           action
------------------------------------------------------------------------
  0  2026-04-15T10:00:00  google_ads  supported        update_budget
  2  2026-04-13T12:00:00  meta_ads    partial       *  update_status
  3  2026-04-12T08:00:00  google_ads  not_supported    update_budget
```

`*` marks entries with caveats (e.g. "spend during pause is not refundable"); run `mureo rollback show <#>` for the full detail.

`show` emits JSON for scripting:

```json
{
  "index": 0,
  "source_timestamp": "2026-04-15T10:00:00",
  "source_action": "update_budget",
  "platform": "google_ads",
  "status": "supported",
  "operation": "google_ads.budgets.update",
  "params": {"budget_id": "222", "amount_micros": 10000000000},
  "caveats": [],
  "notes": ""
}
```

A rollback entry only appears when the agent wrote a `reversible_params` hint at the time of the original action. Operations outside the planner's allow-list, or hints that smuggle unexpected parameter keys, are rejected at plan time — see [architecture.md](architecture.md#defense-in-depth-for-ai-agents) for the threat model.

### Applying a rollback

Execution is not a CLI command — it is the `rollback.apply` MCP tool. The CLI is intentionally read-only; applying a rollback from the CLI would bypass the authentication, rate-limiting, and input-validation gate that every forward action passes through. To apply a rollback, ask the agent to call `rollback.apply` with the index shown by `mureo rollback list`:

```
You: "Roll back action #0."
Agent: rollback.plan.get → previews the reversal.
Agent: rollback.apply({index: 0, confirm: true}) → dispatches.
```

`confirm` must be the literal boolean `true` (truthy non-booleans are refused). On success the executor appends a new log entry tagged `rollback_of=<index>`; a second apply of the same index is refused. `state_file` resolves strictly inside the MCP server's current working directory — `..`-traversal and symlink escape are refused so an attacker-crafted `STATE.json` elsewhere on disk cannot be used as the reversal source.

## Output Format

Authentication check commands output JSON to stdout:

```bash
mureo auth check-google | jq .
```

```json
{
  "developer_token": "***************abcd",
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "***************wxyz",
  "refresh_token": "***************efgh",
  "login_customer_id": "1234567890"
}
```

Secrets are masked, showing only the last 4 characters.

## Ad Platform Operations

Ad platform operations (listing campaigns, creating ads, analyzing performance, etc.) are available through **MCP tools**, not the CLI. AI agents (Claude Code, Cursor, Codex, Gemini) call these tools directly.

See [mcp-server.md](mcp-server.md) for the full tool reference.
