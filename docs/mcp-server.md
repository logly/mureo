# MCP Server Guide

mureo exposes 169 advertising and SEO operation tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP). Any MCP-compatible client can connect and call these tools over stdio.

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

## Tool Reference (169 tools)

### Google Ads (82 tools)

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
| `google_ads.ads.policy_details` | Get ad policy approval details | `customer_id`, `ad_group_id`, `ad_id` |

#### Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.keywords.list` | List keywords | `customer_id` |
| `google_ads.keywords.add` | Add keywords | `customer_id`, `ad_group_id`, `keywords` |
| `google_ads.keywords.remove` | Remove a keyword | `customer_id`, `ad_group_id`, `criterion_id` |
| `google_ads.keywords.suggest` | Get keyword suggestions (Keyword Planner) | `customer_id`, `seed_keywords` |
| `google_ads.keywords.diagnose` | Diagnose keyword quality scores | `customer_id`, `campaign_id` |
| `google_ads.keywords.pause` | Pause a keyword | `customer_id`, `ad_group_id`, `criterion_id` |
| `google_ads.keywords.audit` | Audit keyword performance and quality | `customer_id`, `campaign_id` |
| `google_ads.keywords.cross_adgroup_duplicates` | Find duplicate keywords across ad groups | `customer_id`, `campaign_id` |

#### Negative Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.negative_keywords.list` | List negative keywords | `customer_id`, `campaign_id` |
| `google_ads.negative_keywords.add` | Add negative keywords to a campaign | `customer_id`, `campaign_id`, `keywords` |
| `google_ads.negative_keywords.remove` | Remove a negative keyword | `customer_id`, `campaign_id`, `criterion_id` |
| `google_ads.negative_keywords.add_to_ad_group` | Add negative keywords to an ad group | `customer_id`, `ad_group_id`, `keywords` |
| `google_ads.negative_keywords.suggest` | Suggest negative keywords based on search terms | `customer_id`, `campaign_id` |

#### Budget

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.budget.get` | Get campaign budget | `customer_id`, `campaign_id` |
| `google_ads.budget.update` | Update budget | `customer_id`, `budget_id`, `amount` |
| `google_ads.budget.create` | Create a new campaign budget | `customer_id`, `name`, `amount` |

#### Accounts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.accounts.list` | List accessible Google Ads accounts | *(none)* |

#### Search Terms

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.search_terms.report` | Get search terms report | `customer_id` |
| `google_ads.search_terms.analyze` | Analyze search terms with intent classification | `customer_id`, `campaign_id` |

#### Sitelinks

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.sitelinks.list` | List sitelink extensions | `customer_id`, `campaign_id` |
| `google_ads.sitelinks.create` | Create a sitelink extension | `customer_id`, `campaign_id`, `sitelink_text`, `final_url` |
| `google_ads.sitelinks.remove` | Remove a sitelink extension | `customer_id`, `campaign_id`, `extension_id` |

#### Callouts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.callouts.list` | List callout extensions | `customer_id`, `campaign_id` |
| `google_ads.callouts.create` | Create a callout extension | `customer_id`, `campaign_id`, `callout_text` |
| `google_ads.callouts.remove` | Remove a callout extension | `customer_id`, `campaign_id`, `extension_id` |

