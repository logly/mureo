"""mureo CLI main entry point.

Typer app definition and subcommand group registration.
Registered as the ``mureo`` command in pyproject.toml.
"""

from __future__ import annotations

import typer

from mureo.cli.auth_cmd import auth_app
from mureo.cli.google_ads import google_ads_app
from mureo.cli.meta_ads import meta_ads_app

app = typer.Typer(
    name="mureo",
    help="Ad operations toolkit for AI agents",
    no_args_is_help=True,
)

app.add_typer(google_ads_app)
app.add_typer(meta_ads_app)
app.add_typer(auth_app)

if __name__ == "__main__":
    app()
