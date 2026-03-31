"""Google Ads MCP tool handler implementation (extensions)

Handlers for sitelinks, callouts, conversions, and targeting.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
# Sitelinks
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_sitelinks_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_sitelinks(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_sitelinks_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "link_text": _require(args, "link_text"),
        "final_url": _require(args, "final_url"),
    }
    for key in ("description1", "description2"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.create_sitelink(params)
    return _json_result(result)


@api_error_handler
async def handle_sitelinks_remove(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "asset_id": _require(args, "asset_id"),
    }
    result = await client.remove_sitelink(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Callouts
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_callouts_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_callouts(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_callouts_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "callout_text": _require(args, "callout_text"),
    }
    result = await client.create_callout(params)
    return _json_result(result)


@api_error_handler
async def handle_callouts_remove(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "asset_id": _require(args, "asset_id"),
    }
    result = await client.remove_callout(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_conversions_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_conversion_actions()
    return _json_result(result)


@api_error_handler
async def handle_conversions_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_conversion_action(_require(args, "conversion_action_id"))
    return _json_result(result)


@api_error_handler
async def handle_conversions_performance(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_conversion_performance(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_conversions_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "name": _require(args, "name"),
    }
    for key in (
        "type",
        "category",
        "default_value",
        "always_use_default_value",
        "click_through_lookback_window_days",
        "view_through_lookback_window_days",
    ):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.create_conversion_action(params)
    return _json_result(result)


@api_error_handler
async def handle_conversions_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "conversion_action_id": _require(args, "conversion_action_id"),
    }
    for key in (
        "name",
        "category",
        "status",
        "default_value",
        "always_use_default_value",
        "click_through_lookback_window_days",
        "view_through_lookback_window_days",
    ):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_conversion_action(params)
    return _json_result(result)


@api_error_handler
async def handle_conversions_remove(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "conversion_action_id": _require(args, "conversion_action_id"),
    }
    result = await client.remove_conversion_action(params)
    return _json_result(result)


@api_error_handler
async def handle_conversions_tag(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_conversion_action_tag(
        _require(args, "conversion_action_id")
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Targeting
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_recommendations_list(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_recommendations(
        campaign_id=_opt(args, "campaign_id"),
        recommendation_type=_opt(args, "recommendation_type"),
    )
    return _json_result(result)


@api_error_handler
async def handle_recommendations_apply(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "resource_name": _require(args, "resource_name"),
    }
    result = await client.apply_recommendation(params)
    return _json_result(result)


@api_error_handler
async def handle_device_targeting_get(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_device_targeting(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_device_targeting_set(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "enabled_devices": _require(args, "enabled_devices"),
    }
    result = await client.set_device_targeting(params)
    return _json_result(result)


@api_error_handler
async def handle_bid_adjustments_get(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_bid_adjustments(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_bid_adjustments_update(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "criterion_id": _require(args, "criterion_id"),
        "bid_modifier": _require(args, "bid_modifier"),
    }
    result = await client.update_bid_adjustment(params)
    return _json_result(result)


@api_error_handler
async def handle_location_targeting_list(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_location_targeting(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_location_targeting_update(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
    }
    for key in ("add_locations", "remove_criterion_ids"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_location_targeting(params)
    return _json_result(result)


@api_error_handler
async def handle_schedule_targeting_list(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_schedule_targeting(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_schedule_targeting_update(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
    }
    for key in ("add_schedules", "remove_criterion_ids"):
        val = _opt(args, key)
        if val is not None:
            params[key] = val
    result = await client.update_schedule_targeting(params)
    return _json_result(result)


@api_error_handler
async def handle_change_history_list(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_change_history(
        start_date=_opt(args, "start_date"),
        end_date=_opt(args, "end_date"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Handler mapping
# ---------------------------------------------------------------------------

HANDLERS_EXTENSIONS: dict[str, Any] = {
    # Sitelinks
    "google_ads.sitelinks.list": handle_sitelinks_list,
    "google_ads.sitelinks.create": handle_sitelinks_create,
    "google_ads.sitelinks.remove": handle_sitelinks_remove,
    # Callouts
    "google_ads.callouts.list": handle_callouts_list,
    "google_ads.callouts.create": handle_callouts_create,
    "google_ads.callouts.remove": handle_callouts_remove,
    # Conversions
    "google_ads.conversions.list": handle_conversions_list,
    "google_ads.conversions.get": handle_conversions_get,
    "google_ads.conversions.performance": handle_conversions_performance,
    "google_ads.conversions.create": handle_conversions_create,
    "google_ads.conversions.update": handle_conversions_update,
    "google_ads.conversions.remove": handle_conversions_remove,
    "google_ads.conversions.tag": handle_conversions_tag,
    # Targeting
    "google_ads.recommendations.list": handle_recommendations_list,
    "google_ads.recommendations.apply": handle_recommendations_apply,
    "google_ads.device_targeting.get": handle_device_targeting_get,
    "google_ads.device_targeting.set": handle_device_targeting_set,
    "google_ads.bid_adjustments.get": handle_bid_adjustments_get,
    "google_ads.bid_adjustments.update": handle_bid_adjustments_update,
    "google_ads.location_targeting.list": handle_location_targeting_list,
    "google_ads.location_targeting.update": handle_location_targeting_update,
    "google_ads.schedule_targeting.list": handle_schedule_targeting_list,
    "google_ads.schedule_targeting.update": handle_schedule_targeting_update,
    "google_ads.change_history.list": handle_change_history_list,
}
