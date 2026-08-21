"""Platform key → the name an operator reads (#678).

Lifted verbatim out of :mod:`mureo.web.reports`, which had grown past the
point where one reader could hold it. Nothing here changed in the move — same
functions, same bodies, same order.

One question is answered here and nowhere else: given a ``platforms`` key as
stored in STATE.json, what does the dashboard call it? Three cases, and the
third is the one that carries weight:

  1. A built-in key (``google_ads``, ``meta_ads``, …) has a name in the shared
     table :data:`~mureo.core.platform_keys.BUILTIN_PLATFORM_DISPLAY_NAMES`.
  2. A ``plugin:<dist>`` key belonging to an in-tree bridge is labelled as the
     first-party integration it is, without a ``(plugin)`` suffix.
  3. Anything else is returned **unchanged**. That is not a fallback but a
     signal: returning the key verbatim is precisely how mureo answers "this
     key is unrecognisable", and :data:`~mureo.web.report_document
     .CONFLICT_UNRECOGNIZED_KEY` is defined in terms of it. So a change here
     that invented a prettier name for an unknown key would silently switch
     off a conflict finding two modules away.

The plugin half of the vocabulary is read from
:func:`~mureo.context.platform_guards.installed_platform_names` — the same
enumeration the write-time guard uses (#631) — so this resolver can never
disagree with what mureo accepted on write.

No document, no store, no I/O: every function takes a string and returns a
string.
"""

from __future__ import annotations

from mureo.context.platform_guards import installed_platform_names
from mureo.core.platform_keys import (
    BUILTIN_PLATFORM_DISPLAY_NAMES,
    PLUGIN_PLATFORM_PREFIX,
    is_plugin_platform_key,
    plugin_platform_parts,
)

# Built-in platform key → human display name. Plugin keys (``plugin:<dist>``)
# and any unknown key are resolved by :func:`platform_display_name` instead.
#
# The map itself lives in ``mureo.core.platform_keys`` (#609): the write-time
# guard has to accept exactly these keys, and ``mureo.context`` cannot import
# ``mureo.web``. This module keeps the local name because it is the read-side
# resolver's own vocabulary and every reference below reads as one.
_BUILTIN_DISPLAY_NAMES = BUILTIN_PLATFORM_DISPLAY_NAMES

# Distribution → display name for OFFICIAL, in-tree bridges (audit #30).
# These ride the ``plugin:<dist>`` dispatch path to reuse the plugin safety
# layer, but that is an implementation detail: they ship inside mureo, so
# labelling them "(plugin)" would tell the operator a first-party integration
# is third-party. Only in-tree bridges belong here; a genuine third-party
# distribution keeps the suffix.
#
# The key is spelled out rather than imported from
# ``mureo.amazon_ads.provider.AMAZON_SOURCE_DISTRIBUTION`` on purpose: that
# module pulls the bridge (and the mcp SDK types it imports) onto the
# configure-UI import path, which the wizard deliberately avoids. A test pins
# the two strings together.
_OFFICIAL_BRIDGE_DISPLAY_NAMES: dict[str, str] = {
    "mureo-amazon-ads-bridge": "Amazon Ads",
}


