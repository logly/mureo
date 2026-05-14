"""`mureo configure` — open the local web configuration UI in a browser."""

from __future__ import annotations

import typer

from mureo.web import run_configure_wizard

configure_app = typer.Typer(
    name="configure",
    help=(
        "Open the local web configuration UI in your browser. "
        "Bind to 127.0.0.1 on an ephemeral port (no remote access)."
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
    timeout_seconds: float = typer.Option(
        600.0,
        "--timeout-seconds",
        help="Stop the server after this many seconds of inactivity.",
    ),
) -> None:
    """Open the local mureo configuration UI in a browser."""
    typer.echo("Starting mureo configuration UI on 127.0.0.1 (loopback only)...")
    run_configure_wizard(
        open_browser=not no_browser,
        timeout_seconds=timeout_seconds,
    )
    typer.echo("Configure UI stopped.")
