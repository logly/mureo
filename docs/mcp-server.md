# MCP Server Guide

mureo exposes 173 tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP): 170 advertising and SEO operation tools across Google Ads, Meta Ads, and Search Console, plus 2 rollback tools and 1 cross-platform anomaly-detection tool. Any MCP-compatible client can connect and call these tools over stdio.

## Starting the Server

```bash
pip install mureo

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

## Tool Reference

### Google Ads

#### Campaigns

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_campaigns_list` | List campaigns | `customer_id` |
| `google_ads_campaigns_get` | Get campaign details | `customer_id`, `campaign_id` |
| `google_ads_campaigns_create` | Create a campaign (search or display, via `channel_type`) | `customer_id`, `name` |
| `google_ads_campaigns_update` | Update campaign settings | `customer_id`, `campaign_id` |
| `google_ads_campaigns_update_status` | Change status (ENABLED/PAUSED/REMOVED) | `customer_id`, `campaign_id`, `status` |
| `google_ads_campaigns_diagnose` | Diagnose campaign delivery | `customer_id`, `campaign_id` |

#### Ad Groups

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_ad_groups_list` | List ad groups | `customer_id` |
| `google_ads_ad_groups_create` | Create an ad group | `customer_id`, `campaign_id`, `name` |
| `google_ads_ad_groups_update` | Update an ad group | `customer_id`, `ad_group_id` |

#### Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_ads_list` | List ads | `customer_id` |
| `google_ads_ads_create` | Create a responsive search ad (RSA) | `customer_id`, `ad_group_id`, `headlines`, `descriptions` |
| `google_ads_ads_create_display` | Create a responsive display ad (RDA); image files are uploaded automatically | `customer_id`, `ad_group_id`, `headlines`, `long_headline`, `descriptions`, `business_name`, `marketing_image_paths`, `square_marketing_image_paths`, `final_url` |
| `google_ads_ads_update` | Update an ad | `customer_id`, `ad_group_id`, `ad_id` |
| `google_ads_ads_update_status` | Change ad status | `customer_id`, `ad_group_id`, `ad_id`, `status` |
| `google_ads_ads_policy_details` | Get ad policy approval details | `customer_id`, `ad_group_id`, `ad_id` |

#### Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_keywords_list` | List keywords | `customer_id` |
| `google_ads_keywords_add` | Add keywords | `customer_id`, `ad_group_id`, `keywords` |
| `google_ads_keywords_remove` | Remove a keyword | `customer_id`, `ad_group_id`, `criterion_id` |
| `google_ads_keywords_suggest` | Get keyword suggestions (Keyword Planner) | `customer_id`, `seed_keywords` |
| `google_ads_keywords_diagnose` | Diagnose keyword quality scores | `customer_id`, `campaign_id` |
| `google_ads_keywords_pause` | Pause a keyword | `customer_id`, `ad_group_id`, `criterion_id` |
| `google_ads_keywords_audit` | Audit keyword performance and quality | `customer_id`, `campaign_id` |
| `google_ads_keywords_cross_adgroup_duplicates` | Find duplicate keywords across ad groups | `customer_id`, `campaign_id` |

#### Negative Keywords

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_negative_keywords_list` | List negative keywords | `customer_id`, `campaign_id` |
| `google_ads_negative_keywords_add` | Add negative keywords to a campaign | `customer_id`, `campaign_id`, `keywords` |
| `google_ads_negative_keywords_remove` | Remove a negative keyword | `customer_id`, `campaign_id`, `criterion_id` |
| `google_ads_negative_keywords_add_to_ad_group` | Add negative keywords to an ad group | `customer_id`, `ad_group_id`, `keywords` |
| `google_ads_negative_keywords_suggest` | Suggest negative keywords based on search terms | `customer_id`, `campaign_id` |

#### Budget

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_budget_get` | Get campaign budget | `customer_id`, `campaign_id` |
| `google_ads_budget_update` | Update budget | `customer_id`, `budget_id`, `amount` |
| `google_ads_budget_create` | Create a new campaign budget | `customer_id`, `name`, `amount` |

#### Accounts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_accounts_list` | List accessible Google Ads accounts | *(none)* |

#### Search Terms

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_search_terms_report` | Get search terms report | `customer_id` |
| `google_ads_search_terms_analyze` | Analyze search terms with intent classification | `customer_id`, `campaign_id` |

#### Sitelinks

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_sitelinks_list` | List sitelink extensions | `customer_id`, `campaign_id` |
| `google_ads_sitelinks_create` | Create a sitelink extension | `customer_id`, `campaign_id`, `sitelink_text`, `final_url` |
| `google_ads_sitelinks_remove` | Remove a sitelink extension | `customer_id`, `campaign_id`, `extension_id` |

