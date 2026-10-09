"""Behavioral tests for brace expansion: what is one group, and what is not.

A group is part of one word, so a separator the shell acts on ends it; and
a span the shell leaves literal is not structure, at any depth.

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
class TestABraceGroupIsPartOfOneWord:
    """What counts as a group's contents is a question about quoting.

    Bash does not expand a brace group across a separator it is allowed to
    act on, so a ``{...}`` holding one is not brace expansion and costs the
    guard nothing.  A separator the shell may *not* act on is ordinary text
    in the middle of the word, so a group holding one is a group like any
    other.  Both halves matter: deciding it by which characters are present,
    rather than by whether the shell would act on them, gets one of the two
    wrong whichever way it is written.

    Every command here goes through a real bash, because every one of them
    turns on a quoting question.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # A separator the shell acts on: these are not groups, so they
            # are not expanded and cost nothing. The second is the same text
            # with the separators taken out, which IS a group — one group,
            # well inside the budget — so both spellings are allowed and for
            # different reasons.
            'echo {"a": 1, "b": 2}',
            'echo {"a":1,"b":2}',
            # The same, nine times over in a body, which is where a
            # structure that counted them as groups would run out of budget.
            "cat <<'eof'\n"
            + "\n".join(f'{{"k{i}": {i}, "v{i}": {i}}}' for i in range(9))
            + "\neof",
            # Shell brace grouping and a function body are separated by `;`
            # and by newlines, and have no comma, so they are not groups on
            # either count.
            "{ echo a; echo b; }",
            "{\necho a\necho b\n}",
            "g() { echo a; }\ng",
            # Real brace expansion keeps working: the separators are between
            # the groups, not inside them.
            "mkdir -p build/{lib,bin} dist/{a,b}",
            "cp {a,b}.txt dest/",
            "echo start; echo {a,b}",
            "echo one\necho {a,b}",
            # An object filter written for another program, quoted so the
            # shell keeps off it.
            "jq '{name: .name, id: .id}' f.json",
            "awk '{print $1, $2}' f",
        ],
    )
    def test_a_separator_the_shell_acts_on_is_not_inside_a_group(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command

    @pytest.mark.parametrize(
        "alternative",
        [
            'o,"x y"',
            "o,'x y'",
            'o,"x;y"',
            'o,"x|y"',
            'o,"x&y"',
            'o,"x(y"',
            'o,"x<y"',
            'o,"x>y"',
            'o,"x\ty"',
            'o,"x\ny"',
            "o,x\\ y",
        ],
    )
    def test_a_separator_the_shell_cannot_act_on_leaves_a_group_a_group(
        self, fake_home: Path, alternative: str
    ) -> None:
        """Quoted, the character is text; the word, and the group, are whole.

        The group's first alternative is the protected directory's own name,
        so bash expands it straight onto the directory whatever the second
        alternative holds.  ``credential_guard_product.py`` runs the same
        property against a real ``HOME`` with a marker file in it.
        """
        command = "cat ~/.mure{" + alternative + "}/credentials.json"
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "directory", command

    @pytest.mark.parametrize(
        "command",
        [
            # An expandable group holding both a separator and an expansion.
            # Bash expands neither of these, so refusing them costs nothing
            # real — and it is what keeps an expansion form the span fold
            # does not recognise on the deny side instead of making the group
            # disappear.
            "echo {a, $(date)}",
            "echo {a, $x}",
            "echo {a, ${x}}",
            "echo {a, `date`}",
            # A separator of the second kind inside an expandable group.
            "echo {a;b,c}",
            "echo {a|b,c}",
            "echo {a,b(c)}",
        ],
    )
    def test_contents_that_did_not_resolve_are_refused_on_their_own_ground(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "unresolved", command
        reason = json.loads(proc.stdout)["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
        assert "~/.mureo" not in reason, "the command never named the directory"

    def test_the_placeholders_cannot_be_written_by_the_command(
        self, fake_home: Path
    ) -> None:
        """A placeholder in the input must not buy a boundary.

        The placeholders are the only characters in the normalized text that
        mean something other than themselves — two for the kinds of separator,
        two for the braces of a span the shell leaves literal — so a command
        that writes one has to be unable to claim it: each is replaced on the
        way in.  Written inside a group, the character therefore does not make
        the group vanish, and written anywhere else it is an ordinary boundary.
        """
        for placeholder in ("\x01", "\x02", "\x03", "\x04"):
            inside = run_guard_in_shell(
                _bash_guard_command(),
                {"command": f"cat ~/.mure{{o,{placeholder}x}}/credentials.json"},
                fake_home,
            )
            assert deny_decision(inside) == "deny", placeholder
            assert _refusal_category(inside) == "directory", placeholder

            elsewhere = run_guard_in_shell(
                _bash_guard_command(),
                {"command": f"echo a{placeholder}b"},
                fake_home,
            )
            assert deny_decision(elsewhere) is None, placeholder


def _inert_nest(depth: int) -> str:
    """A ``{...}`` with no comma and no ``..``, nested ``depth`` levels deep."""
    body = ""
    for i in range(depth):
        body = "{" + chr(97 + i % 26) + body + "}"
    return body


@needs_shell
@pytest.mark.unit
class TestASpanTheShellLeavesLiteralIsNotStructure:
    """A ``{...}`` with no comma and no ``..`` is text, inside a group or out.

    Bash expands braces over the raw command before it does anything else, so
    which alternatives a group has is settled without regard to a ``{...}``
    sitting inside one: the inner span stays as written and the outer one is
    expanded.  A reading that resolved nesting by waiting for the innermost
    span to go away waited forever on an inert one, because there is nothing
    about it to resolve — and while it waited, the group around it was not a
    group to anybody but the shell.

    So the inert span's braces are taken out of the way as the literal
    characters they are, and put back before any rule runs.  Both halves are
    load-bearing: without the first the enclosing group is invisible, and
    without the second a candidate string is not the string the shell produces.
    """

    @pytest.mark.parametrize(
        "alternative",
        [
            "o,x{y}",
            "o,{y}x",
            "o,{y}x{z}",
            "o,x{}",
            "o,x{y{z}}",
            "o,x{y{z{w}}}",
            'o,x{"y"}',
            "o,p,x{y}",
            "o,x{y}z{w}",
            "o,x{y}{z}",
        ],
    )
    def test_an_inert_span_inside_a_group_leaves_the_group_a_group(
        self, fake_home: Path, alternative: str
    ) -> None:
        """The group's first alternative is the directory's own name.

        Whatever the second alternative holds, bash expands the first straight
        onto the protected directory, so the group has to be read as a group.
        """
        command = "cat ~/.mure{" + alternative + "}/credentials.json"
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "directory", command

    @pytest.mark.parametrize("depth", [1, 2, 3, 8, 20, 64])
    def test_nesting_an_inert_span_does_not_buy_depth(
        self, fake_home: Path, depth: int
    ) -> None:
        """One level or sixty-four, the group around it is still the group.

        Taking the braces out of the way needs one pass per level, so depth is
        the thing to measure rather than the one shape that showed the
        question. Past the passes the mapping is given, the text is read
        half-mapped and is therefore refused with the rest of the structure the
        budget did not finish — the deny side, which is where running out has
        to land.
        """
        command = "cat ~/.mure{o,x" + _inert_nest(depth) + "}/credentials.json"
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command

    @pytest.mark.parametrize("depth", [65, 100])
    def test_nesting_past_the_passes_is_refused_as_budget(
        self, fake_home: Path, depth: int
    ) -> None:
        """Nesting deeper than the passes can map is the budget's refusal."""
        command = "{" * depth + "a" + "}" * depth
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", depth
        assert _refusal_category(proc) == "budget", depth

    @pytest.mark.parametrize(
        "command",
        [
            # An inert span is put back as written, so a command that passes
            # one to a program reads exactly as it was typed.
            "find . -name '*.pyc' -exec rm {} ;",
            "find . -type f -exec grep -l x {} ;",
            "awk '{print $1}' f",
            "echo {}",
            "echo a{b}c",
            "echo {a}{b}",
            "git log --format={}",
            "echo {x{y}}",
            "jq '{a: {b: 1}}' f.json",
            "kubectl get pods -o jsonpath={.items[0].metadata.name}",
            "echo {a}, {b}",
            "mv x {y}",
            # Real brace expansion is unaffected: these have a comma or a
            # `..`, so they are the shell's to expand and nothing is mapped.
            "mkdir -p build/{lib,bin,share}",
            "mv file{1..10}.txt dest/",
            "cp a{,.bak}",
            "echo {1..100}",
            "echo {a,b}{c,d}",
            "echo x{1,2} y{3,4} z{5,6}",
        ],
    )
    def test_an_inert_span_costs_nothing(self, fake_home: Path, command: str) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command


def _quoted(body: str) -> str:
    """``body`` as the quoted argument of a shell that re-reads it."""
    return "sh -c 'echo " + body + "'"


def _groups(count: int) -> str:
    return " ".join(["{a,b}"] * count)


def _alternatives(count: int) -> str:
    return "{" + ",".join(["x"] * count) + "}"


@needs_shell
@pytest.mark.unit
class TestEveryReadingSetIsBoundByTheBudget:
    """What the budget does not resolve is refused in either reading set.

    The second set does not answer the pattern rule, so a coarse reading there
    would be judged by nothing.  It enumerates what it can instead, and a group
    it cannot enumerate is left unresolved and refused.  The first set keeps
    its coarse readings.
    """

    @pytest.mark.parametrize(
        "command",
        [
            _quoted(_groups(8)),
            _quoted("{1..10}"),
            _quoted("{a..c}"),
            _quoted(_alternatives(64)),
        ],
    )
    def test_allows_what_the_second_set_can_enumerate(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command

    @pytest.mark.parametrize(
        "command",
        [
            _quoted(_groups(9)),
            _quoted("{1..10..2}"),
            _quoted(_alternatives(65)),
        ],
    )
    def test_refuses_what_the_second_set_cannot_enumerate(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "budget", command

    @pytest.mark.parametrize(
        "command",
        ["echo " + _alternatives(65), "echo {1..10..2}"],
    )
    def test_the_first_set_keeps_its_coarse_readings(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", command
        assert _refusal_category(proc) == "directory", command
