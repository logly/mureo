"""Meta Ads client and credential resolution for the MCP handlers.

Every Meta Ads tool funnels through :func:`_get_client`: it picks the
credentials (an active credential source, BYOD mode, or the credentials
file), binds the effective ``account_id`` to the workspace allow-list,
refreshes a file-sourced token when needed, and builds the client.
:func:`_entity_result` marks entity reads served from a BYOD import. Split
out of :mod:`mureo.mcp._handlers_meta_ads`, which re-exports these names so
the sibling handler modules and existing callers keep importing them from
there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.types import TextContent

from mureo.auth import (
    create_meta_ads_client,
    load_meta_ads_credentials,
    refresh_meta_token_if_needed,
)
from mureo.byod.runtime import byod_freshness, byod_has
from mureo.core.runtime_context import runtime_meta_account_ids
from mureo.mcp._client_factory import get_meta_ads_client
from mureo.mcp._helpers import (
    _json_result,
    _no_creds_result,
    _opt,
    register_client_for_cleanup,
)
from mureo.mcp.credential_source import call_source, current_meta_source
from mureo.throttle import META_ADS_THROTTLE, Throttler

_NO_CREDS_MSG = (
    "Credentials not found. Set environment variable "
    "(META_ADS_ACCESS_TOKEN) "
    "or configure ~/.mureo/credentials.json."
)

_throttler = Throttler(META_ADS_THROTTLE)


def _normalize_meta_account_id(value: str) -> str:
    """Strip the ``act_`` prefix so membership checks are prefix-insensitive."""
    return value[4:] if value.startswith("act_") else value


def _canonical_meta_account_id(value: str) -> str:
    """Ensure the ``act_`` prefix the Meta client factory requires."""
    return value if value.startswith("act_") else f"act_{value}"


def _resolve_account_id(requested: str | None, default: str | None) -> str:
    """Resolve and workspace-enforce the Meta ``account_id`` (#411).

    Every Meta tool funnels through ``_get_client``, which takes
    ``account_id`` as a free caller argument while the (possibly shared)
    credentials can reach every managed ad account. This binds the
    EFFECTIVE id — explicit argument or credentials default alike — to the
    active client's allow-list, mirroring Search Console's ``site_url``
    enforcement (#375):

    - **Not tenant-scoped** (:func:`runtime_meta_account_ids` → ``None``):
      unchanged — argument wins, credentials default second, missing both
      is an error.
    - **Tenant-scoped**: an out-of-set value is refused (fail-closed,
      prefix-insensitive); no usable value resolves to the single
      configured account, or is refused when several are configured
      (ambiguous) or none are (fail-fast).
    """
    allowed = runtime_meta_account_ids()
    if allowed is None:
        account_id = requested or default
        if not account_id:
            raise ValueError(
                "account_id is required. Provide it as a parameter or "
                "configure it in ~/.mureo/credentials.json via mureo auth "
                "setup."
            )
        return str(account_id)
    if not allowed:
        raise ValueError(
            "Meta Ads is not configured for this client. Configure the "
            "client's ad account before querying it."
        )
    normalized_allowed = {_normalize_meta_account_id(entry) for entry in allowed}
    if requested:
        if _normalize_meta_account_id(str(requested)) not in normalized_allowed:
            raise ValueError(
                f"account_id {requested!r} is not one of this client's "
                "configured ad accounts and was refused."
            )
        return _canonical_meta_account_id(str(requested))
    if default and _normalize_meta_account_id(str(default)) in normalized_allowed:
        return _canonical_meta_account_id(str(default))
    if len(allowed) == 1:
        return _canonical_meta_account_id(next(iter(allowed)))
    raise ValueError(
        "account_id is required: this client has multiple configured ad "
        "accounts — pass one of them explicitly."
    )


async def _get_client(arguments: dict[str, Any]) -> Any:
    """Load credentials, refresh token if needed, and create a client.

    Falls back to account_id from credentials.json if not provided
    in the tool arguments.

    In BYOD mode, returns a CSV-backed client without any credentials.

    An active credential source's ``meta_ads`` entry (#821) wins over BYOD
    and the file, and its token is used as-is: the source owns the token
    lifecycle, so no refresh is attempted.

    Returns None on auth error (real mode only).
    """
    meta = current_meta_source()
    if meta is None and byod_has("meta_ads"):
        account_id = _opt(arguments, "account_id") or "act_byod"
        client = get_meta_ads_client(
            creds=None, account_id=account_id, throttler=_throttler
        )
        register_client_for_cleanup(client)
        return client

    creds = (
        call_source("meta_ads", meta.load_credentials)
        if meta is not None
        else load_meta_ads_credentials()
    )
    if creds is None:
        return None

    # getattr, not attribute access: the default must not be evaluated
    # eagerly against credential objects that lack the field (the old
    # ``or``-chain short-circuited when an explicit id was passed).
    account_id = _resolve_account_id(
        _opt(arguments, "account_id"), getattr(creds, "account_id", None)
    )
    if not str(account_id).startswith("act_"):
        raise ValueError(
            f"Invalid account_id format: {account_id} (must start with 'act_')"
        )

    if meta is None:
        creds = await refresh_meta_token_if_needed(creds)
    client = create_meta_ads_client(creds, account_id, throttler=_throttler)
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