#### Callouts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_callouts_list` | List callout extensions | `customer_id`, `campaign_id` |
| `google_ads_callouts_create` | Create a callout extension | `customer_id`, `campaign_id`, `callout_text` |
| `google_ads_callouts_remove` | Remove a callout extension | `customer_id`, `campaign_id`, `extension_id` |

#### Conversions

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_conversions_list` | List conversion actions | `customer_id` |
| `google_ads_conversions_get` | Get conversion action details | `customer_id`, `conversion_action_id` |
| `google_ads_conversions_performance` | Get conversion performance metrics | `customer_id` |
| `google_ads_conversions_create` | Create a conversion action | `customer_id`, `name`, `type` |
| `google_ads_conversions_update` | Update a conversion action | `customer_id`, `conversion_action_id` |
| `google_ads_conversions_remove` | Remove a conversion action | `customer_id`, `conversion_action_id` |
| `google_ads_conversions_tag` | Get conversion tracking tag snippet | `customer_id`, `conversion_action_id` |

#### Targeting

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_recommendations_list` | List optimization recommendations | `customer_id` |
| `google_ads_recommendations_apply` | Apply an optimization recommendation | `customer_id`, `recommendation_id` |
| `google_ads_device_targeting_get` | Get device targeting settings | `customer_id`, `campaign_id` |
| `google_ads_device_targeting_set` | Set device targeting bid adjustments | `customer_id`, `campaign_id`, `device_type`, `bid_modifier` |
| `google_ads_bid_adjustments_get` | Get bid adjustment settings | `customer_id`, `campaign_id` |
| `google_ads_bid_adjustments_update` | Update bid adjustments | `customer_id`, `campaign_id` |
| `google_ads_location_targeting_list` | List location targeting criteria | `customer_id`, `campaign_id` |
| `google_ads_location_targeting_update` | Update location targeting | `customer_id`, `campaign_id` |
| `google_ads_schedule_targeting_list` | List ad schedule targeting | `customer_id`, `campaign_id` |
| `google_ads_schedule_targeting_update` | Update ad schedule targeting | `customer_id`, `campaign_id` |
| `google_ads_change_history_list` | List account change history | `customer_id` |

#### Analysis & Reporting

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_performance_report` | Get performance report | `customer_id` |
| `google_ads_performance_analyze` | Analyze performance trends and anomalies | `customer_id` |
| `google_ads_cost_increase_investigate` | Investigate sudden cost increases | `customer_id`, `campaign_id` |
| `google_ads_health_check_all` | Run a comprehensive account health check | `customer_id` |
| `google_ads_ad_performance_compare` | Compare ad performance across variants | `customer_id`, `ad_group_id` |
| `google_ads_ad_performance_report` | Get detailed ad-level performance report | `customer_id` |
| `google_ads_network_performance_report` | Get network-level performance breakdown | `customer_id` |
| `google_ads_budget_efficiency` | Analyze budget utilization efficiency | `customer_id` |
| `google_ads_budget_reallocation` | Suggest budget reallocation across campaigns | `customer_id` |
| `google_ads_auction_insights_get` | Get auction insights (competitor analysis) | `customer_id`, `campaign_id` |
| `google_ads_rsa_assets_analyze` | Analyze RSA asset performance | `customer_id`, `ad_group_id` |
| `google_ads_rsa_assets_audit` | Audit RSA assets for best practices | `customer_id`, `campaign_id` |
| `google_ads_search_terms_review` | Review search terms with rule-based scoring | `customer_id`, `campaign_id` |

#### B2B

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_btob_optimizations` | Get B2B-specific optimization suggestions | `customer_id` |

#### Creative

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_landing_page_analyze` | Analyze landing page relevance and quality | `customer_id`, `campaign_id` |
| `google_ads_creative_research` | Research competitive creative strategies | `customer_id` |

#### Monitoring

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_monitoring_delivery_goal` | Monitor campaign delivery against goals | `customer_id`, `campaign_id` |
| `google_ads_monitoring_cpa_goal` | Monitor CPA against target goals | `customer_id`, `campaign_id` |
| `google_ads_monitoring_cv_goal` | Monitor conversion volume against goals | `customer_id`, `campaign_id` |
| `google_ads_monitoring_zero_conversions` | Detect campaigns with zero conversions | `customer_id` |

