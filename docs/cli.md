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

### OpenAI Codex CLI

```bash
mureo setup codex
```

Full parity with Claude Code. Installs:

1. MCP server configuration as a tagged `[mcp_servers.mureo]` block in `~/.codex/config.toml` (append-only; refuses to overwrite an untagged pre-existing `[mcp_servers.mureo]`).
2. Credential guard — PreToolUse hooks in `~/.codex/hooks.json` (Read + Bash) that block any tool call that would touch `~/.mureo/credentials*`.
3. Workflow commands as **Codex skills** at `~/.codex/skills/<command>/SKILL.md` with YAML frontmatter. Users invoke them with `$daily-check`, `$onboard`, … or via the `/skills` picker. (Codex CLI 0.117.0+ no longer surfaces `~/.codex/prompts/`, per [openai/codex#15941](https://github.com/openai/codex/issues/15941); re-running `mureo setup codex` also deletes stale prompt files that mureo owns, while leaving user-authored prompts alone.)
4. Shared mureo skills at `~/.codex/skills/mureo-*/`.

`--skip-auth` is supported and is auto-implied under a non-TTY subprocess (e.g. an AI agent's Bash tool) so the command can never hang on a confirm prompt.

### Gemini CLI

```bash
mureo setup gemini
```

Registers mureo as a Gemini CLI extension at `~/.gemini/extensions/mureo/gemini-extension.json` with `mcpServers.mureo` and `contextFileName: CONTEXT.md`. Operator-added top-level keys (`excludeTools`, renamed `contextFileName`) and extra `mcpServers` entries are preserved across reinstall. Gemini CLI does not support PreToolUse hooks or the `.md` command format, so those layers are not installed.

### Per-platform flags (all `setup …` subcommands)

Every setup subcommand accepts:

- `--skip-auth` — install MCP config (+ guard / commands / skills, where supported) without running OAuth. Auto-implied under a non-TTY invocation.
- `--google-ads` / `--no-google-ads` — override the "configure Google Ads?" prompt.
- `--meta-ads` / `--no-meta-ads` — override the "configure Meta Ads?" prompt.

Passing the platform flags alongside `--skip-auth` (or under a non-TTY) emits a warning and is ignored.

## Authentication Commands

```bash
# Show authentication status for all platforms
mureo auth status

# Check Google Ads credentials (masked output)
mureo auth check-google

# Check Meta Ads credentials (masked output)
mureo auth check-meta

# Interactive authentication wizard (terminal prompts)
mureo auth setup

# Browser-based authentication wizard (no terminal input needed)
mureo auth setup --web
```

`mureo auth setup` has two flavours:

- **Terminal mode (default)** — walks you through Google Ads / Meta Ads setup via stdin prompts. Best when you're comfortable with pasting secrets into a terminal.
- **`--web` mode** — starts a local HTTP wizard on `http://127.0.0.1:<random-port>/`, opens it in your browser, and asks for the same secrets via an HTML form. Recommended when you were pointed here by an AI agent (Claude Code, etc.) that cannot itself receive terminal input safely. Every field has a deep link next to it so you know where to fetch the Developer Token / App ID / Secret from Google's or Meta's console.

Both modes end at the same destination: `~/.mureo/credentials.json` is populated and Claude Desktop (or any other MCP client) picks up mureo after a restart.

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
