---
name: _mureo-meta-ads
description: "Meta Ads: Manage campaigns, ad sets, ads, insights, and audiences on Facebook/Instagram."
metadata:
  version: 0.2.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo meta-ads --help"
---

# Meta Ads (Marketing API v21.0)
> PREREQUISITE: Read `../_mureo-shared/SKILL.md` for auth, global flags, and security rules.

## Tool Summary

| # | Tool Name | Category | Type | Description |
|---|-----------|----------|------|-------------|
| 1 | `meta_ads_campaigns_list` | Campaign | Read | List campaigns |
| 2 | `meta_ads_campaigns_get` | Campaign | Read | Get campaign details |
| 3 | `meta_ads_campaigns_create` | Campaign | Write | Create a campaign |
| 4 | `meta_ads_campaigns_update` | Campaign | Write | Update campaign settings |
| 5 | `meta_ads_campaigns_pause` | Campaign | Write | Pause a campaign |
| 6 | `meta_ads_campaigns_enable` | Campaign | Write | Enable a paused campaign |
| 7 | `meta_ads_ad_sets_list` | Ad Set | Read | List ad sets |
| 8 | `meta_ads_ad_sets_get` | Ad Set | Read | Get ad set details |
| 9 | `meta_ads_ad_sets_create` | Ad Set | Write | Create an ad set |
| 10 | `meta_ads_ad_sets_update` | Ad Set | Write | Update ad set settings |
| 11 | `meta_ads_ad_sets_pause` | Ad Set | Write | Pause an ad set |
| 12 | `meta_ads_ad_sets_enable` | Ad Set | Write | Enable a paused ad set |
| 13 | `meta_ads_ads_list` | Ad | Read | List ads |
| 14 | `meta_ads_ads_get` | Ad | Read | Get ad details |
| 15 | `meta_ads_ads_create` | Ad | Write | Create an ad |
| 16 | `meta_ads_ads_update` | Ad | Write | Update an ad |
| 17 | `meta_ads_ads_pause` | Ad | Write | Pause an ad |
| 18 | `meta_ads_ads_enable` | Ad | Write | Enable a paused ad |
| 19 | `meta_ads_insights_report` | Insights | Read | Performance report |
| 20 | `meta_ads_insights_breakdown` | Insights | Read | Breakdown report (age, gender, etc.) |
| 21 | `meta_ads_analysis_performance` | Analysis | Read | Analyze overall performance trends |
| 22 | `meta_ads_analysis_audience` | Analysis | Read | Analyze audience performance and overlap |
| 23 | `meta_ads_analysis_placements` | Analysis | Read | Analyze placement performance breakdown |
| 24 | `meta_ads_analysis_cost` | Analysis | Read | Analyze cost trends and efficiency |
| 25 | `meta_ads_analysis_compare_ads` | Analysis | Read | Compare performance across ads |
| 26 | `meta_ads_analysis_suggest_creative` | Analysis | Read | Suggest creative improvements based on data |
| 27 | `meta_ads_audiences_list` | Audience | Read | List custom audiences |
| 28 | `meta_ads_audiences_get` | Audience | Read | Get audience details |
| 29 | `meta_ads_audiences_create` | Audience | Write | Create a custom audience |
| 30 | `meta_ads_audiences_delete` | Audience | Write | Delete a custom audience |
| 31 | `meta_ads_audiences_create_lookalike` | Audience | Write | Create a lookalike audience |
| 32 | `meta_ads_pixels_list` | Pixel | Read | List pixels |
| 33 | `meta_ads_pixels_get` | Pixel | Read | Get pixel details |
| 34 | `meta_ads_pixels_stats` | Pixel | Read | Get pixel firing statistics |
| 35 | `meta_ads_pixels_events` | Pixel | Read | List pixel events |
| 36 | `meta_ads_conversions_send` | CAPI | Write | Send conversion events (generic) |
| 37 | `meta_ads_conversions_send_purchase` | CAPI | Write | Send a purchase event |
| 38 | `meta_ads_conversions_send_lead` | CAPI | Write | Send a lead event |
| 39 | `meta_ads_creatives_list` | Creative | Read | List ad creatives |
| 40 | `meta_ads_creatives_create` | Creative | Write | Create a standard ad creative |
| 41 | `meta_ads_creatives_create_dynamic` | Creative | Write | Create a dynamic product ad creative |
| 42 | `meta_ads_creatives_upload_image` | Creative | Write | Upload an image for use in creatives |
| 43 | `meta_ads_creatives_create_carousel` | Creative | Write | Create a carousel creative (2-10 cards) |
| 44 | `meta_ads_creatives_create_collection` | Creative | Write | Create a collection creative |
| 45 | `meta_ads_images_upload_file` | Image | Write | Upload an image from local file |
| 46 | `meta_ads_catalogs_list` | Catalog | Read | List product catalogs |
| 47 | `meta_ads_catalogs_get` | Catalog | Read | Get catalog details |
| 48 | `meta_ads_catalogs_create` | Catalog | Write | Create a product catalog |
| 49 | `meta_ads_catalogs_delete` | Catalog | Write | Delete a product catalog |
| 50 | `meta_ads_products_list` | Catalog | Read | List products in a catalog |
| 51 | `meta_ads_products_get` | Catalog | Read | Get product details |
| 52 | `meta_ads_products_add` | Catalog | Write | Add a product to a catalog |
| 53 | `meta_ads_products_update` | Catalog | Write | Update a product |
| 54 | `meta_ads_products_delete` | Catalog | Write | Delete a product |
| 55 | `meta_ads_feeds_list` | Catalog | Read | List feeds for a catalog |
| 56 | `meta_ads_feeds_create` | Catalog | Write | Create a feed (URL-based, scheduled import) |
| 57 | `meta_ads_lead_forms_list` | Lead | Read | List lead forms (per page) |
| 58 | `meta_ads_lead_forms_get` | Lead | Read | Get lead form details |
| 59 | `meta_ads_lead_forms_create` | Lead | Write | Create a lead form |
| 60 | `meta_ads_leads_get` | Lead | Read | Get lead data (per form) |
| 61 | `meta_ads_leads_get_by_ad` | Lead | Read | Get lead data (per ad) |
| 62 | `meta_ads_videos_upload` | Video | Write | Upload a video from URL |
| 63 | `meta_ads_videos_upload_file` | Video | Write | Upload a video from local file |
| 64 | `meta_ads_split_tests_list` | Split Test | Read | List split tests |
| 65 | `meta_ads_split_tests_get` | Split Test | Read | Get split test details and results |
| 66 | `meta_ads_split_tests_create` | Split Test | Write | Create a split test |
| 67 | `meta_ads_split_tests_end` | Split Test | Write | End a split test |
| 68 | `meta_ads_ad_rules_list` | Ad Rule | Read | List automated rules |
| 69 | `meta_ads_ad_rules_get` | Ad Rule | Read | Get rule details |
| 70 | `meta_ads_ad_rules_create` | Ad Rule | Write | Create an automated rule |
| 71 | `meta_ads_ad_rules_update` | Ad Rule | Write | Update an automated rule |
| 72 | `meta_ads_ad_rules_delete` | Ad Rule | Write | Delete an automated rule |
| 73 | `meta_ads_page_posts_list` | Page Post | Read | List Facebook page posts |
| 74 | `meta_ads_page_posts_boost` | Page Post | Write | Boost a page post (create ad from post) |
| 75 | `meta_ads_instagram_accounts` | Instagram | Read | List connected Instagram accounts |
| 76 | `meta_ads_instagram_media` | Instagram | Read | List Instagram posts |
| 77 | `meta_ads_instagram_boost` | Instagram | Write | Boost an Instagram post |