def platform_display_name(key: str) -> str:
    """Resolve a human label for a ``platforms`` key.

    Rules:
    - A built-in key (``google_ads`` / ``meta_ads`` / ``search_console`` /
      ``ga4``) → its registered name.
    - A plugin key naming an OFFICIAL in-tree bridge → its registered
      name, with no ``" (plugin)"`` suffix (e.g.
      ``plugin:mureo-amazon-ads-bridge`` → ``"Amazon Ads"``). See
      :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES`.
    - A canonical ``plugin:<dist>:<provider>`` key (#537) → a humanized
      label from ``<provider>``, suffixed ``" (plugin)"``: the provider
      names the *platform*, which is what a label is for, while the
      distribution is packaging (e.g.
      ``plugin:mureo-lineyahoo-bridge:yahoo_ads`` → ``"Yahoo Ads
      (plugin)"``, not a mangled ``"Mureo-Lineyahoo-Bridge:Yahoo Ads"``).
      A provider that humanizes to nothing falls back to the distribution.
    - A legacy ``plugin:<dist>`` key → a humanized label from ``<dist>``:
      drop a leading ``mureo-`` and a trailing ``-bridge``, title-case the
      hyphen-separated words, and suffix ``" (plugin)"`` (e.g.
      ``plugin:mureo-logly-bridge`` → ``"Logly (plugin)"``,
      ``plugin:acme-ads`` → ``"Acme Ads (plugin)"``). Unchanged, so state
      written before #537 keeps the label it already had.
    - A bare provider name an INSTALLED plugin registered (#609/#631) → the
      humanized name with the same ``" (plugin)"`` suffix
      (``logly_ads_context`` → ``"Logly Ads Context (plugin)"``). See
      :func:`_installed_plugin_platform_label`.
    - Anything else (an unknown built-in-shaped key) → the key itself, so
      the dashboard never renders a blank label.

    :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES` is keyed by distribution, so an
    official bridge shipping several platforms would label them all alike;
    none does today, and the fix when one appears is a per-provider entry,
    not a change to this resolution order.
    """
    builtin = _BUILTIN_DISPLAY_NAMES.get(key)
    if builtin is not None:
        return builtin
    # Issues #481 / #537: the canonical plugin key — see
    # mureo.core.platform_keys.
    if is_plugin_platform_key(key):
        dist, provider = plugin_platform_parts(key)
        official = _OFFICIAL_BRIDGE_DISPLAY_NAMES.get(dist)
        if official is not None:
            return official
        label = _humanize_words(provider) if provider else ""
        if not label:
            label = _humanize_dist(dist)
        return f"{label} (plugin)" if label else key
    return _installed_plugin_platform_label(key) or key


def _installed_plugin_platform_label(key: str) -> str:
    """Label a bare provider name an installed plugin registered (#631).

    ``key`` is a platform name straight out of the ``mureo.providers`` /
    ``mureo.analytics`` entry points — ``logly_ads_context``, not
    ``plugin:mureo-logly-bridge:logly_ads_context``. That has been a valid
    key to WRITE since #609, and this function is why the read side no longer
    calls it unresolvable: a key the guard accepted was being flagged
    ``unrecognized_key`` on the dashboard at the same moment
    ``mureo repair platform-key`` reported the same entry ``Clean``.

    Same ``" (plugin)"`` suffix as the canonical key for the same platform:
    the entry comes from a plugin under either spelling, and two labels for
    one platform on one dashboard would replace this inconsistency with
    another. :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES` cannot apply here — it is
    keyed by distribution and a bare name carries none — so an in-tree bridge
    held under its bare provider name keeps the suffix. Resolving that would
    mean reading ``ep.dist``, i.e. reading more of an entry point than the
    guard does, and mureo writes the canonical key for those anyway.

    Fails OPEN exactly as :func:`~mureo.context.platform_guards.
    reject_unknown_platform_key` does: an environment that cannot be
    enumerated labels the key rather than reporting it unrecognised, because
    a broken ``importlib.metadata`` is not evidence that a key is wrong.

    Two shapes are excluded whatever the registry says: a key claiming the
    plugin namespace without naming a platform (``plugin:``,
    ``plugin:<dist>:``), which the write path refuses on shape alone
    (``reject_unusable_platform_key``) and which no enumeration failure can
    make legitimate; and a name that humanizes to nothing. Both yield ``""``
    and the caller falls back to the raw key.
    """
    if key.startswith(PLUGIN_PLATFORM_PREFIX):
        return ""
    installed = installed_platform_names()
    if installed is not None and key not in installed:
        return ""
    label = _humanize_words(key)
    return f"{label} (plugin)" if label else ""


def _humanize_words(name: str) -> str:
    """Title-case a ``-``/``_``-separated identifier.

    ``yahoo_ads`` → ``Yahoo Ads``; ``acme-ads`` → ``Acme Ads``. An
    identifier that carries no word characters yields ``""`` so the
    caller can fall back.
    """
    words = [w for w in name.strip().replace("_", "-").split("-") if w]
    return " ".join(word.capitalize() for word in words)


def _humanize_dist(dist: str) -> str:
    """Turn a distribution name into a Title-Cased label.

    ``mureo-logly-bridge`` → ``Logly``; ``acme-ads`` → ``Acme Ads``. A
    leading ``mureo-`` and a trailing ``-bridge`` are mureo packaging
    conventions, not part of the brand, so they are stripped. An empty
    result (e.g. ``plugin:mureo-``, which is nothing but conventions)
    yields ``""`` and the caller falls back to the raw key.
    """
    name = dist.strip()
    if name.startswith("mureo-"):
        name = name[len("mureo-") :]
    if name.endswith("-bridge"):
        name = name[: -len("-bridge")]
    return _humanize_words(name)
