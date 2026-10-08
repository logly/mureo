"""mureo.google_ads - Google Ads API operations (database-independent).

Re-exports and submodules are resolved lazily (PEP 562). Importing *any*
submodule of this package used to run this file eagerly, which imported
:mod:`mureo.google_ads.client` and through it the whole generated
``google.ads.googleads`` protobuf tree. That made a stdlib-only helper such as
``mureo.google_ads._gaql_validator`` — pulled in by the MCP tool schemas via
``mureo.mcp._period_param`` — cost seconds of API-client import that the schemas
never use, on the MCP server's startup path (#807).

Nothing about the package's surface changes. The names in ``__all__`` import as
before, ``package.some_submodule`` still resolves (``__getattr__`` imports it,
which is what the eager block used to do as a side effect), and ``dir()`` lists
both — they are materialised on access instead of at package import.

Two things a lazy package cannot give back:

* ``mypy`` types *any* attribute of a module with a module-level
  ``__getattr__`` as ``Any``, so ``package.typo`` passes type-checking where on
  an eager package it would not. There is no way to keep the laziness and the
  check both; the names in ``__all__`` are declared under ``TYPE_CHECKING``
  below so at least those keep their real types.
* An ``ImportError`` inside a submodule now surfaces on first access rather
  than at package import. It is not swallowed: only a
  ``ModuleNotFoundError`` naming *this* attribute becomes an
  ``AttributeError``; anything else propagates unchanged.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.google_ads.accounts import (
        GoogleAdsAccountListError,
        list_accessible_accounts,
    )
    from mureo.google_ads.client import GoogleAdsApiClient

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
