# MCP Server Guide

mureo exposes 81 advertising operation tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). Any MCP-compatible client can connect and call these tools over stdio.

## Starting the Server

```bash
# Requires the mcp extra
pip install "mureo[mcp]"

# Start the MCP server
python -m mureo.mcp
```

The server communicates over stdin/stdout using the MCP JSON-RPC protocol. It is not meant to be run interactively -- it should be launched by an MCP client.

## Client Configuration

### Claude Desktop

Add to your MCP configuration (`~/.config/claude/mcp.json` or the app's settings):

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

### Using a Virtual Environment

If mureo is installed in a virtual environment, use the full path to the Python interpreter:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "mureo.mcp"]
    }
  }
}
```

Or use `uv` to run it:

```json
{
  "mcpServers": {
    "mureo": {
      "command": "uv",
      "args": ["run", "python", "-m", "mureo.mcp"]
    }
  }
}
```

## Tool Reference (81 tools)

### Google Ads (29 tools)

#### Campaigns

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.campaigns.list` | List campaigns | `customer_id` |
| `google_ads.campaigns.get` | Get campaign details | `customer_id`, `campaign_id` |
| `google_ads.campaigns.create` | Create a campaign | `customer_id`, `name` |
| `google_ads.campaigns.update` | Update campaign settings | `customer_id`, `campaign_id` |
| `google_ads.campaigns.update_status` | Change status (ENABLED/PAUSED/REMOVED) | `customer_id`, `campaign_id`, `status` |
| `google_ads.campaigns.diagnose` | Diagnose campaign delivery | `customer_id`, `campaign_id` |

#### Ad Groups

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.ad_groups.list` | List ad groups | `customer_id` |
| `google_ads.ad_groups.create` | Create an ad group | `customer_id`, `campaign_id`, `name` |
| `google_ads.ad_groups.update` | Update an ad group | `customer_id`, `ad_group_id` |

#### Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.ads.list` | List ads | `customer_id` |
| `google_ads.ads.create` | Create a responsive search ad (RSA) | `customer_id`, `ad_group_id`, `headlines`, `descriptions` |
| `google_ads.ads.update` | Update an ad | `customer_id`, `ad_group_id`, `ad_id` |
| `google_ads.ads.update_status` | Change ad status | `customer_id`, `ad_group_id`, `ad_id`, `status` |

#### Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.keywords.list` | List keywords | `customer_id` |
| `google_ads.keywords.add` | Add keywords | `customer_id`, `ad_group_id`, `keywords` |
| `google_ads.keywords.remove` | Remove a keyword | `customer_id`, `ad_group_id`, `criterion_id` |
| `google_ads.keywords.suggest` | Get keyword suggestions (Keyword Planner) | `customer_id`, `seed_keywords` |
| `google_ads.keywords.diagnose` | Diagnose keyword quality scores | `customer_id`, `campaign_id` |

#### Negative Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.negative_keywords.list` | List negative keywords | `customer_id`, `campaign_id` |
| `google_ads.negative_keywords.add` | Add negative keywords | `customer_id`, `campaign_id`, `keywords` |

#### Budget

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.budget.get` | Get campaign budget | `customer_id`, `campaign_id` |
| `google_ads.budget.update` | Update budget | `customer_id`, `budget_id`, `amount` |

#### Analysis & Reporting

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.performance.report` | Get performance report | `customer_id` |
| `google_ads.search_terms.report` | Get search terms report | `customer_id` |
| `google_ads.search_terms.review` | Review search terms with rule-based scoring | `customer_id`, `campaign_id` |
| `google_ads.auction_insights.analyze` | Analyze auction insights (competitors) | `customer_id`, `campaign_id` |
| `google_ads.cpc.detect_trend` | Detect CPC trend (rising/stable/falling) | `customer_id`, `campaign_id` |
| `google_ads.device.analyze` | Analyze device-level performance | `customer_id`, `campaign_id` |

#### Image Assets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.assets.upload_image` | Upload a local image file as a Google Ads asset | `customer_id`, `file_path` |

### Meta Ads (52 tools)

