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
- `client_secret` (the LwA application client secret) — required for
  the authorization wizard below, and for the automatic access-token
  refresh afterwards

One more setting in the LwA security profile: add your **return URL**
to *Allowed Return URLs* (Login with Amazon → your Security Profile →
Web Settings). The documented direct-advertiser pattern is any valid
URL you control — mureo defaults to `https://amazon.com`, so adding
exactly that is enough. Consent redirects there and you copy the code
out of the address bar; nothing is served on it.

You do **not** have to obtain a `refresh_token` by hand — the wizard in
step 2 mints one for you.

## 2. Set up in the configure UI (recommended)

```bash
mureo configure
```

That opens the local configuration UI in your browser (bound to
`127.0.0.1`). Then:

1. Open the **dashboard** and scroll to the **Plugin credentials**
   section.
2. Find the **Amazon Ads** card.
3. Fill in **Client ID** and **Client Secret**.
4. Optionally set **Region** (`na` / `eu` / `fe`, default `na`) and
   **Account Mode** (`dynamic` / `fixed`, default `dynamic`). In
   `fixed` mode also fill at least one of **Profile ID**, **Account
   ID**, **Manager Account ID**.
5. Click **Save**.
6. In the **Authorize with Amazon** block below the form, click
   **Open Amazon consent page**. Amazon opens in a new tab.
7. Approve access. Amazon redirects you to your return URL — an
   ordinary page, possibly a 404. That is expected.
8. Copy the **full address** from the browser's address bar (it looks
   like `https://amazon.com/?code=ANxxxxx&scope=…`) and paste it into
   **Redirected address**, then click **Finish authorization**. Pasting
   just the `code=` value works too.

> Copy the address **as-is** — mureo reads the `code` parameter out of
> it. Don't retype or trim it: a hand-edited URL is the usual reason an
> exchange fails with "no code".

mureo exchanges the code for an access token **and** a refresh token,
stores both, and refreshes the tool list in the same step. The
authorization code is valid for **5 minutes** — if you take longer,
just click **Open Amazon consent page** again.

The same **Authorize with Amazon** block appears in the setup wizard's
Amazon step, right after you save the credentials there.

The values land in the `amazon_ads` section of
`~/.mureo/credentials.json` at `0o600`. Secret fields are write-only in
the form: leaving one blank on a later edit **keeps** the stored value
rather than clearing it, so you never have to re-type a token to change
the region.

> **What kind of wizard this is.** Amazon's direct-advertiser consent
> has no loopback callback for a local tool to listen on, so this is a
> guided **paste-code** flow, not the one-click redirect-back flow the
> Google / Meta cards use: mureo builds the consent URL and opens it,
> you paste the redirected address back. Everything after the paste is
> automatic.

