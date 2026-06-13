"""`mureo open` — open the running configure dashboard in a browser (#241).

A stable entry point that survives an ephemeral-port fallback: instead of
re-launching ``mureo configure`` (and changing the URL), ``mureo open``
reads the active-port state file written by the running server
(``~/.mureo/configure.json``), re-validates it with the ``/api/ping``
probe, and opens the recorded URL.

If the state file is missing or the recorded server no longer answers
(stale port after a shutdown), it prints clear guidance to run
``mureo configure`` first and exits non-zero so scripts can branch on it.

Home resolution honours the ``MUREO_HOME`` environment variable when set
(used by tests and power users running an alternate home) and otherwise
falls back to ``Path.home()`` — the same ``~/.mureo`` convention as
:mod:`mureo.web.host_paths`.
"""

from __future__ import annotations

import contextlib
import os
import webbrowser
from pathlib import Path

import typer

from mureo.web.instance import probe_mureo_instance, read_state_file

open_app = typer.Typer(
    name="open",
    help=(
        "Open the running mureo configuration dashboard in your browser. "
        "Reuses the active server (run `mureo configure` first)."
    ),
    invoke_without_command=True,
)

#: Environment variable that overrides the ``~/.mureo`` home root.
MUREO_HOME_ENV = "MUREO_HOME"


def _resolve_home() -> Path:
    """Resolve the home root for ``~/.mureo`` state lookup.

    Honours ``MUREO_HOME`` (tests / alternate-home installs) and falls
    back to ``Path.home()`` in normal operation.
    """
    override = os.environ.get(MUREO_HOME_ENV)
    if override:
        return Path(override)
    return Path.home()


@open_app.callback(invoke_without_command=True)
def open_dashboard(
    url_only: bool = typer.Option(
        False,
        "--url-only",
        help="Print the dashboard URL only; do not open a browser.",
    ),
) -> None:
    """Open the active mureo configure dashboard, or guide if none runs."""
    home = _resolve_home()
    state = read_state_file(home)
    bind_host = "127.0.0.1"
    if state is not None and probe_mureo_instance(bind_host, int(state["port"])):
        url = str(state["url"])
        typer.echo(url)
        if not url_only:
            # Best-effort: a headless host where the browser cannot open
            # must not fail the command — the URL is already printed.
            with contextlib.suppress(Exception):
                webbrowser.open(url)
        return

    typer.echo(
        "No running mureo configure server found. "
        "Start it with `mureo configure`, then run `mureo open`.",
        err=True,
    )
    raise typer.Exit(code=1)
