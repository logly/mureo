---
name: mureo-google-ads
description: "Google Ads: Manage campaigns, ad groups, ads, keywords, budgets, and performance analysis."
metadata:
  version: 0.2.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo google-ads --help"
---

# Google Ads (v18)
> PREREQUISITE: Read `../mureo-shared/SKILL.md` for auth, global flags, and security rules.

## Tool Summary

| # | Tool Name | Category | Type | Description |
|---|-----------|----------|------|-------------|
| 1 | `google_ads.campaigns.list` | Campaign | Read | List campaigns |
| 2 | `google_ads.campaigns.get` | Campaign | Read | Get campaign details |
| 3 | `google_ads.campaigns.create` | Campaign | Write | Create a campaign (search or display, via `channel_type`) |
| 4 | `google_ads.campaigns.update` | Campaign | Write | Update campaign settings |
| 5 | `google_ads.campaigns.update_status` | Campaign | Write | Change campaign status |
| 6 | `google_ads.campaigns.diagnose` | Campaign | Read | Diagnose delivery issues |
| 7 | `google_ads.ad_groups.list` | Ad Group | Read | List ad groups |
| 8 | `google_ads.ad_groups.create` | Ad Group | Write | Create an ad group |
| 9 | `google_ads.ad_groups.update` | Ad Group | Write | Update ad group settings |
| 10 | `google_ads.ads.list` | Ad | Read | List ads |
| 11 | `google_ads.ads.create` | Ad | Write | Create an RSA ad |
| 12 | `google_ads.ads.update` | Ad | Write | Update ad content |
| 13 | `google_ads.ads.update_status` | Ad | Write | Change ad status |
| 14 | `google_ads.ads.policy_details` | Ad | Read | Get ad policy approval details |
| 15 | `google_ads.keywords.list` | Keyword | Read | List keywords |
| 16 | `google_ads.keywords.add` | Keyword | Write | Add keywords |
| 17 | `google_ads.keywords.remove` | Keyword | Write | Remove a keyword |
| 18 | `google_ads.keywords.suggest` | Keyword | Read | Suggest keywords via Keyword Planner |
| 19 | `google_ads.keywords.diagnose` | Keyword | Read | Diagnose keyword quality scores |
| 20 | `google_ads.keywords.pause` | Keyword | Write | Pause a keyword |
| 21 | `google_ads.keywords.audit` | Keyword | Read | Audit keyword performance and quality |
| 22 | `google_ads.keywords.cross_adgroup_duplicates` | Keyword | Read | Find duplicate keywords across ad groups |
| 23 | `google_ads.negative_keywords.list` | Negative KW | Read | List negative keywords |
| 24 | `google_ads.negative_keywords.add` | Negative KW | Write | Add negative keywords to a campaign |
| 25 | `google_ads.negative_keywords.remove` | Negative KW | Write | Remove a negative keyword |
| 26 | `google_ads.negative_keywords.add_to_ad_group` | Negative KW | Write | Add negative keywords to an ad group |
| 27 | `google_ads.negative_keywords.suggest` | Negative KW | Read | Suggest negative keywords from search terms |
| 28 | `google_ads.budget.get` | Budget | Read | Get campaign budget |
| 29 | `google_ads.budget.update` | Budget | Write | Update daily budget |
| 30 | `google_ads.budget.create` | Budget | Write | Create a new campaign budget |
| 31 | `google_ads.accounts.list` | Account | Read | List accessible Google Ads accounts |
| 32 | `google_ads.search_terms.report` | Search Terms | Read | Search terms report |
| 33 | `google_ads.search_terms.review` | Search Terms | Read | Review search terms with rule-based scoring |
| 34 | `google_ads.search_terms.analyze` | Search Terms | Read | Analyze search terms with intent classification |
| 35 | `google_ads.sitelinks.list` | Extension | Read | List sitelink extensions |
| 36 | `google_ads.sitelinks.create` | Extension | Write | Create a sitelink extension |
| 37 | `google_ads.sitelinks.remove` | Extension | Write | Remove a sitelink extension |
| 38 | `google_ads.callouts.list` | Extension | Read | List callout extensions |
| 39 | `google_ads.callouts.create` | Extension | Write | Create a callout extension |
| 40 | `google_ads.callouts.remove` | Extension | Write | Remove a callout extension |
| 41 | `google_ads.conversions.list` | Conversion | Read | List conversion actions |
| 42 | `google_ads.conversions.get` | Conversion | Read | Get conversion action details |
| 43 | `google_ads.conversions.performance` | Conversion | Read | Get conversion performance metrics |
| 44 | `google_ads.conversions.create` | Conversion | Write | Create a conversion action |
| 45 | `google_ads.conversions.update` | Conversion | Write | Update a conversion action |
| 46 | `google_ads.conversions.remove` | Conversion | Write | Remove a conversion action |
| 47 | `google_ads.conversions.tag` | Conversion | Read | Get conversion tracking tag snippet |
| 48 | `google_ads.recommendations.list` | Targeting | Read | List optimization recommendations |
| 49 | `google_ads.recommendations.apply` | Targeting | Write | Apply an optimization recommendation |
| 50 | `google_ads.device_targeting.get` | Targeting | Read | Get device targeting settings |
| 51 | `google_ads.device_targeting.set` | Targeting | Write | Set device targeting bid adjustments |
| 52 | `google_ads.bid_adjustments.get` | Targeting | Read | Get bid adjustment settings |
| 53 | `google_ads.bid_adjustments.update` | Targeting | Write | Update bid adjustments |
| 54 | `google_ads.location_targeting.list` | Targeting | Read | List location targeting criteria |
| 55 | `google_ads.location_targeting.update` | Targeting | Write | Update location targeting |
| 56 | `google_ads.schedule_targeting.list` | Targeting | Read | List ad schedule targeting |
| 57 | `google_ads.schedule_targeting.update` | Targeting | Write | Update ad schedule targeting |
| 58 | `google_ads.change_history.list` | Targeting | Read | List account change history |
| 59 | `google_ads.performance.report` | Analysis | Read | Performance report |
| 60 | `google_ads.performance.analyze` | Analysis | Read | Analyze performance trends and anomalies |
| 61 | `google_ads.cost_increase.investigate` | Analysis | Read | Investigate sudden cost increases |
| 62 | `google_ads.health_check.all` | Analysis | Read | Comprehensive account health check |
| 63 | `google_ads.ad_performance.compare` | Analysis | Read | Compare ad performance across variants |
| 64 | `google_ads.ad_performance.report` | Analysis | Read | Detailed ad-level performance report |
| 65 | `google_ads.network_performance.report` | Analysis | Read | Network-level performance breakdown |
| 66 | `google_ads.budget.efficiency` | Analysis | Read | Analyze budget utilization efficiency |
| 67 | `google_ads.budget.reallocation` | Analysis | Read | Suggest budget reallocation across campaigns |
| 68 | `google_ads.auction_insights.get` | Analysis | Read | Get auction insights (competitor analysis) |
| 69 | `google_ads.auction_insights.analyze` | Analysis | Read | Auction insights analysis |
| 70 | `google_ads.rsa_assets.analyze` | Analysis | Read | Analyze RSA asset performance |
| 71 | `google_ads.rsa_assets.audit` | Analysis | Read | Audit RSA assets for best practices |
| 72 | `google_ads.cpc.detect_trend` | Analysis | Read | Detect CPC trend direction |
| 73 | `google_ads.device.analyze` | Analysis | Read | Device performance analysis |
| 74 | `google_ads.btob.optimizations` | B2B | Read | Get B2B-specific optimization suggestions |
| 75 | `google_ads.landing_page.analyze` | Creative | Read | Analyze landing page relevance and quality |
| 76 | `google_ads.creative.research` | Creative | Read | Research competitive creative strategies |
| 77 | `google_ads.monitoring.delivery_goal` | Monitoring | Read | Monitor campaign delivery against goals |
| 78 | `google_ads.monitoring.cpa_goal` | Monitoring | Read | Monitor CPA against target goals |
| 79 | `google_ads.monitoring.cv_goal` | Monitoring | Read | Monitor conversion volume against goals |
| 80 | `google_ads.monitoring.zero_conversions` | Monitoring | Read | Detect campaigns with zero conversions |
| 81 | `google_ads.capture.screenshot` | Capture | Read | Capture a screenshot of a URL |
| 82 | `google_ads.assets.upload_image` | Asset | Write | Upload image as Google Ads asset |
| 83 | `google_ads.ads.create_display` | Ad | Write | Create an RDA (responsive display ad); image files are uploaded automatically |

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
  ```

- `cross_adgroup_duplicates` -- Find duplicate keywords across ad groups in a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

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
  ```

