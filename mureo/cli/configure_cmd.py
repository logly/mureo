"""`mureo configure` — open the local web configuration UI in a browser."""

from __future__ import annotations

import typer

from mureo.web import run_configure_wizard
from mureo.web.server import DEFAULT_CONFIGURE_PORT

configure_app = typer.Typer(
    name="configure",
    help=(
        "Open the local web configuration UI in your browser. "
        f"Binds 127.0.0.1:{DEFAULT_CONFIGURE_PORT} by default (no remote "
        "access); falls back to a free port if that one is busy."
    ),
    invoke_without_command=True,
)


@configure_app.callback(invoke_without_command=True)
def configure(
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Do not automatically open a browser tab.",
    ),
    port: int = typer.Option(
        DEFAULT_CONFIGURE_PORT,
        "--port",
        help=(
            "Preferred loopback port for a stable, bookmarkable URL. "
            "If it is busy, mureo falls back to a free port automatically. "
            "Pass 0 for a pure ephemeral port (no fixed default)."
        ),
    ),
    timeout_seconds: float = typer.Option(
        600.0,
        "--timeout-seconds",
        help=(
            "Hard cap: auto-stop after this many seconds even if you "
            "never finish. Normally it exits the moment you finish in "
            "the browser or press Ctrl+C."
        ),
    ),
) -> None:
    """Open the local mureo configuration UI in a browser.

    Prefers the fixed default port for a bookmarkable URL. If a mureo
    configure server is already running on that port, it is re-opened
    instead of starting a second one (single-instance reuse); a foreign
    occupant triggers an automatic fallback to a free port.
    """
    typer.echo("Starting mureo configuration UI on 127.0.0.1 (loopback only)...")
    reused = run_configure_wizard(
        open_browser=not no_browser,
        timeout_seconds=timeout_seconds,
        preferred_port=port,
    )
    if reused:
        # Single-instance reuse: an existing server was re-opened, so no
        # new server ran and there is nothing to "stop".
        url = f"http://127.0.0.1:{port}/"
        typer.echo(f"mureo configure is already running at {url} — opening it.")
        return
    typer.echo("Configure UI stopped.")
