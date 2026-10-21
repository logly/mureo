"""Local web configuration UI for mureo.

Phase 1 surface: ``ConfigureWizard`` and ``run_configure_wizard`` —
spawn a ``http.server``-backed ThreadingHTTPServer bound to
``127.0.0.1`` on an ephemeral port and serve a single-page configure
UI. NO third-party web framework.

Public re-exports keep the import surface stable for callers (CLI,
tests) so internals (``handlers``, ``server``, ``session``) can be
refactored without breaking client code.

Both names live in :mod:`mureo.web.server` and are resolved on first
access (PEP 562 ``__getattr__`` below), so importing this package — or
any leaf submodule such as :mod:`mureo.web.instance` or
:mod:`mureo.web.service` — never loads the configure server (#863).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.web.server import ConfigureWizard, run_configure_wizard

__all__ = ["ConfigureWizard", "run_configure_wizard"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        # Re-export of the configure server, resolved on access so a leaf
        # ``mureo.web.*`` import does not load it (#863).
        from mureo.web import server  # noqa: PLC0415 — PEP 562 re-export (#863)

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
