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

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_WEB = _ROOT / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


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
    js = _read("dashboard.js")
    assert "reportSummaryTotals = REPORTS_FORMAT.reportSummaryTotals" in js
    assert "function reportSummaryTotals(" not in js


@pytest.mark.unit
def test_the_figures_are_rendered_as_figures_above_the_flags_and_the_prose() -> None:
    """ "Figures as figures, flags as a list, narrative as prose" — in that
    order, because the order is what makes the block skimmable."""
    body = _function_body(_read("dashboard.js"), "function renderReportsLatest(")
    assert "reportSummaryTotals(report)" in body
    assert "report-latest-kpis" in body
    # Reuses the client card's KPI cell, so a figure reads the same wherever
    # this view prints one.
    assert "clientKpiCell(" in body
    assert body.index("reportSummaryTotals(report)") < body.index("report.flags")
    assert body.index("report.flags") < body.index("report.narrative")


@pytest.mark.unit
def test_a_report_with_no_structure_still_renders_its_prose() -> None:
    """Reports already on disk are one paragraph and nothing else. They stay
    readable — the figure row is simply absent."""
    body = _function_body(_read("dashboard.js"), "function renderReportsLatest(")
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
