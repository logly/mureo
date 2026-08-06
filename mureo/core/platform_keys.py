"""The canonical platform key for a plugin platform (Issues #481, #537).

A plugin platform has **one** identifier that every mureo surface joins
on: ``plugin:<distribution>:<provider>``, where ``<distribution>`` is the
pip distribution the plugin ships as and ``<provider>`` is the
entry-point name that distribution registered *this* platform under
(``mureo-lineyahoo-bridge`` + ``yahoo_ads`` →
``plugin:mureo-lineyahoo-bridge:yahoo_ads``). It is the STATE.json
``platforms`` key, the ``action_log`` ``platform`` value, the key the
reporting dashboard resolves a label from, and the ``platform`` field
``mureo_analytics_modules_list`` reports.

Why the provider is part of the key (#537)
------------------------------------------
#481 keyed on the distribution alone, which assumes a distribution ships
exactly one platform. It does not have to:
``mureo-lineyahoo-bridge`` registers ``line_ads``, ``yahoo_ads`` and
``yahoo_ads_display``. Under the distribution-only key all three
canonicalise to ``plugin:mureo-lineyahoo-bridge``, so a writer that
canonicalises correctly files three platforms' spend under one entry —
one platform's numbers recorded as another's — and the key cannot be
resolved back to which platform it meant.

The format never depends on how many platforms a distribution *happens*
to ship. Deriving the shape from that count would silently change the
first platform's key the day a second one is added, breaking joins for
data already written under it. :func:`plugin_platform_key` therefore
takes the two names and nothing else — it has no way to consult a
registry, by construction.

Why ``:`` is a safe separator
-----------------------------
Not because the two halves are forbidden from containing one — one of
them is not. Safety rests on where each half comes from, plus the parse:

- The **distribution** half is never a value a plugin supplies. It is
  always the installing metadata's own distribution name (``ep.dist``,
  reaching this module via ``plugin_source`` /
  ``ProviderEntry.source_distribution``), and a pip distribution name
  cannot contain ``:`` — PEP 503 / PEP 508 allow only ASCII letters,
  digits, ``-``, ``_`` and ``.`` (normalising to
  ``[a-z0-9]+([-_.][a-z0-9]+)*``). So the first segment can never forge
  a separator.
- The **provider** half is validated on one path and unvalidated on the
  other. For ``mureo.providers``, mureo uses the provider class's own
  ``name``, pinned to ``^[a-z][a-z0-9_]*$`` by
  :func:`mureo.core.providers.base.validate_provider_name`. For
  ``mureo.analytics`` it is ``AnalyticsModule.platform``, checked only
  for non-emptiness and the reserved ``plugin:`` prefix — so a
  colon-bearing provider genuinely can be shipped.
- What makes *that* safe is the parse, not a grammar: splitting on the
  **first** ``:`` after the prefix. The distribution is always the
  segment before it and everything after is the provider verbatim, so a
  colon-bearing provider round-trips instead of being truncated or
  stealing the distribution's segment.

Do **not** rewrite the above into "an entry-point name cannot contain
``:``". That is false, and it is the tempting wrong reason to trust this
separator. ``importlib.metadata`` splits each ``entry_points.txt`` line
on the first ``=`` only, so ``weird:name = mod:attr`` parses happily with
``ep.name == "weird:name"``; the ``:`` restriction people remember
applies to an entry point's *value* (``module:attr``), not its name.
mureo is safe because it never keys the provider half on a raw
``ep.name`` — not because such a name could not exist.

The legacy short form
---------------------
``plugin:<distribution>`` — the #481 key — **stays valid on read**. For
a distribution that provides exactly one platform the two forms denote
the same platform, so state already written under the short form keeps
joining and needs no rewrite. mureo never rewrites an operator's state
entries; see :func:`plugin_platform_key_matches` for the one subtlety
(the short form names a *distribution*, so a caller holding more than
one candidate for it must refuse rather than guess).

An analytics module also carries a **registry name** — the name it
registered itself under in the ``mureo.analytics`` entry-point group
(``AnalyticsModule.platform``). On its own that name is **not** a key:
nothing persists it, and a lookup by it will not join with STATE.json.
It is the ``<provider>`` component, and a distribution that ships both a
``mureo.providers`` provider and a ``mureo.analytics`` module for the
same platform must name them identically in both groups, or the two
surfaces build different keys for one platform.

This module is the single source of that convention. Everything that
builds, recognises, or takes apart a plugin platform key goes through
it rather than open-coding the ``"plugin:"`` literal.
"""

from __future__ import annotations

PLUGIN_PLATFORM_PREFIX = "plugin:"
"""The prefix that marks a platform key as belonging to a plugin."""

PLUGIN_PLATFORM_SEPARATOR = ":"
"""What separates the distribution from the provider inside a key.

Safe because the distribution half cannot contain it and the parse
splits on the FIRST occurrence, so an unvalidated provider half
round-trips — not because both halves are forbidden from containing one.
See this module's docstring.
"""


