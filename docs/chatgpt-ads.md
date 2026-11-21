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
bidding config, and set the account's daily spending limit. Six more tools
create a campaign, ad group or ad (always paused) and archive one, and three
support them: an image upload, an ad preview and a location search (#995).
Six tools read, create and fill custom audiences (see
[Custom audiences](#custom-audiences)), and five set up and report conversion
measurement (see [Conversion measurement](#conversion-measurement)).
Changes made on the account outside mureo are imported
from its audit log (see [Change import](#change-import)). The API is in beta
and adds fields often, so every object and row is returned as the platform
sent it, with unknown fields and enum values left as they are.

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
[Changes](#changes), [Creating](#creating) and [Archiving](#archiving), and
the audience and measurement tools under
[Custom audiences](#custom-audiences) and
[Conversion measurement](#conversion-measurement).

| Tool | API | Arguments (defaults) |
|------|-----|----------------------|
| `chatgpt_ads_account_get` | `GET /ad_account` | *(none)* |
| `chatgpt_ads_account_spend_limits_get` | `GET /ad_account/spend_limit_windows` | *(none)* |
| `chatgpt_ads_campaigns_list` | `GET /campaigns` | `name`, `include_serving_issues` (false), `limit` (50) |
| `chatgpt_ads_campaigns_get` | `GET /campaigns/{campaign_id}` | `campaign_id` (required), `include_serving_issues` (false) |
| `chatgpt_ads_ad_groups_list` | `GET /ad_groups` | `campaign_id`, `name`, `limit` (50) |
| `chatgpt_ads_ad_groups_get` | `GET /ad_groups/{ad_group_id}` | `ad_group_id` (required) |
| `chatgpt_ads_ads_list` | `GET /ads` | `ad_group_id`, `name`, `limit` (50) |
| `chatgpt_ads_ads_get` | `GET /ads/{ad_id}` | `ad_id` (required) |
| `chatgpt_ads_insights_report` | `GET /ad_account/insights`, `/campaigns/{id}/insights`, `/ad_groups/{id}/insights`, `/ads/{id}/insights` | `period` (`last_30d`), `level` (`campaign`), at most one of `campaign_id` / `ad_group_id` / `ad_id`, `time_granularity` (`none`), `metrics` (delivery set), `attribution_window_days` (API default), `limit` (1000) |
| `chatgpt_ads_change_history_list` | `GET /audit_logs` | `period` (`last_7d`), `campaign_id`, `ad_group_id`, `ad_id`, `limit` (50) |
| `chatgpt_ads_ads_preview` | `POST /ads/{ad_id}/preview` | `ad_id` (required) |
| `chatgpt_ads_locations_search` | `GET /geo_lookup/search` | `query` (required, sent as `q`), `limit` (20) |

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
- **`chatgpt_ads_ads_preview`** returns the platform's preview unchanged:
  `data[].body` is an HTML iframe snippet that expires after 24 hours. It is
  a `POST` that changes no campaign, ad group or ad (the platform renders and
  saves an expiring preview snapshot), which is why it is treated as a read
  and retried like a `GET`. An ad still in draft cannot be previewed.
- **`chatgpt_ads_locations_search`** looks up regions and markets by name.
  `query` is 1 to 200 characters and not all spaces; `limit` is 1 to 100. The
  answer (`query`, `count`, `results` with `id`, `name`, `canonical_name`,
  `type`, `country_code` and parent fields) is returned unchanged; a result's
  `id` goes into `targeting.locations.include` of a campaign create.

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
the change. Archiving is a separate, irreversible tool (see
[Archiving](#archiving)). Budget and bid edits
are tools of their own, not fields of the general update tools, because
mureo reads the kind of a recorded change off its tool name when it matches a
platform's change history against `action_log`
(`mureo_external_changes_import`): a budget change recorded under a generic
campaign-edit name could never be recognised as mureo's own budget change.

- **Pause and activate** send no body. `enable` makes the entity eligible to
  spend again. A pause on a campaign that is already paused is accepted and
  answers the campaign unchanged.
- **`name`** is 3 to 1000 characters on one line (no line break anywhere)
  and not all spaces.
- **`start_time` / `end_time`** are Unix seconds from 946684800 (2000-01-01)
  to 4102444800 (2100-01-01), or `null` to clear that end. A key that is
  present, even as `null`, is changed; a key left out is left as it is.
- **`budget`** is the complete new budget object: `daily_spend_limit_micros`
  and/or `lifetime_spend_limit_micros`, each at least 1000000 and nothing
  else. The platform replaces the whole object, so a key left out is removed,
  and an amount replaces the old one rather than adding to it. The platform
  rejects a lifetime budget below the amount already spent, and can reject a
  daily budget below an ad group's effective bid.
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
  `custom_audience_bid_multipliers` (items of `custom_audience_id`, an id of
  1 to 128 letters, digits, `_` or `-`, and
  `bid_multiplier_micros`, 100000 to 10000000, where 1000000 is 1.0x).
  Omitting both `strategy` and `max_bid_micros` selects automatic bidding,
  which responses report as `automated_bid` or, on a clicks campaign, as
  `maximize_clicks`. A fixed bid reads back as `target_strategy`
  (`target_cpc` with click billing) and `target_micros`, not as
  `strategy` / `max_bid_micros`. With impression billing the bid
  is per impression, not per thousand: CPM / 1000.
- **What the bid caps cover.** `max_cpc_bid_per_ad_group` and
  `max_bid_amount_per_ad_set` both read `max_bid_micros`, and nothing else:
  which of the two an operator wrote says nothing about an ad group's
  billing event, so each one that is set holds the bid. Audience bid
  multipliers (up to 10x) and the strategies without a bid (automatic
  bidding, `maximize_clicks`, `maximize_conversions`) are not bounded by
  them, and with impression billing
  the amount is per impression (CPM = amount × 1000), so a per-click cap does
  not meaningfully constrain it. The campaign budget is what bounds spend.
- **`amount_micros`** is an integer of at least 0. The platform expects a
  multiple of the currency's smallest unit, which mureo does not check. The
  STRATEGY.md cap
  `max_daily_budget_per_campaign` also holds this amount, although the limit
  is account-wide: mureo's policy gate reads an `amount_micros` argument as a
  daily budget in micros, declared or not.

The platform rules quoted here and in the next section (which budgets and
limits it rejects, which accounts and keys may use the account limit) are
the API reference's; mureo does not enforce them itself.

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
answer is not a JSON object, carries a `revision` that is not a whole number
of at least 0, or carries a `daily_limits` that is not an array or a
`daily_limit` that is not an object (`null` is fine for both). A non-empty
`daily_limits` array is the list of rules; otherwise the single
`daily_limit` is (absent or `null` = none).

### Creating

| Tool | API | Arguments |
|------|-----|-----------|
| `chatgpt_ads_campaigns_create` | `POST /campaigns` | `name`, `budget`, `bidding_type` (required), `targeting`, `start_time`, `end_time`, `conversion_event_setting_ids`, `projected_total_daily_budget`, `idempotency_key` |
| `chatgpt_ads_ad_groups_create` | `POST /ad_groups` | `campaign_id`, `name`, `bidding_config` (required), `context_hints`, `idempotency_key` |
| `chatgpt_ads_ads_create` | `POST /ads` | `ad_group_id`, `name`, `creative` (required), `idempotency_key` |
| `chatgpt_ads_images_upload_file` | `POST /upload` (multipart field `file`) | `file_path` (required) |

Each create returns the new platform object unchanged; its `id` is what the
next level's create needs (campaign → ad group → ad).

- **Always paused.** The create tools take no `status`; mureo always sends
  `"status": "paused"`, and a `status` argument is refused. A created
  campaign, ad group and ad answer `status` `paused`. Nothing created
  through mureo can spend until the matching `*_enable` tool is called.
- **`budget`** takes exactly one of `daily_spend_limit_micros` or
  `lifetime_spend_limit_micros` (at least 1000000; the platform refuses both
  and neither, and mureo refuses them before sending). The platform also
  refuses a daily budget below a per-currency minimum, with a 400 whose
  message names the minimum in micros (2,500,000,000 for JPY); mureo does not
  check it beforehand. A STRATEGY.md
  `max_daily_budget_per_campaign` does not bound a lifetime budget: a create
  with only `lifetime_spend_limit_micros` passes it however large, and only
  `max_lifetime_budget_per_campaign` bounds that amount.
- **`bidding_type`** (`impressions`, `clicks` or `conversions`) cannot be
  changed once the campaign exists. The platform pairs it with the ad
  groups' bidding: `impressions` with impression billing and `fixed_bid`;
  `clicks` with click billing and `fixed_bid` or `maximize_clicks`;
  `conversions` with click billing and `fixed_bid` or
  `maximize_conversions`, and exactly one conversion event setting. The
  maximize strategies need a daily budget. mureo states these rules in the
  tool descriptions and leaves them to the platform: the ad group create does
  not know its campaign's `bidding_type` without another read.
- **`targeting`** is passed through unchanged, with only the documented keys
  at every level: `locations` / `excluded_locations` (`countries` as up to
  250 ISO 3166-1 alpha-2 codes, `include` as up to 2500 location objects
  whose `id` comes from `chatgpt_ads_locations_search`), `custom_audiences` /
  `excluded_custom_audiences` (`ids`, up to 1000), and `platforms.included`
  (`ios_app`, `android_app`, `web`, `desktop_web`, `ios_web`,
  `android_web`). Omitted, the platform default applies. The descriptive
  fields of an `include` object (`name`, `type`, `country_code`,
  `region_code`, copied from a search result) are at most 255 characters
  each.
- **mureo's own bounds.** The platform states no limit for these, so mureo
  sets them to bound one request body: up to 250 `countries` (ISO 3166-1
  assigns 249 codes), up to 1000 audience ids and 1000
  `conversion_event_setting_ids`, at most 255 characters per descriptive
  `include` field, and 1 to 1000 characters per `context_hints` item. Both the
  schema and the handler enforce them, before any request.
- **`start_time` / `end_time`** are Unix seconds in the same range as the
  campaign update; `null` is refused, leave a key out instead.
- **`conversion_event_setting_ids`** (up to 1000) and the ids inside
  `targeting` follow the id rule above.
- **`projected_total_daily_budget`** is the same optional context key as on
  the budget tool (currency units, checked, never sent), so
  `max_total_daily_budget` can be evaluated. `current_daily_budget` means
  nothing for a new campaign and is not offered.
- **`bidding_config`** is the same object as on
  `chatgpt_ads_ad_groups_update_bid`, and the bid caps cover the same amount
  (see [What the bid caps cover](#changes)).
- **`context_hints`** is up to 2000 free-form strings of 1 to 1000
  characters each that guide placement; they are not hard eligibility rules.
- **`creative`** is a single-image chat card, the only creative type mureo
  offers: `type` `chat_card`, `title` 3 to 50 characters on one line, `body`
  up to 100 characters, `target_url` the `http` / `https` landing page (up to
  2048 characters, required; a host is required, and user-info such as
  `user:password@`, a backslash, whitespace or a control character is
  refused; mureo only checks the shape, since it never fetches the page and
  the platform does in its own review), `file_id` from the image upload, and
  `image_crop` (`x`, `y`, `width`, `height`, each a fraction from 0 to 1;
  only with `file_id`). Multi-image and product-template creatives are not
  offered.
- **Review.** An ad answers `review_status` `in_review` at creation and
  later reads `approved` or `rejected`; read it with
  `chatgpt_ads_ads_get`.

**Idempotency key.** Each create sends an `Idempotency-Key` header: the
`idempotency_key` argument (1 to 255 letters, digits, `_` or `-`), or a key
mureo generates once per call. Every attempt of one call reuses it. The
platform documents that, for a repeat with the same key, it returns the
existing object instead of creating a duplicate when a matching earlier create
is visible to it, so a create, unlike other changes, is retried on a 5xx (at
most 3 attempts in total, as for a `GET`). That retry waits the normal backoff
before repeating; whether a create still in flight is already visible to the
repeat is not documented. A repeat with the same key returns the earlier
entity with the same id, and the answer carries the key as
`user_external_id`. A repeat with the same key and a different body is not
refused: it returns the earlier entity unchanged, so a key must never be
reused for a different entity. When a create ends in a 5xx, a non-JSON success
body, a transport error or the call deadline, the error text ends with the key
instead of the "may have been applied" sentence: `The entity may have been
created; repeat the call with idempotency_key="<key>" and the same arguments:
when the platform can see the earlier create it returns that entity instead of
creating a second one.` The key is not a secret.

**Images.** `chatgpt_ads_images_upload_file` checks the local file the way
mureo's other image uploads do before sending anything: the extension must be
`.jpg`, `.jpeg`, `.png` or `.webp`, the file must exist and be a regular
file whose content is identified as the format its extension names (so a
file that is not an image, or a link to one, with an image extension is
refused), a path with `..` is refused, and the file may be at most 30MB (the
platform documents no size limit; the cap is the one mureo's Meta Ads image
upload uses). The platform requires creative images to be JPEG, PNG or WebP
and at least 640×640 pixels, which mureo does not check. The file is sent
with its file name and the content type of its extension; the file is
opened once, and the bytes checked are the bytes sent. The returned
`file_id` goes into `creative.file_id`. An upload is not retried on a 5xx or
a transport error (a 429 is retried, like every request).
Errors from the platform or the transport never quote the path or the file's
bytes; a refused path is named in the argument error.

**Undoing a create.** No reversal is recorded and `rollback_apply` cannot
undo a create: the entity has no id before the call. To undo one by hand,
leave it paused (it cannot spend), or archive it with the matching
`*_archive` tool once you are sure (irreversible).

### Archiving

| Tool | API | Arguments |
|------|-----|-----------|
| `chatgpt_ads_campaigns_archive` | `POST /campaigns/{campaign_id}/archive` | `campaign_id` (required) |
| `chatgpt_ads_ad_groups_archive` | `POST /ad_groups/{ad_group_id}/archive` | `ad_group_id` (required) |
| `chatgpt_ads_ads_archive` | `POST /ads/{ad_id}/archive` | `ad_id` (required) |

An archive sends no body and returns the updated object unchanged. It is
**irreversible**: the platform has no restore operation, mureo records no
reversal, and `rollback_plan_get` reports the entry as not supported. The
tools carry `destructiveHint` (as does the audience member removal, see
[Custom audiences](#custom-audiences)). To stop spending reversibly, pause
instead.
Archiving a campaign does not archive its ad groups and ads: they keep their
status and are archived one by one. An archived campaign is left out of
`chatgpt_ads_campaigns_list`'s default answer. Whether archiving an ad group
archives its ads is not documented.

### Custom audiences

| Tool | API | Arguments (defaults) |
|------|-----|----------------------|
| `chatgpt_ads_audiences_list` | `GET /custom_audiences` | `intended_use` (`inclusion` \| `exclusion` \| `bid_multiplier`), `limit` (50) |
| `chatgpt_ads_audiences_get` | `GET /custom_audiences/{custom_audience_id}` | `audience_id` (required) |
| `chatgpt_ads_audiences_create` | `POST /custom_audiences` | `name` (required), `description` |
| `chatgpt_ads_audiences_members_add` | `POST /custom_audiences/{custom_audience_id}/add` | `audience_id`, `file_path`, `identifier_type` (required), `idempotency_key` |
| `chatgpt_ads_audiences_members_remove` | `POST /custom_audiences/{custom_audience_id}/remove` | `audience_id`, `file_path`, `identifier_type` (required), `idempotency_key` |
| `chatgpt_ads_audiences_operations_get` | `GET /custom_audiences/{custom_audience_id}/operations/{operation_id}` | `audience_id`, `operation_id` (required) |

The audience id argument is `audience_id` on every tool (the name mureo's
other audience tools use); it is sent in the path.

- **Creating an audience.** `chatgpt_ads_audiences_create` sends only `name`
  (3 to 1000 characters on one line, not all spaces) and, when given,
  `description` (at most 1000 characters; the platform states no limit, so
  mureo uses the name's). No file is ever sent, so the audience starts empty;
  an empty audience needs the account's small-audience enablement. A new
  audience answers status `rockset_ingest_pending`, then `ready`; wait for
  `ready` before using it. It can be missing from
  `chatgpt_ads_audiences_list` for a few seconds after the create. The
  platform offers no idempotency key for
  this call: when the answer is lost, the error ends with the "may have been
  applied" sentence, and the reference says to check the audience list before
  creating another.
- **Eligibility.** An audience used for inclusion or as a bid multiplier
  needs at least 25,000 matched users; exclusion has no minimum. Custom
  audiences are not supported for campaigns that target the EEA or
  Switzerland.
- **Rights and consent.** Upload only first-party data you have the right
  and the consent to use for this purpose. That is the operator's
  responsibility; mureo does not check it.

**The identifier file.** The add and remove tools never take identifiers as
arguments: tool arguments are written to mureo's audit trail and pass through
the model. They read a local file instead:

- **Format.** UTF-8 text (a byte-order mark is accepted), extension `.txt` or
  `.csv`, one identifier per line, no header row; every line holds the type
  `identifier_type` names (`email`, `phone`, `gaid`, `email_sha256` or
  `phone_number_sha256`). Surrounding whitespace is stripped, blank lines are
  skipped and duplicates are dropped after normalisation. After that the file
  must hold 1 to 10,000 distinct identifiers (the reference's inline,
  small-update path); a file with none is refused with `file_path holds no
  identifiers; give one per line`, and a larger one with its count and asked
  to be split. A line is one value: a quoted value or a comma-separated row
  is an invalid line. The platform's own CSV upload format (a header row,
  several columns) is not what this file is; export the one column instead.
- **The path rules** are those of the image upload: the file must exist, be
  a regular file and be at most 2 MiB, and a path with `..` is refused. The
  file is opened once and the bytes read are the bytes parsed.
- **What is hashed.** `email` is trimmed and lowercased (dots, plus tags and
  apostrophes kept) and must then be a plain ASCII address: only printable
  ASCII without spaces, exactly one `@` with text on both sides, none of
  `"` `,` `;` `:` `<` `>` `(` `)` `[` `]` `\`, and a domain that holds a dot
  and neither starts nor ends with a dot or a hyphen. An address with
  non-ASCII characters is refused, because the reference does not say how
  the platform normalises one; hash such addresses yourself and pass
  `email_sha256`. A valid address is sent as the SHA-256 of its UTF-8 bytes
  in lowercase hex, typed `email_sha256`. `phone` loses spaces, hyphens, dots
  and parentheses, must then be E.164 (`+`, a first digit 1 to 9, 7 to 15
  digits in all), and is hashed including the `+`, typed
  `phone_number_sha256`; a number without `+` and country code is invalid,
  and no country is guessed, and a number written with a bracketed trunk zero
  (`+44 (0)20 ...`) is invalid, because dropping the brackets would keep a
  zero that is not part of the number. `email_sha256` and
  `phone_number_sha256` lines must be 64 hex characters and are lowercased.
  `gaid` must be a canonical hyphenated UUID other than all zeros; it is
  lowercased and sent unhashed, as the platform requires.
- **What leaves the machine.** Only the digests and raw advertising ids, as
  `{"identifiers": [{"identifier_type", "identifier"}, ...]}`. The plaintext
  types `email` and `phone` are never sent, and neither is the path.
- **One invalid line refuses the call.** Before any request, a `ValueError`
  names the number of invalid lines and up to 10 line numbers. No message, log
  line or result quotes a line of the file, not even in part; a file that is
  not valid UTF-8 is refused without quoting its bytes.
- **The audit trail** records the call's arguments, so it holds the file path
  and the identifier type, never an identifier. In a platform error for an
  add or remove, anything shaped like a digest or an advertising id is
  replaced with `***` before the text is returned or logged.

**Asynchronous operations.** An add or remove returns the platform's operation
object unchanged (`operation_id`, `status` `processing`, `succeeded` or
`failed`, and `failure_reason` when it failed). Poll
`chatgpt_ads_audiences_operations_get` until it is no longer `processing`.
`succeeded` means the operation finished, not that every identifier matched
a user: for a remove built from an opt-out list, a line hashed from a
different spelling than the one uploaded removes nobody.

**Removal is destructive.** `chatgpt_ads_audiences_members_remove` carries
`destructiveHint`, as the archives do: what it removes is gone, and a removal
can take an audience below the 25,000 matched users that inclusion and bid
multipliers need.

**Idempotency key.** The platform requires an `Idempotency-Key` on add and
remove; mureo sends the `idempotency_key` argument or a key it generates once
per call, exactly as the creates do, and retries a 5xx with the same key and
body. The reference says a repeat with the same key returns or resumes the
first accepted operation, and may do so without checking the new body. So when
an add or remove ends in a 5xx, a non-JSON success body, a transport error or
the deadline, the error ends with `The operation may have been accepted;
repeat the call with idempotency_key="<key>", the same arguments and the same
file: a repeat with that key returns or resumes the first accepted operation
instead of starting a second one.` Reuse a key only to retry the same call.

**No reversal.** Neither add nor remove records a reversal, and
`rollback_apply` cannot undo one: removing what was added would also remove
members that were in the audience before the add, so the opposite call is not
a restore. An audience create records none either.

### Conversion measurement

| Tool | API | Arguments (defaults) |
|------|-----|----------------------|
| `chatgpt_ads_pixels_list` | `GET /conversions/pixels` | `limit` (50) |
| `chatgpt_ads_pixels_create` | `POST /conversions/pixels` | `name` (required) |
| `chatgpt_ads_conversion_events_list` | `GET /conversions/event_settings` | `limit` (50) |
| `chatgpt_ads_conversion_events_create` | `POST /conversions/event_settings` | `name`, `event_type`, `source_id` (required), `custom_event_name` |
| `chatgpt_ads_conversions_report` | `POST /conversions/insights` | `period` (`last_30d`), `level` (`campaign`), `entity_ids`, `group_by_entity`, `time_granularity`, `breakdown`, `attribution_time_basis`, `attribution_window_days`, `view_through_attribution_window_days`, `include_events`, `event_names`, `include_zero_rows` |

- **Pixels.** A pixel is a web conversion source. The create always sends
  `client_type` `web`, the only documented value. Its answer carries `id`,
  the source id an event setting takes, and `pixel_id`, which initialises the
  JavaScript Pixel and is not what an event setting takes. A pixel cannot be
  edited or deleted through the API.
- **Event settings are permanent.** The API has no endpoint to edit or delete
  a conversion event setting, so the create's description leads with that.
  `name` is 1 to 1000 characters on one line (the platform states a minimum
  of 1 and no maximum). `event_type` is held to the id pattern; the documented
  values are `app_installed`, `app_opened`, `appointment_scheduled`,
  `checkout_started`, `contents_viewed`, `custom`, `items_added`,
  `lead_created`, `order_created`, `page_viewed`, `registration_completed`,
  `subscription_created` and `trial_started`. `custom_event_name` is required
  when `event_type` is `custom` and refused otherwise: 1 to 64 letters,
  digits, `_` or `-`, starting and ending with a letter or digit (the platform
  also refuses a standard event name and lowercases it). `source_id` is one
  pixel `id`, sent as `source_ids: [source_id]`; the reference documents a
  `Client data source not found` answer, which means `source_id` is not a
  pixel of this account. `attribution_window_days` is not an argument: every
  setting is created with 30, the only value the reference documents, since
  a setting cannot be changed afterwards.
- **No idempotency key.** Neither create carries one; a lost answer ends with
  the "may have been applied" sentence. List before creating again. A new
  conversion event setting can be missing from
  `chatgpt_ads_conversion_events_list` for a few seconds after its create.
- **The feature gate.** The reference says the pixel collection answers
  `404 Not found` when conversions are not enabled for the account. On the
  pixel list and create mureo reports a 404 as the `feature_not_enabled`
  result. A 404 from the event settings or the conversion report keeps its
  ordinary meaning (an `API error: HTTP 404 ...` text). An account that has
  no pixel and no event setting yet is not gated for that reason: its lists
  answer empty and its creates are accepted.
- **The report.** `chatgpt_ads_conversions_report` returns the platform's
  answer unchanged: `data` rows with `entity_id`, `date` / `country` /
  `device` where they apply, `conversions` (click plus view-through within the
  chosen windows), `click_through_conversions`, `view_through_conversions` and
  `order_created_attributed_sales`; with `include_events`, per-event
  `attributed_events`; plus `count` and `account_currency`. It is a `POST`
  that changes nothing, so it carries `readOnlyHint` and is retried like a
  `GET`, and its failures never say a change may have been applied.
- **Report arguments.** `period`, `level`, `time_granularity` and
  `attribution_window_days` take the names and values of
  `chatgpt_ads_insights_report` (`level` is `campaign`, `ad_group` or `ad`).
  The period becomes one `time_ranges` entry, the JSON-encoded string the
  reference shows, `{"type":"unix_range","start":"<unix seconds>","end":"<unix seconds>"}`,
  with whole days in the account's time zone and an exclusive end.
  `entity_ids` is 1 to 100 ids of that level (the reference states no limit;
  this bounds one request body) and is required while `group_by_entity` is
  true (the platform default); with `group_by_entity` false and no
  `entity_ids` the rows cover the whole account. `breakdown` is `country` or
  `device`; `attribution_time_basis` is `ad_event_time` or `conversion_time`;
  `view_through_attribution_window_days` is 0 or 1; `include_events` sends
  `include: ["attributed_events"]`; `event_names` (1 to 500 names of up to
  256 characters, not all spaces) is refused unless `include_events` is true;
  `include_zero_rows` is a boolean. Only the keys given are sent, plus
  `aggregation_level` and `time_ranges`, so every platform default applies
  otherwise.
- **Report limits.** There is no pagination: more than 2,000 summary rows (or
  2,000 event rows) is refused by the platform with 413, so narrow
  `entity_ids` or the period. Conversions are attributed late and recent days
  can still grow; allow at least one day.
- **Against the insights report.** Use `chatgpt_ads_insights_report` for
  conversions next to spend and delivery, and this report for goal totals,
  click- and view-through counts, sales and event details. The insights
  `conversions` metric also counts click plus view-through; compare the two
  only over the same entities, dates, windows and time basis.

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
| `chatgpt_ads_ad_groups_update_bid` | the same tool with the prior bidding config; a prior fixed bid (`target_strategy` / `target_micros`) as `fixed_bid` with the prior amount | anything present in the prior config fails the tool's check: a `billing_event_type` other than `impression` or `click`, a strategy that is neither one the tool takes nor `automated_bid`, an unusable `max_bid_micros`, `target_micros` or multiplier, or more than 1000 multipliers; or the config has a `target_strategy` mureo does not know (anything but `target_cpc` with click billing), carries both shapes (`target_*` with `strategy` or `max_bid_micros`), or has a key mureo does not know |
| `chatgpt_ads_account_daily_spend_limit_set` | the same tool with the prior amount | there was no daily rule before (removing a limit is a different operation), more than one, or its amount fails the tool's check |

For a campaign update, a field whose prior value fails the check is left out
of the reversal and named in its caveats, and `rollback_plan_get` reports the
plan as partial. A budget, a bidding config and an ad group name are restored
whole or not at all: the platform replaces the whole budget and bidding
objects, so a partial one would remove a limit or a multiplier. A budget
reversal that sets a lower lifetime budget than the call did carries the
caveat that the platform rejects a lifetime budget below the amount already
spent. A prior `automated_bid` config is restored without `strategy` or
`max_bid_micros`, and a prior fixed bid, which reads back as
`target_strategy` `target_cpc` and `target_micros`, is restored as
`fixed_bid` with `max_bid_micros` set to the prior amount. A config with a
`target_strategy` mureo does not know, with both shapes, or with a key mureo
does not know records no reversal: the platform replaces the whole object,
so dropping or guessing a key would restore a different config. A `null`
value is treated as absent. If the prior read fails or times out, the
change goes ahead without a reversal; only the error's type is logged.

Creates, archives and the image upload are recorded in `action_log` too, with
no reversal (see [Undoing a create](#creating) and [Archiving](#archiving)).
An archive names the archived entity. A create cannot name the entity it
creates, whose id exists only once the call returns: an ad group create
records its `campaign_id`, an ad create its ad group, and a campaign create
and the image upload no entity. An audience add or remove names the
audience (`entity_type: "audience"`) and records no reversal; an audience,
pixel or event-setting create names no entity and records none either.

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
the ad account's time zone. The default `last_7d` covers seven complete days
ending yesterday, so it leaves out today; pass `today` for changes made today.

## Change import

`mureo_external_changes_import` records changes made on the ad account
outside mureo (in Ads Manager, or by another API client) into `action_log`,
from the same audit log. The provider registers this change feed together
with its tools, so it answers for `plugin:mureo-chatgpt-ads:chatgpt_ads`; with
`MUREO_DISABLE_CHATGPT_ADS=1` there is no feed either. See
[change-import.md](change-import.md) for how an import is recorded and
deduplicated.

- **What is imported.** Each audit-log entry whose `ts` falls inside the
  window the pass asked for becomes one `external_change:<TYPE>` entry, where
  `<TYPE>` is the entry's `obj_type` in upper snake case (`Campaign` →
  `CAMPAIGN`, `AdGroup` → `AD_GROUP`). The operation is the first word of
  `audit_log_type` (`update_campaign` → `UPDATE`), and the changed fields are
  the keys of `changes` that hold a value: at most 20 changed fields per
  entry, in the order the entry gives them, each made of letters, digits, `_`
  and `.` (at most 64 characters). The audit log lists every field of the
  resource in `changes` and leaves the ones the entry did not change null, so
  a null key is not a changed field. Ids and the actor are kept only when
  made of letters, digits and `_ . : @ -` (at most 200 characters). The
  free-text `item_name` is never
  copied, and `actor_type` is not read: it names the kind of actor, not the
  client that made the change. An entry without a usable `ts`, or dated
  outside the window, is skipped and counted in a note; one entry dated in
  the future would otherwise move the next pass's start past now.
- **Which account.** One API key reads one ad account, and the key is shared
  by every workspace on the machine. The account id recorded for this
  platform in STATE.json must be the `id` that `chatgpt_ads_account_get`
  returns. Before reading the audit log the feed reads `GET /ad_account`; when
  the key reads a different account nothing is imported and the outcome is
  `unavailable` (the reason names neither id). When STATE.json records no
  account id the check is skipped, and the result carries a note saying so.
- **Oldest first, 1,000 per pass.** The window is read oldest first and one
  pass imports at most 1,000 entries. A capped pass says `truncated: true`,
  and its note names the time it read through. Run the import again: the
  next pass continues from the newest change imported. mureo's own changes
  are not stored, so they do not move that point; if the next pass stops at
  the same point, pass the `since` the note gives. A capped pass whose
  entries did not come back oldest first, or whose first 1,000 entries cannot
  be dated, imports nothing and is an `error` outcome asking for an explicit
  `since` that leaves at most 1,000 entries in the window.
- **Which entries carry an identity.** A campaign entry names `campaign_id`,
  an ad group entry names the ad group (`entity_type: "ad_group"`,
  `entity_id`, plus its `campaign_id`), and an ad entry names `ad_id` (plus
  its `campaign_id`, not its ad group). These are the identities the change
  tools record, so mureo's own pause / enable, archive, budget, bid, name
  and schedule changes are recognised by tool name, target and a 10-minute
  window, as [change-import.md](change-import.md#deduplication) describes,
  and are not imported a second time.
- **Creates and archives.** A create's record cannot name the entity it
  created, so the audit-log entry for a campaign, ad group or ad mureo
  created is imported as an external change. This is the deduper's verdict
  on a plausible entry; the platform does not publish how it reports a
  create. The audit log reports an archive as a `status` change, and the
  archive tools' names read as a status change too, so mureo's own archive
  of a campaign, ad group or ad is recognised by tool name, target and the
  window like its pause / enable. An archive entry that names no changed
  field reads as a campaign, ad group or ad edit rather than a status
  change, so it is imported as external for all three.
- **What the audit log holds.** An entry made with an API key carries the
  same `actor_type` as one made in Ads Manager and the user's id as its
  actor, so the entry does not tell the two apart. Image uploads and
  custom-audience creates are not recorded. A pause and an archive are
  reported with a `status` key in `changes`; a pause of a campaign that is
  already paused is recorded as an entry with no changed field, so that
  entry is imported as an external change even when mureo sent the pause.
  `obj_type` values include `Campaign`, `AdGroup`, `Ad`, `AdAccount`,
  `AdsManagerApiKey`, `ClientDataSource` and `ConversionEventSetting`.
- **Always imported as external.** An account-level change (the daily
  spending limit) and an entry on any resource other than a campaign, ad
  group or ad carry no identity, so they are imported as external even when
  mureo made them. The deduper also reads the changed-field names, so an
  entry with more than 20 changed fields can be imported as external even
  when mureo made it.
- **What it cannot see.** The platform publishes neither how long it keeps
  audit-log entries nor which changes it records, so an empty window is not
  evidence that the account was static. Every result says so in its notes.
- **Failures.** A missing or rejected key, an ad-account answer without a
  usable `id`, and every API error are reported as the platform's `error`
  outcome, never as a quiet window.

## Periods and time zone

`period` takes the same vocabulary as the Meta Ads tools: `today`,
`yesterday`, `last_7d`, `last_14d`, `last_30d`, `last_90d` (N complete days
ending yesterday), `this_month`, `last_month`, or an explicit
`YYYY-MM-DD..YYYY-MM-DD` (both ends inclusive). `today` and `this_month` are
accepted: the platform answers 200 to a range whose last day is today.

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
| Budgets and bid amounts on campaigns and ad groups, the account's spending limits, and every amount a change tool sends to the platform | **micros** of the account currency (1,000,000 = one unit) |
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
| `max_cpc_bid_per_ad_group`, `max_bid_amount_per_ad_set` | `bidding_config.max_bid_micros` | audience multipliers, the strategies without a bid, and impression billing, where the amount is per impression |

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
  it twice. Some `POST`s are retried on a 5xx like a `GET`: the ad preview,
  which changes no campaign, ad group or ad (it saves an expiring preview
  snapshot), the conversion report, which only reads, and a create or an
  audience add or remove, which carries an idempotency key (see
  [Creating](#creating) and [Custom audiences](#custom-audiences)). A numeric `Retry-After` header of up to 30 seconds sets the wait;
  a longer one is not waited for, and the answer is reported at once. Without
  a usable header the wait doubles from 1 second. A 429 or 5xx on the last
  attempt is reported as an API error. A transport error is not retried.
- **Page sizes.** Pages are requested at the API's maximum or the rows still
  needed, whichever is smaller: 500 for campaigns, ad groups, ads, custom
  audiences, pixels and conversion event settings, 100 for audit logs, 2000
  for insights.
- **Reporting window.** At most 365 days. The API keeps non-hourly delivery
  reporting for the most recent 365 days, and conversion metrics need full
  days in the account's time zone and at most 365 days.
- **Timeout.** 30 seconds per request, and 120 seconds for the whole tool
  call (every page, retry and backoff together). A call that runs out of time
  is reported as `API error: the call did not finish within 120 seconds`;
  for a change tool the text goes on to say the change may have been applied,
  and for a create or an audience add or remove it names the idempotency key
  to repeat it with (see
  [Failures](#failures)). The read that records a reversal has its own
  15-second limit.
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
| A change tool that ends in a 5xx, a non-JSON success body, a transport error or the call deadline | the same text, ending `The change may have been applied; check the account before retrying.` |
| A create that ends the same way | the same text, ending with the repeat-with-`idempotency_key` sentence, which returns the earlier entity when the platform can see the earlier create (see [Creating](#creating)) |
| An audience add or remove that ends the same way | the same text, ending with the repeat-with-`idempotency_key` sentence for operations (see [Custom audiences](#custom-audiences)) |
| A 404 on the pixel list or create | `{"status": "error", "error": "feature_not_enabled", "detail": ...}`: conversions are not enabled for this ad account |
| An event-setting create answered `Client data source not found` | the ordinary `API error:` text: `source_id` is not a pixel of this account |
| An image file that is missing, not a regular file, of another type, whose content is not identified as the format its extension names, over 30MB, or named with `..` | `FileNotFoundError` or `ValueError` from mureo's shared image check, before any request |
| An identifier file that is missing, not a regular file, not `.txt` / `.csv`, over 2 MiB, named with `..` or not UTF-8 | `FileNotFoundError` or `ValueError`, before any request; no byte of the file is quoted |
| An identifier file with an invalid line | `ValueError` naming the count and up to 10 line numbers, before any request; no line is quoted |
| An identifier file with no identifiers, or more than 10,000 distinct ones | `ValueError`: `file_path holds no identifiers; give one per line`, or the distinct count and a request to split the file, before any request |
| `chatgpt_ads_account_daily_spend_limit_set` with more than one daily rule | `{"status": "refused", "error": "multiple_daily_spend_limits", "detail": ...}`, before any change |
| `chatgpt_ads_account_daily_spend_limit_set` whose spending-limits answer is not a JSON object, or carries an unusable `revision` or daily rules in an unexpected shape | text `API error: ...; nothing was changed`, before any change |
| `chatgpt_ads_campaigns_update_budget` that would change the budget type | `{"status": "refused", "error": "budget_kind_change", "detail": ...}`, before any change; `budget_unreadable` when the current budget holds neither amount |
| A missing or malformed argument | `ValueError`, raised before any request |

The platform answers an error as
`{"error": {"message", "type", "param", "code"}}`. `code` can be `null`: some
400 answers carry `type` `server_error`, no code, and a message that itself
starts with the status (`"400: ..."`), so the text reads
`API error: HTTP 400: 400: ...`. Examples of codes are `invalid_api_key`
(401) and `integer_above_max_value` (400, a `limit` above the maximum). The
message of a plain 404 reads `Not found: <id>`.

A change that ends in a 5xx, a non-JSON success body, a transport error or
the deadline may have reached the platform before the answer was lost. Read
the entity with the matching `*_get` tool before trying again; repeating the
call blind could apply it twice. A create is the exception: repeat it with the
`idempotency_key` its error names and the same arguments. If that repeat fails
too, list by name (`chatgpt_ads_campaigns_list`, `chatgpt_ads_ad_groups_list`
or `chatgpt_ads_ads_list` with `name`) before creating with a new key. An
audience add or remove is repeated the same way, with its key, the same
arguments and the same file. An audience, pixel or event-setting create has
no key: list the audiences, pixels or event settings before creating again.

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

- **Editing after creation.** No tool changes an ad's creative, a
  campaign's targeting or an ad group's context hints once created, or a
  date-range spending limit, or removes the account's daily limit. Creatives
  other than the single-image chat card (multi-image, product templates) are
  not offered.
- **Partner access.** No OAuth and no partner key: mureo never sends the
  `OpenAI-Ad-Account` header, so it reads only the ad account an advertiser
  key is scoped to.
- **Other APIs.** No bulk API, hotel feeds or product feeds.
- **Other audience and conversion operations.** No audience replace, merge or
  archive, no cancel or resume of an audience operation, no operation
  listing, no audience created from a file, no conversion API keys and no
  read of recent conversion events.
- **Other insights options.** No segments, filters, sorting, zero-row
  includes, hourly or monthly buckets, or attribution time basis.
- **BYOD.** ChatGPT Ads is not part of BYOD mode.
- **mureo-only analysis.** Anomaly baselines and the other analyses keyed to
  the Google Ads and Meta Ads tools do not exist for ChatGPT Ads; treat
  findings as advisory.

## Not yet exercised against a live account

The tools are written against the published API reference and OpenAPI
document, tested against recorded answers and exercised against a live ad
account. These points remain unverified:

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
- **Fixed bid with impression billing.** A fixed bid on click billing reads
  back as `target_strategy` `target_cpc` with `target_micros`. What a fixed
  bid on impression billing reads back as is unverified, so such a config
  records no reversal.
- **`expected_revision`.** How the platform answers when the revision has
  moved on since mureo read it, and whether an account with no daily rule
  accepts revision 0.
- **The fields a reversal reads.** `status` values `active` and `paused`,
  `start_time` / `end_time` at the top level of a campaign, `budget` and
  `bidding_config` in the shapes above, and `amount_micros` on a daily rule
  are as the API reference and the OpenAPI document give them. If a live
  answer differs, the affected change is recorded without a reversal, or
  with a caveat, and no error is raised.
- **Repeating a pause or an activate.** Whether a pause on an ad group or an
  ad that is already paused, or an activate on an entity that is already
  active, is accepted unchanged or answered with an error.
- **Audit-log vocabulary.** The reference documents one example entry, a
  campaign rename (`audit_log_type` `update_campaign`, `obj_type` `Campaign`,
  `changes` with a `name` key). The ad group and ad spellings change import
  expects (`AdGroup`, `Ad`) are the ones the audit log uses (see
  [Change import](#change-import)); the full set of
  `audit_log_type` and `obj_type` values and of the keys of `changes` is not
  published.
- **An activate in the audit log.** Whether an activate is reported with a
  `status` key in `changes`, as a pause and an archive are. If it is not,
  mureo's own enable is not recognised and is imported as an external
  change.
- **Audience operations.** How long an add or remove stays `processing`, and
  how the platform answers an inline request near the 10,000-identifier
  limit.
- **Repeating an add or remove.** Whether a repeat with the same key returns
  the first operation as the reference describes.
- **The conversions feature gate.** Whether the pixel list and create answer
  `404 Not found`, and nothing else, on an account for which the platform
  has not enabled conversions, and
  what the event-setting paths answer then (mureo reports their answer as an
  ordinary error), as well as the status of a `Client data source not found`
  answer.
- **`source_ids`.** The reference says a pixel's `id` (not its `pixel_id`) is
  the value an event setting takes; this is not confirmed against a live
  account.
- **`time_ranges`.** The report sends the JSON-encoded string form of the
  reference's example, with string Unix seconds and an exclusive end; other
  forms are not tried.
- **Ordering.** Whether `order=asc` returns entries oldest first across
  pages, which a capped change-import pass relies on to leave only newer
  entries for the next pass. A capped pass that sees entries out of order
  imports nothing.
- **Account id.** That the `id` of `GET /ad_account` is the value to compare
  with the account id recorded in STATE.json; change import refuses the
  window when the two differ.
- **Idempotent replay.** Whether a create still in flight is already
  visible to a repeat: mureo's own retry of a 5xx waits its normal backoff
  first, and the platform documents the replay only for a matching earlier
  create that is visible to it.
- **Upload size limit.** The platform documents no maximum image size; the
  30MB cap is mureo's. A smaller platform limit would surface as an API
  error.
- **Archive cascade.** Whether archiving an ad group archives its ads.

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
