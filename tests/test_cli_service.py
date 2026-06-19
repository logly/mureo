"""``mureo service install/uninstall/status`` CLI (#241 Phase 2 — Part C).

The command layer is OS-agnostic: it resolves the backend for the current
``sys.platform`` and surfaces the backend's structured result, mapping
``ok`` to the process exit code. These tests pin:

* dispatch — ``darwin`` → launchd, ``linux`` → systemd, ``win32`` →
  windows (platform monkeypatched, backends mocked);
* exit codes — 0 when the backend result is ``ok``, nonzero otherwise;
* an unsupported platform prints a clear message and exits nonzero,
  never raising;
* ``status`` prints installed / running / URL from the structured result.

The backend modules are mocked so no ``launchctl``/``systemctl``/
``schtasks`` runs and nothing is written to the real filesystem.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mureo.web.service import OpResult, StatusResult


def _app() -> Any:
    from mureo.cli.main import app

    return app


def _runner() -> CliRunner:
    return CliRunner()


@pytest.mark.unit
class TestServiceSubcommandRegistered:
    def test_service_group_registered(self) -> None:
        from mureo.cli.main import app

        names = [
            g.typer_instance.info.name
            for g in app.registered_groups
            if g.typer_instance
        ]
        assert "service" in names

    def test_service_help_lists_subcommands(self) -> None:
        result = _runner().invoke(_app(), ["service", "--help"])
        assert result.exit_code == 0
        assert "install" in result.output
        assert "uninstall" in result.output
        assert "restart" in result.output
        assert "status" in result.output


@pytest.mark.unit
class TestInstallDispatch:
    @pytest.mark.parametrize(
        ("platform", "backend_attr"),
        [
            ("darwin", "launchd"),
            ("linux", "systemd"),
            ("win32", "windows"),
        ],
    )
    def test_install_dispatches_to_backend(
        self, platform: str, backend_attr: str
    ) -> None:
        backend = MagicMock()
        backend.install.return_value = OpResult(ok=True, message="installed")
        with (
            patch("mureo.cli.service_cmd.sys.platform", platform),
            patch(
                f"mureo.web.service.{backend_attr}.install",
                backend.install,
            ),
        ):
            result = _runner().invoke(_app(), ["service", "install"])
        assert result.exit_code == 0, result.output
        backend.install.assert_called_once()

    def test_install_nonzero_on_backend_error(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "darwin"),
            patch(
                "mureo.web.service.launchd.install",
                return_value=OpResult(ok=False, message="permission denied"),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "install"])
        assert result.exit_code != 0
        assert "permission denied" in result.output

    def test_install_prints_dashboard_url(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "darwin"),
            patch(
                "mureo.web.service.launchd.install",
                return_value=OpResult(ok=True, message="ok"),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "install"])
        assert result.exit_code == 0
        assert "http://127.0.0.1:7613/" in result.output


@pytest.mark.unit
class TestUninstallDispatch:
    @pytest.mark.parametrize(
        ("platform", "backend_attr"),
        [
            ("darwin", "launchd"),
            ("linux", "systemd"),
            ("win32", "windows"),
        ],
    )
    def test_uninstall_dispatches_to_backend(
        self, platform: str, backend_attr: str
    ) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", platform),
            patch(
                f"mureo.web.service.{backend_attr}.uninstall",
                return_value=OpResult(ok=True, message="removed"),
            ) as mock_uninstall,
        ):
            result = _runner().invoke(_app(), ["service", "uninstall"])
        assert result.exit_code == 0, result.output
        mock_uninstall.assert_called_once()

    def test_uninstall_nonzero_on_backend_error(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "linux"),
            patch(
                "mureo.web.service.systemd.uninstall",
                return_value=OpResult(ok=False, message="failed"),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "uninstall"])
        assert result.exit_code != 0
        assert "failed" in result.output


@pytest.mark.unit
class TestStatusDispatch:
    def test_status_prints_installed_running_and_url(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "darwin"),
            patch(
                "mureo.web.service.launchd.status",
                return_value=StatusResult(
                    installed=True,
                    running=True,
                    url="http://127.0.0.1:7613/",
                ),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "status"])
        assert result.exit_code == 0, result.output
        assert "http://127.0.0.1:7613/" in result.output
        # Some affirmative wording for installed + running.
        lower = result.output.lower()
        assert "installed" in lower
        assert "running" in lower

    def test_status_reports_not_installed(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "linux"),
            patch(
                "mureo.web.service.systemd.status",
                return_value=StatusResult(
                    installed=False, running=False, url="http://127.0.0.1:7613/"
                ),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "status"])
        assert result.exit_code == 0
        assert "not installed" in result.output.lower()


@pytest.mark.unit
class TestUnsupportedPlatform:
    def test_install_unsupported_platform_message(self) -> None:
        with patch("mureo.cli.service_cmd.sys.platform", "sunos5"):
            result = _runner().invoke(_app(), ["service", "install"])
        assert result.exit_code != 0
        assert "not supported" in result.output.lower()
        assert "sunos5" in result.output

    def test_status_unsupported_platform_does_not_crash(self) -> None:
        with patch("mureo.cli.service_cmd.sys.platform", "aix"):
            result = _runner().invoke(_app(), ["service", "status"])
        # No traceback — a clean, explained nonzero exit.
        assert result.exit_code != 0
        assert "not supported" in result.output.lower()


@pytest.mark.unit
class TestRestartDispatch:
    @pytest.mark.parametrize(
        ("platform", "backend_attr"),
        [
            ("darwin", "launchd"),
            ("linux", "systemd"),
            ("win32", "windows"),
        ],
    )
    def test_restart_dispatches_to_backend(
        self, platform: str, backend_attr: str
    ) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", platform),
            patch(
                f"mureo.web.service.{backend_attr}.restart",
                return_value=OpResult(ok=True, message="restarted"),
            ) as mock_restart,
        ):
            result = _runner().invoke(_app(), ["service", "restart"])
        assert result.exit_code == 0, result.output
        mock_restart.assert_called_once()

    def test_restart_nonzero_on_backend_error(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "darwin"),
            patch(
                "mureo.web.service.launchd.restart",
                return_value=OpResult(ok=False, message="not installed"),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "restart"])
        assert result.exit_code != 0
        assert "not installed" in result.output

    def test_restart_prints_dashboard_url(self) -> None:
        with (
            patch("mureo.cli.service_cmd.sys.platform", "darwin"),
            patch(
                "mureo.web.service.launchd.restart",
                return_value=OpResult(ok=True, message="restarted"),
            ),
        ):
            result = _runner().invoke(_app(), ["service", "restart"])
        assert result.exit_code == 0
        assert "http://127.0.0.1:7613/" in result.output
