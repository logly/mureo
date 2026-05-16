"""Path resolution for ``mureo.web.host_paths``.

Covers ``get_host_paths`` per-host branching, the ``HostPaths``
frozen dataclass shape, ``SUPPORTED_HOSTS`` allow-list, and
platform-conditional macOS vs Linux/Windows paths for Claude Desktop.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from mureo.web.host_paths import (
    SUPPORTED_HOSTS,
    HostPaths,
    get_host_paths,
)


@pytest.mark.unit
class TestSupportedHosts:
    def test_supported_hosts_is_tuple(self) -> None:
        assert isinstance(SUPPORTED_HOSTS, tuple)

    def test_only_claude_code_and_desktop(self) -> None:
        assert set(SUPPORTED_HOSTS) == {"claude-code", "claude-desktop"}


@pytest.mark.unit
class TestHostPathsDataclass:
    def test_is_frozen(self) -> None:
        assert dataclasses.is_dataclass(HostPaths)
        paths = HostPaths(
            host="claude-code",
            settings_path=Path("/x/s"),
            skills_dir=Path("/x/k"),
            commands_dir=Path("/x/c"),
            credentials_path=Path("/x/cr"),
            mcp_registry_path=Path("/x/m"),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            paths.host = "claude-desktop"  # type: ignore[misc]

    def test_holds_all_six_fields(self) -> None:
        paths = HostPaths(
            host="claude-code",
            settings_path=Path("/x/s.json"),
            skills_dir=Path("/x/sk"),
            commands_dir=Path("/x/cmd"),
            credentials_path=Path("/x/cr.json"),
            mcp_registry_path=Path("/x/m.json"),
        )
        assert paths.host == "claude-code"
        assert paths.settings_path == Path("/x/s.json")
        assert paths.skills_dir == Path("/x/sk")
        assert paths.commands_dir == Path("/x/cmd")
        assert paths.credentials_path == Path("/x/cr.json")
        assert paths.mcp_registry_path == Path("/x/m.json")


@pytest.mark.unit
class TestGetHostPathsClaudeCode:
    def test_claude_code_resolves_under_dot_claude(self, tmp_path: Path) -> None:
        paths = get_host_paths("claude-code", home=tmp_path)
        assert paths.host == "claude-code"
        assert paths.settings_path == tmp_path / ".claude" / "settings.json"
        assert paths.skills_dir == tmp_path / ".claude" / "skills"
        assert paths.commands_dir == tmp_path / ".claude" / "commands"
        assert paths.credentials_path == tmp_path / ".mureo" / "credentials.json"
        # MCP discovery file is ~/.claude.json (user scope), NOT
        # ~/.claude/settings.json — the crux of the registration fix.
        assert paths.mcp_registry_path == tmp_path / ".claude.json"

    def test_claude_code_uses_home_default_when_none(self) -> None:
        paths = get_host_paths("claude-code")
        assert paths.settings_path == Path.home() / ".claude" / "settings.json"
        assert paths.mcp_registry_path == Path.home() / ".claude.json"


@pytest.mark.unit
class TestGetHostPathsClaudeDesktopMacOS:
    def test_macos_uses_application_support_path(self, tmp_path: Path) -> None:
        with patch("mureo.web.host_paths.platform.system", return_value="Darwin"):
            paths = get_host_paths("claude-desktop", home=tmp_path)
        expected = (
            tmp_path
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
        assert paths.settings_path == expected

    def test_macos_shares_skills_and_commands_dirs_with_claude_code(
        self, tmp_path: Path
    ) -> None:
        with patch("mureo.web.host_paths.platform.system", return_value="Darwin"):
            paths = get_host_paths("claude-desktop", home=tmp_path)
        assert paths.skills_dir == tmp_path / ".claude" / "skills"
        assert paths.commands_dir == tmp_path / ".claude" / "commands"
        # Desktop reads MCP from the same claude_desktop_config.json.
        assert paths.mcp_registry_path == paths.settings_path


@pytest.mark.unit
class TestGetHostPathsClaudeDesktopLinuxWindows:
    @pytest.mark.parametrize("system", ["Linux", "Windows"])
    def test_non_macos_falls_back_to_dot_claude_settings(
        self, tmp_path: Path, system: str
    ) -> None:
        with patch("mureo.web.host_paths.platform.system", return_value=system):
            paths = get_host_paths("claude-desktop", home=tmp_path)
        assert paths.settings_path == tmp_path / ".claude" / "settings.json"


@pytest.mark.unit
class TestGetHostPathsRejectsUnknownHost:
    @pytest.mark.parametrize(
        "host",
        ["", "vscode", "cursor", "Claude-Code", "claude_code", "../etc"],
    )
    def test_unknown_host_raises_value_error(self, host: str, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsupported host"):
            get_host_paths(host, home=tmp_path)


@pytest.mark.unit
class TestHostPathsCredentialsLocation:
    """credentials.json must always live under ``~/.mureo/`` regardless
    of host — the credential store is mureo-owned, not Claude-owned."""

    @pytest.mark.parametrize("host", list(SUPPORTED_HOSTS))
    def test_credentials_under_dot_mureo_for_every_host(
        self, host: str, tmp_path: Path
    ) -> None:
        paths = get_host_paths(host, home=tmp_path)
        assert paths.credentials_path == tmp_path / ".mureo" / "credentials.json"
