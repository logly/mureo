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
import tempfile
from pathlib import Path
from typing import Any

from mureo.cli.setup_cmd import _get_data_path

logger = logging.getLogger(__name__)


def _atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp file + rename).

    A crash mid-write leaves the original file intact, so the tag-based
    idempotency check cannot be defeated by half-written output.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------


_MCP_TAG = "[mureo-mcp-config]"
_GUARD_TAG = "[mureo-credential-guard]"

_MCP_CONFIG_BLOCK = f"""# >>> {_MCP_TAG} >>>
[mcp_servers.mureo]
command = "python"
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


def install_codex_credential_guard() -> Path | None:
    """Append PreToolUse hooks to ``~/.codex/hooks.json``.

    Existing hook entries are preserved. Returns the path on first
    install or ``None`` if the mureo tag is already present.
    """
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


# ---------------------------------------------------------------------------
# 3. Workflow commands (as Codex skills)
# ---------------------------------------------------------------------------


def _first_nonblank_line(text: str) -> str:
    """Return the first non-empty line of ``text``, stripped of whitespace."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _yaml_escape(value: str) -> str:
    """Escape a string for a YAML double-quoted scalar.

    YAML's double-quoted scalar interprets backslash escapes, so in
    addition to escaping ``\\`` and ``"`` we also need to guard against
    characters that would either (a) terminate the scalar prematurely —
    LF / CR / NEL / U+2028 / U+2029 are all treated as line breaks by
    YAML parsers — or (b) survive into the rendered description as raw
    control bytes. Any character outside printable ASCII/Unicode is
    emitted as ``\\xNN`` (for bytes < 0x100) or ``\\uNNNN`` so the
    frontmatter round-trips through any conformant YAML parser.
    """
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        # Safe: printable ASCII OR non-ASCII printable Unicode (minus the
        # line-separator set that YAML treats as a newline).
        if (0x20 <= code < 0x7F) or (code >= 0xA0 and code not in (0x2028, 0x2029)):
            out.append(ch)
        elif code <= 0xFF:
            out.append(f"\\x{code:02x}")
        else:
            out.append(f"\\u{code:04x}")
    return "".join(out)


def _build_command_skill(name: str, body: str) -> str:
    """Wrap a bundled command ``.md`` in Codex skill frontmatter.

    ``description`` is the first non-empty line of the source file so
    Codex's ``/skills`` picker can show a meaningful one-liner. The
    body is copied verbatim after the frontmatter terminator.
    """
    description = _yaml_escape(_first_nonblank_line(body)) or name
    return f'---\nname: {name}\ndescription: "{description}"\n---\n\n{body}'


def install_codex_command_skills(
    target_dir: Path | None = None,
) -> tuple[int, Path]:
    """Install bundled workflow commands as Codex skills.

    Codex CLI 0.117.0 (2026-03) stopped surfacing files placed in
    ``~/.codex/prompts/`` in the slash-command menu (Issue
    `openai/codex#15941 <https://github.com/openai/codex/issues/15941>`_).
    Custom prompts were deprecated in favor of skills, so mureo now
    wraps each bundled command into
    ``~/.codex/skills/<command>/SKILL.md`` with YAML frontmatter.
    Users invoke them with ``$daily-check`` or via the ``/skills``
    picker in Codex.

    Re-running also removes the matching legacy files from
    ``~/.codex/prompts/`` so stale copies don't show up as duplicates;
    user-authored prompts with names outside mureo's bundled set are
    left alone.
    """
    dest = target_dir or (Path.home() / ".codex" / "skills")
    dest.mkdir(parents=True, exist_ok=True)

    src = _get_data_path("commands")
    bundled_names: set[str] = set()
    count = 0
    for md_file in sorted(src.glob("*.md")):
        name = md_file.stem
        bundled_names.add(md_file.name)
        skill_dir = dest / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        skill_dir.mkdir(parents=True)
        body = md_file.read_text(encoding="utf-8")
        (skill_dir / "SKILL.md").write_text(
            _build_command_skill(name, body), encoding="utf-8"
        )
        count += 1

    # Legacy cleanup: remove stale ~/.codex/prompts/<bundled>.md from prior
    # installs so the user sees a clean Codex state. Skip symlinks — they
    # imply the operator intentionally pointed a bundled name at their own
    # file (e.g. a dotfiles repo), and silently unlinking loses the link
    # even though the target stays intact.
    legacy_prompts = Path.home() / ".codex" / "prompts"
    if legacy_prompts.is_dir():
        for legacy_file in legacy_prompts.iterdir():
            if (
                legacy_file.is_file()
                and not legacy_file.is_symlink()
                and legacy_file.name in bundled_names
            ):
                try:
                    legacy_file.unlink()
                except OSError:
                    logger.warning(
                        "Could not remove stale legacy prompt: %s", legacy_file
                    )

    return count, dest


# ---------------------------------------------------------------------------
# 4. Skills
# ---------------------------------------------------------------------------


def install_codex_skills(target_dir: Path | None = None) -> tuple[int, Path]:
    """Copy bundled skill directories to ``~/.codex/skills/``."""
    dest = target_dir or (Path.home() / ".codex" / "skills")
    dest.mkdir(parents=True, exist_ok=True)

    src = _get_data_path("skills")
    count = 0
    for skill_dir in sorted(src.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            target = dest / skill_dir.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(skill_dir, target)
            count += 1
    return count, dest
