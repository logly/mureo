# Amazon Ads (official-MCP bridge)

mureo connects to the **official Amazon Ads MCP** on your behalf, the
same way mureo-native Google/Meta work:

```
Claude  →  local mureo MCP  →  Amazon hosted MCP endpoint
```

Credentials live in `~/.mureo/credentials.json` (Claude never sees
them), and every Amazon tool call flows through mureo's audit /
throttle / strategy / rollback safety layer.

**Scope (honest):** read-focused, the manifest-backed bridge below.
Amazon's own tool names are exposed as-is (no taxonomy remap) —
consistent with how mureo treats other official MCPs. LwA access-token
auto-refresh is built in (see below). Deep per-platform analytics
keyed to Amazon's native tool names are **not** available yet (tracked
in #120) — treat Amazon findings as advisory.

## 1. Get Amazon credentials (you do this — mureo never enters them)

You need a **Login with Amazon (LwA) app** + an Amazon Developer
account with **Amazon Ads API** access. From those, obtain:

- `client_id` (the LwA application client id)
- `access_token` (an LwA access token; **expires after ~60 minutes**)
- `refresh_token` + `client_secret` — strongly recommended: together
  they let mureo refresh the access token for you (see below). Without
  them you must paste a fresh `access_token` by hand each time.

## 2. Add the `amazon_ads` section to `~/.mureo/credentials.json`

```json
{
  "amazon_ads": {
    "client_id": "amzn1.application-oa2-client.xxxxx",
    "access_token": "Atza|xxxxx",
    "region": "na",
    "account_mode": "dynamic"
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `client_id` | yes | LwA application client id |
| `access_token` | yes | LwA access token (`Atza|…`) |
| `region` | no (default `na`) | `na` / `eu` / `fe` — picks the endpoint |
| `account_mode` | no (default `dynamic`) | `dynamic` (LLM is asked per call) or `fixed` |
| `refresh_token`, `client_secret` | recommended | both required to enable automatic access-token refresh |
| `profile_id`, `account_id`, `manager_account_id` | no | **Fixed** mode only (≥1 required to engage Fixed) |

## 3. Build the tool manifest

```bash
mureo amazon refresh-manifest
```

This connects once (authenticated), lists Amazon's MCP tools, and
writes `~/.mureo/amazon_tools.json`. The mureo MCP server reads that
file **at start** (pure, no network, no credentials) to expose the
Amazon tools — so a missing manifest simply means "no Amazon tools",
never a startup failure.

Re-run this command whenever Amazon's tool surface changes, or after
you re-authorize. It is not needed for a routine token refresh — mureo
does that itself (see below).

## 4. Restart Claude / the mureo MCP server

Amazon's tools now appear (under Amazon's own names, e.g.
`campaign_management-*`, `account_management-*`) and are audited +
strategy-gated like built-in platforms. Mutating calls are promoted
into `STATE.json` `action_log` (`platform=plugin:mureo-amazon-ads-bridge`)
with an observation window, exactly like the #114 plugin safety layer.

## Access-token refresh (automatic)

When **both** `refresh_token` and `client_secret` are present, mureo
handles the ~60-minute expiry for you. On the first failure of an
Amazon tool call it performs exactly one Login-with-Amazon refresh
(`grant_type=refresh_token` against the regional token host), writes
the new token back into `~/.mureo/credentials.json`, and retries the
call once. Tokens and secrets never appear in error messages or logs.

- One refresh + one retry per call, never a loop.
- If Amazon answers `invalid_grant`, the refresh token itself is dead:
  the advertiser must re-authorize, and mureo says so explicitly.
- If `~/.mureo/credentials.json` cannot be written (most often because
  it is malformed — mureo refuses to overwrite a corrupt file and lose
  your other providers' credentials), the call fails with that reason
  rather than a silent retry loop.
- `mureo amazon refresh-manifest` does **not** auto-refresh; it uses
  the stored `access_token` as-is. Refresh only happens on the tool
  dispatch path.

Without `refresh_token` + `client_secret`, update `access_token` in
`~/.mureo/credentials.json` by hand when it expires.

## Why mureo sits in the request path

Some official hosted MCPs are registered directly with your AI host,
which then connects and authenticates on its own. Amazon is bridged
through mureo instead for two reasons: the LwA credentials stay in
`~/.mureo/credentials.json` and never enter the host's own MCP
configuration, and the automatic refresh above only works with mureo in
the request path — it is what observes the failure, exchanges the
refresh token, and retries. The trade-off is that Amazon tools are
available only while the mureo MCP server is running.

## Caveats

- **No taxonomy remap:** tools keep Amazon's names (mureo does not
  rename official-MCP tools — same as Google/Meta official).
- **No deep mureo analytics:** the per-platform analysis keyed to
  mureo's native tool names does not exist for Amazon (tracked in
  #120). Amazon read findings are advisory.
- **Credentials exposure class** is identical to the Google developer
  token / Meta access token already stored in
  `~/.mureo/credentials.json`.
