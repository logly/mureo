"""mureo CLI main entry point.

Typer app definition and subcommand group registration.
Registered as the ``mureo`` command in pyproject.toml.
"""

from __future__ import annotations

import typer

from mureo.cli.auth_cmd import auth_app
from mureo.cli.byod_cmd import byod_app
from mureo.cli.configure_cmd import configure_app
from mureo.cli.demo_cmd import demo_app
from mureo.cli.install_desktop_cmd import install_desktop_app
from mureo.cli.providers_cmd import providers_app
from mureo.cli.rollback_cmd import rollback_app
from mureo.cli.setup_cmd import setup_app

app = typer.Typer(
    name="mureo",
    help="Your local-first AI ad ops crew. Works with Claude Code, Cursor, Codex & Gemini.",
    no_args_is_help=True,
)

app.add_typer(auth_app)
app.add_typer(setup_app)
app.add_typer(install_desktop_app)
app.add_typer(rollback_app)
app.add_typer(byod_app)
app.add_typer(demo_app)
app.add_typer(providers_app)
app.add_typer(configure_app)

if __name__ == "__main__":
    app()
