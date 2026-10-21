"""Google Ads client and credential resolution for the MCP handlers.

Every Google Ads tool funnels through :func:`_get_client`: it picks the
credentials (an active credential source, BYOD mode, or the credentials
file), binds the effective ``customer_id`` to the workspace allow-list, and
builds the client off the event loop. Split out of
:mod:`mureo.mcp._handlers_google_ads`, which re-exports these names so the
sibling handler modules keep importing them from there.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

    from mureo.core.credential_source import GoogleCredentialSource

from mureo.auth import create_google_ads_client, load_google_ads_credentials
from mureo.byod.runtime import byod_has
from mureo.client_factory import get_google_ads_client
from mureo.core.account_scope import resolve_customer_id
from mureo.core.credential_source import call_source, current_google_source
from mureo.mcp._helpers import _no_creds_result, _opt
from mureo.throttle import GOOGLE_ADS_THROTTLE, Throttler

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variables "
    "(GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, "
    "GOOGLE_ADS_REFRESH_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)

_throttler = Throttler(GOOGLE_ADS_THROTTLE)


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials and create a client.

    Resolution order for customer_id:
    1. Explicit customer_id in tool arguments
    2. creds.customer_id from credentials.json
    3. creds.login_customer_id as fallback (legacy credentials without
       a separate customer_id field)

    In BYOD mode (``~/.mureo/byod/manifest.json`` registers google_ads), no
    credentials are needed (CSV-backed client); a credential source wins (#821).

    Returns None on auth error (real mode only).
    """
    google = current_google_source()
    if google is None and byod_has("google_ads"):
        customer_id = _opt(arguments, "customer_id") or "byod"
        return get_google_ads_client(
            creds=None, customer_id=customer_id, throttler=_throttler
        )

    creds = (
        load_google_ads_credentials()
        if google is None
        else call_source("google", google.load_credentials)
    )
    if creds is None:
        return None

    # getattr, not attribute access: the default must not be evaluated
    # eagerly against credential objects that lack the field (the old
    # ``or``-chain short-circuited when an explicit id was passed).
    customer_id = resolve_customer_id(
        _opt(arguments, "customer_id"),
        getattr(creds, "customer_id", None)
        or getattr(creds, "login_customer_id", None),
    )
    if not str(customer_id).replace("-", "").isdigit():
        raise ValueError(
            f"Invalid customer_id format: {customer_id} (must be numeric, hyphens allowed)"
        )

    # Off the loop: the SDK import (~1 s CPU, #809) and a token refresh (#821)
    return await asyncio.to_thread(_build_client, google, creds, customer_id)


def _build_client(
    google: GoogleCredentialSource | None, creds: Any, customer_id: str
) -> Any:
    """Build the client; runs on a worker thread.

    ``oauth_credentials`` is passed only when a source supplies one, so the
    no-source call keeps the factory's original (narrower) signature.
    """
    kwargs: dict[str, Any] = {"throttler": _throttler}
    if google is not None:
        oauth = call_source("google", google.oauth_credentials, creds)
        if oauth is not None:
            kwargs["oauth_credentials"] = oauth
    return create_google_ads_client(creds, customer_id, **kwargs)


def _no_google_creds() -> list[TextContent]:
    """Return a Google Ads credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)
