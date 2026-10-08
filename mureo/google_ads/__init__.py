"""mureo.google_ads - Google Ads API operations (database-independent).

Re-exports are resolved lazily (PEP 562). Importing *any* submodule of this
package used to run this file eagerly, which imported
:mod:`mureo.google_ads.client` and through it the whole generated
``google.ads.googleads`` protobuf tree. That made a stdlib-only helper such as
``mureo.google_ads._gaql_validator`` — pulled in by the MCP tool schemas via
``mureo.mcp._period_param`` — cost several seconds of API-client import that the
schemas never use, and it was the single largest share of the MCP server's
startup time (#807).

The public names below still import exactly as before; they are materialised on
first attribute access instead of at package import.
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
