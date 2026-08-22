"""Static-content guards for the stored report's structure (#662, read half).

**Read this with ``tests/js/reports_format.test.js``.** WHICH fields of a
stored report summary are headline figures is decided in
``mureo/_data/web/reports_format.js`` and *executed* by
``node --test tests/js/*.test.js``. The RENDERING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

The report summary has always been ``{totals / kpis, flags, narrative}``.
Nothing rendered the first, so a report that put its figures where they
belong looked exactly like one that folded them into the paragraph — and
what an operator got was ~700 characters in a single ``<p>``.

What is pinned:

- the figures are rendered as figures, ABOVE the flags and the prose;
- the renderer does not decide which fields are figures — a report summary
  is agent-written, and everything that reaches that row is presented as a
  headline number;
- a report that states no structure still renders. Reports already on disk
  are real content: they stay readable as prose rather than being
  reformatted by guesswork.

This is the read half only. Making the writer USE the structure — the
enforced ``narrative`` bound — is the other half of #662 and is not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_WEB = _ROOT / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


#: The Reports rendering layer, split six ways by #687. A test that asserts
#: about symbols on more than one side of that split reads the whole layer
#: rather than guessing which file a given renderer ended up in.
_REPORTS_LAYER = (
    "dashboard_reports.js",
    "dashboard_reports_report.js",
    "dashboard_reports_overview.js",
    "dashboard_reports_cards.js",
    "dashboard_reports_triage.js",
    "dashboard_reports_state.js",
)


def _read_layer() -> str:
    return "\n".join(_read(name) for name in _REPORTS_LAYER)


def _function_body(js: str, signature: str) -> str:
    """Source of the top-level function opened by ``signature``.

    (Same helper as ``test_web_assets_reports_triage.py``.)
    """
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


@pytest.mark.unit
def test_the_renderer_binds_the_vocabulary_rather_than_re_deciding_it() -> None:
    """Everything that reaches the figure row is presented as a headline
    number, over an object an agent wrote. Which fields qualify is a
    decision the JS suite executes."""
    js = _read("dashboard_reports_state.js")
    assert "reportSummaryTotals = REPORTS_FORMAT.reportSummaryTotals" in js
    assert "function reportSummaryTotals(" not in js


@pytest.mark.unit
def test_the_figures_are_rendered_as_figures_under_the_conclusion() -> None:
    """ "Conclusion as prose, figures as figures" — in that order.

    #691 turned this block into tier (1) of three and led it with the
    narrative, because the report's opening sentence is its conclusion and it
    is what an operator opened the page for. The flag row moved to tier (2),
    which is the tier about what is WRONG — see ``buildReportFlagRow``.

    What is pinned here is unchanged in substance: the figures are rendered
    as figures, by the same cell the client card uses.
    """
    body = _function_body(_read_layer(), "function renderReportsLatest(")
    assert "reportSummaryTotals(report)" in body
    assert "report-latest-kpis" in body
    # Reuses the client card's KPI cell, so a figure reads the same wherever
    # this view prints one.
    assert "clientKpiCell(" in body
    assert body.index("report.narrative") < body.index("reportSummaryTotals(report)")
    # The flags are still rendered, and still capped — in tier (2).
    flag_row = _function_body(_read_layer(), "function buildReportFlagRow(")
    assert "report-flags" in flag_row
    assert "REPORT_FLAG_CAP" in flag_row


@pytest.mark.unit
def test_a_report_with_no_structure_still_renders_its_prose() -> None:
    """Reports already on disk are one paragraph and nothing else. They stay
    readable — the figure row is simply absent."""
    body = _function_body(_read_layer(), "function renderReportsLatest(")
    assert "if (totals.length > 0) {" in body
    assert "if (report.narrative) {" in body


@pytest.mark.unit
def test_the_figure_row_has_no_reserved_empty_cells() -> None:
    """A row of dashes is not a report. The block is built from what the
    report stated and nothing else."""
    css = _read("app.css")
    body = css.split(".report-latest-kpis {", 1)
    assert len(body) == 2, ".report-latest-kpis rule missing"
    block = body[1].split("}", 1)[0]
    assert "min-width: 0" in block


# ---------------------------------------------------------------------
# The report's own statistics, below the headline row (#670)
# ---------------------------------------------------------------------
#
# The other half of #662's write-side choice. Keys outside the canonical six
# are STORED — a goal review's CVR, its per-goal target, a per-platform split
# — because refusing them sends that content back into the paragraph the
# length bound exists to empty. Nothing read them, so they were accepted on
# write and invisible for good: #659's shape one field over.
#
# `tests/js/reports_latest_stats.test.js` drives this against the real DOM.
# What is pinned here is the part a rendering test would still pass without:
# that the values are not put through a formatter on the way out.


@pytest.mark.unit
def test_the_secondary_stats_are_read_from_the_vocabulary_module() -> None:
    """Same split as the headline row: dashboard.js renders, it does not
    decide what a report stated."""
    js = _read("dashboard_reports_state.js")
    assert "reportSecondaryStats = REPORTS_FORMAT.reportSecondaryStats" in js
    assert "function reportSecondaryStats(" not in js


@pytest.mark.unit
def test_the_stats_sit_below_the_headline_row() -> None:
    """Below, and visibly not part of it: these are the report's own words
    for something mureo has no headline label for.

    The "and above the flags" half of this pin retired with #691, which moved
    the flag row to tier (2). What it was protecting — that these are never
    read as the headline figures — is the ordering below, which still holds.
    """
    body = _function_body(_read_layer(), "function renderReportsLatest(")
    assert "reportSecondaryStats(report)" in body
    assert "buildReportStatsRow(stats)" in body
    assert "report-latest-stats" in _function_body(
        _read_layer(), "function buildReportStatsRow("
    )
    assert body.index("reportSummaryTotals(report)") < body.index(
        "reportSecondaryStats(report)"
    )


@pytest.mark.unit
def test_a_stat_value_is_printed_as_written() -> None:
    """No thousands separator, no percentage heuristic, no currency: the
    formatters here all answer a question about a metric mureo knows, and
    applying one to a figure it does not know is how a view ends up stating
    a number the report never wrote."""
    helper = _function_body(_read_layer(), "function buildReportStatElement(")
    assert "textContent = String(" in helper
    assert "formatKpi(" not in helper
    assert "formatNumber(" not in helper


@pytest.mark.unit
def test_what_cannot_be_shown_flat_is_counted_not_dropped() -> None:
    """A silently discarded entry is the bug #670 was filed about."""
    row = _function_body(_read_layer(), "function buildReportStatsRow(")
    assert "stats.hidden > 0" in row
    assert "dashboard.reports_stats_more" in row


@pytest.mark.unit
def test_the_stats_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in ("dashboard.reports_stats_title", "dashboard.reports_stats_more"):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_a_stat_chip_does_not_look_like_a_headline_figure() -> None:
    """The row above states mureo's own metrics for the window. These are
    the report's, and they must not be read as the same thing."""
    css = _read("app.css")
    for selector in (".report-latest-stats {", ".report-stat {"):
        assert selector in css, f"{selector} rule missing"
    block = css.split(".report-stat {", 1)[1].split("}", 1)[0]
    assert "font-size" in block
