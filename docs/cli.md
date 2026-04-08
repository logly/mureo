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
| `setup` | Environment setup (Claude Code, Cursor) |
| `auth` | Authentication management |

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

Ad platform operations (listing campaigns, creating ads, analyzing performance, etc.) are available through **MCP tools**, not the CLI. AI agents (Claude Code, Cursor) call these tools directly.

See [mcp-server.md](mcp-server.md) for the full tool reference.