## Key Differences from Google Ads

| Aspect | Google Ads | Meta Ads |
|--------|-----------|----------|
| Account ID format | `"1234567890"` | `"act_XXXXXXXXXXXX"` |
| Budget unit | Currency amount | Cents (1/100 of currency unit) |
| Hierarchy | Campaign > Ad Group > Ad | Campaign > Ad Set > Ad |
| Ad creation | Inline headlines/descriptions | Separate creative, then link to ad |
| Status values | `ENABLED` / `PAUSED` / `REMOVED` | `ACTIVE` / `PAUSED` |
| Period format | `LAST_7_DAYS` | `last_7d` |

## API Resources

### campaigns

- `list` -- List all campaigns in the ad account.
  ```
  Required: account_id (string, "act_XXXX" format)
  Optional: status_filter (string: "ACTIVE" | "PAUSED"), limit (integer, default: 50)
  ```

- `get` -- Get detailed information about a specific campaign.
  ```
  Required: account_id, campaign_id
  ```

- `create` -- Create a new campaign. **Requires user confirmation.**
  ```
  Required: account_id, name, objective
  Optional: status (default: "PAUSED"), daily_budget (integer, in cents), lifetime_budget (integer, in cents)
  ```
  Objective options: `CONVERSIONS`, `LINK_CLICKS`, `REACH`, `BRAND_AWARENESS`, `VIDEO_VIEWS`, `LEAD_GENERATION`, `MESSAGES`, `APP_INSTALLS`

- `update` -- Update campaign settings. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id
  Optional: name, status, daily_budget (integer, in cents)
  ```

- `pause` -- Pause a campaign. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id
  ```

- `enable` -- Enable a paused campaign. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id
  ```

### ad_sets

- `list` -- List ad sets, optionally filtered by campaign.
  ```
  Required: account_id
  Optional: campaign_id, limit (integer, default: 50)
  ```

- `get` -- Get ad set details.
  ```
  Required: account_id, ad_set_id
  ```

- `create` -- Create an ad set with targeting and budget. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id, name, daily_budget (integer, in cents)
  Optional: billing_event (default: "IMPRESSIONS"), optimization_goal (default: "REACH"),
            targeting (object), status (default: "PAUSED")
  ```
  Optimization goals: `REACH`, `IMPRESSIONS`, `OFFSITE_CONVERSIONS`, `LINK_CLICKS`, `LANDING_PAGE_VIEWS`, `LEAD_GENERATION`, `VALUE`

- `update` -- Update ad set settings. **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id
  Optional: name, status, daily_budget (integer, in cents), targeting (object)
  ```

- `pause` -- Pause an ad set. **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id
  ```

- `enable` -- Enable a paused ad set. **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id
  ```

### ads

- `list` -- List ads, optionally filtered by ad set.
  ```
  Required: account_id
  Optional: ad_set_id, limit (integer, default: 50)
  ```

- `get` -- Get ad details.
  ```
  Required: account_id, ad_id
  ```

- `create` -- Create an ad linking to an existing creative. **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id, name, creative_id
  Optional: status (default: "PAUSED")
  ```

- `update` -- Update ad name or status. **Requires user confirmation.**
  ```
  Required: account_id, ad_id
  Optional: name, status ("ACTIVE" | "PAUSED")
  ```

- `pause` -- Pause an ad. **Requires user confirmation.**
  ```
  Required: account_id, ad_id
  ```

- `enable` -- Enable a paused ad. **Requires user confirmation.**
  ```
  Required: account_id, ad_id
  ```

### insights

- `report` -- Get performance metrics for the account or specific campaign.
  ```
  Required: account_id
  Optional: campaign_id, period (default: "last_7d"), level (default: "campaign")
  ```
  Period options: `today`, `yesterday`, `last_7d`, `last_14d`, `last_30d`, `last_90d`, `this_month`, `last_month`

  Level options: `campaign`, `adset`, `ad`

- `breakdown` -- Get performance broken down by demographic dimensions.
  ```
  Required: account_id, campaign_id
  Optional: breakdown (default: "age,gender"), period (default: "last_7d")
  ```
  Breakdown options: `age`, `gender`, `age,gender`, `country`, `region`, `publisher_platform`, `platform_position`, `device_platform`, `impression_device`

### analysis

- `performance` -- Analyze overall performance trends.
  ```
  Required: account_id
  Optional: campaign_id, period
  ```

- `audience` -- Analyze audience performance and overlap.
  ```
  Required: account_id
  Optional: campaign_id, period
  ```

- `placements` -- Analyze placement performance breakdown.
  ```
  Required: account_id
  Optional: campaign_id, period
  ```

- `cost` -- Analyze cost trends and efficiency.
  ```
  Required: account_id
  Optional: campaign_id, period
  ```

- `compare_ads` -- Compare performance across ads.
  ```
  Required: account_id
  Optional: campaign_id, ad_set_id, period
  ```

- `suggest_creative` -- Suggest creative improvements based on data.
  ```
  Required: account_id
  Optional: campaign_id, period
  ```

### audiences

- `list` -- List custom audiences in the ad account.
  ```
  Required: account_id
  Optional: limit (integer, default: 50)
  ```

- `get` -- Get audience details.
  ```
  Required: account_id, audience_id
  ```

- `create` -- Create a custom audience. **Requires user confirmation.**
  ```
  Required: account_id, name, subtype
  Optional: description, retention_days, pixel_id
  ```
  Subtype options: `WEBSITE`, `CUSTOM`, `APP`, `ENGAGEMENT`, `OFFLINE`

- `delete` -- Delete a custom audience. **Requires user confirmation.**
  ```
  Required: account_id, audience_id
  ```

- `create_lookalike` -- Create a lookalike audience. **Requires user confirmation.**
  ```
  Required: account_id, source_audience_id, country
  Optional: ratio (float, 0.01-0.20)
  ```

### pixels

- `list` -- List pixels in the ad account.
  ```
  Required: account_id
  ```

- `get` -- Get pixel details.
  ```
  Required: account_id, pixel_id
  ```

- `stats` -- Get pixel firing statistics.
  ```
  Required: account_id, pixel_id
  ```

- `events` -- List pixel events.
  ```
  Required: account_id, pixel_id
  ```

### conversions (CAPI)

- `send` -- Send conversion events (generic). **Requires user confirmation.**
  ```
  Required: account_id, pixel_id, events (array)
  ```

- `send_purchase` -- Send a purchase event. **Requires user confirmation.**
  ```
  Required: account_id, pixel_id, event_time, user_data, currency, value
  ```

- `send_lead` -- Send a lead event. **Requires user confirmation.**
  ```
  Required: account_id, pixel_id, event_time, user_data
  ```

### creatives

- `list` -- List ad creatives.
  ```
  Required: account_id
  Optional: limit (integer, default: 50)
  ```

- `create` -- Create a standard ad creative. **Requires user confirmation.**
  ```
  Required: account_id, name
  Optional: image_hash, link_url, message, page_id
  ```

- `create_dynamic` -- Create a dynamic product ad creative. **Requires user confirmation.**
  ```
  Required: account_id, catalog_id
  Optional: product_set_id, message, link
  ```

- `upload_image` -- Upload an image for use in creatives.
  ```
  Required: account_id, file_path
  ```

- `create_carousel` -- Create a carousel creative (2-10 cards). **Requires user confirmation.**
  ```
  Required: account_id, page_id, cards (array), link
  ```

- `create_collection` -- Create a collection creative. **Requires user confirmation.**
  ```
  Required: account_id, page_id, product_ids (array), link
  ```

### images

- `upload_file` -- Upload an image from local file.
  ```
  Required: account_id, file_path
  ```

### catalogs (Product Catalog / DPA)

- `list` -- List product catalogs.
  ```
  Required: account_id, business_id
  ```

- `get` -- Get catalog details.
  ```
  Required: account_id, catalog_id
  ```

- `create` -- Create a product catalog. **Requires user confirmation.**
  ```
  Required: account_id, business_id, name
  ```

- `delete` -- Delete a product catalog. **Requires user confirmation.**
  ```
  Required: account_id, catalog_id
  ```

### products

- `list` -- List products in a catalog.
  ```
  Required: account_id, catalog_id
  Optional: limit
  ```

- `get` -- Get product details.
  ```
  Required: account_id, product_id
  ```

- `add` -- Add a product to a catalog. **Requires user confirmation.**
  ```
  Required: account_id, catalog_id, retailer_id, name, availability, condition, price, url, image_url
  ```

- `update` -- Update a product. **Requires user confirmation.**
  ```
  Required: account_id, product_id
  Optional: name, availability, condition, price, url, image_url
  ```

- `delete` -- Delete a product. **Requires user confirmation.**
  ```
  Required: account_id, product_id
  ```

### feeds

- `list` -- List feeds for a catalog.
  ```
  Required: account_id, catalog_id
  ```

- `create` -- Create a feed (URL-based, scheduled import). **Requires user confirmation.**
  ```
  Required: account_id, catalog_id, name, feed_url
  Optional: schedule (object)
  ```

### lead_forms

- `list` -- List lead forms (per page).
  ```
  Required: account_id, page_id
  ```

- `get` -- Get lead form details.
  ```
  Required: account_id, form_id
  ```

- `create` -- Create a lead form. **Requires user confirmation.**
  ```
  Required: account_id, page_id, name, questions (array), privacy_policy_url
  ```

### leads

- `get` -- Get lead data (per form).
  ```
  Required: account_id, form_id
  Optional: limit
  ```

- `get_by_ad` -- Get lead data (per ad).
  ```
  Required: account_id, ad_id
  Optional: limit
  ```

### videos

- `upload` -- Upload a video from URL.
  ```
  Required: account_id, video_url
  Optional: title, description
  ```

- `upload_file` -- Upload a video from local file.
  ```
  Required: account_id, file_path
  Optional: title, description
  ```

### split_tests

- `list` -- List split tests.
  ```
  Required: account_id
  ```

- `get` -- Get split test details and results.
  ```
  Required: account_id, study_id
  ```

- `create` -- Create a split test. **Requires user confirmation.**
  ```
  Required: account_id, name, cells (array), objectives (array), start_time, end_time
  ```

- `end` -- End a split test. **Requires user confirmation.**
  ```
  Required: account_id, study_id
  ```

### ad_rules

- `list` -- List automated rules.
  ```
  Required: account_id
  ```

- `get` -- Get rule details.
  ```
  Required: account_id, rule_id
  ```

- `create` -- Create an automated rule (alerts, auto-pause, etc.). **Requires user confirmation.**
  ```
  Required: account_id, name, evaluation_spec (object), execution_spec (object)
  ```

- `update` -- Update an automated rule. **Requires user confirmation.**
  ```
  Required: account_id, rule_id
  Optional: name, evaluation_spec, execution_spec, status
  ```

- `delete` -- Delete an automated rule. **Requires user confirmation.**
  ```
  Required: account_id, rule_id
  ```

### page_posts

- `list` -- List Facebook page posts.
  ```
  Required: account_id, page_id
  Optional: limit
  ```

- `boost` -- Boost a page post (create ad from post). **Requires user confirmation.**
  ```
  Required: account_id, page_id, post_id, ad_set_id
  ```

### instagram

- `accounts` -- List connected Instagram accounts.
  ```
  Required: account_id
  ```

- `media` -- List Instagram posts.
  ```
  Required: account_id, ig_user_id
  Optional: limit
  ```

- `boost` -- Boost an Instagram post (create ad from post). **Requires user confirmation.**
  ```
  Required: account_id, ig_user_id, media_id, ad_set_id
  ```

## Common Workflows

### 1. Campaign Performance Check

```
Step 1: List active campaigns
  -> meta_ads_campaigns_list {account_id, status_filter: "ACTIVE"}

Step 2: Get performance report
  -> meta_ads_insights_report {account_id, period: "last_7d", level: "campaign"}

Step 3: Analyze performance trends
  -> meta_ads_analysis_performance {account_id}

Step 4: Break down by demographics
  -> meta_ads_insights_breakdown {account_id, campaign_id, breakdown: "age,gender"}

Step 5: Check placement performance
  -> meta_ads_analysis_placements {account_id}
```

### 2. Full Campaign Setup

