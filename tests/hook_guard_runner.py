"""Test helper: execute a credential-guard hook command like the agent harness.

Claude Code / Codex run PreToolUse hook commands through a shell with the
tool-call JSON on stdin.  The guard commands mureo installs have the shape::

    python3 -c "<single-line python>" # [mureo-credential-guard]

Re-running the embedded payload through ``sys.executable`` keeps these tests
portable (no bash dependency on the Windows CI job) while exercising the
exact code a shell would hand to ``python3 -c``.  ``extract_python_code``
also asserts the payload is shell-safe: because the code sits inside double
quotes on the command line, any ``"``, ``$``, backtick, or backslash would
change meaning under a POSIX shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_COMMAND_RE = re.compile(r'^python3 -c "(?P<code>[^"]*)" # \[mureo-credential-guard\]$')

_SHELL_HAZARDS = ("$", "`", "\\", "\n")


def extract_python_code(command: str) -> str:
    """Return the python payload from a guard command, refusing unsafe shapes."""
    match = _COMMAND_RE.match(command)
    if match is None:
        raise AssertionError(f"unexpected guard command shape: {command!r}")
    code = match.group("code")
    for hazard in _SHELL_HAZARDS:
        if hazard in code:
            raise AssertionError(
                f"guard payload contains shell-unsafe character {hazard!r}: {code!r}"
            )
    return code


def run_guard(
    command: str,
    tool_input: dict[str, Any],
    home: Path,
    tool_name: str = "Read",
) -> subprocess.CompletedProcess[str]:
    """Run a guard command with ``tool_input`` on stdin and ``home`` as $HOME.

    ``HOME`` (POSIX) and ``USERPROFILE`` (Windows) are both overridden so the
    guard's ``os.path.expanduser('~/.mureo')`` resolves inside the test tree.
    """
    code = extract_python_code(command)
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [sys.executable, "-c", code],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def deny_decision(proc: subprocess.CompletedProcess[str]) -> str | None:
    """Return the ``permissionDecision`` emitted by a guard run, if any."""
    if not proc.stdout.strip():
        return None
    output = json.loads(proc.stdout)
    decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
    return str(decision) if decision is not None else None
