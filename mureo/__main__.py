"""``python -m mureo`` entry point (#241 Phase 2 — Part B).

The auto-start service managers (launchd / systemd / Task Scheduler)
launch mureo as ``<python> -m mureo configure --serve`` rather than via
the ``mureo`` console script. Resolving the CLI through the module is
path-independent: it works wherever ``pip`` placed the console-script
shim and regardless of ``PATH``, so a LaunchAgent/unit/task that pins
``sys.executable -m mureo`` always finds the same code.

Re-exports the Typer ``app`` so ``mureo.__main__.app`` is the canonical
CLI object, then runs it under the ``__main__`` guard.
"""

from __future__ import annotations

from mureo.cli.main import app

__all__ = ["app"]


if __name__ == "__main__":
    app()
