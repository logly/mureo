---
name: _mureo-amazon-ads
description: "Amazon Ads (official MCP, bridged by mureo): query campaigns, ad groups, ads and targets, run reports, and manage account access under Amazon's own tool names."
metadata:
  version: 0.10.45
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo --help"
---

# Amazon Ads (official MCP, bridged by mureo)
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, security rules, and
> output format — and specifically its **Plugin platforms (third-party
> providers)** section, which is the contract Amazon rides: honest scope,
> declaration-first guardrails, `action_log` promotion, structural strategy
> parity for mutations. This file does not repeat any of it.

> **Canonical platform key: `plugin:mureo-amazon-ads-bridge:amazon_ads`.** Use it verbatim
> wherever a mureo surface names a platform — STATE.json `platforms`,
> `mureo_state_upsert_campaign(platform="plugin:mureo-amazon-ads-bridge:amazon_ads")`,
> `mureo_state_platform_metrics_set`, `action_log`, `mureo_analytics_*`.
> Amazon's own tools carry no mureo platform key; joining on anything else
> (`amazon`, `amazon_ads`, a tool namespace) silently fails to join.
>
> The older `plugin:mureo-amazon-ads-bridge` form (before the key carried
> the provider, logly/mureo#537) **stays valid on read** — it resolves to
> the same platform, and the dashboard still labels it *Amazon Ads*. If
> STATE.json already holds an entry under it, **keep writing that key**:
> a second entry for one ad account is what double-counts it on the
> Reports card, and mureo never merges or rewrites either entry.

> **There is no `mureo amazon-ads …` CLI command.** The only Amazon CLI is
> `mureo amazon refresh-manifest` (rebuilds the tool list). Every operation
> below is an **MCP tool** — call it directly.

## What this surface is — and is not

- **Amazon's own tool names, forwarded verbatim.** mureo renames nothing (same
  treatment as the other official MCPs).
- **Naming convention: `<namespace>-<verb>_<resource>` — the namespace is
  separated by a HYPHEN**, with underscores inside each part
  (`campaign_management-query_ad`, `account_management-query_advertiser_account`).
  Native mureo tools are all-underscore (`google_ads_campaigns_list`), so any
  name matching, prefix filter, or "which platform is this tool" heuristic must
  account for the hyphen.
- **The tool list is the operator's own manifest**, written by
  `mureo amazon refresh-manifest` next to `credentials.json` and read by the
  mureo MCP server at start. 85 tools on the reference account. The surface can
  drift: if a tool named here is absent from the session, **say so and suggest
  re-running `mureo amazon refresh-manifest`** rather than guessing a name.
  mureo warns once per process when the served manifest is older than its
  staleness threshold — read that warning as "everything below may be out of
  date", and re-check before reporting a capability as missing.
- **No tool declares an `outputSchema`** (0 of 85). Response shapes are learned
  by calling. Only two envelopes are confirmed from live responses:
  `campaign_management-query_campaign` → `{"campaigns": [...]}` and
  `campaign_management-query_ad` → `{"ads": [...]}`. For everything else, read
  the actual response before you describe it — never state a field name you
  have not seen come back.
