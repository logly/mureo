"""Shared service-argv/command construction (#241 Phase 2).

``service_argv`` is consumed as a real list (launchd ``ProgramArguments``,
``subprocess``); ``service_command`` is the single-string form re-parsed by
systemd ``ExecStart`` / ``schtasks /TR``, where the executable MUST stay
quoted so a spaced install path (the Windows default) is not split.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mureo.web.service._common import service_argv, service_command


@pytest.mark.unit
class TestServiceArgv:
    def test_argv_is_python_m_mureo_configure_serve(self) -> None:
        argv = service_argv(port=7613)
        assert argv[1:] == ("-m", "mureo", "configure", "--serve", "--port", "7613")

    def test_port_is_coerced_to_str(self) -> None:
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
