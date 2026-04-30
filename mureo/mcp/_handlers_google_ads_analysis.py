"""Google Ads MCP tool handler implementation (analysis, monitoring, creative)

Handlers for performance analysis, budget analysis, auction insights,
RSA analysis, B2B optimization, creative, monitoring, and capture.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.mcp._handlers_google_ads import _get_client, _no_google_creds
from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    api_error_handler,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Campaigns & budget (additional)
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_budget_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "name": _require(args, "name"),
        "amount": _require(args, "amount"),
    }
    result = await client.create_budget(params)
    return _json_result(result)


@api_error_handler
async def handle_accounts_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_accounts()
    return _json_result(result)


@api_error_handler
async def handle_network_performance_report(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_network_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_performance_report(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_ad_performance_report(
        ad_group_id=_opt(args, "ad_group_id"),
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Keywords (additional)
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_keywords_pause(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "criterion_id": _require(args, "criterion_id"),
    }
    result = await client.pause_keyword(params)
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_remove(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "criterion_id": _require(args, "criterion_id"),
    }
    result = await client.remove_negative_keyword(params)
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_add_to_ad_group(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_negative_keywords_to_ad_group(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ads (additional)
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_policy_details(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_ad_policy_details(
        _require(args, "ad_group_id"),
        _require(args, "ad_id"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Search term analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_search_terms_analyze(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.analyze_search_terms(
        _require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_suggest(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.suggest_negative_keywords(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
        target_cpa=_opt(args, "target_cpa"),
        ad_group_id=_opt(args, "ad_group_id"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Keyword analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_keywords_audit(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.audit_keywords(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
        target_cpa=_opt(args, "target_cpa"),
    )
    return _json_result(result)


@api_error_handler
async def handle_keywords_cross_adgroup_duplicates(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.find_cross_adgroup_duplicates(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Performance analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_performance_analyze(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.analyze_performance(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_7_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_cost_increase_investigate(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.investigate_cost_increase(
        _require(args, "campaign_id"),
    )
    return _json_result(result)


@api_error_handler
async def handle_health_check(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.health_check_all_campaigns()
    return _json_result(result)


@api_error_handler
async def handle_ad_performance_compare(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.compare_ad_performance(
        ad_group_id=_require(args, "ad_group_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Budget analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_budget_efficiency(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.analyze_budget_efficiency(
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_budget_reallocation(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.suggest_budget_reallocation(
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Auction insights
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_auction_insights_get(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_auction_insights(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# RSA analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_rsa_assets_analyze(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.analyze_rsa_assets(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_rsa_assets_audit(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.audit_rsa_assets(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# B2B
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_btob_optimizations(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.suggest_btob_optimizations(
        campaign_id=_require(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Creative
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_landing_page_analyze(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.analyze_landing_page(_require(args, "url"))
    return _json_result(result)


@api_error_handler
async def handle_creative_research(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.research_creative(
        campaign_id=_require(args, "campaign_id"),
        url=_require(args, "url"),
        ad_group_id=_opt(args, "ad_group_id"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_delivery_goal_evaluate(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.evaluate_delivery_goal(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_cpa_goal_evaluate(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.evaluate_cpa_goal(
        _require(args, "campaign_id"),
        _require(args, "target_cpa"),
    )
    return _json_result(result)


@api_error_handler
async def handle_cv_goal_evaluate(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.evaluate_cv_goal(
        _require(args, "campaign_id"),
        _require(args, "target_cv_daily"),
    )
    return _json_result(result)


@api_error_handler
async def handle_zero_conversions_diagnose(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_zero_conversions(
        _require(args, "campaign_id"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_capture(args: dict[str, Any]) -> list[TextContent]:
    from mureo.google_ads._message_match import LPScreenshotter

    url = _require(args, "url")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    screenshotter = LPScreenshotter()
    screenshot_bytes = await screenshotter.capture(url)
    encoded = base64.b64encode(screenshot_bytes).decode("ascii")
    return _json_result(
        {
            "url": url,
            "screenshot_base64": encoded,
            "format": "png",
        }
    )


# ---------------------------------------------------------------------------
# Handler mapping
# ---------------------------------------------------------------------------

HANDLERS_ANALYSIS: dict[str, Any] = {
    # Campaigns & budget (additional)
    "google_ads_budget_create": handle_budget_create,
    "google_ads_accounts_list": handle_accounts_list,
    "google_ads_network_performance_report": handle_network_performance_report,
    "google_ads_ad_performance_report": handle_ad_performance_report,
    # Keywords (additional)
    "google_ads_keywords_pause": handle_keywords_pause,
    "google_ads_negative_keywords_remove": handle_negative_keywords_remove,
    "google_ads_negative_keywords_add_to_ad_group": handle_negative_keywords_add_to_ad_group,
    # Ads (additional)
    "google_ads_ads_policy_details": handle_ads_policy_details,
    # Search term analysis
    "google_ads_search_terms_analyze": handle_search_terms_analyze,
    "google_ads_negative_keywords_suggest": handle_negative_keywords_suggest,
    # Keyword analysis
    "google_ads_keywords_audit": handle_keywords_audit,
    "google_ads_keywords_cross_adgroup_duplicates": handle_keywords_cross_adgroup_duplicates,
    # Performance analysis
    "google_ads_performance_analyze": handle_performance_analyze,
    "google_ads_cost_increase_investigate": handle_cost_increase_investigate,
    "google_ads_health_check_all": handle_health_check,
    "google_ads_ad_performance_compare": handle_ad_performance_compare,
    # Budget analysis
    "google_ads_budget_efficiency": handle_budget_efficiency,
    "google_ads_budget_reallocation": handle_budget_reallocation,
    # Auction insights
    "google_ads_auction_insights_get": handle_auction_insights_get,
    # RSA analysis
    "google_ads_rsa_assets_analyze": handle_rsa_assets_analyze,
    "google_ads_rsa_assets_audit": handle_rsa_assets_audit,
    # B2B
    "google_ads_btob_optimizations": handle_btob_optimizations,
    # Creative
    "google_ads_landing_page_analyze": handle_landing_page_analyze,
    "google_ads_creative_research": handle_creative_research,
    # Monitoring
    "google_ads_monitoring_delivery_goal": handle_delivery_goal_evaluate,
    "google_ads_monitoring_cpa_goal": handle_cpa_goal_evaluate,
    "google_ads_monitoring_cv_goal": handle_cv_goal_evaluate,
    "google_ads_monitoring_zero_conversions": handle_zero_conversions_diagnose,
    # Capture
    "google_ads_capture_screenshot": handle_capture,
}
