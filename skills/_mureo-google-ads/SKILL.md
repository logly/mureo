---
name: _mureo-google-ads
description: "Google Ads: Manage campaigns, ad groups, ads, keywords, budgets, and performance analysis."
metadata:
  version: 0.17.3
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo --help"
---

# Google Ads (v23)
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, global flags, and security rules.

> **There is no `mureo google-ads …` CLI command.** Every operation below is an
> **MCP tool** (`google_ads_*`). Call the tool directly — never run or suggest a
> `mureo google-ads campaigns-list`-style shell command (it does not exist and
> will error, which is NOT a mureo bug).

## No customer_id? (recovery)

Every Google Ads tool needs a `customer_id` (the target account). It is resolved
from the stored credentials (set by `mureo auth setup`). When it is missing a
tool returns **`customer_id is required. Provide it as a parameter or configure
it …`** — auth is fine, only the *account* is unset (a common state when the
operator finished sign-in but skipped account selection).

When you see that error, **recover automatically — do NOT ask the operator to
look up the ID in the Google Ads UI, and do NOT fall back to a CSV / "ask the
agency"**:

1. Call **`google_ads_accounts_list`** — it needs **no** `customer_id` and
   returns every account reachable by the login.
2. **Exactly one account** → use its id as `customer_id` on the retried call and
   tell the operator which account you selected.
3. **Several accounts** → show the list and ask the operator which one to use.
4. **Zero accounts** → the login can't reach any Google Ads account; tell the
   operator to re-run `mureo auth setup` (or grant the account access), and that
   `customer_id` can be set there or via `GOOGLE_ADS_CUSTOMER_ID` (plus
   `GOOGLE_ADS_LOGIN_CUSTOMER_ID` for an MCC).

To persist the choice so it survives across sessions, point the operator at
`mureo auth setup` (account picker) or the `configure` UI's env writer
(`GOOGLE_ADS_CUSTOMER_ID`); passing `customer_id` per call works for the
immediate request but is not remembered.

## Tool Summary

