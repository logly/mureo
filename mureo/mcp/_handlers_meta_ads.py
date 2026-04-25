"""Meta Ads MCP tool handler implementation

Separates handler functions from tools_meta_ads.py to prevent file size bloat.
Tool definitions (TOOLS) and handler mapping (HANDLERS) remain in tools_meta_ads.py.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.auth import (
    create_meta_ads_client,
    load_meta_ads_credentials,
    refresh_meta_token_if_needed,
)
from mureo.mcp._client_factory import get_meta_ads_client, is_demo_mode
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    _require,
    api_error_handler,
)
from mureo.throttle import META_ADS_THROTTLE, Throttler

logger = logging.getLogger(__name__)

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variable "
    "(META_ADS_ACCESS_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)

_throttler = Throttler(META_ADS_THROTTLE)


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials, refresh token if needed, and create a client.

    Falls back to account_id from credentials.json if not provided
    in the tool arguments.

    In demo mode, returns a CSV-backed client without any credentials
    or network access.

    Returns None on auth error (real mode only).
    """
    if is_demo_mode():
        account_id = _opt(arguments, "account_id") or "act_demo"
        return get_meta_ads_client(
            creds=None, account_id=account_id, throttler=_throttler
        )

    creds = load_meta_ads_credentials()
    if creds is None:
        return None

    account_id = _opt(arguments, "account_id") or creds.account_id
    if not account_id:
        raise ValueError(
            "account_id is required. Provide it as a parameter or configure it "
            "in ~/.mureo/credentials.json via mureo auth setup."
        )
    if not str(account_id).startswith("act_"):
        raise ValueError(
            f"Invalid account_id format: {account_id} (must start with 'act_')"
        )

    creds = await refresh_meta_token_if_needed(creds)
    return create_meta_ads_client(creds, account_id, throttler=_throttler)


