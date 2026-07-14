"""Google Ads MCP tool handler implementation

Handler functions called from tools_google_ads.py.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.auth import (
    create_google_ads_client,
    load_google_ads_credentials,
)
from mureo.byod.runtime import byod_has
from mureo.core.runtime_context import runtime_google_ads_customer_ids
from mureo.mcp._client_factory import get_google_ads_client
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    _require,
    api_error_handler,
)
from mureo.throttle import GOOGLE_ADS_THROTTLE, Throttler

logger = logging.getLogger(__name__)

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variables "
    "(GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CLIENT_ID, "
    "GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)

_throttler = Throttler(GOOGLE_ADS_THROTTLE)


def _normalize_customer_id(value: str) -> str:
    """Strip hyphens so membership checks are format-insensitive."""
    return value.replace("-", "")


def _resolve_customer_id(requested: str | None, default: str | None) -> str:
    """Resolve and workspace-enforce the Google Ads ``customer_id`` (#411).

    Every Google Ads tool funnels through ``_get_client``, which takes
    ``customer_id`` as a free caller argument while the (possibly shared)
    developer token + OAuth can reach every managed account. This binds
    the EFFECTIVE id — explicit argument or credentials default alike —
    to the active client's allow-list, mirroring Search Console's
    ``site_url`` enforcement (#375):

    - **Not tenant-scoped** (:func:`runtime_google_ads_customer_ids` →
      ``None``): unchanged — argument wins, credentials default
      (``customer_id`` then ``login_customer_id``) second, missing both is
      an error.
    - **Tenant-scoped**: an out-of-set value is refused (fail-closed,
      hyphen-insensitive). No usable value — including a credentials
      default that is not in the set, the common case when only the
      operator's MCC ``login_customer_id`` is present — resolves to the
      single configured account, or is refused when several are configured
      (ambiguous) or none are (fail-fast).
    """
    allowed = runtime_google_ads_customer_ids()
    if allowed is None:
        customer_id = requested or default
        if not customer_id:
            raise ValueError(
                "customer_id is required. Provide it as a parameter or "
                "configure it in ~/.mureo/credentials.json via mureo auth "
                "setup."
            )
        return str(customer_id)
    if not allowed:
        raise ValueError(
            "Google Ads is not configured for this client. Configure the "
            "client's account before querying it."
        )
    normalized_allowed = {_normalize_customer_id(entry) for entry in allowed}
    if requested:
        if _normalize_customer_id(str(requested)) not in normalized_allowed:
            raise ValueError(
                f"customer_id {requested!r} is not one of this client's "
                "configured accounts and was refused."
            )
        return str(requested)
    if default and _normalize_customer_id(str(default)) in normalized_allowed:
        return str(default)
    if len(allowed) == 1:
        return next(iter(allowed))
    raise ValueError(
        "customer_id is required: this client has multiple configured "
        "accounts — pass one of them explicitly."
    )


def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials and create a client.

    Resolution order for customer_id:
    1. Explicit customer_id in tool arguments
    2. creds.customer_id from credentials.json
    3. creds.login_customer_id as fallback (legacy credentials without
       a separate customer_id field)

    In BYOD mode (``~/.mureo/byod/manifest.json`` registers google_ads),
    no credentials are required and a CSV-backed client is returned.

    Returns None on auth error (real mode only).
    """
    if byod_has("google_ads"):
        customer_id = _opt(arguments, "customer_id") or "byod"
        return get_google_ads_client(
            creds=None, customer_id=customer_id, throttler=_throttler
        )

    creds = load_google_ads_credentials()
    if creds is None:
        return None

    # getattr, not attribute access: the default must not be evaluated
    # eagerly against credential objects that lack the field (the old
    # ``or``-chain short-circuited when an explicit id was passed).
    customer_id = _resolve_customer_id(
        _opt(arguments, "customer_id"),
        getattr(creds, "customer_id", None)
        or getattr(creds, "login_customer_id", None),
    )
    if not str(customer_id).replace("-", "").isdigit():
        raise ValueError(
            f"Invalid customer_id format: {customer_id} (must be numeric, hyphens allowed)"
        )
    return create_google_ads_client(creds, customer_id, throttler=_throttler)


def _no_google_creds() -> list[TextContent]:
    """Return a Google Ads credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_campaigns_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_campaigns(status_filter=_opt(args, "status_filter"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_campaign(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_campaigns_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.update_campaign_status(
        _require(args, "campaign_id"), _require(args, "status")
    )
    return _json_result(result)


@api_error_handler
async def handle_campaigns_diagnose(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_campaign_delivery(_require(args, "campaign_id"))
    return _json_result(result)


# ---------------------------------------------------------------------------
# Ad groups
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_ad_groups_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ad_groups(
        campaign_id=_opt(args, "campaign_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ad_groups_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_ads(
        ad_group_id=_opt(args, "ad_group_id"),
        status_filter=_opt(args, "status_filter"),
    )
    return _json_result(result)


@api_error_handler
async def handle_ads_create(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    result = await client.create_ad(params)
    return _json_result(result)


@api_error_handler
async def handle_ads_create_display(args: dict[str, Any]) -> list[TextContent]:
    """Create a Responsive Display Ad. Image file paths are uploaded
    by the client before the ad is created.
    """
    client = _get_client(args)
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
    result = await client.create_display_ad(params)
    return _json_result(result)


@api_error_handler
async def handle_ads_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.diagnose_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_list(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_negative_keywords(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_negative_keywords_add(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    params: dict[str, Any] = {
        "campaign_id": _require(args, "campaign_id"),
        "keywords": _require(args, "keywords"),
    }
    result = await client.add_negative_keywords(params)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_budget_get(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_budget(_require(args, "campaign_id"))
    return _json_result(result)


@api_error_handler
async def handle_budget_update(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.get_performance_report(
        campaign_id=_opt(args, "campaign_id"),
        period=_opt(args, "period", "LAST_30_DAYS"),
    )
    return _json_result(result)


@api_error_handler
async def handle_search_terms_report(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.analyze_auction_insights(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_cpc_detect_trend(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    campaign_id = _require(args, "campaign_id")
    result = await client.detect_cpc_trend(
        campaign_id, period=_opt(args, "period", "LAST_30_DAYS")
    )
    return _json_result(result)


@api_error_handler
async def handle_device_analyze(args: dict[str, Any]) -> list[TextContent]:
    client = _get_client(args)
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
    client = _get_client(args)
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
    client = _get_client(args)
    if client is None:
        return _no_google_creds()
    result = await client.list_image_assets(limit=_opt(args, "limit", 100))
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
