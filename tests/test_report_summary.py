"""The WRITE half of #662: a report summary has to state its structure.

``mureo_state_report_set`` has always documented ``totals`` (headline
numbers) / ``flags`` (notable items) / ``narrative`` (short text), and
nothing checked any of it — so what an operator got was ~700 characters in
one paragraph, with the figures, the findings, the verdict and the proposal
all inside the string. #663 renders the structure; this file pins the half
that makes there BE one.

Read it with ``tests/test_web_assets_report_structure.py`` (the read half)
and ``tests/test_report_flags.py`` (the flag vocabulary).

Three rules, and the reason each refuses rather than repairs:

- ``narrative`` has a bound the writer cannot exceed. Over it the write is
  REFUSED — never truncated, because a sentence cut in half is worse than a
  long one (#662 says so in as many words).
- a canonical headline metric must be a raw number. ``"¥773,957"`` is the
  observed failure in miniature: it is written where the view reads
  figures, and the view can render nothing from it.
- anything outside the vocabulary is stored as written. ``totals`` also
  carries per-platform and per-goal context that is not one of mureo's six
  metrics, and refusing it would push that content back into the paragraph
  this issue exists to empty.

And reports already on disk are untouched: the bound is a write-time rule,
so a legacy paragraph still reads back verbatim and still survives a write
of a sibling report kind.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mureo.context.models import StateDocument
from mureo.context.state import read_state_file, set_report, write_state_file
from mureo.core.report_summary import (
    NARRATIVE_MAX_CHARS,
    REPORT_SUMMARY_RULE,
    REPORT_TOTALS_KEYS,
    validate_report_summary,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parent.parent

# The paragraph #662 reports, verbatim from the issue (one ``<p>``, no
# structure). It is the case the bound exists for, so it is the case tested.
_OBSERVED_WALL = (
    "日次チェック(EFFICIENCY_STABILIZE)。前回06-20から約20日ぶり。"
    "BizHint(PC)のみ稼働。直近30日(06-11〜07-10): 費用¥773,957/CV50/"
    "CPA¥15,479/CVR0.21%。前回比でCV 8→50(約6倍)、CPA ¥47,786→¥15,479"
    "(-68%)と大幅改善し、両Goal(CPA¥30k以下・月CV20以上)を現行トレンドで"
    "達成。CV計測は06-24頃から正常に登録開始。広告別: ad4623207が30CV/"
    "CPA¥12.4k主力、ad4623208が12CV/CPA¥18.1k、ad4623209が8CV/"
    "CPA¥21.6k。枠別: 4296399が費用68%集約、4311492は費用¥115,740で0CV・"
    "CTR4.66%と異常。判定=Healthy(目標達成)。CPA余裕大につき"
    "SCALE_EXPANSIONへの移行と停止中SP/PSW再開を提案(未実行)。"
)


def _state_file(tmp_path: Path) -> Path:
    fp = tmp_path / "STATE.json"
    write_state_file(fp, StateDocument(version="2"))
    return fp


# ---------------------------------------------------------------------------
# The narrative bound
# ---------------------------------------------------------------------------


def test_the_bound_is_stated_once_and_is_a_real_number() -> None:
    """Every surface quotes this constant rather than restating a number."""
    assert isinstance(NARRATIVE_MAX_CHARS, int)
    assert NARRATIVE_MAX_CHARS == 400
    assert str(NARRATIVE_MAX_CHARS) in REPORT_SUMMARY_RULE


def test_a_narrative_exactly_at_the_bound_is_accepted() -> None:
    """The bound is inclusive — an author who counted is not refused."""
    validate_report_summary({"narrative": "a" * NARRATIVE_MAX_CHARS})


def test_one_character_over_the_bound_is_refused() -> None:
    with pytest.raises(ValueError) as excinfo:
        validate_report_summary({"narrative": "a" * (NARRATIVE_MAX_CHARS + 1)})
    message = str(excinfo.value)
    # Both numbers, so the author knows how much has to move rather than
    # guessing at it.
    assert str(NARRATIVE_MAX_CHARS + 1) in message
    assert str(NARRATIVE_MAX_CHARS) in message
    # And WHERE it moves to — a refusal that only says "too long" invites a
    # shorter paragraph, not a structured report.
    assert REPORT_SUMMARY_RULE in message


def test_the_observed_paragraph_is_refused() -> None:
    """The ~700-character wall from the issue does not get written again."""
    assert len(_OBSERVED_WALL) > NARRATIVE_MAX_CHARS
    with pytest.raises(ValueError):
        validate_report_summary({"narrative": _OBSERVED_WALL})


def test_nothing_is_silently_truncated(tmp_path: Path) -> None:
    """A refused write leaves the document exactly as it was.

    Truncation is the tempting alternative and it is the wrong one: half a
    sentence reads like a bug in mureo, and the operator cannot tell what
    was cut.
    """
    fp = _state_file(tmp_path)
    set_report(fp, "daily", {"narrative": "Healthy. Nothing to do."})
    before = fp.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        set_report(fp, "daily", {"narrative": _OBSERVED_WALL})

    assert fp.read_text(encoding="utf-8") == before
    stored = read_state_file(fp).reports
    assert stored is not None
    assert stored["daily"]["narrative"] == "Healthy. Nothing to do."


def test_a_narrative_that_is_not_prose_is_refused() -> None:
    """``narrative`` is prose. A list of findings is what ``flags`` is for."""
    with pytest.raises(ValueError):
        validate_report_summary({"narrative": ["one", "two"]})
    with pytest.raises(ValueError):
        validate_report_summary({"narrative": 42})


def test_an_absent_or_null_narrative_is_not_an_error() -> None:
    validate_report_summary({})
    validate_report_summary({"narrative": None})
    validate_report_summary({"narrative": ""})


# ---------------------------------------------------------------------------
# The headline figures
# ---------------------------------------------------------------------------


def test_a_canonical_metric_must_be_a_raw_number() -> None:
    """``"¥773,957"`` where the view reads a figure renders as nothing."""
    with pytest.raises(ValueError) as excinfo:
        validate_report_summary({"totals": {"spend": "¥773,957"}})
    message = str(excinfo.value)
    assert "spend" in message
    assert REPORT_SUMMARY_RULE in message


def test_a_boolean_is_not_a_figure() -> None:
    with pytest.raises(ValueError):
        validate_report_summary({"totals": {"conversions": True}})


def test_a_metric_that_is_not_finite_is_refused() -> None:
    with pytest.raises(ValueError):
        validate_report_summary({"totals": {"cpa": float("nan")}})
    with pytest.raises(ValueError):
        validate_report_summary({"totals": {"cpa": float("inf")}})


def test_real_figures_are_accepted() -> None:
    validate_report_summary(
        {
            "totals": {
                "spend": 773957,
                "conversions": 50,
                "cpa": 15479.14,
                "ctr": 0.0466,
                "clicks": 4312,
                "impressions": 92510,
            },
            "narrative": "Both goals met; proposing SCALE_EXPANSION.",
        }
    )


def test_a_key_outside_the_vocabulary_is_stored_as_written(tmp_path: Path) -> None:
    """Passed through, not rendered as a figure — and not refused.

    ``totals`` carries context that is not one of mureo's six metrics (a
    CVR, a per-goal target, a per-platform split). Refusing it would send
    that content back into the paragraph.
    """
    fp = _state_file(tmp_path)
    summary = {"totals": {"spend": 773957, "cvr": "0.21%", "goal_target_cpa": 30000}}
    updated = set_report(fp, "daily", summary)
    assert updated.reports is not None
    assert updated.reports["daily"] == summary


def test_the_per_platform_breakdown_is_not_the_headline_row() -> None:
    """A nested platform map is not what the view renders as figures, so it
    is not held to the figure rule."""
    validate_report_summary({"kpis": {"google_ads": {"spend": "¥773,957"}}})


def test_the_field_the_view_reads_is_the_field_that_is_checked() -> None:
    """The renderer prefers ``totals`` over ``kpis`` and unwraps one nested
    ``totals`` (``reportSummaryTotals`` in ``reports_format.js``). The write
    rule follows it exactly — checking a field the view does not read would
    refuse a report that renders correctly, and vice versa."""
    # ``totals`` wins: the string in ``kpis`` is the per-platform half.
    validate_report_summary({"kpis": {"spend": "¥1"}, "totals": {"spend": 1}})
    # ...and the nested shape is unwrapped the same way the view unwraps it.
    with pytest.raises(ValueError):
        validate_report_summary({"kpis": {"totals": {"spend": "¥1"}}})
    # A bare ``kpis`` IS the headline row when no ``totals`` is stated.
    with pytest.raises(ValueError):
        validate_report_summary({"kpis": {"spend": "¥1"}})


def test_a_totals_block_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError):
        validate_report_summary({"totals": [1, 2, 3]})
    with pytest.raises(ValueError):
        validate_report_summary({"kpis": "spend 773957"})


def test_a_null_totals_is_absent_not_malformed() -> None:
    validate_report_summary({"totals": None, "kpis": None})


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_a_paragraph_already_on_disk_still_reads_back(tmp_path: Path) -> None:
    """The bound is a WRITE rule. Reports already stored are real content."""
    fp = tmp_path / "STATE.json"
    fp.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {},
                "action_log": [],
                "reports": {"daily": {"narrative": _OBSERVED_WALL}},
            }
        ),
        encoding="utf-8",
    )
    doc = read_state_file(fp)
    assert doc.reports is not None
    assert doc.reports["daily"]["narrative"] == _OBSERVED_WALL


def test_a_legacy_paragraph_survives_a_write_of_another_report(
    tmp_path: Path,
) -> None:
    """Writing today's weekly report must not be refused — nor rewritten —
    because last month's daily report is a paragraph."""
    fp = tmp_path / "STATE.json"
    fp.write_text(
        json.dumps(
            {
                "version": "2",
                "platforms": {},
                "action_log": [],
                "reports": {"daily": {"narrative": _OBSERVED_WALL}},
            }
        ),
        encoding="utf-8",
    )
    updated = set_report(fp, "weekly", {"narrative": "Steady week."})
    assert updated.reports is not None
    assert updated.reports["daily"]["narrative"] == _OBSERVED_WALL
    assert updated.reports["weekly"] == {"narrative": "Steady week."}


