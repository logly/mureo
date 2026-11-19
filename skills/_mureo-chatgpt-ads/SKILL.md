---
name: _mureo-chatgpt-ads
description: "ChatGPT Ads (bundled provider over OpenAI's Advertiser API): read the ad account, spending limits, campaigns, ad groups, ads, performance insights and the change history; pause and activate, rename, reschedule, set budgets, bids and the account daily spending limit, each recorded with a reversal; create campaigns, ad groups and ads (always paused), archive them irreversibly, upload images, preview ads and search locations; create and fill custom audiences from a local identifier file; set up pixels and conversion events and report conversions."
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

- **Eighteen read tools and twenty-three tools that change the account**
  over OpenAI's Advertiser API, the API behind ChatGPT Ads. mureo calls the
  API itself; no other MCP server is involved.
- **What can change:** pause and activate a campaign, ad group or ad; rename
  or reschedule a campaign; set a campaign's budget; rename an ad group; set
  an ad group's bidding config; set the account's daily spending limit;
  create a campaign, ad group or ad (always paused); archive one; upload an
  image; create a custom audience and add or remove its members; create a
  pixel or a conversion event setting. Nothing edits a creative, targeting or context hints after
  creation, or removes the account limit: for those, say the change has to
  be made in Ads Manager; do not look for another tool.
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
| `chatgpt_ads_ads_preview` | Show how an ad renders: an HTML iframe snippet that expires after 24 hours (not for a draft ad). It changes no campaign, ad group or ad (the platform renders and saves an expiring preview snapshot), which is why it is treated as a read |
| `chatgpt_ads_locations_search` | Find location ids for campaign targeting by name (`query`, `limit` default 20, at most 100) |

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

Changes made on this account outside mureo are recorded into `action_log` by
`mureo_external_changes_import`, from the same audit log (at most 1,000
entries per pass, oldest first). A capped pass says `truncated` and its note
names the time it read through: run the import again, which continues from
the newest change imported, and if it stops at the same point, pass the
`since` the note gives rather than repeating the same call. The account id
recorded for this platform in STATE.json must be the `id` that
`chatgpt_ads_account_get` returns: when the key reads another account,
nothing is imported and the outcome is `unavailable`; when none is recorded,
the import runs unchecked and its notes say so. An account-level change such
as the daily spending limit is always imported as external, even when mureo
made it, and so is the entry for an entity mureo created (its record cannot
name an id that did not exist yet).

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
  which reads back as `automated_bid`. `max_cpc_bid_per_ad_group` and
  `max_bid_amount_per_ad_set` read `max_bid_micros` only: audience
  multipliers (up to 10x) and the strategies without a bid are not bounded
  by them, and with impression billing the amount
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
  change names no campaign, ad group or ad. Creates, archives and uploads
  are recorded with no reversal (see below).
- **No learning-period rules.** `mureo_learning_reset_preflight` answers
  `unknown` for these tools; do not claim a change will or will not reset
  learning.

### Creating and archiving

| Tool | Use it to |
|------|-----------|
| `chatgpt_ads_campaigns_create` | Create a campaign (`name`, `budget`, `bidding_type`; optional `targeting`, schedule, conversion event settings) |
| `chatgpt_ads_ad_groups_create` | Create an ad group in a campaign (`campaign_id`, `name`, `bidding_config`; optional `context_hints`) |
| `chatgpt_ads_images_upload_file` | Upload a local JPEG, PNG or WebP image (at least 640x640, at most 30MB); its content must be identified as the format its extension names, and the bytes checked are the bytes sent. Its `file_id` goes into `creative.file_id`. Not retried on a 5xx or a transport error |
| `chatgpt_ads_ads_create` | Create an ad in an ad group (`ad_group_id`, `name`, `creative`: a single-image chat card) |
| `chatgpt_ads_campaigns_archive` / `chatgpt_ads_ad_groups_archive` / `chatgpt_ads_ads_archive` | Archive an entity, irreversibly |

