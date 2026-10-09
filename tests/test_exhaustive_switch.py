"""The exhaustive-lane switch must not be satisfiable by a typo.

``tests/conftest.py`` runs the ``slow`` lanes only when the switch is exactly
``"1"``. Any other value used to skip all of them and exit 0, so a CI job that
spelt it ``true`` would be green and empty — the failure the ``test-slow`` job
was added to end. A value that is neither unset nor ``"1"`` is now a usage
error, which fails the run before anything is collected.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from tests._measurement_child import CHILD_TIMEOUT_SECONDS
from tests.conftest import EXHAUSTIVE_TESTS_ENV

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _collect_this_file(switch: str | None) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items()}
    env.pop(EXHAUSTIVE_TESTS_ENV, None)
    if switch is not None:
        env[EXHAUSTIVE_TESTS_ENV] = switch
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            str(pathlib.Path(__file__).resolve()),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        timeout=CHILD_TIMEOUT_SECONDS,
    )


@pytest.mark.unit
@pytest.mark.parametrize("misspelt", ["true", "yes", "0", ""])
def test_a_misspelt_switch_fails_the_run(misspelt: str) -> None:
    proc = _collect_this_file(misspelt)

    assert proc.returncode == pytest.ExitCode.USAGE_ERROR, (
        proc.returncode,
        proc.stdout[-1000:],
        proc.stderr[-1000:],
    )
    assert EXHAUSTIVE_TESTS_ENV in proc.stderr, proc.stderr[-1000:]


@pytest.mark.unit
@pytest.mark.parametrize("accepted", [None, "1"])
def test_the_accepted_values_still_run(accepted: str | None) -> None:
    proc = _collect_this_file(accepted)

    assert proc.returncode == pytest.ExitCode.OK, (proc.stdout, proc.stderr)