| # | Tool Name | Category | Type | Description |
|---|-----------|----------|------|-------------|
| 1 | `google_ads_campaigns_list` | Campaign | Read | List campaigns |
| 2 | `google_ads_campaigns_get` | Campaign | Read | Get campaign details |
| 3 | `google_ads_campaigns_create` | Campaign | Write | Create a campaign (search or display, via `channel_type`) |
| 4 | `google_ads_campaigns_update` | Campaign | Write | Update campaign settings |
| 5 | `google_ads_campaigns_update_status` | Campaign | Write | Change campaign status |
| 6 | `google_ads_campaigns_diagnose` | Campaign | Read | Diagnose delivery issues |
| 7 | `google_ads_ad_groups_list` | Ad Group | Read | List ad groups |
| 8 | `google_ads_ad_groups_create` | Ad Group | Write | Create an ad group |
| 9 | `google_ads_ad_groups_update` | Ad Group | Write | Update ad group settings |
| 10 | `google_ads_ads_list` | Ad | Read | List ads |
| 11 | `google_ads_ads_create` | Ad | Write | Create an RSA ad |
| 12 | `google_ads_ads_update` | Ad | Write | Update ad content |
| 13 | `google_ads_ads_update_status` | Ad | Write | Change ad status |
| 14 | `google_ads_ads_policy_details` | Ad | Read | Get ad policy approval details |
| 15 | `google_ads_keywords_list` | Keyword | Read | List keywords |
| 16 | `google_ads_keywords_add` | Keyword | Write | Add keywords |
| 17 | `google_ads_keywords_remove` | Keyword | Write | Remove a keyword |
| 18 | `google_ads_keywords_suggest` | Keyword | Read | Suggest keywords via Keyword Planner |
| 19 | `google_ads_keywords_diagnose` | Keyword | Read | Diagnose keyword quality scores |
| 20 | `google_ads_keywords_pause` | Keyword | Write | Pause a keyword |
| 21 | `google_ads_keywords_audit` | Keyword | Read | Audit keyword performance and quality |
| 22 | `google_ads_keywords_cross_adgroup_duplicates` | Keyword | Read | Find duplicate keywords across ad groups |
| 23 | `google_ads_negative_keywords_list` | Negative KW | Read | List negative keywords |
| 24 | `google_ads_negative_keywords_add` | Negative KW | Write | Add negative keywords to a campaign |
| 25 | `google_ads_negative_keywords_remove` | Negative KW | Write | Remove a negative keyword |
| 26 | `google_ads_negative_keywords_add_to_ad_group` | Negative KW | Write | Add negative keywords to an ad group |
| 27 | `google_ads_negative_keywords_suggest` | Negative KW | Read | Suggest negative keywords from search terms |
| 28 | `google_ads_budget_get` | Budget | Read | Get campaign budget |
| 29 | `google_ads_budget_update` | Budget | Write | Update daily budget |
| 30 | `google_ads_budget_create` | Budget | Write | Create a new campaign budget |
| 31 | `google_ads_accounts_list` | Account | Read | List accessible Google Ads accounts |
| 32 | `google_ads_search_terms_report` | Search Terms | Read | Search terms report |
| 33 | `google_ads_search_terms_review` | Search Terms | Read | Review search terms with rule-based scoring |
| 34 | `google_ads_search_terms_analyze` | Search Terms | Read | Analyze search terms with intent classification |
| 35 | `google_ads_sitelinks_list` | Extension | Read | List sitelink extensions |
| 36 | `google_ads_sitelinks_create` | Extension | Write | Create a sitelink extension |
| 37 | `google_ads_sitelinks_remove` | Extension | Write | Remove a sitelink extension |
| 38 | `google_ads_callouts_list` | Extension | Read | List callout extensions |
| 39 | `google_ads_callouts_create` | Extension | Write | Create a callout extension |
| 40 | `google_ads_callouts_remove` | Extension | Write | Remove a callout extension |
| 41 | `google_ads_conversions_list` | Conversion | Read | List conversion actions |
| 42 | `google_ads_conversions_get` | Conversion | Read | Get conversion action details |
| 43 | `google_ads_conversions_performance` | Conversion | Read | Get conversion performance metrics |
| 44 | `google_ads_conversions_create` | Conversion | Write | Create a conversion action |
| 45 | `google_ads_conversions_update` | Conversion | Write | Update a conversion action |
| 46 | `google_ads_conversions_remove` | Conversion | Write | Remove a conversion action |
| 47 | `google_ads_conversions_tag` | Conversion | Read | Get conversion tracking tag snippet |
| 48 | `google_ads_recommendations_list` | Targeting | Read | List optimization recommendations |
| 49 | `google_ads_recommendations_apply` | Targeting | Write | Apply an optimization recommendation |
| 50 | `google_ads_device_targeting_get` | Targeting | Read | Get device targeting settings |
| 51 | `google_ads_device_targeting_set` | Targeting | Write | Set device targeting bid adjustments |
| 52 | `google_ads_bid_adjustments_get` | Targeting | Read | Get bid adjustment settings |
| 53 | `google_ads_bid_adjustments_update` | Targeting | Write | Update bid adjustments |
| 54 | `google_ads_location_targeting_list` | Targeting | Read | List location targeting criteria |
| 55 | `google_ads_location_targeting_update` | Targeting | Write | Update location targeting |
| 56 | `google_ads_schedule_targeting_list` | Targeting | Read | List ad schedule targeting |
| 57 | `google_ads_schedule_targeting_update` | Targeting | Write | Update ad schedule targeting |
| 58 | `google_ads_change_history_list` | Targeting | Read | List account change history |
| 59 | `google_ads_performance_report` | Analysis | Read | Performance report |
| 60 | `google_ads_performance_analyze` | Analysis | Read | Analyze performance trends and anomalies |
| 61 | `google_ads_cost_increase_investigate` | Analysis | Read | Investigate sudden cost increases |
| 62 | `google_ads_health_check_all` | Analysis | Read | Comprehensive account health check |
| 63 | `google_ads_ad_performance_compare` | Analysis | Read | Compare ad performance across variants |
| 64 | `google_ads_ad_performance_report` | Analysis | Read | Detailed ad-level performance report |
| 65 | `google_ads_network_performance_report` | Analysis | Read | Network-level performance breakdown |
| 66 | `google_ads_budget_efficiency` | Analysis | Read | Analyze budget utilization efficiency |
| 67 | `google_ads_budget_reallocation` | Analysis | Read | Suggest budget reallocation across campaigns |
| 68 | `google_ads_auction_insights_get` | Analysis | Read | Get auction insights (competitor analysis) |
| 69 | `google_ads_auction_insights_analyze` | Analysis | Read | Auction insights analysis |
| 70 | `google_ads_rsa_assets_analyze` | Analysis | Read | Analyze RSA asset performance |
| 71 | `google_ads_rsa_assets_audit` | Analysis | Read | Audit RSA assets for best practices |
| 72 | `google_ads_cpc_detect_trend` | Analysis | Read | Detect CPC trend direction |
| 73 | `google_ads_device_analyze` | Analysis | Read | Device performance analysis |
| 74 | `google_ads_btob_optimizations` | B2B | Read | Get B2B-specific optimization suggestions |
| 75 | `google_ads_landing_page_analyze` | Creative | Read | Analyze landing page relevance and quality |
| 76 | `google_ads_creative_research` | Creative | Read | Research competitive creative strategies |
| 77 | `google_ads_monitoring_delivery_goal` | Monitoring | Read | Monitor campaign delivery against goals |
| 78 | `google_ads_monitoring_cpa_goal` | Monitoring | Read | Monitor CPA against target goals |
| 79 | `google_ads_monitoring_cv_goal` | Monitoring | Read | Monitor conversion volume against goals |
| 80 | `google_ads_monitoring_zero_conversions` | Monitoring | Read | Detect campaigns with zero conversions |
| 81 | `google_ads_capture_screenshot` | Capture | Read | Capture a screenshot of a URL |
| 82 | `google_ads_assets_upload_image` | Asset | Write | Upload image as Google Ads asset |
| 83 | `google_ads_ads_create_display` | Ad | Write | Create an RDA (responsive display ad); image files are uploaded automatically |
| 84 | `google_ads_demographic_targeting_list` | Targeting | Read | List demographic criteria (age/gender/parental status/income) |
| 85 | `google_ads_audience_targeting_list` | Targeting | Read | List audience criteria (user lists, interests, custom/combined audiences) |
| 86 | `google_ads_image_assets_list` | Asset | Read | List image assets with names and dimensions |
| 87 | `google_ads_negative_placements_list` | Negative Placement | Read | List excluded websites / apps / app categories (campaign + ad group) |
| 88 | `google_ads_negative_placements_add` | Negative Placement | Write | Exclude websites / apps / app categories (batch, one revertible unit) |
| 89 | `google_ads_negative_placements_remove` | Negative Placement | Write | Lift exclusions by criterion_id (batch) |
| 90 | `google_ads_asset_group_assets_list` | Performance Max | Read | List the headlines / long headlines / descriptions linked to a P-MAX asset group |
| 91 | `google_ads_asset_group_assets_replace` | Performance Max | Write | Swap one P-MAX headline / long headline / description for new text |

