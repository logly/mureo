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

# Browser configuration UI — localhost, no terminal input needed
# (supersedes the removed `mureo auth setup --web`)
mureo configure
```

### `--skip-auth` and non-interactive invocation

Every `mureo setup …` subcommand accepts `--skip-auth`, which installs the MCP config, credential guard, and (where supported) command/skill files without running OAuth. Useful for the double-click installer flow where authentication is handled later via `/onboard` in Claude Code, `$onboard` in Codex, or `mureo auth setup` in a real terminal.

When `mureo setup …` is invoked from an AI agent's subprocess (Claude Code's Bash tool, Codex, etc.) that has no controlling TTY, `--skip-auth` is implied automatically so the command cannot hang on a `typer.confirm` prompt. A banner in stdout tells the operator to finish authentication in `Terminal.app` afterwards.

Each subcommand also exposes explicit `--google-ads/--no-google-ads` and `--meta-ads/--no-meta-ads` flags, so you can specify exactly which platforms to configure without any prompt. Passing them alongside `--skip-auth` (or under a non-TTY) emits a warning and is ignored.

### `mureo configure` — browser configuration UI

> `mureo auth setup --web` was **removed**; its browser credential flow is now part of the unified `mureo configure` UI.

Prefer `mureo configure` when you were pointed to mureo by an AI agent that cannot safely receive terminal input, or you simply want a GUI. It starts a short-lived HTTP server on a random localhost port, opens your browser at it, and — beyond Google Ads / Meta Ads / GA4 credential entry via HTML forms and standard OAuth redirects (every field deep-linked to the right console), plus an **Amazon Ads** card in the dashboard's *Plugin credentials* section whose **Authorize with Amazon** flow obtains the LwA tokens (Amazon's consent has no loopback callback, so it is a guided paste-code flow: mureo opens the consent page and you paste the redirected address back; see [amazon-ads.md](amazon-ads.md)) — also lets you pick the Claude host, run basic setup (MCP server + credential-guard hook + skills), add the official MCP providers, switch each platform between mureo-native and the official MCP, and scaffold Demo/BYOD. Flags: `--no-browser`, `--timeout-seconds N` (idle shutdown, default 600). The same security hardening (CSRF rotation, OAuth `state` re-validation, DNS-rebinding guard, localhost-pinned redirect verification, generic error surface, POST size cap, CSP) applies — see `SECURITY.md`.

**When something fails in the UI**, the on-screen message is deliberately generic (an error surface must not echo token material). The cause is in the configure log — `~/.mureo/logs/configure.log`, printed on startup and written on every platform — including the ones that are otherwise invisible: a Meta token refresh that failed or could not be persisted, an account listing that was rejected, a `credentials.json` that would not parse. Raise the detail with `MUREO_LOG_LEVEL=DEBUG mureo configure`. No log line at any level carries a token, secret or credential value. See [cli.md — Configure log](cli.md#configure-log).

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

### Amazon Ads

| Variable | Required | Description |
|----------|----------|-------------|
| `AMAZON_ADS_CLIENT_ID` | Yes | Login with Amazon (LwA) application client ID |
| `AMAZON_ADS_REFRESH_TOKEN` | Conditional | LwA refresh token — with the client secret, mureo mints and refreshes access tokens for you |
| `AMAZON_ADS_CLIENT_SECRET` | Conditional | LwA application client secret |
| `AMAZON_ADS_ACCESS_TOKEN` | Conditional | LwA access token (expires in ~60 min) |
| `AMAZON_ADS_REGION` | No | `na` / `eu` / `fe` (default `na`) |
| `AMAZON_ADS_ACCOUNT_MODE` | No | `dynamic` / `fixed` (default `dynamic`) |
| `AMAZON_ADS_PROFILE_ID` | No | Fixed account mode only |
| `AMAZON_ADS_ACCOUNT_ID` | No | Fixed account mode only |
| `AMAZON_ADS_MANAGER_ACCOUNT_ID` | No | Fixed account mode only |

"Conditional" means the client ID plus **either** `AMAZON_ADS_ACCESS_TOKEN` **or both** of `AMAZON_ADS_REFRESH_TOKEN` and `AMAZON_ADS_CLIENT_SECRET`. See [amazon-ads.md](amazon-ads.md).

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

> **Scope matters.** The refresh token *must* carry the Google Ads scope `https://www.googleapis.com/auth/adwords`. Reusing a refresh token minted for a different scope makes Google Ads API calls fail at runtime with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. `mureo configure` / `mureo auth setup` request this scope (plus Search Console) automatically — prefer them over hand-minted tokens. Official reference: [Google Ads API — OAuth 2.0 scopes](https://developers.google.com/google-ads/api/docs/oauth/overview).

## Obtaining Meta Ads Credentials

### Permissions (OAuth scopes)

`mureo configure` / `mureo auth setup` request the following scopes automatically during sign-in — you do not list them by hand. The full set is the source of truth in `mureo/auth_setup.py` (`_META_OAUTH_SCOPES`):