#### Campaigns

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.campaigns.list` | List campaigns | `account_id` |
| `meta_ads.campaigns.get` | Get campaign details | `account_id`, `campaign_id` |
| `meta_ads.campaigns.create` | Create a campaign | `account_id`, `name`, `objective` |
| `meta_ads.campaigns.update` | Update a campaign | `account_id`, `campaign_id` |

#### Ad Sets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.ad_sets.list` | List ad sets | `account_id` |
| `meta_ads.ad_sets.create` | Create an ad set | `account_id`, `campaign_id`, `name`, `daily_budget` |
| `meta_ads.ad_sets.update` | Update an ad set | `account_id`, `ad_set_id` |

#### Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.ads.list` | List ads | `account_id` |
| `meta_ads.ads.create` | Create an ad | `account_id`, `ad_set_id`, `name`, `creative_id` |
| `meta_ads.ads.update` | Update an ad | `account_id`, `ad_id` |

#### Insights

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.insights.report` | Get performance report | `account_id` |
| `meta_ads.insights.breakdown` | Get breakdown report (age, gender, etc.) | `account_id`, `campaign_id` |

#### Audiences

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.audiences.list` | List custom audiences | `account_id` |
| `meta_ads.audiences.create` | Create a custom audience | `account_id`, `name`, `subtype` |

#### Conversions API (CAPI)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.conversions.send` | Send conversion events (generic) | `account_id`, `pixel_id`, `events` |
| `meta_ads.conversions.send_purchase` | Send a purchase event | `account_id`, `pixel_id`, `event_time`, `user_data`, `currency`, `value` |
| `meta_ads.conversions.send_lead` | Send a lead event | `account_id`, `pixel_id`, `event_time`, `user_data` |

#### Product Catalog (DPA)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.catalogs.list` | List product catalogs | `account_id`, `business_id` |
| `meta_ads.catalogs.create` | Create a product catalog | `account_id`, `business_id`, `name` |
| `meta_ads.catalogs.get` | Get catalog details | `account_id`, `catalog_id` |
| `meta_ads.catalogs.delete` | Delete a product catalog | `account_id`, `catalog_id` |
| `meta_ads.products.list` | List products in a catalog | `account_id`, `catalog_id` |
| `meta_ads.products.add` | Add a product to a catalog | `account_id`, `catalog_id`, `retailer_id`, `name`, `availability`, `condition`, `price`, `url`, `image_url` |
| `meta_ads.products.get` | Get product details | `account_id`, `product_id` |
| `meta_ads.products.update` | Update a product | `account_id`, `product_id` |
| `meta_ads.products.delete` | Delete a product | `account_id`, `product_id` |
| `meta_ads.feeds.list` | List feeds for a catalog | `account_id`, `catalog_id` |
| `meta_ads.feeds.create` | Create a feed (URL-based, scheduled import) | `account_id`, `catalog_id`, `name`, `feed_url` |

#### Lead Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.lead_forms.list` | List lead forms (per page) | `account_id`, `page_id` |
| `meta_ads.lead_forms.get` | Get lead form details | `account_id`, `form_id` |
| `meta_ads.lead_forms.create` | Create a lead form | `account_id`, `page_id`, `name`, `questions`, `privacy_policy_url` |
| `meta_ads.leads.get` | Get lead data (per form) | `account_id`, `form_id` |
| `meta_ads.leads.get_by_ad` | Get lead data (per ad) | `account_id`, `ad_id` |

#### Videos

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.videos.upload` | Upload a video from URL | `account_id`, `video_url` |
| `meta_ads.videos.upload_file` | Upload a video from local file | `account_id`, `file_path` |

#### Creatives (Carousel & Collection)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.creatives.create_carousel` | Create a carousel creative (2-10 cards) | `account_id`, `page_id`, `cards`, `link` |
| `meta_ads.creatives.create_collection` | Create a collection creative | `account_id`, `page_id`, `product_ids`, `link` |

#### Images

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.images.upload_file` | Upload an image from local file | `account_id`, `file_path` |

#### Split Tests (A/B Testing)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.split_tests.list` | List split tests | `account_id` |
| `meta_ads.split_tests.get` | Get split test details and results | `account_id`, `study_id` |
| `meta_ads.split_tests.create` | Create a split test | `account_id`, `name`, `cells`, `objectives`, `start_time`, `end_time` |
| `meta_ads.split_tests.end` | End a split test | `account_id`, `study_id` |

