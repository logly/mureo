# ChatGPT Ads (bundled provider)

mureo reads **ChatGPT Ads** accounts through OpenAI's **Advertiser API**, the
API behind ChatGPT Ads. The provider ships inside mureo (`mureo/chatgpt_ads/`)
and is served through the provider path, the same one the Amazon Ads bridge
and third-party provider plugins use:

```
Claude  →  local mureo MCP  →  https://api.ads.openai.com/v1
```

The Ads API key stays in mureo's credential store (Claude never sees it), and
every call goes through mureo's plugin safety layer: the audit trail and the
per-tool throttle.

**Scope:** nine **read-only** tools: the ad account, campaigns, ad groups,
ads, insights and the change history. No tool changes anything on the
platform yet; changes are tracked in #994 and #995. The API is in beta and
adds fields often, so every object and row is returned as the platform sent it,
with unknown fields and enum values left as they are.

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

All nine tools are read-only (`readOnlyHint`), take no account argument (the
key selects the account), and reject arguments their schema does not declare.

| Tool | API | Arguments (defaults) |
|------|-----|----------------------|
| `chatgpt_ads_account_get` | `GET /ad_account` | *(none)* |
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
- **`name`** is 3 to 1000 characters and not all spaces.
- **`limit`** is 1 to 1000. The list tools follow the API's cursor
  (`has_more` / `last_id` → `after`) until that many rows are collected and
  return one flat JSON array; no cursor is returned. Rows beyond `limit` are
  dropped without notice, so a daily insights report, which returns one row
  per entity per day, needs a `limit` of at least entities × days.
- **Single gets** return the platform object unchanged.

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
| Budgets and bid amounts on campaigns and ad groups | **micros** of the account currency (1,000,000 = one unit) |
| Insights `spend`, `cpc`, `cpm` | the account currency's **major units** (12.50 = 12.50) |
| Insights `ctr` | a ratio |

mureo converts neither; read each value in its own unit.

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
  list tool can send several page requests.
- **Retries.** A `GET` answered with 429 or any 5xx is tried at most 3 times in
  total. A numeric `Retry-After` header of up to 30 seconds sets the wait; a
  longer one is not waited for, and the answer is reported at once. Without a
  usable header the wait doubles from 1 second. A 429 or 5xx on the last
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
| A success answer that is not JSON | text `API error: HTTP <status>: the response body is not JSON` |
| A transport error | text `API error: transport error (<error class>)` |
| The call deadline, the page cap, a list cursor that does not advance | text `API error: ...` (see [Limits](#limits)) |
| A missing or malformed argument | `ValueError`, raised before any request |

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

- **Changes.** No create, update, pause or activate tool (#994, #995).
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

## Terms

The key belongs to the advertiser's own ad account. The platform's terms
restrict sharing an API key with another party; check them before using a key
someone else issued.

## Refreshing the contract fixture

`tests/fixtures/chatgpt_ads_openapi_subset.json` lists, for each `GET`
operation the tools call, the method, the path template and the query
parameter names, cut from the OpenAPI document. A test fails any request whose
path or parameter names are not in it. To refresh it after the API changes:

1. Download the OpenAPI document, linked from the API overview
   (`https://developers.openai.com/ads/openapi.json`). Its paths are relative
   to `https://api.ads.openai.com/v1`.
2. For each operation in the fixture, copy the `name` of every parameter with
   `"in": "query"` under `paths["<path>"].get.parameters`. For an
   `array`-typed parameter, also list the bracketed spelling (`include[]`,
   `fields[]`, `time_ranges[]`) that the reference's examples send.
3. Set `openapi_version` and the `_comment` to the document's `info.version`
   and the date you read it, and update `OPENAPI_VERSION` and
   `OPENAPI_READ_ON` in `mureo/chatgpt_ads/_api.py` to match.
4. Run `pytest tests/test_chatgpt_ads_client.py tests/test_chatgpt_ads_tools.py`.
   A failure names the request that left the contract.
