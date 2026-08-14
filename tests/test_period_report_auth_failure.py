"""/weekly-report and /monthly-report must treat an auth failure as a hole.

Field report (#602): the hole #580 closed in ``/daily-check`` was still open
in both period reports. When a platform's credentials were missing or its
token had been rejected, the run completed and shipped a report that looked
whole — auth-failure prose where the numbers belonged, next to real figures
from the platforms that did answer, followed by the usual recommendations.

For a period report the misread is worse than for a daily one. The numbers
are period *totals*, they are compared against a prior period, and they get
quoted onward to a stakeholder. A cross-platform total computed without a
platform, set beside a prior total that included it, manufactures a decline
out of a credential problem.

The detection half already exists: every platform answers an auth failure
with ``{"status": "auth_error", "auth_cause": ..., "detail": ...}`` (see
``tests/test_auth_failure_envelope.py``), and ``_mureo-shared`` documents it.
This suite pins the missing branch in both period skills, in BOTH the
packaged copy and the repo-root mirror, kept byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = ("weekly-report", "monthly-report")

#: name -> the period-over-period vocabulary that skill must use.
_PERIOD_WORD = {"weekly-report": "week", "monthly-report": "month"}


def _packaged(name: str) -> Path:
    return _ROOT / "mureo" / "_data" / "skills" / name / "SKILL.md"


def _mirror(name: str) -> Path:
    return _ROOT / "skills" / name / "SKILL.md"


def _body(name: str) -> str:
    return _packaged(name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", _SKILLS)
class TestPeriodReportAuthFailure:
    def test_copies_are_byte_identical(self, name: str) -> None:
        assert _packaged(name).read_bytes() == _mirror(name).read_bytes()

    def test_names_the_machine_readable_marker(self, name: str) -> None:
        """The skill must key on the payload, not on error prose — prose is
        exactly what it failed to recognise."""
        body = _body(name)
        assert '"status": "auth_error"' in body
        assert "auth_cause" in body

    def test_documents_both_causes_and_their_recovery(self, name: str) -> None:
        body = _body(name)
        assert "no_credentials" in body
        assert "token_invalid" in body
        assert "mureo configure" in body
        assert "re-authorize" in body

    def test_forbids_rendering_the_failure_as_data(self, name: str) -> None:
        """An unreadable platform is never a quiet platform."""
        body = _body(name)
        assert "detail" in body.lower()
        auth_lines = [ln for ln in body.splitlines() if "auth_error" in ln]
        assert auth_lines, f"{name}: no auth-failure branch in the skill"

    def test_marks_the_report_partial_and_names_the_platform(self, name: str) -> None:
        body = _body(name)
        assert "partial" in body.lower()
        partial_lines = [ln for ln in body.splitlines() if "**partial**" in ln.lower()]
        assert partial_lines, f"{name}: report is never marked partial"
        assert any("platform" in ln.lower() for ln in partial_lines)

    def test_withholds_recommendations_that_depend_on_it(self, name: str) -> None:
        lowered = _body(name).lower()
        assert "withhold" in lowered
        assert "recommendation" in lowered

    def test_refuses_to_compare_a_partial_period_with_a_complete_one(
        self, name: str
    ) -> None:
        """The load-bearing rule (#602): a period missing a platform must not
        be set against a prior period that had it. Silently doing so reads as
        a genuine drop, and the number is quoted onward."""
        body = _body(name)
        period = _PERIOD_WORD[name]
        pins = (
            f"A partial {period} is not comparable to a complete one",
            "manufactur",  # "manufactures a decline out of a credential problem"
        )
        for pin in pins:
            assert pin in body, f"{name}: missing period-comparison pin {pin!r}"
        lowered = body.lower()
        # Both escapes must be offered: restate both periods over the same
        # set of platforms, or withhold the comparison outright.
        assert "same set of platforms" in lowered
        assert "withhold the comparison" in lowered

    def test_does_not_persist_a_number_it_did_not_read(self, name: str) -> None:
        """The persisted rollup becomes the NEXT period's baseline, so a zero
        written for an unreadable platform breaks the comparison twice."""
        body = _body(name)
        assert "mureo_state_report_set" in body
        persist = [ln for ln in body.splitlines() if "auth_error" in ln]
        assert any(
            "omit" in ln.lower() for ln in persist
        ), f"{name}: must say to omit, not zero, an unread platform's KPI"

    def test_does_not_abort_the_whole_run(self, name: str) -> None:
        """One platform's credentials failing degrades the report; it never
        aborts the run — the #440 rule, unchanged."""
        assert "never aborts the run" in _body(name)
