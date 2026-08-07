"""Behavioral tests for the shared credential-guard hook templates (#393).

The guard must actually BLOCK.  Claude Code and Codex PreToolUse hooks treat
a plain exit code 1 as a *non-blocking* error — the tool call proceeds — so
the old ``sys.exit(1)`` templates never protected anything.  Blocking
requires exit code 2 or a ``permissionDecision: "deny"`` JSON on stdout;
mureo uses the deny-JSON form because an interpreter crash (exit 1) can
never be mistaken for an intentional block.

These tests execute the generated hook payloads in a subprocess with a fake
``$HOME``, mirroring how the agent harness invokes them.  The cases whose
answer depends on quoting run the whole command through a real bash instead
— see ``TestGuardThroughARealShell``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from tests.hook_guard_runner import (
    BASH,
    PYTHON3,
    deny_decision,
    run_guard,
    run_guard_in_shell,
)

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

    @pytest.mark.skipif(
        sys.platform == "win32", reason="symlink creation needs privileges"
    )
    def test_denies_outbound_symlink_credentials_file(self, tmp_path: Path) -> None:
        """``~/.mureo/credentials.json`` that is ITSELF a symlink pointing OUT
        must still be blocked.

        Its realpath escapes ``~/.mureo`` (so the realpath check alone would
        allow the read), but the requested path is logically under ``~/.mureo``
        — the logical-path check must catch it. Regression for the inside-out
        symlink evasion.
        """
        home = tmp_path / "home"
        mureo_dir = home / ".mureo"
        mureo_dir.mkdir(parents=True)
        external = tmp_path / "outside" / "stolen.json"
        external.parent.mkdir(parents=True)
        external.write_text('{"access_token": "secret"}', encoding="utf-8")
        cred = mureo_dir / "credentials.json"
        cred.symlink_to(external)

        proc = run_guard(_path_guard_command(), {"file_path": str(cred)}, home)
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

    @pytest.mark.parametrize(
        "command",
        [
            # End of the command string: nothing follows the directory name.
            "ls -la ~/.mureo",
            "tar cf /tmp/x.tar ~/.mureo",
            # Trailing separator, and every quoting form of the same path.
            "ls ~/.mureo/",
            'cat "$HOME/.mureo/credentials.json"',
            "cat '~/.mureo/credentials.json'",
            "cat ~/'.mureo'/credentials.json",
            'cat ~/.mureo""/credentials.json',
            # Mixed case still opens the real file on case-insensitive
            # filesystems, so it must stay blocked.
            "cat ~/.Mureo/credentials.json",
            "ls ~/.MUREO",
            # Anything at all may follow the directory name — the rule only
            # consults what comes before it.
            "cat ~/.mureo$SUFFIX/credentials.json",
            "cat ~/.mureo{,}/credentials.json",
            "cat ~/.mureo*/credentials.json",
            "cat ~/.mureoX/../.mureo/credentials.json",
            # Sibling names are blocked too: only the text before the name is
            # consulted, so ``.mureoX`` — which may well be a symlink INTO the
            # protected directory — is not admitted.
            "cat ~/.mureoX/credentials.json",
            "ls ~/.mureo_backup",
            # A substitution supplying the parent directory leaves an
            # identifier character immediately before the name. These are the
            # forms that make a naive preceded-by test unsafe: each one
            # resolves into ~/.mureo.
            "D=~/; cat $D.mureo/credentials.json",
            "D=~/; cat $D.MUREO/credentials.json",
            "set -- ~/; cat $1.mureo/credentials.json",
            "D=~/; E=; cat $D$E.mureo/credentials.json",
            "cat $(printf '%s.mureo/credentials.json' ~/)",
            "python3 -c \"print(open('%s.mureo/credentials.json' % h).read())\"",
            # ...while every other splice closes with punctuation, which the
            # boundary test catches on its own.
            "D=~/; cat ${D}.mureo/credentials.json",
            'D=~/; cat "$D".mureo/credentials.json',
            "cat $(printf '%s' ~/).mureo/credentials.json",
            "python3 -c \"print(open('{}.mureo/x'.format(h)).read())\"",
        ],
    )
    def test_denies_every_spelling_of_the_mureo_dir(
        self, fake_home: Path, command: str
    ) -> None:
        """The boundary rule must not shrink what is blocked.

        Every form here resolves into ``~/.mureo`` — verified by expanding
        each one with a real shell against a throwaway ``$HOME`` — and every
        one of them was blocked by the previous bare-substring check.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Every one of these was verified against a throwaway $HOME with a
            # real bash 5.2: each prints the contents of the credentials file.
            "cat ~/.mure?/credentials.json",
            "cat ~/.[m]ureo/credentials.json",
            "cat ~/.mur*/credentials.json",
            "cat ~/.m?reo/credentials.json",
            "cat ~/.?????/credentials.json",
            "cat ~/.[!.]*/credentials.json",
            "cat ~/.mure[o]/credentials.json",
            # Brace expansion runs before pathname expansion, so it produces
            # the real directory name without any wildcard at all.
            "cat ~/.mure{o,x}/credentials.json",
            "cat ~/.mur{eo,ex}/credentials.json",
            # Same patterns, other spellings of the parent directory.
            "ls -la ~/.mure?",
            "cp -r ~/.m?reo /tmp/exfil",
            "cat $HOME/.mure?/credentials.json",
            "cat ${HOME}/.mur*/credentials.json",
            'cat "$HOME"/.mure?/credentials.json',
            "cat /Users/x/.mur*/credentials.json",
            # Case-folded, as everywhere else in the guard.
            "cat ~/.MURE?/credentials.json",
            "cat ~/.[M]UREO/credentials.json",
            # A substitution supplies the parent, so the pattern does not
            # start at a path boundary — the same shapes rule 1 covers for
            # the literal name.
            "D=~/; cat $D.mure?/credentials.json",
            "cat $(printf '%s.mure?/credentials.json' ~/)",
            "python3 -c \"print(open('%s.mure?/credentials.json' % h).read())\"",
        ],
    )
    def test_denies_glob_patterns_matching_the_mureo_dir(
        self, fake_home: Path, command: str
    ) -> None:
        """A wildcard inside the directory name still reaches the real files.

        The literal-substring rule looks for six consecutive characters, so
        any metacharacter placed *inside* ``.mureo`` breaks the match while
        the shell still expands the pattern onto the protected directory.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Wildcards that cannot reach a dotfile at all: the shell requires
            # a leading period to be matched explicitly.
            "ls *",
            "rm -rf build/*",
            "cp dist/* /tmp/",
            "node --test tests/js/*.test.js",
            "pytest tests/test_*.py",
            "ls -d */",
            "git add -- mureo/*.py",
            # Dot-leading patterns that cannot spell the directory name.
            "rm -f .coverage*",
            "ls -d .git*",
            "cat .env.*",
            "rm -rf .pytest_cache .ruff_cache",
            # Quoted metacharacters never reach pathname expansion — regexes
            # and format strings must not be read as globs.
            "sed 's/.*//' notes.txt",
            "grep -rn '.*TODO' mureo/",
            "find . -name '*.py' -newer setup.py",
            "find . -name '.*' -maxdepth 1",
            "git log --grep '.*fix'",
            # ...including a fully quoted path: quoting suppresses globbing,
            # so `?` here is a literal character and opens nothing.
            'cat "$HOME/.mure?/credentials.json"',
            # Ordinary commands with no pattern at all.
            "ruff check .",
            "git diff -- .",
            "black --check .",
        ],
    )
    def test_allows_everyday_glob_commands(self, fake_home: Path, command: str) -> None:
        """The pattern rule must not fire on day-to-day shell usage."""
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", command

    @pytest.mark.parametrize("command", ["echo hello", "ls -la", "git status"])
    def test_allows_unrelated_commands(self, fake_home: Path, command: str) -> None:
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    @pytest.mark.parametrize(
        "command",
        [
            # mureo's own public browser namespace, case-folding to `.mureo_`.
            "gh release create v0.10.43 --notes 'adds window.MUREO_REPORTS_FORMAT'",
            "git commit -m 'feat: reorder via window.MUREO_REPORTS_ORDER'",
            "grep -rn window.MUREO_WIZARD mureo/_data/web/",
            "node --test tests/js/reports_format.test.js # window.MUREO_AUTH_META",
            # Hostnames under the project's domain, case-folding to `.mureo.`.
            "gh pr create --body 'published to pkgs.mureo.jp'",
            "pip install --index-url https://pkgs.mureo.jp/simple/ mureo-agency",
            "curl -sS https://pkgs.mureo.jp/simple/index.html",
            "open https://docs.mureo.jp/byod",
            "echo www.mureo.jp",
        ],
    )
    def test_allows_mureo_own_identifiers(self, fake_home: Path, command: str) -> None:
        """mureo's browser globals and hostnames are not the directory.

        Both false positives were observed for real: the ``gh release
        create`` call for v0.10.43 was denied over ``window.MUREO_REPORTS_*``
        in its notes, and a ``gh pr create`` was denied over
        ``pkgs.mureo.jp`` in its body. In each the substring is preceded by
        an identifier character belonging to a longer name, so it cannot be
        the start of a ``.mureo`` path component.
        """
        proc = run_guard(
            _bash_guard_command(), {"command": command}, fake_home, tool_name="Bash"
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == "", command


# ---------------------------------------------------------------------------
# The shell layer
# ---------------------------------------------------------------------------


@needs_shell
@pytest.mark.unit
class TestGuardThroughARealShell:
    """Run the generated command the way a host runs it: ``bash -c``.

    Every case below was checked outside the suite against a throwaway
    ``HOME`` holding a marker credentials file: the deny cases print the
    marker when the guard is removed, and the allow cases print nothing.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # Quoting splits the name, and quote removal puts it back
            # together. None of these contains `.mureo` as six consecutive
            # characters, and the first four hide the metacharacter too.
            "cat ~/'.'mure?/credentials.json",
            'cat ~/".mure"?/credentials.json',
            "cat ~/.mure''?/credentials.json",
            'cat ~/.mure"o"/credentials.json',
            'cat "$HOME"/.mure"o"/credentials.json',
            "cat ~/.mur'e'o/credentials.json",
            # An apostrophe inside a double-quoted word is an ordinary
            # character. Reading it as a delimiter pairs it with the next
            # quote and swallows the real pattern in between.
            "echo \"it's\" ; cat ~/.mure?/credentials.json 'x'",
            "echo \"don't\" && cat ~/.mure?/credentials.json 'y'",
            # A backslash-escaped quote is not a delimiter either.
            "echo it\\'s ; cat ~/.mure?/credentials.json",
            # An escaped metacharacter is literal, but an escaped letter is
            # still the letter.
            "cat ~/\\.mureo/credentials.json",
            "cat ~/.mur\\eo/credentials.json",
            # A substitution inside the name makes the rest of it unknown.
            "cat ~/.mure$(printf '?')/credentials.json",
            "cat ~/.mure`printf o`/credentials.json",
            # A brace group can supply any character, including the dot.
            "cat ~/{.,z}mureo/credentials.json",
            "cat ~/.mure{o,x}/credentials.json",
            "cat ~/.mur{e{o,z},y}/credentials.json",
            # A line continuation is deleted, backslash and newline both,
            # before the shell tokenises anything — so the name is spelled
            # across two lines and is contiguous by the time it is used.
            "cat ~/.mu\\\nreo/credentials.json",
            "cat ~/.\\\nmureo/credentials.json",
            "cat ~/.m\\\nu\\\nr\\\ne\\\no/credentials.json",
            "cat ~/.mure\\\n?/credentials.json",
            "cat ~/.m\\\nure?/credentials.json",
            # ...including inside double quotes, where it is still a
            # continuation (and where nothing globs, so the name itself is
            # what has to be seen).
            'cat "$HOME/.mu\\\nreo/credentials.json"',
            # `$"..."` is a translated string: the `$` is not an expansion
            # of anything the guard cannot see.
            'cat ~/$".mureo"/credentials.json',
            # ...and the plain forms still deny through the shell layer.
            "cat ~/.mureo/credentials.json",
            "cat ~/.mure?/credentials.json",
            "D=~/; cat $D.mure?/credentials.json",
            "cat $(printf '%s.mure?/credentials.json' ~/)",
        ],
    )
    def test_denies_through_the_shell(self, fake_home: Path, command: str) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Quoted metacharacters are ordinary characters: a regex, a
            # literal argument, a path that opens nothing.
            "sed 's/.*//' notes.txt",
            "sed -e 's|.*/||' paths.txt",
            "find . -name '.*' -maxdepth 1",
            "grep -rn '.*TODO' mureo/",
            'cat "$HOME/.mure?/credentials.json"',
            "cat '~/.mure?/credentials.json'",
            # Everyday globbing, which cannot reach a dotfile.
            "ls *",
            "rm -rf build/*",
            "node --test tests/js/*.test.js",
            "ls -d .git*",
            # Inside single quotes a backslash is an ordinary character, so
            # this is a name with a newline in it, not a continuation, and
            # it opens nothing.
            "cat '~/.mu\\\nreo/credentials.json'",
            # A continuation that only wraps a long line.
            "ls -la \\\n  ~/project",
            # mureo's own identifiers, including inside quotes.
            "gh release create v0.10.44 --notes 'adds window.MUREO_REPORTS_FORMAT'",
            "pip install --index-url https://pkgs.mureo.jp/simple/ mureo-agency",
            "echo user@pkgs.mureo.jp",
        ],
    )
    def test_allows_through_the_shell(self, fake_home: Path, command: str) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", command

    @pytest.mark.parametrize(
        "raw_stdin",
        [
            "{not json",
            "[]",
            '{"tool_input": "not a dict"}',
            "\x00\x01\x02",
        ],
    )
    def test_malformed_input_denies_rather_than_escapes(
        self, fake_home: Path, raw_stdin: str
    ) -> None:
        """An exception in the payload is a bypass, not a crash.

        Exit 1 is a *non-blocking* hook error in both hosts, so a payload
        that raises lets the tool call proceed. Anything the guard cannot
        parse must therefore deny.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), None, fake_home, raw_stdin=raw_stdin
        )
        assert deny_decision(proc) == "deny", raw_stdin
        assert proc.returncode == 0, proc.stderr

    def test_path_guard_malformed_input_denies(self, fake_home: Path) -> None:
        proc = run_guard_in_shell(
            _path_guard_command(), None, fake_home, raw_stdin="{not json"
        )
        assert deny_decision(proc) == "deny"
        assert proc.returncode == 0

    def test_path_guard_unusable_path_denies(self, fake_home: Path) -> None:
        """``realpath`` raises on an embedded NUL — that must not fail open."""
        proc = run_guard_in_shell(
            _path_guard_command(),
            {"file_path": "\x00/x/.mureo/credentials.json"},
            fake_home,
            tool_name="Read",
        )
        assert deny_decision(proc) == "deny"
        assert proc.returncode == 0

    @pytest.mark.parametrize(
        "command",
        [
            # The shell's own glob options are not in the command text. With
            # dotglob set — here, or in an earlier call on the persistent
            # shell, or in the user's rc file — `*` reaches dotfiles.
            "shopt -s dotglob; cat ~/*/credentials.json",
            # The leading dot is produced at runtime, so the text never
            # contains a dot-anchored component to test.
            "cat ~/$(printf '.')mureo/credentials.json",
            "cat ~/$(printf '.')mure?/credentials.json",
            # The name is assembled by a previous command.
            "cat ~/$P/credentials.json",
            # Another notation has to be decoded first.
            "cat ~/$'\\x2emureo'/credentials.json",
        ],
    )
    def test_known_open_bypasses(self, fake_home: Path, command: str) -> None:
        """The bypasses this guard does not close, pinned so they cannot grow.

        All but one were run against a throwaway HOME and printed the
        credentials file; the exception is ``cat ~/$P/x``, which reads it
        only once an earlier call has set ``P`` — the point of the row is
        that the name is nowhere in the text. They are here so the open
        surface is a list someone has to edit, rather than something a
        reviewer discovers: closing one means deleting its row and saying
        so in the module docstring.

        What they have in common is that the text handed to the guard does
        not contain the thing that reaches the filesystem — it is produced
        later, by the shell's options, by another program, or by decoding
        another notation. No inspection of the command text can decide them;
        see the module docstring in ``mureo/credential_guard.py``.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", f"now denied, update the docstring: {command}"


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
