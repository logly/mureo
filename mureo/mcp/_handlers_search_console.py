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
from mureo.core.runtime_context import runtime_search_console_sites
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    _require,
    api_error_handler,
    register_client_for_cleanup,
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
    client = create_search_console_client(creds, throttler=_throttler)
    # Close the persistent httpx.AsyncClient after the handler returns so the
    # native server does not leak keep-alive sockets across tool calls.
    register_client_for_cleanup(client)
    return client


def _no_sc_creds() -> list[TextContent]:
    """Return a credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)


def _resolve_site_url(args: dict[str, Any]) -> str:
    """Resolve and tenant-enforce the ``site_url`` for a Search Console call.

    Search Console reuses the operator-shared Google OAuth, so in a
    multi-account (agency) deployment the shared identity can reach EVERY
    client's property — and every Search Console tool takes ``site_url`` as a
    free argument. Left unchecked, one client's workspace can query a sibling
    client's property (cross-client leak). This binds ``site_url`` to the
    active client the same way Google Ads binds ``customer_id`` from
    per-client config.

    - **Not tenant-scoped** (:func:`runtime_search_console_sites` → ``None`` —
      standalone OSS, no multi-account backend): unchanged. ``site_url`` is a
      required caller argument, used verbatim.
    - **Tenant-scoped**: the value MUST be one of the active client's
      configured properties. An out-of-scope value is refused (fail-closed);
      an omitted value resolves to the single configured site, or is refused
      when the client has several (ambiguous) or none configured (fail-fast).
    """
    allowed = runtime_search_console_sites()
    if allowed is None:
        # Standalone: unchanged. Annotate the Any from _require so the
        # str-typed return is honest to mypy (no-any-return).
        site_url: str = _require(args, "site_url")
        return site_url
    if not allowed:
        raise ValueError(
            "Search Console is not configured for this client. Configure the "
            "client's Search Console property before querying it."
        )
    requested = _opt(args, "site_url")
    if not isinstance(requested, str) or not requested.strip():
        if len(allowed) == 1:
            return next(iter(allowed))
        raise ValueError(
            "site_url is required: this client has multiple configured Search "
            "Console properties — pass one of them explicitly. Use "
            "search_console_sites_list to see the allowed properties."
        )
    requested = requested.strip()
    if requested not in allowed:
        raise ValueError(
            f"site_url {requested!r} is not one of this client's configured "
            "Search Console properties and was refused. Use "
            "search_console_sites_list to see the allowed properties."
        )
    return requested


def _filter_sites_to_allowed(
    sites: Any, allowed: frozenset[str]
) -> list[dict[str, Any]]:
    """Keep only the ``siteEntry`` rows whose ``siteUrl`` is tenant-allowed.

    ``search_console_sites_list`` returns EVERY property the shared OAuth can
    access — including sibling clients' — so when Search Console is
    tenant-scoped the list is filtered to the active client's properties
    before it ever reaches the agent. An empty ``allowed`` set yields ``[]``
    (client scoped but no site configured). Defensive against a malformed
    payload (non-list / non-dict rows / missing ``siteUrl``).
    """
    if not isinstance(sites, list):
        return []
    return [
        row
        for row in sites
        if isinstance(row, dict)
        and isinstance(row.get("siteUrl"), str)
        and row["siteUrl"].strip() in allowed
    ]


# ---------------------------------------------------------------------------
# Sites handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_sites_list(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console_sites_list."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.list_sites()
    # Tenant scoping: never expose sibling clients' properties. When the
    # active client is scoped, filter the shared-OAuth site list down to its
    # own properties before returning it to the agent.
    allowed = runtime_search_console_sites()
    if allowed is not None:
        result = _filter_sites_to_allowed(result, allowed)
    return _json_result(result)


@api_error_handler
async def handle_sites_get(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console_sites_get."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _resolve_site_url(args)
    result = await client.get_site(site_url)
    return _json_result(result)


# ---------------------------------------------------------------------------
# Analytics handlers
# ---------------------------------------------------------------------------


@api_error_handler
async def handle_analytics_query(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console_analytics_query."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_resolve_site_url(args),
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
    """Handle search_console_analytics_top_queries."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_resolve_site_url(args),
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
    """Handle search_console_analytics_top_pages."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_resolve_site_url(args),
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
    """Handle search_console_analytics_device_breakdown."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    result = await client.query_analytics(
        site_url=_resolve_site_url(args),
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
    """Handle search_console_analytics_compare_periods."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()

    site_url = _resolve_site_url(args)
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
    """Handle search_console_sitemaps_list."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _resolve_site_url(args)
    result = await client.list_sitemaps(site_url)
    return _json_result(result)


@api_error_handler
async def handle_sitemaps_submit(args: dict[str, Any]) -> list[TextContent]:
    """Handle search_console_sitemaps_submit."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _resolve_site_url(args)
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
    """Handle search_console_url_inspection_inspect."""
    client = await _get_client(args)
    if client is None:
        return _no_sc_creds()
    site_url = _resolve_site_url(args)
    inspection_url = _require(args, "inspection_url")
    result = await client.inspect_url(site_url, inspection_url)
    return _json_result(result)