## API Resources

### campaigns

- `list` -- List all campaigns in the account. Response includes `channel_type` ("SEARCH" | "DISPLAY" | ...) so you can tell search and display campaigns apart at a glance.
  ```
  Required: customer_id (string)
  Optional: status_filter (string: "ENABLED" | "PAUSED")
  ```

- `get` -- Get detailed information about a specific campaign. Response includes `channel_type`.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `create` -- Create a search or display campaign. **Requires user confirmation.**
  ```
  Required: customer_id, name (string)
  Optional: bidding_strategy (string: "MAXIMIZE_CLICKS" | "MAXIMIZE_CONVERSIONS" | "TARGET_CPA" | ...),
            budget_id (string),
            channel_type (string: "SEARCH" | "DISPLAY"; defaults to "SEARCH")
  ```
  Note: For display campaigns, create the campaign with `channel_type="DISPLAY"`, then create an ad group, then create the display ad via `ads.create_display`.

- `update` -- Update campaign settings (name, bidding strategy). **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string)
  Optional: name (string), bidding_strategy (string)
  ```

- `update_status` -- Change campaign status. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, status (string: "ENABLED" | "PAUSED" | "REMOVED")
  ```

- `diagnose` -- Comprehensive delivery diagnosis. Returns serving status, policy issues, budget constraints.
  ```
  Required: customer_id, campaign_id (string)
  ```

### ad_groups

- `list` -- List ad groups, optionally filtered by campaign.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), status_filter (string)
  ```

- `create` -- Create an ad group within a campaign. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, name (string)
  Optional: cpc_bid_micros (integer, in micros: 1,000,000 = 1 currency unit)
  ```

- `update` -- Update ad group settings. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id (string)
  Optional: name (string), status (string: "ENABLED" | "PAUSED"), cpc_bid_micros (integer)
  ```
  Note: `cpc_bid_micros` is only accepted when the parent campaign uses a manual bidding strategy (`MANUAL_CPC`, `MANUAL_CPM`, `MANUAL_CPV`, `ENHANCED_CPC`). If the campaign uses an automated strategy (MAXIMIZE_CLICKS, MAXIMIZE_CONVERSIONS, TARGET_CPA, TARGET_ROAS, etc.), the tool returns a clear validation error — manual bids at the ad group level are not supported under automated bidding.

### ads

- `list` -- List ads, optionally filtered by ad group. Returns `headlines` and `descriptions` for both RSA and RDA. For RDAs, the response also includes `long_headline`, `business_name`, `marketing_images`, `square_marketing_images`, and `logo_images` (lists of asset resource names).
  Performance Max campaigns return **no rows here** — P-MAX has no `ad_group_ad`. Its ad copy lives on asset groups: use `asset_group_assets.list` / `asset_group_assets.replace` below.
  ```
  Required: customer_id (string)
  Optional: ad_group_id (string), status_filter (string)
  ```

- `create` -- Create a Responsive Search Ad (RSA). **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id (string),
            headlines (array of strings, 3-15 items),
            descriptions (array of strings, 2-4 items)
  Optional: final_url (string), path1 (string), path2 (string)
  ```
  Note: For Responsive Display Ads, use `ads.create_display` instead.

- `update` -- Update RSA ad content. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, ad_id (string)
  Optional: headlines (array of strings), descriptions (array of strings)
  ```
  Note: This tool supports Responsive Search Ads (RSA) only. Calling it on a Responsive Display Ad (RDA) fails fast with a clear error — RDA text updates are not implemented; recreate the ad via `ads.create_display` instead.

- `update_status` -- Change ad status. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, ad_id, status (string: "ENABLED" | "PAUSED")
  ```

