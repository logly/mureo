"""CLI version surface tests — ``mureo --version`` / ``mureo version`` (#487).

Checking the version is the first thing a developer runs after installing,
and it is what every bug report asks for, so this surface is guarded on
three axes:

  - it exists and exits 0 (the reported bug was ``No such option: --version``)
  - it reports the INSTALLED distribution version, falling back to the
    in-tree ``mureo.__version__`` when distribution metadata is unavailable
    (odd editable / vendored layouts)
  - the fallback value does not drift from ``pyproject.toml`` — the same
    release-bump drift guard as ``tests/test_plugin_manifests.py``
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

pytestmark = pytest.mark.unit

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parent.parent

#: ``mureo <PEP 440 version>`` on a single line, nothing else.
VERSION_LINE = re.compile(r"^mureo \d+\.\d+\.\d+\S*$")


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


class TestVersionFlag:
    def test_version_flag_exits_zero(self) -> None:
        from mureo.cli.main import app

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "No such option" not in result.output

    def test_version_flag_prints_single_mureo_version_line(self) -> None:
        from mureo.cli.main import app

        result = runner.invoke(app, ["--version"])
        assert VERSION_LINE.match(result.output.strip()), result.output

    def test_version_flag_reports_installed_distribution_version(self) -> None:
        from mureo.cli.main import app

        with patch("importlib.metadata.version", return_value="9.9.9"):
            result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == "mureo 9.9.9"

    def test_version_flag_falls_back_to_package_dunder(self) -> None:
        """Odd editable installs can have no readable distribution metadata;
        the in-tree ``__version__`` is then the best available answer."""
        import mureo
        from mureo.cli.main import app

        with patch(
            "importlib.metadata.version",
            side_effect=PackageNotFoundError("mureo"),
        ):
            result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == f"mureo {mureo.__version__}"

    def test_version_flag_does_not_trigger_no_command_error(self) -> None:
        """``mureo --version`` with no subcommand must print the version, not
        the ``no_args_is_help`` / missing-command usage error."""
        from mureo.cli.main import app

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "Missing command" not in result.output
        assert "Usage:" not in result.output

    def test_help_tagline_unchanged(self) -> None:
        """Adding the root callback must not shadow the app-level help.

        Typer's precedence between a callback docstring and the ``help=``
        passed to ``typer.Typer(...)`` is version-sensitive; this pins the
        tagline so an accidental docstring (or a Typer upgrade that flips
        the precedence) surfaces as a test failure instead of a silently
        rewritten ``mureo --help``.
        """
        from mureo.cli.main import app

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "local-first AI ad ops crew" in result.output


class TestVersionSubcommand:
    def test_version_subcommand_exits_zero_and_matches_flag(self) -> None:
        from mureo.cli.main import app

        sub = runner.invoke(app, ["version"])
        flag = runner.invoke(app, ["--version"])
        assert sub.exit_code == 0
        assert sub.output.strip() == flag.output.strip()

    def test_version_subcommand_listed_in_help(self) -> None:
        from mureo.cli.main import app

        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "version" in result.output


class TestVersionMatchesPyproject:
    def test_package_dunder_version_matches_pyproject(self) -> None:
        """``mureo.__version__`` is the ``--version`` fallback, so a release
        bump that edits only ``pyproject.toml`` would make the CLI lie.
        Same drift guard as ``test_plugin_version_matches_pyproject``."""
        import mureo

        assert mureo.__version__ == _pyproject_version(), (
            f"mureo.__version__ ({mureo.__version__}) != pyproject.toml "
            f"({_pyproject_version()}). Bump both."
        )

    @pytest.mark.parametrize("argv", [["--version"], ["version"]])
    def test_reports_pyproject_version_for_an_in_sync_install(
        self, argv: list[str]
    ) -> None:
        """On a normal (released) install the distribution metadata equals the
        repo version, and both surfaces must print exactly that."""
        from mureo.cli.main import app

        expected = _pyproject_version()
        with patch("importlib.metadata.version", return_value=expected):
            result = runner.invoke(app, argv)
        assert result.exit_code == 0
        assert result.output.strip() == f"mureo {expected}"