- **Analytics are advisory.** No mureo analytics module ships for Amazon
  (issue #120): anomaly detection, `result_indicator` CV-mismatch, RSA-asset
  audit and rule-based scoring do not exist here. Report
  `analytics_not_available_for_plugin:mureo-amazon-ads-bridge:amazon_ads` instead of
  inventing a heuristic from the tool schemas. The platform-agnostic
  `analysis_anomalies_check` **does** apply — see `../_mureo-shared/SKILL.md`
  → *Generic anomaly check*.
- **Guardrails are EXACT on the known money tools, with the scan as a floor
  under everything.** A bridged manifest carries no mureo declarations, so
  mureo holds them itself: the **13 money-carrying tools** below are declared
  by exact argument PATH —
  `budgets[].budgetValue.monetaryBudgetValue.monetaryBudget.value`,
  `budgetCaps.countryMonetaryBudgetSettings.<CC>.value`, `bid.bid`,
  `bid.{baseBid,defaultBid,maxAverageBid}` and their
  `marketplaceSettings[]` overrides — and `STRATEGY.md` `## Guardrails`
  budget/bid caps are enforced on those paths, not inferred. The **best-effort
  pattern scan still runs underneath them**, and the larger amount wins, so a
  money field that drifted shape or that Amazon added after the snapshot falls
  back to that best-effort cover — a declaration can only ever raise what gets
  checked, never lower it. That cover is a pattern, not a guarantee: it finds
  the field when the new name still looks like money (`budget` / `spend` /
  `bid`, or a plain `value` / `amount` under one), so a leaf renamed to
  something outside that vocabulary is missed exactly as it was before the
  paths were declared. Any OTHER Amazon tool gets that same pattern scan on
  its own. An oversized or deeper-than-scannable payload **fails closed** with
  a message naming the cause. So: a cap on the tools listed below is exact and
  quotes the declared path when a value is unreadable; on any other Amazon
  write call it **is** strong but **not guaranteed**, say so in the output, and
  verify the resulting values after the first mutation.

## Calling requirements (get these wrong and the query fails outright)

Every point below is verified against a live account.

1. **`body.accessRequestedAccount` is REQUIRED** on the account-scoped tools.
   It is a oneOf — exactly one of `{"advertiserAccountId": "<id>"}` **or**
   `{"profileId": "<id>"}`.
2. **`body.adProductFilter.include` is REQUIRED** on the `campaign_management`
   query tools and accepts **EXACTLY ONE** of `AMAZON_DSP`,
   `SPONSORED_BRANDS`, `SPONSORED_DISPLAY`, `SPONSORED_PRODUCTS`,
   `SPONSORED_TELEVISION` ("Only one ad product can be queried at a time").
   **A full sweep is therefore one call per ad product** — budget the turns for
   it, and state in your output which products you actually swept.
3. **A global account must be queried by `profileId`.** When
   `account_management-query_advertiser_account` reports
   `isGlobalAccount: true`, querying by `advertiserAccountId` fails with
   `FIELD_VALUE_IS_INVALID` — *"Multi marketplace query requests only support
   query by primary resource id"*. Pass a `profileId` (one marketplace) and
   repeat per marketplace.
4. **State vocabulary is `ARCHIVED` / `ENABLED` / `PAUSED`** (`stateFilter.include`,
   and the resource's own `state`). `ACTIVE` is Meta's word and `REMOVED` is
   Google's — neither exists here.
5. **Paging**: `maxResults` plus `nextToken`; keep following `nextToken` until
   it is absent, or say that you truncated.
6. Closing the MCP session can log `Session termination failed: 403`. It
   appears *after* the call result and is harmless — do not report it as a
   failed operation.
7. **A rejected call comes back as `API error: <code>: <message>`.** Amazon
   returns its failures as ordinary content, flagged with the MCP protocol's
   `isError` (live-verified 2026-08-05 for both the
   `{"code": "FIELD_VALUE_IS_INVALID", ...}` envelope and the
   `Validation failed: ...` text); mureo normalises those into the same
   `API error: ...` result a built-in tool returns. Such a call changed
   **nothing** and is deliberately **not** recorded in `action_log` — fix the
   arguments from the message and retry, and never report the attempt as a
   completed change. Two things to expect when you read one:
   - **The `code` usually arrives as `***`.** An LwA authorization code has
     the same `"code": "..."` shape, so mureo masks the value rather than
     guessing which it is. **When a message is present it is the diagnosis** —
     work from it and do NOT tell the operator that the code was hidden or
     that information is missing. Example: `API error: ***: Multi marketplace
     query requests only support query by primary resource id` is
     requirement 3 above, and you can act on it as-is.
   - **`API error: Amazon returned no error message; raw body: ...` means
     there is genuinely nothing to read** — the code is masked and Amazon sent
     no message. Say exactly that, quote the raw body, and do not invent a
     cause. Re-read the tool's `inputSchema` and the *Calling requirements*
     above, state your best hypothesis as a hypothesis, and ask the operator
     before retrying a mutation.
   - **A `…<truncated>` suffix means the body was longer than mureo will put
     in your context.** Report what you have and say it was truncated.
   - **The converse holds too**: a response that merely *looks*
     error-flavoured (`{"code": "PARTIAL", ...}`) but is not flagged is a
     success, and a mutation returning it IS recorded.

Minimal working query body:

```json
{
  "body": {
    "accessRequestedAccount": {"profileId": "<profileId>"},
    "adProductFilter": {"include": ["SPONSORED_PRODUCTS"]},
    "stateFilter": {"include": ["ENABLED"]}
  }
}
```

## Step 0 — resolve the account

- `account_management-query_advertiser_account` with `{"body": {}}` returns
  (live-verified) `{"advertiserAccounts": [{"advertiserAccountId": "...",
  "alternateIds": [{"countryCode": "JP", "entityId": "ENTITY...",
  "profileId": "..."}], "displayName": "...", "isGlobalAccount": true}]}`.
  The `profileId`s live in `alternateIds` — **one per marketplace**.
- Pick the scope from `isGlobalAccount`: `false` → either id works;
  `true` → `profileId` only (requirement 3 above).
- `ads_accounts-list_ads_accounts` / `ads_accounts-get_ads_account` enumerate
  the accounts reachable by the token; `manager_accounts-get_manager_accounts`
  and `account_management-query_account_link` cover Manager-Account structures.

## Tool surface — 85 tools by namespace

| Namespace | Tools | What it is for | The ones you actually use |
|-----------|-------|----------------|---------------------------|
| `campaign_management` | 32 | Campaigns, ad groups, ads, targets, portfolios, ad associations | `query_campaign`, `query_ad_group`, `query_ad`, `query_target`, `query_portfolio`, `check_product_eligibility`, `update_campaign_state`, `update_campaign_budget`, `update_ad`, `update_ad_group`, `update_target_bid`, `create_campaign`, `create_singleshot_sp_campaign`, `add_country_campaign` |
| `amc` | 10 | Amazon Marketing Cloud workflows and ad-hoc SQL | `get_workflows`, `get_data_sources`, `execute_query`, `execute_workflow`, `get_workflow_execution_status`, `get_workflow_execution_download_url` |
| `account_management` | 7 | Advertiser accounts, account links, account settings | `query_advertiser_account`, `query_account_link`, `update_advertiser_account` |
| `reporting` | 6 | Async performance / product / inventory reports | `create_campaign_report`, `create_product_report`, `create_report`, `retrieve_report`, `delete_report` |
| `manager_accounts` | 4 | Manager accounts and their links | `get_manager_accounts`, `associate_accounts`, `disassociate_accounts` |
| `billing` | 4 | Invoices, billing profiles, billing notifications | `list_invoices`, `query_billing_notifications`, `list_invoice_summaries` |
| `user_permissions` / `user_invitations` / `user_invitation` / `users` / `user_roles` | 3 / 3 / 2 / 1 / 1 | Who can access the account | `users-list_users`, `user_permissions-list_user_permissions`, `user_invitations-list`, `user_roles-list_user_roles` |
| `ads_accounts` | 3 | The advertising accounts behind the token | `list_ads_accounts`, `get_ads_account` |
| `promotions` | 3 | Promotion offers, rewards, code redemption | `query_promotion_offers`, `query_promotion_rewards` |
| `eligibility` | 2 | Program / product advertising eligibility | `programs`, `product_list` |
| `terms_token` | 2 | Advertising-terms acceptance token | `get_terms_token`, `create_terms_token` |
| `advertiser_product_group_eligibility` | 2 | Product-group eligibility requests (e.g. ADSP) | `query`, `create` |

Read vs write is declared per tool through `annotations.readOnlyHint`: **83 of
the 85 declare it** (32 `true`, 51 `false`) and **2 declare nothing at all** —
`billing-list_invoice_summaries` and `billing-list_billing_profile_usages`
carry no `annotations` object. Two consequences worth knowing before you call
something whose name and behaviour disagree:

- **An explicit hint always wins; only an ABSENT hint falls through to the
  name.** For the two undeclared billing tools mureo consults the shared
  read-shaped-name vocabulary (`is_read_only_tool_name`, matched per
  hyphen-delimited segment, prefixes `list_` / `get_` / `query_` / …): both
  segments start with `list_`, so both are classified as **reads** — they stay
  in the plugin audit log, are not promoted into `action_log`, and are not
  registered for the guardrail argument scan.
- `amc-execute_query` **declares `readOnlyHint: false`**, so it is classified
  as a **mutation** despite running a query: confirm before calling it, and
  expect it in `action_log` with an observation window.

## Reading campaigns, ad groups, ads and targets

All four are `campaign_management-query_*`, all require
`accessRequestedAccount` + `adProductFilter` (see *Calling requirements*), and
all take the same filter shape: `{"<filter>": {"include": [...]}}`.

- `query_campaign` — filters: `campaignIdFilter`, `portfolioIdFilter`,
  `goalFilter`, `nameFilter` (`include` + `queryTermMatchType`:
  `BROAD_MATCH` | `EXACT_MATCH`), `marketplaceScopeFilter`
  (`GLOBAL` | `SINGLE_MARKETPLACE`), `stateFilter`. Envelope `{"campaigns": [...]}`
  (live-verified).
- `query_ad_group` — same pattern, scoped by `campaignIdFilter`.
- `query_ad` — filters: `adIdFilter`, `adGroupIdFilter`, `campaignIdFilter`,
  `nameFilter`, `marketplaceScopeFilter`, `stateFilter`. Envelope
  `{"ads": [...]}` (live-verified).
- `query_target` — keywords, products, categories and audiences.
- `query_ad_association` — which ads are attached to which ad groups.

**Per-item field names are NOT live-verified** (both arrays came back empty on
the reference account, and no tool declares an output schema). What the
write-side input schemas imply — treat as a starting expectation, confirm
against the first real response before reporting field names to the operator:
campaign `campaignId` / `state` / `name` / `budgets`; ad group `adGroupId` /
`state` / `name` / `bid`; ad `adId` / `state` / `name` / `creative` /
`marketplaces`; target `targetId` / `bid`.

## Performance data (reporting is asynchronous)

There is **no synchronous performance tool** on this surface. The flow is
create → poll → retrieve:

```
Step 1: Request the report
  -> reporting-create_campaign_report {body: {accessRequestedAccounts: [...],
       reports: [{format: "CSV"|"GZIP_JSON"|..., periods: [{datePeriod:
       {startDate, endDate}}], query: {fields: [...]}, currencyOfView}]}}
  (reporting-create_product_report / -create_inventory_report / -create_report
   are the same shape for other report families.)

Step 2: Retrieve it
  -> reporting-retrieve_report {body: {reportIds: [...]}}   (repeat until ready)

Step 3: Clean up when you generated a one-off
  -> reporting-delete_report {body: {reportIds: [...]}}
```

`reports` and `periods` are single-element arrays (`minItems`/`maxItems` = 1) —
one report, one date period per call. `query.fields` is required and free-form:
ask for the metric names the operator's report family defines; do not invent
them. For AMC-level analysis use `amc-execute_query` (ad-hoc SQL) or
`amc-execute_workflow` + `amc-get_workflow_execution_status` +
`amc-get_workflow_execution_download_url`.

## Ad-level delivery state — ONE state, and it is the configured one

Amazon exposes **exactly one state per ad**: `state`, one of `ENABLED` /
`PAUSED` / `ARCHIVED`. That is the **configured** state — what the ad is set
to. **There is no separate serving, delivery or policy-review status in this
surface**, unlike Meta's `effective_status` / `configured_status` pair.

When you persist Amazon ads into STATE.json (`ads[]` on the campaign
snapshot — `/sync-state` and `/daily-check` both do this):

- Record Amazon's `state` as the ad's **`status`** (verbatim, per
  `../_mureo-shared/SKILL.md` → *Status vocabulary contract*).
- **Leave `effective_status` unset.** `AdState` requires only `ad_id`
  precisely so a platform with no delivery status omits the field instead of
  having one invented for it. Copying `state` into `effective_status` would
  manufacture a serving fact Amazon never reported.
- Consequently Amazon's **effective status is unknown**, not "delivering".
  `state: ENABLED` means "not paused"; it is not evidence that the ad served.
  If you need delivery evidence, get it from spend / impressions in a report —
  and if you have none, say the delivery state is unknown.

## Writes — confirm, then gate

Everything in `campaign_management` other than the `query_*` / `check_*` tools
mutates the account, as do the `create_*` / `update_*` / `delete_*` /
`associate_*` / `redeem_*` tools in the other namespaces. All of them are
subject to the same structural handling as a built-in write (see
`../_mureo-shared/SKILL.md` → *Mutating plugin tools — structural strategy
parity*): **confirm with the operator before the call**, gate against
`STRATEGY.md` (Operation Mode, Goals, `## Guardrails`), and expect the
successful call to land in `action_log` under
`platform="plugin:mureo-amazon-ads-bridge:amazon_ads"` with an observation window. A
call Amazon rejects (`API error: ...`, requirement 7 above) lands nowhere —
it changed nothing, so report it as a failed attempt, not as a change.

The **13 money-carrying tools** — the ones mureo declares exact money paths
for, so their `## Guardrails` caps are enforced exactly (all
`campaign_management-`):

- **Campaign budgets** — `update_campaign_budget`, `update_campaign`,
  `create_campaign`, `create_singleshot_sp_campaign`
  (`budgets[].budgetValue.monetaryBudgetValue.monetaryBudget.value`, the
  `marketplaceSettings[]` per-marketplace overrides beside it, and the
  `flights[].budget…` variant on `create_campaign` / `update_campaign`)
- **Per-country campaign budgets** — `add_country_campaign`
  (`budgetCaps.countryMonetaryBudgetSettings.<CC>.value` — show every country
  you are changing, not just the total)
- **Ad-group budgets** — `create_ad_group` / `update_ad_group`
  (`budgets[].budgetValue…monetaryBudget.value` and
  `optimization.budgetSettings.dailyMinSpendValue`)
- **Portfolio budgets** — `create_portfolio`, `create_singleshot_portfolio`,
  `update_portfolio` (`budget.budgetValue.monetaryBudgetValue…value`)
- **Target bids** — `update_target_bid` / `-update_target` /
  `-create_target` (`bid.bid`, `bid.marketplaceSettings[].bid`)
- **Ad-group bids** — `update_ad_group` / `-create_ad_group`
  (`bid.baseBid` / `bid.defaultBid` / `bid.maxAverageBid` and
  `bid.marketplaceSettings[].defaultBid`), and
  `create_singleshot_sp_campaign` (`bid.marketplaceSettings[].defaultBid`)

Always show the current value before the new one — read it back with the
matching `query_*` tool first.

Pausing / resuming: `campaign_management-update_campaign_state` at campaign
level, `campaign_management-update_ad` (its `ads[].state`) at ad level. Deletes
(`delete_campaign`, `delete_ad_group`, `delete_ad`, `delete_target`) are
destructive and cascade — `delete_campaign` removes its ad groups, ads and
targets. Prefer `PAUSED` unless the operator explicitly asked to delete, and
never assume a delete is reversible: only mureo's built-in allow-listed
operations are auto-reversible, and Amazon's are not among them.

## Important notes

- **One ad product per query call.** An "all campaigns" answer that swept only
  `SPONSORED_PRODUCTS` is wrong for an account that also runs Sponsored Brands
  or DSP. Either sweep all five or name the ones you covered.
- **Money is a plain currency amount.** The budget schema calls its `value`
  "the monetary amount of the budget cap in the given currency", and no
  `micros` / cents-style field appears anywhere in the manifest — so do not
  apply Google's micros or Meta's cents convention here. `currencyOfView` on a
  report changes only the view.
- **Marketplaces are first-class.** A global account is a set of marketplaces;
  campaign, ad and budget shapes carry `marketplaces` /
  `marketplaceScope` / `marketplaceSettings` / per-country budget caps.
  Say which marketplace a number belongs to.
- **Never present an inferred field name as observed.** With no output schemas,
  the honest move when you have not called the tool yet is "the response shape
  is not documented; I will read it from the call".
