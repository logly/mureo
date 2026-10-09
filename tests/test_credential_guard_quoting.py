"""Behavioral tests for the quoting automaton.

A here-document body is read the way bash reads it, without resolving
quoting; and a quoted metacharacter is kept from this shell but not from
the next one along, which is what the second reading answers.

How these tests run the hook payloads is described in
``tests/test_credential_guard.py``; the helpers they share are in
``tests/credential_guard_support.py``.
"""

from __future__ import annotations

import json
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
class TestAHereDocumentBodyIsNotQuotedText:
    """From an unquoted ``<<`` on, the guard stops resolving quoting.

    Bash resolves none in the body of a here-document: a ``'`` or a ``"``
    there is ordinary body text.  A reading that treated them as delimiters
    would disagree with bash about where quoted spans are for the rest of the
    command — and a body holding an unbalanced quote (an apostrophe in prose,
    an unterminated string literal in source) is an everyday thing, not an
    exotic one.

    The latch does not look for the terminator, so it errs long.  That is the
    safe direction: declining to resolve quoting leaves more text visible to
    the rules, while resolving quoting bash does not resolve hides text from
    them.  What it costs is in
    ``test_records_what_not_resolving_quoting_over_blocks``.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # A body that opens a quote it never closes, with the payload on
            # the line after the terminator — where it is plain shell text.
            "cat <<eof\ndon't\neof\ncat ~/.mure{o,x}/credentials.json",
            "cat <<'eof'\ndon't\neof\ncat ~/.mure{o,x}/credentials.json",
            "cat <<-'eof'\ndon't\neof\ncat ~/.mure{o,x}/credentials.json",
            'cat <<eof\nsay "hi\neof\ncat ~/.mure{o,x}/credentials.json',
            "python3 - <<'eof'\ns = \"it's\neof\n" "cat ~/.mure{o,x}/credentials.json",
            # Two bodies, the second one opening the quote.
            "cat <<a\nx\na\ncat <<b\ndon't\nb\n" "cat ~/.mure{o,x}/credentials.json",
            # The name written out needs nothing expanded, and is here so the
            # row above is not the only spelling checked.
            "cat <<eof\ndon't\neof\ncat ~/.mureo/credentials.json",
        ],
    )
    def test_denies_a_payload_after_a_body_that_leaves_a_quote_open(
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
            # The body is the consuming program's source, and the program
            # hands it to a shell of its own. Every row writes the directory
            # in a spelling that only a shell resolves, so the body is the
            # only place it is written and the body is where it has to be
            # seen. Measured against a throwaway HOME with a marker file:
            # each of these reaches it.
            "python3 - <<'eof'\nimport os\n"
            "os.system('cat ~/.mure{o,x}/credentials.json')\neof",
            "python3 - <<'eof'\nimport os\n"
            "os.system('cat ~/.mure\"o\"/credentials.json')\neof",
            "perl <<'eof'\nprint `cat ~/.mure{o,x}/credentials.json`;\neof",
            "ruby <<'eof'\nputs `cat ~/.mure{o,x}/credentials.json`\neof",
            "node <<'eof'\nrequire('child_process')"
            ".execSync('cat ~/.mure{o,x}/credentials.json',"
            "{stdio:'inherit'})\neof",
            # The consumer is a shell, so the body is shell text outright —
            # including the line continuation inside the group, which the
            # body's own reader joins.
            "bash <<'eof'\ncat ~/.mure{o,\\\nx}/credentials.json\neof",
        ],
    )
    def test_denies_a_reference_inside_a_body(
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
            # Everyday here-documents. A body full of quotes and braces is
            # what people actually write, so these are the rows that say the
            # latch is affordable.
            "python3 - <<'eof'\nd = {'a': 1, 'b': {'c': 2}}\neof",
            "python3 - <<'eof'\ns = {1, 2, 3}\neof",
            "python3 - <<eof\nprint('hello')\neof",
            "cat <<'eof'\ndon't worry\neof",
            "jq . <<'eof'\n{\"a\": 1}\neof",
            "awk -f - <<'eof'\n{print $1}\neof",
            "cat <<<'hello'",
            "cat <<'eof'\nuse `ls` to list\neof",
            "echo $((1<<3))",
            'echo $((1<<3)); echo "*.py"',
        ],
    )
    def test_allows_everyday_here_documents(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command

    @pytest.mark.parametrize(
        ("command", "category"),
        [
            # Over-blocks, recorded rather than hidden. Not resolving quoting
            # leaves live whatever a quote used to neutralise: an unmatched
            # bracket in a body is structure the span fold cannot pair up...
            ("python3 - <<'eof'\nprint(\"{\")\neof", "span"),
            ("python3 - <<'eof'\nprint(\"(\")\neof", "span"),
            # ...and a quoted pattern after a terminator is read as a
            # pattern, although bash hands all three of these to the program
            # unexpanded. Each of them is allowed on its own; what denies
            # them is the here-document earlier in the same command.
            #
            # Their category is the point of the rows, not an incidental: the
            # guard has read text without resolving quoting, so it does not
            # know whether the reference it found is one the shell would act
            # on, and a refusal that said the command can reach the directory
            # would be asserting something it cannot know.
            ("cat <<'eof'\nx\neof\nls '.*'", "heredoc"),
            ("cat <<'eof'\nx\neof\nsed 's/.*//' f", "heredoc"),
            ("cat <<'eof'\nx\neof\nfind . -name '.*'", "heredoc"),
        ],
    )
    def test_records_what_not_resolving_quoting_over_blocks(
        self, fake_home: Path, command: str, category: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == category, command

    @pytest.mark.parametrize(
        "command",
        [
            "python3 - <<'eof'\nd = {\"n\": len([1, 2])}\neof",
            'python3 - <<"eof"\nd = {"n": len([1, 2])}\neof',
            'python3 - <<eof\nd = {"n": len([1, 2])}\neof',
            "python3 - <<'eof'\nprint({1, 2})\neof",
            "python3 - <<'eof'\nd = {'a': f(1, 2), 'b': g(3)}\neof",
            "python3 - <<'eof'\nxs = [{'a': 1, 'b': 2}]\neof",
            "node <<'eof'\nconst o = {a: f(1, 2)};\neof",
            "psql <<'eof'\nselect a, b from t where c in (1, 2);\neof",
        ],
    )
    def test_an_operator_in_a_body_is_not_a_separator(
        self, fake_home: Path, command: str
    ) -> None:
        """Bash reads no operator in a body, so neither does this.

        A body is a run of text in whatever language the program reading it
        speaks, and in none of them is ``(`` or ``;`` a word boundary.  Reading
        them as boundaries the way a command line's are read made a brace span
        holding a call or a statement into contents the guard could not account
        for, and refused the commonest thing anyone sends a here-document: a
        short script.  A short script is not a brace group and nothing about
        this guard's subject is decided by it.

        Whitespace stays a separator inside the latch, because a body is still a
        run of lines and two braces on different lines of one are not a group.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command

    @pytest.mark.parametrize(
        "command",
        [
            # An expansion in a body is read in full, delimiter quoted or not:
            # it is where a body's text reaches a shell, either this one's or
            # one the program reading the body starts for itself.
            "cat <<eof\n$(cat ~/.mureo/credentials.json)\neof",
            "cat <<eof\n`cat ~/.mureo/credentials.json`\neof",
            "cat <<eof\n$(cat ~/.mure{o,x}/credentials.json)\neof",
            "perl <<'eof'\nprint `cat ~/.mure{o,x}/credentials.json`;\neof",
            "ruby <<'eof'\nputs `cat ~/.mure{o,x}/credentials.json`\neof",
            "python3 - <<'eof'\nimport os\nos.system('cat ~/.mure{o,x}/x')\neof",
        ],
    )
    def test_a_body_is_still_read_for_the_shell_text_in_it(
        self, fake_home: Path, command: str
    ) -> None:
        """Not reading operators is not the same as not reading the body.

        Brace groups in a body are still read, and so is every expansion in it.
        A body is what a program consumes, and several of the programs anyone
        sends one to hand their own text back to a shell; the guard cannot tell
        which line of a script does that, so it reads the text and not the
        intention.
        """
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    def test_a_refusal_inside_the_latch_does_not_claim_reachability(
        self, fake_home: Path
    ) -> None:
        """What the agent reads has to be something the guard knows.

        Outside the latch quoting is resolved, so a reference the rules find
        is one the shell would act on and the refusal says so.  Inside it,
        quoting is not resolved — deliberately, because bash does not resolve
        it in a body — and the same reference may be text the shell never
        touches.  The two cases therefore get different reasons, and neither
        borrows the other's claim.
        """
        plain = run_guard_in_shell(
            _bash_guard_command(),
            {"command": "cat ~/.mureo/credentials.json"},
            fake_home,
        )
        latched = run_guard_in_shell(
            _bash_guard_command(),
            {"command": "bash <<'eof'\ncat ~/.mureo/credentials.json\neof"},
            fake_home,
        )
        assert deny_decision(plain) == "deny"
        assert deny_decision(latched) == "deny"
        assert _refusal_category(plain) == "directory"
        assert _refusal_category(latched) == "heredoc"
        reason = json.loads(latched.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
        assert "can reach" not in reason
        assert "Read tool" in reason


@needs_shell
@pytest.mark.unit
class TestQuotingKeepsThisShellOffAMetacharacterNotEveryShell:
    """Two readings, because a quoted metacharacter answers two questions.

    The first reading collapses it, which is what quoting means to the shell in
    front of it, and every question about what *this* shell will expand has to
    be answered there.  But a quoted string is also how a command hands text to
    a program that starts a shell of its own, and that shell sees the
    metacharacter as written.  So there is a second reading that leaves it
    live, and the rules that read something written out — the directory name
    and the protected filenames — see both.

    The second reading does not answer the rule that asks whether a *pattern*
    matches.  A pattern the shell will not act on is text, which is the whole
    reason the first reading collapses it, and judging it as a pattern would
    refuse every quoted glob and regex anyone types.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "sh -c 'cat ~/.mure{o,x}/credentials.json'",
            "ssh host 'cat ~/.mure{o,x}/credentials.json'",
            "echo 'cat ~/.mure{o,x}/credentials.json' | sh",
            "python3 -c 'import os; os.system(\"cat ~/.mure{o,x}/credentials.json\")'",
            "python3 -c \"import os; os.system('cat ~/.mure{o,x}/credentials.json')\"",
            "sh -c 'cat ~/{.,z}mureo/credentials.json'",
        ],
    )
    def test_a_quoted_group_is_still_read_as_a_group(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "directory", command

    @pytest.mark.parametrize(
        "command",
        [
            # A quoted pattern is text to the shell, and the second reading
            # must not turn it into a pattern again. Each of these would be
            # refused if it did.
            'cat "$HOME/.mure?/credentials.json"',
            "sed 's/.*//' f",
            "find . -name '.*'",
            "ls '.*'",
            "grep '.*' f",
            "tar -czf a.tgz '*.py'",
            "rsync -a 'src/*' dst/",
            "jq '{a: 1, b: $x}' f",
            "awk '{print $1, $2}' f",
            "python3 -c 'print({1, 2})'",
            "kubectl get pods -o jsonpath='{.items[*].metadata.name}'",
            "echo '{a,b}'",
        ],
    )
    def test_the_second_reading_does_not_judge_a_pattern(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command


@needs_shell
@pytest.mark.unit
class TestQuotingStateRows:
    """Commands that pin the quoting automaton's states.

    Each row is refused, and its category is the one the guard reports.
    """

    @pytest.mark.parametrize(
        ("command", "category"),
        [
            (
                'python3 - <<\'eof\'\nx = "it\'s"\ncat ~/.mure{o," "x}/credentials.json\neof',
                "heredoc",
            ),
            (
                "python3 - <<'eof'\nd = {'a': 1}\ncat ~/.mure{o,\" \"x}/credentials.json\neof",
                "heredoc",
            ),
        ],
    )
    def test_denies(self, fake_home: Path, command: str, category: str) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == category, command