#### Ad Rules (Automated Rules)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.ad_rules.list` | List automated rules | `account_id` |
| `meta_ads.ad_rules.get` | Get rule details | `account_id`, `rule_id` |
| `meta_ads.ad_rules.create` | Create an automated rule (alerts, auto-pause, etc.) | `account_id`, `name`, `evaluation_spec`, `execution_spec` |
| `meta_ads.ad_rules.update` | Update an automated rule | `account_id`, `rule_id` |
| `meta_ads.ad_rules.delete` | Delete an automated rule | `account_id`, `rule_id` |

#### Page Posts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.page_posts.list` | List Facebook page posts | `account_id`, `page_id` |
| `meta_ads.page_posts.boost` | Boost a page post (create ad from post) | `account_id`, `page_id`, `post_id`, `ad_set_id` |

#### Instagram

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.instagram.accounts` | List connected Instagram accounts | `account_id` |
| `meta_ads.instagram.media` | List Instagram posts | `account_id`, `ig_user_id` |
| `meta_ads.instagram.boost` | Boost an Instagram post (create ad from post) | `account_id`, `ig_user_id`, `media_id`, `ad_set_id` |

## Input Parameters

### Google Ads: `customer_id`

The Google Ads customer ID is a 10-digit number (e.g., `"1234567890"`). Dashes are automatically stripped.

### Meta Ads: `account_id`

The Meta Ads account ID must start with `act_` (e.g., `"act_1234567890"`).

### Common Optional Parameters

- `status_filter`: Filter by entity status (`"ENABLED"`, `"PAUSED"`, etc.)
- `period`: Time range for reports (`"LAST_7_DAYS"`, `"LAST_30_DAYS"` for Google Ads; `"today"`, `"yesterday"`, `"last_7d"`, `"last_30d"` for Meta Ads)
- `limit`: Maximum number of results to return (Meta Ads, default: 50)

### Keywords Input Format

The `keywords` parameter for `google_ads.keywords.add` and `google_ads.negative_keywords.add` is an array of objects:

```json
{
  "keywords": [
    {"text": "running shoes", "match_type": "BROAD"},
    {"text": "best running shoes", "match_type": "PHRASE"},
    {"text": "nike running shoes", "match_type": "EXACT"}
  ]
}
```

`match_type` defaults to `"BROAD"` if omitted.

### RSA Creation Input

The `google_ads.ads.create` tool accepts headlines and descriptions arrays:

```json
{
  "customer_id": "1234567890",
  "ad_group_id": "111222333",
  "headlines": ["Buy Running Shoes", "Free Shipping", "Best Prices"],
  "descriptions": ["Shop our collection of running shoes.", "Free returns on all orders."],
  "final_url": "https://example.com/shoes"
}
```

Headlines: 3-15 items. Descriptions: 2-4 items.

## Output Format

All tools return `TextContent` with JSON-serialized results. The JSON structure varies by tool but follows a consistent pattern:

```json
[
  {
    "type": "text",
    "text": "{\"campaigns\": [{\"id\": \"123\", \"name\": \"Brand\", ...}]}"
  }
]
```

The `text` field contains a JSON string that your agent should parse.

## Error Handling

### Authentication Errors

If credentials are missing, tools return a descriptive error message (not an exception):

```json
[
  {
    "type": "text",
    "text": "Authentication credentials not found. Set environment variables or ~/.mureo/credentials.json."
  }
]
```

### API Errors

API errors (rate limits, invalid parameters, etc.) are caught by the `@api_error_handler` decorator and returned as text:

```json
[
  {
    "type": "text",
    "text": "API Error: Meta API request failed (status=400, path=/act_123/campaigns)"
  }
]
```

### Validation Errors

Missing required parameters raise `ValueError`, which the MCP protocol surfaces to the client:

```
ValueError: Required parameter customer_id is not specified
```

### Rate Limiting

- **Google Ads**: Uses gRPC with automatic retry built into the SDK.
- **Meta Ads**: mureo monitors the `x-business-use-case-usage` response header and automatically retries on HTTP 429 with exponential backoff (up to 3 attempts).
