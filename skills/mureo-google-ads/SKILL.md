---
name: mureo-google-ads
description: "Google Ads: Manage campaigns, ad groups, ads, keywords, budgets, and performance analysis."
metadata:
  version: 0.1.0
  openclaw:
    category: "advertising"
    requires:
      bins:
        - mureo
    cliHelp: "mureo google-ads --help"
---

# Google Ads (v18)
> PREREQUISITE: Read `../mureo-shared/SKILL.md` for auth, global flags, and security rules.

## Tool Summary (28 tools)

| # | Tool Name | Category | Type | Description |
|---|-----------|----------|------|-------------|
| 1 | `google_ads.campaigns.list` | Campaign | Read | List campaigns |
| 2 | `google_ads.campaigns.get` | Campaign | Read | Get campaign details |
| 3 | `google_ads.campaigns.create` | Campaign | Write | Create a campaign |
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
| 14 | `google_ads.keywords.list` | Keyword | Read | List keywords |
| 15 | `google_ads.keywords.add` | Keyword | Write | Add keywords |
| 16 | `google_ads.keywords.remove` | Keyword | Write | Remove a keyword |
| 17 | `google_ads.keywords.suggest` | Keyword | Read | Suggest keywords via Keyword Planner |
| 18 | `google_ads.keywords.diagnose` | Keyword | Read | Diagnose keyword quality scores |
| 19 | `google_ads.negative_keywords.list` | Negative KW | Read | List negative keywords |
| 20 | `google_ads.negative_keywords.add` | Negative KW | Write | Add negative keywords |
| 21 | `google_ads.budget.get` | Budget | Read | Get campaign budget |
| 22 | `google_ads.budget.update` | Budget | Write | Update daily budget |
| 23 | `google_ads.performance.report` | Analysis | Read | Performance report |
| 24 | `google_ads.search_terms.report` | Analysis | Read | Search terms report |
| 25 | `google_ads.search_terms.review` | Analysis | Read | Review search terms with add/exclude suggestions |
| 26 | `google_ads.auction_insights.analyze` | Analysis | Read | Auction insights analysis |
| 27 | `google_ads.cpc.detect_trend` | Analysis | Read | Detect CPC trend direction |
| 28 | `google_ads.device.analyze` | Analysis | Read | Device performance analysis |

## API Resources

### campaigns

- `list` -- List all campaigns in the account.
  ```
  Required: customer_id (string)
  Optional: status_filter (string: "ENABLED" | "PAUSED")
  ```
  ```json
  // Example call
  {"customer_id": "1234567890"}

  // Example response
  {
    "campaigns": [
      {
        "campaign_id": "111222333",
        "name": "Brand Search - Tokyo",
        "status": "ENABLED",
        "bidding_strategy_type": "MAXIMIZE_CONVERSIONS",
        "daily_budget": 5000.0,
        "impressions": 12500,
        "clicks": 890,
        "conversions": 45
      }
    ]
  }
  ```

- `get` -- Get detailed information about a specific campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```
  ```json
  {"customer_id": "1234567890", "campaign_id": "111222333"}
  ```

- `create` -- Create a new search campaign. **Requires user confirmation.**
  ```
  Required: customer_id, name (string)
  Optional: bidding_strategy (string: "MAXIMIZE_CLICKS" | "MAXIMIZE_CONVERSIONS" | "TARGET_CPA" | ...),
            budget_id (string)
  ```
  ```json
  {
    "customer_id": "1234567890",
    "name": "New Product Launch 2026",
    "bidding_strategy": "MAXIMIZE_CONVERSIONS",
    "budget_id": "444555666"
  }
  ```

- `update` -- Update campaign settings (name, bidding strategy). **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id (string)
  Optional: name (string), bidding_strategy (string)
  ```

- `update_status` -- Change campaign status (enable, pause, remove). **Requires user confirmation.**
  ```
  Required: customer_id, campaign_id, status (string: "ENABLED" | "PAUSED" | "REMOVED")
  ```

- `diagnose` -- Comprehensive delivery diagnosis for a campaign. Returns serving status, policy issues, budget constraints, and recommendations.
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
  ```json
  {
    "customer_id": "1234567890",
    "campaign_id": "111222333",
    "name": "Exact Match - Core Terms",
    "cpc_bid_micros": 500000
  }
  ```

