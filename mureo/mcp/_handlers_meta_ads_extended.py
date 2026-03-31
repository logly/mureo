"""Meta Ads MCP additional tool handler implementation

Separated from _handlers_meta_ads.py to prevent file size bloat.

Covered categories:
- Campaigns (pause / enable)
- Ad sets (get / pause / enable)
- Ads (get / pause / enable)
- Audiences (get / delete / lookalike)
- Creatives (list / create / dynamic / upload_image)
- Pixels (list / get / stats / events)
- Analysis (analyze_performance / analyze_audience / analyze_placements /
        investigate_cost / compare_ads / suggest_creative_improvements)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.mcp._handlers_meta_ads import _get_client, _no_meta_creds
from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    api_error_handler,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Campaign pause / enable
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_pause(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.pause_campaign(campaign_id)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_enable(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.enable_campaign(campaign_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad set get / pause / enable
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_sets_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    result = await client.get_ad_set(ad_set_id)
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_pause(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    result = await client.pause_ad_set(ad_set_id)
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_enable(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    result = await client.enable_ad_set(ad_set_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad get / pause / enable
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    result = await client.get_ad(ad_id)
    return _json_result(result)


@api_error_handler
async def handle_ads_pause(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    result = await client.pause_ad(ad_id)
    return _json_result(result)


@api_error_handler
async def handle_ads_enable(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    result = await client.enable_ad(ad_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Audience get / delete / lookalike
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_audiences_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    audience_id = _require(args, "audience_id")
    result = await client.get_custom_audience(audience_id)
    return _json_result(result)


@api_error_handler
async def handle_audiences_delete(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    audience_id = _require(args, "audience_id")
    result = await client.delete_custom_audience(audience_id)
    return _json_result(result)


@api_error_handler
async def handle_audiences_create_lookalike(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "source_audience_id": _require(args, "source_audience_id"),
        "country": _require(args, "country"),
        "ratio": _require(args, "ratio"),
    }
    starting_ratio = _opt(args, "starting_ratio")
    if starting_ratio is not None:
        kwargs["starting_ratio"] = starting_ratio
    result = await client.create_lookalike_audience(**kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Creative list / create / dynamic / upload_image
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_creatives_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_creatives(
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_creatives_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "page_id": _require(args, "page_id"),
        "link_url": _require(args, "link_url"),
    }
    for key in (
        "image_url",
        "image_hash",
        "message",
        "headline",
        "description",
        "call_to_action",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_ad_creative(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_dynamic(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "page_id": _require(args, "page_id"),
        "image_hashes": _require(args, "image_hashes"),
        "bodies": _require(args, "bodies"),
        "titles": _require(args, "titles"),
        "link_url": _require(args, "link_url"),
    }
    for key in ("descriptions", "call_to_actions"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_dynamic_creative(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_creatives_upload_image(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    image_url = _require(args, "image_url")
    result = await client.upload_ad_image(image_url)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Pixel list / get / stats / events
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_pixels_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_pixels(
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_pixels_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    pixel_id = _require(args, "pixel_id")
    result = await client.get_pixel(pixel_id)
    return _json_result(result)


@api_error_handler
async def handle_pixels_stats(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    pixel_id = _require(args, "pixel_id")
    period = _opt(args, "period", "last_7d")
    result = await client.get_pixel_stats(pixel_id, period=period)
    return _json_result(result)


@api_error_handler
async def handle_pixels_events(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    pixel_id = _require(args, "pixel_id")
    result = await client.get_pixel_events(pixel_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Analysis handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_analysis_performance(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.analyze_performance(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analysis_audience(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_audience(
        campaign_id=campaign_id,
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analysis_placements(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_placements(
        campaign_id=campaign_id,
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analysis_cost(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.investigate_cost(
        campaign_id=campaign_id,
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analysis_compare_ads(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    result = await client.compare_ads(
        ad_set_id=ad_set_id,
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analysis_suggest_creative(
    args: dict[str, Any],
) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.suggest_creative_improvements(
        campaign_id=campaign_id,
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)
