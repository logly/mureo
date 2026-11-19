---
name: _mureo-chatgpt-ads
description: "ChatGPT Ads (bundled provider over OpenAI's Advertiser API): read the ad account, campaigns, ad groups, ads, performance insights and the change history. Read-only."
metadata:
  version: 0.44.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo --help"
---

# ChatGPT Ads (bundled provider, read-only)
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, and
> output format — and specifically its **Plugin platforms (third-party
> providers)** section: ChatGPT Ads is served through the same provider path,
> so its honest scope applies. This file does not repeat it.

**Before you diagnose or change anything**: Run the **Diagnostic preamble** from ../_mureo-shared/SKILL.md — load learning insights (mureo_learning_insights_get) and consult advisors (mureo_consult_advisor) before drawing conclusions or making a change.

> **Canonical platform key: `plugin:mureo-chatgpt-ads:chatgpt_ads`.** Use it
> verbatim wherever a mureo surface names a platform — STATE.json
> `platforms`, `mureo_state_upsert_campaign(platform="plugin:mureo-chatgpt-ads:chatgpt_ads")`,
> `mureo_state_platform_metrics_set`, `mureo_analytics_*`. Joining on
> anything else (`chatgpt`, `chatgpt_ads`, `openai`) silently fails to join.

> **There is no `mureo chatgpt-ads …` CLI command.** Every operation below is
> an **MCP tool** (`chatgpt_ads_*`) — call it directly.

## What this surface is — and is not

- **Nine read-only tools** over OpenAI's Advertiser API, the API behind
  ChatGPT Ads. mureo calls the API itself; no other MCP server is involved.
- **No tool changes anything.** There is no create, update, pause, activate
  or budget tool yet. If the operator asks for a change, say it has to be made
  in Ads Manager for now; do not look for a write tool.
- **One API key = one ad account.** The key the operator configured selects
  the account, so no tool takes an account id. To report on another ad
  account, the operator has to configure that account's own key. The key
  belongs to the advertiser's own ad account.
- **Objects come back as the platform sent them.** The API is in beta and
  adds fields and enum values; read unknown ones as they are rather than
  treating them as errors.
- **mureo-only analyses do not exist here** (anomaly baselines, RSA audit,
  CV-mismatch). Treat findings as advisory and say so.

## Step 0 — confirm the account

Call `chatgpt_ads_account_get` first. It returns the account's `id`, `name`,
`status`, `timezone` and `currency_code`. Every report is in that currency and
that time zone; say which account you read.

## Which tool when

| Tool | Use it to |
|------|-----------|
| `chatgpt_ads_account_get` | Confirm the account, its currency and time zone |
| `chatgpt_ads_campaigns_list` | Find campaigns and their ids (`name` filter, `include_serving_issues`, `limit` default 50) |
| `chatgpt_ads_campaigns_get` | Read one campaign's objective, bidding type, budget, targeting and schedule; `include_serving_issues=true` to see why it is not delivering |
| `chatgpt_ads_ad_groups_list` | List one campaign's ad groups (`campaign_id` is required) |
| `chatgpt_ads_ad_groups_get` | Read one ad group's bid settings and serving issues |
| `chatgpt_ads_ads_list` | Find ads, optionally within one ad group; check review status across ads |
| `chatgpt_ads_ads_get` | See why one ad was rejected or is not serving, and what its creative says |
| `chatgpt_ads_insights_report` | Performance for a period |
| `chatgpt_ads_change_history_list` | Who changed what, before explaining a performance shift |

Lists follow the API's cursor until `limit` rows are collected (at most 1000)
and come back as one array; there is no cursor to pass back.

### Insights

- `period`: `today`, `yesterday`, `last_7d`, `last_14d`, `last_30d`
  (default), `last_90d`, `this_month`, `last_month`, or
  `YYYY-MM-DD..YYYY-MM-DD` (inclusive). `last_Nd` ends yesterday. Periods
  resolve in the **ad account's** time zone, not the operator's. At most 365
  days.
