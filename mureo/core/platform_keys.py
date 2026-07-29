"""The canonical platform key for a plugin platform (Issue #481).

A plugin platform has **one** identifier that every mureo surface joins
on: ``plugin:<distribution>``, where ``<distribution>`` is the pip
distribution name the plugin ships as (``mureo-logly-bridge`` →
``plugin:mureo-logly-bridge``). It is the STATE.json ``platforms`` key,
the ``action_log`` ``platform`` value, the key the reporting dashboard
resolves a label from, and the ``platform`` field
``mureo_analytics_modules_list`` reports.

An analytics module also carries a **registry name** — the name it
registered itself under in the ``mureo.analytics`` entry-point group
(``AnalyticsModule.platform``). That name need not equal the
distribution name and is **not** a key: nothing persists it, and a
lookup by it will not join with STATE.json. Issue #481 is exactly the
bug where the two identifiers were used interchangeably, so state
written under one was read back under the other and silently failed to
join.

This module is the single source of that convention. Everything that
builds, recognises, or takes apart a plugin platform key goes through
it rather than open-coding the ``"plugin:"`` literal.
"""

from __future__ import annotations

PLUGIN_PLATFORM_PREFIX = "plugin:"
"""The prefix that marks a platform key as belonging to a plugin."""


def plugin_platform_key(distribution: str) -> str:
    """Return the canonical platform key for a plugin ``distribution``.

    ``"mureo-logly-bridge"`` → ``"plugin:mureo-logly-bridge"``.

    Idempotent: an already-canonical key passed back in is returned
    unchanged rather than double-prefixed, so a caller that cannot tell
    whether it holds a distribution name or a key stays safe.
    """
    # Defensive only — every current call site feeds this a bare
    # distribution name (from ``plugin_source``, i.e. the entry point's
    # own distribution), and a module may not name itself ``plugin:*``.
    if is_plugin_platform_key(distribution):
        return distribution
    return f"{PLUGIN_PLATFORM_PREFIX}{distribution}"


def is_plugin_platform_key(key: str) -> bool:
    """Return ``True`` when ``key`` is a canonical plugin platform key.

    A bare ``"plugin:"`` carries no distribution, so it is **not** a
    usable key — the dashboard already falls back to rendering it raw.
    Built-in keys (``google_ads`` / ``meta_ads`` / ``tiktok_ads`` / …)
    and analytics registry names are ``False``.
    """
    return key.startswith(PLUGIN_PLATFORM_PREFIX) and len(key) > len(
        PLUGIN_PLATFORM_PREFIX
    )


def plugin_distribution(key: str) -> str:
    """Return the distribution embedded in a plugin platform ``key``.

    ``"plugin:mureo-logly-bridge"`` → ``"mureo-logly-bridge"``. Any key
    that is not a plugin platform key (a built-in, a hosted connector, a
    bare ``"plugin:"``) yields ``""`` — the caller decides what to do
    with a key that carries no distribution.
    """
    if not is_plugin_platform_key(key):
        return ""
    return key[len(PLUGIN_PLATFORM_PREFIX) :]


__all__ = [
    "PLUGIN_PLATFORM_PREFIX",
    "is_plugin_platform_key",
    "plugin_distribution",
    "plugin_platform_key",
]
