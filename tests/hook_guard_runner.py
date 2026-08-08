"""Test helper: execute a credential-guard hook command like the agent harness.

Claude Code / Codex run PreToolUse hook commands through a shell with the
tool-call JSON on stdin.  The guard commands mureo installs have the shape::

    python3 -c "<single-line python>" # [mureo-credential-guard]

Re-running the embedded payload through ``sys.executable`` keeps these tests
portable (no bash dependency on the Windows CI job) while exercising the
exact code a shell would hand to ``python3 -c``.  ``extract_python_code``
also asserts the payload is shell-safe: because the code sits inside double
quotes on the command line, any ``"``, ``$``, backtick, backslash, or ``!``
(history expansion) would change meaning under a POSIX shell.

That is not the whole story, though: lifting the payload out skips the
wrapper, so a quoting mistake in the wrapper itself would go unnoticed.
``run_guard_in_shell`` closes that by handing the whole command to a real
bash.  Anything whose answer depends on quoting — the guard's own, or the
command's — belongs there.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_COMMAND_RE = re.compile(r'^python3 -c "(?P<code>[^"]*)" # \[mureo-credential-guard\]$')

_SHELL_HAZARDS = ("$", "`", "\\", "\n", "!")

BASH = shutil.which("bash")
PYTHON3 = shutil.which("python3")


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


def run_guard_in_shell(
    command: str,
    tool_input: dict[str, Any] | None,
    home: Path,
    tool_name: str = "Bash",
    raw_stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the guard command *as a shell runs it*: ``bash -c <command>``.

    ``run_guard`` above lifts the python payload out of the command and runs
    it directly, which never exercises the ``python3 -c "..."`` wrapper.  The
    quoting of that wrapper is a layer of its own: it is where a stray ``"``,
    ``$``, backtick or ``!`` in the payload would change the program the
    shell actually runs.  Tests that care about a quoting question must go
    through here.

    ``raw_stdin`` sends bytes verbatim instead of a tool-call JSON, for the
    malformed-input cases.
    """
    assert BASH is not None and PYTHON3 is not None, "needs bash and python3"
    payload = (
        raw_stdin
        if raw_stdin is not None
        else json.dumps({"tool_name": tool_name, "tool_input": tool_input or {}})
    )
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [BASH, "-c", command],
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
