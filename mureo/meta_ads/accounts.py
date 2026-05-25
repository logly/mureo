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

import httpx

logger = logging.getLogger(__name__)

# Same surface as ``mureo.auth_setup`` — mirrored here so the public
# module does not depend on private constants in the auth-setup
# module. Keep in sync if either side bumps the Graph API version.
_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_HTTP_TIMEOUT = 30.0


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Retrieve the list of Meta ad accounts the access token can reach.

    Calls ``GET /me/adaccounts`` on the Graph API. Returns the raw
    ``data`` array as-is so callers can pick the fields they need
    without an intermediate normalisation step.

    Args:
        access_token: Meta Ads access token (System User or User token).

    Returns:
        List of ad account dicts (``id``, ``name``, ``account_status``).

    Raises:
        RuntimeError: When the Graph API call fails (network error or
            non-2xx response).
    """
    params = {
        "fields": "id,name,account_status",
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/me/adaccounts",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])  # type: ignore[no-any-return]
    except Exception as exc:
        raise RuntimeError(f"Failed to retrieve ad account list: {exc}") from exc


__all__ = ["list_meta_ad_accounts"]
