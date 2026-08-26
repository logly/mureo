# MCP Server Guide

mureo exposes 225 tools via the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP): 192 advertising and SEO operation tools across Google Ads (92), Meta Ads (90), and Search Console (10), 2 rollback tools, 3 batch tools (group a bulk change into one revertible unit), 1 change-import tool (record changes made outside mureo), 5 cross-platform analysis tools (anomaly detection, delivery-collapse detection and diagnosis, the exclusion delivery-impact preview and tracking-parameter consistency), 12 mureo-context tools (strategy / state / reports / per-day history / collection failures — per platform and for the workspace as a whole — / outcome evaluation), 2 analytics-registry tools, 2 learning tools (`mureo_learning_insights_get` for the operator's local `/learn` history and `mureo_consult_advisor` for federated retrieval against external advisor MCP servers — see [`docs/insight-federation.md`](insight-federation.md)), 1 learning-period pre-flight tool (`mureo_learning_reset_preflight` — is a pending change reset-triggering, and is the campaign already learning; see [Learning-period reset pre-flight](#learning-period-reset-pre-flight)), and 5 Creative Studio tools (text-free key-visual generation + banner composition). Any MCP-compatible client can connect and call these tools over stdio. Re-check this count when MCP tools are added or removed (`test_list_tools_returns_all_tools` pins the exact number). The count covers mureo's own tool families only — tools bridged from the official **Amazon Ads** MCP (and from any installed provider plugin) are appended on top at server start and vary per operator; see [Amazon Ads (official-MCP bridge)](#amazon-ads-official-mcp-bridge) below.

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

### OpenAI Codex

Codex reads MCP servers from `~/.codex/config.toml` (**TOML**, not JSON) — shared
across the Codex CLI, IDE extension, and desktop app. The easiest path is
`mureo setup codex` (or `mureo configure` → pick the **OpenAI Codex** host),
which writes a tagged `[mcp_servers.mureo]` block and preserves the rest of the
file. To wire it by hand:

```toml
[mcp_servers.mureo]
command = "python"
args = ["-m", "mureo.mcp"]
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

#### Negative Placements (delivery-surface exclusions)

Excluded websites, mobile apps and mobile app categories — the placement side of exclusion, as opposed to the search-term side above.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_negative_placements_list` | List excluded websites / apps / app categories at campaign and ad group level | `customer_id` |
| `google_ads_negative_placements_add` | Exclude websites / apps / app categories (batch, one revertible unit) | `customer_id`, one of `campaign_id` / `ad_group_id`, `placements` |
| `google_ads_negative_placements_remove` | Lift exclusions by `criterion_id` (batch) | `customer_id`, one of `campaign_id` / `ad_group_id`, `criterion_ids` |

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
| `google_ads_demographic_targeting_list` | List explicit demographic criteria (age range, gender, parental status, household income) set on ad groups | `customer_id` |
| `google_ads_audience_targeting_list` | List audience-type criteria (user interests, remarketing / customer-match lists, custom / combined audiences) attached to ad groups | `customer_id` |

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
| `google_ads_auction_insights_analyze` | Interpret impression-share metrics into human-readable competitive-position insights | `customer_id`, `campaign_id` |
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
| `google_ads_image_assets_list` | List existing image assets with their names and dimensions (width/height, file size, serving URL) | `customer_id` |

#### Performance Max asset groups

`google_ads_ads_list` returns no rows for a Performance Max campaign: P-MAX
has no `ad_group_ad`. Its headlines, long headlines and descriptions — and
its images and logos — are assets linked to an **asset group** through
`asset_group_asset`. These three tools are the P-MAX creative surface.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `google_ads_asset_group_assets_list` | List the text AND image assets linked to Performance Max asset groups, with the `asset_id` and the `asset_group_asset` handle for each. Optionally filtered by `asset_group_id` or `campaign_id` | `customer_id` |
| `google_ads_asset_group_assets_replace` | Swap one headline, long headline or description of an asset group for new text | `customer_id`, `asset_group_id`, `field_type`, `old_asset_id`, `new_text` |
| `google_ads_asset_group_images_replace` | Swap one image or logo of an asset group, from an existing asset id or a local file | `customer_id`, `asset_group_id`, `field_type`, `old_asset_id`, and one of `new_asset_id` / `new_image_path` |

**One read, two row shapes.** `google_ads_asset_group_assets_list` issues one
query covering both halves, because the question is "show me this asset
group's creative", not "show me its text". Every entry carries
`resource_name`, `field_type`, `status`, `asset_id`, `asset_group_id`,
`asset_group_name`, `campaign_id` and `campaign_resource_name`; `field_type`
says what the rest holds. A text link (`HEADLINE`, `LONG_HEADLINE`,
`DESCRIPTION`) adds `text`. An image link (`MARKETING_IMAGE`,
`SQUARE_MARKETING_IMAGE`, `PORTRAIT_MARKETING_IMAGE`, `LOGO`,
`LANDSCAPE_LOGO`) adds `asset_name`, `url` (the full-size serving URL),
`width_pixels` and `height_pixels`. This is also the only Google read that
says *which* asset group serves a given image: `google_ads_image_assets_list`
is account-wide and does not.

**The text swap.** A Google Ads text `Asset` is immutable, so the swap is not
an update: it creates a new `Asset`, links it under the same `field_type`,
and removes the old link. All three go in **one** atomic
`GoogleAdsService.mutate`, so the asset group's asset count for that field
type never dips below the Performance Max minimum — a removal issued on its
own can be refused with `AssetGroupError.NOT_ENOUGH_HEADLINE_ASSET` (or the
long-headline / description twin), which the tool reports as an actionable
message rather than a raw API error. The old `Asset` itself is not deleted;
only its link to that asset group is.

**The image swap.** Nothing has to be created inside the mutate — an image
asset exists before an asset group can point at it — so the request is two
operations, link then unlink, again as one atomic mutate against the same
`NOT_ENOUGH_MARKETING_IMAGE_ASSET` / `NOT_ENOUGH_SQUARE_MARKETING_IMAGE_ASSET`
/ `NOT_ENOUGH_LOGO_ASSET` floors. Pass `new_asset_id` for an image the
account already holds, or `new_image_path` for a local file — exactly one of
the two; the tool uploads the file itself, so an operator never has to work
out which situation they are in. Google enforces a shape per slot
(`MARKETING_IMAGE` 1.91:1 min 600x314, `SQUARE_MARKETING_IMAGE` 1:1 min
300x300, `PORTRAIT_MARKETING_IMAGE` 4:5 min 480x600, `LOGO` 1:1 min 128x128,
`LANDSCAPE_LOGO` 4:1 min 512x128) and mureo checks it **before** uploading or
linking anything, so a wrongly proportioned file costs no API call and leaves
no unlinked asset behind. For a format it cannot measure locally (GIF, or an
unrecognised header) it does not guess: the file goes to Google and an
`ImageError` refusal comes back translated into the rule for that slot.
mureo never crops or resizes.

Neither swap is automatically reversible: to undo one, call the tool again
with the old text or the old `asset_id`.

**Text and images only.** Video, business name, and every other field type of
an asset group are neither returned by `google_ads_asset_group_assets_list`
nor replaceable. A video asset references a YouTube video id rather than
uploaded bytes, so it is a different entry shape and a different operator
workflow. `/creative-refresh` treats every surface with no write tool as
draft-only and says so before drafting rather than after the operator agrees;
see its *Apply or draft* section.

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
| `meta_ads_creatives_create` | Create a standard ad creative (single image **or video**) | `account_id`, `name` |
| `meta_ads_creatives_create_carousel` | Create a carousel creative (2-10 cards) | `account_id`, `page_id`, `cards`, `link` |
| `meta_ads_creatives_create_collection` | Create a collection creative | `account_id`, `page_id`, `product_ids`, `link` |
| `meta_ads_creatives_create_dynamic` | Create a dynamic product ad creative | `account_id`, `catalog_id` |
| `meta_ads_creatives_create_lead` | Create a Lead Ad creative attached to an Instant Form | `account_id`, `name`, `page_id`, `form_id`, `link_url` |
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

#### Targeting Discovery

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_targeting_search` | Resolve interest names to internal targeting IDs (with audience-size bounds and path) | `query` |
| `meta_ads_targeting_categories` | List a full targeting category catalogue (behaviors / demographics / etc.) with internal IDs | `category_class` |

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
| `meta_ads_pixels_create` | Create a pixel | `account_id`, `name` |

#### Analysis

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_analysis_performance` | Analyze overall performance trends | `account_id` |
| `meta_ads_analysis_audience` | Analyze audience performance and overlap | `account_id` |
| `meta_ads_analysis_placements` | Analyze placement performance breakdown | `account_id` |
| `meta_ads_analysis_cost` | Analyze cost trends and efficiency | `account_id` |
| `meta_ads_analysis_compare_ads` | Compare performance across ads | `account_id` |
| `meta_ads_analysis_suggest_creative` | Suggest creative improvements based on data | `account_id` |

#### Placement Exclusions

Which publishers, Audience Network app categories and content types an ad set must NOT be delivered against. Stored inside the ad set's targeting spec; named as their own tools so mureo can record and reverse an exclusion change.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_excluded_placements_get` | Read an ad set's current exclusion lists | `account_id`, `ad_set_id` |
| `meta_ads_excluded_placements_set` | Replace the supplied exclusion facets on an ad set | `account_id`, `ad_set_id` |

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
| `meta_ads_lead_forms_create` | Create a lead form | `account_id`, `page_id`, `name`, `questions`, `privacy_policy_url`, `follow_up_action_url` |
| `meta_ads_lead_forms_update` | Update lead form status (ACTIVE / ARCHIVED) | `account_id`, `form_id`, `status` |
| `meta_ads_lead_forms_duplicate` | Duplicate a lead form under a Page with a new name | `account_id`, `form_id`, `page_id`, `new_name` |
| `meta_ads_leads_export_csv` | Export form leads to a local CSV file | `account_id`, `form_id`, `output_path` |
| `meta_ads_leads_get` | Get lead data (per form) | `account_id`, `form_id` |
| `meta_ads_leads_get_by_ad` | Get lead data (per ad) | `account_id`, `ad_id` |
| `meta_ads_pages_list_photos` | List photos the Page already uploaded; pick one `id` for an Instant Form intro `context_card.cover_photo_id` | `account_id`, `page_id` |

#### Pages

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_pages_list` | List manageable Facebook Pages (personal + business-owned) | `account_id` |

#### Videos

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `meta_ads_videos_upload` | Upload a video from URL | `account_id`, `video_url` |
| `meta_ads_videos_upload_file` | Upload a video from local file | `account_id`, `file_path` |
| `meta_ads_videos_get` | Get video processing status / metadata (poll before creating a creative) | `account_id`, `video_id` |
| `meta_ads_videos_thumbnails` | List auto-generated video thumbnails | `account_id`, `video_id` |

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

> **`site_url`** is an optional parameter on every tool below, not a schema-required one. It is resolved (and tenant-scoped) at runtime: in standalone use you pass it explicitly; under a multi-account backend it is bound to the active client's configured property (and a single-property client may omit it). The "Required Parameters" column lists only the schema-required fields.

#### Sites

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_sites_list` | List verified sites | *(none)* |
| `search_console_sites_get` | Get site details | *(none; `site_url` optional)* |

#### Analytics

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_analytics_query` | Query search analytics data | `start_date`, `end_date` |
| `search_console_analytics_top_queries` | Get top search queries | `start_date`, `end_date` |
| `search_console_analytics_top_pages` | Get top pages by clicks/impressions | `start_date`, `end_date` |
| `search_console_analytics_device_breakdown` | Get performance breakdown by device | `start_date`, `end_date` |
| `search_console_analytics_compare_periods` | Compare search performance across time periods | `start_date_1`, `end_date_1`, `start_date_2`, `end_date_2` |

#### Sitemaps

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_sitemaps_list` | List sitemaps for a site | *(none; `site_url` optional)* |
| `search_console_sitemaps_submit` | Submit a sitemap | `feedpath` |

#### URL Inspection

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `search_console_url_inspection_inspect` | Inspect a URL for indexing status | `inspection_url` |

### Rollback

Cross-platform tools for inspecting and applying the reversal of a previously-recorded `action_log` entry. `rollback_apply` re-dispatches through the same MCP handler used for forward actions, so the reversal re-enters the full policy gate (auth, rate-limit, GAQL validation, planner allow-list).

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `rollback_plan_get` | Inspect the reversal plan for one `action_log` entry (`supported` / `partial` / `not_supported`), its `operation` + `params`, and any caveats — or, with `batch_id` instead, for a whole batch (see below). Read-only. | exactly one of `index` / `batch_id` |
| `rollback_apply` | Execute the reversal plan for `action_log[index]`. Requires `confirm=true` as a literal boolean. Appends a new log entry tagged `rollback_of=<index>`. | `index`, `confirm` |

Both tools accept an optional `state_file` argument (default `STATE.json`), which is resolved strictly inside the MCP server's current working directory. Path traversal, symlink escape, and `rollback.*` self-recursion are all refused. A second apply of the same index is refused (idempotency is enforced by scanning later log entries for a matching `rollback_of` marker). Downstream SDK exceptions are logged server-side only; the MCP response returns a generic message so tokens and account identifiers cannot leak into model context.

#### Planning a whole batch (#549)

`rollback_plan_get` with `batch_id` returns one plan covering **every** member of that batch (see [Batch](#batch) below for how membership is declared), so a bulk pass is reviewed as one unit instead of entry by entry:

| Field | Meaning |
|-------|---------|
| `coverage` | `full` / `partial` / `none` / `empty` — how much of the batch a reversal would actually restore |
| `platform_coverage` | The same verdict **per platform key**, because reversibility is not uniform across platforms |
| `counts` | Members per verdict (`reversible`, `reversible_with_caveats`, `irreversible`, `nothing_to_reverse`, `already_reversed`, `total`) |
| `apply_order` | The reversible members' `action_log` indices, newest first — the order to feed `rollback_apply` |
| `members[]` | Every member with its `index`, `platform`, `reversibility` verdict, the `reason` when it cannot be reversed, and its `operation` / `params` / `caveats` when it can |

The point of the response is the part that is **not** reversible. A batch where 60 of 80 members can be restored reports `coverage: "partial"` with the other 20 listed and explained, before anything is applied — a revert whose completeness the operator cannot verify leaves them unable to rule their own fix out as a variable.

`rollback_plan_get` is read-only and `rollback_apply` still takes one `index` at a time, so applying a batch reversal is a loop over `apply_order` — each call re-entering the same policy gate as a forward action. There is deliberately no "apply the whole batch" call: a single result code for 80 dispatches would have to summarize partial failure, which is the reporting problem this feature exists to remove.

### Batch

Declare the boundary of a bulk change so it becomes one reviewable, plannable unit in `action_log`. A bulk pass is many tool calls and nothing in a single call says which others belong with it, so the boundary is declared rather than guessed.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_batch_begin` | Open a batch. Every `action_log` entry recorded until it is closed is tagged with the returned `batch_id`. Refused if one is already open. | `label` |
| `mureo_batch_end` | Close the open batch and return its exact membership (`member_indices`, `member_count`, `platforms`). Closing is **final**. Refused if none is open. | *(none)* |
| `mureo_batch_status` | Report which batch is collecting (or `null`), how many members it holds, which platforms they span, and a `warning` when it has been open too long. Read-only. | *(none)* |

**Membership cannot be forged or grown after the fact.** `mureo_state_action_log_append` accepts an optional `batch_id`, but it is validated, not trusted: it must name a batch that was actually declared and is still open. An unknown id is refused (an id naming no batch is a typo or a fabrication, not a change set), and a **closed** batch is refused too — `mureo_batch_end` reports a `member_count` the operator keeps, and a membership that can still grow afterwards makes that number silently false. To group imported or backfilled history, open a batch for the import rather than reattaching to an old one.

**A forgotten `mureo_batch_end` announces itself.** A missed `begin` yields no batch, which is obvious and harmless; a missed `end` yields a batch that keeps swallowing unrelated changes for days and then reports them, confidently, as one unit. After 24 hours open, `mureo_batch_status` returns a `warning`, and one is appended to the result of every mutating tool call so the agent that forgot is told without having to ask. mureo never closes a batch for you — an automatic timeout would trade a visible wrong answer for an invisible one. Suppress the appended reminder with `MUREO_DISABLE_BATCH_REMINDER=1`.

Membership is stamped where every recording path already converges (`append_action_log`), not through tool arguments — which is what makes it work for platforms whose tool schemas mureo does not own. What that means per platform:

| Platform kind | Joins a batch | Reversal of a member |
|---------------|---------------|----------------------|
| Native Google Ads / Meta Ads | Yes. Status toggles are recorded automatically; **every other mutation** (budget, keywords, placement exclusions, …) joins only if the agent records it with `mureo_state_action_log_append` | Executed, for the allow-listed operations |
| Bridged / plugin (`plugin:<dist>:<provider>`, e.g. Amazon Ads) | Yes — successful mutations are promoted to `action_log` automatically | Recorded for visibility; executed only when the reversal names a *registered* plugin tool. Otherwise the member is reported `irreversible` with the reason |
| Hosted connectors (`tiktok_ads`) | Yes, for entries recorded with `mureo_state_action_log_append` — mureo is not in the data path, so nothing is automatic | Not executed by design. Members are reported `irreversible`, so the batch plan is an accurate manual checklist |
| Search Console | **No.** Its mutations (`sitemaps_submit`) are not recorded in `action_log` at all, so there is nothing to group | n/a |

Batch state lives in STATE.json (`batches`), not in process memory, so a host that restarts the MCP server mid-pass does not silently stop collecting members. Records are kept after close (with `ended_at`) so a `batch_id` still resolves to the operator's own label weeks later.

### Change import

Record changes made **outside** mureo — in a platform's own UI, its editor, or another tool — so mureo's guarantees survive manual operation. Without this, mureo cannot tell "nothing happened" from "something happened that I cannot see".

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_external_changes_import` | Poll each configured platform's change feed and append anything mureo did not do to `action_log` with `origin: "external"`. Skips changes already imported and changes mureo itself made. Idempotent. | *(none)* |

Optional: `platforms` (array of platform keys; omit to cover every platform in STATE.json), `since` (ISO 8601 window start; omit to resume from the newest change already imported), `path`.

**The response is designed to be read for blind spots, not just for finds.** Every configured platform appears in `platforms[]`:

| `status` | Meaning |
|---|---|
| `imported` | The feed ran. An empty `imported_indices` here is a real "nothing changed in this window" |
| `unavailable` | The platform was **not checked**: either mureo has no change feed for it, or a registered feed could not answer for this account/mode (BYOD, unsupported account type). `reason: "change_import_unavailable_for_<platform>"`; the specific cause is in `notes`. Not evidence that nothing happened |
| `error` | The feed exists but could not be read (expired token, missing credentials). Also unchecked, also not evidence of quiet |

`blind_spots` collects the `unavailable` and `error` platforms; `truncated_platforms` collects those whose feed capped its response, meaning older changes inside that window are unreachable and **cannot be recovered later**. `feeds_available_for` lists the platforms that have a registered feed at all.

Per-platform coverage — which feeds exist, which mureo reads today, and what each omits — is in [`docs/change-import.md`](change-import.md). Do not infer it from tool availability.

An imported entry is permanently distinguishable from one mureo performed. It carries `origin: "external"`, the platform's `occurred_at`, and an `observation_due` anchored on that (so an older change lands already past due), and **no** `metrics_at_action`. `rollback_plan_get` returns `not_supported` for every external entry — mureo never saw the prior value, so a "reversal" would be a fresh change dressed as a restoration.

For a hosted connector mureo cannot poll (`tiktok_ads`), a skill that reads the connector's own change tools records what it finds through `mureo_state_action_log_append` with `origin: "external"` plus `external_id` and `occurred_at`.

Bridges and plugins participate by shipping an entry point in the `mureo.change_feeds` group implementing `ChangeFeedProvider` — a **new** Protocol in a **new** group, so no published plugin is affected. See [`docs/ABI-stability.md` §4b](ABI-stability.md#4b-changefeedprovider-protocol-issue-545).

### Analysis

Cross-platform analysis that operates on data the caller supplies — an `action_log` history, ad records, a delivery report — rather than on a platform API the tool picks for itself. `analysis_anomalies_check`, both delivery-collapse tools and `analysis_tracking_consistency_check` reach no platform API at all, so they behave identically for native, plugin, bridged and hosted-connector platforms; `analysis_exclusion_impact_preview` issues one read of the account's own report unless the caller supplies `delivery_records`.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `analysis_anomalies_check` | Compare a campaign's current metrics against a median-based baseline built from `action_log` history. Returns severity-ordered anomalies — zero spend (CRITICAL), CPA spike (HIGH/CRITICAL, gated by 30+ conversions), CTR drop (HIGH/CRITICAL, gated by 1000+ impressions). | `current` (`current.campaign_id` and `current.cost` required) |
| `analysis_delivery_collapse_check` | Flag campaigns whose impressions fell off a cliff while their status still says they should be serving. Baseline comes from the supplied day-grain rows, **not** from `action_log`. | `platform`, `rows` |
| `analysis_delivery_collapse_diagnose` | Overlay a change feed on one campaign's daily delivery, fold in elimination-ladder evidence, and report the cause **and** the open questions. `change_lookback_days` (default 3) and `timeline_days` (default 21) are settable — widen the lookback for a cause with a delayed effect. | `platform`, `campaign_id`, `rows` |

#### Delivery collapse (#546)

`google_ads_cost_increase_investigate` answers "why did spend jump?". These two answer its inverse — a campaign that is still ENABLED while its impressions have gone to zero, which is the most detectable failure mode in ad operations and the one mureo previously had no scheduled detector for.

**Why not `analysis_anomalies_check`.** That tool must be hand-fed one campaign's current metrics and baselines them off `action_log`, which is thin or empty on accounts operated partly by hand. `analysis_delivery_collapse_check` takes a whole day-grain report and derives its baseline from those rows (`baseline_source: "platform_daily_delivery"`), so it works with an empty action log.

**Row shape** — one row per campaign per day, ~30+ days:

```json
{"campaign_id": "123", "campaign_name": "Display / Prospecting", "status": "ENABLED",
 "end_date": "2026-12-31", "date": "2026-05-31", "impressions": 0, "clicks": 0, "cost": 0}
```

**What it will not fire on.** The false-positive suppression is the reason the detector is usable unattended:

- **Weekend / weekday seasonality** — the baseline is the median of the **same weekday** in the trailing window (`same_weekday_median`, falling back to `all_day_median` when a weekday has too few samples). A 96% Saturday dip on a weekday-heavy account is normal and is not reported.
- **Intraday budget pacing** — the current day is always partial, so days at or after `as_of` (the server's today, overridable for tests) are never evaluated.
- **Intentional pauses** — a campaign whose status is not a serving status is skipped. The *status says serving, nothing is serving* contradiction is the entire signal.
- **Finished flights** — a campaign past its `end_date` is expected to stop.
- **Low-volume campaigns** — a baseline under `delivery_collapse_min_baseline_impressions` (default 1000/day) hits zero routinely.
- **New campaigns** — fewer than `delivery_collapse_min_baseline_days` (default 14) days *with real delivery* in the window yields no signal. It counts delivering days, not window length, so a campaign cannot reach the bar on days it was already down.

It reports `reported_through` (the latest date the platform reported anything) and `unreported_days` alongside `signals`. **An empty `signals` list is only an all-clear when `unreported_days` is 0** — see *What detection cannot see* below.

Two things it deliberately does **not** depend on:

- **How long the outage has been running.** Detection is asserted across the whole duration range (1 day to 180+), because a detector that silently stops firing on the *longest* outages is worst exactly where it matters most.
- **Whether a platform emits zero-delivery rows.** Google Ads and Meta both omit a `(campaign, date)` row when nothing served, which is the very symptom being looked for. Missing days are reconciled to explicit zeros — but only where the report **proves** the platform covered them. A platform that already returns zeros produces no gaps, so the reconciliation is a no-op for it.

  The proof matters, and it is the difference between a working detector and one that gets muted. A gap **bracketed by later rows** (the campaign's own, or any other campaign in the account) is certain: the platform reported past it, so nothing served. A gap **beyond the last date anything was reported** is not — that is a dead campaign *or* a platform that has not caught up, and mureo cannot tell which, so those days are left out of the evaluation entirely. Filling to the *requested* range end instead turned a one-day reporting lag into a CRITICAL "100% below baseline" on every healthy campaign, at any hour of the day, and no `delivery_collapse_consecutive_days` setting closed it — a two-day lag simply produced `days_at_collapse=2`.

  **One precondition on `rows`.** Using the whole report as the bracket assumes **every campaign in a single call was fetched together and finalises at the same time**. mureo's own Google and Meta clients issue one account-wide query per call, so they satisfy it by construction. An agent assembling rows itself may not: rows stitched from several fetches, or a connector whose campaigns finalise at different times, make the *fastest* campaign's latest date the evidence, and a slower but perfectly healthy campaign gets zero-filled up to it and reported as collapsed. Two rules follow:

  - Pass **all** campaigns from **one** fetch in a single call. Do not mix rows retrieved at different times.
  - When you cannot guarantee that, set `reported_through` to the **oldest** per-campaign last date you trust. It costs a day or two of recency and never hides a real collapse. Do *not* pass the end of the range you requested — that asserts coverage the platform never confirmed, which is the bug above.

#### What detection cannot see

Two blind spots follow from that rule, both listed in the diagnosis `limitations` as well:

- **A campaign with no rows anywhere in the window is invisible.** With no first row there is no series to reconcile, and inventing one would fabricate the baseline. Widen the window, or check the platform UI.
- **When every campaign stops reporting on the same day, no signal fires.** Nothing proves those days were covered, and a total account outage is indistinguishable from a platform-side reporting failure. This one is *reported* rather than hidden: `unreported_days` climbs, and a value that keeps growing across runs is a finding in its own right — treat it as Action needed and check the account directly.

**Thresholds live in STRATEGY.md `## Guardrails`** (all optional; a malformed or out-of-range value drops that one rule and keeps the default):

```markdown
## Guardrails
- delivery_collapse_drop_pct: 90                    # % below baseline that counts as a collapse
- delivery_collapse_consecutive_days: 1             # complete days required before alerting
- delivery_collapse_min_baseline_impressions: 1000  # ignore campaigns below this daily volume
- delivery_collapse_baseline_days: 28               # trailing window the median is taken from
- delivery_collapse_min_baseline_days: 14           # minimum history before the detector speaks
- delivery_collapse_min_same_weekday_samples: 2     # below this, fall back to the all-day median
```

**What the diagnosis cannot answer.** `analysis_delivery_collapse_diagnose` returns `most_likely_cause: null` and `confidence: "undetermined"` unless supplied evidence actually implicates a step — seven passing checks is an honest "undetermined", not a diagnosis. Every response carries `unresolved` (steps nobody could check, and a note when there is no change in the pre-cliff window) and a standing `limitations` list:

- Serving-side suppression — the platform choosing not to enter a campaign into auctions — is not exposed by any read API mureo has, on any platform.
- No supported platform exposes billing state through an API mureo integrates.
- Learning-phase internals (Google bid-strategy learning, Meta ad-set learning) are not readable; a learning reset is inferred from a change event, never observed.
- Change feeds reaching mureo are incomplete: Google Ads change history omits system-initiated changes and retains ~30 days; **Meta publishes an account activity log but mureo does not fetch it yet**, so Meta changes reach the timeline only via `action_log`; and manual work reaches `action_log` only if it was imported. No change in the window is weak evidence, not exoneration — and on Meta the gap is mureo's, not the platform's.
- Several campaigns collapsing on the same day is reported as a correlation only.

`next_checks` names the mureo tool for each open step on platforms that have one, and an empty string where mureo has no tool at all (billing everywhere; bid competitiveness and learning state on Meta) rather than inventing one.
| `analysis_exclusion_impact_preview` | Size a bulk exclusion / block / negative-keyword batch before applying it: what share of the recent window's impressions, clicks, cost and conversions the excluded entities carried, incrementally and cumulatively. Returns `would_block` from the same rule the dispatcher enforces. | either `tool` (+ `arguments`) or `excluded_entities` |
| `analysis_tracking_consistency_check` | Audit final-URL tracking parameters across ad records from any platform. Returns findings with `severity`, `delivery_state` (`served` / `not_served` / `unknown`), the ad ids and the evidence — a utm scheme belonging to exactly one other campaign, one landing page under two schemes, a parameter the rest of the campaign carries, and violations of a `## Tracking Convention` declared in STRATEGY.md. Pass `planned_ads` to pre-flight ads before creating them. | `ads` |

#### `analysis_exclusion_impact_preview` (#547)

Applying an exclusion batch without knowing its size is how a Display campaign
goes to zero impressions. This tool answers "how much of *my current delivery*
does this remove", from the account's own recent performance — never a platform
reach estimator.

Two calling conventions:

- **`tool` + `arguments`** — the exact call you are about to make. mureo reads
  the excluded entities out of the arguments and fetches the matching report
  for that scope.
- **`excluded_entities` + `delivery_records`** — you supply both sides. This
  form **reaches no platform API**, so a platform mureo does not model is still
  auditable whenever you can pull its own report.

`window_days` defaults to STRATEGY.md's `exclusion_impact_window_days` (else
30). `standing_exclusions` is optional; omit it (rather than passing `[]`) when
the standing set is unknown — an empty list means "there are none", and the
cumulative figure is withheld rather than understated when it is unknown.

Coverage is `measured`, `partial` (some entity kinds are structurally
unattributable on that basis) or `unknown`. `unknown` never means "no impact",
and `incremental` is `null` rather than a row of zeroes. A window that served
nothing reports `share_pct: null`, not `0`.

Per-surface attribution:

| Surface | Delivery source | Attributable |
|---|---|---|
| `google_ads_negative_placements_add` | `group_placement_view` over the window | Yes for `website` / `mobile_application`; `mobile_app_category` is not a placement that serves, so a mixed batch reports `partial` |
| `google_ads_negative_keywords_add` / `_add_to_ad_group` | `search_term_view` over the window, matched per `EXACT` / `PHRASE` / `BROAD` | Yes. Negative keywords do not match close variants and neither does the estimate, so it is a lower bound |
| `meta_ads_excluded_placements_set` | — | **No.** No insights breakdown attributes past delivery to publisher categories, publisher block lists or brand-safety content types. Reported `unknown` |
| Plugin / bridged surfaces (Yahoo, LINE, SmartNews, LOGLY, Amazon) | Whatever the provider registers via `register_exclusion_surface`, else caller-supplied `delivery_records` | Provider-declared |

**Cumulative tightening.** `cumulative` is the share attributable to the whole
standing exclusion set once this batch lands, which is what catches a fortnight
of individually-small passes: an entity excluded a week ago still carries its
pre-exclusion impressions inside a 30-day window. Its limit is the window — an
exclusion older than the window contributed nothing to it and is invisible — so
the cumulative figure is a lower bound. It is withheld (`null` with a reason)
for an ad-group-level Google placement write, because campaign-level exclusions
also cover that ad group and are not reachable from the call's arguments, and
for `google_ads_negative_keywords_add_to_ad_group`, because Google Ads exposes
no ad-group-level negative keyword listing.

**An inert rule says so.** Because the cumulative figure is withheld on those
scopes, `max_cumulative_delivery_share_removed_pct` enforces **nothing** there
— and that is the scope the motivating incident happened at. Pair it with
`max_delivery_share_removed_pct`, which is per-batch and needs no standing
list. When a rule the operator wrote could not be evaluated for a call, mureo
names it rather than letting it pass silently: `unevaluated_rules` in this
tool's response, and a `NOT ENFORCED on this call:` line (with the backstop to
add) in the notice appended to the exclusion's own result.

**Enforcement.** The three `STRATEGY.md` `## Guardrails` keys
`max_delivery_share_removed_pct`,
`max_cumulative_delivery_share_removed_pct` and
`block_exclusions_without_impact_data` are enforced in the dispatcher before an
exclusion tool runs. They are *not* in `StrategyPolicyGate`: the check needs one
awaited platform read and the `PolicyGate` v1 ABI is synchronous by design and
must stay pure and fast. With none of them written the check does no I/O at all
and behaviour is unchanged. `MUREO_DISABLE_EXCLUSION_PREFLIGHT=1` turns it off
entirely.

`had_prior_spend` (default `true`) suppresses the zero-spend alert for fresh campaigns. `min_baseline_entries` (default `7`) controls how many history entries are required before a baseline is built; below this, `baseline` is `null` and only zero-spend is evaluated. Numeric fields accept int / float / numeric-string and reject `"N/A"` or booleans. `state_file` is sandboxed the same way as for the rollback tools. A parseable-but-corrupt `STATE.json` produces a `baseline_warning` in the response without silencing live zero-spend detection.

`analysis_tracking_consistency_check` takes ad records (`ad_id`, `campaign_id`, `final_urls`, `platform`, optional `campaign_name` / `status` / `impressions`) that the caller assembles from `google_ads_ads_list`, `meta_ads_ads_list`, a plugin's own list tool or a bridged MCP — so a platform mureo cannot fetch ads for is still auditable whenever the agent can list them. Ads are only compared with ads carrying the same `platform` value. `impressions` grades the finding: `>0` makes it a data-integrity incident (`critical`), `0` a cheap fix (`high`), and omitting it leaves `delivery_state: unknown` with a note saying the severity may be understated — omitted is not `0`. Ads whose URL could not be read are listed in `ads_without_readable_url` rather than reported clean. See [docs/tracking-consistency.md](tracking-consistency.md) for the full list of what is and is not detectable.

### Mureo Context

Read and write the strategy context files (`STRATEGY.md`, `STATE.json`) directly through the MCP server. These tools exist for hosts that have no direct filesystem access (Claude Desktop chat, web, remote MCP); every write is atomic and validated before it replaces the file.

Both read tools carry a **`server_now`** field — the server's clock as ISO 8601 with a UTC offset (e.g. `2026-07-28T10:12:33+09:00`). It is the authoritative current date for an agent that cannot run `date` (headless / Bash-less hosts): every other date in the document is history. `server_now` is a response field only and is never persisted — the parser ignores unknown top-level keys, so a copy echoed back into `STATE.json` is dropped by the next mureo write.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_strategy_get` | Read STRATEGY.md — raw markdown plus an `exists` flag (empty markdown when absent) and `server_now` | *(none)* |
| `mureo_strategy_set` | Atomically replace STRATEGY.md (parsed for well-formedness before writing) | `markdown` |
| `mureo_state_get` | Read STATE.json as a parsed v2 document (version, platforms, campaigns, action_log) plus `server_now` | *(none)* |
| `mureo_state_action_log_append` | Atomically append a single action_log entry for later evaluation (`timestamp` is stamped server-side) | `entry` |
| `mureo_state_upsert_campaign` | Upsert a CampaignSnapshot (with optional performance `metrics`) into STATE.json | `campaign` |
| `mureo_state_report_set` | Persist a structured report summary for the read-only dashboard. `report` names the kind, one per skill that writes one — `daily`, `weekly`, `monthly`, `goal`, `audience`, `experiment`, `fatigue`, `pacing`, `tracking`. The structure is enforced: headline figures belong in `totals` as raw numbers (a canonical metric carrying a string is refused — it renders as nothing), each finding is its own `flags` entry, and `narrative` is capped at 400 characters, a longer one being refused rather than truncated. Reports already on disk are untouched — the bound applies to new writes | `report`, `summary` |
| `mureo_state_platform_metrics_set` | Set a platform-level metric rollup (feeds the YESTERDAY / LAST_7_DAYS / LAST_30_DAYS dashboard toggle). The window vocabulary is closed — those three tokens only, as `metrics_period` and as `periods` keys; any other window is refused rather than stored, and never rounded onto a neighbouring one | `platform`, `account_id` |
| `mureo_state_platform_daily_set` | Add **day-grain** history to a platform, keyed by calendar date (`YYYY-MM-DD`) — the trend line and day-over-day delta the window rollups cannot hold, since each of those keeps one value and every collection overwrites it. Merged per date key, so a day already stored survives the next write. Only complete PAST days are accepted (today is still being spent into), a day you did not collect is omitted rather than written as zeros, and the most recent 35 days are kept | `platform`, `account_id`, `days` |
| `mureo_state_platform_not_collected_set` | Record **why** a platform could not be collected — or clear that note once it can. Omit `reason` to clear, and do so on the next successful collection: nothing else retires it. The stored figures are never touched (they were not updated, not proven wrong), and `last_synced_at` is not re-stamped | `platform`, `account_id` |
| `mureo_state_workspace_not_collected_set` | Record **why the whole workspace** could not be collected — the run that died before any platform was reached — or clear that note once one succeeds. Takes **no** `platform` and **no** `account_id`: those are exactly what such a failure could not resolve. Nothing else in the document is touched, including any per-platform note, and `last_synced_at` is not re-stamped | *(none)* |
| `mureo_state_set_conversion_events` | Declare which Meta Insights `action_type` rows count as this account's conversions | `platform`, `account_id` |
| `mureo_outcome_evaluate` | Deterministically score a logged action's outcome (improved / regressed / inconclusive) from before/after metrics | `before`, `after` |

### Analytics Registry

Discover and invoke the analytics modules registered for each platform (built-in `google_ads` / `meta_ads`, plus any supplied by provider plugins via the `mureo.analytics` entry-point group). Both tools are read-only diagnostics and route through the standard analysis dispatcher (#440).

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_analytics_modules_list` | List analytics modules per platform and the capabilities each advertises (`detect_anomalies`, `diagnose_performance`, `audit_creative`, `analyze_budget_efficiency`, `detect_delivery_collapse`) | *(none)* |
| `mureo_analytics_run` | Run one capability of a platform's analytics module and return its structured result; degrades to a structured status (`no_analytics_module` / `capability_not_available` / `error`) instead of failing the workflow | `platform`, `capability`, `account_id` |

### Learning

Retrieve accumulated practitioner know-how before drawing diagnostic conclusions — the operator's own `/learn` history and, optionally, federated retrieval against external advisor MCP servers (see [`insight-federation.md`](insight-federation.md)).

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_learning_insights_get` | Load every insight previously saved via `/learn` as raw Markdown | *(none)* |
| `mureo_consult_advisor` | Query external advisor MCP servers (vector search) enriched with local campaign state; advisor responses are treated as untrusted external content | `question` |

### Learning-period reset pre-flight

Every automated-bidding system has a learning period, and a change that restarts it costs days of delivery — most damagingly while someone is troubleshooting a collapsed campaign, because troubleshooting means many changes in a row. This tool answers, *before* the change, whether it restarts learning and whether the campaign is already re-learning.

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `mureo_learning_reset_preflight` | Classify a pending change against the campaign's learning period: `reset_risk` (with the first-party source it rests on), `learning_state`, and whether `## Guardrails` would refuse it | `tool_name` |

Read-only: it calls no platform API and changes nothing.

**Three surfaces, of deliberately different strength.** MCP has no interposed confirmation step — mureo either runs a tool call or refuses it — so these are not interchangeable:

| Surface | When | Strength |
|---|---|---|
| `## Guardrails` `block_learning_resets` / `block_learning_resets_during_incident` | before dispatch | **hard** — the call is refused by `StrategyPolicyGate`, before any API call |

`block_learning_resets` is an account-wide freeze: it refuses every reset-triggering change, with or without an identifiable campaign. `block_learning_resets_during_incident` is narrower by name and in fact — it refuses only a change that **identifies a campaign** which is not positively known to be out of a learning period. An unknown state on an identified campaign is refused (fail-closed); a change that identifies no campaign at all (`google_ads_conversions_*` is account-level, `google_ads_budget_update` is keyed on a `budget_id`) has no subject and is not refused, or the rule would permanently block editing a conversion action with no relation to any incident.
| `mureo_learning_reset_preflight` | before the change, when the agent calls it | advisory — as strong as the agent's compliance |
| A notice appended to a reset-triggering call's own result | after that call | records the reset so the *next* change in the sequence is not made blind |

**Per-platform coverage.** Reset triggers are sourced from first-party documentation only; where mureo has no such source it reports `unknown` and never `no_reset`, because a false "this resets nothing" turns a missing warning into implied approval.

| Platform | Learning state readable by mureo? | Reset triggers known? |
|---|---|---|
| Google Ads | **Yes** — `bidding_details.bidding_strategy_system_status` on the campaign's STATE.json snapshot | **Yes** — Google's own `LEARNING_*` enum members ([`BiddingStrategySystemStatus`](https://developers.google.com/google-ads/api/reference/rpc/v23/BiddingStrategySystemStatusEnum.BiddingStrategySystemStatus)) |
| Meta Ads | No — Meta exposes [`learning_stage_info`](https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-learning-stage-info/) on the **ad set**; mureo's client does not request it and STATE.json is campaign-level | No — Meta documents that "significant edits" restart the phase without enumerating them |
| Amazon Ads (official-MCP bridge) | No — no learning-state read exists on the bridged tool surface | No |
| Yahoo / LINE / SmartNews / LOGLY (plugins) | No — unless the plugin registers rules | No — unless the plugin registers rules |

A plugin or bridge advertises its own platform's rules through `mureo.policy.learning_rules.register_platform_learning_rules`, the same registry pattern the budget/bid declarations use.

**What a platform has no check for — only a wrong assumption.** The table above is the *data* half: facts mureo can verify. The prose half is `mureo.policy.platform_model.register_platform_model` (#648) — one capped paragraph stating how a platform selects and prices delivery, and what it therefore does not have. It is rendered into the server's MCP `instructions` (the `initialize` response), so it is read before any tool call and does not depend on a skill description matching; it appears only when this server serves tools for that platform. Every model carries the same first-party `Evidence` record, and mureo core registers none of its own — a platform with no registered model contributes nothing rather than a default. Registration is first-wins and a model is rendered only where the provider that registered it actually contributed the matching tools, so a plugin can state how its own platform works but never how another's does; a block that lost statements to the length cap says so in the block itself. See [`plugin-authoring.md` §3](plugin-authoring.md#3-provider-protocols).

**The state read is local by design.** A policy gate runs on every tool call and must not make network calls, so the learning state comes from STATE.json rather than from the platform. Keep it fresh (`google_ads_campaigns_get` / `google_ads_campaigns_diagnose` → `mureo_state_upsert_campaign`); a missing observation is reported `unknown`, never `steady`.

### Creative Studio

Generate creator-quality ad creatives — text-free key visuals plus copy composed over them into per-format banners. Image generation runs through configured providers; banner composition renders HTML/CSS with headless Chromium and requires the `creative` extra (`pip install 'mureo[creative]'`). See [`creative-studio.md`](creative-studio.md).

| Tool | Description | Required Parameters |
|------|-------------|-------------------|
| `creative_studio_providers_list` | List image-generation providers, whether each has an API key configured, its capabilities, and model ids | *(none)* |
| `creative_studio_generate_visual` | Generate text-free key-visual PNGs from a visual-only prompt (a hard no-text constraint is appended) | `prompt` |
| `creative_studio_brand_kit_get` | Return the loaded brand kit (colours, fonts, logo, clear-space) or tasteful defaults | *(none)* |
| `creative_studio_edit_visual` | Refine an existing key visual through a provider's edit path (art-direction loop) | `path`, `instruction` |
| `creative_studio_compose` | Composite ad copy + brand kit over a key visual into per-format banner PNGs | `visual_path`, `headline`, `cta` |

### Amazon Ads (official-MCP bridge)

Amazon Ads is **not** a mureo-native tool family, so it has no table above.
mureo bridges the **official Amazon Ads MCP**: the tools it exposes come from
the operator's own local manifest (`amazon_tools.json`, beside the
credentials file — `~/.mureo/amazon_tools.json` by default, written by
`mureo amazon refresh-manifest`), and their surface is defined by Amazon, not
by mureo. That means the exact tool list **cannot be enumerated here** — it is
whatever your account's manifest holds, and it changes when Amazon changes it.

What is stable:

- **Names are Amazon's own** — mureo does not remap official-MCP tool names.
  They are namespaced by Amazon's own taxonomy, e.g. `campaign_management-*`
  and `account_management-*`.
- **Read at start, pure.** The bridge reads the manifest file only — no
  credentials, no network — so a missing or malformed manifest means "no
  Amazon tools", never a startup failure. Re-run `refresh-manifest` and
  restart the server after Amazon's surface changes.
- **Same safety layer as a plugin tool.** Amazon calls ride the plugin
  dispatch branch below: audited to the append-only jsonl log (secrets
  scrubbed), throttled, strategy-gated, and — for successful mutations —
  promoted into `STATE.json` `action_log` under
  `platform="plugin:mureo-amazon-ads-bridge:amazon_ads"` with an observation window.
- **Env gate.** `MUREO_DISABLE_AMAZON_ADS=1` suppresses the bridged Amazon
  family the same way `MUREO_DISABLE_GOOGLE_ADS` / `MUREO_DISABLE_META_ADS`
  suppress their built-in families.

Credential setup (configure UI card, `AMAZON_ADS_*` env vars, or the
`amazon_ads` section of `~/.mureo/credentials.json`), access-token minting and
auto-refresh, and the honest scope of what Amazon support does *not* include
are all covered in [`amazon-ads.md`](amazon-ads.md).

### Plugin-Provided Tools (third-party providers)

Beyond the built-in platforms above, the server also exposes tools from
**third-party provider plugins** discovered via the `mureo.providers`
entry-point group. A plugin opts in by implementing the
`MCPToolProvider` Protocol (`mcp_tools()` + `async handle_mcp_tool()`);
see [`plugin-authoring.md`](plugin-authoring.md) §3. The in-tree Amazon
Ads bridge implements the same Protocol, so everything below applies to
it too.

Server behaviour:

- **Additive.** Plugin tools are appended *after* all built-in tools.
  With no third-party plugins installed, the tool list is identical to
  before — built-in behaviour is unchanged.
- **Built-ins win on name collision.** A plugin tool whose name matches
  any built-in tool is dropped (a `PluginToolWarning` is emitted); the
  built-in keeps the name. Plugin authors should namespace tool names
  with their provider name (e.g. `acme_ads_list_campaigns`).
- **First plugin wins** when two plugins contribute the same tool name.
- **Fault-isolated.** A plugin that fails to construct, whose
  `mcp_tools()` raises, or whose `handle_mcp_tool` is not `async`, is
  skipped with a `PluginToolWarning` — it can never crash the server or
  block other plugins. Discovery itself failing wholesale yields zero
  plugin tools rather than a startup error.
- **Discovered once at server start**, like the env-var gates below.

Plugin tools obey the same `MUREO_DISABLE_*` reasoning only insofar as
the plugin chooses; the disable env vars gate the built-in families,
not third-party plugins. The in-tree **Amazon Ads bridge** rides this
same dispatch branch but *is* mureo's own code, so it does have a gate:
`MUREO_DISABLE_AMAZON_ADS=1`.

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

An auth failure is returned as a result, not raised as an exception — but it is a **structured, machine-readable outcome**, not prose. Every platform uses the same envelope:

```json
[
  {
    "type": "text",
    "text": "{\"status\": \"auth_error\", \"auth_cause\": \"no_credentials\", \"detail\": \"Credentials not found. Set environment variable (META_ADS_ACCESS_TOKEN) or configure ~/.mureo/credentials.json.\"}"
  }
]
```

| Field | Meaning |
|-------|---------|
| `status` | Always `auth_error`. This is the marker to branch on: mureo could not read this platform at all, so it produced **no data** for this call. |
| `auth_cause` | `no_credentials` — nothing is configured for this platform. `token_invalid` — a credential exists and the platform rejected it (expired or revoked token, withdrawn permission). The two have different recovery actions. |
| `detail` | The operator-facing sentence: which environment variable to set, or what the platform said. |

Both causes are produced centrally, so every platform behaves identically: `no_credentials` from the shared `_no_creds_result` helper, `token_invalid` from `@api_error_handler` when the underlying exception is an auth failure (`PlatformAuthError`, an HTTP 401/403, or a Google Ads `authentication_error` / `authorization_error`). The vocabulary lives in `mureo/core/auth_failure.py`.

**An agent must never render an `auth_error` result as data.** A platform that could not be read is not a platform that was quiet, and a report containing one is partial — see the partial-report rule in the `/daily-check`, `/weekly-report` and `/monthly-report` skills. In the two period reports it goes further: a period missing a platform is never compared against a prior period that had it, and the unreadable platform's KPI is omitted from the persisted rollup rather than written as `0`, because that rollup is the next period's baseline. mureo also treats the envelope as a failed call internally: a mutation that returns it is never written to `action_log`.

### API Errors

API errors (rate limits, invalid parameters, etc.) are caught by the `@api_error_handler` decorator and returned as text, prefixed with `API error:`:

```json
[
  {
    "type": "text",
    "text": "API error: Meta API request failed (status=400, path=/act_123/campaigns)"
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