def plugin_platform_key(distribution: str, provider: str = "") -> str:
    """Return the canonical platform key for one plugin platform.

    ``("mureo-lineyahoo-bridge", "yahoo_ads")`` →
    ``"plugin:mureo-lineyahoo-bridge:yahoo_ads"``.

    ``provider`` is the entry-point name the distribution registered this
    platform under. Omitting it yields the legacy ``plugin:<dist>`` short
    form — for callers that genuinely cannot name the provider (an older
    plugin instance whose breadcrumb is missing), which is honest about
    the ambiguity rather than fabricating a provider.

    The key shape does **not** depend on how many platforms
    ``distribution`` ships; this function cannot know that, and #537
    explains why it must not.

    Idempotent: an already-canonical key passed back in as
    ``distribution`` is returned unchanged rather than double-prefixed,
    so a caller that cannot tell whether it holds a distribution name or
    a key stays safe. A short-form key plus a ``provider`` is completed
    to the long form; a long-form key keeps its own provider.
    """
    dist, prov = distribution, provider
    # Defensive only — every current call site feeds this a bare
    # distribution name (from ``plugin_source``, i.e. the entry point's
    # own distribution), and a module may not name itself ``plugin:*``.
    if is_plugin_platform_key(distribution):
        dist, embedded = plugin_platform_parts(distribution)
        if embedded:
            prov = embedded
    if not prov:
        return f"{PLUGIN_PLATFORM_PREFIX}{dist}"
    return f"{PLUGIN_PLATFORM_PREFIX}{dist}{PLUGIN_PLATFORM_SEPARATOR}{prov}"


def is_plugin_platform_key(key: str) -> bool:
    """Return ``True`` when ``key`` is a usable plugin platform key.

    Both forms qualify: ``plugin:<dist>:<provider>`` (canonical) and
    ``plugin:<dist>`` (the #481 short form, still valid on read).

    Two shapes claim the namespace without being usable and are
    ``False``: a bare ``"plugin:"`` carries no distribution, and
    ``"plugin:<dist>:"`` claims the long form while naming no provider —
    the dashboard already falls back to rendering such a key raw.
    Built-in keys (``google_ads`` / ``meta_ads`` / ``tiktok_ads`` / …)
    and analytics registry names are ``False``.
    """
    if not key.startswith(PLUGIN_PLATFORM_PREFIX):
        return False
    distribution, separator, provider = key[len(PLUGIN_PLATFORM_PREFIX) :].partition(
        PLUGIN_PLATFORM_SEPARATOR
    )
    if not distribution:
        return False
    return not (separator and not provider)


def plugin_platform_parts(key: str) -> tuple[str, str]:
    """Return ``(distribution, provider)`` for a plugin platform ``key``.

    ``"plugin:mureo-lineyahoo-bridge:yahoo_ads"`` →
    ``("mureo-lineyahoo-bridge", "yahoo_ads")``. The legacy short form
    yields an empty provider: ``"plugin:mureo-logly-bridge"`` →
    ``("mureo-logly-bridge", "")``. Any key that is not a plugin platform
    key yields ``("", "")``.

    The split is on the FIRST separator after the prefix, so a provider
    name is returned verbatim even if it contains one.
    """
    if not is_plugin_platform_key(key):
        return ("", "")
    distribution, _separator, provider = key[len(PLUGIN_PLATFORM_PREFIX) :].partition(
        PLUGIN_PLATFORM_SEPARATOR
    )
    return (distribution, provider)


def plugin_distribution(key: str) -> str:
    """Return the distribution embedded in a plugin platform ``key``.

    ``"plugin:mureo-logly-bridge"`` and
    ``"plugin:mureo-logly-bridge:logly_ads_context"`` both yield
    ``"mureo-logly-bridge"``. Any key that is not a plugin platform key
    (a built-in, a hosted connector, a bare ``"plugin:"``) yields ``""``
    — the caller decides what to do with a key that carries no
    distribution.
    """
    return plugin_platform_parts(key)[0]


def plugin_provider(key: str) -> str:
    """Return the provider embedded in a plugin platform ``key``.

    ``"plugin:mureo-lineyahoo-bridge:yahoo_ads"`` → ``"yahoo_ads"``.
    ``""`` for the legacy short form (which names a distribution, not a
    platform) and for anything that is not a plugin platform key.
    """
    return plugin_platform_parts(key)[1]


def plugin_platform_key_matches(key: str, distribution: str, provider: str) -> bool:
    """Return ``True`` when ``key`` denotes the platform ``(distribution,
    provider)``.

    The join every surface uses, and the reason existing state keeps
    working. Two keys match one platform:

    - the canonical ``plugin:<distribution>:<provider>`` — an exact,
      unambiguous match;
    - the legacy ``plugin:<distribution>`` — which names the
      distribution only, so it matches **every** platform that
      distribution provides.

    That second rule is deliberately permissive and is what makes state
    written before #537 keep joining: a distribution providing exactly
    one platform has exactly one candidate, so the short form and the
    canonical key denote the same thing. Where a distribution provides
    several, the short form is genuinely ambiguous — a caller that finds
    more than one candidate must say so or refuse, never pick one and
    call it resolved. This function reports the match; it does not break
    ties, because it cannot see the candidate set.
    """
    key_distribution, key_provider = plugin_platform_parts(key)
    if not key_distribution or key_distribution != distribution:
        return False
    if not key_provider:  # legacy short form — names the distribution only
        return True
    return key_provider == provider


__all__ = [
    "PLUGIN_PLATFORM_PREFIX",
    "PLUGIN_PLATFORM_SEPARATOR",
    "is_plugin_platform_key",
    "plugin_distribution",
    "plugin_platform_key",
    "plugin_platform_key_matches",
    "plugin_platform_parts",
    "plugin_provider",
]
