"""mureo.google_ads - Google Ads API operations (database-independent).

Re-exports and submodules are resolved lazily (PEP 562,
:mod:`mureo._lazy_package`). Importing *any* submodule of this package used to
run this file eagerly, which imported :mod:`mureo.google_ads.client` and through
it the whole generated ``google.ads.googleads`` protobuf tree. That made a
stdlib-only helper such as ``mureo.google_ads._gaql_validator`` — pulled in by
the MCP tool schemas via ``mureo.mcp._period_param`` — cost seconds of
API-client import that the schemas never use, on the MCP server's startup path
(#807).

Nothing about the package's surface changes. The names in ``__all__`` import as
before, ``package.some_submodule`` still resolves (``__getattr__`` imports it,
which is what the eager block used to do as a side effect), and ``dir()`` lists
both — they are materialised on access instead of at package import.

The laziness is kept out of a type-checker's way rather than paid for in lost
checking. ``mypy`` types *any* attribute of a module that has a module-level
``__getattr__`` as ``Any``, which would make ``from mureo.google_ads import
Typo`` and ``package.typo`` pass. So the hooks are defined in the ``else``
branch below, where a type-checker never looks, and every name in ``__all__`` is
imported explicitly under ``TYPE_CHECKING`` with the ``X as X`` form that marks
it a re-export. A typo'd name still fails ``mypy``, the real types survive, and
the laziness is unchanged at runtime. The three lists (``__all__``, the
``TYPE_CHECKING`` imports, ``_LAZY_EXPORTS``) have to agree;
tests/test_mcp_startup_budget.py reads this file and fails if they drift.

One thing a lazy package does change: an ``ImportError`` inside a submodule
surfaces on first access rather than at package import. It is not swallowed —
see :func:`mureo._lazy_package.lazy_getattr`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# Public name -> module that defines it.
_LAZY_EXPORTS: dict[str, str] = {
    "GoogleAdsAccountListError": "mureo.google_ads.accounts",
    "GoogleAdsApiClient": "mureo.google_ads.client",
    "list_accessible_accounts": "mureo.google_ads.accounts",
}

__all__ = [
    "GoogleAdsAccountListError",
    "GoogleAdsApiClient",
    "list_accessible_accounts",
]

if TYPE_CHECKING:
    from mureo.google_ads.accounts import (
        GoogleAdsAccountListError as GoogleAdsAccountListError,
    )
    from mureo.google_ads.accounts import (
        list_accessible_accounts as list_accessible_accounts,
    )
    from mureo.google_ads.client import GoogleAdsApiClient as GoogleAdsApiClient
else:
    from mureo._lazy_package import lazy_dir, lazy_getattr

    def __getattr__(name: str) -> object:
        return lazy_getattr(__name__, _LAZY_EXPORTS, name)

    def __dir__() -> list[str]:
        return lazy_dir(__path__, __all__, globals())
