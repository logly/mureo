"""Meta Ads MCP tool definitions and handler mapping

Provides tool definitions (MCP Tool) and handler dispatch.
Handler implementations are separated into _handlers_meta_ads.py / _handlers_meta_ads_extended.py.
Dispatched from server.py.

Tool definitions are split into category sub-modules:
  _tools_meta_ads_campaigns.py   -- Campaigns, ad sets, ads
  _tools_meta_ads_creatives.py   -- Creatives, images, videos
  _tools_meta_ads_audiences.py   -- Audiences, pixels
  _tools_meta_ads_insights.py    -- Insights, analysis
  _tools_meta_ads_catalog.py     -- Catalog, products, feeds
  _tools_meta_ads_leads.py       -- Lead forms, leads
  _tools_meta_ads_other.py       -- Split tests, automated rules, page posts, Instagram
  _tools_meta_ads_conversions.py -- Conversions (CAPI)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent, Tool

from mureo.mcp._handlers_meta_ads import (
    handle_ad_sets_create,
    handle_ad_sets_list,
    handle_ad_sets_update,
    handle_ads_create,
    handle_ads_list,
    handle_ads_update,
    handle_audiences_create,
    handle_audiences_list,
    handle_campaigns_create,
    handle_campaigns_get,
    handle_campaigns_list,
    handle_campaigns_update,
    handle_catalogs_create,
    handle_catalogs_delete,
    handle_catalogs_get,
    handle_catalogs_list,
    handle_conversions_send,
    handle_conversions_send_lead,
    handle_conversions_send_purchase,
    handle_creatives_create_carousel,
    handle_creatives_create_collection,
    handle_feeds_create,
    handle_feeds_list,
    handle_images_upload_file,
    handle_insights_breakdown,
    handle_insights_report,
    handle_lead_forms_create,
    handle_lead_forms_get,
    handle_lead_forms_list,
    handle_leads_get,
    handle_leads_get_by_ad,
    handle_products_add,
    handle_products_delete,
    handle_products_get,
    handle_products_list,
    handle_products_update,
    handle_videos_upload,
    handle_videos_upload_file,
)
from mureo.mcp._handlers_meta_ads_extended import (
    handle_ad_sets_enable,
    handle_ad_sets_get,
    handle_ad_sets_pause,
    handle_ads_enable,
    handle_ads_get,
    handle_ads_pause,
    handle_analysis_audience,
    handle_analysis_compare_ads,
    handle_analysis_cost,
    handle_analysis_performance,
    handle_analysis_placements,
    handle_analysis_suggest_creative,
    handle_audiences_create_lookalike,
    handle_audiences_delete,
    handle_audiences_get,
    handle_campaigns_enable,
    handle_campaigns_pause,
    handle_creatives_create,
    handle_creatives_create_dynamic,
    handle_creatives_list,
    handle_creatives_upload_image,
    handle_pixels_events,
    handle_pixels_get,
    handle_pixels_list,
    handle_pixels_stats,
)
from mureo.mcp._handlers_meta_ads_other import (
    handle_ad_rules_create,
    handle_ad_rules_delete,
    handle_ad_rules_get,
    handle_ad_rules_list,
    handle_ad_rules_update,
    handle_instagram_accounts,
    handle_instagram_boost,
    handle_instagram_media,
    handle_page_posts_boost,
    handle_page_posts_list,
    handle_split_tests_create,
    handle_split_tests_end,
    handle_split_tests_get,
    handle_split_tests_list,
)

# Import category-specific tool definitions
from mureo.mcp._tools_meta_ads_audiences import TOOLS as _TOOLS_AUDIENCES
from mureo.mcp._tools_meta_ads_campaigns import TOOLS as _TOOLS_CAMPAIGNS
from mureo.mcp._tools_meta_ads_catalog import TOOLS as _TOOLS_CATALOG
from mureo.mcp._tools_meta_ads_conversions import TOOLS as _TOOLS_CONVERSIONS
from mureo.mcp._tools_meta_ads_creatives import TOOLS as _TOOLS_CREATIVES
from mureo.mcp._tools_meta_ads_insights import TOOLS as _TOOLS_INSIGHTS
from mureo.mcp._tools_meta_ads_leads import TOOLS as _TOOLS_LEADS
from mureo.mcp._tools_meta_ads_other import TOOLS as _TOOLS_OTHER

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool definitions -- aggregated from sub-modules
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = (
    _TOOLS_CAMPAIGNS
    + _TOOLS_INSIGHTS
    + _TOOLS_AUDIENCES
    + _TOOLS_CONVERSIONS
    + _TOOLS_CATALOG
    + _TOOLS_LEADS
    + _TOOLS_CREATIVES
    + _TOOLS_OTHER
)

# Tool name lookup set
_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Execute the handler corresponding to the tool name.

    Raises:
        ValueError: Unknown tool name or missing required parameter
    """
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")

    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Handler mapping
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    # Campaigns
    "meta_ads_campaigns_list": handle_campaigns_list,
    "meta_ads_campaigns_get": handle_campaigns_get,
    "meta_ads_campaigns_create": handle_campaigns_create,
    "meta_ads_campaigns_update": handle_campaigns_update,
    "meta_ads_campaigns_pause": handle_campaigns_pause,
    "meta_ads_campaigns_enable": handle_campaigns_enable,
    # Ad sets
    "meta_ads_ad_sets_list": handle_ad_sets_list,
    "meta_ads_ad_sets_get": handle_ad_sets_get,
    "meta_ads_ad_sets_create": handle_ad_sets_create,
    "meta_ads_ad_sets_update": handle_ad_sets_update,
    "meta_ads_ad_sets_pause": handle_ad_sets_pause,
    "meta_ads_ad_sets_enable": handle_ad_sets_enable,
    # Ads
    "meta_ads_ads_list": handle_ads_list,
    "meta_ads_ads_get": handle_ads_get,
    "meta_ads_ads_create": handle_ads_create,
    "meta_ads_ads_update": handle_ads_update,
    "meta_ads_ads_pause": handle_ads_pause,
    "meta_ads_ads_enable": handle_ads_enable,
    # Insights
    "meta_ads_insights_report": handle_insights_report,
    "meta_ads_insights_breakdown": handle_insights_breakdown,
    # Audiences
    "meta_ads_audiences_list": handle_audiences_list,
    "meta_ads_audiences_get": handle_audiences_get,
    "meta_ads_audiences_create": handle_audiences_create,
    "meta_ads_audiences_delete": handle_audiences_delete,
    "meta_ads_audiences_create_lookalike": handle_audiences_create_lookalike,
    # Conversions
    "meta_ads_conversions_send": handle_conversions_send,
    "meta_ads_conversions_send_purchase": handle_conversions_send_purchase,
    "meta_ads_conversions_send_lead": handle_conversions_send_lead,
    # Catalogs
    "meta_ads_catalogs_list": handle_catalogs_list,
    "meta_ads_catalogs_create": handle_catalogs_create,
    "meta_ads_catalogs_get": handle_catalogs_get,
    "meta_ads_catalogs_delete": handle_catalogs_delete,
    # Products
    "meta_ads_products_list": handle_products_list,
    "meta_ads_products_add": handle_products_add,
    "meta_ads_products_get": handle_products_get,
    "meta_ads_products_update": handle_products_update,
    "meta_ads_products_delete": handle_products_delete,
    # Feeds
    "meta_ads_feeds_list": handle_feeds_list,
    "meta_ads_feeds_create": handle_feeds_create,
    # Lead ads
    "meta_ads_lead_forms_list": handle_lead_forms_list,
    "meta_ads_lead_forms_get": handle_lead_forms_get,
    "meta_ads_lead_forms_create": handle_lead_forms_create,
    "meta_ads_leads_get": handle_leads_get,
    "meta_ads_leads_get_by_ad": handle_leads_get_by_ad,
    # Image upload
    "meta_ads_images_upload_file": handle_images_upload_file,
    # Videos
    "meta_ads_videos_upload": handle_videos_upload,
    "meta_ads_videos_upload_file": handle_videos_upload_file,
    # Creatives
    "meta_ads_creatives_list": handle_creatives_list,
    "meta_ads_creatives_create": handle_creatives_create,
    "meta_ads_creatives_create_dynamic": handle_creatives_create_dynamic,
    "meta_ads_creatives_upload_image": handle_creatives_upload_image,
    "meta_ads_creatives_create_carousel": handle_creatives_create_carousel,
    "meta_ads_creatives_create_collection": handle_creatives_create_collection,
    # Pixels
    "meta_ads_pixels_list": handle_pixels_list,
    "meta_ads_pixels_get": handle_pixels_get,
    "meta_ads_pixels_stats": handle_pixels_stats,
    "meta_ads_pixels_events": handle_pixels_events,
    # Analysis
    "meta_ads_analysis_performance": handle_analysis_performance,
    "meta_ads_analysis_audience": handle_analysis_audience,
    "meta_ads_analysis_placements": handle_analysis_placements,
    "meta_ads_analysis_cost": handle_analysis_cost,
    "meta_ads_analysis_compare_ads": handle_analysis_compare_ads,
    "meta_ads_analysis_suggest_creative": handle_analysis_suggest_creative,
    # Split Test (A/B test)
    "meta_ads_split_tests_list": handle_split_tests_list,
    "meta_ads_split_tests_get": handle_split_tests_get,
    "meta_ads_split_tests_create": handle_split_tests_create,
    "meta_ads_split_tests_end": handle_split_tests_end,
    # Ad Rules (automated rules)
    "meta_ads_ad_rules_list": handle_ad_rules_list,
    "meta_ads_ad_rules_get": handle_ad_rules_get,
    "meta_ads_ad_rules_create": handle_ad_rules_create,
    "meta_ads_ad_rules_update": handle_ad_rules_update,
    "meta_ads_ad_rules_delete": handle_ad_rules_delete,
    # Page posts
    "meta_ads_page_posts_list": handle_page_posts_list,
    "meta_ads_page_posts_boost": handle_page_posts_boost,
    # Instagram
    "meta_ads_instagram_accounts": handle_instagram_accounts,
    "meta_ads_instagram_media": handle_instagram_media,
    "meta_ads_instagram_boost": handle_instagram_boost,
}
