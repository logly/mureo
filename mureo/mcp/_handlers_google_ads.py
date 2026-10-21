"""Google Ads MCP tool handler implementation

Handler functions called from tools_google_ads.py.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

# Client / credential resolution lives in its own module; the names are
# re-exported (``as`` form) because sibling modules import them from here.
from mureo.mcp._google_ads_client import _NO_CREDS_MSG as _NO_CREDS_MSG
from mureo.mcp._google_ads_client import _get_client as _get_client
from mureo.mcp._google_ads_client import _no_google_creds as _no_google_creds
from mureo.mcp._google_ads_client import _throttler as _throttler
from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    api_error_handler,
)
from mureo.mcp._tracking_preflight import (
    PreflightOutcome,
    google_ads_create_preflight,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_campaigns(status_filter=_opt(args, "status_filter"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_campaign(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"name": _require(args, "name")}
    for key in ("bidding_strategy", "budget_id", "channel_type"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.create_campaign(params)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"campaign_id": _require(args, "campaign_id")}
    for key in ("name", "bidding_strategy"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_campaign(params)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update_status(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.update_campaign_status(
        _require(args, "campaign_id"), _require(args, "status")
    )
    return _json_result(result)


@api_error_handler
async def handle_campaigns_diagnose(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_campaign_delivery(_require(args, "campaign_id"))
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad groups
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_groups_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ad_groups(
        campaign_id=_opt(args, "campaign_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_groups_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "name": _require(args, "name"),
    }
    cpc = _opt(args, "cpc_bid_micros")
    if cpc is not None:
        params["cpc_bid_micros"] = cpc
    result = await client.create_ad_group(params)
    return _json_result(result)


@api_error_handler
async def handle_ad_groups_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"ad_group_id": _require(args, "ad_group_id")}
    for key in ("name", "status", "cpc_bid_micros"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_ad_group(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ads
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ads(
        ad_group_id=_opt(args, "ad_group_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


def _with_preflight_note(
    result: dict[str, Any], outcome: PreflightOutcome
) -> dict[str, Any]:
    """Attach a "guardrail did not run" note to a successful create.

    A returned copy, never a mutation of the client's dict. Silence and
    "checked, clean" must not look the same to the operator.
    """
    if outcome.note is None:
        return result
    return {**result, "tracking_preflight": outcome.note}


@api_error_handler
async def handle_ads_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "headlines": _require(args, "headlines"),
        "descriptions": _require(args, "descriptions"),
    }
    for key in ("final_url", "path1", "path2"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    outcome = await google_ads_create_preflight(
        client,
        ad_group_id=params["ad_group_id"],
        final_url=params.get("final_url"),
        acknowledged=bool(_opt(args, "acknowledge_tracking_findings", False)),
    )
    if outcome.refusal is not None:
        return outcome.refusal
    result = await client.create_ad(params)
    return _json_result(_with_preflight_note(result, outcome))


@api_error_handler
async def handle_ads_create_display(args: dict[str, Any]) -> list[TextContent]:
    """Create a Responsive Display Ad. Image file paths are uploaded
    by the client before the ad is created.
    """
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "headlines": _require(args, "headlines"),
        "long_headline": _require(args, "long_headline"),
        "descriptions": _require(args, "descriptions"),
        "business_name": _require(args, "business_name"),
        "marketing_image_paths": _require(args, "marketing_image_paths"),
        "square_marketing_image_paths": _require(args, "square_marketing_image_paths"),
        "final_url": _require(args, "final_url"),
    }
    logos = _opt(args, "logo_image_paths")
    if logos is not None:
        params["logo_image_paths"] = logos
    outcome = await google_ads_create_preflight(
        client,
        ad_group_id=params["ad_group_id"],
        final_url=params.get("final_url"),
        acknowledged=bool(_opt(args, "acknowledge_tracking_findings", False)),
    )
    if outcome.refusal is not None:
        return outcome.refusal
    result = await client.create_display_ad(params)
    return _json_result(_with_preflight_note(result, outcome))


@api_error_handler
async def handle_ads_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "ad_id": _require(args, "ad_id"),
    }
    for key in ("headlines", "descriptions"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_ad(params)
    return _json_result(result)


@api_error_handler
async def handle_ads_update_status(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "ad_id": _require(args, "ad_id"),
        "status": _require(args, "status"),
    }
    result = await client.update_ad_status(**params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_keywords_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_keywords(
        campaign_id=_opt(args, "campaign_id"),
        ad_group_id=_opt(args, "ad_group_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_keywords_add(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_keywords(params)
    return _json_result(result)


@api_error_handler
async def handle_keywords_remove(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "ad_group_id": _require(args, "ad_group_id"),
        "criterion_id": _require(args, "criterion_id"),
    }
    result = await client.remove_keyword(params)
    return _json_result(result)


@api_error_handler
async def handle_keywords_suggest(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    seed = _require(args, "seed_keywords")
    result = await client.suggest_keywords(
        seed,
        language_id=_opt(args, "language_id", "1005"),
        geo_id=_opt(args, "geo_id", "2392"),
    )
    return _json_result(result)


@api_error_handler
async def handle_keywords_diagnose(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_negative_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_add(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_negative_keywords(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Negative placements (delivery-surface exclusions, #544)
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_negative_placements_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_negative_placements(
        campaign_id=_opt(args, "campaign_id"),
        ad_group_id=_opt(args, "ad_group_id"),
    )
    return _json_result(result)


@api_error_handler
async def handle_negative_placements_add(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    # The level keys stay optional here on purpose: the client enforces
    # "exactly one of campaign_id / ad_group_id" in one place, so the two
    # ways of getting it wrong (neither, both) produce the same message.
    params: dict[str, Any] = {
        "campaign_id": _opt(args, "campaign_id"),
        "ad_group_id": _opt(args, "ad_group_id"),
        "placements": _require(args, "placements"),
    }
    result = await client.add_negative_placements(params)
    return _json_result(result)


@api_error_handler
async def handle_negative_placements_remove(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _opt(args, "campaign_id"),
        "ad_group_id": _opt(args, "ad_group_id"),
        "criterion_ids": _require(args, "criterion_ids"),
    }
    result = await client.remove_negative_placements(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_budget_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_budget(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_budget_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {"budget_id": _require(args, "budget_id")}
    # Accept currency-unit or exact-micros forms for the daily and/or total
    # (CUSTOM_PERIOD) amounts. The client validates value bounds and pair
    # exclusivity; here we only require that at least one is present.
    for key in ("amount", "amount_micros", "total_amount", "total_amount_micros"):
        if args.get(key) is not None:
            params[key] = args[key]
    if len(params) == 1:
        raise ValueError(
            "one of 'amount', 'amount_micros', 'total_amount' or "
            "'total_amount_micros' is required"
        )
    result = await client.update_budget(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_performance_report(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_search_terms_report(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_search_terms_report(
        campaign_id=_opt(args, "campaign_id"),
        ad_group_id=_opt(args, "ad_group_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_search_terms_review(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    kwargs: dict[str, Any] = {"campaign_id": _require(args, "campaign_id")}
    period = _opt(args, "period")
    if period:
        kwargs["period"] = period
    target_cpa = _opt(args, "target_cpa")
    if target_cpa is not None:
        kwargs["target_cpa"] = target_cpa
    result = await client.review_search_terms(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_auction_insights(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_auction_insights(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_cpc_detect_trend(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.detect_cpc_trend(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_device_analyze(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_device_performance(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Image assets
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_assets_upload_image(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    file_path = _require(args, "file_path")
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")
    # Keep in sync with the tool schema/description in _tools_google_ads_assets
    # (jpg/jpeg/png/gif). .webp was accepted here but not documented, letting an
    # unsupported upload pass local validation only to be rejected later by the
    # Google Ads API with a confusing error.
    _allowed_image_ext = (".png", ".jpg", ".jpeg", ".gif")
    if not file_path.lower().endswith(_allowed_image_ext):
        raise ValueError(
            f"Unsupported image format. Allowed: {', '.join(_allowed_image_ext)}"
        )
    name = _opt(args, "name")
    result = await client.upload_image_asset(file_path, name=name)
    return _json_result(result)


@api_error_handler
async def handle_image_assets_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_image_assets(limit=_opt(args, "limit", 100))
    return _json_result(result)


# ---------------------------------------------------------------------------
# Performance Max asset-group assets (#590 text, #626 images)
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_asset_group_assets_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_asset_group_assets(
        asset_group_id=_opt(args, "asset_group_id"),
        campaign_id=_opt(args, "campaign_id"),
    )
    return _json_result(result)


@api_error_handler
async def handle_asset_group_assets_replace(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "asset_group_id": _require(args, "asset_group_id"),
        "field_type": _require(args, "field_type"),
        "old_asset_id": _require(args, "old_asset_id"),
        "new_text": _require(args, "new_text"),
    }
    result = await client.replace_asset_group_text_asset(params)
    return _json_result(result)


@api_error_handler
async def handle_asset_group_images_replace(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "asset_group_id": _require(args, "asset_group_id"),
        "field_type": _require(args, "field_type"),
        "old_asset_id": _require(args, "old_asset_id"),
    }
    # new_asset_id / new_image_path are exactly-one-of, which `_require`
    # cannot express. The client refuses zero or two, so the rule holds for
    # any caller, not just this handler.
    for key in ("new_asset_id", "new_image_path", "new_image_name"):
        value = _opt(args, key)
        if value is not None:
            params[key] = value
    result = await client.replace_asset_group_image_asset(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Handler mapping
# ---------------------------------------------------------------------------
_HANDLERS_BASE: dict[str, Any] = {
    "google_ads_campaigns_list": handle_campaigns_list,
    "google_ads_campaigns_get": handle_campaigns_get,
    "google_ads_campaigns_create": handle_campaigns_create,
    "google_ads_campaigns_update": handle_campaigns_update,
    "google_ads_campaigns_update_status": handle_campaigns_update_status,
    "google_ads_campaigns_diagnose": handle_campaigns_diagnose,
    "google_ads_ad_groups_list": handle_ad_groups_list,
    "google_ads_ad_groups_create": handle_ad_groups_create,
    "google_ads_ad_groups_update": handle_ad_groups_update,
    "google_ads_ads_list": handle_ads_list,
    "google_ads_ads_create": handle_ads_create,
    "google_ads_ads_create_display": handle_ads_create_display,
    "google_ads_ads_update": handle_ads_update,
    "google_ads_ads_update_status": handle_ads_update_status,
    "google_ads_keywords_list": handle_keywords_list,
    "google_ads_keywords_add": handle_keywords_add,
    "google_ads_keywords_remove": handle_keywords_remove,
    "google_ads_keywords_suggest": handle_keywords_suggest,
    "google_ads_keywords_diagnose": handle_keywords_diagnose,
    "google_ads_negative_keywords_list": handle_negative_keywords_list,
    "google_ads_negative_keywords_add": handle_negative_keywords_add,
    "google_ads_negative_placements_list": handle_negative_placements_list,
    "google_ads_negative_placements_add": handle_negative_placements_add,
    "google_ads_negative_placements_remove": handle_negative_placements_remove,
    "google_ads_budget_get": handle_budget_get,
    "google_ads_budget_update": handle_budget_update,
    "google_ads_performance_report": handle_performance_report,
    "google_ads_search_terms_report": handle_search_terms_report,
    "google_ads_search_terms_review": handle_search_terms_review,
    "google_ads_auction_insights_analyze": handle_auction_insights,
    "google_ads_cpc_detect_trend": handle_cpc_detect_trend,
    "google_ads_device_analyze": handle_device_analyze,
    "google_ads_assets_upload_image": handle_assets_upload_image,
    "google_ads_image_assets_list": handle_image_assets_list,
    "google_ads_asset_group_assets_list": handle_asset_group_assets_list,
    "google_ads_asset_group_assets_replace": handle_asset_group_assets_replace,
    "google_ads_asset_group_images_replace": handle_asset_group_images_replace,
}

# Merge extension and analysis handlers
from mureo.mcp._handlers_google_ads_analysis import (  # noqa: E402
    HANDLERS_ANALYSIS,
)
from mureo.mcp._handlers_google_ads_extensions import (  # noqa: E402
    HANDLERS_EXTENSIONS,
)

HANDLERS: dict[str, Any] = {
    **_HANDLERS_BASE,
    **HANDLERS_EXTENSIONS,
    **HANDLERS_ANALYSIS,
}