#### Capture

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_capture_screenshot` | Capture a screenshot of a URL | `url` |

#### Device & CPC

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_device_analyze` | Analyze device-level performance | `customer_id`, `campaign_id` |
| `google_ads_cpc_detect_trend` | Detect CPC trend (rising/stable/falling) | `customer_id`, `campaign_id` |

#### Image Assets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_assets_upload_image` | Upload a local image file as a Google Ads asset | `customer_id`, `file_path` |

### Meta Ads

#### Campaigns

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_campaigns_list` | List campaigns | `account_id` |
| `meta_ads_campaigns_get` | Get campaign details | `account_id`, `campaign_id` |
| `meta_ads_campaigns_create` | Create a campaign | `account_id`, `name`, `objective` |
| `meta_ads_campaigns_update` | Update a campaign | `account_id`, `campaign_id` |
| `meta_ads_campaigns_pause` | Pause a campaign | `account_id`, `campaign_id` |
| `meta_ads_campaigns_enable` | Enable a paused campaign | `account_id`, `campaign_id` |

#### Ad Sets

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_ad_sets_list` | List ad sets | `account_id` |
| `meta_ads_ad_sets_create` | Create an ad set | `account_id`, `campaign_id`, `name`, `daily_budget` |
| `meta_ads_ad_sets_update` | Update an ad set | `account_id`, `ad_set_id` |
| `meta_ads_ad_sets_get` | Get ad set details | `account_id`, `ad_set_id` |
| `meta_ads_ad_sets_pause` | Pause an ad set | `account_id`, `ad_set_id` |
| `meta_ads_ad_sets_enable` | Enable a paused ad set | `account_id`, `ad_set_id` |

#### Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_ads_list` | List ads | `account_id` |
| `meta_ads_ads_create` | Create an ad | `account_id`, `ad_set_id`, `name`, `creative_id` |
| `meta_ads_ads_update` | Update an ad | `account_id`, `ad_id` |
| `meta_ads_ads_get` | Get ad details | `account_id`, `ad_id` |
| `meta_ads_ads_pause` | Pause an ad | `account_id`, `ad_id` |
| `meta_ads_ads_enable` | Enable a paused ad | `account_id`, `ad_id` |

#### Creatives

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_creatives_list` | List ad creatives | `account_id` |
| `meta_ads_creatives_create` | Create a standard ad creative | `account_id`, `name` |
| `meta_ads_creatives_create_carousel` | Create a carousel creative (2-10 cards) | `account_id`, `page_id`, `cards`, `link` |
| `meta_ads_creatives_create_collection` | Create a collection creative | `account_id`, `page_id`, `product_ids`, `link` |
| `meta_ads_creatives_create_dynamic` | Create a dynamic product ad creative | `account_id`, `catalog_id` |
| `meta_ads_creatives_upload_image` | Upload an image for use in creatives | `account_id`, `file_path` |

#### Images

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_images_upload_file` | Upload an image from local file | `account_id`, `file_path` |

#### Insights

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_insights_report` | Get performance report | `account_id` |
| `meta_ads_insights_breakdown` | Get breakdown report (age, gender, etc.) | `account_id`, `campaign_id` |

#### Audiences

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_audiences_list` | List custom audiences | `account_id` |
| `meta_ads_audiences_create` | Create a custom audience | `account_id`, `name`, `subtype` |
| `meta_ads_audiences_get` | Get audience details | `account_id`, `audience_id` |
| `meta_ads_audiences_delete` | Delete a custom audience | `account_id`, `audience_id` |
| `meta_ads_audiences_create_lookalike` | Create a lookalike audience | `account_id`, `source_audience_id`, `country` |

#### Conversions API (CAPI)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_conversions_send` | Send conversion events (generic) | `account_id`, `pixel_id`, `events` |
| `meta_ads_conversions_send_purchase` | Send a purchase event | `account_id`, `pixel_id`, `event_time`, `user_data`, `currency`, `value` |
| `meta_ads_conversions_send_lead` | Send a lead event | `account_id`, `pixel_id`, `event_time`, `user_data` |

#### Pixels

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_pixels_list` | List pixels | `account_id` |
| `meta_ads_pixels_get` | Get pixel details | `account_id`, `pixel_id` |
| `meta_ads_pixels_stats` | Get pixel firing statistics | `account_id`, `pixel_id` |
| `meta_ads_pixels_events` | List pixel events | `account_id`, `pixel_id` |

#### Analysis

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_analysis_performance` | Analyze overall performance trends | `account_id` |
| `meta_ads_analysis_audience` | Analyze audience performance and overlap | `account_id` |
| `meta_ads_analysis_placements` | Analyze placement performance breakdown | `account_id` |
| `meta_ads_analysis_cost` | Analyze cost trends and efficiency | `account_id` |
| `meta_ads_analysis_compare_ads` | Compare performance across ads | `account_id` |
| `meta_ads_analysis_suggest_creative` | Suggest creative improvements based on data | `account_id` |

