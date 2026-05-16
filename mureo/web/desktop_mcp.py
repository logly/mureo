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
from collections.abc import Mapping
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
    "install_desktop_server_block",
    "remove_desktop_mcp_block",
    "remove_desktop_server_block",
    "resolve_desktop_config_path",
    "set_mureo_disable_env_desktop",
    "unset_mureo_disable_env_desktop",
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


def _normalize_block(server_config: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy a (possibly ``MappingProxyType``) block to plain JSON.

    Catalog blocks are frozen ``MappingProxyType`` with tuple-ified
    nested lists; ``copy.deepcopy`` round-trips them to mutable
    dicts/lists so the on-disk JSON matches the dict shape callers and
    tests assert (and the idempotency check compares like for like).
    """
    return copy.deepcopy(_unfreeze(server_config))


def _unfreeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _unfreeze(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_unfreeze(v) for v in value]
    return value


def install_desktop_server_block(
    config_path: Path,
    server_id: str,
    server_config: Mapping[str, Any],
    *,
    backup: bool = True,
) -> bool:
    """Surgically register ``mcpServers[server_id]`` in the Desktop config.

    Handles arbitrary block shapes verbatim — both the hosted_http
    ``{"type": "http", "url": ...}`` shape (no command/args) and the
    pipx/npm ``{"command": ..., "args": [...]}`` shape. The loaded
    config is deep-copied and only ``mcpServers[server_id]`` is set; all
    other ``mcpServers`` entries and unrelated top-level keys are
    preserved. The write is atomic (tempfile + ``os.replace``).

    Returns ``True`` when the block was written, ``False`` (no rewrite,
    file byte-identical) when ``server_id`` is already present with an
    EQUAL block (idempotent). Raises ``DesktopConfigCorruptError`` on a
    corrupt config, a non-dict ``mcpServers``, or a symlinked file,
    never overwriting the original.
    """
    block = _normalize_block(server_config)
    config, servers = _read_servers(config_path)
    if servers.get(server_id) == block:
        return False

    if backup and config_path.exists():
        _backup_config(config_path)

    merged = copy.deepcopy(config)
    merged_servers = dict(servers)
    merged_servers[server_id] = block
    merged["mcpServers"] = merged_servers
    _atomic_write_config(config_path, merged)
    return True


def set_mureo_disable_env_desktop(config_path: Path, env_var: str) -> bool:
    """Set ``mcpServers.mureo.env[env_var] = "1"`` in the Desktop config.

    Used when an official hosted provider is chosen on the Desktop host
    so the surviving mureo MCP stops exposing its now-redundant,
    unauthenticated tool family for that platform (mirrors the Claude
    Code ``set_mureo_disable_env``). Only mureo's OWN block is touched —
    not the Connectors-managed remote MCP — so there is no DCR/OAuth
    constraint here. Atomic, surgical, all other entries preserved.

    Returns ``True`` when the file was rewritten, ``False`` for a no-op
    (no ``mcpServers.mureo`` block to update, or the var is already
    ``"1"``). Raises ``DesktopConfigCorruptError`` (via ``_read_servers``)
    on a corrupt config without overwriting it.
    """
    config, servers = _read_servers(config_path)
    mureo_block = servers.get("mureo")
    if not isinstance(mureo_block, dict):
        return False
    env = mureo_block.get("env")
    if env is not None and not isinstance(env, dict):
        raise DesktopConfigCorruptError(
            f"'mcpServers.mureo.env' in {config_path} is not an object. "
            "Fix or remove it before re-running."
        )
    if isinstance(env, dict) and env.get(env_var) == "1":
        return False

    if config_path.exists():
        _backup_config(config_path)
    merged = copy.deepcopy(config)
    merged_block = dict(merged["mcpServers"]["mureo"])
    merged_env = dict(merged_block.get("env") or {})
    merged_env[env_var] = "1"
    merged_block["env"] = merged_env
    merged["mcpServers"]["mureo"] = merged_block
    _atomic_write_config(config_path, merged)
    return True


def unset_mureo_disable_env_desktop(config_path: Path, env_var: str) -> bool:
    """Pop ``mcpServers.mureo.env[env_var]`` from the Desktop config.

    The inverse of :func:`set_mureo_disable_env_desktop` — re-enables
    mureo's own tool family for the platform when the official provider
    is removed. Drops an emptied ``env`` object so the block stays
    clean. Idempotent ``False`` no-op when the block, the ``env``, or
    the key is absent.
    """
    config, servers = _read_servers(config_path)
    mureo_block = servers.get("mureo")
    if not isinstance(mureo_block, dict):
        return False
    env = mureo_block.get("env")
    if not isinstance(env, dict) or env_var not in env:
        return False

    if config_path.exists():
        _backup_config(config_path)
    merged = copy.deepcopy(config)
    merged_block = dict(merged["mcpServers"]["mureo"])
    merged_env = dict(merged_block.get("env") or {})
    merged_env.pop(env_var, None)
    if merged_env:
        merged_block["env"] = merged_env
    else:
        merged_block.pop("env", None)
    merged["mcpServers"]["mureo"] = merged_block
    _atomic_write_config(config_path, merged)
    return True


def remove_desktop_server_block(config_path: Path, server_id: str) -> bool:
    """Pop only ``mcpServers[server_id]`` from the Desktop config.

    Returns ``True`` when the entry was removed, ``False`` when it was
    absent or the config file is missing (idempotent). Raises
    ``DesktopConfigCorruptError`` on a corrupt config without
    overwriting it.
    """
    if not config_path.exists():
        return False

    config, servers = _read_servers(config_path)
    if server_id not in servers:
        return False

    merged = copy.deepcopy(config)
    merged_servers = dict(servers)
    del merged_servers[server_id]
    merged["mcpServers"] = merged_servers
    _atomic_write_config(config_path, merged)
    return True


def install_desktop_mcp_block(
    config_path: Path,
    command: str,
    args: list[str],
    *,
    backup: bool = True,
) -> bool:
    """Register the ``mcpServers.mureo`` block in the Desktop config.

    Thin ``server_id="mureo"`` delegation to
    :func:`install_desktop_server_block`. Writes the MCP launcher's
    required ``{"command": <exe>, "args": [...]}`` shape — ``command``
    is the bare executable and ``args`` is a separate list, matching the
    proven Claude Code ``auth_setup._MCP_SERVER_CONFIG`` schema.
    ``command`` must NOT be a pre-joined ``"<exe> -m mureo.mcp"`` string
    (Claude Desktop would try to spawn an executable literally named
    that and fail). The produced ``mcpServers.mureo`` bytes are
    byte-for-byte identical to the prior direct implementation.

    Back-compat contract (unchanged): returns ``False`` when ANY
    ``mureo`` entry is already present (presence-based, not
    block-equality) so a stale/legacy block is never silently
    overwritten — the caller emits ``noop already_configured``.
    """
    if config_path.exists():
        _, servers = _read_servers(config_path)
        if "mureo" in servers:
            return False
    return install_desktop_server_block(
        config_path,
        "mureo",
        {"command": command, "args": list(args)},
        backup=backup,
    )


def remove_desktop_mcp_block(config_path: Path) -> bool:
    """Pop only the ``mcpServers.mureo`` key from the Desktop config.

    Thin ``server_id="mureo"`` delegation to
    :func:`remove_desktop_server_block`.
    """
    return remove_desktop_server_block(config_path, "mureo")
