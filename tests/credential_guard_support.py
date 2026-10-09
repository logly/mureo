"""Helpers shared by the credential-guard test modules.

The guard's tests are split by the step of the guard they exercise; what
they all need -- the protected files, the fake home holding them, the
rendered hook commands and the refusal categories -- lives here once.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.hook_guard_runner import BASH, PYTHON3

needs_shell = pytest.mark.skipif(
    BASH is None or PYTHON3 is None,
    reason="the shell layer needs both bash and python3 on PATH",
)

_PROTECTED_FILES = (
    "credentials.json",
    "agency.json",
    "config.json",
    "setup_state.json",
    os.path.join("shared", "credentials.json.bak"),
)


def make_fake_home(tmp_path: Path) -> Path:
    """A home directory with a populated ``~/.mureo``."""
    mureo_dir = tmp_path / ".mureo"
    (mureo_dir / "shared").mkdir(parents=True)
    for name in _PROTECTED_FILES:
        (mureo_dir / name).write_text("{}", encoding="utf-8")
    return tmp_path


def _path_guard_command() -> str:
    from mureo.credential_guard import path_guard_entry

    return str(path_guard_entry()["hooks"][0]["command"])


def _bash_guard_command() -> str:
    from mureo.credential_guard import bash_guard_entry

    return str(bash_guard_entry()["hooks"][0]["command"])


# Each refusal has its own reason; the marker below is the phrase that is in
# one of them and in none of the others.  Matching on the reason text rather
# than on which branch of the hook fired is deliberate: the reason is what the
# agent actually reads, so it is what a test about reasons has to assert on.
_REFUSAL_MARKERS = (
    ("oversize", "over 65536 bytes"),
    ("span", "not closed"),
    ("budget", "brace expansion"),
    ("unresolved", "could not resolve"),
    ("heredoc", "here-document operator"),
    ("filename", "credential file"),
    ("directory", "can reach"),
)


def _refusal_category(proc: subprocess.CompletedProcess[str]) -> str | None:
    """Which refusal a guard run produced, or ``None`` when it allowed.

    A deny arrives in one of two shapes — the deny JSON on stdout with exit 0,
    or exit 2 with the reason on stderr — and both hosts accept either.  A
    helper that read only one channel would report the other as "allowed" and
    the test would pass for the wrong reason, so both are read here.
    """
    reason = None
    if proc.stdout.strip():
        reason = (
            json.loads(proc.stdout)
            .get("hookSpecificOutput", {})
            .get("permissionDecisionReason")
        )
    if reason is None and proc.returncode == 2:
        reason = proc.stderr.strip()
    if not reason:
        return None
    for category, marker in _REFUSAL_MARKERS:
        if marker in reason:
            return category
    raise AssertionError(f"refusal reason matches no known category: {reason!r}")
