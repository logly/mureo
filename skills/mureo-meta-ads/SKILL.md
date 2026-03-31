---
name: mureo-meta-ads
description: "Meta Ads: Manage campaigns, ad sets, ads, insights, and audiences on Facebook/Instagram."
metadata:
  version: 0.1.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo meta-ads --help"
---

# Meta Ads (Marketing API v21.0)
> PREREQUISITE: Read `../mureo-shared/SKILL.md` for auth, global flags, and security rules.

## Tool Summary (14 tools)

| # | Tool Name | Category | Type | Description |
|---|-----------|----------|------|-------------|
| 1 | `meta_ads.campaigns.list` | Campaign | Read | List campaigns |
| 2 | `meta_ads.campaigns.get` | Campaign | Read | Get campaign details |
| 3 | `meta_ads.campaigns.create` | Campaign | Write | Create a campaign |
| 4 | `meta_ads.campaigns.update` | Campaign | Write | Update campaign settings |
| 5 | `meta_ads.ad_sets.list` | Ad Set | Read | List ad sets |
| 6 | `meta_ads.ad_sets.create` | Ad Set | Write | Create an ad set |
| 7 | `meta_ads.ad_sets.update` | Ad Set | Write | Update ad set settings |
| 8 | `meta_ads.ads.list` | Ad | Read | List ads |
| 9 | `meta_ads.ads.create` | Ad | Write | Create an ad |
| 10 | `meta_ads.ads.update` | Ad | Write | Update an ad |
| 11 | `meta_ads.insights.report` | Insights | Read | Performance report |
| 12 | `meta_ads.insights.breakdown` | Insights | Read | Breakdown report (age, gender, etc.) |
| 13 | `meta_ads.audiences.list` | Audience | Read | List custom audiences |
| 14 | `meta_ads.audiences.create` | Audience | Write | Create a custom audience |

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
  ```json
  // Example call
  {"account_id": "act_123456789"}

  // Example response
  {
    "campaigns": [
      {
        "id": "23851234567890",
        "name": "Summer Sale 2026",
        "status": "ACTIVE",
        "objective": "CONVERSIONS",
        "daily_budget": 100000,
        "lifetime_budget": null
      }
    ]
  }
  ```

- `get` -- Get detailed information about a specific campaign.
  ```
  Required: account_id, campaign_id (string)
  ```
  ```json
  {"account_id": "act_123456789", "campaign_id": "23851234567890"}
  ```

- `create` -- Create a new campaign. **Requires user confirmation.**
  ```
  Required: account_id, name, objective (string)
  Optional: status (string, default: "PAUSED"),
            daily_budget (integer, in cents),
            lifetime_budget (integer, in cents)
  ```
  ```json
  {
    "account_id": "act_123456789",
    "name": "Product Launch - Conversions",
    "objective": "CONVERSIONS",
    "status": "PAUSED",
    "daily_budget": 500000
  }
  ```
  Objective options: `CONVERSIONS`, `LINK_CLICKS`, `REACH`, `BRAND_AWARENESS`, `VIDEO_VIEWS`, `LEAD_GENERATION`, `MESSAGES`, `APP_INSTALLS`

  Note: `daily_budget` is in **cents**. 500000 cents = 5,000 in the account currency.

- `update` -- Update campaign settings. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id (string)
  Optional: name (string), status (string), daily_budget (integer, in cents)
  ```

### ad_sets

- `list` -- List ad sets, optionally filtered by campaign.
  ```
  Required: account_id (string)
  Optional: campaign_id (string), limit (integer, default: 50)
  ```

- `create` -- Create an ad set with targeting and budget. **Requires user confirmation.**
  ```
  Required: account_id, campaign_id, name (string), daily_budget (integer, in cents)
  Optional: billing_event (string, default: "IMPRESSIONS"),
            optimization_goal (string, default: "REACH"),
            targeting (object),
            status (string, default: "PAUSED")
  ```
  ```json
  {
    "account_id": "act_123456789",
    "campaign_id": "23851234567890",
    "name": "Tokyo - Ages 25-44",
    "daily_budget": 200000,
    "billing_event": "IMPRESSIONS",
    "optimization_goal": "OFFSITE_CONVERSIONS",
    "targeting": {
      "geo_locations": {
        "regions": [{"key": "3886"}]
      },
      "age_min": 25,
      "age_max": 44,
      "genders": [1, 2]
    },
    "status": "PAUSED"
  }
  ```
  Optimization goals: `REACH`, `IMPRESSIONS`, `OFFSITE_CONVERSIONS`, `LINK_CLICKS`, `LANDING_PAGE_VIEWS`, `LEAD_GENERATION`, `VALUE`

- `update` -- Update ad set settings (name, status, budget, targeting). **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id (string)
  Optional: name (string), status (string), daily_budget (integer, in cents), targeting (object)
  ```