def _no_meta_creds() -> list[TextContent]:
    """Return a Meta Ads credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)


# ---------------------------------------------------------------------------
# Campaign handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_campaigns(
        status_filter=_opt(args, "status_filter"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.get_campaign(campaign_id)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "objective": _require(args, "objective"),
    }
    for key in ("status", "daily_budget", "lifetime_budget"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_campaign(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status", "daily_budget"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_campaign(campaign_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad set handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_sets_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ad_sets(
        campaign_id=_opt(args, "campaign_id"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "name": _require(args, "name"),
    }
    for key in (
        "daily_budget",
        "billing_event",
        "optimization_goal",
        "targeting",
        "status",
        "bid_amount",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_ad_set(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ad_sets_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status", "daily_budget", "targeting"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_ad_set(ad_set_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ads_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_ads(
        ad_set_id=_opt(args, "ad_set_id"),
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_ads_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "ad_set_id": _require(args, "ad_set_id"),
        "name": _require(args, "name"),
        "creative_id": _require(args, "creative_id"),
    }
    status = _opt(args, "status")
    if status is not None:
        kwargs["status"] = status
    result = await client.create_ad(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_ads_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status"):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    result = await client.update_ad(ad_id, **update_kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Insights handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_insights_report(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.get_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "last_7d"),
        level=_opt(args, "level", "campaign"),
    )
    return _json_result(result)


@api_error_handler
async def handle_insights_breakdown(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.get_breakdown_report(
        campaign_id=campaign_id,
        breakdown=_opt(args, "breakdown", "age,gender"),
        period=_opt(args, "period", "last_7d"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Audience handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_audiences_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.list_custom_audiences(
        limit=_opt(args, "limit", 50),
    )
    return _json_result(result)


@api_error_handler
async def handle_audiences_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "subtype": _opt(args, "subtype", "CUSTOM"),
    }
    for key in (
        "description",
        "retention_days",
        "pixel_id",
        "rule",
        "customer_file_source",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_custom_audience(**kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Conversions (CAPI) handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_conversions_send(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    pixel_id = _require(args, "pixel_id")
    events = _require(args, "events")
    test_event_code = _opt(args, "test_event_code")
    result = await client.send_event(pixel_id, events, test_event_code=test_event_code)
    return _json_result(result)


@api_error_handler
async def handle_conversions_send_purchase(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "pixel_id": _require(args, "pixel_id"),
        "event_time": _require(args, "event_time"),
        "user_data": _require(args, "user_data"),
        "currency": _require(args, "currency"),
        "value": _require(args, "value"),
    }
    for key in ("content_ids", "event_source_url", "test_event_code"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.send_purchase_event(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_conversions_send_lead(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "pixel_id": _require(args, "pixel_id"),
        "event_time": _require(args, "event_time"),
        "user_data": _require(args, "user_data"),
    }
    for key in ("event_source_url", "test_event_code"):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.send_lead_event(**kwargs)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Catalog handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_catalogs_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    business_id = _require(args, "business_id")
    result = await client.list_catalogs(business_id)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    business_id = _require(args, "business_id")
    name = _require(args, "name")
    result = await client.create_catalog(business_id, name)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.get_catalog(catalog_id)
    return _json_result(result)


@api_error_handler
async def handle_catalogs_delete(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.delete_catalog(catalog_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Product handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_products_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.list_products(catalog_id, limit=_opt(args, "limit", 100))
    return _json_result(result)


@api_error_handler
async def handle_products_add(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    product_data: dict[str, Any] = {
        "retailer_id": _require(args, "retailer_id"),
        "name": _require(args, "name"),
        "availability": _require(args, "availability"),
        "condition": _require(args, "condition"),
        "price": _require(args, "price"),
        "url": _require(args, "url"),
        "image_url": _require(args, "image_url"),
    }
    for key in ("description", "brand", "category"):
        val = _opt(args, key)
        if val is not None:
            product_data[key] = val
    result = await client.add_product(catalog_id, product_data)
    return _json_result(result)


@api_error_handler
async def handle_products_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    result = await client.get_product(product_id)
    return _json_result(result)


@api_error_handler
async def handle_products_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    updates: dict[str, Any] = {}
    for key in (
        "name",
        "description",
        "availability",
        "price",
        "url",
        "image_url",
        "brand",
        "category",
    ):
        val = _opt(args, key)
        if val is not None:
            updates[key] = val
    result = await client.update_product(product_id, updates)
    return _json_result(result)


@api_error_handler
async def handle_products_delete(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    product_id = _require(args, "product_id")
    result = await client.delete_product(product_id)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Feed handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_feeds_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    result = await client.list_product_feeds(catalog_id)
    return _json_result(result)


@api_error_handler
async def handle_feeds_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    catalog_id = _require(args, "catalog_id")
    name = _require(args, "name")
    feed_url = _require(args, "feed_url")
    schedule = _opt(args, "schedule", "DAILY")
    result = await client.create_product_feed(
        catalog_id, name, feed_url, schedule=schedule
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Lead ad handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_lead_forms_list(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    page_id = _require(args, "page_id")
    result = await client.list_lead_forms(page_id, limit=_opt(args, "limit", 50))
    return _json_result(result)


@api_error_handler
async def handle_lead_forms_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    form_id = _require(args, "form_id")
    result = await client.get_lead_form(form_id)
    return _json_result(result)


@api_error_handler
async def handle_lead_forms_create(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "page_id": _require(args, "page_id"),
        "name": _require(args, "name"),
        "questions": _require(args, "questions"),
        "privacy_policy_url": _require(args, "privacy_policy_url"),
    }
    follow_up = _opt(args, "follow_up_action_url")
    if follow_up is not None:
        kwargs["follow_up_action_url"] = follow_up
    result = await client.create_lead_form(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_leads_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    form_id = _require(args, "form_id")
    result = await client.get_leads(form_id, limit=_opt(args, "limit", 100))
    return _json_result(result)


@api_error_handler
async def handle_leads_get_by_ad(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_id = _require(args, "ad_id")
    result = await client.get_ad_leads(ad_id, limit=_opt(args, "limit", 100))
    return _json_result(result)


# ---------------------------------------------------------------------------
# Image upload handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_images_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")
    _allowed_image_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    if not file_path.lower().endswith(_allowed_image_ext):
        raise ValueError(
            f"Unsupported image format. Allowed: {', '.join(_allowed_image_ext)}"
        )
    name = _opt(args, "name")
    result = await client.upload_ad_image_file(file_path, name=name)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Video, carousel, collection handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_videos_upload(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    video_url = _require(args, "video_url")
    title = _opt(args, "title")
    result = await client.upload_ad_video(video_url, title=title)
    return _json_result(result)


@api_error_handler
async def handle_videos_upload_file(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    file_path = _require(args, "file_path")
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")
    _allowed_video_ext = (".mp4", ".mov", ".avi", ".wmv", ".flv", ".mkv")
    if not file_path.lower().endswith(_allowed_video_ext):
        raise ValueError(
            f"Unsupported video format. Allowed: {', '.join(_allowed_video_ext)}"
        )
    title = _opt(args, "title")
    result = await client.upload_ad_video_file(file_path, title=title)
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_carousel(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_carousel_creative(
        page_id=_require(args, "page_id"),
        cards=_require(args, "cards"),
        link=_require(args, "link"),
        name=_opt(args, "name"),
    )
    return _json_result(result)


@api_error_handler
async def handle_creatives_create_collection(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.create_collection_creative(
        page_id=_require(args, "page_id"),
        product_ids=_require(args, "product_ids"),
        link=_require(args, "link"),
        cover_image_hash=_opt(args, "cover_image_hash"),
        cover_video_id=_opt(args, "cover_video_id"),
        name=_opt(args, "name"),
    )
    return _json_result(result)


# ---------------------------------------------------------------------------
# Page posts, Instagram, Split Test, Ad Rules handlers are separated into
# _handlers_meta_ads_other.py. Re-exported here for backward compatibility.
# ---------------------------------------------------------------------------

from mureo.mcp._handlers_meta_ads_other import (  # noqa: E402, F401
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