- `update` -- Update ad group settings. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id (string)
  Optional: name (string), status (string: "ENABLED" | "PAUSED"), cpc_bid_micros (integer)
  ```

### ads

- `list` -- List ads, optionally filtered by ad group.
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
  ```json
  {
    "customer_id": "1234567890",
    "ad_group_id": "777888999",
    "headlines": [
      "Official Store - Free Shipping",
      "New Arrivals 2026 Collection",
      "Limited Time 30% Off"
    ],
    "descriptions": [
      "Shop the latest collection. Free shipping on orders over $50.",
      "Trusted by 100,000+ customers. Easy returns within 30 days."
    ],
    "final_url": "https://example.com/products",
    "path1": "products",
    "path2": "new"
  }
  ```

- `update` -- Update RSA ad content. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, ad_id (string)
  Optional: headlines (array of strings), descriptions (array of strings)
  ```

- `update_status` -- Change ad status. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, ad_id, status (string: "ENABLED" | "PAUSED")
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
  ```json
  {
    "customer_id": "1234567890",
    "ad_group_id": "777888999",
    "keywords": [
      {"text": "running shoes", "match_type": "PHRASE"},
      {"text": "marathon training shoes", "match_type": "EXACT"},
      {"text": "best running shoes 2026"}
    ]
  }
  ```
  Note: `match_type` defaults to `BROAD` if omitted.

- `remove` -- Remove a keyword by criterion ID. **Requires user confirmation.**
  ```
  Required: customer_id, ad_group_id, criterion_id (string)
  ```

- `suggest` -- Get keyword suggestions from Keyword Planner.
  ```
  Required: customer_id (string),
            seed_keywords (array of strings)
  Optional: language_id (string, default: "1005" = Japanese),
            geo_id (string, default: "2392" = Japan)
  ```
  ```json
  {
    "customer_id": "1234567890",
    "seed_keywords": ["running shoes", "athletic footwear"]
  }
  ```

- `diagnose` -- Diagnose keyword quality scores and delivery status for a campaign.
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
  ```json
  {
    "customer_id": "1234567890",
    "campaign_id": "111222333",
    "keywords": [
      {"text": "free", "match_type": "BROAD"},
      {"text": "cheap", "match_type": "BROAD"},
      {"text": "how to", "match_type": "PHRASE"}
    ]
  }
  ```

### budget

- `get` -- Get the daily budget for a campaign.
  ```
  Required: customer_id, campaign_id (string)
  ```
  ```json
  // Example response
  {
    "budget_id": "444555666",
    "campaign_id": "111222333",
    "amount": 5000.0,
    "delivery_method": "STANDARD"
  }
  ```

- `update` -- Update daily budget amount. **Requires user confirmation.** Always show current vs. new amount.
  ```
  Required: customer_id, budget_id (string), amount (number)
  ```
  ```json
  {
    "customer_id": "1234567890",
    "budget_id": "444555666",
    "amount": 8000.0
  }
  ```

### performance (Analysis)

- `report` -- Get performance metrics aggregated by campaign.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), period (string, default: "LAST_30_DAYS")
  ```
  Period options: `TODAY`, `YESTERDAY`, `LAST_7_DAYS`, `LAST_14_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`, `LAST_MONTH`
  ```json
  {"customer_id": "1234567890", "period": "LAST_7_DAYS"}
  ```

### search_terms (Analysis)

- `report` -- Get search terms report showing actual queries that triggered ads.
  ```
  Required: customer_id (string)
  Optional: campaign_id (string), ad_group_id (string), period (string, default: "LAST_30_DAYS")
  ```

- `review` -- Multi-rule review of search terms with add/exclude recommendations. Evaluates each search term against performance thresholds and suggests candidates for keyword addition or negative keyword exclusion.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_7_DAYS"), target_cpa (number)
  ```
  ```json
  {
    "customer_id": "1234567890",
    "campaign_id": "111222333",
    "target_cpa": 3000.0
  }
  ```

### auction_insights (Analysis)

- `analyze` -- Analyze auction insights: impression share, overlap rate, top-of-page rate, and competitor domains.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

### cpc (Analysis)

- `detect_trend` -- Detect CPC trend direction (rising / stable / falling) using linear regression on daily CPC data. Also detects sudden spikes and week-over-week changes.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

### device (Analysis)

- `analyze` -- Compare performance across devices (Desktop / Mobile / Tablet). Shows CPA, CVR, CTR per device, detects CPA gaps, and identifies wasted spend on zero-conversion devices.
  ```
  Required: customer_id, campaign_id (string)
  Optional: period (string, default: "LAST_30_DAYS")
  ```

