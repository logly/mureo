"""Atomic JSON merge / remove helpers for Claude Code's ``settings.json``.

Each public function:
- defaults ``settings_path`` to ``Path.home() / ".claude" / "settings.json"``
  computed *inside* the function so monkeypatched ``Path.home`` is honored
  by tests and by future re-homing of the user config directory;
- writes via a same-directory unpredictable ``tempfile``-allocated file
  followed by ``os.fsync`` + ``os.replace`` so a crash mid-write cannot
  corrupt the existing file and data is durably on disk before the rename;
- preserves unrelated top-level keys (``permissions`` etc.) and unrelated
  ``mcpServers`` entries (notably the native ``mureo`` block).

A separate writer (rather than reusing ``mureo.auth_setup.install_mcp_config``)
is intentional — the four existing ``setup`` commands continue to use the
older non-atomic writer; refactoring it is out of scope for Phase 1.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.providers.catalog import ProviderSpec

logger = logging.getLogger(__name__)


class ConfigWriteError(Exception):
    """Raised when ``settings.json`` cannot be safely updated.

    Used specifically when an existing file contains malformed JSON — we
    refuse to silently overwrite the file to protect user data.
    """


@dataclass(frozen=True)
class AddResult:
    """Outcome of an ``add_provider_to_claude_settings`` call."""

    changed: bool


@dataclass(frozen=True)
class RemoveResult:
    """Outcome of a ``remove_provider_from_claude_settings`` call."""

    changed: bool


def _default_settings_path() -> Path:
    """Return the default settings path (computed at call time)."""
    return Path.home() / ".claude" / "settings.json"


def _load_existing(settings_path: Path) -> dict[str, Any]:
    """Load ``settings.json`` as a dict, or return ``{}`` if absent.

    Raises:
        ConfigWriteError: when the existing file is malformed JSON. The
            exception message includes the path so the operator can locate
            and fix the file manually.
    """
    if not settings_path.exists():
        return {}
    try:
        text = settings_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigWriteError(
            f"failed to read existing settings at {settings_path}: {exc}"
        ) from exc
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigWriteError(
            f"existing settings file at {settings_path} is malformed JSON "
            f"(refusing to overwrite to protect user data): {exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ConfigWriteError(
            f"existing settings at {settings_path} is not a JSON object "
            f"(got {type(loaded).__name__}); refusing to overwrite."
        )
    return loaded


def _fsync_directory(parent: Path) -> None:
    """Best-effort ``fsync`` of ``parent`` so a rename is durable.

    POSIX requires ``fsync`` on the directory to flush a rename to disk.
    Not supported on Windows; ignore ``OSError`` there.
    """
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def _atomic_write_json(payload: dict[str, Any], settings_path: Path) -> None:
    """Serialize ``payload`` and atomically replace ``settings_path``.

    Uses :func:`tempfile.mkstemp` to allocate an unpredictable same-directory
    tmp file, sets its mode to ``0o600`` before writing, ``fsync``s the data
    to disk, then ``os.replace``s it into place. Best-effort ``fsync`` on the
    parent directory after the rename so the directory entry is durable too.
    On failure the tmp file is unlinked so no debris remains. The original
    ``settings_path`` (if any) is untouched until ``os.replace`` succeeds.
    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    # Allocate an unpredictable tmp file in the same directory as the target
    # so ``os.replace`` is guaranteed to be a rename within the same
    # filesystem (and therefore atomic on POSIX).
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=settings_path.name + ".",
        suffix=".tmp",
        dir=str(settings_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        # Restrict permissions BEFORE writing the data so the file is never
        # readable to other local users during the write/replace window.
        os.fchmod(tmp_fd, 0o600)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            tmp_fd = -1  # ownership transferred to ``fh``; do not close twice
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, settings_path)
        _fsync_directory(settings_path.parent)
    except (OSError, ValueError):
        # Clean up the tmp file on any FS-level failure so the directory
        # stays tidy. ``ValueError`` covers ``json.dumps`` having serialized
        # something unexpected (defensive — payload is built internally).
        try:
            if tmp_fd != -1:
                os.close(tmp_fd)
        except OSError:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to remove tmp file %s", tmp_path)
        raise


def add_provider_to_claude_settings(
    spec: ProviderSpec,
    *,
    settings_path: Path | None = None,
) -> AddResult:
    """Merge ``spec`` into ``settings.json`` atomically and idempotently.

    Args:
        spec: catalog entry to register.
        settings_path: override target path. Defaults to
            ``Path.home() / ".claude" / "settings.json"``.

    Returns:
        ``AddResult(changed=True)`` when the file was updated.
        ``AddResult(changed=False)`` when the existing entry already matches
        ``spec.mcp_server_config`` byte-for-byte (idempotent re-add).

    Raises:
        ConfigWriteError: existing settings file is malformed JSON.
    """
    target = settings_path or _default_settings_path()
    existing = _load_existing(target)

    mcp_servers_raw = existing.get("mcpServers")
    if mcp_servers_raw is None:
        mcp_servers: dict[str, Any] = {}
    elif isinstance(mcp_servers_raw, dict):
        mcp_servers = mcp_servers_raw
    else:
        raise ConfigWriteError(
            f"existing settings at {target} has a non-object 'mcpServers' "
            f"value (got {type(mcp_servers_raw).__name__}); refusing to "
            f"overwrite to protect user data."
        )

    # Normalize the catalog payload through a JSON round-trip so the
    # comparison key matches what would actually be written to disk:
    # ``_freeze_config`` converts nested lists to tuples for catalog
    # immutability, but JSON has no tuple type — the on-disk shape (and
    # the value re-read by ``_load_existing``) is always list-form. A
    # direct ``current == dict(spec.mcp_server_config)`` would compare
    # ``[..] != (..)`` and report ``changed=True`` on every re-add,
    # breaking the idempotency contract documented above.
    desired_config: dict[str, Any] = json.loads(
        json.dumps(dict(spec.mcp_server_config), ensure_ascii=False)
    )
    current = mcp_servers.get(spec.id)
    if current == desired_config:
        return AddResult(changed=False)

    mcp_servers[spec.id] = desired_config
    existing["mcpServers"] = mcp_servers

    _atomic_write_json(existing, target)
    return AddResult(changed=True)


def remove_provider_from_claude_settings(
    provider_id: str,
    *,
    settings_path: Path | None = None,
) -> RemoveResult:
    """Remove ``mcpServers[provider_id]`` from ``settings.json``.

    Idempotent: if the key is absent, returns ``RemoveResult(changed=False)``
    without rewriting the file.

    Raises:
        ConfigWriteError: existing settings file is malformed JSON.
    """
    target = settings_path or _default_settings_path()
    if not target.exists():
        return RemoveResult(changed=False)

    existing = _load_existing(target)
    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict) or provider_id not in mcp_servers:
        return RemoveResult(changed=False)

    del mcp_servers[provider_id]
    existing["mcpServers"] = mcp_servers
    _atomic_write_json(existing, target)
    return RemoveResult(changed=True)


def is_provider_installed(
    provider_id: str,
    *,
    settings_path: Path | None = None,
) -> bool:
    """Return True iff ``provider_id`` is registered in ``settings.json``.

    Returns False (does not raise) when the file is missing or malformed,
    so ``mureo providers list`` keeps working in degraded environments.
    """
    target = settings_path or _default_settings_path()
    if not target.exists():
        return False
    try:
        loaded = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(loaded, dict):
        return False
    mcp_servers = loaded.get("mcpServers")
    return isinstance(mcp_servers, dict) and provider_id in mcp_servers
