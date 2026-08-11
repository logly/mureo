"""Built-in change feeds for mureo-native platforms (#545).

One feed today: Google Ads. Meta Ads, Yahoo, LINE, SmartNews, Amazon and
TikTok are deliberately absent — see ``docs/change-import.md`` for what each
platform's feed is and why mureo cannot read it yet. A missing feed is
reported as ``change_import_unavailable_for_<platform>``, never as "no
changes", because the absence of a feed is not evidence that nothing
happened.
"""

from __future__ import annotations


def register_builtin_change_feeds() -> None:
    """Register every built-in change feed on the default registry.

    Called once from :func:`mureo.change_import.registry.default_change_feed_registry`.
    Imports are local so registry import stays cheap and free of auth side
    effects — the live client is opened per call, not here.
    """
    from mureo.change_import.builtin.google_ads import GoogleAdsChangeFeed
    from mureo.change_import.registry import register_change_feed

    register_change_feed(GoogleAdsChangeFeed())


__all__ = ["register_builtin_change_feeds"]
