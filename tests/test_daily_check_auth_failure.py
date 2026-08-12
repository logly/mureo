"""/daily-check must treat a platform's auth failure as a first-class outcome.

Field report (#580): a platform's token had expired, the run went through
every step, and the report shipped with ``"API error: Meta API request failed
(status=400, ...)"`` sitting where the numbers belonged, next to real figures
from the platforms that did answer, followed by the usual recommendations.
Nothing marked the report partial, so it read as "that platform was quiet"
rather than "that platform was unreadable".

Every failure-handling line the skill already had addresses a different
condition and says to keep going — the analytics-module fall-through, the
official-hosted-MCP tool-surface fallbacks, and step 2b's ``blind_spots``.
This suite pins the missing branch, in BOTH the packaged copy and the
repo-root mirror, kept byte-identical.

Marks: unit — pure on-disk file inspection, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent
_PACKAGED = _ROOT / "mureo" / "_data" / "skills" / "daily-check" / "SKILL.md"
_MIRROR = _ROOT / "skills" / "daily-check" / "SKILL.md"


def _body() -> str:
    return _PACKAGED.read_text(encoding="utf-8")


def test_copies_are_byte_identical() -> None:
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()


def test_names_the_machine_readable_marker() -> None:
    """The skill must key on the payload, not on error prose — prose is
    exactly what it failed to recognise."""
    body = _body()
    assert '"status": "auth_error"' in body
    assert "auth_cause" in body


def test_documents_both_causes() -> None:
    body = _body()
    assert "no_credentials" in body
    assert "token_invalid" in body


def test_forbids_rendering_the_failure_as_data() -> None:
    """An unreadable platform is never a quiet platform."""
    body = _body().lower()
    assert "quiet" in body
    assert "detail" in body


def test_marks_the_report_partial_and_names_the_platform() -> None:
    body = _body().lower()
    assert "partial" in body
    auth_lines = [ln for ln in _body().splitlines() if "auth_error" in ln]
    assert auth_lines, "no auth-failure branch in the skill"
    assert any("platform" in ln.lower() for ln in auth_lines)


def test_withholds_recommendations_that_depend_on_the_missing_platform() -> None:
    lowered = _body().lower()
    assert "withhold" in lowered
    assert "recommendation" in lowered


def test_does_not_abort_the_whole_run() -> None:
    """The #440 rule — never fail the whole daily-check because one platform
    broke — still holds; the report degrades, it does not stop."""
    assert "never fail the whole daily-check" in _body()
