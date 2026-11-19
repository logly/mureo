"""The providers shipped inside mureo, registered from one place (#121, #992).

A bundled provider ships in the mureo distribution rather than as a
``mureo.providers`` entry point, so :meth:`Registry.discover` never sees it.
It satisfies the same ``MCPToolProvider`` shape as a third-party plugin, so
feeding it through the same collection gives it the plugin safety layer
(audit, throttle, strategy promotion, ``action_log``, rollback) with no
platform-specific branch in the dispatch path. Two surfaces need every
bundled provider in :data:`~mureo.core.providers.default_registry`:

- the MCP server, which feeds registry entries through
  ``collect_plugin_tools`` to expose the provider's tools
  (:func:`discover_with_bundled`), and
- the ``mureo configure`` UI, whose plugin-credentials section renders a form
  for every registered provider declaring ``account_credential_fields``
  (:func:`register_bundled_providers`).

Both read :data:`_BUNDLED_PROVIDERS`, so adding a bundled provider is one row
here and neither process can serve a provider the other does not show.

Ordering contract
-----------------
Bundled providers are registered BEFORE entry-point discovery. The registry is
first-wins, so registering first is what makes a bundled provider
deterministically beat a third-party distribution that publishes an entry
point under the same name — in both processes, not just whichever happened to
register earlier. A foreign entry that was already in the registry before
this runs keeps the slot (the documented first-wins contract); a row's
register function then returns that foreign entry.

Disabling
---------
Each row carries its own ``MUREO_DISABLE_*`` gate, read at call time. A
disabled provider is neither registered nor appended, so the server exposes
none of its tools and the configure UI renders no card for a provider the
server will not serve. A third-party entry point of the same name is left to
discovery, as the other ``MUREO_DISABLE_*`` gates leave the official MCP they
step aside for.

This module sits below :mod:`mureo.mcp` and :mod:`mureo.web`, which both
import it; it imports neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.amazon_ads.provider import amazon_ads_disabled, register_amazon_provider

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from mureo.core.providers.registry import ProviderEntry

#: One row per bundled provider, in registration order: ``(disabled,
#: register)``. ``disabled()`` reads the provider's ``MUREO_DISABLE_*`` gate;
#: ``register()`` registers it idempotently and returns the live entry
#: (first-wins, so possibly a foreign one).
_BUNDLED_PROVIDERS: tuple[
    tuple[Callable[[], bool], Callable[[], ProviderEntry]], ...
] = ((amazon_ads_disabled, register_amazon_provider),)


def register_bundled_providers() -> tuple[ProviderEntry, ...]:
    """Register every enabled bundled provider; return the live entries.

    Call this BEFORE entry-point discovery (see the ordering contract above).
    Safe to call repeatedly: each row's register function is a silent no-op
    once its provider is in the registry.
    """
    return tuple(
        register() for disabled, register in _BUNDLED_PROVIDERS if not disabled()
    )


def discover_with_bundled(
    discover: Callable[[], Iterable[ProviderEntry]],
) -> tuple[ProviderEntry, ...]:
    """``discover()``'s entries plus every enabled bundled provider.

    The bundled providers are registered first, then ``discover`` runs.
    ``discover`` returns only what its own pass registered, so a bundled entry
    is appended explicitly — unless ``discover`` already returned an entry of
    the same name, which would otherwise expose that provider's tools twice.
    """
    bundled = register_bundled_providers()
    entries = tuple(discover())
    discovered = {entry.name for entry in entries}
    return entries + tuple(entry for entry in bundled if entry.name not in discovered)


__all__ = ["discover_with_bundled", "register_bundled_providers"]
