"""Symmetric ``remove_*`` counterparts of ``install_mcp_config`` /
``install_credential_guard``.

Lives in a new module (rather than growing the already-oversize
``mureo.auth_setup``) per CTO decision #1 in the planner HANDOFF
``feat-web-config-ui-phase1-uninstall.md``.

Both removers:

- default ``settings_path`` to ``Path.home() / ".claude" / "settings.json"``
  computed *inside* the function so monkeypatched ``Path.home`` is honored;
- write via a same-directory unpredictable ``tempfile``-allocated file
  followed by ``os.fsync`` + ``os.replace`` so a crash mid-write cannot
  corrupt the existing file and data is durably on disk before the rename;
- refuse to silently overwrite malformed JSON (``ConfigWriteError`` is
  raised — the operator must repair the file manually);
- are idempotent: a second call on an already-removed state returns
  ``RemoveResult(changed=False)`` without rewriting the file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess  # noqa: S404 - fixed argv, shell=False (claude mcp remove)
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Unique identifier the credential-guard hooks carry in their ``command``
# field. Must match the literal used by ``mureo.auth_setup`` so removal is
# tag-driven (not heuristic).
_MUREO_HOOK_TAG = "[mureo-credential-guard]"


class ConfigWriteError(Exception):
    """Raised when ``settings.json`` cannot be safely updated.

    Used specifically when an existing file contains malformed JSON — we
    refuse to silently overwrite the file to protect user data.
    """


@dataclass(frozen=True)
class RemoveResult:
    """Outcome envelope for a remove call."""

    changed: bool


def _default_settings_path() -> Path:
    """Return the default settings path (computed at call time)."""
    return Path.home() / ".claude" / "settings.json"


def _default_user_mcp_path() -> Path:
    """File ``claude mcp ... --scope user`` persists to (``~/.claude.json``).

    User-scope MCP servers live here, NOT in ``settings.json`` — see
    ``mureo.auth_setup._claude_user_config_path``.
    """
    return Path.home() / ".claude.json"


def _load_existing(settings_path: Path) -> dict[str, Any] | None:
    """Load ``settings.json`` as a dict, or ``None`` if the file is absent.

    Raises:
        ConfigWriteError: when the existing file is malformed JSON or not a
            JSON object. The exception message includes the path so the
            operator can locate and fix the file manually.
    """
    if not settings_path.exists():
        return None
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
    """Best-effort ``fsync`` of ``parent`` so a rename is durable."""
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
    to disk, then ``os.replace``s it into place. On failure the tmp file is
    unlinked so no debris remains.
    """
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=settings_path.name + ".",
        suffix=".tmp",
        dir=str(settings_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        os.fchmod(tmp_fd, 0o600)
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            tmp_fd = -1  # ownership transferred to ``fh``
            fh.write(serialized)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, settings_path)
        _fsync_directory(settings_path.parent)
    except (OSError, ValueError):
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


