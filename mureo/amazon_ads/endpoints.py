"""Region → endpoint URL and credential → request headers.

Pure, no network. Source of truth = Phase 0 verified facts
(2026-05-18, official Amazon Ads MCP docs):

  NA  https://advertising-ai.amazon.com/mcp
  EU  https://advertising-ai-eu.amazon.com/mcp
  FE  https://advertising-ai-fe.amazon.com/mcp

Auth is header-based: ``Authorization: Bearer <access_token>`` +
``Amazon-Ads-ClientId``. Fixed account context adds the FIXED marker
and >=1 account-id header; with no id we deliberately fall back to the
Dynamic header set rather than emit a FIXED config Amazon would reject.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.auth import AmazonAdsCredentials

_REGION_URL = {
    "na": "https://advertising-ai.amazon.com/mcp",
    "eu": "https://advertising-ai-eu.amazon.com/mcp",
    "fe": "https://advertising-ai-fe.amazon.com/mcp",
}

_ACCEPT = "application/json, text/event-stream"


def endpoint_url(region: str) -> str:
    """Return the streamable-HTTP MCP endpoint for ``region``.

    Raises:
        ValueError: region is not one of ``na`` / ``eu`` / ``fe``.
    """
    try:
        return _REGION_URL[region]
    except KeyError:
        raise ValueError(
            f"unknown Amazon Ads region: {region!r} (expected na|eu|fe)"
        ) from None


def request_headers(creds: AmazonAdsCredentials) -> dict[str, str]:
    """Build the per-request headers for the Amazon hosted MCP."""
    headers: dict[str, str] = {
        "Authorization": f"Bearer {creds.access_token}",
        "Amazon-Ads-ClientId": creds.client_id,
        "Accept": _ACCEPT,
    }
    if creds.account_mode == "fixed":
        fixed: dict[str, str] = {}
        if creds.profile_id:
            fixed["Amazon-Advertising-API-Scope"] = creds.profile_id
        if creds.account_id:
            fixed["Amazon-Ads-AccountID"] = creds.account_id
        if creds.manager_account_id:
            fixed["Amazon-Ads-Manager-AccountID"] = creds.manager_account_id
        # Only assert FIXED when at least one account id is present —
        # Amazon rejects FIXED with no scope/account header.
        if fixed:
            headers["Amazon-Ads-AI-Account-Selection-Mode"] = "FIXED"
            headers.update(fixed)
    return headers
