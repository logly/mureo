# ChatGPT Ads (bundled provider)

mureo reads and changes **ChatGPT Ads** accounts through OpenAI's
**Advertiser API**, the API behind ChatGPT Ads. The provider ships inside
mureo (`mureo/chatgpt_ads/`) and is served through the provider path, the
same one the Amazon Ads bridge
and third-party provider plugins use:

```
Claude  →  local mureo MCP  →  https://api.ads.openai.com/v1
```

The Ads API key stays in mureo's credential store (Claude never sees it), and
every call goes through mureo's plugin safety layer: the audit trail and the
per-tool throttle, and for the tools that change the account also the
`action_log` record, rollback and the STRATEGY.md caps on the amounts each
tool declares (which amounts those are is under [Units](#units)).

**Scope:** ten read tools (the ad account, its spending limits, campaigns, ad
groups, ads, insights and the change history) and eleven tools that change the
account: pause and activate a campaign, ad group or ad, rename or reschedule a
campaign, set a campaign's budget, rename an ad group, set an ad group's
bidding config, and set the account's daily spending limit. Creating entities
is tracked in #995. The API is in beta and adds fields often, so every object
and row is returned as the platform sent it, with unknown fields and enum
values left as they are.

## 1. Create an Ads API key

Create the key on the **Settings page in Ads Manager**, for your own ad
account. One key is scoped to one ad account: mureo reads the account the key
belongs to, and `chatgpt_ads_account_get` tells you which one that is.

The Advertiser API key is not the same as an OpenAI platform API key. mureo
never reads `OPENAI_API_KEY` (which Creative Studio uses for image
generation) for ChatGPT Ads.

## 2. Give the key to mureo

```bash
mureo configure
```

Paste the key into the **Ads API key** field of the **ChatGPT Ads** tab in the
dashboard's **Connection credentials** section and save. The value is stored in the `chatgpt_ads` section of
`~/.mureo/credentials.json`:

```json
{
  "chatgpt_ads": {
    "api_key": "..."
  }
}
```

The field is a secret field: it shows ✓ Configured / ✗ Not set, the input is
always empty, and saving it blank keeps the stored value. The tools are listed
whether or not a key is stored, and the key is read on every call, so saving
it needs no MCP server restart.

### Environment variable

| Variable | Required | Notes |
|----------|----------|-------|
| `CHATGPT_ADS_API_KEY` | when nothing is stored | Read only when the `chatgpt_ads` section holds no usable key |

A blank or whitespace-only value counts as absent in both places.

### Switching the provider off

The provider is registered by default. Set `MUREO_DISABLE_CHATGPT_ADS=1` (the
exact string `1`) before starting the MCP server or `mureo configure` to leave
it out entirely: no ChatGPT Ads tools are listed, no credential card is shown,
and the server's `instructions` carry no ChatGPT Ads delivery-model line (see
[What the agent is told](#what-the-agent-is-told)).

## Tools

Every tool takes no account argument (the key selects the account) and
rejects arguments its schema does not declare. The read tools carry
`readOnlyHint`; the tools that change the account are listed under
[Changes](#changes).

| Tool | API | Arguments (defaults) |
|------|-----|----------------------|
| `chatgpt_ads_account_get` | `GET /ad_account` | *(none)* |
| `chatgpt_ads_account_spend_limits_get` | `GET /ad_account/spend_limit_windows` | *(none)* |
| `chatgpt_ads_campaigns_list` | `GET /campaigns` | `name`, `include_serving_issues` (false), `limit` (50) |
| `chatgpt_ads_campaigns_get` | `GET /campaigns/{campaign_id}` | `campaign_id` (required), `include_serving_issues` (false) |
| `chatgpt_ads_ad_groups_list` | `GET /ad_groups` | `campaign_id` (required), `name`, `limit` (50) |
| `chatgpt_ads_ad_groups_get` | `GET /ad_groups/{ad_group_id}` | `ad_group_id` (required) |
| `chatgpt_ads_ads_list` | `GET /ads` | `ad_group_id`, `name`, `limit` (50) |
| `chatgpt_ads_ads_get` | `GET /ads/{ad_id}` | `ad_id` (required) |
| `chatgpt_ads_insights_report` | `GET /ad_account/insights`, `/campaigns/{id}/insights`, `/ad_groups/{id}/insights`, `/ads/{id}/insights` | `period` (`last_30d`), `level` (`campaign`), at most one of `campaign_id` / `ad_group_id` / `ad_id`, `time_granularity` (`none`), `metrics` (delivery set), `attribution_window_days` (API default), `limit` (1000) |
| `chatgpt_ads_change_history_list` | `GET /audit_logs` | `period` (`last_7d`), `campaign_id`, `ad_group_id`, `ad_id`, `limit` (50) |

- **Ids** (`campaign_id`, `ad_group_id`, `ad_id`) must match
  `^[A-Za-z0-9_-]{1,128}$`; anything else is refused before a request is
  sent.
- **`include_serving_issues`** adds `include[]=serving_issues`, the
  platform's reasons a campaign is not delivering.
- **`name`** is 3 to 1000 characters on one line (no line break anywhere)
  and not all spaces.
- **`limit`** is 1 to 1000. The list tools follow the API's cursor
  (`has_more` / `last_id` → `after`) until that many rows are collected and
  return one flat JSON array; no cursor is returned. Rows beyond `limit` are
  dropped without notice, so a daily insights report, which returns one row
  per entity per day, needs a `limit` of at least entities × days.
- **Single gets** return the platform object unchanged.
- **`chatgpt_ads_account_spend_limits_get`** returns the account's spending
  limits unchanged: the date-range limits, the active or upcoming daily rule
  (`daily_limit` / `daily_limits`, with spent and remaining micros), the
  `revision` and the earliest allowed start dates. It answers only for
  accounts on invoice billing and keys that may manage billing.

### Changes

| Tool | API | Arguments |
|------|-----|-----------|
| `chatgpt_ads_campaigns_pause` / `_enable` | `POST /campaigns/{campaign_id}/pause` / `/activate` | `campaign_id` (required) |
| `chatgpt_ads_ad_groups_pause` / `_enable` | `POST /ad_groups/{ad_group_id}/pause` / `/activate` | `ad_group_id` (required) |
| `chatgpt_ads_ads_pause` / `_enable` | `POST /ads/{ad_id}/pause` / `/activate` | `ad_id` (required) |
| `chatgpt_ads_campaigns_update` | `POST /campaigns/{campaign_id}` | `campaign_id` (required), at least one of `name`, `start_time`, `end_time` |
| `chatgpt_ads_campaigns_update_budget` | `GET /campaigns/{campaign_id}`, then `POST /campaigns/{campaign_id}` | `campaign_id`, `budget` (both required), `current_daily_budget`, `projected_total_daily_budget` |
| `chatgpt_ads_ad_groups_update` | `POST /ad_groups/{ad_group_id}` | `ad_group_id`, `name` (both required) |
| `chatgpt_ads_ad_groups_update_bid` | `POST /ad_groups/{ad_group_id}` | `ad_group_id`, `bidding_config` (both required) |
| `chatgpt_ads_account_daily_spend_limit_set` | `GET /ad_account/spend_limit_windows`, then `POST /ad_account/daily_spend_limit` | `amount_micros` (required) |

Each tool returns the platform's answer unchanged: the updated campaign, ad
group or ad, or, for the account limit, the account's spending limits after
the change. Archiving is not available; use Ads Manager. Budget and bid edits
are tools of their own, not fields of the general update tools, because
mureo reads the kind of a recorded change off its tool name when it matches a
platform's change history against `action_log`
(`mureo_external_changes_import`): a budget change recorded under a generic
campaign-edit name could never be recognised as mureo's own budget change.

- **Pause and activate** send no body. `enable` makes the entity eligible to
  spend again.
- **`name`** is 3 to 1000 characters on one line (no line break anywhere)
  and not all spaces.
- **`start_time` / `end_time`** are Unix seconds from 946684800 (2000-01-01)
  to 4102444800 (2100-01-01), or `null` to clear that end. A key that is
  present, even as `null`, is changed; a key left out is left as it is.
- **`budget`** is the complete new budget object: `daily_spend_limit_micros`
  and/or `lifetime_spend_limit_micros`, each at least 1000000 and nothing
  else. The platform replaces the whole object, so a key left out is removed,
  and an amount replaces the old one rather than adding to it. The platform
  rejects a lifetime budget below the amount already spent.
- **The budget type cannot change.** The tool reads the campaign first (one
  more request) and compares the amounts its budget holds (a value other than
  `null`) with the keys sent. When they differ (a daily budget sent as a
  lifetime one, or a second amount added or one dropped) it changes nothing
  and returns `{"status": "refused", "error": "budget_kind_change", ...}`,
  naming both sets of keys; when the current budget holds neither amount it
  returns the same refusal with `budget_unreadable`. Change the budget type in
  Ads Manager. A budget sent without `daily_spend_limit_micros` would delete
  the campaign's daily limit, which no daily cap sees.
- **`current_daily_budget` / `projected_total_daily_budget`** are optional
  numbers of at least 0 in **account-currency units** (75.0 is 75.00), not
  micros: the campaign's current daily budget and the account's total daily
  budget across campaigns after the change. They are mureo's cross-provider
  budget context keys: the STRATEGY.md caps `max_daily_budget_increase_pct`
  and `max_total_daily_budget` read them, and without them those two caps
  cannot be checked. They are checked and never sent to the platform, and a
  reversal does not carry them.
- **`bidding_config`** is the complete new bidding config, which the platform
  also replaces as a whole: `billing_event_type` (`impression` or `click`,
  required), `strategy` (`fixed_bid`, `maximize_clicks` or
  `maximize_conversions`), `max_bid_micros` (1 to 30400000000000) and
  `custom_audience_bid_multipliers` (items of `custom_audience_id` and
  `bid_multiplier_micros`, 100000 to 10000000, where 1000000 is 1.0x).
  Omitting both `strategy` and `max_bid_micros` selects automatic bidding,
  which responses report as `automated_bid`. With impression billing the bid
  is per impression, not per thousand: CPM / 1000.
- **What the bid cap covers.** `max_cpc_bid_per_ad_group` reads
  `max_bid_micros` only. Audience bid multipliers (up to 10x) and the
  strategies without a bid (automatic bidding, `maximize_clicks`,
  `maximize_conversions`) are not bounded by it, and with impression billing
  the amount is per impression (CPM = amount × 1000), so a per-click cap does
  not meaningfully constrain it. The campaign budget is what bounds spend.
- **`amount_micros`** is an integer of at least 0, in multiples of the
  currency's smallest unit. The STRATEGY.md cap
  `max_daily_budget_per_campaign` also holds this amount, although the limit
  is account-wide: mureo's policy gate reads an `amount_micros` argument as a
  daily budget in micros, declared or not.

Every argument is checked before the first request; a bool or a float where
an integer is expected is refused.

### The account daily spending limit

The account limit is shared by every campaign and renews at midnight in the
account's time zone. The platform offers it only to accounts on invoice
billing, and only to keys that may manage billing; otherwise the answer is
`feature_not_enabled` or an API error. A decrease below the spend already
counted for the day is rejected by the platform
(`budget_window_amount_below_spend`).

`chatgpt_ads_account_daily_spend_limit_set` first reads the spending limits.
The request form it sends has no window id, so it cannot say which of several
daily rules it means: with more than one active or upcoming rule it changes
nothing and returns
`{"status": "refused", "error": "multiple_daily_spend_limits", "detail": ...}`,
pointing to Ads Manager. Otherwise it sends the amount with
`expected_revision` set to the `revision` it read (0 when the answer carries
none), so a change made in between is not silently overwritten. Before any
write it also stops, with an API error that says nothing was changed, when the
answer is not a JSON object or carries a `revision` that is not a whole number
of at least 0. A non-empty `daily_limits` array is the list of rules;
otherwise the single `daily_limit` is (absent or `null` = none).

### Recorded changes and rollback

When the MCP server runs in a directory with a `STATE.json`, each change is
recorded in its `action_log` under the tool name, with the entity it touched
(`campaign_id`, an ad group's id or `ad_id`). An account-level spend-limit
change carries no entity identity, so its entry names no campaign, ad group
or ad. A call that ended in an error is not recorded.

Before the change is sent, mureo reads the prior state with one of the read
tools, run like any tool call and bounded by 15 seconds in total (it can retry
inside that, see [Limits](#limits)), and records a reversal that
`rollback_apply` can run. Every value a reversal carries has passed the same
check the reversal's tool runs on its arguments, so a recorded reversal is one
the tool accepts:

| Change | Reversal recorded | No reversal when |
|--------|-------------------|------------------|
| pause | the matching `_enable` | the entity was not `active` before (already paused, archived, ...) |
| enable | the matching `_pause` | the entity was not `paused` before |
| `chatgpt_ads_campaigns_update` | the same tool with the prior value of each field the call set | no field's prior value passes the tool's check |
| `chatgpt_ads_campaigns_update_budget` | the same tool with every prior budget amount that is not `null` | the prior budget holds neither amount, or any amount it holds fails the tool's check (a string, a float, 0 or another value below 1000000) |
| `chatgpt_ads_ad_groups_update` | the same tool with the prior name | the prior name is missing or fails the tool's check |
| `chatgpt_ads_ad_groups_update_bid` | the same tool with the prior bidding config | anything present in the prior config fails the tool's check: a `billing_event_type` other than `impression` or `click`, a strategy that is neither one the tool takes nor `automated_bid`, an unusable `max_bid_micros` or multiplier, or more than 1000 multipliers |
| `chatgpt_ads_account_daily_spend_limit_set` | the same tool with the prior amount | there was no daily rule before (removing a limit is a different operation), more than one, or its amount fails the tool's check |

For a campaign update, a field whose prior value fails the check is left out
of the reversal and named in its caveats, and `rollback_plan_get` reports the
plan as partial. A budget, a bidding config and an ad group name are restored
whole or not at all: the platform replaces the whole budget and bidding
objects, so a partial one would remove a limit or a multiplier. A budget
reversal that sets a lower lifetime budget than the call did carries the
caveat that the platform rejects a lifetime budget below the amount already
spent. A prior `automated_bid` config is restored without `strategy` or
`max_bid_micros`; a `null` value is treated as absent, and response-only keys
are not restored. If the prior read fails or times out, the change goes ahead
without a reversal; only the error's type is logged.

No learning-period reset rules are registered for ChatGPT Ads: the platform's
documentation states none, so `mureo_learning_reset_preflight` reports the
reset risk of these tools as `unknown`.

### Insights

- **Scope and level.** The scope id picks the endpoint (none = the whole
  account). `level` (`account` | `campaign` | `ad_group` | `ad`) picks the row
  entity and must be at or below the scope. The default is `campaign`, or the
  scope's own level when scoped to an ad group or an ad.
- **Metrics.** Delivery metrics: `impressions`, `clicks`, `spend`, `ctr`,
  `cpc`, `cpm` (the default set). Conversion metrics: `conversions`, `cpa`,
  `post_click_cvr`, `order_created_attributed_sales`, `order_created_roas`.
  Any other name, or a name given twice, is refused. Each row also carries the entity's id and name,
  and `readable_time` when `time_granularity` is `daily`.
- **Granularity.** `none` (one row per entity for the whole window) or
  `daily`. mureo always sends one of the two, so the API's own default
  (`daily`) never applies.
- **Attribution.** `attribution_window_days` (7, 14 or 30) sets the click
  window for conversion metrics; omitted, the API default (30) applies. The
  view-through window is not exposed, so the API default (1 day) applies to
  it.

### Change history

`chatgpt_ads_change_history_list` returns audit-log entries unchanged (`id`,
`ts`, `actor_id`, `actor_type`, `audit_log_type`, `obj_type`, `obj_id`,
`item_name`, `changes`). `period` is sent as `start_time` / `end_time` in Unix
seconds: from midnight of the first day to the last second of the last day, in
the ad account's time zone.

## Periods and time zone

`period` takes the same vocabulary as the Meta Ads tools: `today`,
`yesterday`, `last_7d`, `last_14d`, `last_30d`, `last_90d` (N complete days
ending yesterday), `this_month`, `last_month`, or an explicit
`YYYY-MM-DD..YYYY-MM-DD` (both ends inclusive).

Relative values resolve against **today in the ad account's time zone**, the
`timezone` that `GET /ad_account` returns, because the API reads a date range
in that zone. Near midnight the account's today and the host's differ by a day.
When the account names no zone, or one the host's time zone database does not
know, UTC is used. For this reason the insights and change-history tools send
one `GET /ad_account` before the report itself. Windows has no system time
zone database, so mureo installs the `tzdata` package there.

A window longer than 365 days is refused.

## Units

| Value | Unit |
|-------|------|
| Budgets and bid amounts on campaigns and ad groups, the account's spending limits, and every amount a change tool takes | **micros** of the account currency (1,000,000 = one unit) |
| `bid_multiplier_micros` | micros of a multiplier (1,000,000 = 1.0x) |
| Insights `spend`, `cpc`, `cpm` | the account currency's **major units** (12.50 = 12.50) |
| Insights `ctr` | a ratio |

mureo converts none of them; read each value in its own unit. The change
tools declare which amounts the STRATEGY.md caps (written in currency units)
read, in `micros`, so they are compared after dividing by 1,000,000:

| Cap | Reads | Does not bound |
|-----|-------|----------------|
| `max_daily_budget_per_campaign` | `budget.daily_spend_limit_micros`, and the account's `amount_micros` | |
| `max_lifetime_budget_per_campaign` | `budget.lifetime_spend_limit_micros` | |
| `max_daily_budget_increase_pct`, `max_total_daily_budget` | `current_daily_budget` / `projected_total_daily_budget` (currency units), when the caller passes them | a call that leaves them out |
| `max_cpc_bid_per_ad_group` | `bidding_config.max_bid_micros` | audience multipliers, the strategies without a bid, and impression billing, where the amount is per impression |

## Data freshness

From the API's reporting documentation:

| Metrics | What the documentation says |
|---------|-----------------------------|
| Impressions, clicks, CTR | "Can become available within minutes. Recent values may change as processing completes." |
| Spend, CPC, CPM | "Reflect finalized activity and can update later than impressions and clicks." |
| Conversions and purchase outcomes | "Allow at least one day for conversion data to appear." |

"Current-day and current-month reports can contain partial periods." Treat
same-day rows as provisional, and do not divide the latest spend by the latest
click count to get CPC; use the returned `cpc`.

## Limits

- **Platform rate limits.** The API enforces 600 requests per minute per
  endpoint and 1,200 requests per minute overall, by both ad account and IP
  address.
- **mureo's throttle.** Each ChatGPT Ads tool declares its own throttle, 8
  calls per second with a burst of 5, and so gets a bucket of its own rather
  than the shared plugin bucket. The throttle counts tool calls: one call to a
  list tool can send several page requests, and the reads a change makes
  before it writes (the prior-state read for a reversal, the campaign read of
  `chatgpt_ads_campaigns_update_budget`, the spending-limits read of
  `chatgpt_ads_account_daily_spend_limit_set`) are not counted.
- **Retries.** A `GET` answered with 429 or any 5xx is tried at most 3 times in
  total. A `POST` is retried on 429 only, because a 429 is answered without
  processing the request (unverified, see
  [Not yet exercised](#not-yet-exercised-against-a-live-account)); a 5xx on a
  `POST` is final, because the change may
  have been applied before the answer was lost and repeating it could apply
  it twice. A numeric `Retry-After` header of up to 30 seconds sets the wait;
  a longer one is not waited for, and the answer is reported at once. Without
  a usable header the wait doubles from 1 second. A 429 or 5xx on the last
  attempt is reported as an API error. A transport error is not retried.
- **Page sizes.** Pages are requested at the API's maximum or the rows still
  needed, whichever is smaller: 500 for campaigns, ad groups and ads, 100 for
  audit logs, 2000 for insights.
- **Reporting window.** At most 365 days. The API keeps non-hourly delivery
  reporting for the most recent 365 days, and conversion metrics need full
  days in the account's time zone and at most 365 days.
- **Timeout.** 30 seconds per request, and 120 seconds for the whole tool
  call (every page, retry and backoff together). A call that runs out of time
  is reported as `API error: the call did not finish within 120 seconds`.
  The read that records a reversal has its own 15-second limit.
- **Page cap.** One call requests at most 50 pages. A list that needs more is
  reported as an API error asking for a lower `limit` or narrower filters,
  rather than returned short. A page that says more rows follow without an
  advancing cursor is reported the same way.

## Failures

| Situation | Result |
|-----------|--------|
| No key stored and `CHATGPT_ADS_API_KEY` unset | `{"status": "auth_error", "auth_cause": "no_credentials", "detail": ...}`; the detail names the ChatGPT Ads card of `mureo configure` and `CHATGPT_ADS_API_KEY` |
| 401, or a 403 that is not a feature gate | `{"status": "auth_error", "auth_cause": "token_invalid", "detail": "ChatGPT Ads rejected the API key: ..."}` |
| 403 or 404 whose error code ends in `_disabled` or `_not_enabled`, or whose message says `is not enabled` / `not enabled for` | `{"status": "error", "error": "feature_not_enabled", "detail": ...}`: the feature is not enabled for this ad account |
| Any other error answer (400, a plain 404, 409, 413, 422, 5xx, 429 after retries) | text `API error: HTTP <status> (<code>): <message>`; `(<code>)` only when the body carries a well-formed code, and `no readable error detail in the response body` in place of the message when the body is not a JSON object or names none |
| A success answer that is not JSON | text `API error: HTTP <status>: the response body is not JSON`; for a change tool, with the ending below |
| A change answered 2xx with an empty body (a 204, or only whitespace) | `{}`: the platform took the change and returned nothing |
| A transport error | text `API error: transport error (<error class>)` |
| The call deadline, the page cap, a list cursor that does not advance | text `API error: ...` (see [Limits](#limits)) |
| A change tool that ends in a 5xx, a non-JSON success body, a transport error or the call deadline | the same text, ending `The change may have been applied; read the entity before retrying.` |
| `chatgpt_ads_account_daily_spend_limit_set` with more than one daily rule | `{"status": "refused", "error": "multiple_daily_spend_limits", "detail": ...}`, before any change |
| `chatgpt_ads_account_daily_spend_limit_set` whose spending-limits answer is not a JSON object or carries an unusable `revision` | text `API error: ...; nothing was changed`, before any change |
| `chatgpt_ads_campaigns_update_budget` that would change the budget type | `{"status": "refused", "error": "budget_kind_change", "detail": ...}`, before any change; `budget_unreadable` when the current budget holds neither amount |
| A missing or malformed argument | `ValueError`, raised before any request |

A change that ends in a 5xx, a non-JSON success body, a transport error or
the deadline may have reached the platform before the answer was lost. Read
the entity with the matching `*_get` tool before trying again; repeating the
call blind could apply it twice.

The platform's message is quoted only from a JSON object body. It is
collapsed to one line, stripped of non-printable characters, passed through
mureo's secret scrub and cut at 200 characters. A body that is not JSON (an
intermediary's error page, for instance) is never quoted. The API key never
appears in a result, an error message or a log line: its exact value is
replaced with `***` in an error body before the body is read, a transport
error is reported by its class name only, and error answers are read without
the request that produced them.

## What the agent is told

The provider registers a **platform delivery model**: one paragraph, with a
first-party source, that the MCP server renders into its `instructions` while
it serves the ChatGPT Ads tools. With the provider enabled (the default) the
server's `instructions` therefore carry a `chatgpt_ads` line under "Platform
delivery models". It says that delivery is decided by an auction that sets the
actual CPC, that each ad group's billing event decides whether impressions or
clicks are billed and conversion-optimized bidding still bills per valid
click, that budgets and bids are in micros, and that conversions arrive at
least one day late. See
[`plugin-authoring.md`](plugin-authoring.md#declaring-your-platforms-delivery-model-optional).

The foundation skill
[`skills/_mureo-chatgpt-ads/SKILL.md`](../skills/_mureo-chatgpt-ads/SKILL.md)
covers when to use each tool, the units, provisional same-day data and how to
relay each failure to the operator.

The STATE.json platform key is `plugin:mureo-chatgpt-ads:chatgpt_ads`.

## Not supported today

- **Creating and archiving.** No tool creates a campaign, ad group or ad
  (#995) or archives one. No tool changes an ad's creative, an ad group's
  targeting, or a date-range spending limit, or removes the account's daily
  limit.
- **Partner access.** No OAuth and no partner key: mureo never sends the
  `OpenAI-Ad-Account` header, so it reads only the ad account an advertiser
  key is scoped to.
- **Other APIs.** No bulk API, hotel feeds, product feeds, custom audiences,
  conversion setup or conversion insights.
- **Other insights options.** No segments, filters, sorting, zero-row
  includes, hourly or monthly buckets, or attribution time basis.
- **BYOD.** ChatGPT Ads is not part of BYOD mode.
- **mureo-only analysis.** Anomaly baselines and the other analyses keyed to
  the Google Ads and Meta Ads tools do not exist for ChatGPT Ads; treat
  findings as advisory.

## Not yet exercised against a live account

The tools are written against the published API reference and OpenAPI
document and tested against recorded answers, not yet against a live ad
account. These points are unverified:

- **Error-body shape.** The reference defines no error-body schema. mureo
  reads `{"error": {"message", "code"}}`, `{"error": "<text>"}` and a
  top-level `message`, `detail` or `code`, and reports the status code alone
  for any other body.
- **`GET /ad_groups` without `campaign_id`.** The reference marks
  `campaign_id` required and the OpenAPI document marks it optional; the tool
  requires it.
- **`Retry-After`.** Whether 429 answers carry it, and in which form.
- **Feature gates.** Which status codes and error codes a feature that is not
  enabled for an account answers with. The reference documents
  `product_feed_api_disabled` and `product_feed_delta_api_disabled` for the
  feed APIs only.
- **Conversion metric names.** Delivery metrics are requested as
  `<level>.<metric>` (for example `campaign.impressions`), the reference's
  canonical form; conversion metrics are requested under their bare names
  (`conversions`, `cpa`, ...), as the reference's examples do. Whether every
  conversion metric is accepted that way is unverified.
- **Ranges that end today.** A `date_range` `until` normalizes to the following
  local midnight, and the reference says bounds cannot be in the future.
  Whether `today` and `this_month` are accepted, clamped or refused is
  unverified.
- **`budget` with one limit set.** Whether a campaign whose budget holds only
  a daily or only a lifetime amount answers with the other key absent, `null`
  or 0. Absent and `null` count as unset. A 0 counts as present and fails the
  tool's check, so such a budget records no reversal, and a change to it is
  refused as a budget type change.
- **Changing the budget type.** What the platform answers when a budget's
  keys change (daily to lifetime, or one added or dropped). mureo refuses
  such a change before sending it.
- **A change answered with no body.** Whether the platform ever answers a
  change with an empty body (204). mureo returns `{}` for one.
- **429 on a change.** Whether a 429 is always answered without processing
  the request, which is why a `POST` is retried on 429.
- **`automated_bid` round trip.** Responses can report the strategy
  `automated_bid`, which a request expresses by omitting `strategy` and
  `max_bid_micros`. Whether sending that back restores the same config is
  unverified.
- **`expected_revision`.** How the platform answers when the revision has
  moved on since mureo read it, and whether an account with no daily rule
  accepts revision 0.
- **Pausing a paused entity.** Whether pause on an entity that is already
  paused, or activate on one that is already active, is accepted unchanged or
  answered with an error.

## Terms

The key belongs to the advertiser's own ad account. The platform's terms
restrict sharing an API key with another party; check them before using a key
someone else issued.

## Refreshing the contract fixture

`tests/fixtures/chatgpt_ads_openapi_subset.json` lists, for each operation the
tools call, the method, the path template, the query parameter names and, for
a `POST`, the top-level request-body property names, cut from the OpenAPI
document. A test fails any request whose method, path, parameter names or
body keys are not in it. To refresh it after the API changes:

1. Download the OpenAPI document, linked from the API overview
   (`https://developers.openai.com/ads/openapi.json`). Its paths are relative
   to `https://api.ads.openai.com/v1`.
2. For each operation in the fixture, copy the `name` of every parameter with
   `"in": "query"` under `paths["<path>"].<method>.parameters`. For an
   `array`-typed parameter, also list the bracketed spelling (`include[]`,
   `fields[]`, `time_ranges[]`) that the reference's examples send. For a
   `POST`, list the property names of the schema its `requestBody`
   references (`application/json`) under `body`; an operation with no request
   body gets an empty list.
3. Set `openapi_version` and the `_comment` to the document's `info.version`
   and the date you read it, and update `OPENAPI_VERSION` and
   `OPENAPI_READ_ON` in `mureo/chatgpt_ads/_api.py` to match.
4. Run `pytest tests/test_chatgpt_ads_client.py tests/test_chatgpt_ads_tools.py tests/test_chatgpt_ads_mutations.py`.
   A failure names the request that left the contract.
