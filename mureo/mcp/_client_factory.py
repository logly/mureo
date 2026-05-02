"""Central factory for ad-platform clients used by MCP handlers.

Per-platform auto-detection: if BYOD data is registered for a platform
(``~/.mureo/byod/manifest.json`` lists it), this factory returns a
CSV-backed ``mureo.byod.clients`` instance. Otherwise it delegates to
``mureo.auth.create_*_client`` for live API access.

Handlers MUST go through this factory to pick up BYOD mode automatically.
There is no global ``--byod`` flag; the manifest's existence is the switch.
"""

from __future__ import annotations

from typing import Any


def get_google_ads_client(
    creds: Any, customer_id: str, throttler: Any | None = None
) -> Any:
    """Return a Google Ads client (real or BYOD)."""
    from mureo.byod.runtime import byod_data_dir, byod_has

    if byod_has("google_ads"):
        from mureo.byod.clients import ByodGoogleAdsClient

        return ByodGoogleAdsClient(
            data_dir=byod_data_dir() / "google_ads", customer_id=customer_id
        )

    from mureo.auth import create_google_ads_client as _real

    return _real(creds, customer_id, throttler=throttler)


def get_meta_ads_client(
    creds: Any, account_id: str, throttler: Any | None = None
) -> Any:
    """Return a Meta Ads client (real or BYOD)."""
    from mureo.byod.runtime import byod_data_dir, byod_has

    if byod_has("meta_ads"):
        from mureo.byod.clients import ByodMetaAdsClient

        return ByodMetaAdsClient(
            data_dir=byod_data_dir() / "meta_ads", account_id=account_id
        )

    from mureo.auth import create_meta_ads_client as _real

    return _real(creds, account_id, throttler=throttler)


def get_search_console_client(creds: Any, throttler: Any | None = None) -> Any:
    """Return a Search Console client (Live API only).

    BYOD path was removed in Phase 1 of the BYOD redesign; SC is reached
    only via the existing OAuth credentials.
    """
    from mureo.auth import create_search_console_client as _real

    return _real(creds, throttler=throttler)
