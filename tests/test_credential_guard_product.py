"""Differential tests for the Bash guard: what the shell does vs what the
guard decides.

The parametrised rows in ``test_credential_guard.py`` pin roughly ninety
spellings someone thought of.  These check a whole product, and they check
it against a real bash rather than against a re-implementation of the rule
— which is the only way the earlier bypasses were ever found.

Two speeds:

* the default run takes an evenly-strided sample of the product and asks
  the guard about each.  It is deterministic, needs a couple of hundred
  subprocesses, and is what CI defends on every commit;
* ``-m slow`` runs the whole product, and additionally executes every
  member in a throwaway HOME to confirm it really does read the marker
  file.  This is where the counts quoted in
  ``mureo/credential_guard.py`` come from::

      pytest tests/test_credential_guard_product.py -m slow

Keep the numbers in that docstring and the output of the slow run in step.
If you add an axis here, update them; if a claim there has no counterpart
here, delete the claim.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.credential_guard_product import (
    build_home,
    members,
    reads_marker,
)
from tests.hook_guard_runner import BASH, PYTHON3, deny_decision, run_guard_in_shell

needs_shell = pytest.mark.skipif(
    BASH is None or PYTHON3 is None,
    reason="the differential product needs both bash and python3 on PATH",
)

# The sample the default run checks. Strided rather than random so a
# failure names the same member on every machine.
_SAMPLE_STRIDE = 23


def _bash_guard_command() -> str:
    from mureo.credential_guard import bash_guard_entry

    return bash_guard_entry()["hooks"][0]["command"]


def _denies(command: str, home: Path) -> bool:
    proc = run_guard_in_shell(_bash_guard_command(), {"command": command}, home)
    assert proc.returncode == 0, proc.stderr
    return deny_decision(proc) == "deny"


@needs_shell
@pytest.mark.unit
class TestProductSample:
    def test_sample_of_the_product_is_denied(self, tmp_path: Path) -> None:
        """Every strided member of the product must deny.

        Each is a spelling of ``~/.mureo/credentials.json`` assembled from
        a parent form, a way of breaking the name, a filling for that form,
        a nesting depth and a position. None of them contains the six
        characters of the directory name consecutively unless the ``none``
        break was chosen.
        """
        home = Path(build_home(str(tmp_path)))
        sample = members()[::_SAMPLE_STRIDE]
        assert len(sample) > 100, "the product shrank; check the axes"
        missed = [label for label, cmd in sample if not _denies(cmd, home)]
        assert not missed, f"{len(missed)} of {len(sample)} allowed: {missed[:5]}"

    def test_the_axes_are_all_represented(self) -> None:
        """A guard against an axis quietly dropping out of the product."""
        labels = [label for label, _ in members()]
        for axis in ("$VAR", "backtick", "continuation", "brace here", "sequence"):
            assert any(axis in label for label in labels), axis
        for depth in ("d0", "d3", "d11", "d20"):
            assert any(label.endswith(depth) for label in labels), depth


@pytest.fixture
def only_when_asked_for(request: pytest.FixtureRequest) -> None:
    """Run only when ``slow`` was selected, so a plain ``pytest`` skips it.

    Expressed here rather than as a global ``addopts`` filter: a marker that
    silently disappears from the default run is how a suite ends up with
    checks nobody has executed in months.
    """
    if "slow" not in str(request.config.getoption("markexpr")):
        pytest.skip("exhaustive; run with: pytest -m slow")


@needs_shell
@pytest.mark.slow
class TestWholeProduct:
    @pytest.mark.usefixtures("only_when_asked_for")
    def test_every_member_reads_the_file_and_is_denied(self, tmp_path: Path) -> None:
        """The claim the module docstring makes, in full.

        Both halves matter. That every member is denied is the guarantee;
        that every member really reads the marker is what stops the product
        quietly filling up with commands that prove nothing.
        """
        home = Path(build_home(str(tmp_path)))
        all_members = members()
        inert = [
            label
            for label, cmd in all_members
            if not reads_marker(cmd, home, BASH or "bash")
        ]
        missed = [label for label, cmd in all_members if not _denies(cmd, home)]
        assert not inert, f"{len(inert)} members do not reach the file: {inert[:5]}"
        assert not missed, f"{len(missed)} allowed: {missed[:5]}"


@needs_shell
@pytest.mark.unit
class TestNestingDepth:
    """The expansion budget's cliff, which cost a round on its own.

    Past the budget the old code left literal braces in the candidates —
    ordinary characters to fnmatch — so neither rule fired. Unresolved
    structure now denies on its own, and this is the table that says so.
    """

    @staticmethod
    def _nested(depth: int, alts: int) -> str:
        inner = "mureo"
        for level in range(1, depth + 1):
            filler = ",".join(f"z{level}x{k}" for k in range(alts - 1))
            inner = "{" + filler + "," + inner + "}"
        return "cat ~/." + inner + "/credentials.json"

    @pytest.mark.parametrize("alts", [2, 3, 5])
    @pytest.mark.parametrize("depth", list(range(1, 21)))
    def test_denies_at_every_depth(self, tmp_path: Path, depth: int, alts: int) -> None:
        home = Path(build_home(str(tmp_path)))
        command = self._nested(depth, alts)
        assert reads_marker(command, home, BASH or "bash"), "case proves nothing"
        assert _denies(command, home), command


@needs_shell
@pytest.mark.unit
class TestResourceBounds:
    """A guard that is merely slow is a guard that is bypassed.

    ``sys.excepthook`` cannot catch the host killing an overrunning hook,
    and that process exits non-zero without printing the deny JSON — the
    non-blocking case, where the tool call proceeds. Oversized input is
    therefore refused before any of the analysis runs.
    """

    @staticmethod
    def _decide(command: str, seconds: float) -> str:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        proc = subprocess.run(
            [BASH or "bash", "-c", _bash_guard_command()],
            input=payload,
            capture_output=True,
            text=True,
            timeout=seconds,
        )
        assert proc.returncode == 0, proc.stderr[:400]
        return "deny" if proc.stdout.strip() else "allow"

    @pytest.mark.parametrize(
        ("label", "alt_len", "alts", "groups"),
        [
            ("modest", 100, 4, 2),
            ("wide alternatives", 8000, 64, 4),
            ("wide and repeated", 8000, 64, 8),
            ("multi-megabyte", 16000, 64, 8),
        ],
    )
    def test_expansion_bombs_are_answered_quickly(
        self, label: str, alt_len: int, alts: int, groups: int
    ) -> None:
        body = ",".join(["z" * alt_len] * (alts - 1) + ["mureo"])
        command = (
            "cat ~/." + "".join("{" + body + "}" for _ in range(groups)) + "/creds"
        )
        # A generous ceiling: the point is that it answers at all, in time
        # the host will not kill it. Locally these run in ~0.2s.
        assert self._decide(command, seconds=15) == "deny", label

    def test_oversized_commands_are_refused_at_the_boundary(self) -> None:
        """Nothing legitimate approaches 64 KB, and past it the guard has
        not read the command, so it cannot say the command is safe."""
        assert self._decide("echo " + "z" * (65536 - 5), seconds=15) == "allow"
        assert self._decide("echo " + "z" * (65537 - 5), seconds=15) == "deny"
