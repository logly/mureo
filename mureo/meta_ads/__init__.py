"""mureo.meta_ads - Meta Ads API operations (database-independent).

Re-exports are resolved lazily (PEP 562), for the same reason as
:mod:`mureo.google_ads`: importing one submodule used to run this file and with
it the whole API client. ``mureo.auth`` only wants ``OAUTH_TOKEN_URL`` out of
``mureo.meta_ads._api_version``, and every MCP handler module imports
``mureo.auth``, so the Meta client was being built on the server's startup path
by a module that never calls it (#807).

The public names below still import exactly as before; they are materialised on
first attribute access instead of at package import.
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
    """Import the module owning ``name`` on first access (PEP 562)."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the lazy names too, so introspection matches the eager package."""
    return sorted({*globals(), *__all__})
