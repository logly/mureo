# Amazon Ads (official-MCP bridge) — Phase 1

mureo connects to the **official Amazon Ads MCP** on your behalf, the
same way mureo-native Google/Meta work:

```
Claude  →  local mureo MCP  →  Amazon hosted MCP endpoint
```

Credentials live in `~/.mureo/credentials.json` (Claude never sees
them), and every Amazon tool call flows through mureo's audit /
throttle / strategy / rollback safety layer.

**Phase 1 scope (honest):** read-focused, the manifest-backed bridge
below. Amazon's own tool names are exposed as-is (no taxonomy remap) —
consistent with how mureo treats other official MCPs. Deep
per-platform analytics and LwA access-token auto-refresh are Phase 2.

## 1. Get Amazon credentials (you do this — mureo never enters them)

You need a **Login with Amazon (LwA) app** + an Amazon Developer
account with **Amazon Ads API** access. From those, obtain:

- `client_id` (the LwA application client id)
- `access_token` (an LwA access token; **expires** — see caveats)
- optionally `refresh_token` + `client_secret` (recorded for Phase 2
  auto-refresh; unused in Phase 1)

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
| `refresh_token`, `client_secret` | no | recorded for Phase 2 auto-refresh |
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

Re-run this command whenever you renew the access token or Amazon's
tool surface changes.

## 4. Restart Claude / the mureo MCP server

Amazon's tools now appear (under Amazon's own names, e.g.
`campaign_management-*`, `account_management-*`) and are audited +
strategy-gated like built-in platforms. Mutating calls are promoted
into `STATE.json` `action_log` (`platform=plugin:mureo-amazon-ads-bridge`)
with an observation window, exactly like the #114 plugin safety layer.

## Caveats

- **Token expiry:** the LwA access token expires. When it does, update
  `access_token` in `~/.mureo/credentials.json` and re-run
  `mureo amazon refresh-manifest`. Automatic LwA refresh is Phase 2.
- **No taxonomy remap:** tools keep Amazon's names (mureo does not
  rename official-MCP tools — same as Google/Meta official). Deep
  mureo analytics keyed to native tool names are Phase 2.
- **Credentials exposure class** is identical to the Google developer
  token / Meta access token already stored in
  `~/.mureo/credentials.json`.