#### Conversions

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.conversions.list` | List conversion actions | `customer_id` |
| `google_ads.conversions.get` | Get conversion action details | `customer_id`, `conversion_action_id` |
| `google_ads.conversions.performance` | Get conversion performance metrics | `customer_id` |
| `google_ads.conversions.create` | Create a conversion action | `customer_id`, `name`, `type` |
| `google_ads.conversions.update` | Update a conversion action | `customer_id`, `conversion_action_id` |
| `google_ads.conversions.remove` | Remove a conversion action | `customer_id`, `conversion_action_id` |
| `google_ads.conversions.tag` | Get conversion tracking tag snippet | `customer_id`, `conversion_action_id` |

#### Targeting

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.recommendations.list` | List optimization recommendations | `customer_id` |
| `google_ads.recommendations.apply` | Apply an optimization recommendation | `customer_id`, `recommendation_id` |
| `google_ads.device_targeting.get` | Get device targeting settings | `customer_id`, `campaign_id` |
| `google_ads.device_targeting.set` | Set device targeting bid adjustments | `customer_id`, `campaign_id`, `device_type`, `bid_modifier` |
| `google_ads.bid_adjustments.get` | Get bid adjustment settings | `customer_id`, `campaign_id` |
| `google_ads.bid_adjustments.update` | Update bid adjustments | `customer_id`, `campaign_id` |
| `google_ads.location_targeting.list` | List location targeting criteria | `customer_id`, `campaign_id` |
| `google_ads.location_targeting.update` | Update location targeting | `customer_id`, `campaign_id` |
| `google_ads.schedule_targeting.list` | List ad schedule targeting | `customer_id`, `campaign_id` |
| `google_ads.schedule_targeting.update` | Update ad schedule targeting | `customer_id`, `campaign_id` |
| `google_ads.change_history.list` | List account change history | `customer_id` |

#### Analysis & Reporting

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.performance.report` | Get performance report | `customer_id` |
| `google_ads.performance.analyze` | Analyze performance trends and anomalies | `customer_id` |
| `google_ads.cost_increase.investigate` | Investigate sudden cost increases | `customer_id`, `campaign_id` |
| `google_ads.health_check.all` | Run a comprehensive account health check | `customer_id` |
| `google_ads.ad_performance.compare` | Compare ad performance across variants | `customer_id`, `ad_group_id` |
| `google_ads.ad_performance.report` | Get detailed ad-level performance report | `customer_id` |
| `google_ads.network_performance.report` | Get network-level performance breakdown | `customer_id` |
| `google_ads.budget.efficiency` | Analyze budget utilization efficiency | `customer_id` |
| `google_ads.budget.reallocation` | Suggest budget reallocation across campaigns | `customer_id` |
| `google_ads.auction_insights.get` | Get auction insights (competitor analysis) | `customer_id`, `campaign_id` |
| `google_ads.rsa_assets.analyze` | Analyze RSA asset performance | `customer_id`, `ad_group_id` |
| `google_ads.rsa_assets.audit` | Audit RSA assets for best practices | `customer_id`, `campaign_id` |
| `google_ads.search_terms.review` | Review search terms with rule-based scoring | `customer_id`, `campaign_id` |

#### B2B

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.btob.optimizations` | Get B2B-specific optimization suggestions | `customer_id` |

#### Creative

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.landing_page.analyze` | Analyze landing page relevance and quality | `customer_id`, `campaign_id` |
| `google_ads.creative.research` | Research competitive creative strategies | `customer_id` |

#### Monitoring

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.monitoring.delivery_goal` | Monitor campaign delivery against goals | `customer_id`, `campaign_id` |
| `google_ads.monitoring.cpa_goal` | Monitor CPA against target goals | `customer_id`, `campaign_id` |
| `google_ads.monitoring.cv_goal` | Monitor conversion volume against goals | `customer_id`, `campaign_id` |
| `google_ads.monitoring.zero_conversions` | Detect campaigns with zero conversions | `customer_id` |

#### Capture

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.capture.screenshot` | Capture a screenshot of a URL | `url` |

#### Device & CPC

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.device.analyze` | Analyze device-level performance | `customer_id`, `campaign_id` |
| `google_ads.cpc.detect_trend` | Detect CPC trend (rising/stable/falling) | `customer_id`, `campaign_id` |

#### Image Assets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads.assets.upload_image` | Upload a local image file as a Google Ads asset | `customer_id`, `file_path` |

### Meta Ads (77 tools)

