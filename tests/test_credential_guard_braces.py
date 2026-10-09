"""Behavioral tests for brace expansion: what is one group, and what is not.

A group is part of one word, so a separator the shell acts on ends it; and
a span the shell leaves literal is not structure, at any depth.

How these tests run the hook payloads is described in
``tests/test_credential_guard.py``; the helpers they share are in
``tests/credential_guard_support.py``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.credential_guard_support import (
    _bash_guard_command,
    _refusal_category,
    needs_shell,
)
from tests.hook_guard_runner import BASH, deny_decision, run_guard_in_shell


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
    """``count`` two-way groups with no separator between them."""
    return "{a,b}" * count


def _alternatives(count: int) -> str:
    """One group of ``count`` distinct alternatives."""
    return "{" + ",".join(f"x{i}" for i in range(count)) + "}"


def _quoted_args(regions: int) -> str:
    """``regions`` separate quoted words, each full of groups on its own.

    The words are separated by unquoted spaces, so each is a word of its own
    to the shell that re-reads the string, and the second set expands them
    one at a time.
    """
    word = "'" + _groups(10) + "'"
    return "echo " + " ".join([word] * regions)


@needs_shell
@pytest.mark.unit
class TestEveryReadingSetIsBoundByTheBudget:
    """What the budget does not resolve is refused in either reading set.

    The second set does not answer the pattern rule, so a coarse reading there
    would be judged by nothing.  It enumerates what it can instead, and a group
    it cannot enumerate is left unresolved and refused.  The first set keeps
    its coarse readings.

    The second set is expanded a word at a time.  One word makes at most 1,024
    distinct strings in a pass, and the words of a command make at most 4,096
    between them; a word that would overrun either is left unresolved.  Equal
    strings are counted once, so a group whose alternatives repeat costs only
    what its distinct members do.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # One word, ten two-way groups: 1024 strings, at the limit.
            _quoted(_groups(10)),
            # One group of distinct alternatives, at the limit.
            _quoted(_alternatives(1024)),
            # Four words of 1024 each, at the total.
            _quoted_args(4),
            # Separated words each stay small, so many of them are fine.
            "echo '" + _groups(6) + "' '" + _groups(6) + "'",
            _quoted("{1..10}"),
            _quoted("{a..c}"),
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
            # One more two-way group than the per-word limit holds.
            _quoted(_groups(11)),
            # One more distinct alternative than the per-word limit holds.
            _quoted(_alternatives(1025)),
            # One more word than the total holds.
            _quoted_args(5),
            _quoted("{1..10..2}"),
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


def _objects(count: int, sep: str = ",", colon: str = ":") -> str:
    return sep.join(
        f'{{"id"{colon}{i}{sep}"name"{colon}"item{i}"}}' for i in range(count)
    )


_THREE_DICTS = "a={'x':1,'y':2,'z':3}; b={'x':1,'y':2,'z':3}; c={'x':1,'y':2,'z':3}"


@needs_shell
@pytest.mark.unit
class TestQuotedDataIsNotRefusedForItsSize:
    """Data handed to a program in one quoted string is allowed.

    JSON for ``curl -d``, a dict in a ``python -c`` script: each brace pair
    with a comma in it is a group to a shell that re-reads the string, so the
    second reading set expands it.  Expanding the string as a whole multiplied
    the groups of every word together and refused ordinary payloads on the
    budget; expanding it a word at a time, and counting equal strings once,
    gives the same candidates without the product.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "curl -s -X POST -H 'Content-Type: application/json' -d "
            '\'{"ids":[' + ",".join(str(i) for i in range(1, 71)) + "]}' "
            "https://example.com/api",
            "curl -s -d '[" + _objects(9) + "]' https://example.com/api",
            "curl -s -d '[" + _objects(9, ", ", ": ") + "]' https://example.com/api",
            'python3 -c "' + _THREE_DICTS + "; s='" + "x" * 4000 + "'; "
            'print(a,b,c,len(s))"',
            'python3 -c "' + _THREE_DICTS + '; print(a,b,c)"',
            "jq '.items[] | {id: .id, name: .name, tags: [.tags[] | "
            "{k: .key, v: .value}]}' data.json",
            "git commit -m 'refactor: accept {a, b} and {c, d} in config parser'",
            "curl -s -X POST https://example.com/api/v1/items "
            "-H 'Content-Type: application/json' -d "
            '\'{"items":['
            + ",".join(
                f'{{"sku":"abc-{i:03d}","qty":{i},"price":{i * 100}}}' for i in range(5)
            )
            + '],"note":"'
            + "y" * 200
            + "\"}'",
        ],
    )
    def test_benign_json_and_scripts_are_allowed(
        self, fake_home: Path, command: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": command}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) is None, command


def _second_set_alternatives(group: str) -> set[str]:
    """What the second reading set makes of ``group``, as the hook sees it.

    The hook lowercases the command before reading it, so the group is
    lowercased here too, and the result is compared with a real bash run.
    """
    from mureo._credential_guard.braces import _BRACE_HELPERS
    from mureo._credential_guard.chars import _CHARS

    scope: dict[str, Any] = {}
    exec("import re, functools; " + _CHARS + _BRACE_HELPERS, scope)
    return set(scope["aq"](group.lower()))


@needs_shell
@pytest.mark.unit
class TestOneCharacterRangesInTheSecondSet:
    """A one-character range is a sequence to bash only between two letters.

    Bash compares the endpoints as written, but the hook only ever sees the
    command lowercased, so it reads a letter range as the widest range its
    endpoints could have spelled.  That is a superset of what bash makes of
    any case-spelling, which is the safe direction.  A range whose endpoint is
    not a letter is not a sequence it enumerates, so it is left unresolved and
    refused.
    """

    @pytest.mark.parametrize(
        "group",
        ["{A..Z}", "{a..z}", "{A..z}", "{a..Z}", "{z..a}", "{Z..A}", "{a..d}"],
    )
    def test_the_enumeration_is_a_superset_of_what_bash_makes(self, group: str) -> None:
        assert BASH is not None
        made = subprocess.run(
            [BASH, "-c", "for x in " + group + '; do printf "<%s>" "$x"; done'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        chars = {m.lower() for m in made[1:-1].split("><") if m}
        assert len(chars) > 1, made
        assert chars <= _second_set_alternatives(group)

    @pytest.mark.parametrize("group", ["{-..0}", "{@..a}", "{a..~}", "{0..a}"])
    def test_a_range_between_non_letters_is_refused(
        self, fake_home: Path, group: str
    ) -> None:
        proc = run_guard_in_shell(
            _bash_guard_command(), {"command": _quoted(group)}, fake_home
        )
        assert proc.returncode == 0, proc.stderr
        assert deny_decision(proc) == "deny", group
        assert _refusal_category(proc) == "budget", group
