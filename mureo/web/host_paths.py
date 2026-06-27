"""Centralised filesystem paths for each supported AI-agent host."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_HOSTS: tuple[str, ...] = ("claude-code", "claude-desktop", "codex")


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

    Per-OS canonical locations:

    - **macOS** (``Darwin``):
      ``~/Library/Application Support/Claude/claude_desktop_config.json``
    - **Windows**: ``%APPDATA%\\Claude\\claude_desktop_config.json``
      (i.e. ``~/AppData/Roaming/Claude/claude_desktop_config.json``)
    - **Linux**: Claude Desktop has no Linux build, so the Claude
      Code-style ``~/.claude/settings.json`` best-effort fallback is
      kept (nothing on Linux reads this anyway).
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
    if system == "Windows":
        # %APPDATA% defaults to ~/AppData/Roaming; deriving it from the
        # injected ``home`` keeps this testable and honours a custom
        # home, mirroring the macOS branch's home-relative approach.
        return home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
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


def _codex_paths(home: Path) -> HostPaths:
    """Resolve OpenAI Codex CLI paths.

    Codex reads MCP servers from ``~/.codex/config.toml`` (TOML, written
    by :mod:`mureo.web.codex_mcp`) — so ``settings_path`` and
    ``mcp_registry_path`` are the SAME file, unlike the Claude hosts. Skills
    live under ``~/.codex/skills`` (Codex's own skill dir, not the shared
    ``~/.claude/skills``); ``commands_dir`` is carried for signature
    symmetry only (Codex surfaces workflows as skills, not commands).
    ``credentials.json`` is the shared ``~/.mureo`` store.
    """
    config = home / ".codex" / "config.toml"
    return HostPaths(
        host="codex",
        settings_path=config,
        skills_dir=home / ".codex" / "skills",
        commands_dir=home / ".codex" / "commands",
        credentials_path=home / ".mureo" / "credentials.json",
        mcp_registry_path=config,
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
    if host == "codex":
        return _codex_paths(resolved_home)
    return _claude_desktop_paths(resolved_home)
