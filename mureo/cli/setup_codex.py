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

The credential guard templates are shared with the Claude Code installer
via :mod:`mureo.credential_guard` (see that module for the blocking
contract and evasion limitations). The guard is defense-in-depth, not the
primary control — real safety comes from filesystem permissions on
``~/.mureo`` itself.

The ``hooks.json`` schema nests the event lists under a top-level
``hooks`` key (``{"hooks": {"PreToolUse": [...]}}``), matching the Codex
CLI hook format documented at https://developers.openai.com/codex/hooks
(same shape as Claude's settings.json). Earlier mureo versions wrote a
top-level ``PreToolUse`` list that Codex never loads; install/remove
migrate mureo's own tagged entries out of that legacy location (#393).
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

from mureo import credential_guard
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
_GUARD_TAG = credential_guard.GUARD_TAG

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
    """The shared PreToolUse guard entries (path tools + Bash).

    Identical to the Claude Code install — the templates live in
    :mod:`mureo.credential_guard` so a blocking-behavior fix can never
    again land on one host and miss the other (#393).
    """
    return credential_guard.guard_entries()


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
    """Install the PreToolUse guard into ``~/.codex/hooks.json``.

    Entries land under the nested ``{"hooks": {"PreToolUse": [...]}}``
    location Codex actually loads. Foreign hook entries are preserved
    everywhere; mureo's own tagged entries are upgraded in place, including
    any stranded in the legacy top-level ``PreToolUse`` list an older mureo
    wrote (#393). Returns the path when the file changed or ``None`` when
    the guard is already current (or the file could not be parsed).

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

    changed = False

    # Legacy top-level list: strip mureo's own tagged entries (they migrate
    # to the nested location below); foreign entries stay where they are.
    legacy = existing.get("PreToolUse")
    legacy_kept: list[Any] = []
    if legacy is not None:
        if not isinstance(legacy, list):
            logger.warning(
                "hooks.json 'PreToolUse' is not a list (got %s) — "
                "refusing to overwrite",
                type(legacy).__name__,
            )
            return None
        legacy_kept = [e for e in legacy if not credential_guard.is_guard_entry(e)]
        changed = changed or len(legacy_kept) != len(legacy)

    hooks_obj = existing.get("hooks", {})
    if not isinstance(hooks_obj, dict):
        logger.warning(
            "hooks.json 'hooks' is not an object (got %s) — refusing to overwrite",
            type(hooks_obj).__name__,
        )
        return None
    pre_tool_use = hooks_obj.get("PreToolUse", [])
    if not isinstance(pre_tool_use, list):
        logger.warning(
            "hooks.json 'hooks.PreToolUse' is not a list (got %s) — "
            "refusing to overwrite",
            type(pre_tool_use).__name__,
        )
        return None

    kept = [e for e in pre_tool_use if not credential_guard.is_guard_entry(e)]
    desired = kept + _credential_guard_hooks()
    changed = changed or desired != pre_tool_use
    if not changed:
        logger.info("Codex credential guard already installed: %s", hooks_file)
        return None

    if legacy is not None:
        if legacy_kept:
            existing["PreToolUse"] = legacy_kept
        else:
            existing.pop("PreToolUse", None)
    existing["hooks"] = hooks_obj
    hooks_obj["PreToolUse"] = desired

    _atomic_write_text(
        hooks_file,
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
    )
    logger.info("Codex credential guard installed: %s", hooks_file)
    return hooks_file


def remove_codex_credential_guard(hooks_file: Path | None = None) -> Path | None:
    """Drop the mureo-tagged PreToolUse hooks from ``~/.codex/hooks.json``.

    The inverse of :func:`install_codex_credential_guard`: removes only the
    entries whose command carries the ``[mureo-credential-guard]`` tag —
    from both the nested ``hooks.PreToolUse`` location and the legacy
    top-level list — and preserves every other hook. Returns the path when
    something was removed, or ``None`` when the file is absent/unparseable
    or no tagged entry was present (idempotent). ``hooks_file`` mirrors the
    install override.
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

    changed = False

    legacy = parsed.get("PreToolUse")
    if isinstance(legacy, list):
        legacy_kept = [e for e in legacy if not credential_guard.is_guard_entry(e)]
        if len(legacy_kept) != len(legacy):
            parsed["PreToolUse"] = legacy_kept
            changed = True

    hooks_obj = parsed.get("hooks")
    if isinstance(hooks_obj, dict):
        nested = hooks_obj.get("PreToolUse")
        if isinstance(nested, list):
            nested_kept = [e for e in nested if not credential_guard.is_guard_entry(e)]
            if len(nested_kept) != len(nested):
                hooks_obj["PreToolUse"] = nested_kept
                changed = True

    if not changed:
        return None  # nothing tagged — idempotent no-op
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
