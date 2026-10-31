"""Shared service-argv/command construction (#241 Phase 2).

``service_argv`` is consumed as a real list (launchd ``ProgramArguments``,
``subprocess``); ``service_command`` is the single-string form re-parsed by
systemd ``ExecStart`` / ``schtasks /TR``, where the executable MUST stay
quoted so a spaced install path (the Windows default) is not split.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mureo.web.service import SERVICE_ENVIRONMENT
from mureo.web.service._common import (
    service_argv,
    service_command,
    service_environment,
)


@pytest.mark.unit
class TestServiceArgv:
    def test_argv_is_python_m_mureo_configure_serve(self) -> None:
        argv = service_argv(port=7613)
        assert argv[1:] == ("-m", "mureo", "configure", "--serve", "--port", "7613")

    def test_port_is_coerced_to_str(self) -> None:
        # Pass a bool (an int subclass that is NOT already its str form) so
        # the assertion exercises the str(int(...)) coercion rather than a
        # value that would pass even as a no-op.
        assert service_argv(port=True)[-1] == "1"
        assert service_argv(port=7613)[-1] == "7613"


@pytest.mark.unit
class TestServiceCommand:
    def test_executable_is_quoted(self) -> None:
        """A spaced executable (Windows ``C:\\Program Files\\...``) must be
        double-quoted so systemd/schtasks do not split the path."""
        spaced = r"C:\Program Files\Python310\python.exe"
        with patch("mureo.web.service._common.sys.executable", spaced):
            cmd = service_command(port=7613)
        assert cmd.startswith(f'"{spaced}"')
        assert cmd == f'"{spaced}" -m mureo configure --serve --port 7613'

    def test_command_carries_the_serve_invocation(self) -> None:
        cmd = service_command(port=7613)
        assert "-m mureo configure --serve --port 7613" in cmd


@pytest.mark.unit
class TestServiceEnvironment:
    def test_carries_marker_and_installing_shell_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/opt/x/bin:/usr/bin")
        assert service_environment() == {
            "MUREO_MANAGED_SERVICE": "1",
            "PATH": "/opt/x/bin:/usr/bin",
        }

    def test_omits_path_when_unset_or_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PATH", raising=False)
        assert service_environment() == {"MUREO_MANAGED_SERVICE": "1"}
        monkeypatch.setenv("PATH", "")
        assert service_environment() == {"MUREO_MANAGED_SERVICE": "1"}

    def test_drops_empty_and_relative_path_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty or relative entry would resolve against the daemon's cwd."""
        monkeypatch.setenv("PATH", "/opt/x/bin::bin:./node_modules/.bin:/usr/bin")
        assert service_environment()["PATH"] == "/opt/x/bin:/usr/bin"

    def test_omits_path_when_no_absolute_entry_remains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", ":bin:.")
        assert service_environment() == {"MUREO_MANAGED_SERVICE": "1"}

    def test_does_not_mutate_the_shared_marker_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        service_environment()
        assert SERVICE_ENVIRONMENT == {"MUREO_MANAGED_SERVICE": "1"}