### ads

- `list` -- List ads, optionally filtered by ad set.
  ```
  Required: account_id (string)
  Optional: ad_set_id (string), limit (integer, default: 50)
  ```

- `create` -- Create an ad linking to an existing creative. **Requires user confirmation.**
  ```
  Required: account_id, ad_set_id, name, creative_id (string)
  Optional: status (string, default: "PAUSED")
  ```
  ```json
  {
    "account_id": "act_123456789",
    "ad_set_id": "23851234567891",
    "name": "Single Image - Variant A",
    "creative_id": "23851234567892",
    "status": "PAUSED"
  }
  ```
  Note: Creatives must be created separately before creating an ad. Use the Meta Ads creative tools in the SaaS version (mureo-core) or create via the Meta Ads Manager UI.

- `update` -- Update ad name or status. **Requires user confirmation.**
  ```
  Required: account_id, ad_id (string)
  Optional: name (string), status (string: "ACTIVE" | "PAUSED")
  ```

### insights

- `report` -- Get performance metrics for the account or specific campaign.
  ```
  Required: account_id (string)
  Optional: campaign_id (string), period (string, default: "last_7d"),
            level (string, default: "campaign")
  ```
  ```json
  {
    "account_id": "act_123456789",
    "campaign_id": "23851234567890",
    "period": "last_30d",
    "level": "adset"
  }
  ```
  Period options: `today`, `yesterday`, `last_7d`, `last_14d`, `last_30d`, `last_90d`, `this_month`, `last_month`

  Level options: `campaign`, `adset`, `ad`

  ```json
  // Example response
  {
    "insights": [
      {
        "campaign_id": "23851234567890",
        "campaign_name": "Summer Sale 2026",
        "impressions": 45000,
        "clicks": 1200,
        "spend": 350000,
        "cpc": 291,
        "cpm": 7778,
        "ctr": 2.67,
        "conversions": 85,
        "cpa": 4118
      }
    ]
  }
  ```
  Note: Monetary values (`spend`, `cpc`, `cpm`, `cpa`) are in cents.

- `breakdown` -- Get performance broken down by demographic dimensions.
  ```
  Required: account_id, campaign_id (string)
  Optional: breakdown (string, default: "age,gender"), period (string, default: "last_7d")
  ```
  ```json
  {
    "account_id": "act_123456789",
    "campaign_id": "23851234567890",
    "breakdown": "age",
    "period": "last_30d"
  }
  ```
  Breakdown options: `age`, `gender`, `age,gender`, `country`, `region`, `publisher_platform`, `platform_position`, `device_platform`, `impression_device`

### audiences

- `list` -- List custom audiences in the ad account.
  ```
  Required: account_id (string)
  Optional: limit (integer, default: 50)
  ```

- `create` -- Create a custom audience. **Requires user confirmation.**
  ```
  Required: account_id, name, subtype (string)
  Optional: description (string), retention_days (integer), pixel_id (string)
  ```
  ```json
  {
    "account_id": "act_123456789",
    "name": "Website Visitors - Last 30 Days",
    "subtype": "WEBSITE",
    "description": "People who visited the site in the last 30 days",
    "retention_days": 30,
    "pixel_id": "1234567890"
  }
  ```
  Subtype options: `WEBSITE` (pixel-based), `CUSTOM` (customer list), `APP` (app events), `ENGAGEMENT` (page/video engagement), `OFFLINE` (offline events)

