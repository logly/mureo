"""Meta Ads MCP tool handler implementation

Separates handler functions from tools_meta_ads.py to prevent file size bloat.
Tool definitions (TOOLS) and handler mapping (HANDLERS) remain in tools_meta_ads.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

# The upload / creative handlers live in their own module; re-exported here
# because tools_meta_ads and existing callers import them from this module.
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_creatives_create_carousel as handle_creatives_create_carousel,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_creatives_create_collection as handle_creatives_create_collection,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_images_upload_file as handle_images_upload_file,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_pages_list_photos as handle_pages_list_photos,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_videos_get as handle_videos_get,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_videos_thumbnails as handle_videos_thumbnails,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_videos_upload as handle_videos_upload,
)
from mureo.mcp._handlers_meta_ads_creatives import (
    handle_videos_upload_file as handle_videos_upload_file,
)
from mureo.mcp._helpers import (
    _json_result,
    _opt,
    _require,
    _validate_positive_money,
    api_error_handler,
)

# Client / credential resolution lives in its own module; the names are
# re-exported (``as`` form) because sibling modules and callers import them
# from here.
from mureo.mcp._meta_ads_client import _NO_CREDS_MSG as _NO_CREDS_MSG
from mureo.mcp._meta_ads_client import _entity_result as _entity_result
from mureo.mcp._meta_ads_client import _get_client as _get_client
from mureo.mcp._meta_ads_client import _no_meta_creds as _no_meta_creds
from mureo.mcp._meta_ads_client import _throttler as _throttler

logger = logging.getLogger(__name__)


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
    return _entity_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.get_campaign(campaign_id)
    return _entity_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    _validate_positive_money(args, "daily_budget", "lifetime_budget")
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {
        "name": _require(args, "name"),
        "objective": _require(args, "objective"),
    }
    for key in (
        "status",
        "daily_budget",
        "lifetime_budget",
        "bid_strategy",
        "is_adset_budget_sharing_enabled",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_campaign(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_campaigns_update(args: dict[str, Any]) -> list[TextContent]:
    _validate_positive_money(args, "daily_budget")
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    campaign_id = _require(args, "campaign_id")
    update_kwargs: dict[str, Any] = {}
    for key in ("name", "status", "daily_budget", "bid_strategy"):
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
    return _entity_result(result)


@api_error_handler
async def handle_ad_sets_create(args: dict[str, Any]) -> list[TextContent]:
    _validate_positive_money(args, "daily_budget", "bid_amount")
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
        "bid_strategy",
        "bid_constraints",
        "promoted_object",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    result = await client.create_ad_set(**kwargs)
    return _json_result(result)


def _normalized_end_time(value: Any) -> int | str:
    """Validate an ad-set ``end_time`` argument and normalize the zero form.

    Meta's documented convention for "no end date, run continuously" is
    ``end_time=0``; the string ``"0"`` is wire-identical once form-encoded,
    so it is normalized to the integer ``0`` here — otherwise it could
    sidestep the lifetime-budget contradiction guard below.
    """
    err = ValueError(
        "end_time must be an ISO 8601 datetime string, a UNIX timestamp, "
        f"or 0 to clear the end date (got {value!r})"
    )
    if isinstance(value, bool):
        raise err
    if isinstance(value, int):
        if value < 0:
            raise err
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise err
        return 0 if stripped == "0" else value
    raise err


def _validate_ad_set_schedule_and_budget(args: dict[str, Any]) -> int | str | None:
    """Reject contradictory ad-set budget/schedule updates before dispatch.

    Meta treats daily_budget and lifetime_budget as mutually exclusive on an
    ad set, and a lifetime budget requires a schedule end — while end_time=0
    means "no end date". Returns the normalized end_time (or None if absent).
    """
    if args.get("daily_budget") is not None and args.get("lifetime_budget") is not None:
        raise ValueError(
            "daily_budget and lifetime_budget are mutually exclusive on an "
            "ad set — supply only one."
        )
    if args.get("end_time") is None:
        return None
    end_time = _normalized_end_time(args["end_time"])
    if end_time == 0 and args.get("lifetime_budget") is not None:
        raise ValueError(
            "end_time=0 (no end date) cannot be combined with lifetime_budget "
            "— a lifetime budget requires a schedule end."
        )
    return end_time


@api_error_handler
async def handle_ad_sets_update(args: dict[str, Any]) -> list[TextContent]:
    _validate_positive_money(args, "daily_budget", "lifetime_budget", "bid_amount")
    end_time = _validate_ad_set_schedule_and_budget(args)
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    ad_set_id = _require(args, "ad_set_id")
    update_kwargs: dict[str, Any] = {}
    for key in (
        "name",
        "status",
        "daily_budget",
        "lifetime_budget",
        "targeting",
        "bid_strategy",
        "bid_amount",
        "bid_constraints",
        "promoted_object",
    ):
        val = _opt(args, key)
        if val is not None:
            update_kwargs[key] = val
    # end_time is handled outside the loop: 0 is a meaningful value (clear
    # the end date, Meta convention), so a falsy check must not drop it.
    if end_time is not None:
        update_kwargs["end_time"] = end_time
    replace_targeting = bool(args.get("replace_targeting", False))
    result = await client.update_ad_set(
        ad_set_id, replace_targeting=replace_targeting, **update_kwargs
    )
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
    return _entity_result(result)


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
        "follow_up_action_url": _require(args, "follow_up_action_url"),
    }
    for key in (
        "locale",
        "context_card",
        "thank_you_page",
        "conditional_questions_choices",
    ):
        val = _opt(args, key)
        if val is not None:
            kwargs[key] = val
    if _opt(args, "is_higher_intent"):
        kwargs["is_higher_intent"] = True
    result = await client.create_lead_form(**kwargs)
    return _json_result(result)


@api_error_handler
async def handle_leads_export_csv(args: dict[str, Any]) -> list[TextContent]:
    """Export form leads to a local CSV file."""
    from pathlib import Path as _Path

    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    kwargs: dict[str, Any] = {}
    limit = _opt(args, "limit")
    if limit is not None:
        kwargs["limit"] = limit
    field_order = _opt(args, "field_order")
    if field_order is not None:
        kwargs["field_order"] = field_order
    count = await client.export_leads_to_csv(
        _require(args, "form_id"),
        _Path(_require(args, "output_path")),
        **kwargs,
    )
    return _json_result({"rows": count})


@api_error_handler
async def handle_lead_forms_update(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.update_lead_form(
        _require(args, "form_id"),
        status=_require(args, "status"),
    )
    return _json_result(result)


@api_error_handler
async def handle_lead_forms_duplicate(args: dict[str, Any]) -> list[TextContent]:
    client = await _get_client(args)
    if client is None:
        return _no_meta_creds()
    result = await client.duplicate_lead_form(
        _require(args, "form_id"),
        page_id=_require(args, "page_id"),
        new_name=_require(args, "new_name"),
    )
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
    handle_pages_list,
    handle_split_tests_create,
    handle_split_tests_end,
    handle_split_tests_get,
    handle_split_tests_list,
)
