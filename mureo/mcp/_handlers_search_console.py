"""Search Console MCP handler implementations.

Handler functions for Google Search Console MCP tools.
Tool definitions and handler mapping are in tools_search_console.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.auth import create_search_console_client, load_google_ads_credentials
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    _require,
    api_error_handler,
)
from mureo.throttle import SEARCH_CONSOLE_THROTTLE, Throttler

logger = logging.getLogger(__name__)

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variables "
    "(GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)

_throttler = Throttler(SEARCH_CONSOLE_THROTTLE)


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials and create a Search Console client.

    Returns None on auth error.
    """
    creds = load_google_ads_credentials()
    if creds is None:
        return None
    return create_search_console_client(creds, throttler=_throttler)


def _no_sc_creds() -> list[TextContent]:
    """Return a credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)


# ---------------------------------------------------------------------------
# Sites handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_sites_list(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console.sites.list."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.list_sites()
    return _json_result(result)


@api_error_handler
async def handle_sites_get(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console.sites.get."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _require(args, "site_url")
    result = await client.get_site(site_url)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Analytics handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_analytics_query(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console.analytics.query."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_require(args, "site_url"),
        start_date=_require(args, "start_date"),
        end_date=_require(args, "end_date"),
        dimensions=_opt(args, "dimensions"),
        row_limit=_opt(args, "row_limit", 100),
        dimension_filter_groups=_opt(args, "dimension_filter_groups"),
    )
    return _json_result(result)


@api_error_handler
async def handle_analytics_top_queries(
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle search_console.analytics.top_queries."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_require(args, "site_url"),
        start_date=_require(args, "start_date"),
        end_date=_require(args, "end_date"),
        dimensions=["query"],
        row_limit=_opt(args, "row_limit", 100),
    )
    return _json_result(result)


@api_error_handler
async def handle_analytics_top_pages(
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle search_console.analytics.top_pages."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_require(args, "site_url"),
        start_date=_require(args, "start_date"),
        end_date=_require(args, "end_date"),
        dimensions=["page"],
        row_limit=_opt(args, "row_limit", 100),
    )
    return _json_result(result)


@api_error_handler
async def handle_analytics_device_breakdown(
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle search_console.analytics.device_breakdown."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_require(args, "site_url"),
        start_date=_require(args, "start_date"),
        end_date=_require(args, "end_date"),
        dimensions=["device"],
        row_limit=_opt(args, "row_limit", 100),
    )
    return _json_result(result)


@api_error_handler
async def handle_analytics_compare_periods(
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle search_console.analytics.compare_periods."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()

    site_url = _require(args, "site_url")
    dimensions = _opt(args, "dimensions", ["query"])
    row_limit = _opt(args, "row_limit", 100)

    period_1 = await client.query_analytics(
        site_url=site_url,
        start_date=_require(args, "start_date_1"),
        end_date=_require(args, "end_date_1"),
        dimensions=dimensions,
        row_limit=row_limit,
    )
    period_2 = await client.query_analytics(
        site_url=site_url,
        start_date=_require(args, "start_date_2"),
        end_date=_require(args, "end_date_2"),
        dimensions=dimensions,
        row_limit=row_limit,
    )

    return _json_result({"period_1": period_1, "period_2": period_2})


# ---------------------------------------------------------------------------
# Sitemap handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_sitemaps_list(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console.sitemaps.list."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _require(args, "site_url")
    result = await client.list_sitemaps(site_url)
    return _json_result(result)


@api_error_handler
async def handle_sitemaps_submit(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console.sitemaps.submit."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _require(args, "site_url")
    feedpath = _require(args, "feedpath")
    result = await client.submit_sitemap(site_url, feedpath)
    return _json_result(result)


# ---------------------------------------------------------------------------
# URL Inspection handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_url_inspection_inspect(
    args: dict[str, Any],
) -> list[TextContent]:
    """Handle search_console.url_inspection.inspect."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _require(args, "site_url")
    inspection_url = _require(args, "inspection_url")
    result = await client.inspect_url(site_url, inspection_url)
    return _json_result(result)
