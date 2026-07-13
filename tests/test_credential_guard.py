"""Behavioral tests for the shared credential-guard hook templates (#393).

The guard must actually BLOCK.  Claude Code and Codex PreToolUse hooks treat
a plain exit code 1 as a *non-blocking* error — the tool call proceeds — so
the old ``sys.exit(1)`` templates never protected anything.  Blocking
requires exit code 2 or a ``permissionDecision: "deny"`` JSON on stdout;
mureo uses the deny-JSON form because an interpreter crash (exit 1) can
never be mistaken for an intentional block.

These tests execute the generated hook payloads in a subprocess with a fake
``$HOME``, mirroring how the agent harness invokes them.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from tests.hook_guard_runner import deny_decision, run_guard

_PROTECTED_FILES = (
    "credentials.json",
    "agency.json",
    "config.json",
    "setup_state.json",
    os.path.join("shared", "credentials.json.bak"),
)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """A home directory with a populated ``~/.mureo``."""
    mureo_dir = tmp_path / ".mureo"
    (mureo_dir / "shared").mkdir(parents=True)
    for name in _PROTECTED_FILES:
        (mureo_dir / name).write_text("{}", encoding="utf-8")
    return tmp_path


def _path_guard_command() -> str:
    from mureo.credential_guard import path_guard_entry

    return path_guard_entry()["hooks"][0]["command"]


def _bash_guard_command() -> str:
    from mureo.credential_guard import bash_guard_entry

    return bash_guard_entry()["hooks"][0]["command"]


# ---------------------------------------------------------------------------
# Path guard (Read / Edit / Write / Grep / Glob)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathGuardBehavior:
    def test_denies_read_of_credentials(self, fake_home: Path) -> None:
        proc = run_guard(
            _path_guard_command(),
            {"file_path": str(fake_home / ".mureo" / "credentials.json")},
            fake_home,
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny"

    @pytest.mark.parametrize("name", _PROTECTED_FILES)
    def test_denies_every_file_under_mureo_dir(
        self, fake_home: Path, name: str
    ) -> None:
        """The whole ``~/.mureo`` tree is protected, not just credentials.json."""
        proc = run_guard(
            _path_guard_command(),
            {"file_path": str(fake_home / ".mureo" / name)},
            fake_home,
        )
        assert deny_decision(proc) == "deny"

    def test_denies_tilde_path(self, fake_home: Path) -> None:
        proc = run_guard(
            _path_guard_command(),
            {"file_path": "~/.mureo/credentials.json"},
            fake_home,
        )
        assert deny_decision(proc) == "deny"

    def test_denies_grep_path_field(self, fake_home: Path) -> None:
        """Grep/Glob send ``path`` instead of ``file_path``."""
        proc = run_guard(
            _path_guard_command(),
            {"path": str(fake_home / ".mureo"), "pattern": "token"},
            fake_home,
            tool_name="Grep",
        )
        assert deny_decision(proc) == "deny"

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation needs privileges"
    )
    def test_denies_symlink_evasion(self, fake_home: Path, tmp_path: Path) -> None:
        """A symlink outside ~/.mureo resolving into it is still blocked."""
        link = tmp_path / "innocent.json"
        link.symlink_to(fake_home / ".mureo" / "credentials.json")
        proc = run_guard(_path_guard_command(), {"file_path": str(link)}, fake_home)
        assert deny_decision(proc) == "deny"

    def test_allows_files_outside_mureo(self, fake_home: Path) -> None:
        project_file = fake_home / "project" / "main.py"
        project_file.parent.mkdir()
        project_file.write_text("print('ok')\n", encoding="utf-8")
        proc = run_guard(
            _path_guard_command(), {"file_path": str(project_file)}, fake_home
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_allows_similarly_named_sibling_dir(self, fake_home: Path) -> None:
        """Prefix matching must not spill over to ``~/.mureo-backup`` etc."""
        sibling = fake_home / ".mureo-backup" / "credentials.json"
        sibling.parent.mkdir()
        sibling.write_text("{}", encoding="utf-8")
        proc = run_guard(_path_guard_command(), {"file_path": str(sibling)}, fake_home)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_denies_uppercase_path_evasion(self, fake_home: Path) -> None:
        """macOS/Windows filesystems are case-insensitive by default, so
        ``~/.MUREO/credentials.json`` opens the real file — must be denied."""
        proc = run_guard(
            _path_guard_command(),
            {"file_path": str(fake_home / ".MUREO" / "credentials.json")},
            fake_home,
        )
        assert deny_decision(proc) == "deny"

    def test_allows_empty_tool_input(self, fake_home: Path) -> None:
        proc = run_guard(_path_guard_command(), {}, fake_home)
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Bash guard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBashGuardBehavior:
    def test_denies_wildcard_read(self, fake_home: Path) -> None:
        """``cat ~/.mureo/cred*`` evaded the old 'credentials' substring check."""
        proc = run_guard(
            _bash_guard_command(),
            {"command": "cat ~/.mureo/cred*"},
            fake_home,
            tool_name="Bash",
        )
        assert proc.returncode == 0
        assert deny_decision(proc) == "deny"

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/.mureo/credentials.json",
            "cat $HOME/.mureo/config.json",
            "cp -r ~/.mureo /tmp/exfil",
            "python3 -c 'print(open(\"/Users/x/.mureo/agency.json\").read())'",
            "cat ~/.MUREO/credentials.json",  # case-insensitive filesystems
        ],
    )
    def test_denies_mureo_dir_references(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny"

    @pytest.mark.parametrize("command", ["echo hello", "ls -la", "git status"])
    def test_allows_unrelated_commands(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Template structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGuardTemplates:
    def test_no_nonblocking_exit1(self) -> None:
        """exit(1) is a non-blocking hook error — it must never come back."""
        for command in (_path_guard_command(), _bash_guard_command()):
            assert "sys.exit(1)" not in command
            assert "permissionDecision" in command

    def test_deny_json_shape(self, fake_home: Path) -> None:
        import json

        proc = run_guard(
            _path_guard_command(),
            {"file_path": str(fake_home / ".mureo" / "credentials.json")},
            fake_home,
        )
        output = json.loads(proc.stdout)["hookSpecificOutput"]
        assert output["hookEventName"] == "PreToolUse"
        assert output["permissionDecision"] == "deny"
        assert output["permissionDecisionReason"]

    def test_commands_are_tagged(self) -> None:
        from mureo.credential_guard import GUARD_TAG

        for command in (_path_guard_command(), _bash_guard_command()):
            assert command.endswith(f"# {GUARD_TAG}")

    def test_path_matcher_covers_file_tools(self) -> None:
        from mureo.credential_guard import bash_guard_entry, path_guard_entry

        matcher = path_guard_entry()["matcher"]
        for tool in ("Read", "Edit", "Write", "Grep", "Glob", "NotebookEdit"):
            assert re.fullmatch(matcher, tool), f"matcher must cover {tool}"
        assert bash_guard_entry()["matcher"] == "Bash"

    def test_unsafe_deny_reason_is_rejected(self) -> None:
        """A reason with quoting hazards would fail open (exit 1) at hook
        runtime — it must be refused at build time instead."""
        from mureo.credential_guard import _deny_expr

        for bad in ("it's blocked", 'say "no"', "a\\b", "cost $5", "x`y`"):
            with pytest.raises(ValueError, match="unsafe"):
                _deny_expr(bad)

    def test_guard_entries_returns_fresh_copies(self) -> None:
        """Installers merge these into user config — aliasing would let one
        install mutate another's already-written structure."""
        from mureo.credential_guard import guard_entries

        first, second = guard_entries(), guard_entries()
        assert first == second
        assert first[0] is not second[0]
        assert first[0]["hooks"] is not second[0]["hooks"]
