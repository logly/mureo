"""Symmetric ``remove_*`` counterparts of ``install_mcp_config`` /
``install_credential_guard``.

Lives in a new module (rather than growing the already-oversize
``mureo.auth_setup``) per CTO decision #1 in the planner HANDOFF
``feat-web-config-ui-phase1-uninstall.md``.

Both removers:

- default ``settings_path`` to ``Path.home() / ".claude" / "settings.json"``
  computed *inside* the function so monkeypatched ``Path.home`` is honored;
- write via :func:`mureo.core.atomic_json.atomic_write_json` (a same-directory
  unpredictable ``tempfile`` + ``os.fsync`` + ``os.replace``) so a crash
  mid-write cannot corrupt the existing file and data is durably on disk
  before the rename;
- refuse to silently overwrite malformed JSON: reads go through
  :func:`mureo.core.atomic_json.load_existing_json`, which raises
  ``ConfigWriteError`` — the operator must repair the file manually;
- are idempotent: a second call on an already-removed state returns
  ``RemoveResult(changed=False)`` without rewriting the file.

``ConfigWriteError`` is re-exported from :mod:`mureo.core.atomic_json` for
import compatibility (callers and tests import it from this module).
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # noqa: S404 - fixed argv, shell=False (claude mcp remove)
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mureo.core.atomic_json import (
    ConfigWriteError,
    atomic_write_json,
    load_existing_json,
)
from mureo.credential_guard import GUARD_TAG as _MUREO_HOOK_TAG

logger = logging.getLogger(__name__)

__all__ = [
    "ConfigWriteError",
    "RemoveResult",
    "remove_mcp_config",
    "remove_credential_guard",
]


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
    if not target.exists():
        return RemoveResult(changed=False)
    existing = load_existing_json(target)

    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        return RemoveResult(changed=False)
    if "mureo" not in mcp_servers:
        return RemoveResult(changed=False)

    mcp_servers.pop("mureo")
    atomic_write_json(existing, target)
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
    if not target.exists():
        return RemoveResult(changed=False)
    existing = load_existing_json(target)

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
    atomic_write_json(existing, target)
    logger.info("mureo credential guard hooks removed from %s", target)
    return RemoveResult(changed=True)
