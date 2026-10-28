"""Built-in change feeds for mureo-native platforms (#545).

One feed today: Google Ads. Meta Ads, Yahoo, LINE, SmartNews, Amazon and
TikTok are deliberately absent — see ``docs/change-import.md`` for what each
platform's feed is and why mureo cannot read it yet. A missing feed is
reported as ``change_import_unavailable_for_<platform>``, never as "no
changes", because the absence of a feed is not evidence that nothing
happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed

if TYPE_CHECKING:
    from mureo.change_import.protocol import ChangeFeedProvider


def builtin_change_feeds() -> tuple[ChangeFeedProvider, ...]:
    """One fresh instance of every built-in change feed.

    Called from :func:`mureo.change_import.registry.default_change_feed_registry`,
    which registers them; this package does not import the registry, so the
    dependency runs one way (#879). Building a feed has no auth side effects
    — the live client is opened per call, not here.
    """
    return (GoogleAdsChangeFeed(),)


__all__ = ["builtin_change_feeds"]
