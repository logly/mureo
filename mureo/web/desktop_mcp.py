"""Thin Claude Desktop ``mcpServers.mureo`` writer/remover.

Reuses the proven ``desktop_installer`` primitives (``_load_config`` /
``_atomic_write_config`` / ``_backup_config``) but writes only the
minimal ``mcpServers.mureo`` block — it deliberately does NOT call
``desktop_installer.install_desktop()`` (which also creates a
workspace, a wrapper script, an optional demo seed, and hard-raises
off macOS). The web ``/api/setup/basic`` flow has no workspace inputs
and must respect the ``host_paths`` non-macOS fallback (planner
HANDOFF Q1/Q6).

Every mutation is surgical: the loaded config is deep-copied and only
``mcpServers.mureo`` is set (install) or popped (remove). All other
``mcpServers`` entries and unrelated top-level keys are preserved
verbatim. Corrupt JSON, a non-object top level, a non-dict
``mcpServers``, and a symlinked config are all refused WITHOUT
overwriting the user's file. ``~/.mureo/credentials.json`` is never
read, written, or deleted.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from mureo.desktop_installer import (
    DesktopConfigCorruptError,
    _atomic_write_config,
    _backup_config,
    _load_config,
)
from mureo.web.host_paths import get_host_paths

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "install_desktop_mcp_block",
    "remove_desktop_mcp_block",
    "resolve_desktop_config_path",
]


def resolve_desktop_config_path(home: Path | None = None) -> Path:
    """Resolve the Claude Desktop config path via ``host_paths``.

    Uses ``get_host_paths("claude-desktop", home).settings_path`` rather
    than ``desktop_installer._macos_config_path()`` so the injected
    ``home`` is honoured (tests) and the non-macOS
    ``~/.claude/settings.json`` fallback is respected (no
    ``DesktopInstallUnsupportedPlatformError`` in the web flow).
    """
    return get_host_paths("claude-desktop", home=home).settings_path


def _read_servers(config_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the config and return ``(config, mcpServers)``.

    Raises ``DesktopConfigCorruptError`` on invalid/non-object JSON
    (via ``_load_config``) or when ``mcpServers`` is present but not a
    dict — without overwriting the file.
    """
    config = _load_config(config_path)
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise DesktopConfigCorruptError(
            f"Existing config at {config_path} has a non-object "
            "'mcpServers' value. Fix or remove it before re-running."
        )
    return config, servers


def install_desktop_mcp_block(
    config_path: Path, command: str, *, backup: bool = True
) -> bool:
    """Register the ``mcpServers.mureo`` block in the Desktop config.

    Returns ``True`` when the block was written, ``False`` when a
    ``mureo`` entry was already present (caller emits ``noop
    already_configured``). Raises ``DesktopConfigCorruptError`` on a
    corrupt config or a symlinked file, never overwriting the original.
    """
    config, servers = _read_servers(config_path)
    if "mureo" in servers:
        return False

    if backup and config_path.exists():
        _backup_config(config_path)

    merged = copy.deepcopy(config)
    merged_servers = dict(servers)
    merged_servers["mureo"] = {"command": command}
    merged["mcpServers"] = merged_servers
    _atomic_write_config(config_path, merged)
    return True


def remove_desktop_mcp_block(config_path: Path) -> bool:
    """Pop only the ``mcpServers.mureo`` key from the Desktop config.

    Returns ``True`` when the entry was removed, ``False`` when it was
    absent or the config file is missing (idempotent → caller emits
    ``noop not_installed``). Raises ``DesktopConfigCorruptError`` on a
    corrupt config without overwriting it.
    """
    if not config_path.exists():
        return False

    config, servers = _read_servers(config_path)
    if "mureo" not in servers:
        return False

    merged = copy.deepcopy(config)
    merged_servers = dict(servers)
    del merged_servers["mureo"]
    merged["mcpServers"] = merged_servers
    _atomic_write_config(config_path, merged)
    return True
