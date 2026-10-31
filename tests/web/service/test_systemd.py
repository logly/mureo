"""Linux systemd --user backend for ``mureo service`` (#241 Phase 2).

The Linux auto-start backend writes a per-user systemd unit at
``~/.config/systemd/user/mureo-configure.service`` and enables it with
``systemctl --user`` so the headless configure daemon runs at login. These
tests pin:

* unit CONTENT — ``ExecStart`` (``-m mureo configure --serve --port
  7613``), ``Restart=always``, ``WantedBy=default.target``;
* ``install`` writes the unit then runs ``daemon-reload`` + ``enable
  --now`` (fixed argv, ``shell=False``);
* ``uninstall`` runs ``disable --now`` and removes the unit, and is a
  clean no-op when nothing is installed;
* graceful degradation — missing ``systemctl`` / nonzero exit → structured
  error, never a traceback.

All ``subprocess`` and writes are mocked / redirected to ``tmp_path``.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mureo.web.service import systemd

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _ok() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


def _fail(stderr: str = "boom") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / ".config" / "systemd" / "user").mkdir(parents=True)
    (h / ".mureo").mkdir(parents=True)
    return h


@pytest.mark.unit
class TestUnitContent:
    def test_unit_path_under_systemd_user(self, home: Path) -> None:
        path = systemd.unit_path(home)
        assert path == home / ".config" / "systemd" / "user" / "mureo-configure.service"

    def test_unit_execstart_invokes_serve(self, home: Path) -> None:
        unit = systemd.build_unit(port=7613)
        assert sys.executable in unit
        assert "-m mureo configure --serve --port 7613" in unit

    def test_unit_restart_always(self, home: Path) -> None:
        assert "Restart=always" in systemd.build_unit(port=7613)

    def test_unit_stamps_managed_service_env(self, home: Path) -> None:
        """Marker so the daemon knows Restart=always will relaunch it and may
        exit-to-restart after a self-upgrade."""
        assert "Environment=MUREO_MANAGED_SERVICE=1" in systemd.build_unit(port=7613)

    def test_unit_records_installing_shell_path(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A systemd user unit does not inherit the login shell's PATH, so
        the unit keeps it for ``pipx`` / ``npm`` lookups (#966)."""
        monkeypatch.setenv("PATH", "/opt/x/bin:/usr/bin")
        lines = systemd.build_unit(port=7613).splitlines()
        assert "Environment=PATH=/opt/x/bin:/usr/bin" in lines
        assert "Environment=MUREO_MANAGED_SERVICE=1" in lines

    def test_unit_quotes_a_path_with_spaces(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/Applications/My Tools/bin:/usr/bin")
        lines = systemd.build_unit(port=7613).splitlines()
        assert 'Environment="PATH=/Applications/My Tools/bin:/usr/bin"' in lines

    def test_unit_escapes_quotes_and_backslashes_in_path(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", '/opt/a"b\\c/bin')
        lines = systemd.build_unit(port=7613).splitlines()
        assert 'Environment="PATH=/opt/a\\"b\\\\c/bin"' in lines

    def test_unit_quotes_a_path_with_a_single_quote(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """systemd treats ``'`` as a quote, so the value is double-quoted."""
        monkeypatch.setenv("PATH", "/opt/it's/bin:/usr/bin")
        lines = systemd.build_unit(port=7613).splitlines()
        assert 'Environment="PATH=/opt/it\'s/bin:/usr/bin"' in lines

    def test_unit_escapes_newline_and_tab_in_path(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A raw newline would end the directive, so it is written ``\\n``."""
        monkeypatch.setenv("PATH", "/opt/a\nb/bin:/opt/c\td/bin:/opt/e\rf/bin")
        unit = systemd.build_unit(port=7613)
        lines = unit.splitlines()
        assert (
            'Environment="PATH=/opt/a\\nb/bin:/opt/c\\td/bin:/opt/e\\rf/bin"' in lines
        )
        assert "\t" not in unit and "\r" not in unit
        assert not any(line.startswith("b/bin") for line in lines)

    def test_unit_escapes_percent_specifiers_in_path(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """systemd expands ``%`` specifiers in ``Environment=``, so a literal
        ``%`` is written ``%%``."""
        monkeypatch.setenv("PATH", "/opt/100%/bin:/usr/bin")
        lines = systemd.build_unit(port=7613).splitlines()
        assert "Environment=PATH=/opt/100%%/bin:/usr/bin" in lines

    def test_unit_omits_path_when_shell_has_none(
        self, home: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PATH", raising=False)
        assert "PATH=" not in systemd.build_unit(port=7613)

    def test_unit_wantedby_default_target(self, home: Path) -> None:
        assert "WantedBy=default.target" in systemd.build_unit(port=7613)


@pytest.mark.unit
class TestInstall:
    def test_install_writes_unit_and_enables(self, home: Path) -> None:
        with patch.object(systemd.subprocess, "run", return_value=_ok()) as mock_run:
            result = systemd.install(home=home, port=7613)
        path = systemd.unit_path(home)
        assert path.exists()
        assert "Restart=always" in path.read_text(encoding="utf-8")
        assert result.ok is True
        flat = [tok for c in mock_run.call_args_list for tok in c.args[0]]
        assert "systemctl" in flat
        assert "--user" in flat
        assert "daemon-reload" in flat
        assert "enable" in flat
        assert "--now" in flat
        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False

    def test_install_is_idempotent_overwrite(self, home: Path) -> None:
        path = systemd.unit_path(home)
        path.write_text("stale", encoding="utf-8")
        with patch.object(systemd.subprocess, "run", return_value=_ok()):
            result = systemd.install(home=home, port=7613)
        assert result.ok is True
        assert "ExecStart" in path.read_text(encoding="utf-8")

    def test_install_reports_error_on_nonzero_exit(self, home: Path) -> None:
        with patch.object(systemd.subprocess, "run", return_value=_fail("nope")):
            result = systemd.install(home=home, port=7613)
        assert result.ok is False
        assert "nope" in (result.message or "")

    def test_install_handles_missing_systemctl(self, home: Path) -> None:
        with patch.object(
            systemd.subprocess, "run", side_effect=FileNotFoundError("systemctl")
        ):
            result = systemd.install(home=home, port=7613)
        assert result.ok is False
        assert result.message

    @staticmethod
    def _run_with_active(
        active: bool, restart: subprocess.CompletedProcess[str] | None = None
    ) -> tuple[list[list[str]], Callable[..., object]]:
        calls: list[list[str]] = []

        def fake_run(argv: list[str], **kwargs: object) -> object:
            calls.append(argv)
            if "is-active" in argv:
                return _ok() if active else _fail("inactive")
            if "restart" in argv and restart is not None:
                return restart
            return _ok()

        return calls, fake_run

    def test_install_fresh_unit_is_not_restarted(self, home: Path) -> None:
        calls, fake_run = self._run_with_active(False)
        with patch.object(systemd.subprocess, "run", side_effect=fake_run):
            result = systemd.install(home=home, port=7613)
        assert result.ok is True
        assert result.message == "enabled"
        assert not any("restart" in argv for argv in calls)

    def test_install_restarts_a_running_unit(self, home: Path) -> None:
        """``enable --now`` leaves a running unit as it is, so the rewritten
        unit only takes effect after a restart."""
        calls, fake_run = self._run_with_active(True)
        with patch.object(systemd.subprocess, "run", side_effect=fake_run):
            result = systemd.install(home=home, port=7613)
        assert result.ok is True
        assert result.message == "restarted"
        enable = ["systemctl", "--user", "enable", "--now", systemd.UNIT_NAME]
        restart = ["systemctl", "--user", "restart", systemd.UNIT_NAME]
        assert calls.index(restart) > calls.index(enable)

    def test_install_reports_restart_failure(self, home: Path) -> None:
        _, fake_run = self._run_with_active(True, restart=_fail("restart boom"))
        with patch.object(systemd.subprocess, "run", side_effect=fake_run):
            result = systemd.install(home=home, port=7613)
        assert result.ok is False
        assert result.message == "restart boom"


@pytest.mark.unit
class TestUninstall:
    def test_uninstall_disables_and_removes(self, home: Path) -> None:
        path = systemd.unit_path(home)
        path.write_text("placeholder", encoding="utf-8")
        with patch.object(systemd.subprocess, "run", return_value=_ok()) as mock_run:
            result = systemd.uninstall(home=home)
        assert result.ok is True
        assert not path.exists()
        flat = [tok for c in mock_run.call_args_list for tok in c.args[0]]
        assert "disable" in flat
        assert "--now" in flat

    def test_uninstall_not_installed_is_clean_noop(self, home: Path) -> None:
        with patch.object(systemd.subprocess, "run", return_value=_ok()) as mock_run:
            result = systemd.uninstall(home=home)
        assert result.ok is True
        mock_run.assert_not_called()

    def test_uninstall_swallows_disable_failure(self, home: Path) -> None:
        path = systemd.unit_path(home)
        path.write_text("placeholder", encoding="utf-8")
        with patch.object(systemd.subprocess, "run", return_value=_fail("inactive")):
            result = systemd.uninstall(home=home)
        assert not path.exists()
        assert result.ok is True


@pytest.mark.unit
class TestStatus:
    def test_status_installed_and_running(self, home: Path) -> None:
        systemd.unit_path(home).write_text("x", encoding="utf-8")
        with patch.object(systemd, "probe_mureo_instance", return_value=True):
            result = systemd.status(home=home, port=7613)
        assert result.installed is True
        assert result.running is True
        assert result.url == "http://127.0.0.1:7613/"

    def test_status_not_installed(self, home: Path) -> None:
        with patch.object(systemd, "probe_mureo_instance", return_value=False):
            result = systemd.status(home=home, port=7613)
        assert result.installed is False
        assert result.running is False


@pytest.mark.unit
class TestRestart:
    """``restart`` runs ``systemctl --user restart`` on the installed unit."""

    def _write_unit(self, home: Path) -> None:
        path = systemd.unit_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd.build_unit(port=7613), encoding="utf-8")

    def test_restart_runs_systemctl_restart(self, home: Path) -> None:
        self._write_unit(home)
        with patch.object(systemd.subprocess, "run", return_value=_ok()) as mock_run:
            result = systemd.restart(home=home, port=7613)
        assert result.ok
        assert result.message == "restarted"
        argvs = [c.args[0] for c in mock_run.call_args_list]
        assert ["systemctl", "--user", "restart", systemd.UNIT_NAME] in argvs

    def test_restart_not_installed_is_clear_error(self, home: Path) -> None:
        with patch.object(systemd.subprocess, "run", return_value=_ok()) as mock_run:
            result = systemd.restart(home=home, port=7613)
        assert not result.ok
        assert "not installed" in result.message
        mock_run.assert_not_called()

    def test_restart_reports_error_on_nonzero_exit(self, home: Path) -> None:
        self._write_unit(home)
        with patch.object(systemd.subprocess, "run", return_value=_fail("nope")):
            result = systemd.restart(home=home, port=7613)
        assert not result.ok
        assert "nope" in result.message

    def test_restart_handles_missing_systemctl(self, home: Path) -> None:
        self._write_unit(home)
        with patch.object(
            systemd.subprocess, "run", side_effect=FileNotFoundError("systemctl")
        ):
            result = systemd.restart(home=home, port=7613)
        assert not result.ok
        assert "systemctl not found" in result.message