Already hold a `refresh_token` from somewhere else? Paste it (with the
client secret) into the card's **Refresh Token** field instead and skip
the authorization block — see [manual authorization](#appendix-manual-authorization-fallback)
for the terminal-only route.

Then continue with step 5 (build the tool manifest) — or skip it: the
authorization wizard already refreshed the tool list for you.

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
| `refresh_token_obtained_at` | no | Written by the authorization wizard: ISO 8601 UTC timestamp of the consent that produced the current refresh token. Metadata, not a credential — it drives the re-authorization reminder below. Absent = unknown, and unknown is never warned about |

## 5. Build the tool manifest

```bash
mureo amazon refresh-manifest
```

This connects once (authenticated), lists Amazon's MCP tools, and
writes `amazon_tools.json` **beside your credentials file** —
`~/.mureo/amazon_tools.json` in a standard install. The mureo MCP server
reads that file **at start** (pure, no network, no credentials) to
expose the Amazon tools — so a missing manifest simply means "no Amazon
tools", never a startup failure.

> The manifest always follows the credentials file. If a host plugin
> relocates `credentials.json` (a multi-tenant runtime context), the
> manifest moves with it and every reader — the bridge, this CLI, the
> `mureo configure` dashboard — resolves the same single location.

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

## Refresh tokens expire too (365 days)

Amazon's LwA refresh tokens are long-lived but **not permanent**:

- Refresh tokens issued **on or after 2026-07-30** expire **365 days
  after the advertiser consented**.
- Tokens issued **before** that have no fixed expiry, so there is no
  countdown to show for them.

Amazon does not tell a client when a token was issued, so mureo records
it itself: the authorization wizard writes
`amazon_ads.refresh_token_obtained_at` (ISO 8601, UTC) at the moment of
the exchange. The dashboard's Amazon card then shows a **re-authorize
hint** once that token passes **335 days** — 30 days of headroom before
Amazon revokes it mid-operation.

If the stamp is absent (a setup that predates the wizard, or a refresh
token you pasted in by hand), mureo shows **nothing**: an unknown issue
date could belong to a pre-2026-07-30 token that never expires, and
warning about it annually would be false.

When a refresh token does die, Amazon answers the token exchange with
`invalid_grant` and mureo says so explicitly. There is nothing mureo can
do automatically at that point.

To re-authorize (before or after it dies):

1. Open the **Amazon Ads** card in `mureo configure` and run the
   **Authorize with Amazon** flow again (step 2 above). The new tokens
   and a fresh `refresh_token_obtained_at` replace the old ones.
2. Or, without the UI: obtain a **new** `refresh_token` (see the
   [manual appendix](#appendix-manual-authorization-fallback)) and
   paste it into the card's **Refresh Token** field / update
   `AMAZON_ADS_REFRESH_TOKEN` / `~/.mureo/credentials.json`. The next
   Amazon tool call mints a fresh access token from it automatically.
3. Re-run `mureo amazon refresh-manifest` too if Amazon's tool surface
   has changed since (the UI flow does this for you).

## Why mureo sits in the request path

Some official hosted MCPs are registered directly with your AI host,
which then connects and authenticates on its own. Amazon is bridged
through mureo instead for two reasons: the LwA credentials stay in
`~/.mureo/credentials.json` and never enter the host's own MCP
configuration, and the automatic minting/refresh above only works with
mureo in the request path — it is what observes the failure, exchanges
the refresh token, and retries. The trade-off is that Amazon tools are
available only while the mureo MCP server is running.

## Appendix: manual authorization (fallback)

The configure UI does exactly this for you; here it is in full for
terminal-only setups, containers, and debugging. Both steps use the
regional hosts:

| Region | Authorize prefix | Token endpoint |
|--------|------------------|----------------|
| `na` | `https://www.amazon.com/ap/oa` | `https://api.amazon.com/auth/o2/token` |
| `eu` | `https://eu.account.amazon.com/ap/oa` | `https://api.amazon.co.uk/auth/o2/token` |
| `fe` | `https://apac.account.amazon.com/ap/oa` | `https://api.amazon.co.jp/auth/o2/token` |

1. Open this URL in a browser (one line, `redirect_uri` must be in your
   security profile's Allowed Return URLs):

   ```
   https://www.amazon.com/ap/oa?client_id=YOUR_CLIENT_ID&scope=advertising::campaign_management&response_type=code&redirect_uri=https%3A%2F%2Famazon.com
   ```

2. Approve access, then copy the `code=` value out of the address bar
   you are redirected to. **It expires in 5 minutes.**

3. Exchange it (within those 5 minutes):

   ```bash
   curl -X POST https://api.amazon.com/auth/o2/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "grant_type=authorization_code" \
     -d "code=THE_CODE" \
     -d "redirect_uri=https://amazon.com" \
     -d "client_id=YOUR_CLIENT_ID" \
     -d "client_secret=YOUR_CLIENT_SECRET"
   ```

   The response carries `access_token` (`Atza|…`), `refresh_token`
   (`Atzr|…`) and `expires_in`.

4. Put `refresh_token` (and `client_secret`) into the `amazon_ads`
   section — via the configure card, the `AMAZON_ADS_*` env vars, or by
   hand. Optionally add `refresh_token_obtained_at` with the current
   UTC timestamp (e.g. `2026-07-31T09:15:00+00:00`) so the
   re-authorization reminder can count from the right day; leave it out
   and mureo simply stays quiet about the expiry.

5. Run `mureo amazon refresh-manifest` once.

## Caveats

- **Paste-code authorization, not a redirect-back wizard:** Amazon's
  direct-advertiser consent has no loopback callback, so the configure
  UI opens Amazon's consent page and you paste the redirected address
  back. That is the only shape difference from the Google / Meta cards
  — the tokens are obtained, stored and refreshed for you either way.
- **No taxonomy remap:** tools keep Amazon's names (mureo does not
  rename official-MCP tools — same as Google/Meta official).
- **No deep mureo analytics:** the per-platform analysis keyed to
  mureo's native tool names does not exist for Amazon (tracked in
  #120). Amazon read findings are advisory.
- **Credentials exposure class** is identical to the Google developer
  token / Meta access token already stored in
  `~/.mureo/credentials.json`.
