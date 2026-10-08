"""mureo.meta_ads - Meta Ads API operations (database-independent).

Re-exports and submodules are resolved lazily (PEP 562), for the same reason as
:mod:`mureo.google_ads`: importing one submodule used to run this file and with
it the whole API client. ``mureo.auth`` only wants ``OAUTH_TOKEN_URL`` out of
``mureo.meta_ads._api_version``, and every MCP handler module imports
``mureo.auth``, so the Meta client was being built on the server's startup path
by a module that never calls it (#807).

Nothing about the package's surface changes. The names in ``__all__`` import as
before, ``package.some_submodule`` still resolves (``__getattr__`` imports it,
which is what the eager block used to do as a side effect), and ``dir()`` lists
both — they are materialised on access instead of at package import. See
:mod:`mureo.google_ads` for the two things a lazy package cannot give back
(``mypy`` cannot flag a typo'd attribute; an ``ImportError`` inside a submodule
surfaces on first access).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.meta_ads._api_version import META_GRAPH_API_VERSION
    from mureo.meta_ads.accounts import MetaAdAccountList, list_meta_ad_accounts
    from mureo.meta_ads.client import MetaAdsApiClient
    from mureo.meta_ads.mappers import (
        map_ad,
        map_ad_set,
        map_campaign,
        map_insights,
    )

# Public name -> module that defines it.
_LAZY_EXPORTS: dict[str, str] = {
    "META_GRAPH_API_VERSION": "mureo.meta_ads._api_version",
    "MetaAdAccountList": "mureo.meta_ads.accounts",
    "MetaAdsApiClient": "mureo.meta_ads.client",
    "list_meta_ad_accounts": "mureo.meta_ads.accounts",
    "map_ad": "mureo.meta_ads.mappers",
    "map_ad_set": "mureo.meta_ads.mappers",
    "map_campaign": "mureo.meta_ads.mappers",
    "map_insights": "mureo.meta_ads.mappers",
}

__all__ = [
    "META_GRAPH_API_VERSION",
    "MetaAdAccountList",
    "MetaAdsApiClient",
    "list_meta_ad_accounts",
    "map_ad",
    "map_ad_set",
    "map_campaign",
    "map_insights",
]


def __getattr__(name: str) -> Any:
    """Resolve a re-exported name, or a submodule, on first access (PEP 562).

    Deliberately does NOT cache into ``globals()``: a cached re-export outlives
    the ``mock.patch`` that produced it (``patch`` restores the *defining*
    module's attribute, not this package's copy), which would leave a dead mock
    installed here for the rest of the process. ``import_module`` is a
    ``sys.modules`` lookup after the first call, so re-resolving is cheap.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        return getattr(import_module(module_name), name)
    try:
        return import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{__name__}.{name}":
            raise
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    """List the lazy names and the submodules, as the eager package did."""
    from pkgutil import iter_modules

    return sorted(
        set(globals()) | set(__all__) | {info.name for info in iter_modules(__path__)}
    )
