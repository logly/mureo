"""Windows Task Scheduler backend for ``mureo service`` (#241 Phase 2).

The Windows auto-start backend registers an on-logon Scheduled Task named
``MureoConfigure`` via ``schtasks`` so the headless configure daemon runs
at login. There is no unit file — installed-ness is queried with
``schtasks /Query``. These tests pin:

* ``install`` runs ``schtasks /Create ... /SC ONLOGON /F`` then
  ``schtasks /Run`` (fixed argv, ``shell=False``) with a ``/TR`` that
  invokes ``-m mureo configure --serve --port 7613``;
* ``uninstall`` runs ``schtasks /Delete /TN MureoConfigure /F`` and is a
  clean no-op when the task does not exist;
* ``status`` reports installed (``/Query`` exit 0) and running (ping);
* graceful degradation — missing ``schtasks`` / nonzero create → structured
  error, never a traceback.

All ``subprocess`` calls are mocked; nothing touches the real scheduler.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.web.service import windows

if TYPE_CHECKING:
    from pathlib import Path


def _ok(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".mureo").mkdir(parents=True)
    return h


@pytest.mark.unit
class TestTaskCommand:
    def test_task_run_command_invokes_serve(self) -> None:
        cmd = windows.task_run_command(port=7613)
        assert sys.executable in cmd
        assert "-m mureo configure --serve --port 7613" in cmd

    def test_task_name_constant(self) -> None:
        assert windows.TASK_NAME == "MureoConfigure"


@pytest.mark.unit
class TestInstall:
    def test_install_creates_and_runs_task(self, home: Path) -> None:
        with patch.object(windows.subprocess, "run", return_value=_ok()) as mock_run:
            result = windows.install(home=home, port=7613)
        assert result.ok is True
        argvs = [c.args[0] for c in mock_run.call_args_list]
        flat = [tok for argv in argvs for tok in argv]
        assert "schtasks" in flat
        assert "/Create" in flat
        assert "/SC" in flat
        assert "ONLOGON" in flat
        assert "/F" in flat
        assert "/Run" in flat
        assert windows.TASK_NAME in flat
        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False

    def test_install_is_idempotent_with_force_flag(self, home: Path) -> None:
        """``/F`` overwrites an existing task, so re-install is clean."""
        with patch.object(windows.subprocess, "run", return_value=_ok()):
            first = windows.install(home=home, port=7613)
            second = windows.install(home=home, port=7613)
        assert first.ok is True
        assert second.ok is True

    def test_install_reports_error_on_nonzero_create(self, home: Path) -> None:
        with patch.object(windows.subprocess, "run", return_value=_fail("denied")):
            result = windows.install(home=home, port=7613)
        assert result.ok is False
        assert "denied" in (result.message or "")

    def test_install_handles_missing_schtasks(self, home: Path) -> None:
        with patch.object(
            windows.subprocess, "run", side_effect=FileNotFoundError("schtasks")
        ):
            result = windows.install(home=home, port=7613)
        assert result.ok is False
        assert result.message


@pytest.mark.unit
class TestUninstall:
    def test_uninstall_deletes_task(self, home: Path) -> None:
        # /Query (exists) then /Delete.
        with patch.object(
            windows.subprocess, "run", side_effect=[_ok(), _ok()]
        ) as mock_run:
            result = windows.uninstall(home=home)
        assert result.ok is True
        flat = [tok for c in mock_run.call_args_list for tok in c.args[0]]
        assert "/Delete" in flat
        assert windows.TASK_NAME in flat

    def test_uninstall_not_installed_is_clean_noop(self, home: Path) -> None:
        # /Query returns nonzero — task absent → no /Delete.
        with patch.object(
            windows.subprocess, "run", return_value=_fail("not found")
        ) as mock_run:
            result = windows.uninstall(home=home)
        assert result.ok is True
        flat = [tok for c in mock_run.call_args_list for tok in c.args[0]]
        assert "/Delete" not in flat

    def test_uninstall_handles_missing_schtasks(self, home: Path) -> None:
        with patch.object(
            windows.subprocess, "run", side_effect=FileNotFoundError("schtasks")
        ):
            result = windows.uninstall(home=home)
        assert result.ok is False
        assert result.message


@pytest.mark.unit
class TestStatus:
    def test_status_installed_and_running(self, home: Path) -> None:
        with (
            patch.object(windows.subprocess, "run", return_value=_ok()),
            patch.object(windows, "probe_mureo_instance", return_value=True),
        ):
            result = windows.status(home=home, port=7613)
        assert result.installed is True
        assert result.running is True
        assert result.url == "http://127.0.0.1:7613/"

    def test_status_not_installed(self, home: Path) -> None:
        with (
            patch.object(windows.subprocess, "run", return_value=_fail("absent")),
            patch.object(windows, "probe_mureo_instance", return_value=False),
        ):
            result = windows.status(home=home, port=7613)
        assert result.installed is False
        assert result.running is False

    def test_status_missing_schtasks_reports_not_installed(self, home: Path) -> None:
        with (
            patch.object(windows.subprocess, "run", side_effect=FileNotFoundError("x")),
            patch.object(windows, "probe_mureo_instance", return_value=False),
        ):
            result = windows.status(home=home, port=7613)
        assert result.installed is False