# ---------------------------------------------------------------------------
# One vocabulary, two languages
# ---------------------------------------------------------------------------


def test_the_python_vocabulary_matches_the_one_the_browser_renders() -> None:
    """``REPORT_TOTALS_KEYS`` and ``REPORTS_SUMMARY_TOTAL_KEYS`` are the same
    list in two languages, and a drift between them is invisible: the write
    side would accept a figure the view never prints, or refuse one it does.

    Order matters too — it is the order the detail view renders.
    """
    js = (_ROOT / "mureo" / "_data" / "web" / "reports_format.js").read_text(
        encoding="utf-8"
    )
    block = js.split("const REPORTS_SUMMARY_TOTAL_KEYS = [", 1)
    assert len(block) == 2, "REPORTS_SUMMARY_TOTAL_KEYS missing"
    keys = tuple(re.findall(r'"([a-z_]+)"', block[1].split("]", 1)[0]))
    assert keys == tuple(REPORT_TOTALS_KEYS)


def test_the_rule_names_the_fields_and_the_vocabulary() -> None:
    """The rule is what an agent reads BEFORE calling (it is pasted into the
    tool schema) and what it is told on refusal. One text, both paths."""
    for key in REPORT_TOTALS_KEYS:
        assert key in REPORT_SUMMARY_RULE
    assert "totals" in REPORT_SUMMARY_RULE
    assert "flags" in REPORT_SUMMARY_RULE
    assert "narrative" in REPORT_SUMMARY_RULE
