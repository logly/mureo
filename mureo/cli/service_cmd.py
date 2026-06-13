"""``mureo service`` — install/uninstall/status the auto-start daemon (#241).

Registers (or removes, or inspects) a *user-level* auto-start agent that
runs the headless configure daemon (``mureo configure --serve``) at login:

* ``install``   — write the OS unit AND start it now; print the dashboard
  URL and that it will auto-start at login. Idempotent.
* ``uninstall`` — stop the running daemon AND remove the unit. Idempotent
  (a clean no-op when nothing is installed).
* ``status``    — report installed? (unit registered) and running? (probe
  ``/api/ping`` on the configured port) and print the URL.

This layer is OS-agnostic: it resolves the right backend for the current
``sys.platform`` (:mod:`mureo.web.service.launchd` /
:mod:`~mureo.web.service.systemd` / :mod:`~mureo.web.service.windows`),
surfaces the backend's structured result, and maps ``ok`` to the exit
code. An unsupported platform prints a clear message and exits nonzero,
never raising.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import typer

from mureo.web.service import SERVICE_PORT, dashboard_url

if TYPE_CHECKING:
    from types import ModuleType

service_app = typer.Typer(
    name="service",
    help=(
        "Install, remove, or inspect the mureo auto-start service. "
        "Runs the configure dashboard headless at login (user-level "
        "agent — no root)."
    ),
    no_args_is_help=True,
)

#: Map ``sys.platform`` prefixes to their backend module name.
_PLATFORM_BACKENDS = {
    "darwin": "launchd",
    "linux": "systemd",
    "win32": "windows",
}


def _resolve_backend() -> ModuleType:
    """Import and return the backend module for the current platform.

    Raises :class:`typer.Exit` (code 1) with a clear message on an
    unsupported platform so no command ever crashes with a traceback.
    """
    name = _PLATFORM_BACKENDS.get(sys.platform)
    if name is None:
        typer.echo(
            f"mureo service is not supported on platform '{sys.platform}'. "
            "Supported: macOS (launchd), Linux (systemd --user), "
            "Windows (Task Scheduler).",
            err=True,
        )
        raise typer.Exit(code=1)
    # Import lazily so a platform-specific import never runs at module load.
    import importlib

    return importlib.import_module(f"mureo.web.service.{name}")


@service_app.command("install")
def install() -> None:
    """Install and start the auto-start service now."""
    backend = _resolve_backend()
    result = backend.install(port=SERVICE_PORT)
    if not result.ok:
        typer.echo(f"Failed to install mureo service: {result.message}", err=True)
        raise typer.Exit(code=1)
    url = dashboard_url(port=SERVICE_PORT)
    typer.echo("mureo service installed and started.")
    typer.echo(f"Dashboard: {url}")
    typer.echo("It will auto-start at every login.")


@service_app.command("uninstall")
def uninstall() -> None:
    """Stop and remove the auto-start service."""
    backend = _resolve_backend()
    result = backend.uninstall()
    if not result.ok:
        typer.echo(f"Failed to uninstall mureo service: {result.message}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"mureo service uninstalled ({result.message}).")


@service_app.command("status")
def status() -> None:
    """Report whether the service is installed and running."""
    backend = _resolve_backend()
    result = backend.status(port=SERVICE_PORT)
    installed = "installed" if result.installed else "not installed"
    running = "running" if result.running else "not running"
    typer.echo(f"Service: {installed}, {running}.")
    typer.echo(f"Dashboard: {result.url}")