#### Product Catalog (DPA)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_catalogs_list` | List product catalogs | `account_id`, `business_id` |
| `meta_ads_catalogs_create` | Create a product catalog | `account_id`, `business_id`, `name` |
| `meta_ads_catalogs_get` | Get catalog details | `account_id`, `catalog_id` |
| `meta_ads_catalogs_delete` | Delete a product catalog | `account_id`, `catalog_id` |
| `meta_ads_products_list` | List products in a catalog | `account_id`, `catalog_id` |
| `meta_ads_products_add` | Add a product to a catalog | `account_id`, `catalog_id`, `retailer_id`, `name`, `availability`, `condition`, `price`, `url`, `image_url` |
| `meta_ads_products_get` | Get product details | `account_id`, `product_id` |
| `meta_ads_products_update` | Update a product | `account_id`, `product_id` |
| `meta_ads_products_delete` | Delete a product | `account_id`, `product_id` |
| `meta_ads_feeds_list` | List feeds for a catalog | `account_id`, `catalog_id` |
| `meta_ads_feeds_create` | Create a feed (URL-based, scheduled import) | `account_id`, `catalog_id`, `name`, `feed_url` |

#### Lead Ads

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_lead_forms_list` | List lead forms (per page) | `account_id`, `page_id` |
| `meta_ads_lead_forms_get` | Get lead form details | `account_id`, `form_id` |
| `meta_ads_lead_forms_create` | Create a lead form | `account_id`, `page_id`, `name`, `questions`, `privacy_policy_url` |
| `meta_ads_leads_get` | Get lead data (per form) | `account_id`, `form_id` |
| `meta_ads_leads_get_by_ad` | Get lead data (per ad) | `account_id`, `ad_id` |

#### Videos

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_videos_upload` | Upload a video from URL | `account_id`, `video_url` |
| `meta_ads_videos_upload_file` | Upload a video from local file | `account_id`, `file_path` |

#### Creatives (Carousel & Collection)

*(See Creatives section above for carousel and collection tools.)*

#### Split Tests (A/B Testing)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_split_tests_list` | List split tests | `account_id` |
| `meta_ads_split_tests_get` | Get split test details and results | `account_id`, `study_id` |
| `meta_ads_split_tests_create` | Create a split test | `account_id`, `name`, `cells`, `objectives`, `start_time`, `end_time` |
| `meta_ads_split_tests_end` | End a split test | `account_id`, `study_id` |

#### Ad Rules (Automated Rules)

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_ad_rules_list` | List automated rules | `account_id` |
| `meta_ads_ad_rules_get` | Get rule details | `account_id`, `rule_id` |
| `meta_ads_ad_rules_create` | Create an automated rule (alerts, auto-pause, etc.) | `account_id`, `name`, `evaluation_spec`, `execution_spec` |
| `meta_ads_ad_rules_update` | Update an automated rule | `account_id`, `rule_id` |
| `meta_ads_ad_rules_delete` | Delete an automated rule | `account_id`, `rule_id` |

#### Page Posts

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_page_posts_list` | List Facebook page posts | `account_id`, `page_id` |
| `meta_ads_page_posts_boost` | Boost a page post (create ad from post) | `account_id`, `page_id`, `post_id`, `ad_set_id` |

#### Instagram

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_instagram_accounts` | List connected Instagram accounts | `account_id` |
| `meta_ads_instagram_media` | List Instagram posts | `account_id`, `ig_user_id` |
| `meta_ads_instagram_boost` | Boost an Instagram post (create ad from post) | `account_id`, `ig_user_id`, `media_id`, `ad_set_id` |

### Search Console

Search Console tools reuse the same Google OAuth2 credentials as Google Ads -- no additional authentication is required.

#### Sites

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_sites_list` | List verified sites | *(none)* |
| `search_console_sites_get` | Get site details | `site_url` |

#### Analytics

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_analytics_query` | Query search analytics data | `site_url` |
| `search_console_analytics_top_queries` | Get top search queries | `site_url` |
| `search_console_analytics_top_pages` | Get top pages by clicks/impressions | `site_url` |
| `search_console_analytics_device_breakdown` | Get performance breakdown by device | `site_url` |
| `search_console_analytics_compare_periods` | Compare search performance across time periods | `site_url` |

#### Sitemaps

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_sitemaps_list` | List sitemaps for a site | `site_url` |
| `search_console_sitemaps_submit` | Submit a sitemap | `site_url`, `sitemap_url` |