- **Created paused, always.** There is no `status` argument; nothing created
  can spend until the operator approves the matching `*_enable` call. Show
  the full object (name, budget, bidding, targeting, creative) before the
  create, as for any change.
- **`budget` holds exactly one** of `daily_spend_limit_micros` or
  `lifetime_spend_limit_micros`. Pass `projected_total_daily_budget`
  (currency units) so `max_total_daily_budget` can be checked.
  `max_daily_budget_per_campaign` does not bound a lifetime budget; only
  `max_lifetime_budget_per_campaign` does.
- **mureo's own bounds** (the platform states none): up to 250 `countries`,
  1000 audience ids, 1000 `conversion_event_setting_ids`, 255 characters per
  descriptive `include` field, and 1 to 1000 characters per `context_hints`
  item. `target_url` needs a host and takes no `user:password@` and no
  backslash.
- **`bidding_type` cannot be changed later.** `impressions` pairs with
  impression billing and `fixed_bid`; `clicks` with click billing and
  `fixed_bid` or `maximize_clicks`; `conversions` with click billing and
  `fixed_bid` or `maximize_conversions` and exactly one conversion event
  setting. The maximize strategies need a daily budget. The platform enforces
  this; say so before the operator picks one.
- **Ads go to review** on creation (`in_review`, then `approved` or
  `rejected`); read the outcome with `chatgpt_ads_ads_get`.
- **Lost answers.** A create carries an idempotency key. When it ends with
  `repeat the call with idempotency_key="..."`, repeat the same call with
  that key and the same arguments: when the platform can see the earlier
  create it returns that entity instead of creating a second one. If that
  repeat fails too, list by name (`chatgpt_ads_campaigns_list`,
  `chatgpt_ads_ad_groups_list` or `chatgpt_ads_ads_list` with `name`) before
  creating with a new key. Do not repeat a create without the key.
- **No undo.** `rollback_apply` cannot undo a create or an archive. Undo a
  create by leaving it paused, or archive it once the operator confirms.
  Archiving cannot be reversed on the platform: prefer pausing, and say so
  before asking for approval. Whether archiving a campaign or ad group also
  archives its children is not documented.

### Custom audiences

| Tool | Use it to |
|------|-----------|
| `chatgpt_ads_audiences_list` / `chatgpt_ads_audiences_get` | Find audiences (`intended_use` filter) and read one's status and size (`audience_id`) |
| `chatgpt_ads_audiences_create` | Create an empty audience (`name`, optional `description`) |
| `chatgpt_ads_audiences_members_add` / `_remove` | Add or remove members from a local file (`audience_id`, `file_path`, `identifier_type`) |
| `chatgpt_ads_audiences_operations_get` | Poll an add or remove until its `status` is no longer `processing` |

- **Identifiers never go in arguments.** Arguments reach the audit trail and
  the conversation. Ask the operator for a path to a UTF-8 `.txt` or `.csv`
  file (at most 2 MiB), one identifier per line, no header, every line of the
  `identifier_type` named: `email` and `phone` (E.164 with `+` and country
  code) are hashed with SHA-256 on the machine; `email_sha256` and
  `phone_number_sha256` are sent as given; `gaid` is sent unhashed. Never
  read, quote or summarise the file's lines in the conversation.
- **One value per line.** A quoted value or a comma-separated row is an
  invalid line, so the platform's own CSV upload format (a header row,
  several columns) is not this file: ask for the one column. An email must be
  a plain ASCII address (no quotes, `mailto:`, brackets or invisible
  characters, a dotted domain); for non-ASCII addresses the operator hashes
  them and passes `email_sha256`. A phone written `+44 (0)20 ...` is invalid:
  drop the bracketed zero.
- **One invalid line refuses the whole call**, with the count and up to 10
  line numbers; nothing is sent. A file must hold 1 to 10,000 distinct
  identifiers: an empty one is refused on its own; split a larger one and
  call once per part.