| Scope | Enables |
| --- | --- |
| `ads_management` | Create / edit campaigns, ad sets, ads, budgets, bids |
| `ads_read` | Read ad data and insights |
| `business_management` | Resolve ad accounts reached through a Business Portfolio (a permission warning may appear during sign-in — it is required and safe to accept) |
| `pages_show_list` | List the Facebook Pages you can link |
| `pages_manage_ads` | Manage ads tied to a Page |
| `pages_read_engagement` | Read a Page's posts and photos (list posts for the Boost Post flow, `meta_ads_page_posts_list`; list existing Page photos to pick an Instant Form cover from, `meta_ads_pages_list_photos`) |
| `leads_retrieval` | Retrieve leads from Lead Ads / Instant Forms |

Notes:

- `public_profile` is granted by default on every Facebook Login and does not need to be requested explicitly, so it is not in the list above.
- "Page Public Metadata Access" / "Page Public Content Access" are **not** required — mureo only ever operates on Pages you administer (it resolves a Page Access Token via `/me/accounts` and Business-owned Pages), never arbitrary public Pages.
- `pages_manage_posts` was requested through v0.14.0 and is not requested any more. It existed to upload a Page photo for an Instant Form cover; the cover is now picked from photos the Page already has (`meta_ads_pages_list_photos`), which reads with `pages_read_engagement` + `pages_show_list`. A token issued earlier still carries the granted permission — nothing in mureo calls it, and dropping it needs no action from you.
- After upgrading mureo to a version that adds new scopes, re-run `mureo auth setup` (or re-authenticate in `mureo configure`) so the token is re-issued with the new permissions — an existing token does not gain scopes retroactively. Removing a scope needs no re-auth.

### Access Token

**Option A: Graph API Explorer (for testing)**

1. Go to [Meta Graph API Explorer](https://developers.facebook.com/tools/explorer/).
2. Select your app.
3. Click **Generate Access Token**. For read/write ads, `ads_management` + `ads_read` is the minimum; add the `pages_*` / `leads_retrieval` scopes from the table above to exercise Page, Lead Ads, and Instant Form features.
4. The resulting token is short-lived (1-2 hours).

**Option B: Long-Lived Token (for production)**

1. Obtain a short-lived user token via the Graph API Explorer.
2. Exchange it for a long-lived token (60 days):

```bash
curl -X POST "https://graph.facebook.com/v21.0/oauth/access_token" \
  -d "grant_type=fb_exchange_token" \
  -d "client_id=YOUR_APP_ID" \
  -d "client_secret=YOUR_APP_SECRET" \
  -d "fb_exchange_token=SHORT_LIVED_TOKEN"
```

> **Use POST, not GET.** The Graph `/oauth/access_token` endpoint
> accepts these parameters via the request body, keeping `client_secret`
> and the token out of the URL (and out of any request/proxy logs).
> mureo's own token exchange posts them as a form body for the same
> reason.

**Option C: System User Token (recommended for automation — and required for Live apps)**

A Business Manager **system-user token** is the most robust Meta credential,
and for many operators it is the *only* one that works end to end:

- **Live-mode apps cannot complete OAuth from the localhost configure UI.**
  Facebook rejects the `http://localhost` redirect on its own consent page,
  so the failure happens before mureo's callback is ever reached — the browser
  login simply dead-ends. A system-user token needs no browser redirect.
- **Dev-mode apps cannot create ad creatives.** Uploading the image asset may
  succeed, but publishing a **new** creative to Meta requires a **Live app** —
  a development-mode app is blocked with error subcode **1885183**. A
  system-user token minted on the Live app clears this.

Generate one (4 steps):

1. **Business settings → System users** → create a system user with the
   **Admin** role.
2. Assign the **ad account** (Manage ads) and the **Page** (Manage content) to
   that system user.
3. Generate a token **for your Live app**, choose **Never expire**, and select
   the scopes `ads_management`, `ads_read`, `business_management`,
   `pages_manage_ads`, `pages_read_engagement` (add the remaining `pages_*` /
   `leads_retrieval` scopes from the table above for Page / Lead Ads / Instant
   Form features).
4. Copy the generated token.

**Entering the token in the configure UI.** In the Meta Ads authentication step
of `mureo configure`, open **"Paste a system-user token"** (next to *Login with
Facebook*), paste the token, click **Validate token** (this reports the granted
vs missing scopes and lists the ad accounts the token can reach), pick the ad
account, then **Save**. Because the token never expires, mureo stores it
**without** `app_id` / `app_secret`, which keeps it out of the auto-refresh path
below — nothing to rotate, nothing to expire.

Prefer that card. Saving `META_ADS_ACCESS_TOKEN` through the Setup tab's
**mureo Credentials (advanced)** form also works — a hand-entered token is
stored as entered and stays off the auto-refresh clock — but it writes one
field, so it neither validates the token nor lets you pick an ad account.

System User tokens do not expire.

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

### When the refresh does not happen

Auto-refresh runs on credential load, so a mureo that has not been used for two
months, or an exchange Meta keeps rejecting, leaves an aging token on disk. The
dashboard's **mureo integrations** list watches for exactly that: past 53 days
the Meta row shows how old the token is and why that matters, next to a
**Re-authenticate** button that opens the system-user token card in place — no
need to re-run the setup wizard.

Only a token that can expire is flagged. A system-user token is stored without
`app_id` / `app_secret` (see above), and a token saved without a
`token_obtained_at` stamp has an age mureo cannot know; neither is ever
reported as expiring.

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