#### Campaigns

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.campaigns.list` | List campaigns | `account_id` |
| `meta_ads.campaigns.get` | Get campaign details | `account_id`, `campaign_id` |
| `meta_ads.campaigns.create` | Create a campaign | `account_id`, `name`, `objective` |
| `meta_ads.campaigns.update` | Update a campaign | `account_id`, `campaign_id` |
| `meta_ads.campaigns.pause` | Pause a campaign | `account_id`, `campaign_id` |
| `meta_ads.campaigns.enable` | Enable a paused campaign | `account_id`, `campaign_id` |

#### Ad Sets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.ad_sets.list` | List ad sets | `account_id` |
| `meta_ads.ad_sets.create` | Create an ad set | `account_id`, `campaign_id`, `name`, `daily_budget` |
| `meta_ads.ad_sets.update` | Update an ad set | `account_id`, `ad_set_id` |
| `meta_ads.ad_sets.get` | Get ad set details | `account_id`, `ad_set_id` |
| `meta_ads.ad_sets.pause` | Pause an ad set | `account_id`, `ad_set_id` |
| `meta_ads.ad_sets.enable` | Enable a paused ad set | `account_id`, `ad_set_id` |

#### Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.ads.list` | List ads | `account_id` |
| `meta_ads.ads.create` | Create an ad | `account_id`, `ad_set_id`, `name`, `creative_id` |
| `meta_ads.ads.update` | Update an ad | `account_id`, `ad_id` |
| `meta_ads.ads.get` | Get ad details | `account_id`, `ad_id` |
| `meta_ads.ads.pause` | Pause an ad | `account_id`, `ad_id` |
| `meta_ads.ads.enable` | Enable a paused ad | `account_id`, `ad_id` |

#### Creatives

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.creatives.list` | List ad creatives | `account_id` |
| `meta_ads.creatives.create` | Create a standard ad creative | `account_id`, `name` |
| `meta_ads.creatives.create_carousel` | Create a carousel creative (2-10 cards) | `account_id`, `page_id`, `cards`, `link` |
| `meta_ads.creatives.create_collection` | Create a collection creative | `account_id`, `page_id`, `product_ids`, `link` |
| `meta_ads.creatives.create_dynamic` | Create a dynamic product ad creative | `account_id`, `catalog_id` |
| `meta_ads.creatives.upload_image` | Upload an image for use in creatives | `account_id`, `file_path` |

#### Images

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.images.upload_file` | Upload an image from local file | `account_id`, `file_path` |

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
| `meta_ads.audiences.get` | Get audience details | `account_id`, `audience_id` |
| `meta_ads.audiences.delete` | Delete a custom audience | `account_id`, `audience_id` |
| `meta_ads.audiences.create_lookalike` | Create a lookalike audience | `account_id`, `source_audience_id`, `country` |

#### Conversions API (CAPI)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.conversions.send` | Send conversion events (generic) | `account_id`, `pixel_id`, `events` |
| `meta_ads.conversions.send_purchase` | Send a purchase event | `account_id`, `pixel_id`, `event_time`, `user_data`, `currency`, `value` |
| `meta_ads.conversions.send_lead` | Send a lead event | `account_id`, `pixel_id`, `event_time`, `user_data` |

#### Pixels

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.pixels.list` | List pixels | `account_id` |
| `meta_ads.pixels.get` | Get pixel details | `account_id`, `pixel_id` |
| `meta_ads.pixels.stats` | Get pixel firing statistics | `account_id`, `pixel_id` |
| `meta_ads.pixels.events` | List pixel events | `account_id`, `pixel_id` |

#### Analysis

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads.analysis.performance` | Analyze overall performance trends | `account_id` |
| `meta_ads.analysis.audience` | Analyze audience performance and overlap | `account_id` |
| `meta_ads.analysis.placements` | Analyze placement performance breakdown | `account_id` |
| `meta_ads.analysis.cost` | Analyze cost trends and efficiency | `account_id` |
| `meta_ads.analysis.compare_ads` | Compare performance across ads | `account_id` |
| `meta_ads.analysis.suggest_creative` | Suggest creative improvements based on data | `account_id` |

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