## Common Workflows

### 1. Performance Check

A typical daily performance check flow:

```
Step 1: List campaigns to identify active ones
  -> google_ads.campaigns.list {customer_id, status_filter: "ENABLED"}

Step 2: Get overall performance report
  -> google_ads.performance.report {customer_id, period: "LAST_7_DAYS"}

Step 3: For underperforming campaigns, run diagnostics
  -> google_ads.campaigns.diagnose {customer_id, campaign_id}

Step 4: Check keyword quality scores
  -> google_ads.keywords.diagnose {customer_id, campaign_id}

Step 5: Analyze device performance for CPA gaps
  -> google_ads.device.analyze {customer_id, campaign_id}
```

### 2. Negative Keyword Addition

When cleaning up wasted spend from irrelevant search terms:

```
Step 1: Get search terms report
  -> google_ads.search_terms.report {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Or use automated review for suggestions
  -> google_ads.search_terms.review {customer_id, campaign_id, target_cpa: 3000}

Step 3: Review current negative keywords to avoid duplicates
  -> google_ads.negative_keywords.list {customer_id, campaign_id}

Step 4: Add negative keywords (CONFIRM WITH USER)
  -> google_ads.negative_keywords.add {customer_id, campaign_id, keywords: [...]}
```

### 3. New Campaign Creation

Full campaign setup from scratch:

```
Step 1: Create the campaign
  -> google_ads.campaigns.create {customer_id, name, bidding_strategy, budget_id}

Step 2: Create ad groups
  -> google_ads.ad_groups.create {customer_id, campaign_id, name}

Step 3: Add keywords to each ad group
  -> google_ads.keywords.add {customer_id, ad_group_id, keywords: [...]}

Step 4: Create RSA ads for each ad group
  -> google_ads.ads.create {customer_id, ad_group_id, headlines: [...], descriptions: [...], final_url}

Step 5: Add campaign-level negative keywords
  -> google_ads.negative_keywords.add {customer_id, campaign_id, keywords: [...]}

Step 6: Enable the campaign (starts with PAUSED by default)
  -> google_ads.campaigns.update_status {customer_id, campaign_id, status: "ENABLED"}
```

### 4. Budget Adjustment

Safe budget change workflow:

```
Step 1: Get current budget
  -> google_ads.budget.get {customer_id, campaign_id}
  (Note the budget_id and current amount)

Step 2: Calculate change percentage
  Example: current 5,000 -> new 6,000 = +20%

Step 3: Show user the change details and get confirmation
  "Budget change: 5,000 -> 6,000 (+20%)
   This exceeds the 20% threshold. Smart bidding learning may be affected.
   Proceed? [y/n]"

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

Step 4: Check CPC trends (are bids competitive?)
  -> google_ads.cpc.detect_trend {customer_id, campaign_id}

Step 5: Analyze auction insights (competitor landscape)
  -> google_ads.auction_insights.analyze {customer_id, campaign_id}

Step 6: Review budget constraints
  -> google_ads.budget.get {customer_id, campaign_id}
```

### 6. Competitive Analysis

Understanding the competitive landscape:

```
Step 1: Analyze auction insights
  -> google_ads.auction_insights.analyze {customer_id, campaign_id, period: "LAST_30_DAYS"}

Step 2: Detect CPC trend (rising CPC may indicate increased competition)
  -> google_ads.cpc.detect_trend {customer_id, campaign_id}

Step 3: Review device performance (competitors may dominate certain devices)
  -> google_ads.device.analyze {customer_id, campaign_id}

Step 4: Get keyword suggestions to find new opportunities
  -> google_ads.keywords.suggest {customer_id, seed_keywords: ["..."]}
```

## Important Notes

- **Micros**: Some values (e.g., `cpc_bid_micros`) are in micros where 1,000,000 = 1 currency unit. For example, 500,000 micros = 0.50 in the account currency.
- **Period values**: Use Google Ads date range constants like `LAST_7_DAYS`, `LAST_30_DAYS`, `THIS_MONTH`.
- **customer_id**: Always a 10-digit string without dashes (e.g., `"1234567890"`, not `"123-456-7890"`).
- **RSA limits**: Headlines 3-15, descriptions 2-4. Maximum 3 enabled RSA ads per ad group.
