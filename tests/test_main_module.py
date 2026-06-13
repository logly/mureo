"""``python -m mureo`` module entry point (#241 Phase 2 — Part B).

The service managers (launchd / systemd / Task Scheduler) launch mureo as
``<python> -m mureo configure --serve`` rather than via the console
script, so the runtime path never depends on where ``pip`` placed the
``mureo`` shim. These tests pin that ``mureo.__main__`` exposes the Typer
``app`` and that invoking the module actually runs the CLI.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.unit
class TestMainModuleExposesApp:
    def test_main_module_imports_and_exposes_app(self) -> None:
        """``mureo.__main__`` must re-export the same Typer ``app``."""
        import mureo.__main__ as main_module
        from mureo.cli.main import app

        assert main_module.app is app

    def test_app_is_typer_instance(self) -> None:
        import typer

        import mureo.__main__ as main_module

        assert isinstance(main_module.app, typer.Typer)


@pytest.mark.unit
class TestPythonDashMInvocation:
    def test_python_m_mureo_help_runs(self) -> None:
        """``python -m mureo --help`` exits 0 and lists subcommands.

        Runs the real module in a subprocess so the ``__main__`` guard and
        console wiring are exercised end-to-end (no mocks).
        """
        result = subprocess.run(
            [sys.executable, "-m", "mureo", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "configure" in result.stdout
        assert "service" in result.stdout
