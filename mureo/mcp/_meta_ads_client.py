"""Meta Ads client and credential resolution for the MCP handlers.

Every Meta Ads tool funnels through :func:`_get_client`, which runs the
shared opener :func:`mureo.client_factory.open_meta_ads_client` (an active
credential source, BYOD mode, or the credentials file; workspace scoping;
a file-sourced token refresh; the shared rate limiter) (#875).
:func:`_entity_result` marks entity reads served from a BYOD import. Split
out of :mod:`mureo.mcp._handlers_meta_ads`, which re-exports these names so
the sibling handler modules and existing callers keep importing them from
there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.byod.runtime import byod_freshness, byod_has
from mureo.client_factory import NoCredentialsError, open_meta_ads_client
from mureo.core.credential_source import current_meta_source
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    register_client_for_cleanup,
)

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variable "
    "(META_ADS_ACCESS_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Open a Meta Ads client through the shared opener and register it for cleanup.

    Falls back to account_id from credentials.json if not provided
    in the tool arguments; a bare id is prefixed ``act_``.

    In BYOD mode (``~/.mureo/byod/manifest.json`` registers meta_ads), no
    credentials are needed (CSV-backed client); a credential source wins and
    its token is used as-is, without a refresh (#821).

    Returns None when no credentials are configured; a workspace-scope
    refusal raises ``AccountIdRefused`` (a ``ValueError``).
    """
    try:
        client, _ = await open_meta_ads_client(_opt(arguments, "account_id"))
    except NoCredentialsError:
        return None
    # Close the client's persistent httpx.AsyncClient after the handler returns
    # (see register_client_for_cleanup) so the native server does not leak
    # keep-alive sockets across tool calls.
    register_client_for_cleanup(client)
    return client


def _no_meta_creds() -> list[TextContent]:
    """Return a Meta Ads credentials-not-found error."""
    return _no_creds_result(_NO_CREDS_MSG)


def _entity_result(payload: Any) -> list[TextContent]:
    """JSON result for an entity read, marked when it came from BYOD (#468).

    In BYOD mode these tools read the CSVs ``mureo byod import`` wrote, not
    the Graph API — so what they report is the state at import time. The
    response is wrapped as ``{"source": "byod_import", "as_of": <imported_at>,
    "data": <rows>}`` so the agent can see that its picture of delivery status
    is a snapshot and may have moved since. Row data is untouched inside
    ``data``.

    A live response is returned exactly as before (no wrapper): the ABSENCE of
    a marker means live. Wrapping live responses too would be more explicit,
    but would change the shape every existing caller, skill, and test expects
    — not worth it for information the absence already conveys.

    An active credential source's ``meta_ads`` entry wins over BYOD mode
    (#821), so its responses are live and carry no marker.
    """
    if current_meta_source() is not None:
        return _json_result(payload)
    marker = byod_freshness("meta_ads") if byod_has("meta_ads") else None
    if marker is None:
        return _json_result(payload)
    return _json_result({**marker, "data": payload})