- **Consent is the operator's.** Upload only first-party data the
  advertiser has the right and consent to use; say so before the first add.
- **Size and region.** Inclusion and bid-multiplier use need at least 25,000
  matched users; exclusion has no minimum. Custom audiences are not supported
  for campaigns that target the EEA or Switzerland.
- **Lost answers.** An add or remove carries an idempotency key; when it ends
  with `repeat the call with idempotency_key="..."`, repeat it with that key,
  the same arguments and the same file. An audience create has no key: list
  audiences before creating another.
- **`succeeded` is not a match count.** It means the operation finished; a
  remove from an opt-out list removes nobody whose address was spelled
  differently when it was uploaded. Say so when reporting a remove.
- **No reversal.** `rollback_apply` cannot undo an add or remove: removing
  what was added would also drop members who were there before.
- **Remove is destructive** (`destructiveHint`, like an archive) and can take
  an audience below the 25,000 matched users inclusion and bid multipliers
  need; say so before asking for approval.

### Conversion measurement

| Tool | Use it to |
|------|-----------|
| `chatgpt_ads_pixels_list` / `chatgpt_ads_pixels_create` | Find or create a web pixel (`name`) |
| `chatgpt_ads_conversion_events_list` | Find conversion event settings and their ids |
| `chatgpt_ads_conversion_events_create` | Create an event setting (`name`, `event_type`, `source_id`; `custom_event_name` when `event_type` is `custom`; always the documented 30-day click window) |
| `chatgpt_ads_conversions_report` | Conversion totals, click- and view-through counts, sales and per-event details for a period |

- **Event settings are permanent.** No API edits or deletes one; confirm the
  name, type and source with the operator before creating it.
- **`source_id` is the pixel's `id`**, not its `pixel_id` (that one
  initialises the JavaScript Pixel). An answer `Client data source not found`
  means `source_id` is not a pixel of this account: list the pixels again.
- **`feature_not_enabled` on the pixel list or create** means conversions are
  not enabled for the account; relay it, do not retry. A 404 on event
  settings is an ordinary `API error:`.
- **The report** takes `period`, `level`, `time_granularity` and
  `attribution_window_days` as `chatgpt_ads_insights_report` does, and needs
  `entity_ids` (1 to 100) unless `group_by_entity` is false. There is no
  pagination: more than 2,000 rows is refused, so narrow the ids or the
  period. Use `chatgpt_ads_insights_report` for conversions next to spend.

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
| Text ending `The change may have been applied; check the account before retrying.` | A change ended in a 5xx, an unreadable success answer, a transport error or the deadline, after the request may have reached the platform | Read the entity with its `*_get` tool (or list audiences, pixels or event settings after a create without a key) and report what it shows; never repeat the change blind |
| Text ending `repeat the call with idempotency_key="<key>" and the same arguments: ...` | A create ended the same way; the platform may hold the new entity | Repeat the create with that `idempotency_key` and unchanged arguments after the operator agrees; if that fails too, list by `name` before creating with a new key |
| Text ending `repeat the call with idempotency_key="<key>", the same arguments and the same file: ...` | An audience add or remove ended the same way; the operation may have been accepted | Repeat it with that key, the same arguments and the same file after the operator agrees |

An `auth_error` is not data: never render `detail` where a metric belongs and
never read the missing numbers as zero. Mark ChatGPT Ads as **not read** with
its `auth_cause`, and keep going with the other platforms.

A `ValueError` means the call itself was malformed (an unknown period, two
scope ids, a level above the scope, an unknown metric, an image of another
type, not identified as its extension's format, or over 30MB; an identifier
file with an invalid line or too many identifiers). A `FileNotFoundError`
means the image or identifier file path does not exist. Fix the arguments;
nothing was sent to the API.

## Important notes

- Read tools (the ad preview and location search included) write nothing to
  `action_log`. A change tool that fails is not
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
