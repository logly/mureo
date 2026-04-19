# Authentication Guide

## Recommended Setup

For most users, the one-command setup is the easiest way to get started:

```bash
# Claude Code users (authentication + MCP + commands + skills + credential guard)
mureo setup claude-code

# Cursor users (authentication + MCP only)
mureo setup cursor

# OpenAI Codex CLI users (MCP + credential guard + workflow skills + shared skills)
mureo setup codex

# Gemini CLI users (extension manifest + MCP)
mureo setup gemini

# CLI-only users (authentication only, terminal prompts)
mureo auth setup

# Browser-based auth wizard — localhost HTML form, no terminal input needed
mureo auth setup --web
```

### `--skip-auth` and non-interactive invocation

Every `mureo setup …` subcommand accepts `--skip-auth`, which installs the MCP config, credential guard, and (where supported) command/skill files without running OAuth. Useful for the double-click installer flow where authentication is handled later via `/onboard` in Claude Code, `$onboard` in Codex, or `mureo auth setup` in a real terminal.

When `mureo setup …` is invoked from an AI agent's subprocess (Claude Code's Bash tool, Codex, etc.) that has no controlling TTY, `--skip-auth` is implied automatically so the command cannot hang on a `typer.confirm` prompt. A banner in stdout tells the operator to finish authentication in `Terminal.app` afterwards.

Each subcommand also exposes explicit `--google-ads/--no-google-ads` and `--meta-ads/--no-meta-ads` flags, so you can specify exactly which platforms to configure without any prompt. Passing them alongside `--skip-auth` (or under a non-TTY) emits a warning and is ignored.

### `mureo auth setup --web` — browser-based wizard

Prefer the `--web` flavour when you were pointed to mureo by an AI agent that cannot safely receive terminal input. It starts a short-lived HTTP server on a random localhost port, opens your browser at it, and walks you through Google Ads / Meta Ads credential entry via HTML forms and standard OAuth redirects. Every field in the form has a deep link next to it so you know where to fetch each secret. Security hardening (CSRF rotation, OAuth `state` re-validation, DNS-rebinding guard, localhost-pinned redirect verification, generic error surface, POST size cap, CSP) is described in `SECURITY.md` → "Browser-based auth wizard".

## How Credentials Work

mureo loads credentials from `~/.mureo/credentials.json`, falling back to environment variables if the file is missing or incomplete.

## credentials.json Format

Create `~/.mureo/credentials.json` with the following structure:

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
    "access_token": "YOUR_ACCESS_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET"
  }
}
```

You can include only the platforms you use. For example, if you only use Google Ads, the `meta_ads` section can be omitted.

### Google Ads Fields

| Field | Required | Description |
|-------|----------|-------------|
| `developer_token` | Yes | Google Ads API developer token |
| `client_id` | Yes | OAuth 2.0 client ID |
| `client_secret` | Yes | OAuth 2.0 client secret |
| `refresh_token` | Yes | OAuth 2.0 refresh token |
| `login_customer_id` | No | Manager account ID (MCC). If omitted, the target `customer_id` is used as fallback. |

### Meta Ads Fields

| Field | Required | Description |
|-------|----------|-------------|
| `access_token` | Yes | Meta Graph API access token (User or System User token) |
| `app_id` | No | Meta App ID |
| `app_secret` | No | Meta App Secret |

## Environment Variable Fallback

If `~/.mureo/credentials.json` is missing or lacks the required fields, mureo falls back to environment variables.

### Google Ads

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | Yes | API developer token |
| `GOOGLE_ADS_CLIENT_ID` | Yes | OAuth 2.0 client ID |
| `GOOGLE_ADS_CLIENT_SECRET` | Yes | OAuth 2.0 client secret |
| `GOOGLE_ADS_REFRESH_TOKEN` | Yes | OAuth 2.0 refresh token |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | No | Manager account (MCC) customer ID |

### Meta Ads

| Variable | Required | Description |
|----------|----------|-------------|
| `META_ADS_ACCESS_TOKEN` | Yes | Graph API access token |
| `META_ADS_APP_ID` | No | Meta App ID |
| `META_ADS_APP_SECRET` | No | Meta App Secret |

**Resolution order**: credentials.json takes priority. Environment variables are only checked if the corresponding section in credentials.json is missing or incomplete.

## Obtaining Google Ads Credentials

### 1. Developer Token

1. Sign in to your Google Ads Manager account at [ads.google.com](https://ads.google.com).
2. Navigate to **Tools & Settings > Setup > API Center**.
3. If you don't have a developer token, apply for one. For testing, you'll receive a test token immediately.
4. Copy the developer token.

### 2. OAuth 2.0 Client ID and Secret

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Enable the **Google Ads API** under **APIs & Services > Library**.
4. Navigate to **APIs & Services > Credentials**.
5. Click **Create Credentials > OAuth client ID**.
6. Select **Desktop app** as the application type.
7. Copy the **Client ID** and **Client Secret**.

### 3. Refresh Token

Use the `google-auth-oauthlib` library to obtain a refresh token:

```python
from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    },
    scopes=["https://www.googleapis.com/auth/adwords"],
)
flow.run_local_server(port=8080)
print("Refresh token:", flow.credentials.refresh_token)
```

Alternatively, use the [Google OAuth Playground](https://developers.google.com/oauthplayground/) with the `https://www.googleapis.com/auth/adwords` scope.