- Scope with at most one of `campaign_id` / `ad_group_id` / `ad_id` (none =
  the whole account). `level` (`account` | `campaign` | `ad_group` | `ad`)
  picks the row entity and must be at or below the scope; default `campaign`,
  or the scope's own level for an ad group or ad.
- `metrics`: delivery `impressions`, `clicks`, `spend`, `ctr`, `cpc`, `cpm`
  (the default set); conversion `conversions`, `cpa`, `post_click_cvr`,
  `order_created_attributed_sales`, `order_created_roas`. Ask for conversion
  metrics only over full days.
- `time_granularity`: `none` (default, one row per entity) or `daily` (one
  row per entity per day).
- `limit`: default 1000, the maximum. Rows beyond it are dropped without
  notice, so a daily report over many entities can come back short: when the
  row count equals `limit`, narrow the scope or the period and ask again.
- `attribution_window_days`: 7, 14 or 30 for the click window; omitted, the
  API default (30) applies.

### Change history

`chatgpt_ads_change_history_list` defaults to `last_7d` and can be narrowed to
one campaign, ad group or ad. Read it before attributing a performance change
to the market.

## Units — do not mix them

| Value | Unit |
|-------|------|
| Budgets and bid amounts in campaign / ad group objects | **micros** of the account currency: 1,000,000 = 1 unit (an amount of `50000000` is 50.00) |
| Insights `spend`, `cpc`, `cpm` | **major currency units** (12.50 = 12.50) |
| Insights `ctr` | a ratio |

Convert micros before comparing a budget with spend, and never convert
insights values a second time.

## Same-day data is provisional

Impressions and clicks can arrive within minutes; spend, CPC and CPM reflect
finalized activity and can arrive later; conversions take at least a day.

- Label `today` and `this_month` figures provisional, and do not compare a
  partial day or month with a complete one.
- Never conclude "conversions dropped" from today's or yesterday's rows.
- Use the returned `cpc` / `cpm`; dividing the latest spend by the latest
  clicks gives a different, wrong number.

## Relaying failures to the operator

| Result | What it means | Tell the operator |
|--------|---------------|-------------------|
| `"status": "auth_error"`, `"auth_cause": "no_credentials"` | No ChatGPT Ads API key is configured | Create an Ads API key on the Settings page in Ads Manager for their own ad account, then paste it in the **ChatGPT Ads** tab of `mureo configure` (or set `CHATGPT_ADS_API_KEY`). No restart is needed |
| `"status": "auth_error"`, `"auth_cause": "token_invalid"` | A key is configured and the API rejected it (wrong, revoked, or without access to the account) | Check the key in Ads Manager, issue a new one if needed, and save it in the same tab |
| `"status": "error"`, `"error": "feature_not_enabled"` | The account does not have that feature enabled | Relay `detail` as-is and say the feature has to be enabled for the account on the platform's side; mureo cannot enable it. Do not retry unchanged |
| Text starting `API error:` | Any other platform error, already retried where a retry could help (429 / 5xx) | Quote the message; for a 429 suggest waiting and narrowing the request |

An `auth_error` is not data: never render `detail` where a metric belongs and
never read the missing numbers as zero. Mark ChatGPT Ads as **not read** with
its `auth_cause`, and keep going with the other platforms.

A `ValueError` means the call itself was malformed (an unknown period, two
scope ids, a level above the scope, an unknown metric). Fix the arguments;
nothing was sent to the API.

## Important notes

- Read-only: nothing here writes to `action_log` or can be rolled back,
  because nothing is changed.
- The operator can switch the provider off with `MUREO_DISABLE_CHATGPT_ADS=1`;
  the `chatgpt_ads_*` tools are then absent from the session. Report the
  platform as not available rather than guessing.
- The server's `instructions` carry a ChatGPT Ads delivery-model line
  (auction-set CPC, billing by the ad group's billing event, micros,
  conversion delay). Follow it and do not carry over another platform's
  auction or bidding concepts.
- Full reference: `docs/chatgpt-ads.md`.