- `policy_details` -- Get ad policy approval details and disapproval reasons.
  ```
  Required: customer_id, ad_group_id, ad_id (string)
  ```

### asset_group_assets (Performance Max ad copy)

A Performance Max campaign has no `ad_group_ad`, so `ads.list` / `ads.update`
never see it. Its headlines, long headlines and descriptions are assets linked
to an **asset group**. These two tools are the P-MAX ad-copy surface — do not
tell an operator that swapping P-MAX copy is unsupported by the API; it is not.

- `list` -- List the HEADLINE / LONG_HEADLINE / DESCRIPTION assets linked to
  Performance Max asset groups. Returns one entry per link:
  `{resource_name, field_type, status, asset_id, text, asset_group_id,
  asset_group_name, campaign_id, campaign_resource_name}`, in the order the API
  returned them and not deduplicated. Start here when you have a campaign id but
  no asset group id.
  ```
  Required: customer_id (string)
  Optional: asset_group_id (string), campaign_id (string)
  ```

- `replace` -- Swap one headline / long headline / description for new text.
  **Requires user confirmation.**
  ```
  Required: customer_id, asset_group_id (string),
            field_type (string: "HEADLINE" | "LONG_HEADLINE" | "DESCRIPTION"),
            old_asset_id (string, from asset_group_assets.list),
            new_text (string)
  ```
  A Google Ads text `Asset` is immutable, so this is not an update: it creates a
  new `Asset`, links it under the same `field_type`, and removes the old link —
  all three in ONE atomic mutate, so the asset group's asset count for that
  field type never dips below the Performance Max minimum. Display-width limits
  (a full-width character counts as two): HEADLINE 30, LONG_HEADLINE 90,
  DESCRIPTION 90. Text already linked under the same `field_type` is refused
  before any write (Google rejects a duplicate link), as is an `old_asset_id`
  that is not linked under that `field_type`. The old `Asset` itself is not
  deleted, only its link to this asset group. Not automatically reversible: to
  undo, call `replace` again with the old text, which `list` reported.

### keywords

- `list` -- List keywords with performance metrics.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), ad_group_id (string), status_filter (string)
  ```

- `add` -- Add keywords to an ad group. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id (string),
            keywords (array of {text: string, match_type?: "BROAD" | "PHRASE" | "EXACT"})
  ```
  Note: `match_type` defaults to `BROAD` if omitted.

- `remove` -- Remove a keyword by criterion ID. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, criterion_id (string)
  ```

- `suggest` -- Get keyword suggestions from Keyword Planner.
  ```
  Required: customer_id (string), seed_keywords (array of strings)
  Optional: language_id (string, default: "1005" = Japanese),
            geo_id (string, default: "2392" = Japan)
  ```

- `diagnose` -- Diagnose keyword quality scores and delivery status for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `pause` -- Pause a keyword. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, criterion_id (string)
  ```

- `audit` -- Audit keyword performance and quality scores across a campaign.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS"), target_cpa (number)
  ```
  `period` takes any date range constant or an explicit `BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'` range.

- `cross_adgroup_duplicates` -- Find duplicate keywords across ad groups in a campaign.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```
  `period` takes any date range constant or an explicit `BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'` range.

### negative_keywords

- `list` -- List campaign-level negative keywords.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `add` -- Add negative keywords to a campaign. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string),
            keywords (array of {text: string, match_type?: "BROAD" | "PHRASE" | "EXACT"})
  ```

- `remove` -- Remove a negative keyword. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, criterion_id (string)
  ```

- `add_to_ad_group` -- Add negative keywords to an ad group. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id (string),
            keywords (array of {text: string, match_type?: "BROAD" | "PHRASE" | "EXACT"})
  ```

- `suggest` -- Suggest negative keywords based on search term analysis.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS"), target_cpa (number), ad_group_id (string)
  ```
  Period-over-period tool: fixed-length windows only (`LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`, or an explicit `BETWEEN` range).

### negative_placements

Delivery-surface exclusions: excluded **websites**, **mobile apps** and **mobile app
categories**. This is the placement side of exclusion; `negative_keywords` above is the
search-term side. Both campaign-level and ad group-level criteria are supported — supply
**exactly one** of `campaign_id` / `ad_group_id`.

A `add` call is recorded in STATE.json's `action_log` with an `observation_due` window and
is reversible as **one unit** via `rollback_apply`, however many exclusions it carried. That
is the whole point of routing placement hygiene through mureo: a bulk exclusion pass that
kills delivery can be tied to a date and undone, instead of being reconstructed by hand.

- `list` -- List excluded websites / apps / app categories. Returns level ("campaign" |
  "ad_group"), criterion_id, type, criterion_type, value, display_name, and the parent
  campaign / ad group ids.
  ```
  Required: customer_id (string)
  Optional: campaign_id, ad_group_id (string)
  ```

