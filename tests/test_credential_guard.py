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

import json
import re
import sys
from pathlib import Path

import pytest

from tests.credential_guard_support import (
    _PROTECTED_FILES,
    _bash_guard_command,
    _path_guard_command,
    _refusal_category,
    make_fake_home,
    needs_shell,
)
from tests.hook_guard_runner import (
    deny_decision,
    run_guard,
    run_guard_bytes,
    run_guard_in_shell,
)


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """A home directory with a populated ``~/.mureo``."""
    return make_fake_home(tmp_path)


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
            # An alternative carrying its own dot, which is unrelated to the
            # dot of the dotfile. Folding the group to a single placeholder
            # had to guess which of the two the dot belonged to, and chose
            # wrong: these read the credentials file.
            "cat ~/.{mureo,x.y}/credentials.json",
            "cp -r ~/.{mureo,bashrc.bak} /tmp/dest/",
            "ls -la ~/.{mureo,x.y}",
            "cat ~/.mure{o,x.y}/credentials.json",
            "cat ~/.m{ureo,x.y}/credentials.json",
            "cat ~/.{MUREO,x.y}/credentials.json",
            "cat $HOME/.{mureo,x.y}/credentials.json",
            "cat ~/.{mure?,x.y}/credentials.json",
            "cat ~/.{a.b,c.d,mureo}/credentials.json",
            "cat ~/.{mureo,{a,b}.c}/credentials.json",
            # A sequence expression is not a list of alternatives at all,
            # and `{l..n}` covers `m` without the letter appearing anywhere.
            "cat ~/.{l..n}ureo/credentials.json",
            "cat ~/.mure{n..p}/credentials.json",
            # Nested past the expansion budget. The budget used to end in a
            # coarse fallback that left literal braces in the candidates —
            # ordinary characters to fnmatch — so neither rule fired and the
            # file was read. Unresolved structure now denies on its own.
            "cat ~/.{z2,{z1,mureo}}/credentials.json",
            "cat ~/.{z9,{z8,{z7,{z6,{z5,{z4,{z3,{z2,{z1,mureo}}}}}}}}}/creds",
            "cat ~/.{z11,{z10,{z9,{z8,{z7,{z6,{z5,{z4,{z3,{z2,{z1,mureo}}}"
            "}}}}}}}}/credentials.json",
            "cp -r ~/.{z11,{z10,{z9,{z8,{z7,{z6,{z5,{z4,{z3,{z2,{z1,mureo}}}"
            "}}}}}}}}/ /tmp/dest/",
            # Three and five alternatives per level reach the budget sooner.
            "cat ~/.{a,b,{c,d,{e,f,{g,h,{i,j,{k,l,{m,n,mureo}}}}}}}/creds",
            # A letter range covering `m`. This one really does expand onto
            # the directory; `{-..0}` below does not, and is a row in the
            # conservative-refusal test instead.
            "cat ~/.{l..n}ureo/credentials.json",
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
            # The parent directory comes from a substitution *and* the name
            # is broken by something only normalization resolves. This is
            # the product of the two axes, and it is the category that
            # shipped twice: while the two rules read different strings,
            # whatever one of them folded away the other could not see.
            "D2=~/; cat $D2.mu\\\nreo/credentials.json",
            'D2=~/; cat "$D2".mu\\\nreo/credentials.json',
            "set -- ~/; cat $1.mu\\\nreo/credentials.json",
            "D2=~/; E2=; cat $D2$E2.mu\\\nreo/credentials.json",
            "D2=~/; cat ${D2}.mu\\\nreo/credentials.json",
            "D2=~/; cat $D2.\\\nmureo/credentials.json",
            "D2=~/; cat $D2.m\\\nur\\\neo/credentials.json",
            'D2=~/; cat $D2.mure"o"/credentials.json',
            "D2=~/; cat $D2.mur'e'o/credentials.json",
            "D2=~/; cat $D2.mure?/credentials.json",
            'D2=~/; cat "$D2".mure[o]/credentials.json',
            "set -- ~/; cat $1.mure{o,x}/credentials.json",
            "cat $(printf '%s' ~/).mu\\\nreo/credentials.json",
            "cat `printf '%s' ~/`.mure?/credentials.json",
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
            # Brace usage that is not an attempt at the directory. The
            # refusal on unresolved structure must not reach these: the
            # awk/jq bodies are quoted, `{}` has no comma, and eight groups
            # sit inside the expansion budget.
            "awk '{print $1}' data.txt",
            "find . -name '*.pyc' -exec rm {} ;",
            "mkdir -p build/{lib,bin,share}",
            "mv report.{txt,md}",
            "mv file{1..10}.txt archive/",
            # A bare sequence group, which is a common idiom and denied
            # until the range was consulted: integers hold no dot, and a
            # character range holds one only if it spans ASCII 46.
            "echo {1..100}",
            "for i in {1..5}; do touch file$i.txt; done",
            "printf '%s\\n' {A..Z}",
            "touch file{1..20}.log",
            "mkdir -p test{1..3}/{a..c}",
            "echo {a..z}{0..9}",
            "mkdir -p a/{1,2}/b/{3,4}/c/{5,6}/d/{7,8}",
            "kubectl get pods -o jsonpath='{.items[0].metadata.name}'",
            # Braces on separate lines of a multi-line command must not pair
            # up across the newline and swallow what lies between them.
            "echo '{' > a.json\necho '}' >> a.json",
            # Everyday expansions. Taking an expansion out of the command's
            # brace structure must not make the ordinary ones refusals: the
            # braces, parentheses and separators inside one are the
            # expansion's own, and none of these is unresolved structure.
            "echo $(date)",
            "echo ${HOME}",
            "echo $((1 + 2))",
            "echo ${PATH%%:*}",
            "for f in $(ls); do echo $f; done",
            "diff <(sort a.txt) <(sort b.txt)",
            "V=$(git rev-parse HEAD); echo ${V:0:8}",
            # A closing brace with nothing to close is not unresolved
            # structure: a stray closer hides nothing, so only a stray
            # *opener* is refused (see the budget test for that row).
            "echo a}b",
            "case $x in a) echo a;; esac",
            "f() { echo a; }; f",
            "((i=1)); echo $i",
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
        assert _refusal_category(proc) == "crash", raw_stdin

    def test_path_guard_malformed_input_denies(self, fake_home: Path) -> None:
        proc = run_guard_in_shell(
            _path_guard_command(), None, fake_home, raw_stdin="{not json"
        )
        assert deny_decision(proc) == "deny"
        assert proc.returncode == 0
        assert _refusal_category(proc) == "crash"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "the trigger is POSIX-specific: os.path.realpath raises on an "
            "embedded NUL there, while on Windows it returns and the path "
            "simply does not resolve under ~/.mureo, so there is no "
            "exception to escape. The property this demonstrates — an "
            "exception denies rather than exits 1 — is asserted on every "
            "platform by the malformed-stdin tests above, for both guards"
        ),
    )
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
        assert _refusal_category(proc) == "crash"

    @pytest.mark.parametrize(
        "command",
        [
            "cat ~/{-..0}mureo/credentials.json",
            "echo {-..0}",
            "echo {a..z..2}",
        ],
    )
    def test_denies_sequence_syntax_it_does_not_recognise(
        self, fake_home: Path, command: str
    ) -> None:
        """Unrecognised sequence syntax is refused rather than reasoned about.

        These are over-blocks, recorded as such. Bash expands a sequence
        only when both endpoints are integers or single letters, so
        ``{-..0}`` is not a sequence at all and stays literal — none of
        these reaches the directory, and none of them is something a person
        types. The guard does not parse the syntax and does not try to: it
        reads what it cannot resolve conservatively, which is the same rule
        that closed the nesting cliff.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # The shell's own glob options are not in the command text. With
            # dotglob set — here, or in an earlier call on the persistent
            # shell, or in the user's rc file — `*` reaches dotfiles.
            "shopt -s dotglob; cat ~/*/credentials.json",
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

        The list is shorter than it was: reading an expansion's result as text
        of unknown extent, rather than as text that stops where the body's own
        text does, decides some of the shapes whose name is produced at
        runtime. It decides them by what is written in the body, so the class
        is not closed — only the spellings that write enough of the name down.

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


# A code page that cannot be mistaken for UTF-8: what a Japanese Windows
# console decodes a text-mode stdin with.  ``None`` is the platform default.
_STDIN_ENCODINGS = (None, "cp932")


def _utf8_call(tool_name: str, tool_input: dict[str, str]) -> bytes:
    """A tool call the way a host sends it: UTF-8, non-ASCII unescaped."""
    call = {"tool_name": tool_name, "tool_input": tool_input}
    return json.dumps(call, ensure_ascii=False).encode("utf-8")


@pytest.mark.unit
class TestStdinIsReadAsBytes:
    """The payloads read the host's UTF-8 as UTF-8 under any stdin encoding.

    Read as text, stdin is decoded with the console code page on Windows, so
    a home directory with a non-ASCII name stopped matching ``~/.mureo`` and
    non-ASCII text in a Bash command was read as other text.  ``PYTHONIOENCODING``
    pins the text decoding to a code page on every platform, which is what
    lets the property be checked off Windows too.
    """

    @pytest.fixture
    def non_ascii_home(self, tmp_path: Path) -> Path:
        # A name whose UTF-8 bytes also decode as cp932, into other text: the
        # case where text-mode stdin was quietly wrong rather than raising.
        home = tmp_path / "山田"
        home.mkdir()
        return make_fake_home(home)

    @pytest.mark.parametrize("encoding", _STDIN_ENCODINGS)
    def test_path_guard_denies_under_a_non_ascii_home(
        self, non_ascii_home: Path, encoding: str | None
    ) -> None:
        target = str(non_ascii_home / ".mureo" / "credentials.json")
        proc = run_guard_bytes(
            _path_guard_command(),
            _utf8_call("Read", {"file_path": target}),
            non_ascii_home,
            {"PYTHONIOENCODING": encoding} if encoding else None,
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny"
        assert "are protected" in proc.stdout

    @pytest.mark.parametrize("encoding", _STDIN_ENCODINGS)
    def test_path_guard_allows_other_files_under_a_non_ascii_home(
        self, non_ascii_home: Path, encoding: str | None
    ) -> None:
        proc = run_guard_bytes(
            _path_guard_command(),
            _utf8_call("Read", {"file_path": str(non_ascii_home / "a.txt")}),
            non_ascii_home,
            {"PYTHONIOENCODING": encoding} if encoding else None,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == ""

    @pytest.mark.parametrize("encoding", _STDIN_ENCODINGS)
    def test_bash_guard_allows_a_non_ascii_command(
        self, non_ascii_home: Path, encoding: str | None
    ) -> None:
        proc = run_guard_bytes(
            _bash_guard_command(),
            _utf8_call("Bash", {"command": "git commit -m '日本語のメッセージ'"}),
            non_ascii_home,
            {"PYTHONIOENCODING": encoding} if encoding else None,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == ""

    @pytest.mark.parametrize("which", ["path", "bash"])
    def test_empty_stdin_is_refused_with_its_own_reason(
        self, fake_home: Path, which: str
    ) -> None:
        """No stdin is no tool call, which is nothing to allow."""
        command = _path_guard_command() if which == "path" else _bash_guard_command()
        proc = run_guard_bytes(command, b"", fake_home)
        assert proc.returncode == 0, proc.stderr
        assert _refusal_category(proc) == "empty"


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

    def test_every_deny_reason_is_shell_safe(self) -> None:
        """Checked over the module's reasons, not over a hand-written list.

        ``_deny_expr`` already refuses an unsafe reason at build time, but only
        for the reasons something calls it with. Sweeping every ``*_REASON``
        catches one that is added and wired in later, when the import-time
        failure would land on a user instead of here.
        """
        from mureo import credential_guard

        names = sorted(n for n in vars(credential_guard) if n.endswith("_REASON"))
        assert "_BUDGET_REASON" in names, names
        for name in names:
            reason = getattr(credential_guard, name)
            unsafe = set(reason) - credential_guard._SAFE_REASON_CHARS
            assert not unsafe, f"{name} has unsafe characters: {unsafe!r}"
            credential_guard._deny_expr(reason)

    def test_guard_entries_returns_fresh_copies(self) -> None:
        """Installers merge these into user config — aliasing would let one
        install mutate another's already-written structure."""
        from mureo.credential_guard import guard_entries

        first, second = guard_entries(), guard_entries()
        assert first == second
        assert first[0] is not second[0]
        assert first[0]["hooks"] is not second[0]["hooks"]
