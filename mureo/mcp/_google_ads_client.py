"""Google Ads client and credential resolution for the MCP handlers.

Every Google Ads tool funnels through :func:`_get_client`, which runs the
shared opener :func:`mureo.client_factory.open_google_ads_client` (an
active credential source, BYOD mode, or the credentials file; workspace
scoping; the shared rate limiter) off the event loop (#875). Split out of
:mod:`mureo.mcp._handlers_google_ads`, which re-exports these names so the
sibling handler modules keep importing them from there.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.client_factory import NoCredentialsError, open_google_ads_client
from mureo.mcp._helpers import _no_creds_result, _opt

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variables "
    "(GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, "
    "GOOGLE_ADS_REFRESH_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials and create a client.

    Resolution order for customer_id:
    1. Explicit customer_id in tool arguments
    2. creds.customer_id from credentials.json
    3. creds.login_customer_id as fallback (legacy credentials without
       a separate customer_id field)

    In BYOD mode (``~/.mureo/byod/manifest.json`` registers google_ads), no
    credentials are needed (CSV-backed client); a credential source wins (#821).

    Returns None when no credentials are configured; a workspace-scope
    refusal or a non-numeric id raises ``ValueError``.
    """
    # Off the loop: the SDK import (~1 s CPU, #809) and a token refresh (#821)
    try:
        client, _ = await asyncio.to_thread(
            open_google_ads_client, _opt(arguments, "customer_id")
        )
    except NoCredentialsError:
        return None
    return client


def _no_google_creds() -> list[TextContent]:
    """Return a Google Ads credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)