### budget

- `get` -- Get the daily budget for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```

- `update` -- Update daily budget amount. **Requires user confirmation.** Always show current vs. new amount.
  ```
  Required: customer_id, budget_id (string), amount (number)
  ```

- `create` -- Create a new campaign budget. **Requires user confirmation.**
  ```
  Required: customer_id, name (string), amount (number)
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
  Required: customer_id, campaign_id, sitelink_text, final_url (string)
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

### analysis & reporting

- `performance.report` -- Get performance metrics aggregated by campaign.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), period (string, default: "LAST_30_DAYS")
  ```
  Period options: `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`, `LAST_MONTH`

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

## Common Workflows

### 1. Performance Check

A typical daily performance check flow:

```
Step 1: List campaigns to identify active ones
  -> google_ads.campaigns.list {customer_id, status_filter: "ENABLED"}

Step 2: Get overall performance report
  -> google_ads.performance.report {customer_id, period: "LAST_7_DAYS"}

Step 3: Run comprehensive health check
  -> google_ads.health_check.all {customer_id}

Step 4: For underperforming campaigns, run diagnostics
  -> google_ads.campaigns.diagnose {customer_id, campaign_id}

Step 5: Check keyword quality scores
  -> google_ads.keywords.diagnose {customer_id, campaign_id}

