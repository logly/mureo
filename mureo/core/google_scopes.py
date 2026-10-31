"""The scopes mureo's Google OAuth requests, and what Google granted back.

One authorization serves Google Ads, Search Console and GA4 read access.
The consent screen lets the user untick any of them, so the granted set is
read back from the credentials and checked before the token is stored.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "ANALYTICS_READONLY_SCOPE",
    "GOOGLE_ADS_SCOPE",
    "GOOGLE_SCOPES",
    "SEARCH_CONSOLE_SCOPE",
    "check_granted_scopes",
    "granted_scopes",
]

logger = logging.getLogger(__name__)

GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters"
# GA4 read-only, so the same authorization can serve ga4-official as an ADC file
ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GOOGLE_SCOPES: tuple[str, ...] = (
    GOOGLE_ADS_SCOPE,
    SEARCH_CONSOLE_SCOPE,
    ANALYTICS_READONLY_SCOPE,
)


def granted_scopes(credentials: Any) -> tuple[str, ...]:
    """The scopes Google granted, as reported on ``credentials``.

    google-auth fills ``granted_scopes`` from the token response's
    ``scope``, which is the authoritative list when the consent screen lets
    the user untick scopes. Anything else (absent, not a list) reads as
    nothing granted.
    """
    raw = getattr(credentials, "granted_scopes", None)
    if isinstance(raw, str):
        raw = raw.split()
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(scope for scope in raw if isinstance(scope, str))


def check_granted_scopes(granted: tuple[str, ...]) -> None:
    """Fail when Google Ads access was not granted; log other omissions.

    The Google Ads scope is what the stored refresh token exists for, so a
    grant without it must fail at setup rather than at the first API call.
    Search Console and GA4 read access are optional additions: their absence
    is logged (scope URLs only). An empty ``granted`` means the response did
    not report the set, not that none was granted.

    Raises:
        RuntimeError: ``granted`` is reported and lacks the Google Ads scope.
    """
    if not granted:
        return
    if GOOGLE_ADS_SCOPE not in granted:
        raise RuntimeError(
            "Google did not grant the Google Ads scope. Re-run the "
            "authorization and keep every scope ticked."
        )
    missing = [scope for scope in GOOGLE_SCOPES if scope not in granted]
    if missing:
        logger.warning("Google did not grant: %s", ", ".join(missing))
