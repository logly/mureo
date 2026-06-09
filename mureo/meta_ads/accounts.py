"""Accessible-account discovery for the Meta Marketing API.

Public surface for tooling that needs to enumerate the Meta ad
accounts a given access token can reach.

The function was previously defined inside :mod:`mureo.auth_setup`
for the interactive OAuth wizard's account-picker step. Promoting it
to ``mureo.meta_ads.accounts`` exposes the same logic as a stable
public API so configure-UI consumers (in-tree and third-party) can
build account pickers without reaching into the wizard's internal
module.

The original import path ``mureo.auth_setup.list_meta_ad_accounts``
remains valid via a thin re-export there — existing callers do not
need to change.

The returned shape stays ``list[dict[str, Any]]`` (the same dict
shape the auth-setup wizard has always produced). A future minor
release MAY introduce a frozen-dataclass parallel return type; the
dict shape will remain supported for at least one minor.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Same surface as ``mureo.auth_setup`` — mirrored here so the public
# module does not depend on private constants in the auth-setup
# module. Keep in sync if either side bumps the Graph API version.
_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_HTTP_TIMEOUT = 30.0

# Largest page size Graph API will accept without truncation for the
# ``adaccounts`` edge. Defaults to 25 when omitted — too small for any
# Business Manager with more than a handful of accounts.
_PAGE_SIZE = 100

# Defensive upper bound on the cursor walk. 50 pages × 100 = 5000 ad
# accounts — well past anything seen in practice. Caps a buggy Graph
# response that keeps returning a ``paging.next`` cursor so the
# configure UI never spins forever.
_MAX_PAGES = 50

# Host pinning for ``paging.next`` URLs. Graph echoes the URL back to
# us in the response body — refusing to follow anything other than the
# Graph API host stops a tampered response (broken TLS pinning, proxy
# mis-route, etc.) from exfiltrating the access token (which travels in
# the cursor URL's query string from page 2 onward).
_GRAPH_HOST = "graph.facebook.com"


def _is_safe_graph_url(url: str) -> bool:
    """Return True iff ``url`` is an https URL pointing at the Graph host."""

    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == _GRAPH_HOST


def _redact(message: str, secret: str) -> str:
    """Replace ``secret`` in ``message`` with a fixed token marker.

    Used to scrub access tokens out of error messages before they reach
    operator logs or UI surfaces. The original exception chain is broken
    with ``raise ... from None`` separately — see the raise site.
    """

    if not secret:
        return message
    return message.replace(secret, "***REDACTED***")


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Retrieve the list of Meta ad accounts the access token can reach.

    Calls ``GET /me/adaccounts`` on the Graph API and walks the
    ``paging.next`` cursor until exhausted so every account under a
    Business Manager is returned, not just the first 25. Pages are
    concatenated in cursor order (== Graph's natural order) so the
    configure-UI dropdown ranks accounts consistently across runs.

    Args:
        access_token: Meta Ads access token (System User or User token).

    Returns:
        List of ad account dicts (``id``, ``name``, ``account_status``).

    Raises:
        RuntimeError: When the Graph API call fails (network error or
            non-2xx response).
    """
    accounts: list[dict[str, Any]] = []
    next_url: str | None = f"{_META_GRAPH_API_BASE}/me/adaccounts"
    # ``params`` is only sent on the first request — subsequent
    # ``paging.next`` URLs already carry every query parameter Graph
    # needs (including ``access_token`` and ``after`` cursor), so
    # resending them would corrupt the cursor.
    first_request_params: dict[str, Any] | None = {
        "fields": "id,name,account_status",
        "limit": _PAGE_SIZE,
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for _ in range(_MAX_PAGES):
                if not next_url:
                    break
                if not _is_safe_graph_url(next_url):
                    logger.warning(
                        "Refusing to follow non-Graph paging.next URL; "
                        "truncating Meta ad-account list."
                    )
                    break
                response = await client.get(next_url, params=first_request_params)
                response.raise_for_status()
                payload = response.json()
                accounts.extend(payload.get("data", []) or [])
                next_url = (payload.get("paging") or {}).get("next")
                first_request_params = None
            else:
                # Loop exhausted the cap — log so the gap is visible in
                # operator logs even though the UI sees a finite list.
                logger.warning(
                    "Meta ad-account pagination hit the %d-page cap; some "
                    "accounts may be missing from the configure UI.",
                    _MAX_PAGES,
                )
        return accounts
    except Exception as exc:
        # Scrub the access token before it lands in operator logs or UI.
        # From page 2 onward the token lives in ``next_url`` itself, so
        # an HTTPStatusError from httpx (which embeds the request URL in
        # its ``__str__``) would otherwise leak it verbatim.
        scrubbed = _redact(str(exc), access_token)
        # ``from None`` breaks the exception chain so the original
        # exception's ``__cause__`` (which still carries the unscrubbed
        # URL) is not printed by default traceback formatting.
        raise RuntimeError(f"Failed to retrieve ad account list: {scrubbed}") from None


__all__ = ["list_meta_ad_accounts"]
