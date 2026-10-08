"""mureo.meta_ads - Meta Ads API operations (database-independent).

Re-exports and submodules are resolved lazily (PEP 562,
:mod:`mureo._lazy_package`), for the same reason as :mod:`mureo.google_ads`:
importing one submodule used to run this file and with it the whole API client.
``mureo.auth`` only wants ``OAUTH_TOKEN_URL`` out of
``mureo.meta_ads._api_version``, and every MCP handler module imports
``mureo.auth``, so the Meta client was being built on the server's startup path
by a module that never calls it (#807).

Nothing about the package's surface changes. The names in ``__all__`` import as
before, ``package.some_submodule`` still resolves (``__getattr__`` imports it,
which is what the eager block used to do as a side effect), and ``dir()`` lists
both — they are materialised on access instead of at package import. See
:mod:`mureo.google_ads` for why the hooks sit in the ``else`` branch (so that a
typo'd name still fails ``mypy``) and for the one behaviour that does change (an
``ImportError`` inside a submodule surfaces on first access).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from mureo.meta_ads._api_version import (
        META_GRAPH_API_VERSION as META_GRAPH_API_VERSION,
    )
    from mureo.meta_ads.accounts import MetaAdAccountList as MetaAdAccountList
    from mureo.meta_ads.accounts import (
        list_meta_ad_accounts as list_meta_ad_accounts,
    )
    from mureo.meta_ads.client import MetaAdsApiClient as MetaAdsApiClient
    from mureo.meta_ads.mappers import map_ad as map_ad
    from mureo.meta_ads.mappers import map_ad_set as map_ad_set
    from mureo.meta_ads.mappers import map_campaign as map_campaign
    from mureo.meta_ads.mappers import map_insights as map_insights
else:
    from mureo._lazy_package import lazy_dir, lazy_getattr

    def __getattr__(name: str) -> object:
        return lazy_getattr(__name__, _LAZY_EXPORTS, name)

    def __dir__() -> list[str]:
        return lazy_dir(__path__, __all__, globals())
