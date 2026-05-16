"""Centralised filesystem paths for each supported Claude application host."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_HOSTS: tuple[str, ...] = ("claude-code", "claude-desktop")


@dataclass(frozen=True)
class HostPaths:
    """Resolved filesystem locations for one host."""

    host: str
    settings_path: Path
    skills_dir: Path
    commands_dir: Path
    credentials_path: Path
    # File the host actually reads MCP servers from. For Claude Code this
    # is ``~/.claude.json`` (user scope, managed by ``claude mcp``) — NOT
    # ``settings.json`` (hooks/permissions/env only, never consulted for
    # MCP discovery). For Claude Desktop it is the same
    # ``claude_desktop_config.json`` as ``settings_path``.
    mcp_registry_path: Path


def _claude_code_paths(home: Path) -> HostPaths:
    return HostPaths(
        host="claude-code",
        settings_path=home / ".claude" / "settings.json",
        skills_dir=home / ".claude" / "skills",
        commands_dir=home / ".claude" / "commands",
        credentials_path=home / ".mureo" / "credentials.json",
        mcp_registry_path=home / ".claude.json",
    )


def _claude_desktop_settings_path(home: Path) -> Path:
    """Resolve Claude Desktop's per-platform config path.

    On macOS the canonical location is
    ``~/Library/Application Support/Claude/claude_desktop_config.json``.
    On Linux/Windows the install kit falls back to the Claude Code
    style ``~/.claude/settings.json`` — Claude Desktop's per-platform
    layout is not finalised on those OSes.
    """
    system = platform.system()
    if system == "Darwin":
        return (
            home
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return home / ".claude" / "settings.json"


def _claude_desktop_paths(home: Path) -> HostPaths:
    desktop_config = _claude_desktop_settings_path(home)
    return HostPaths(
        host="claude-desktop",
        settings_path=desktop_config,
        skills_dir=home / ".claude" / "skills",
        commands_dir=home / ".claude" / "commands",
        credentials_path=home / ".mureo" / "credentials.json",
        # Desktop reads MCP from the same claude_desktop_config.json.
        mcp_registry_path=desktop_config,
    )


def get_host_paths(host: str, home: Path | None = None) -> HostPaths:
    """Return the path bundle for ``host``.

    Unknown hosts raise ``ValueError``. ``home`` defaults to
    ``Path.home()`` but tests inject a tmp dir.
    """
    if host not in SUPPORTED_HOSTS:
        raise ValueError(f"unsupported host: {host!r}")
    resolved_home = home if home is not None else Path.home()
    if host == "claude-code":
        return _claude_code_paths(resolved_home)
    return _claude_desktop_paths(resolved_home)
