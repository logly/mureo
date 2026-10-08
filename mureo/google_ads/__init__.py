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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

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
    installed here for the rest of the process. The price is real and was
    understated here as "cheap": even on a ``sys.modules`` hit, ``import_module``
    takes the import lock and re-resolves the name, measured at 12.6 us against
    0.14 us for the same attribute on its defining module — about ninety times,
    and a second machine measured 23.6 us against 0.10 us. It stays, because the
    three in-tree call sites read these names once per operation and a dead mock
    poisons every test after it; code in a loop should import the defining
    module. A *miss* costs more still (36 us: it searches the path before
    failing) and is not cached either, so ``hasattr`` in a loop is the wrong
    shape for this package.
    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is not None:
        return getattr(import_module(module_name), name)
    if not name.isidentifier():
        # ``hasattr(pkg, "a.b")`` has to answer False, and a dotted name would
        # send ``import_module`` looking for a grandchild and raise
        # ModuleNotFoundError past ``hasattr`` instead (the ``exc.name`` guard
        # below sees "pkg.a", not the name asked for). PEP 562 promises an
        # AttributeError for anything this module does not have.
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        return import_module(f"{__name__}.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"{__name__}.{name}":
            raise
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__() -> list[str]:
    """List this module's dunders, its public names and its submodules.

    Not ``globals()``: that advertised the imports this file needs in order to
    be lazy (``TYPE_CHECKING``, ``import_module``, ``_LAZY_EXPORTS``) as part of
    the package's surface. They are still reachable as attributes — so are any
    module's imports — but ``dir()`` is what a reader and a completion engine
    take for the surface, and the eager package never listed them.
    """
    from pkgutil import iter_modules

    return sorted(
        {name for name in globals() if name.startswith("__")}
        | set(__all__)
        | {info.name for info in iter_modules(__path__)}
    )
