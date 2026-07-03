"""Install-kit helpers for OpenAI Codex CLI.

Layers installed, mirroring the Claude Code setup:

1. MCP server config in ``~/.codex/config.toml`` (append-only tagged block)
2. Credential guard PreToolUse hooks in ``~/.codex/hooks.json``
3. Workflow commands as Codex skills at ``~/.codex/skills/<command>/SKILL.md``
   (previously written to ``~/.codex/prompts/*.md`` — deprecated in
   codex-cli 0.117.0, see openai/codex#15941). Invoked via
   ``$<command>`` or the ``/skills`` picker.
4. Shared mureo skills as ``~/.codex/skills/mureo-*/``

Idempotency is enforced via tag markers (``[mureo-mcp-config]`` /
``[mureo-credential-guard]``) so re-running ``mureo setup codex`` is
safe and never duplicates entries.

The credential guard is defense-in-depth, not the primary control for
credential protection — the same substring-matching limitations as the
Claude Code guard apply (symlinks, indirect paths, encoded forms, and
shell indirection can all evade the match). Real safety comes from
filesystem permissions on ``~/.mureo/credentials.json`` itself.

The ``hooks.json`` schema (top-level ``PreToolUse`` list) follows the
Codex CLI hook format documented at
https://developers.openai.com/codex/hooks and is compatible with the
matcher / hooks structure reused by ``hatayama/codex-hooks``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from mureo.cli.setup_cmd import _get_data_path

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically and durably (temp + fsync +
    rename).

    A crash mid-write leaves the original file intact, so the tag-based
    idempotency check cannot be defeated by half-written output. fsync before
    the rename (and a best-effort directory fsync after) so a power loss just
    after ``os.replace`` cannot leave a zero-length config.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------


_MCP_TAG = "[mureo-mcp-config]"
_GUARD_TAG = "[mureo-credential-guard]"

# Use the interpreter running `mureo setup codex` (sys.executable), the env
# where mureo IS installed — a bare "python" resolves to a system Python that
# may not have mureo installed (or not exist at all on modern macOS/Linux that
# ship only python3), so the mureo MCP would silently fail to start. Mirrors
# the Claude Code fix in auth_setup._MCP_SERVER_CONFIG. json.dumps yields a
# TOML-safe basic string (correct quoting/backslash escaping on Windows paths).
_MCP_CONFIG_BLOCK = f"""# >>> {_MCP_TAG} >>>
[mcp_servers.mureo]
command = {json.dumps(sys.executable)}
args = ["-m", "mureo.mcp"]
# <<< {_MCP_TAG} <<<
"""


def _credential_guard_hooks() -> list[dict[str, Any]]:
    """Two PreToolUse entries (Read + Bash) that block credential reads.

    Structurally mirrors ``mureo.auth_setup._CREDENTIAL_GUARD_HOOK_*`` but
    written here to keep the Codex install surface self-contained.
    """
    read_cmd = (
        'python3 -c "'
        "import sys,json; "
        "d=json.loads(sys.stdin.read()); "
        "p=d.get('tool_input',{}).get('file_path',''); "
        "sys.exit(1) if 'credentials' in p and '.mureo' in p else sys.exit(0)"
        f'" # {_GUARD_TAG}'
    )
    bash_cmd = (
        'python3 -c "'
        "import sys,json; "
        "d=json.loads(sys.stdin.read()); "
        "c=d.get('tool_input',{}).get('command',''); "
        "sys.exit(1) if '.mureo/credentials' in c or "
        "('.mureo' in c and 'credentials' in c) else sys.exit(0)"
        f'" # {_GUARD_TAG}'
    )
    return [
        {
            "matcher": "Read",
            "hooks": [{"type": "command", "command": read_cmd}],
        },
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": bash_cmd}],
        },
    ]


# ---------------------------------------------------------------------------
# 1. MCP config
# ---------------------------------------------------------------------------


class CodexMcpConflictError(Exception):
    """Existing ``[mcp_servers.mureo]`` block lacks the mureo tag marker.

    Appending would create a duplicate TOML key that Codex will reject.
    The installer refuses to guess whether the existing block is stale,
    hand-authored, or from a prior mureo version; the operator must
    reconcile it manually.
    """


def install_codex_mcp_config() -> Path | None:
    """Append a tagged ``[mcp_servers.mureo]`` block to ``~/.codex/config.toml``.

    Preserves all existing content. Returns the config path on first
    install, or ``None`` when the tagged block is already present
    (idempotent). Raises :class:`CodexMcpConflictError` if an untagged
    ``[mcp_servers.mureo]`` already exists so a TOML duplicate-key error
    surfaces at setup time, not the first Codex launch.
    """
    config = Path.home() / ".codex" / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)

    existing = config.read_text(encoding="utf-8") if config.exists() else ""
    if _MCP_TAG in existing:
        logger.info("Codex MCP config already installed: %s", config)
        return None
    if "[mcp_servers.mureo]" in existing:
        raise CodexMcpConflictError(
            f"An untagged [mcp_servers.mureo] block already exists in {config}. "
            "Remove it and re-run `mureo setup codex`, or add the tag marker "
            f"(# >>> {_MCP_TAG} >>> ... # <<< {_MCP_TAG} <<<) to adopt it."
        )

    separator = "" if existing.endswith("\n") or not existing else "\n"
    _atomic_write_text(config, existing + separator + _MCP_CONFIG_BLOCK)
    logger.info("Codex MCP config installed: %s", config)
    return config


# ---------------------------------------------------------------------------
# 2. Credential guard
# ---------------------------------------------------------------------------


def install_codex_credential_guard(hooks_file: Path | None = None) -> Path | None:
    """Append PreToolUse hooks to ``~/.codex/hooks.json``.

    Existing hook entries are preserved. Returns the path on first
    install or ``None`` if the mureo tag is already present.

    ``hooks_file`` overrides the target (the home-aware configure-UI flow
    passes ``<home>/.codex/hooks.json``); it defaults to the real
    ``~/.codex/hooks.json`` for the ``mureo setup codex`` CLI.
    """
    if hooks_file is None:
        hooks_file = Path.home() / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if hooks_file.exists():
        try:
            parsed = json.loads(hooks_file.read_text(encoding="utf-8"))
            existing = parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not parse %s — refusing to overwrite", hooks_file)
            return None

    pre_tool_use_raw = existing.get("PreToolUse", [])
    if not isinstance(pre_tool_use_raw, list):
        logger.warning(
            "hooks.json 'PreToolUse' is not a list (got %s) — refusing to overwrite",
            type(pre_tool_use_raw).__name__,
        )
        return None
    pre_tool_use: list[dict[str, Any]] = pre_tool_use_raw
    existing["PreToolUse"] = pre_tool_use

    for entry in pre_tool_use:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []):
            if _GUARD_TAG in hook.get("command", ""):
                logger.info("Codex credential guard already installed: %s", hooks_file)
                return None

    pre_tool_use.extend(_credential_guard_hooks())

    _atomic_write_text(
        hooks_file,
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
    )
    logger.info("Codex credential guard installed: %s", hooks_file)
    return hooks_file


def remove_codex_credential_guard(hooks_file: Path | None = None) -> Path | None:
    """Drop the mureo-tagged PreToolUse hooks from ``~/.codex/hooks.json``.

    The inverse of :func:`install_codex_credential_guard`: removes only the
    entries whose command carries the ``[mureo-credential-guard]`` tag, and
    preserves every other hook. Returns the path when something was removed,
    or ``None`` when the file is absent/unparseable or no tagged entry was
    present (idempotent). ``hooks_file`` mirrors the install override.
    """
    if hooks_file is None:
        hooks_file = Path.home() / ".codex" / "hooks.json"
    if not hooks_file.exists():
        return None
    try:
        parsed = json.loads(hooks_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not parse %s — refusing to overwrite", hooks_file)
        return None
    if not isinstance(parsed, dict):
        return None
    pre_tool_use = parsed.get("PreToolUse")
    if not isinstance(pre_tool_use, list):
        return None

    def _is_mureo_entry(entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        return any(
            _GUARD_TAG in hook.get("command", "")
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict)
        )

    kept = [entry for entry in pre_tool_use if not _is_mureo_entry(entry)]
    if len(kept) == len(pre_tool_use):
        return None  # nothing tagged — idempotent no-op
    parsed["PreToolUse"] = kept
    _atomic_write_text(
        hooks_file,
        json.dumps(parsed, indent=2, ensure_ascii=False) + "\n",
    )
    logger.info("Codex credential guard removed: %s", hooks_file)
    return hooks_file


# ---------------------------------------------------------------------------
# 3. Skills (operational + foundation)
# ---------------------------------------------------------------------------
#
# Phase 3 (PR #77) merged slash commands into skills, so the legacy
# `install_codex_command_skills` helper that wrapped commands as Codex
# skills is no longer needed — `install_codex_skills` below copies the
# unified skill set (10 operational + foundation) directly from
# `mureo/_data/skills/` into `~/.codex/skills/`.


def install_codex_skills(target_dir: Path | None = None) -> tuple[int, Path]:
    """Copy bundled skill directories to ``~/.codex/skills/``."""
    dest = target_dir or (Path.home() / ".codex" / "skills")
    dest.mkdir(parents=True, exist_ok=True)

    src = _get_data_path("skills")
    count = 0
    for skill_dir in sorted(src.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            target = dest / skill_dir.name
            _replace_dest(target)
            shutil.copytree(skill_dir, target)
            count += 1
    return count, dest


def _replace_dest(path: Path) -> None:
    """Remove ``path`` in preparation for a fresh copytree/mkdir.

    ``shutil.rmtree`` refuses symlinks by design (to avoid nuking the
    link's target). Operators who have symlinked a bundled skill name
    at their own dev copy would otherwise see ``mureo setup codex``
    crash on re-run with ``OSError: Cannot call rmtree on a symbolic
    link``. Unlink the symlink and leave the target intact.
    """
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)
