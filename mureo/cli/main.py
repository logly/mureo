"""mureo CLI main entry point.

Typer app definition and subcommand group registration.
Registered as the ``mureo`` command in pyproject.toml.
"""

from __future__ import annotations

import typer

from mureo.cli.auth_cmd import auth_app
from mureo.cli.rollback_cmd import rollback_app
from mureo.cli.setup_cmd import setup_app

app = typer.Typer(
    name="mureo",
    help="Marketing orchestration framework for AI agents",
    no_args_is_help=True,
)

app.add_typer(auth_app)
app.add_typer(setup_app)
app.add_typer(rollback_app)

if __name__ == "__main__":
    app()
