"""weekly-report and goal-review must author STRUCTURED report flags.

Follow-up to the daily-check migration: the same canonical
``{code, severity, params}`` vocabulary now drives the weekly and goal reports
too (see ``tests/test_daily_check_structured_flags.py``). This pins that both
SKILL.md files instruct the structured shape — not the old detail-in-the-slug
string — in BOTH the packaged copy and the repo-root mirror, byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(params=["weekly-report", "goal-review"])
def skill(request):
    name = request.param
    packaged = _ROOT / "mureo" / "_data" / "skills" / name / "SKILL.md"
    mirror = _ROOT / "skills" / name / "SKILL.md"
    return name, packaged, mirror


def test_copies_byte_identical(skill) -> None:
    _name, packaged, mirror = skill
    assert packaged.read_bytes() == mirror.read_bytes()


def test_documents_structured_flag_shape(skill) -> None:
    _name, packaged, _mirror = skill
    body = packaged.read_text(encoding="utf-8")
    assert "{code, severity, params}" in body
    assert "NOT baked into the code" in body
    assert "`action`/`watch`/`info`/`positive`" in body
    assert '{code:"custom", severity, label}' in body
    assert "goals_met" in body


def test_legacy_slug_example_is_gone(skill) -> None:
    """The old detail-in-the-slug example strings must be replaced."""
    name, packaged, _mirror = skill
    body = packaged.read_text(encoding="utf-8")
    stale = {
        "weekly-report": "meta_ads_cpa_up_15pct",
        "goal-review": "goal_cpa_off_track",
    }[name]
    # It may still be referenced as the "never write a slug like …" counter-
    # example, but must not be the promoted `flags` value any more.
    assert f'["{stale}"]' not in body
