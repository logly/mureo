"""Central factory for ad-platform clients used by every live-client opener.

The MCP handlers, the analytics adapters and change import open their
clients here (#863: it sits below ``mureo.mcp``, so none of them loads the
MCP server to reach it).

Per-platform auto-detection: if BYOD data is registered for a platform
(``~/.mureo/byod/manifest.json`` lists it), this factory returns a
CSV-backed ``mureo.byod.clients`` instance. Otherwise it delegates to
``mureo.auth.create_*_client`` for live API access.

Openers MUST go through this factory to pick up BYOD mode automatically.
There is no global ``--byod`` flag; the manifest's existence is the switch.
"""

from __future__ import annotations

from typing import Any

from mureo.byod.clients import ByodGoogleAdsClient, ByodMetaAdsClient

# Bound at import: patch ``mureo.client_factory.byod_has``, not
# ``mureo.byod.runtime.byod_has`` (which only the openers read through).
from mureo.byod.runtime import byod_data_dir, byod_has


def get_google_ads_client(
    creds: Any, customer_id: str, throttler: Any | None = None
) -> Any:
    """Return a Google Ads client (real or BYOD)."""
    if byod_has("google_ads"):
        return ByodGoogleAdsClient(
            data_dir=byod_data_dir() / "google_ads", customer_id=customer_id
        )

    # Startup cost (~0.5 s CPU): mureo.auth is deferred to first client build (#809).
    from mureo.auth import create_google_ads_client as _real

    return _real(creds, customer_id, throttler=throttler)


def get_meta_ads_client(
    creds: Any, account_id: str, throttler: Any | None = None
) -> Any:
    """Return a Meta Ads client (real or BYOD)."""
    if byod_has("meta_ads"):
        return ByodMetaAdsClient(
            data_dir=byod_data_dir() / "meta_ads", account_id=account_id
        )

    # Startup cost (~0.5 s CPU): mureo.auth is deferred to first client build (#809).
    from mureo.auth import create_meta_ads_client as _real

    return _real(creds, account_id, throttler=throttler)