Step 6: Analyze device performance for CPA gaps
  -> google_ads.device.analyze {customer_id, campaign_id}

Step 7: Monitor conversion goals
  -> google_ads.monitoring.zero_conversions {customer_id}
```

### 2. Negative Keyword Addition

When cleaning up wasted spend from irrelevant search terms:

```
Step 1: Get search terms report
  -> google_ads.search_terms.report {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Or use automated review for suggestions
  -> google_ads.search_terms.review {customer_id, campaign_id, target_cpa: 3000}

Step 3: Analyze search terms with intent classification
  -> google_ads.search_terms.analyze {customer_id, campaign_id}

Step 4: Get AI-suggested negative keywords
  -> google_ads.negative_keywords.suggest {customer_id, campaign_id}

Step 5: Review current negative keywords to avoid duplicates
  -> google_ads.negative_keywords.list {customer_id, campaign_id}

Step 6: Add negative keywords (CONFIRM WITH USER)
  -> google_ads.negative_keywords.add {customer_id, campaign_id, keywords: [...]}
```

### 3. New Campaign Creation

Full campaign setup from scratch:

```
Step 1: Create a budget
  -> google_ads.budget.create {customer_id, name, amount}

Step 2: Create the campaign (omit channel_type or set "SEARCH" for a search campaign)
  -> google_ads.campaigns.create {customer_id, name, bidding_strategy, budget_id}

Step 3: Create ad groups
  -> google_ads.ad_groups.create {customer_id, campaign_id, name}

Step 4: Add keywords to each ad group
  -> google_ads.keywords.add {customer_id, ad_group_id, keywords: [...]}

Step 5: Create RSA ads for each ad group
  -> google_ads.ads.create {customer_id, ad_group_id, headlines: [...], descriptions: [...], final_url}

Step 6: Add campaign-level negative keywords
  -> google_ads.negative_keywords.add {customer_id, campaign_id, keywords: [...]}

Step 7: Add sitelink extensions
  -> google_ads.sitelinks.create {customer_id, campaign_id, sitelink_text, final_url}

Step 8: Add callout extensions
  -> google_ads.callouts.create {customer_id, campaign_id, callout_text}

Step 9: Set up conversion tracking
  -> google_ads.conversions.create {customer_id, name, type}

Step 10: Enable the campaign
  -> google_ads.campaigns.update_status {customer_id, campaign_id, status: "ENABLED"}
```

### 3b. New Display Campaign + Responsive Display Ad

Display campaigns use a different `channel_type` and require image assets.
mureo uploads the local image files automatically before creating the ad.

```
Step 1: Create a budget
  -> google_ads.budget.create {customer_id, name, amount}

Step 2: Create a DISPLAY campaign
  -> google_ads.campaigns.create {
       customer_id, name, channel_type: "DISPLAY",
       bidding_strategy: "MAXIMIZE_CONVERSIONS", budget_id
     }

Step 3: Create an ad group inside the display campaign
  -> google_ads.ad_groups.create {customer_id, campaign_id, name}

Step 4: Create the responsive display ad
  -> google_ads.ads.create_display {
       customer_id, ad_group_id,
       headlines: [...], long_headline, descriptions: [...],
       business_name,
       marketing_image_paths: ["/path/to/marketing-1200x628.jpg"],
       square_marketing_image_paths: ["/path/to/square-1200x1200.jpg"],
       logo_image_paths: ["/path/to/logo.png"],   # optional
       final_url
     }

Step 5: Enable the campaign
  -> google_ads.campaigns.update_status {customer_id, campaign_id, status: "ENABLED"}
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
  -> google_ads.budget.get {customer_id, campaign_id}

Step 2: Analyze budget efficiency
  -> google_ads.budget.efficiency {customer_id}

Step 3: Get reallocation suggestions
  -> google_ads.budget.reallocation {customer_id}

Step 4: Update budget (CONFIRM WITH USER)
  -> google_ads.budget.update {customer_id, budget_id, amount: 6000}
```

### 5. Delivery Troubleshooting

When a campaign is not getting impressions:

```
Step 1: Check campaign status and settings
  -> google_ads.campaigns.get {customer_id, campaign_id}

Step 2: Run comprehensive delivery diagnosis
  -> google_ads.campaigns.diagnose {customer_id, campaign_id}

Step 3: Check keyword quality and delivery status
  -> google_ads.keywords.diagnose {customer_id, campaign_id}

Step 4: Check ad policy details for disapprovals
  -> google_ads.ads.policy_details {customer_id, ad_group_id, ad_id}

Step 5: Check CPC trends (are bids competitive?)
  -> google_ads.cpc.detect_trend {customer_id, campaign_id}

Step 6: Analyze auction insights (competitor landscape)
  -> google_ads.auction_insights.analyze {customer_id, campaign_id}

Step 7: Monitor delivery pace
  -> google_ads.monitoring.delivery_goal {customer_id, campaign_id}

Step 8: Review budget constraints
  -> google_ads.budget.get {customer_id, campaign_id}
```

### 6. Competitive Analysis

Understanding the competitive landscape:

```
Step 1: Analyze auction insights
  -> google_ads.auction_insights.analyze {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Get auction insights data
  -> google_ads.auction_insights.get {customer_id, campaign_id}

Step 3: Detect CPC trend (rising CPC may indicate increased competition)
  -> google_ads.cpc.detect_trend {customer_id, campaign_id}

Step 4: Investigate cost increases
  -> google_ads.cost_increase.investigate {customer_id, campaign_id}

Step 5: Research competitive creative strategies
  -> google_ads.creative.research {customer_id}

Step 6: Get keyword suggestions to find new opportunities
  -> google_ads.keywords.suggest {customer_id, seed_keywords: ["..."]}
```

### 7. RSA Optimization

Improving responsive search ad performance:

```
Step 1: Analyze RSA asset performance
  -> google_ads.rsa_assets.analyze {customer_id, ad_group_id}

Step 2: Audit RSA assets for best practices
  -> google_ads.rsa_assets.audit {customer_id, campaign_id}

Step 3: Compare ad variants
  -> google_ads.ad_performance.compare {customer_id, ad_group_id}

Step 4: Check landing page relevance
  -> google_ads.landing_page.analyze {customer_id, campaign_id}
```

### 8. Account Audit

Comprehensive account review:

```
Step 1: List all accessible accounts
  -> google_ads.accounts.list {}

Step 2: Run health check
  -> google_ads.health_check.all {customer_id}

Step 3: Audit keywords
  -> google_ads.keywords.audit {customer_id, campaign_id}

Step 4: Find duplicate keywords
  -> google_ads.keywords.cross_adgroup_duplicates {customer_id, campaign_id}

Step 5: Review change history
  -> google_ads.change_history.list {customer_id}

Step 6: Check optimization recommendations
  -> google_ads.recommendations.list {customer_id}
```

## Important Notes

- **Micros**: Some values (e.g., `cpc_bid_micros`) are in micros where 1,000,000 = 1 currency unit. For example, 500,000 micros = 0.50 in the account currency.
- **Period values**: Use Google Ads date range constants like `LAST_7_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`.
- **customer_id**: Always a 10-digit string without dashes (e.g., `"1234567890"`, not `"123-456-7890"`).
- **RSA limits**: Headlines 3-15, descriptions 2-4. Maximum 3 enabled RSA ads per ad group.
- **Write operations**: All tools that create, update, or remove resources require user confirmation before execution.
