"""The whole-product credential-guard sweep must run in exactly one lane (#808).

``tests/test_credential_guard_product.py`` takes about two hours, so the
per-PR ``test-slow`` job leaves it out by name and the scheduled
``credential-guard-sweep.yml`` workflow runs it instead. Both halves are
plain YAML that no test would otherwise read: a typo in the path, a dropped
``-m slow`` or a switch spelt anything but ``1`` would turn the sweep into a
green run that executed nothing, and removing the ``--ignore`` would put two
hours on every pull request. These tests pin both lanes so that neither
change can land silently.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.conftest import EXHAUSTIVE_TESTS_ENV, EXHAUSTIVE_TESTS_ON

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
_SWEEP_WORKFLOW = _WORKFLOWS / "credential-guard-sweep.yml"
_CI_WORKFLOW = _WORKFLOWS / "ci.yml"
_SWEEP_JOB = "sweep"
_SLOW_JOB = "test-slow"
_PRODUCT_FILE = "tests/test_credential_guard_product.py"
_SLOW_MARKER = "-m slow"
# Well past the measured local run (1 h 56 m), so a slower hosted runner is
# not cut off mid-sweep and reported as a guard failure.
_MIN_TIMEOUT_MINUTES = 240
_PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")

pytestmark = pytest.mark.unit


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} is not a YAML mapping"
    return document


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 reads the bare key ``on`` as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "workflow triggers are not a mapping"
    return triggers


def _steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    steps = workflow["jobs"][job]["steps"]
    assert isinstance(steps, list)
    return steps


def _step_running(workflow: dict[str, Any], job: str, needle: str) -> dict[str, Any]:
    matches = [
        step
        for step in _steps(workflow, job)
        if needle in str(step.get("run", "")) and _SLOW_MARKER in step["run"]
    ]
    assert len(matches) == 1, f"expected one {job} step running {needle!r}"
    return matches[0]


def _switch_is_on(workflow: dict[str, Any], job: str, step: dict[str, Any]) -> bool:
    for env in (workflow.get("env"), workflow["jobs"][job].get("env"), step.get("env")):
        if isinstance(env, dict) and str(env.get(EXHAUSTIVE_TESTS_ENV)) == (
            EXHAUSTIVE_TESTS_ON
        ):
            return True
    inline = re.compile(
        rf"(?:^|\s){EXHAUSTIVE_TESTS_ENV}={EXHAUSTIVE_TESTS_ON}\s+pytest\b",
        re.MULTILINE,
    )
    return bool(inline.search(step["run"]))


@pytest.fixture(scope="module")
def sweep() -> dict[str, Any]:
    return _load(_SWEEP_WORKFLOW)


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return _load(_CI_WORKFLOW)


def test_sweep_runs_on_a_schedule_and_on_demand(sweep: dict[str, Any]) -> None:
    triggers = _triggers(sweep)
    assert triggers.get("schedule"), "the sweep has no schedule"
    assert all(entry.get("cron") for entry in triggers["schedule"])
    assert "workflow_dispatch" in triggers


def test_sweep_job_has_room_for_the_whole_enumeration(
    sweep: dict[str, Any],
) -> None:
    timeout = sweep["jobs"][_SWEEP_JOB]["timeout-minutes"]
    assert isinstance(timeout, int)
    assert timeout >= _MIN_TIMEOUT_MINUTES


def test_sweep_step_runs_the_product_file_with_the_switch_on(
    sweep: dict[str, Any],
) -> None:
    step = _step_running(sweep, _SWEEP_JOB, _PRODUCT_FILE)
    assert _switch_is_on(sweep, _SWEEP_JOB, step), (
        f"the sweep step does not set {EXHAUSTIVE_TESTS_ENV}={EXHAUSTIVE_TESTS_ON},"
        " so every test in it would skip and the run would be green and empty"
    )


def test_sweep_runs_are_not_cancelled_by_a_newer_one(
    sweep: dict[str, Any],
) -> None:
    concurrency = sweep["concurrency"]
    assert concurrency["group"]
    assert concurrency["cancel-in-progress"] is False


def test_every_action_in_the_sweep_is_pinned_to_a_commit(
    sweep: dict[str, Any],
) -> None:
    used = [
        step["uses"].split("#")[0].strip()
        for job in sweep["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert used, "the sweep uses no actions at all"
    unpinned = [ref for ref in used if not _PINNED_ACTION.match(ref)]
    assert not unpinned, f"not pinned to a 40-hex commit SHA: {unpinned}"


def test_per_pr_slow_lane_still_leaves_the_product_file_out(
    ci: dict[str, Any],
) -> None:
    step = _step_running(ci, _SLOW_JOB, "pytest")
    assert (
        f"--ignore={_PRODUCT_FILE}" in step["run"]
    ), "the per-PR slow lane would run the two-hour sweep on every pull request"
