# Docker Guide

Run the mureo MCP server in an isolated container. Useful for:

- **Non–Claude Code MCP clients**: Cursor, Codex CLI, Gemini CLI, Continue, Cline, Zed, or any custom MCP client.
- **CI/CD pipelines**: scheduled anomaly checks, rollback dry-runs, weekly reports.
- **Multi-tenant / agency ops**: isolated credentials per client via separate containers.
- **MCP registry health checks** (Glama, etc.).

> Slash commands (`/daily-check`, `/rescue`) and the credential-guard hook are Claude Code–specific UX. For those, use `pip install mureo` with `mureo setup claude-code` instead.

## Build and run

```bash
docker build -t mureo .
docker run --rm -v ~/.mureo:/home/mureo/.mureo mureo
```

Connect your MCP client by pointing its config at this `docker run` command.

## Authentication

Credentials are loaded from `/home/mureo/.mureo/credentials.json` inside the container (via bind mount) or from environment variables. Three common patterns:

**1. Mounted credentials file** — if `~/.mureo/credentials.json` already exists on the host (from a prior `mureo auth setup`, a team-shared vault, or hand-crafted), the bind mount above is enough.

Schema for hand-crafting:

```json
{
  "google_ads": {
    "developer_token": "...",
    "client_id": "...apps.googleusercontent.com",
    "client_secret": "...",
    "refresh_token": "...",
    "login_customer_id": "1234567890"
  },
  "meta_ads": { "access_token": "..." }
}
```

Required: Google needs `developer_token` / `client_id` / `client_secret` / `refresh_token`. Meta needs `access_token`. Search Console reuses the Google OAuth credentials (OAuth app must include the `https://www.googleapis.com/auth/webmasters` scope).

**2. Environment variables** — useful for CI/CD where secrets come from a secret manager:

```bash
docker run --rm \
  -e GOOGLE_ADS_DEVELOPER_TOKEN=... \
  -e GOOGLE_ADS_CLIENT_ID=... \
  -e GOOGLE_ADS_CLIENT_SECRET=... \
  -e GOOGLE_ADS_REFRESH_TOKEN=... \
  -e GOOGLE_ADS_LOGIN_CUSTOMER_ID=... \
  -e META_ADS_ACCESS_TOKEN=... \
  mureo
```

Supported: `GOOGLE_ADS_{DEVELOPER_TOKEN, CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, LOGIN_CUSTOMER_ID, CUSTOMER_ID}`, `META_ADS_{ACCESS_TOKEN, APP_ID, APP_SECRET, TOKEN_OBTAINED_AT, ACCOUNT_ID}`.

**3. Interactive wizard inside Docker** — if you don't have OAuth tokens yet and don't want to install mureo on the host:

```bash
docker run -it --rm -v ~/.mureo:/home/mureo/.mureo mureo mureo auth setup
```

Walks you through the OAuth flow in the terminal and writes `credentials.json` to the mounted volume. Subsequent runs pick it up automatically (pattern 1).

To obtain OAuth tokens outside mureo:

- Google Ads OAuth 2.0 refresh token: https://developers.google.com/google-ads/api/docs/oauth/overview
- Meta long-lived access token: https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived
