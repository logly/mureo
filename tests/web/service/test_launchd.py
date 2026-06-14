"""macOS launchd backend for ``mureo service`` (#241 Phase 2 — Part C).

The macOS auto-start backend writes a per-user LaunchAgent plist at
``~/Library/LaunchAgents/io.mureo.configure.plist`` and bootstraps it with
``launchctl`` so the headless configure daemon runs at login (and is
restarted if it dies). These tests pin:

* plist CONTENT — label, ``ProgramArguments`` (``-m mureo configure
  --serve --port 7613``), ``RunAtLoad`` / ``KeepAlive``, log paths;
* ``install`` writes the file to the injected dir and runs the right
  ``launchctl bootstrap`` argv (fixed argv, ``shell=False``);
* ``uninstall`` runs ``launchctl bootout`` and removes the file, and is a
  clean no-op when nothing is installed;
* graceful degradation — a missing ``launchctl`` (FileNotFoundError) or a
  nonzero exit yields a structured error, never a traceback.

All ``subprocess`` and file writes are mocked / redirected to ``tmp_path``;
no real ``launchctl`` runs and ``~/Library`` is never touched.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.web.service import launchd

if TYPE_CHECKING:
    from pathlib import Path


def _ok() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / "Library" / "LaunchAgents").mkdir(parents=True)
    (h / ".mureo").mkdir(parents=True)
    return h


@pytest.mark.unit
class TestPlistContent:
    def test_plist_path_under_launchagents(self, home: Path) -> None:
        path = launchd.plist_path(home)
        assert path == home / "Library" / "LaunchAgents" / "io.mureo.configure.plist"

    def test_plist_has_label_and_program_arguments(self, home: Path) -> None:
        data = launchd.build_plist(home, port=7613)
        parsed = plistlib.loads(data)
        assert parsed["Label"] == "io.mureo.configure"
        args = parsed["ProgramArguments"]
        assert args[0] == sys.executable
        assert args[1:] == [
            "-m",
            "mureo",
            "configure",
            "--serve",
            "--port",
            "7613",
        ]

    def test_plist_runs_at_load_and_keeps_alive(self, home: Path) -> None:
        parsed = plistlib.loads(launchd.build_plist(home, port=7613))
        assert parsed["RunAtLoad"] is True
        assert parsed["KeepAlive"] is True

    def test_plist_stamps_managed_service_env(self, home: Path) -> None:
        """The managed-service marker tells the daemon ``KeepAlive`` will
        relaunch it, so it may exit-to-restart after a self-upgrade."""
        parsed = plistlib.loads(launchd.build_plist(home, port=7613))
        assert parsed["EnvironmentVariables"]["MUREO_MANAGED_SERVICE"] == "1"

    def test_plist_redirects_stdout_and_stderr(self, home: Path) -> None:
        parsed = plistlib.loads(launchd.build_plist(home, port=7613))
        assert parsed["StandardOutPath"] == str(home / ".mureo" / "configure.log")
        assert parsed["StandardErrorPath"] == str(home / ".mureo" / "configure.err")


@pytest.mark.unit
class TestInstall:
    def test_install_writes_plist_and_bootstraps(self, home: Path) -> None:
        with patch.object(launchd.subprocess, "run", return_value=_ok()) as mock_run:
            result = launchd.install(home=home, port=7613)
        path = launchd.plist_path(home)
        assert path.exists(), "plist not written"
        parsed = plistlib.loads(path.read_bytes())
        assert parsed["Label"] == "io.mureo.configure"
        assert result.ok is True
        # The loader argv must be the launchctl bootstrap call (fixed argv).
        argvs = [c.args[0] for c in mock_run.call_args_list]
        flat = [tok for argv in argvs for tok in argv]
        assert "launchctl" in flat
        assert "bootstrap" in flat or "load" in flat
        # shell=False on every call.
        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False

    def test_install_is_idempotent_overwrite(self, home: Path) -> None:
        path = launchd.plist_path(home)
        path.write_text("stale", encoding="utf-8")
        with patch.object(launchd.subprocess, "run", return_value=_ok()):
            result = launchd.install(home=home, port=7613)
        assert result.ok is True
        parsed = plistlib.loads(path.read_bytes())
        assert parsed["Label"] == "io.mureo.configure"

    def test_install_reports_error_on_nonzero_exit(self, home: Path) -> None:
        with patch.object(launchd.subprocess, "run", return_value=_fail("denied")):
            result = launchd.install(home=home, port=7613)
        assert result.ok is False
        assert "denied" in (result.message or "")

    def test_install_handles_missing_launchctl(self, home: Path) -> None:
        with patch.object(
            launchd.subprocess, "run", side_effect=FileNotFoundError("launchctl")
        ):
            result = launchd.install(home=home, port=7613)
        assert result.ok is False
        assert result.message

    def test_install_retries_until_job_sticks(self, home: Path) -> None:
        """``launchctl bootout`` is async: a bootstrap can 'succeed' yet leave
        nothing loaded. Install must re-bootstrap until the job is confirmed
        loaded (regression for a re-install that silently killed the service)."""
        print_calls = {"n": 0}

        def fake_run(argv: list[str], **kwargs: object) -> object:
            if "print" in argv:  # _is_loaded probe
                print_calls["n"] += 1
                # Not loaded on the first check; loaded after one retry.
                return _ok() if print_calls["n"] >= 2 else _fail("could not find")
            return _ok()  # bootout / bootstrap succeed

        with (
            patch.object(launchd.subprocess, "run", side_effect=fake_run),
            patch.object(launchd.time, "sleep") as mock_sleep,
        ):
            result = launchd.install(home=home, port=7613)
        assert result.ok is True
        assert print_calls["n"] >= 2, "did not re-check after a non-sticking bootstrap"
        mock_sleep.assert_called()  # it backed off before retrying

    def test_install_does_not_retry_a_hard_bootstrap_failure(self, home: Path) -> None:
        """A real bootstrap error returns immediately (no retry loop / sleep)."""
        with (
            patch.object(launchd.subprocess, "run", return_value=_fail("denied")),
            patch.object(launchd.time, "sleep") as mock_sleep,
        ):
            result = launchd.install(home=home, port=7613)
        assert result.ok is False
        assert "denied" in (result.message or "")
        mock_sleep.assert_not_called()

    def test_install_fails_if_job_never_sticks(self, home: Path) -> None:
        """If a bootstrap that returns 0 never actually loads, install exhausts
        its retries and reports failure — not a false 'ok'."""

        def fake_run(argv: list[str], **kwargs: object) -> object:
            return _fail("could not find") if "print" in argv else _ok()

        with (
            patch.object(launchd.subprocess, "run", side_effect=fake_run),
            patch.object(launchd.time, "sleep"),
        ):
            result = launchd.install(home=home, port=7613)
        assert result.ok is False
        assert "did not stay loaded" in (result.message or "")


@pytest.mark.unit
class TestUninstall:
    def test_uninstall_bootouts_and_removes(self, home: Path) -> None:
        path = launchd.plist_path(home)
        path.write_text("placeholder", encoding="utf-8")
        with patch.object(launchd.subprocess, "run", return_value=_ok()) as mock_run:
            result = launchd.uninstall(home=home)
        assert result.ok is True
        assert not path.exists(), "plist not removed"
        flat = [tok for c in mock_run.call_args_list for tok in c.args[0]]
        assert "launchctl" in flat
        assert "bootout" in flat or "unload" in flat

    def test_uninstall_not_installed_is_clean_noop(self, home: Path) -> None:
        with patch.object(launchd.subprocess, "run", return_value=_ok()) as mock_run:
            result = launchd.uninstall(home=home)
        assert result.ok is True
        # Nothing to stop — no subprocess required.
        mock_run.assert_not_called()

    def test_uninstall_swallows_unload_failure(self, home: Path) -> None:
        """A nonzero bootout (already-stopped) still removes the file."""
        path = launchd.plist_path(home)
        path.write_text("placeholder", encoding="utf-8")
        with patch.object(launchd.subprocess, "run", return_value=_fail("not loaded")):
            result = launchd.uninstall(home=home)
        assert not path.exists()
        assert result.ok is True


@pytest.mark.unit
class TestStatus:
    def test_status_installed_and_running(self, home: Path) -> None:
        launchd.plist_path(home).write_text("x", encoding="utf-8")
        with patch.object(launchd, "probe_mureo_instance", return_value=True):
            result = launchd.status(home=home, port=7613)
        assert result.installed is True
        assert result.running is True
        assert result.url == "http://127.0.0.1:7613/"

    def test_status_installed_not_running(self, home: Path) -> None:
        launchd.plist_path(home).write_text("x", encoding="utf-8")
        with patch.object(launchd, "probe_mureo_instance", return_value=False):
            result = launchd.status(home=home, port=7613)
        assert result.installed is True
        assert result.running is False

    def test_status_not_installed(self, home: Path) -> None:
        with patch.object(launchd, "probe_mureo_instance", return_value=False):
            result = launchd.status(home=home, port=7613)
        assert result.installed is False
        assert result.running is False