*(See Creatives section above for carousel and collection tools.)*

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

### Search Console (10 tools)

Search Console tools reuse the same Google OAuth2 credentials as Google Ads -- no additional authentication is required.

#### Sites

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console.sites.list` | List verified sites | *(none)* |
| `search_console.sites.get` | Get site details | `site_url` |

#### Analytics

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console.analytics.query` | Query search analytics data | `site_url` |
| `search_console.analytics.top_queries` | Get top search queries | `site_url` |
| `search_console.analytics.top_pages` | Get top pages by clicks/impressions | `site_url` |
| `search_console.analytics.device_breakdown` | Get performance breakdown by device | `site_url` |
| `search_console.analytics.compare_periods` | Compare search performance across time periods | `site_url` |

#### Sitemaps

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console.sitemaps.list` | List sitemaps for a site | `site_url` |
| `search_console.sitemaps.submit` | Submit a sitemap | `site_url`, `sitemap_url` |

#### URL Inspection

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console.url_inspection.inspect` | Inspect a URL for indexing status | `site_url`, `inspection_url` |

## Workflow Commands

Beyond individual MCP tools, mureo provides higher-level operational workflows via **Claude Code slash commands**. These commands orchestrate multiple MCP tools in sequence, guided by the strategy context defined in `STRATEGY.md`.

| Command | Purpose |
|---------|---------|
| `/onboard` | Interactive account setup, STRATEGY.md generation, STATE.json init |
| `/daily-check` | Mode-aware daily health monitoring |
| `/rescue` | Emergency performance rescue |
| `/search-term-cleanup` | Strategy-aligned search term hygiene |
| `/creative-refresh` | Persona/USP-driven ad copy refresh |
| `/budget-rebalance` | Mode-guided budget reallocation |
| `/competitive-scan` | Auction analysis with Market Context |
| `/sync-state` | Manual STATE.json synchronization |

Each command reads strategy context (Operation Mode, Persona, USP, Brand Voice, Market Context) from `STRATEGY.md` and campaign state from `STATE.json`, then selects and invokes the appropriate MCP tools. For example, `/daily-check` adapts its monitoring focus based on the current Operation Mode -- an `EFFICIENCY_STABILIZE` mode prioritizes CPA and budget efficiency, while a `GROWTH_SCALE` mode focuses on impression share and conversion volume.

Command definitions live in `.claude/commands/`. See [strategy-context.md](strategy-context.md) for details on the strategy files, and `skills/mureo-workflows/SKILL.md` for the full Operation Mode reference.

## Working with External MCP Servers

mureo is designed to work alongside other MCP servers in the same client session. For example, you can configure a GA4 MCP server next to mureo so that workflow commands like `/daily-check` and `/budget-rebalance` can incorporate analytics data into their analysis.

mureo's workflow commands check for external tool availability opportunistically -- if a GA4 or other MCP server responds, the agent uses that data; if not, the command proceeds with mureo's own data. There is no hard dependency on any external MCP server.

For detailed setup instructions, supported platforms, and configuration examples, see [integrations.md](integrations.md).

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

## Rate Limiting

AI agents can issue tool calls at high speed, which risks hitting API rate limits and triggering temporary bans. mureo includes a built-in throttling layer (`mureo/throttle.py`) that transparently rate-limits all outgoing API requests.

### Default Limits

| Platform | QPS | Burst | Hourly Cap |
|----------|-----|-------|------------|
| Google Ads | 10 | 5 | -- |
| Meta Ads | 20 | 10 | 50,000 |
| Search Console | 5 | 5 | -- |

The throttler uses a **token bucket algorithm** combined with a **rolling hourly cap** (Meta Ads only). When the bucket is empty, the request awaits until a token becomes available -- no errors are raised and no tool calls are dropped.

Each platform has a module-level singleton throttler that is shared across all MCP tool calls in the same server process. No user configuration is required; throttling is always active.