## Obtaining Meta Ads Credentials

### Access Token

**Option A: Graph API Explorer (for testing)**

1. Go to [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app.
3. Click **Generate Access Token** with the `ads_management` and `ads_read` permissions.
4. The resulting token is short-lived (1-2 hours).

**Option B: Long-Lived Token (for production)**

1. Obtain a short-lived user token via the Graph API Explorer.
2. Exchange it for a long-lived token (60 days):

```bash
curl -X GET "https://graph.facebook.com/v21.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=SHORT_LIVED_TOKEN"
```

**Option C: System User Token (recommended for automation)**

1. Go to [Business Settings](https://business.facebook.com/settings/) > **System Users**.
2. Create a System User with **Admin** role.
3. Assign the ad account to the system user.
4. Generate a token with `ads_management` permission.
5. System User tokens do not expire.

### App ID and App Secret

1. Go to [Meta for Developers](https://developers.facebook.com/).
2. Navigate to your app > **Settings > Basic**.
3. Copy the **App ID** and **App Secret**.

These are optional for basic use, but **required for automatic token refresh** (see below).

## Meta Ads Token Auto-Refresh

mureo can automatically refresh Long-Lived Tokens before they expire, so you never have to manually exchange tokens again.

### How It Works

1. When `mureo auth setup` saves a Meta Ads token, it records a `token_obtained_at` ISO 8601 timestamp in `credentials.json`.
2. Each time Meta Ads credentials are loaded, mureo checks the token age.
3. If the token is **53+ days old** (7-day safety margin before the 60-day expiry), mureo exchanges it for a fresh Long-Lived Token via the Meta Graph API.
4. The new token and timestamp are written back to `credentials.json` atomically.

### Requirements

| Field | Required | Why |
|-------|----------|-----|
| `app_id` | Yes | Needed for the token exchange API call |
| `app_secret` | Yes | Needed for the token exchange API call |
| `token_obtained_at` | Auto | Written by `mureo auth setup`; can be added manually (ISO 8601 format) |

If `app_id` or `app_secret` are missing, auto-refresh is silently skipped and the existing token is used as-is.

### credentials.json with auto-refresh fields

```json
{
  "meta_ads": {
    "access_token": "YOUR_ACCESS_TOKEN",
    "app_id": "YOUR_APP_ID",
    "app_secret": "YOUR_APP_SECRET",
    "token_obtained_at": "2025-12-01T00:00:00Z"
  }
}
```

### Safety Features

- **Concurrent protection** -- an `asyncio.Lock` prevents multiple simultaneous refresh attempts.
- **Atomic file write** -- credentials are written to a temp file first, then renamed, to prevent corruption.
- **0600 permissions** -- the credentials file is restricted to the owner only.
- **Graceful fallback** -- if the refresh fails for any reason (network error, expired app secret, etc.), mureo continues with the existing token and logs a warning. No tool calls are blocked.

## Interactive Setup Wizard

`mureo auth setup` (also called as part of `mureo setup claude-code`) walks you through authentication interactively:

1. **Google Ads OAuth** -- Enter Developer Token + Client ID/Secret, open browser for OAuth, select account.
2. **Meta Ads OAuth** -- Enter App ID/Secret, open browser for OAuth, obtain Long-Lived Token, select account.
3. **MCP configuration** -- Choose global (`~/.claude/settings.json`) or project-level (`.mcp.json`).

### Project-Level MCP Configuration (`.mcp.json`)

If you choose project-level placement, `mureo auth setup` creates a `.mcp.json` file in your project root:

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

AI agents that support `.mcp.json` (e.g., Claude Code) will automatically discover and connect to the mureo MCP server when working in that project directory.

## Verifying Credentials

Use the `mureo auth` commands to verify your setup:

```bash
# Show authentication status for all platforms
mureo auth status

# Check Google Ads credentials (shows masked values)
mureo auth check-google

# Check Meta Ads credentials (shows masked values)
mureo auth check-meta
```

Example output for `mureo auth status`:

```
=== Authentication Status ===

Google Ads: Authenticated
Meta Ads: Authenticated
```

Example output for `mureo auth check-google`:

```json
{
  "developer_token": "***************abcd",
  "client_id": "123456789.apps.googleusercontent.com",
  "client_secret": "***************wxyz",
  "refresh_token": "***************efgh",
  "login_customer_id": "1234567890"
}
```

Secrets are masked, showing only the last 4 characters. This lets you verify the right credentials are loaded without exposing them.
