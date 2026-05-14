"""Local web configuration UI for mureo.

Phase 1 surface: ``ConfigureWizard`` and ``run_configure_wizard`` —
spawn a ``http.server``-backed ThreadingHTTPServer bound to
``127.0.0.1`` on an ephemeral port and serve a single-page configure
UI. NO third-party web framework.

Public re-exports keep the import surface stable for callers (CLI,
tests) so internals (``handlers``, ``server``, ``session``) can be
refactored without breaking client code.
"""

from __future__ import annotations

from mureo.web.server import ConfigureWizard, run_configure_wizard

__all__ = ["ConfigureWizard", "run_configure_wizard"]