- `add` -- Exclude websites / apps / app categories. **Requires user confirmation.** Always
  show the count and the level before writing — a large batch can take a Display campaign
  to zero impressions.

  **Size it first (#547).** Call `analysis_exclusion_impact_preview` with
  `tool="google_ads_negative_placements_add"` and the exact `arguments` you are about to
  send. It reports the share of the last N days' impressions / clicks / cost / conversions
  those placements carried, both for this batch and cumulatively for every standing
  exclusion once it lands, plus `would_block`. Show the operator the share, not just the
  count. If STRATEGY.md `## Guardrails` carries `max_delivery_share_removed_pct` (or
  `max_cumulative_delivery_share_removed_pct`), an over-cap batch is **refused before it
  reaches the API** and the refusal names the measured share.
  ```
  Required: customer_id (string), exactly one of campaign_id / ad_group_id (string),
            placements (array of {type: "website" | "mobile_application" | "mobile_app_category",
                                  value: string})
  ```
  `value` formats: website = domain or URL; mobile_application = platform-prefixed app id
  (`1-` iOS, `2-` Android); mobile_app_category = category constant id or its
  `mobileAppCategoryConstants/<id>` resource name.

- `remove` -- Lift exclusions by criterion_id. **Requires user confirmation.** Ids are
  verified first: anything that is not a negative placement criterion at the named level is
  reported under `skipped` and never removed.
  ```
  Required: customer_id (string), exactly one of campaign_id / ad_group_id (string),
            criterion_ids (array of string)
  ```

### budget

- `get` -- Get the budget attached to a campaign, including its type. Returns id, name, daily_budget(_micros), total_budget / total_amount_micros (null unless a CUSTOM_PERIOD total budget), period (DAILY / CUSTOM_PERIOD), delivery_method, status, reference_count.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `update` -- Update the daily and/or total budget amount. **Requires user confirmation.** Always show current vs. new amount. The period is immutable -- total amounts only apply to CUSTOM_PERIOD budgets.
  ```
  Required: customer_id, budget_id (string), and one of amount / amount_micros / total_amount / total_amount_micros
  ```

- `create` -- Create a new campaign budget. **Requires user confirmation.** Pass period=CUSTOM_PERIOD with total_amount(_micros) for a campaign-lifetime total budget (immutable after creation); otherwise supply the daily amount.
  ```
  Required: customer_id, name (string), and one of amount / total_amount / total_amount_micros
  Optional: period (DAILY | CUSTOM_PERIOD)
  ```

### accounts

- `list` -- List all accessible Google Ads accounts under the manager account.
  ```
  Required: (none)
  ```

### search_terms

- `report` -- Get search terms report showing actual queries that triggered ads.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), ad_group_id (string), period (string, default: "LAST_30_DAYS")
  ```

- `review` -- Multi-rule review of search terms with add/exclude recommendations.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_7_DAYS"), target_cpa (number)
  ```

- `analyze` -- Analyze search terms with intent classification and clustering.
  ```
  Required: customer_id, campaign_id (string)
  ```

### sitelinks

- `list` -- List sitelink extensions for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `create` -- Create a sitelink extension. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, link_text, final_url (string)
  ```

- `remove` -- Remove a sitelink extension. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, extension_id (string)
  ```

### callouts

- `list` -- List callout extensions for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `create` -- Create a callout extension. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, callout_text (string)
  ```

- `remove` -- Remove a callout extension. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, extension_id (string)
  ```

### conversions

- `list` -- List all conversion actions in the account.
  ```
  Required: customer_id (string)
  ```

- `get` -- Get details of a specific conversion action.
  ```
  Required: customer_id, conversion_action_id (string)
  ```

- `performance` -- Get conversion performance metrics across campaigns.
  ```
  Required: customer_id (string)
  ```

- `create` -- Create a new conversion action. **Requires user confirmation.**
  ```
  Required: customer_id, name, type (string)
  ```

- `update` -- Update a conversion action. **Requires user confirmation.**
  ```
  Required: customer_id, conversion_action_id (string)
  ```

- `remove` -- Remove a conversion action. **Requires user confirmation.**
  ```
  Required: customer_id, conversion_action_id (string)
  ```

- `tag` -- Get the conversion tracking tag (JavaScript snippet) for a conversion action.
  ```
  Required: customer_id, conversion_action_id (string)
  ```

### targeting

- `recommendations.list` -- List optimization recommendations from Google.
  ```
  Required: customer_id (string)
  ```

- `recommendations.apply` -- Apply an optimization recommendation. **Requires user confirmation.**
  ```
  Required: customer_id, recommendation_id (string)
  ```

