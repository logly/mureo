"""Shared PreToolUse credential-guard hook templates (#393).

Single source of truth for the guard hooks installed into Claude Code's
``~/.claude/settings.json`` and Codex's ``~/.codex/hooks.json``.  The two
installers previously carried copy-pasted templates, which is how the
non-blocking ``sys.exit(1)`` bug shipped to both hosts.

Blocking contract (identical for Claude Code and Codex): a PreToolUse hook
blocks by printing ``{"hookSpecificOutput": {"permissionDecision": "deny",
...}}`` to stdout and exiting 0, or by exiting 2 with the reason on stderr.
Any other non-zero exit — including 1 — is a *non-blocking* hook error and
the tool call proceeds.  The deny-JSON form is used here because an
interpreter crash (exit 1) can never be mistaken for an intentional block.

Two guards are installed:

* Path guard (``Read|Edit|Write|Grep|Glob|NotebookEdit``): resolves the
  tool's target path with ``os.path.realpath`` (after ``expanduser``) and
  denies when it lands inside ``~/.mureo`` — covering every file in the
  directory and closing the symlink/relative-path evasions of the old
  substring check.
* Bash guard: denies any command whose text references ``.mureo``.  A
  substring check is all a command string allows, but anchoring on the
  directory name (not ``credentials``) also catches wildcard forms like
  ``cat ~/.mureo/cred*``.

Both comparisons are case-folded: macOS and Windows filesystems are
case-insensitive by default, so ``~/.MUREO/credentials.json`` opens the
real file.  On case-sensitive filesystems this can only over-block (a
genuinely distinct ``~/.MUREO`` directory), never under-block — the right
direction for a guard.

The guard remains defense-in-depth, not the primary control: shell
indirection and encoded forms can still evade the Bash guard.  Real safety
comes from filesystem permissions on ``~/.mureo`` itself.

NOTE: the python payloads run inside double quotes on a shell command line
(``python3 -c "..."``), so they must not contain double quotes, ``$``,
backticks, backslashes, or newlines.  ``tests/test_credential_guard.py``
enforces this along with the blocking behavior.
"""

from __future__ import annotations

from typing import Any

# Unique identifier used to detect (and upgrade/remove) mureo-installed hooks.
GUARD_TAG = "[mureo-credential-guard]"

# Matchers are regexes over the tool name. PATH_TOOLS_MATCHER lists the
# Claude Code tools that receive a filesystem path; entries for tools a host
# does not expose (e.g. Codex has no Read tool) simply never fire.
PATH_TOOLS_MATCHER = "Read|Edit|Write|Grep|Glob|NotebookEdit"
BASH_MATCHER = "Bash"

# Characters allowed in a deny reason. The reason is interpolated into a
# single-quoted python literal inside a double-quoted shell command; anything
# outside this set (quotes, $, backticks, backslashes, braces, newlines...)
# could break parsing and turn the block into a fail-open exit-1 error —
# exactly the #393 failure mode.
_SAFE_REASON_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;~/-_"
)


def _deny_expr(reason: str) -> str:
    """A python expression that prints the PreToolUse deny JSON."""
    unsafe = set(reason) - _SAFE_REASON_CHARS
    if unsafe:
        raise ValueError(f"deny reason contains unsafe characters: {unsafe!r}")
    return (
        "print(json.dumps({'hookSpecificOutput':{'hookEventName':'PreToolUse',"
        "'permissionDecision':'deny','permissionDecisionReason':"
        f"'{reason}'}}}}))"
    )


_PATH_GUARD_CODE = (
    "import sys,json,os; "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "i=d.get('tool_input') or {}; "
    "p=str(i.get('file_path') or i.get('path') or i.get('notebook_path') or ''); "
    "b=os.path.realpath(os.path.expanduser('~/.mureo')).lower(); "
    "r=os.path.realpath(os.path.expanduser(p)).lower() if p else ''; "
    + _deny_expr("mureo credential guard: files under ~/.mureo are protected")
    + " if r==b or r.startswith(b+os.sep) else None"
)

_BASH_GUARD_CODE = (
    "import sys,json; "
    "d=json.loads(sys.stdin.read() or '{}'); "
    "c=str((d.get('tool_input') or {}).get('command') or ''); "
    + _deny_expr("mureo credential guard: commands referencing .mureo are blocked")
    + " if '.mureo' in c.lower() else None"
)


def path_guard_command() -> str:
    """The shell command for the path-based guard (Read/Edit/Write/Grep/Glob)."""
    return f'python3 -c "{_PATH_GUARD_CODE}" # {GUARD_TAG}'


def bash_guard_command() -> str:
    """The shell command for the Bash command-text guard."""
    return f'python3 -c "{_BASH_GUARD_CODE}" # {GUARD_TAG}'


def path_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the path guard."""
    return {
        "matcher": PATH_TOOLS_MATCHER,
        "hooks": [{"type": "command", "command": path_guard_command()}],
    }


def bash_guard_entry() -> dict[str, Any]:
    """A fresh PreToolUse entry for the Bash guard."""
    return {
        "matcher": BASH_MATCHER,
        "hooks": [{"type": "command", "command": bash_guard_command()}],
    }


def guard_entries() -> list[dict[str, Any]]:
    """Fresh copies of both guard entries, in install order.

    Fresh so that callers merging them into parsed user config never alias
    dicts across two install targets.
    """
    return [path_guard_entry(), bash_guard_entry()]


def is_guard_entry(entry: Any) -> bool:
    """True when ``entry`` is a mureo-tagged PreToolUse entry.

    Detection is scoped to the inner ``command`` field so a user's own entry
    whose matcher happens to contain the tag literal is never claimed.

    Matching is entry-level: installers drop the whole entry when any inner
    hook carries the tag. mureo only ever writes single-hook entries, so
    this is equivalent to the finer hook-level stripping that
    ``mureo.cli.settings_remove`` performs — it differs only on a
    hand-merged config where a user appended their own hook to a mureo
    entry.
    """
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(hook, dict) and GUARD_TAG in str(hook.get("command", ""))
        for hook in hooks
    )