```
Step 1: Create campaign (CONFIRM WITH USER)
  -> meta_ads_campaigns_create {account_id, name, objective, daily_budget}

Step 2: Create ad set with targeting (CONFIRM WITH USER)
  -> meta_ads_ad_sets_create {account_id, campaign_id, name, daily_budget, targeting}

Step 3: Upload image and create creative
  -> meta_ads_creatives_upload_image {account_id, file_path}
  -> meta_ads_creatives_create {account_id, name, image_hash, link_url, page_id}

Step 4: Create ad linking to creative (CONFIRM WITH USER)
  -> meta_ads_ads_create {account_id, ad_set_id, name, creative_id}
```

### 3. Audience & Lookalike Setup

```
Step 1: List existing audiences
  -> meta_ads_audiences_list {account_id}

Step 2: Create a website visitor audience (CONFIRM WITH USER)
  -> meta_ads_audiences_create {account_id, name, subtype: "WEBSITE", retention_days, pixel_id}

Step 3: Create a lookalike based on it (CONFIRM WITH USER)
  -> meta_ads_audiences_create_lookalike {account_id, source_audience_id, country: "JP"}
```

### 4. A/B Testing with Split Tests

```
Step 1: Create a split test (CONFIRM WITH USER)
  -> meta_ads_split_tests_create {account_id, name, cells, objectives, start_time, end_time}

Step 2: Monitor results
  -> meta_ads_split_tests_get {account_id, study_id}

Step 3: End the test when ready (CONFIRM WITH USER)
  -> meta_ads_split_tests_end {account_id, study_id}
```

### 5. Product Catalog & DPA

```
Step 1: Create a catalog (CONFIRM WITH USER)
  -> meta_ads_catalogs_create {account_id, business_id, name}

Step 2: Add products or create a feed
  -> meta_ads_products_add {account_id, catalog_id, retailer_id, name, ...}
  -> meta_ads_feeds_create {account_id, catalog_id, name, feed_url}

Step 3: Create a dynamic product ad creative (CONFIRM WITH USER)
  -> meta_ads_creatives_create_dynamic {account_id, catalog_id}
```

### 6. Lead Generation

```
Step 1: Create a lead form (CONFIRM WITH USER)
  -> meta_ads_lead_forms_create {account_id, page_id, name, questions, privacy_policy_url}

Step 2: Set up campaign with LEAD_GENERATION objective
  -> meta_ads_campaigns_create {account_id, name, objective: "LEAD_GENERATION"}

Step 3: Download leads
  -> meta_ads_leads_get {account_id, form_id}
```

### 7. Pause / Enable Entities

```
Pause a campaign:
  -> meta_ads_campaigns_pause {account_id, campaign_id}

Re-enable it:
  -> meta_ads_campaigns_enable {account_id, campaign_id}

Same pattern for ad_sets.pause/enable and ads.pause/enable.
```

### 8. Conversions API (Server-Side Tracking)

```
Step 1: List pixels and check events
  -> meta_ads_pixels_list {account_id}
  -> meta_ads_pixels_events {account_id, pixel_id}

Step 2: Send a purchase event (CONFIRM WITH USER)
  -> meta_ads_conversions_send_purchase {account_id, pixel_id, event_time, user_data, currency, value}
```

## Important Notes

- **Budget in cents**: All budget and monetary values are in **cents** (1/100 of the account currency). For example, `daily_budget: 500000` = 5,000 in the account currency.
- **account_id format**: Must include the `act_` prefix (e.g., `"act_123456789"`).
- **Status values**: Meta uses `ACTIVE` / `PAUSED` (not `ENABLED`).
- **Creative-first model**: In Meta Ads, you create a creative object first, then reference its `creative_id` when creating an ad.
- **Targeting object**: The targeting structure follows the Meta Marketing API format. Common fields include `geo_locations`, `age_min`, `age_max`, `genders`, `interests`, `behaviors`, and `custom_audiences`.
- **Conversions API**: Server-side events require hashed `user_data` (email, phone). The SDK handles hashing automatically.