- `device_targeting.get` -- Get device targeting bid adjustment settings.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `device_targeting.set` -- Set device targeting bid adjustments. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, device_type, bid_modifier (string/number)
  ```

- `bid_adjustments.get` -- Get bid adjustment settings for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `bid_adjustments.update` -- Update bid adjustments. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string)
  ```

- `location_targeting.list` -- List location targeting criteria.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `location_targeting.update` -- Update location targeting settings. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string)
  ```

- `schedule_targeting.list` -- List ad schedule targeting rules.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `schedule_targeting.update` -- Update ad schedule targeting. **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string)
  ```

- `change_history.list` -- List account change history (who changed what, when).
  ```
  Required: customer_id (string)
  ```

- `demographic_targeting.list` -- List explicit demographic criteria (age range, gender, parental status, income). Excluded segments have negative=true; segments with no explicit criterion are targeted by default and not returned.
  ```
  Required: customer_id (string)
  Optional: ad_group_id (string), campaign_id (string)
  ```

- `audience_targeting.list` -- List audience-type criteria (user interests, user lists, custom/combined audiences). value is the criterion's resource name.
  ```
  Required: customer_id (string)
  Optional: ad_group_id (string), campaign_id (string)
  ```

### analysis & reporting

- `performance.report` -- Get performance metrics aggregated by campaign.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), period (string, default: "LAST_30_DAYS")
  ```
  Period options: `TODAY`, `YESTERDAY`, `THIS_WEEK_SUN_TODAY`, `THIS_WEEK_MON_TODAY`, `LAST_BUSINESS_WEEK`, `LAST_WEEK_SUN_SAT`, `LAST_WEEK_MON_SUN`, `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`, `THIS_MONTH`, `LAST_MONTH` — or an explicit range: `BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`

- `performance.analyze` -- Analyze performance trends, detect anomalies, and surface insights.
  ```
  Required: customer_id (string)
  ```

- `cost_increase.investigate` -- Investigate sudden cost increases and identify root causes.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `health_check.all` -- Run a comprehensive account health check across all campaigns.
  ```
  Required: customer_id (string)
  ```

- `ad_performance.compare` -- Compare ad performance across variants in an ad group.
  ```
  Required: customer_id, ad_group_id (string)
  ```

- `ad_performance.report` -- Get detailed ad-level performance report.
  ```
  Required: customer_id (string)
  ```

- `network_performance.report` -- Get performance breakdown by network (Search, Display, etc.).
  ```
  Required: customer_id (string)
  ```

- `budget.efficiency` -- Analyze budget utilization efficiency across campaigns.
  ```
  Required: customer_id (string)
  ```

- `budget.reallocation` -- Suggest budget reallocation across campaigns based on performance.
  ```
  Required: customer_id (string)
  ```

- `auction_insights.get` -- Get auction insights with competitor impression share and overlap rate.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `auction_insights.analyze` -- Analyze auction insights: impression share, overlap rate, top-of-page rate, and competitor domains.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

- `rsa_assets.analyze` -- Analyze RSA asset (headline/description) performance ratings.
  ```
  Required: customer_id, ad_group_id (string)
  ```

- `rsa_assets.audit` -- Audit RSA assets for best practices and coverage gaps.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `cpc.detect_trend` -- Detect CPC trend direction (rising / stable / falling) using linear regression on daily CPC data. Also detects sudden spikes and week-over-week changes.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

- `device.analyze` -- Compare performance across devices (Desktop / Mobile / Tablet). Shows CPA, CVR, CTR per device, detects CPA gaps, and identifies wasted spend on zero-conversion devices.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

### b2b

- `btob.optimizations` -- Get B2B-specific optimization suggestions (lead quality, audience targeting, etc.).
  ```
  Required: customer_id (string)
  ```

### creative

- `landing_page.analyze` -- Analyze landing page relevance and quality signals for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `creative.research` -- Research competitive creative strategies and ad copy patterns.
  ```
  Required: customer_id (string)
  ```

### monitoring

- `monitoring.delivery_goal` -- Monitor campaign delivery pace against goals.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `monitoring.cpa_goal` -- Monitor CPA against target goals and alert on deviations.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `monitoring.cv_goal` -- Monitor conversion volume against goals.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `monitoring.zero_conversions` -- Detect campaigns with zero conversions in recent periods.
  ```
  Required: customer_id (string)
  ```

### capture

- `capture.screenshot` -- Capture a screenshot of a URL (useful for landing page audits).
  ```
  Required: url (string)
  ```

### assets

- `assets.upload_image` -- Upload a local image file as a Google Ads asset.
  ```
  Required: customer_id, file_path (string)
  ```

- `image_assets.list` -- List image assets with names, dimensions, and serving URLs.
  ```
  Required: customer_id (string)
  Optional: limit (integer 1-1000, default: 100)
  ```

## Common Workflows

### 1. Performance Check

A typical daily performance check flow:

```
Step 1: List campaigns to identify active ones
  -> google_ads_campaigns_list {customer_id, status_filter: "ENABLED"}

