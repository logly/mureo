"""Behavioral tests for expansion spans and the readings built from them.

An expansion is one token taken out of the command's structure, its body
is a reading of its own, and what it produces has unknown text and extent.

How these tests run the hook payloads is described in
``tests/test_credential_guard.py``; the helpers they share are in
``tests/credential_guard_support.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.credential_guard_support import (
    _bash_guard_command,
    _refusal_category,
    needs_shell,
)
from tests.hook_guard_runner import deny_decision, run_guard_in_shell


@needs_shell
@pytest.mark.unit
class TestOneReadingOfTheWholeCommandText:
    """The guard reads the command as a single string, and that is load-bearing.

    Every row below writes the protected directory as a brace group and then
    surrounds it with something that *looks* like a reason to stop reading: a
    heredoc body, a word boundary, a command substitution.  Each of them was
    measured against a throwaway ``HOME`` holding a marker credentials file,
    and all but ``<<=A`` print the marker when the guard is removed — ``<<=A``
    sends the text to the interpreter's stdin instead, so it is pinned as a
    refusal rather than as a leak.

    They are a table, not prose, because two attempts to narrow the guard — one
    exempting quoted heredoc bodies, one splitting the command into words
    before expanding braces — each re-opened a part of it.  Narrowing means
    deciding where the text stops being shell, and that decision needs bash's
    whole tokeniser to be right.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # `<<<` is a here-string, not a heredoc: it has no body, so the
            # next line is an ordinary command the shell runs.
            "python3 -c pass <<<'eof'\ncat ~/.mure{o,x}/credentials.json\neof",
            # The operator sits in a comment, so there is no heredoc at all
            # and again the next line is a command.
            "python3 -V #<<'eof'\ncat ~/.mure{o,x}/credentials.json\neof",
            # The delimiter is written across two adjacent quoted segments, so
            # the body ends at `eo` — everything between `eof` and `eo`,
            # including the payload, is shell text.
            "python3 - <<'eo'\"f\"\nx = {1,2}\neof\n"
            "cat ~/.mure{o,x}/credentials.json\neo",
            # `<<=A` delimits on `=A`, which never arrives, so the payload is
            # swallowed as an unterminated body: bash does not read the file
            # here, and the refusal is recorded for the shape rather than for
            # a measured leak.
            "python3 - <<=A\ncat ~/.mure{o,x}/credentials.json\nA",
        ],
    )
    def test_denies_a_brace_group_around_a_heredoc(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # A separator inside the group, quoted so that bash keeps the
            # whole thing in one word and expands it. Splitting the command
            # into words first has to agree with bash about every one of
            # these, and the quoted ones are where it stops agreeing.
            'cat ~/.mure{o," "x}/credentials.json',
            "cat ~/.mure{o,' 'x}/credentials.json",
            "cat ~/.mure{o,\\ x}/credentials.json",
            'cat ~/.mure{o,"\tx"}/credentials.json',
            'cat ~/.mure{o,";"x}/credentials.json',
            'cat ~/.mure{o,"|"x}/credentials.json',
            'cat ~/.mure{o,"&"x}/credentials.json',
            'cat ~/.mure{o,"("x}/credentials.json',
            'cat ~/.mure{o,"<"x}/credentials.json',
            'cat ~/.mure{o,">"x}/credentials.json',
            # The same group with no separator in it, as a control.
            "cat ~/.mure{o,x}/credentials.json",
        ],
    )
    def test_denies_a_group_holding_a_quoted_separator(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # A substitution inside the group. The separators in these are
            # unquoted, so anything that tracked quoting but not substitution
            # nesting would read them as word boundaries and cut the group in
            # two — while bash expands it and reaches the directory.
            "cat ~/.mur{e,$()}o/credentials.json",
            "cat ~/.mur{e,$(true)}o/credentials.json",
            "cat ~/.mur{e,$(:|:)}o/credentials.json",
            "cat ~/.mur{e,$(:;:)}o/credentials.json",
            "cat ~/.mur{e,$(:&)}o/credentials.json",
            "cat ~/.mur{e,$(cat</dev/null)}o/credentials.json",
            "cat ~/.mur{e,$(:>/dev/null)}o/credentials.json",
            "cat ~/.mur{e,$(echo a b)}o/credentials.json",
            "cat ~/.mur{e,$(echo $(echo a b))}o/credentials.json",
            "cat ~/.mur{e,`echo a b`}o/credentials.json",
            "cat ~/.mur{e,<(true)}o/credentials.json",
            "cat ~/.mur{e,$((1 + 1))}o/credentials.json",
        ],
    )
    def test_denies_a_group_holding_a_substitution(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # A parameter expansion inside the group. Its braces are not the
            # group's braces, and anything that pairs the two off reads the
            # group as closed where it is not and stops seeing it at all —
            # while bash keeps the whole word, expands the group and takes
            # the first alternative straight into the directory. The plainest
            # spelling is first.
            "cat ~/.mur{e,${q}}o/credentials.json",
            "cat ~/.mur{e,${q:-a b}}o/credentials.json",
            "cat ~/.mur{e,${q:=a b}}o/credentials.json",
            "cat ~/.mur{e,${q:?a b}}o/credentials.json",
            "cat ~/.mur{e,${q:0:1}}o/credentials.json",
            "cat ~/.mur{e,${q/a b/c}}o/credentials.json",
            "cat ~/.mur{e,${#q}}o/credentials.json",
            "cat ~/.mur{e,${q[@]}}o/credentials.json",
            "cat ~/.mur{e,${q^^}}o/credentials.json",
            # ...and the same group one expansion further in, which only a
            # reading that recurses into the body can see.
            "cat $(echo ~/.mur{e,${q}}o/credentials.json)",
            "cat `echo ~/.mur{e,${q}}o/credentials.json`",
        ],
    )
    def test_denies_a_group_holding_a_parameter_expansion(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # Taking the expansion out of the command's structure must not
            # take its text out of the guard's reading: every one of these
            # names the directory or a protected file INSIDE the expansion,
            # and the body is the only place it is written.
            "cat $(echo ~/.mureo/credentials.json)",
            "cat $(cat ~/.mureo/credentials.json)",
            "cat $(echo $(cat ~/.mureo/credentials.json))",
            "cat `echo ~/.mureo/credentials.json`",
            'cat "${q:-~/.mureo/credentials.json}"',
            "cat $(echo ~/.mure{o,x}/credentials.json)",
            "cat $(echo ~/.mure?/credentials.json)",
            "cat $(find ~ -name credentials.json)",
            "cat $((0))$(cat ~/.mureo/credentials.json)",
        ],
    )
    def test_denies_a_reference_inside_an_expansion_body(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            # An expansion whose extent cannot be decided: whatever the
            # guard would conclude about the structure around it would be a
            # guess, so it concludes nothing and refuses on that ground.
            # Bash cannot run any of these as written either.
            "cat ~/.mur{e,$(}o/credentials.json",
            "cat ~/.mur{e,`echo}o/credentials.json",
            "cat ~/.mur{e,${q}o/credentials.json",
            "cat ~/.mure$(",
            "cat ~/.mure`printf o",
            # An unquoted `{` with no `}` after it. This one bash really does
            # run — `echo a{b` prints `a{b` — so it is an over-block, and it
            # is the price of the row above it: a brace group left open
            # around an expansion is the same shape, and telling the two
            # apart means deciding the extent the fold just failed to decide.
            # Recorded here rather than hidden.
            "echo a{b",
        ],
    )
    def test_refuses_an_expansion_whose_extent_is_undecided(
        self, fake_home: Path, command: str
    ) -> None:
        """And says *that*, not that a brace budget ran out.

        No budget is spent deciding an expansion's extent and no brace
        expansion is attempted, so borrowing the budget's reason sent the agent
        to count brace groups when what the command needs is a closing
        delimiter.  The two grounds are separate facts about separate steps and
        each says its own.

        The same ground covers a plain bracket the fold could not pair up,
        which is why the reason names a bracket as well as an expansion: some
        of those are commands a shell runs happily, and a reason that said
        "expansion" would send the reader looking for one that is not there.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "span", command


@needs_shell
@pytest.mark.unit
class TestAnExpansionsResultHasUnknownExtent:
    """A body reading ends where the expansion does; its result does not.

    The shell splices an expansion's result into the middle of a word, so what
    follows the closer belongs to the same path component and the result's own
    length is not in the text.  Read as text that stops where the body's text
    stops, a body ending on part of the directory's name is a name that merely
    resembles it; and the command reading, where the whole expansion is one
    unknown token, has no dot in it to judge.  Each reading dropped the
    question for its own reason.  So a body reading ends in a wildcard, which
    puts the question to the rule that already asks it.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "cat $(printf ~/.mur)eo/credentials.json",
            "cat $(echo ~/.mure)o/credentials.json",
            "cat ~/$(echo .mur)eo/credentials.json",
            "cat `printf ~/.mur`eo/credentials.json",
            "cat ${q:-~/.mur}eo/credentials.json",
        ],
    )
    def test_a_name_split_across_the_closer_is_read(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        ["echo $(ls .)", "echo $(ls -d .)", "echo `ls .`", "echo $(dirname .)"],
    )
    def test_records_what_the_unknown_extent_over_blocks(
        self, fake_home: Path, command: str
    ) -> None:
        """A body ending on a prefix of the directory name, recorded as a cost.

        A bare ``.`` is such a prefix, so an expansion whose body ends on one is
        refused although what it produces is a listing rather than a name.  What
        the expansion produces is not in the text, and a credential guard that
        cannot tell has to answer on the deny side; the bound on the cost is
        that the body has to *end* there.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize(
        "command",
        [
            "echo $(date)",
            "echo ${HOME}",
            "echo $((1 + 2))",
            "diff <(sort a) <(sort b)",
            "echo $(ls -a)",
            "tar -cf a.tar $(cat list.txt)",
            "echo $(git rev-parse HEAD)",
            "echo $(basename a.txt)",
            "echo x | tee >(cat) >/dev/null",
            "for f in $(ls *.py); do echo $f; done",
            "echo ${PATH%%:*}",
            "cd $(dirname a/b.txt)",
            "echo $(pwd)/x",
        ],
    )
    def test_everyday_expansions_are_unaffected(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command
