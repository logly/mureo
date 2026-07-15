"""daily-check must author STRUCTURED report flags (PR-B).

The daily-check skill persists its report via ``mureo_state_report_set``.
PR-A added a canonical flag vocabulary + validation and PR-C renders
structured flags as coarse, localizable chips with a ``params`` drill-down.
This test pins that daily-check's SKILL.md instructs the structured
``{code, severity, params}`` shape (not the old detail-in-the-slug string),
in BOTH the packaged copy and the repo-root mirror, kept byte-identical.
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


def test_daily_check_copies_are_byte_identical() -> None:
    """The packaged skill and the repo-root mirror stay byte-identical."""
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()


def test_documents_structured_flag_shape() -> None:
    body = _body()
    assert "{code, severity, params}" in body
    assert "invalid_traffic_suspected" in body
    assert "goals_met" in body
    assert "custom" in body


def test_keeps_detail_in_params_not_the_code() -> None:
    """The load-bearing rule: detail lives in ``params`` so the chip stays a
    coarse, localizable tag — never baked into the code slug."""
    body = _body()
    assert "NOT baked into the code" in body


def test_severity_vocabulary_referenced() -> None:
    body = _body()
    assert "`action`/`watch`/`info`/`positive`" in body


def test_custom_escape_hatch_documented() -> None:
    body = _body()
    assert '{code:"custom", severity, label}' in body
