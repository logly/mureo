"""mureo CLI main entry point.

Typer app definition and subcommand group registration.
Registered as the ``mureo`` command in pyproject.toml.

Also hosts the version surface (#487): the eager ``--version`` option and
the equivalent ``mureo version`` subcommand. Both print a single
``mureo <version>`` line — the first thing a developer runs after
installing, and what every bug report asks for, so it stays plain text
(no Rich markup) and machine-parseable.
"""

from __future__ import annotations

import logging
from importlib import metadata

import typer

import mureo
from mureo.cli.amazon_cmd import amazon_app
from mureo.cli.auth_cmd import auth_app
from mureo.cli.byod_cmd import byod_app
from mureo.cli.configure_cmd import configure_app
from mureo.cli.demo_cmd import demo_app
from mureo.cli.install_desktop_cmd import install_desktop_app
from mureo.cli.learn_cmd import learn_app
from mureo.cli.open_cmd import open_app
from mureo.cli.providers_cmd import providers_app
from mureo.cli.repair_cmd import repair_app
from mureo.cli.rollback_cmd import rollback_app
from mureo.cli.service_cmd import service_app
from mureo.cli.setup_cmd import setup_app
from mureo.cli.upgrade_cmd import upgrade_app

app = typer.Typer(
    name="mureo",
    help="Your local-first AI ad ops crew. Works with Claude Code, Cursor, Codex & Gemini.",
    no_args_is_help=True,
)

app.add_typer(auth_app)
app.add_typer(setup_app)
app.add_typer(install_desktop_app)
app.add_typer(rollback_app)
app.add_typer(repair_app)
app.add_typer(byod_app)
app.add_typer(demo_app)
app.add_typer(providers_app)
app.add_typer(amazon_app)
app.add_typer(configure_app)
app.add_typer(open_app)
app.add_typer(service_app)
app.add_typer(learn_app)
app.add_typer(upgrade_app)

logger = logging.getLogger(__name__)

#: Distribution name to read the installed version from.
_DIST_NAME = "mureo"


def _resolve_version() -> str:
    """Return the installed ``mureo`` distribution version.

    Distribution metadata is authoritative — it is what ``pip`` actually
    installed. When it cannot be read (no dist-info at all: odd editable
    layouts, a vendored checkout run straight from source), fall back to
    the in-tree ``mureo.__version__`` rather than failing, so the command
    a bug reporter is asked to run always answers. Both values are kept
    in sync with ``pyproject.toml`` by ``tests/test_cli_version.py``.
    """
    try:
        return metadata.version(_DIST_NAME)
    except Exception:  # PackageNotFoundError + exotic metadata failures
        logger.debug("could not read installed mureo version", exc_info=True)
        return mureo.__version__


def _version_line() -> str:
    return f"mureo {_resolve_version()}"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(_version_line())
        raise typer.Exit()


@app.command("version")
def version_cmd() -> None:
    """Show the mureo version."""
    typer.echo(_version_line())


@app.callback()
def _root_callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the mureo version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    # Root callback exists solely to host the eager ``--version`` option;
    # `--version` is handled in `_version_callback` before any subcommand
    # runs, so there is nothing to do here. Kept docstring-free on purpose:
    # Typer's help precedence between a callback docstring and the `help=`
    # passed to `typer.Typer(...)` is version-sensitive, so do not add a
    # docstring here without re-checking `mureo --help` (a test pins the
    # tagline).
    return None


if __name__ == "__main__":
    app()