Step 2: Get overall performance report
  -> google_ads_performance_report {customer_id, period: "LAST_7_DAYS"}

Step 3: Run comprehensive health check
  -> google_ads_health_check_all {customer_id}

Step 4: For underperforming campaigns, run diagnostics
  -> google_ads_campaigns_diagnose {customer_id, campaign_id}

Step 5: Check keyword quality scores
  -> google_ads_keywords_diagnose {customer_id, campaign_id}

Step 6: Analyze device performance for CPA gaps
  -> google_ads_device_analyze {customer_id, campaign_id}

Step 7: Monitor conversion goals
  -> google_ads_monitoring_zero_conversions {customer_id}
```

### 2. Negative Keyword Addition

When cleaning up wasted spend from irrelevant search terms:

```
Step 1: Get search terms report
  -> google_ads_search_terms_report {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Or use automated review for suggestions
  -> google_ads_search_terms_review {customer_id, campaign_id, target_cpa: 3000}

Step 3: Analyze search terms with intent classification
  -> google_ads_search_terms_analyze {customer_id, campaign_id}

Step 4: Get AI-suggested negative keywords
  -> google_ads_negative_keywords_suggest {customer_id, campaign_id}

Step 5: Review current negative keywords to avoid duplicates
  -> google_ads_negative_keywords_list {customer_id, campaign_id}

Step 6: Add negative keywords (CONFIRM WITH USER)
  -> google_ads_negative_keywords_add {customer_id, campaign_id, keywords: [...]}
```

### 3. New Campaign Creation

Full campaign setup from scratch:

```
Step 1: Create a budget
  -> google_ads_budget_create {customer_id, name, amount}

Step 2: Create the campaign (omit channel_type or set "SEARCH" for a search campaign)
  -> google_ads_campaigns_create {customer_id, name, bidding_strategy, budget_id}

Step 3: Create ad groups
  -> google_ads_ad_groups_create {customer_id, campaign_id, name}

Step 4: Add keywords to each ad group
  -> google_ads_keywords_add {customer_id, ad_group_id, keywords: [...]}

Step 5: Create RSA ads for each ad group
  -> analysis_tracking_consistency_check {ads: <existing ads in the campaign>, planned_ads: [...]}
     (tracking-parameter pre-flight -- see ../_mureo-shared/SKILL.md; stop on any finding)
  -> google_ads_ads_create {customer_id, ad_group_id, headlines: [...], descriptions: [...], final_url}

Step 6: Add campaign-level negative keywords
  -> google_ads_negative_keywords_add {customer_id, campaign_id, keywords: [...]}

Step 7: Add sitelink extensions
  -> google_ads_sitelinks_create {customer_id, campaign_id, link_text, final_url}

Step 8: Add callout extensions
  -> google_ads_callouts_create {customer_id, campaign_id, callout_text}

Step 9: Set up conversion tracking
  -> google_ads_conversions_create {customer_id, name, type}

Step 10: Enable the campaign
  -> google_ads_campaigns_update_status {customer_id, campaign_id, status: "ENABLED"}
```

### 3b. New Display Campaign + Responsive Display Ad

Display campaigns use a different `channel_type` and require image assets.
mureo uploads the local image files automatically before creating the ad.

```
Step 1: Create a budget
  -> google_ads_budget_create {customer_id, name, amount}

Step 2: Create a DISPLAY campaign
  -> google_ads_campaigns_create {
       customer_id, name, channel_type: "DISPLAY",
       bidding_strategy: "MAXIMIZE_CONVERSIONS", budget_id
     }

Step 3: Create an ad group inside the display campaign
  -> google_ads_ad_groups_create {customer_id, campaign_id, name}

Step 4: Create the responsive display ad
  -> google_ads_ads_create_display {
       customer_id, ad_group_id,
       headlines: [...], long_headline, descriptions: [...],
       business_name,
       marketing_image_paths: ["/path/to/marketing-1200x628.jpg"],
       square_marketing_image_paths: ["/path/to/square-1200x1200.jpg"],
       logo_image_paths: ["/path/to/logo.png"],   # optional
       final_url
     }

Step 5: Enable the campaign
  -> google_ads_campaigns_update_status {customer_id, campaign_id, status: "ENABLED"}
```

Constraints (RDA):
- Headlines: 1-5, each ≤30 display width
- Long headline: required, ≤90 display width
- Descriptions: 1-5, each ≤90 display width
- Business name: required, ≤25 display width
- Marketing images (1.91:1): 1-15, 3+ recommended for delivery quality
- Square marketing images (1:1): 1-15, 3+ recommended
- Logo images: optional, up to 5
- The target ad group must belong to a DISPLAY campaign — mureo verifies this before any upload happens to avoid orphaned assets.
- If image upload or ad creation fails partway through, an `RDAUploadError` is raised that includes the resource names of any orphaned uploaded assets so the agent can clean them up.

### 4. Budget Adjustment

Safe budget change workflow:

```
Step 1: Get current budget
  -> google_ads_budget_get {customer_id, campaign_id}

Step 2: Analyze budget efficiency
  -> google_ads_budget_efficiency {customer_id}

Step 3: Get reallocation suggestions
  -> google_ads_budget_reallocation {customer_id}

Step 4: Update budget (CONFIRM WITH USER)
  -> google_ads_budget_update {customer_id, budget_id, amount: 6000}
```

### 5. Delivery Troubleshooting

When a campaign is not getting impressions:

```
Step 1: Check campaign status and settings
  -> google_ads_campaigns_get {customer_id, campaign_id}

Step 2: Run comprehensive delivery diagnosis
  -> google_ads_campaigns_diagnose {customer_id, campaign_id}

Step 3: Check keyword quality and delivery status
  -> google_ads_keywords_diagnose {customer_id, campaign_id}

Step 4: Check ad policy details for disapprovals
  -> google_ads_ads_policy_details {customer_id, ad_group_id, ad_id}

Step 5: Check CPC trends (are bids competitive?)
  -> google_ads_cpc_detect_trend {customer_id, campaign_id}

Step 6: Analyze auction insights (competitor landscape)
  -> google_ads_auction_insights_analyze {customer_id, campaign_id}

Step 7: Monitor delivery pace
  -> google_ads_monitoring_delivery_goal {customer_id, campaign_id}

Step 8: Review budget constraints
  -> google_ads_budget_get {customer_id, campaign_id}
```

### 6. Competitive Analysis

Understanding the competitive landscape:

```
Step 1: Analyze auction insights
  -> google_ads_auction_insights_analyze {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Get auction insights data
  -> google_ads_auction_insights_get {customer_id, campaign_id}

Step 3: Detect CPC trend (rising CPC may indicate increased competition)
  -> google_ads_cpc_detect_trend {customer_id, campaign_id}

Step 4: Investigate cost increases
  -> google_ads_cost_increase_investigate {customer_id, campaign_id}

Step 5: Research competitive creative strategies
  -> google_ads_creative_research {customer_id}

Step 6: Get keyword suggestions to find new opportunities
  -> google_ads_keywords_suggest {customer_id, seed_keywords: ["..."]}
```

### 7. RSA Optimization

Improving responsive search ad performance:

```
Step 1: Analyze RSA asset performance
  -> google_ads_rsa_assets_analyze {customer_id, campaign_id}

Step 2: Audit RSA assets for best practices
  -> google_ads_rsa_assets_audit {customer_id, campaign_id}

Step 3: Compare ad variants
  -> google_ads_ad_performance_compare {customer_id, ad_group_id}

Step 4: Check landing page relevance
  -> google_ads_landing_page_analyze {customer_id, url}
```

### 8. Account Audit

Comprehensive account review:

```
Step 1: List all accessible accounts
  -> google_ads_accounts_list {}

Step 2: Run health check
  -> google_ads_health_check_all {customer_id}

Step 3: Audit keywords
  -> google_ads_keywords_audit {customer_id, campaign_id}

Step 4: Find duplicate keywords
  -> google_ads_keywords_cross_adgroup_duplicates {customer_id, campaign_id}

Step 5: Review change history
  -> google_ads_change_history_list {customer_id}

Step 6: Check optimization recommendations
  -> google_ads_recommendations_list {customer_id}
```

## Important Notes

- **Micros**: Some values (e.g., `cpc_bid_micros`) are in micros where 1,000,000 = 1 currency unit. For example, 500,000 micros = 0.50 in the account currency.
- **Period values**: Use Google Ads date range constants like `LAST_7_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`, `THIS_MONTH`. For a window no constant reaches — a single past calendar month, say — pass an explicit range in GAQL spelling instead: `period: "BETWEEN '2026-05-01' AND '2026-05-31'"` (both endpoints inclusive, account time zone). The Meta Ads `'YYYY-MM-DD..YYYY-MM-DD'` form is Meta-only and is rejected here.
- **`LAST_90_DAYS` uses the server date**: every other constant is resolved by Google Ads in the account's reporting time zone, but `LAST_90_DAYS` has no API constant — mureo expands it into the 90 days ending yesterday on the server's date. When the server and the account sit in different time zones the window edges can differ by a day. Pass an explicit `BETWEEN` range when the exact boundary matters.
- **Period-over-period tools** (`search_terms.review`, `performance.analyze`, `negative_keywords.suggest`) also read the equal-length window immediately before the one you ask for, so they take only fixed-length windows: `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`, or an explicit `BETWEEN` range. Calendar constants such as `THIS_MONTH` are refused rather than quietly replaced with a different window.
- **customer_id**: Always a 10-digit string without dashes (e.g., `"1234567890"`, not `"123-456-7890"`).
- **RSA limits**: Headlines 3-15, descriptions 2-4. Maximum 3 enabled RSA ads per ad group.
- **Write operations**: All tools that create, update, or remove resources require user confirmation before execution.