#### URL Inspection

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_url_inspection_inspect` | Inspect a URL for indexing status | `site_url`, `inspection_url` |

### Rollback

Cross-platform tools for inspecting and applying the reversal of a previously-recorded `action_log` entry. `rollback_apply` re-dispatches through the same MCP handler used for forward actions, so the reversal re-enters the full policy gate (auth, rate-limit, GAQL validation, planner allow-list).

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `rollback_plan_get` | Inspect the reversal plan for an `action_log` entry (`supported` / `partial` / `not_supported`), its `operation` + `params`, and any caveats. Read-only. | `index` |
| `rollback_apply` | Execute the reversal plan for `action_log[index]`. Requires `confirm=true` as a literal boolean. Appends a new log entry tagged `rollback_of=<index>`. | `index`, `confirm` |

Both tools accept an optional `state_file` argument (default `STATE.json`), which is resolved strictly inside the MCP server's current working directory. Path traversal, symlink escape, and `rollback.*` self-recursion are all refused. A second apply of the same index is refused (idempotency is enforced by scanning later log entries for a matching `rollback_of` marker). Downstream SDK exceptions are logged server-side only; the MCP response returns a generic message so tokens and account identifiers cannot leak into model context.

### Analysis

Cross-platform anomaly detection that operates on STATE.json's `action_log` history rather than a platform API directly.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `analysis_anomalies_check` | Compare a campaign's current metrics against a median-based baseline built from `action_log` history. Returns severity-ordered anomalies — zero spend (CRITICAL), CPA spike (HIGH/CRITICAL, gated by 30+ conversions), CTR drop (HIGH/CRITICAL, gated by 1000+ impressions). | `current` (`current.campaign_id` and `current.cost` required) |

`had_prior_spend` (default `true`) suppresses the zero-spend alert for fresh campaigns. `min_baseline_entries` (default `7`) controls how many history entries are required before a baseline is built; below this, `baseline` is `null` and only zero-spend is evaluated. Numeric fields accept int / float / numeric-string and reject `"N/A"` or booleans. `state_file` is sandboxed the same way as for the rollback tools. A parseable-but-corrupt `STATE.json` produces a `baseline_warning` in the response without silencing live zero-spend detection.

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

Operational skill definitions live under `skills/` (daily-check, budget-rebalance, etc.). See [strategy-context.md](strategy-context.md) for the strategy file format and Operation Mode reference.

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

The `keywords` parameter for `google_ads_keywords_add` and `google_ads_negative_keywords_add` is an array of objects:

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

The `google_ads_ads_create` tool accepts headlines and descriptions arrays:

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

### Display Campaign and RDA Creation

To create a display campaign, pass `channel_type: "DISPLAY"` to `google_ads_campaigns_create`:

```json
{
  "customer_id": "1234567890",
  "name": "Brand Display Campaign",
  "channel_type": "DISPLAY",
  "bidding_strategy": "MAXIMIZE_CONVERSIONS",
  "budget_id": "555666777"
}
```

Then create an RDA via `google_ads_ads_create_display`. Local image file paths are uploaded automatically before the ad is created:

```json
{
  "customer_id": "1234567890",
  "ad_group_id": "111222333",
  "headlines": ["Run Faster", "Train Smarter"],
  "long_headline": "The shoes that changed how athletes train",
  "descriptions": ["Cushioning tested by Olympic runners.", "Free 30-day returns."],
  "business_name": "Acme Athletics",
  "marketing_image_paths": ["/path/to/marketing-1200x628.jpg"],
  "square_marketing_image_paths": ["/path/to/square-1200x1200.jpg"],
  "logo_image_paths": ["/path/to/logo.png"],
  "final_url": "https://example.com/shoes"
}
```

Constraints (per the Google Ads API):
- Headlines: 1-5 items, each ≤30 display width
- Long headline: required, ≤90 display width
- Descriptions: 1-5 items, each ≤90 display width
- Business name: required, ≤25 display width
- Marketing images (1.91:1): 1-15 files, 3+ recommended for delivery quality
- Square marketing images (1:1): 1-15 files, 3+ recommended
- Logo images: optional, up to 5
- The target ad group must belong to a DISPLAY campaign (mureo verifies this before any upload)

If image upload fails partway through or the ad creation fails after all uploads succeed, an `RDAUploadError` is raised that includes the resource names of any orphaned uploaded assets so they can be cleaned up.

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
