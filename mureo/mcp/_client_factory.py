"""Central factory for ad-platform clients used by MCP handlers.

In real mode this delegates to ``mureo.auth.create_*_client``.
In demo mode (``python -m mureo.mcp --demo``) it returns CSV-backed
``mureo.demo.clients.*`` instances so no network calls are made.

Handlers MUST go through this factory to pick up demo mode automatically.
"""

from __future__ import annotations

from typing import Any

_demo_mode: bool = False


def set_demo_mode(enabled: bool) -> None:
    """Enable or disable demo mode globally for this process.

    Called by ``mureo/mcp/server.py`` at startup when ``--demo`` is present.
    """
    global _demo_mode
    _demo_mode = bool(enabled)


def is_demo_mode() -> bool:
    return _demo_mode


def get_google_ads_client(
    creds: Any, customer_id: str, throttler: Any | None = None
) -> Any:
    """Return a Google Ads client (real or demo)."""
    if _demo_mode:
        from mureo.demo.clients import DemoGoogleAdsClient
        from mureo.demo.installer import demo_data_dir

        return DemoGoogleAdsClient(
            data_dir=demo_data_dir() / "google_ads", customer_id=customer_id
        )

    from mureo.auth import create_google_ads_client as _real

    return _real(creds, customer_id, throttler=throttler)


def get_meta_ads_client(
    creds: Any, account_id: str, throttler: Any | None = None
) -> Any:
    """Return a Meta Ads client (real or demo)."""
    if _demo_mode:
        from mureo.demo.clients import DemoMetaAdsClient
        from mureo.demo.installer import demo_data_dir

        return DemoMetaAdsClient(
            data_dir=demo_data_dir() / "meta_ads", account_id=account_id
        )

    from mureo.auth import create_meta_ads_client as _real

    return _real(creds, account_id, throttler=throttler)


def get_search_console_client(creds: Any, throttler: Any | None = None) -> Any:
    """Return a Search Console client (real or demo)."""
    if _demo_mode:
        from mureo.demo.clients import DemoSearchConsoleClient
        from mureo.demo.installer import demo_data_dir

        return DemoSearchConsoleClient(data_dir=demo_data_dir() / "search_console")

    from mureo.auth import create_search_console_client as _real

    return _real(creds, throttler=throttler)
