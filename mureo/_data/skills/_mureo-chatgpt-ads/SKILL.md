---
name: _mureo-chatgpt-ads
description: "ChatGPT Ads (bundled provider over OpenAI's Advertiser API): read the ad account, spending limits, campaigns, ad groups, ads, performance insights and the change history; pause and activate, rename, reschedule, set budgets, bids and the account daily spending limit, each recorded with a reversal."
metadata:
  version: 0.44.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo --help"
---

# ChatGPT Ads (bundled provider)
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

- **Ten read tools and eleven change tools** over OpenAI's Advertiser API,
  the API behind ChatGPT Ads. mureo calls the API itself; no other MCP server
  is involved.
- **What can change:** pause and activate a campaign, ad group or ad; rename
  or reschedule a campaign; set a campaign's budget; rename an ad group; set
  an ad group's bidding config; set the account's daily spending limit.
  Nothing creates or archives an entity, edits a creative or targeting, or
  removes the account limit: for those, say the change has to be made in Ads
  Manager; do not look for another tool.
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
| `chatgpt_ads_account_spend_limits_get` | Read the account's spending limits, its daily rule and `revision` (invoice-billed accounts only) |

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

## Changing the account

Every change follows `_mureo-shared` → *Confirm Before Write Operations*:
show the operator the current value (read it first), the new value and the
tool, and get explicit approval. Pass `reason` and `expected` as for any
mutating tool. Which STRATEGY.md caps read which amounts is below; a cap
that does not read an amount does not bound it.

| Tool | Use it to |
|------|-----------|
| `chatgpt_ads_campaigns_pause` / `_enable` | Stop a campaign spending / make a paused one eligible to spend again |
| `chatgpt_ads_ad_groups_pause` / `_enable` | The same for an ad group |
| `chatgpt_ads_ads_pause` / `_enable` | The same for an ad |
| `chatgpt_ads_campaigns_update` | Rename a campaign or change `start_time` / `end_time` (Unix seconds; `null` clears) |
| `chatgpt_ads_campaigns_update_budget` | Set a campaign's `budget` |
| `chatgpt_ads_ad_groups_update` | Rename an ad group |
| `chatgpt_ads_ad_groups_update_bid` | Set an ad group's `bidding_config` |
| `chatgpt_ads_account_daily_spend_limit_set` | Set the account's daily spending limit (`amount_micros`) |

- **Budget and bidding objects are replaced whole.** Read the campaign or ad
  group first and send the complete object: a budget key left out is removed,
  and a new amount replaces the old one rather than adding to it. The
  platform rejects a lifetime budget below what is already spent.
- **A budget keeps its type.** `chatgpt_ads_campaigns_update_budget` reads
  the campaign first (one more request) and answers `"status": "refused"`,
  `"error": "budget_kind_change"` (or `budget_unreadable`), changing nothing,
  when the amounts sent differ from the ones the budget holds: send the same
  keys (a daily budget stays daily). Relay that the budget type has to be
  changed in Ads Manager.
- **Budget caps.** The daily and lifetime per-campaign caps read the budget
  amounts. Pass `current_daily_budget` and `projected_total_daily_budget` in
  **currency units, not micros** (75.0 is 75.00) on every budget change, so
  `max_daily_budget_increase_pct` and `max_total_daily_budget` can be checked;
  without them those two caps are not checked. They are never sent to the
  platform.
- **Bids.** `billing_event_type` (`impression` or `click`) is required. With
  impression billing the bid is per impression, not per thousand: CPM / 1000.
  Omitting both `strategy` and `max_bid_micros` selects automatic bidding,
  which reads back as `automated_bid`. `max_cpc_bid_per_ad_group` reads
  `max_bid_micros` only: audience multipliers (up to 10x) and the strategies
  without a bid are not bounded by it, and with impression billing the amount
  is per impression (CPM = amount × 1000). The campaign budget is what bounds
  spend; say so when a change raises multipliers or switches strategy.
- **Account daily limit.** Invoice-billed accounts only. mureo reads the
  current `revision` first; with more than one daily rule it answers
  `"status": "refused"`, `"error": "multiple_daily_spend_limits"` and changes
  nothing: relay that the limits have to be edited in Ads Manager. A
  decrease below the spend already counted today is rejected.
  `max_daily_budget_per_campaign` also holds this account-wide amount.
- **Recorded and reversible.** With a `STATE.json` in the working directory,
  each change lands in `action_log` with a reversal that `rollback_apply`
  can run (pause ↔ enable, or the same tool with the prior values). No
  reversal is recorded when the prior state could not be read, when a prior
  value would fail the tool's own check (a budget, bidding config or ad group
  name is restored whole or not at all; a campaign update leaves such a field
  out and says so), or when the change was a no-op (pausing a campaign that
  was not active). An account-limit
  change names no campaign, ad group or ad.
- **No learning-period rules.** `mureo_learning_reset_preflight` answers
  `unknown` for these tools; do not claim a change will or will not reset
  learning.

## Units — do not mix them

| Value | Unit |
|-------|------|
| Budgets and bid amounts in campaign / ad group objects, spending limits, and every amount a change tool takes | **micros** of the account currency: 1,000,000 = 1 unit (an amount of `50000000` is 50.00) |
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
| Text starting `API error:` | Any other platform error, already retried where a retry could help (429 / 5xx on reads, 429 on changes) | Quote the message; for a 429 suggest waiting and narrowing the request |
| Text ending `The change may have been applied; read the entity before retrying.` | A change ended in a 5xx, an unreadable success answer, a transport error or the deadline, after the request may have reached the platform | Read the entity with its `*_get` tool and report what it shows; never repeat the change blind |

An `auth_error` is not data: never render `detail` where a metric belongs and
never read the missing numbers as zero. Mark ChatGPT Ads as **not read** with
its `auth_cause`, and keep going with the other platforms.

A `ValueError` means the call itself was malformed (an unknown period, two
scope ids, a level above the scope, an unknown metric). Fix the arguments;
nothing was sent to the API.

## Important notes

- Read tools write nothing to `action_log`. A change tool that fails is not
  recorded either; a change recorded without a reversal has to be undone by
  hand with the matching change tool.
- The operator can switch the provider off with `MUREO_DISABLE_CHATGPT_ADS=1`;
  the `chatgpt_ads_*` tools are then absent from the session. Report the
  platform as not available rather than guessing.
- The server's `instructions` carry a ChatGPT Ads delivery-model line
  (auction-set CPC, billing by the ad group's billing event, micros,
  conversion delay). Follow it and do not carry over another platform's
  auction or bidding concepts.
- Full reference: `docs/chatgpt-ads.md`.
