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
minting and auto-refresh are built in (see below). Deep per-platform
analytics keyed to Amazon's native tool names are **not** available yet
(tracked in #120) — treat Amazon findings as advisory.

## 1. Get Amazon credentials (you do this — mureo never enters them)

You need a **Login with Amazon (LwA) app** + an Amazon Developer
account with **Amazon Ads API** access. From those, obtain:

- `client_id` (the LwA application client id) — always required
- `refresh_token` + `client_secret` — **recommended**: together they
  let mureo mint and refresh the short-lived access token for you, so
  there is nothing to paste again later
- `access_token` — optional when you have the pair above. It is an LwA
  access token that **expires after ~60 minutes**; supply it only if
  you are not using a refresh token, in which case you must paste a
  fresh one by hand each time.

## 2. Set up in the configure UI (recommended)

```bash
mureo configure
```

That opens the local configuration UI in your browser (bound to
`127.0.0.1`). Then:

1. Open the **dashboard** and scroll to the **Plugin credentials**
   section.
2. Find the **Amazon Ads** card.
3. Fill in **Client ID**, plus either **Refresh Token** + **Client
   Secret** (recommended) or **Access Token**.
4. Optionally set **Region** (`na` / `eu` / `fe`, default `na`) and
   **Account Mode** (`dynamic` / `fixed`, default `dynamic`). In
   `fixed` mode also fill at least one of **Profile ID**, **Account
   ID**, **Manager Account ID**.
5. Click **Save**.

The values land in the `amazon_ads` section of
`~/.mureo/credentials.json` at `0o600`. Secret fields are write-only in
the form: leaving one blank on a later edit **keeps** the stored value
rather than clearing it, so you never have to re-type a token to change
the region.

> The Amazon browser sign-in wizard (one-click OAuth consent) is not
> built yet — the card is a form you paste into. That is the only
> difference from the Google / Meta cards.

Then continue with step 4 (build the tool manifest).

## 3. Alternative: environment variables

If you deploy mureo in a container or CI and would rather not ship a
credentials file, set these instead. The `amazon_ads` section of
`~/.mureo/credentials.json` **wins** when it holds a usable
combination; the environment is only consulted as a fallback (same rule
as Google and Meta).

| Variable | Required | Notes |
|----------|----------|-------|
| `AMAZON_ADS_CLIENT_ID` | yes | LwA application client id |
| `AMAZON_ADS_REFRESH_TOKEN` | see below | LwA refresh token (`Atzr\|…`) |
| `AMAZON_ADS_CLIENT_SECRET` | see below | LwA application client secret |
| `AMAZON_ADS_ACCESS_TOKEN` | see below | LwA access token (`Atza\|…`) |
| `AMAZON_ADS_REGION` | no (default `na`) | `na` / `eu` / `fe` — picks the endpoint |
| `AMAZON_ADS_ACCOUNT_MODE` | no (default `dynamic`) | `dynamic` or `fixed` |
| `AMAZON_ADS_PROFILE_ID` | no | **Fixed** mode only |
| `AMAZON_ADS_ACCOUNT_ID` | no | **Fixed** mode only |
| `AMAZON_ADS_MANAGER_ACCOUNT_ID` | no | **Fixed** mode only |

"See below" = `AMAZON_ADS_CLIENT_ID` plus **either**
`AMAZON_ADS_ACCESS_TOKEN` **or both** of `AMAZON_ADS_REFRESH_TOKEN` and
`AMAZON_ADS_CLIENT_SECRET`. Anything less and mureo reports Amazon as
not configured.

## 4. Fallback: edit `~/.mureo/credentials.json` by hand

Everything the UI and the environment variables do is just this
section, so hand-editing still works:

```json
{
  "amazon_ads": {
    "client_id": "amzn1.application-oa2-client.xxxxx",
    "refresh_token": "Atzr|xxxxx",
    "client_secret": "amzn1.oa2-cs.v1.xxxxx",
    "region": "na",
    "account_mode": "dynamic"
  }
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `client_id` | yes | LwA application client id |
| `refresh_token` + `client_secret` | recommended | both together enable automatic access-token minting + refresh |
| `access_token` | only without the pair above | LwA access token (`Atza\|…`), expires in ~60 min |
| `region` | no (default `na`) | `na` / `eu` / `fe` — picks the endpoint |
| `account_mode` | no (default `dynamic`) | `dynamic` (LLM is asked per call) or `fixed` |
| `profile_id`, `account_id`, `manager_account_id` | no | **Fixed** mode only (≥1 required to engage Fixed) |

## 5. Build the tool manifest

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

## 6. Restart Claude / the mureo MCP server

Amazon's tools now appear (under Amazon's own names, e.g.
`campaign_management-*`, `account_management-*`) and are audited +
strategy-gated like built-in platforms. Mutating calls are promoted
into `STATE.json` `action_log` (`platform=plugin:mureo-amazon-ads-bridge`)
with an observation window, exactly like the #114 plugin safety layer.

## Access tokens (minted and refreshed for you)

When **both** `refresh_token` and `client_secret` are present, you never
have to touch `access_token`:

- **First use.** With no `access_token` stored, mureo performs one
  Login-with-Amazon exchange (`grant_type=refresh_token` against the
  regional token host) *before* the first forwarded call, writes the
  minted token into `~/.mureo/credentials.json`, and proceeds.
- **Expiry (~60 minutes).** On the first failure of an Amazon tool call
  mureo performs exactly one refresh, persists the new token, and
  retries the call once.

Either way it is **one LwA exchange per dispatch, never a loop**, and
tokens/secrets never appear in error messages or logs.

- If `~/.mureo/credentials.json` cannot be written (most often because
  it is malformed — mureo refuses to overwrite a corrupt file and lose
  your other providers' credentials), the call fails with that reason
  rather than a silent retry loop.
- `mureo amazon refresh-manifest` mints a token the same way: if no
  `access_token` is stored and `refresh_token` + `client_secret` are,
  it performs one LwA exchange, saves the token, and then generates the
  manifest. So the refresh-token-only setup works from the very first
  command — no need to paste an access token just to discover the
  tools. (It does not *re-*mint an already-stored token that has since
  expired; if the command fails with a 401, run it again after a tool
  call has refreshed the token, or clear `access_token` to force a
  fresh mint.)

Without `refresh_token` + `client_secret`, update `access_token` (in
the configure UI's Amazon Ads card, via `AMAZON_ADS_ACCESS_TOKEN`, or
in `~/.mureo/credentials.json`) by hand when it expires.

## Refresh tokens expire too (about once a year)

Amazon's LwA refresh tokens are long-lived but **not permanent** —
plan on re-authorizing roughly annually. When a refresh token dies,
Amazon answers the token exchange with `invalid_grant` and mureo says
so explicitly, telling you to re-authorize. There is nothing mureo can
do automatically at that point.

To recover:

1. Re-authorize your LwA app with Amazon and obtain a **new**
   `refresh_token`.
2. Paste it into the **Refresh Token** field of the Amazon Ads card in
   `mureo configure` (or update `AMAZON_ADS_REFRESH_TOKEN` /
   `~/.mureo/credentials.json`) and save.
3. The next Amazon tool call mints a fresh access token from it
   automatically. Re-run `mureo amazon refresh-manifest` too if
   Amazon's tool surface has changed since.

## Why mureo sits in the request path

Some official hosted MCPs are registered directly with your AI host,
which then connects and authenticates on its own. Amazon is bridged
through mureo instead for two reasons: the LwA credentials stay in
`~/.mureo/credentials.json` and never enter the host's own MCP
configuration, and the automatic minting/refresh above only works with
mureo in the request path — it is what observes the failure, exchanges
the refresh token, and retries. The trade-off is that Amazon tools are
available only while the mureo MCP server is running.

## Caveats

- **No browser sign-in yet:** the configure UI's Amazon card is a paste
  form. The one-click OAuth consent wizard the Google / Meta cards have
  is a later change.
- **No taxonomy remap:** tools keep Amazon's names (mureo does not
  rename official-MCP tools — same as Google/Meta official).
- **No deep mureo analytics:** the per-platform analysis keyed to
  mureo's native tool names does not exist for Amazon (tracked in
  #120). Amazon read findings are advisory.
- **Credentials exposure class** is identical to the Google developer
  token / Meta access token already stored in
  `~/.mureo/credentials.json`.