## Common Workflows

### 1. Campaign Performance Check

```
Step 1: List active campaigns
  -> meta_ads.campaigns.list {account_id, status_filter: "ACTIVE"}

Step 2: Get performance report
  -> meta_ads.insights.report {account_id, period: "last_7d", level: "campaign"}

Step 3: Break down by demographics for deeper analysis
  -> meta_ads.insights.breakdown {account_id, campaign_id, breakdown: "age,gender", period: "last_7d"}

Step 4: Check placement performance
  -> meta_ads.insights.breakdown {account_id, campaign_id, breakdown: "publisher_platform"}
```

### 2. Ad Set Creation

Creating a targeted ad set within an existing campaign:

```
Step 1: List campaigns to find the target
  -> meta_ads.campaigns.list {account_id}

Step 2: Create ad set with targeting (CONFIRM WITH USER)
  -> meta_ads.ad_sets.create {
       account_id, campaign_id, name,
       daily_budget: 200000,
       optimization_goal: "OFFSITE_CONVERSIONS",
       targeting: {geo_locations: {...}, age_min: 25, age_max: 44}
     }

Step 3: Create ad linking to a creative (CONFIRM WITH USER)
  -> meta_ads.ads.create {account_id, ad_set_id, name, creative_id}
```

### 3. Audience Creation

Setting up a remarketing audience:

```
Step 1: List existing audiences to avoid duplicates
  -> meta_ads.audiences.list {account_id}

Step 2: Create a website visitor audience (CONFIRM WITH USER)
  -> meta_ads.audiences.create {
       account_id,
       name: "Cart Abandoners - 14 Days",
       subtype: "WEBSITE",
       retention_days: 14,
       pixel_id: "1234567890"
     }
```

### 4. A/B Test Setup

Testing two ad sets with different targeting:

```
Step 1: Create ad set A (CONFIRM WITH USER)
  -> meta_ads.ad_sets.create {
       account_id, campaign_id,
       name: "Test A - Ages 25-34",
       daily_budget: 100000,
       targeting: {age_min: 25, age_max: 34}
     }

Step 2: Create ad set B (CONFIRM WITH USER)
  -> meta_ads.ad_sets.create {
       account_id, campaign_id,
       name: "Test B - Ages 35-44",
       daily_budget: 100000,
       targeting: {age_min: 35, age_max: 44}
     }

Step 3: Add the same ad creative to both
  -> meta_ads.ads.create {account_id, ad_set_id: "A_ID", name: "Test A Ad", creative_id}
  -> meta_ads.ads.create {account_id, ad_set_id: "B_ID", name: "Test B Ad", creative_id}

Step 4: After running, compare performance
  -> meta_ads.insights.report {account_id, period: "last_7d", level: "adset"}
```

### 5. Budget Adjustment

Safe budget change for a Meta Ads campaign:

```
Step 1: Get current campaign details
  -> meta_ads.campaigns.get {account_id, campaign_id}
  (Note the current daily_budget)

Step 2: Calculate change percentage
  Example: current 300000 cents -> new 500000 cents = +67%

Step 3: Show user the change and get confirmation
  "Budget change: 3,000 -> 5,000 (+67%)
   This is a significant change. Proceed? [y/n]"

Step 4: Update budget (CONFIRM WITH USER)
  -> meta_ads.campaigns.update {account_id, campaign_id, daily_budget: 500000}
```

## Important Notes

- **Budget in cents**: All budget and monetary values are in **cents** (1/100 of the account currency). For example, `daily_budget: 500000` = 5,000 in the account currency.
- **account_id format**: Must include the `act_` prefix (e.g., `"act_123456789"`).
- **Status values**: Meta uses `ACTIVE` / `PAUSED` (not `ENABLED`).
- **Creative-first model**: In Meta Ads, you create a creative object first, then reference its `creative_id` when creating an ad. The MCP toolkit currently requires an existing `creative_id`.
- **Targeting object**: The targeting structure follows the Meta Marketing API format. Common fields include `geo_locations`, `age_min`, `age_max`, `genders`, `interests`, `behaviors`, and `custom_audiences`.