def remove_mcp_config(*, settings_path: Path | None = None) -> RemoveResult:
    """Unregister the mureo MCP server (Claude Code *user* scope).

    Symmetric with ``auth_setup.install_mcp_config(scope="global")``:
    user-scope servers live in ``~/.claude.json`` (managed by the
    ``claude`` CLI), NOT in ``~/.claude/settings.json``.

    When ``settings_path`` is omitted and the ``claude`` binary is on
    PATH, delegation to ``claude mcp remove mureo --scope user`` lets
    Claude Code mutate its own live config file safely. Otherwise the
    ``mureo`` key is popped from the target's root ``mcpServers`` via the
    same atomic, malformed-JSON-refusing writer.

    Idempotent: an already-removed state returns
    ``RemoveResult(changed=False)`` without rewriting anything.

    Args:
        settings_path: override target file. Defaults to
            ``~/.claude.json`` (and forces file mode, skipping the CLI).

    Raises:
        ConfigWriteError: target file is malformed JSON, or the
            ``claude`` CLI is present but the remove command failed.
    """
    if settings_path is None:
        claude_bin = shutil.which("claude")
        if claude_bin is not None:
            probe = subprocess.run(  # noqa: S603 - fixed argv, shell=False
                [claude_bin, "mcp", "get", "mureo"],
                check=False,
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                return RemoveResult(changed=False)  # not registered
            removed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
                [claude_bin, "mcp", "remove", "mureo", "--scope", "user"],
                check=False,
                capture_output=True,
                text=True,
            )
            if removed.returncode != 0:
                raise ConfigWriteError(
                    "claude mcp remove failed (rc="
                    f"{removed.returncode}): {removed.stderr.strip()}"
                )
            logger.info("mureo MCP unregistered (user scope) via claude CLI")
            return RemoveResult(changed=True)

    target = settings_path or _default_user_mcp_path()
    existing = _load_existing(target)
    if existing is None:
        return RemoveResult(changed=False)

    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        return RemoveResult(changed=False)
    if "mureo" not in mcp_servers:
        return RemoveResult(changed=False)

    mcp_servers.pop("mureo")
    _atomic_write_json(existing, target)
    logger.info("mureo MCP block removed from %s", target)
    return RemoveResult(changed=True)


def _is_mureo_hook(hook_entry: Any) -> bool:
    """Return ``True`` if ``hook_entry`` is one of mureo's tagged hooks.

    The tag must appear inside the ``command`` field — a coincidental
    occurrence in any other field (``matcher`` etc.) is ignored.
    """
    if not isinstance(hook_entry, dict):
        return False
    command = hook_entry.get("command")
    return isinstance(command, str) and _MUREO_HOOK_TAG in command


def _strip_mureo_hooks(
    pre_tool_use: list[Any],
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(filtered, changed)`` after dropping mureo's tagged hooks.

    Each PreToolUse entry is itself an object with an inner ``hooks`` list.
    When the entry's inner list contains *only* mureo hooks, the entry is
    pruned entirely. When it contains a mix, only the mureo entries are
    stripped from the inner list (the user-owned ones survive in their
    original order within the same entry).
    """
    filtered: list[dict[str, Any]] = []
    changed = False
    for entry in pre_tool_use:
        if not isinstance(entry, dict):
            filtered.append(entry)
            continue
        inner = entry.get("hooks")
        if not isinstance(inner, list):
            filtered.append(entry)
            continue
        kept_inner = [h for h in inner if not _is_mureo_hook(h)]
        if len(kept_inner) == len(inner):
            filtered.append(entry)
            continue
        changed = True
        if not kept_inner:
            # Entry was only mureo hooks — prune the entry entirely.
            continue
        new_entry = dict(entry)
        new_entry["hooks"] = kept_inner
        filtered.append(new_entry)
    return filtered, changed


def remove_credential_guard(*, settings_path: Path | None = None) -> RemoveResult:
    """Remove mureo's credential-guard hook entries from PreToolUse.

    Only entries whose inner ``command`` field contains ``_MUREO_HOOK_TAG``
    are removed. Unrelated PreToolUse hooks are preserved in their original
    order, even ones whose ``matcher`` happens to coincidentally contain the
    tag literal.

    Idempotent: a second call returns ``RemoveResult(changed=False)`` without
    rewriting the file.

    Args:
        settings_path: override target path. Defaults to
            ``Path.home() / ".claude" / "settings.json"``.

    Raises:
        ConfigWriteError: existing settings file is malformed JSON.
    """
    target = settings_path or _default_settings_path()
    existing = _load_existing(target)
    if existing is None:
        return RemoveResult(changed=False)

    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        return RemoveResult(changed=False)
    pre_tool_use = hooks.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return RemoveResult(changed=False)

    filtered, changed = _strip_mureo_hooks(pre_tool_use)
    if not changed:
        return RemoveResult(changed=False)

    hooks["PreToolUse"] = filtered
    _atomic_write_json(existing, target)
    logger.info("mureo credential guard hooks removed from %s", target)
    return RemoveResult(changed=True)
