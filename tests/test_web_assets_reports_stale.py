"""Static-content guards for the stale-figure rendering (#638).

**Read this with ``tests/js/reports_stale_figures.test.js``.** The DECISION
— may this figure be stated as the selected window's result? — lives in
``mureo/_data/web/reports_logic.js`` and is *executed* by
``node --test tests/js/*.test.js``. The RENDERING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

The regression these exist for: a client card rendered 25,862 cost / 2
conversions / 12,931 CPA in bold as the figures for the window on screen.
That window's real cost was 0 — delivery had stopped eleven days earlier —
and the only disclosure was a small badge beside the numbers. The operator
read the numbers and reported the dashboard as broken. They were right to.

So the pin that matters is POSITIONAL, not textual: a stale figure must
never reach the slot that asserts the selected window (the client card's KPI
cells, the platform card's headline and KPI grid). It may — and must —
still be shown, restated with its age somewhere that claims nothing about
the window.

Same limits as every static guard here: these catch a deleted name, a
flipped comparison or a string that moved branch. They cannot prove a card
rendered at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"

# The pure logic module and the renderer that consumes it (#540).
_REPORTS_ASSETS = ("reports_logic.js", "dashboard_reports.js")


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _function_body(js: str, signature: str) -> str:
    """Source of the top-level function opened by ``signature``.

    Top-level helpers in dashboard.js sit at two-space indent, so the first
    ``\\n  }`` after the signature closes them; nested blocks close deeper.
    (Same helper as ``test_web_assets_reports_conflicts.py``.)
    """
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


@pytest.mark.unit
def test_the_platform_headline_is_withheld_when_the_rollup_is_stale() -> None:
    """Polarity. The card's head prints the selected period directly above
    this number, so a stale figure here IS the false statement #638 is
    about. Inverted, the one card that must not show a number is the only
    one that does."""
    card = _function_body(_read("dashboard_reports.js"), "function buildReportCard(")
    assert "const rowStale = reportsRowIsStale(platform);" in card, (
        "the platform card no longer asks the logic module whether its row " "is stale"
    )
    assert "headlineValue.textContent = rowStale" in card, (
        "the headline no longer branches on the stale verdict — a flipped "
        "comparison puts the stale figure back in the window's own slot"
    )
    # The withheld case is an em dash, never a 0: "mureo will not state
    # this" and "this account spent nothing" are opposite findings, and the
    # second is exactly what the stale card was wrongly implying.
    withheld = card.split("headlineValue.textContent = rowStale", 1)[1]
    assert withheld.split("\n", 2)[1].strip() == '? "—"', withheld[:120]


@pytest.mark.unit
def test_a_stale_platform_card_never_reaches_the_kpi_grid() -> None:
    """The grid asserts the window just as the headline does — CPA, CTR and
    conversions from an 11-day-old pull are not this window's CPA, CTR and
    conversions. The stale branch RETURNS, so the grid is unreachable from
    it; pinning that is what stops a later edit from re-appending the grid
    below the restated figures."""
    card = _function_body(_read("dashboard_reports.js"), "function buildReportCard(")
    assert "if (rowStale) {" in card
    stale_branch = card.split("if (rowStale) {", 1)[1].split("\n    }", 1)[0]
    assert (
        "return card;" in stale_branch
    ), "the stale platform card no longer returns before the KPI grid"
    assert "REPORTS_KPI_LABELS" not in stale_branch
    # …and the grid is still built after it, for every card that is not.
    assert card.index("if (rowStale) {") < card.index("REPORTS_KPI_LABELS")


@pytest.mark.unit
def test_the_client_card_states_why_a_stale_aggregate_is_withheld() -> None:
    """The aggregate is nulled in ``aggregateClientKpis`` (executed by the JS
    suite), so the cell renders "—" through the SAME comparison the conflict
    path already used. What is pinned here is that the card states the
    reason: a bare "—" reads as "no spend".

    The reason is now a badge rather than a sentence — the sentence, and the
    command, were duplicated in the alert row directly above the grid and
    moved there. The badge carries the AGE, because how old the figures are
    is the state the dash stands for; ``tests/js/reports_triage.test.js``
    asserts a withheld client always has one."""
    js = _read("dashboard_reports.js")
    card = _function_body(js, "function buildClientCard(")
    assert "reports-client-card-badge" in card
    # The explanation comes BEFORE the cells, so the "—" is never skimmed
    # without it.
    assert card.index("reports-client-card-badges") < card.index(
        'krow.className = "reports-client-card-kpis"'
    )
    # The badge says how old, not merely that it is old.
    triage = _read("reports_triage.js")
    assert "dashboard.reports_triage_tag_stale_aged" in triage
    assert "relativeAge(row.fetched_at)" in triage
    # …and the withheld figures themselves are still restated on the card.
    assert "reports-client-card-stale-figures" in card


@pytest.mark.unit
def test_the_stale_figures_are_restated_below_the_cells_not_inside_them() -> None:
    """Nothing is hidden — that was never the fix. The figures are moved OUT
    of the slot that asserts the window and into a line that states their
    age. If they were appended into ``krow`` instead they would be back in
    the position this issue is about."""
    card = _function_body(_read("dashboard_reports.js"), "function buildClientCard(")
    assert "buildStaleFiguresElement(" in card
    restated = card.split("card.appendChild(krow);", 1)
    assert len(restated) == 2, "the KPI row is no longer appended to the card"
    assert (
        "buildStaleFiguresElement(" in restated[1]
    ), "the restated stale figures no longer come AFTER the KPI cells"
    assert "buildStaleFiguresElement(" not in restated[0]
    # They go on their own element, never into a KPI cell.
    assert "krow.appendChild(buildStaleFiguresElement" not in card


@pytest.mark.unit
def test_the_restated_line_says_the_age_or_says_it_is_unknown() -> None:
    """The line's whole job is to date the figures. An age mureo cannot
    quote is stated as unknown rather than left blank — a dangling "Last
    collected : 25,862" would read as a claim about now."""
    js = _read("dashboard_reports.js")
    helper = _function_body(js, "function buildStaleFiguresElement(")
    assert "relativeAge(fetchedAt)" in helper
    assert "dashboard.reports_stale_last_collected" in helper
    assert "dashboard.reports_stale_last_collected_unknown" in helper
    # Polarity: the dated string is chosen when there IS an age.
    assert "age\n        ? " in helper or "age ? " in helper, helper[:400]


@pytest.mark.unit
def test_the_renderer_asks_the_logic_module_rather_than_re_deciding() -> None:
    """Staleness stays a property the server computed and the logic module
    reported. A renderer that re-derived it from ``fetched_at`` would drift
    from the window-scaled threshold the read side applies, and would have
    to re-decide what ``stale: null`` means every time."""
    js = _read("dashboard_reports.js")
    assert "reportsRowIsStale = REPORTS_LOGIC.reportsRowIsStale" in js
    for func in ("function buildReportCard(", "function buildClientCard("):
        body = _function_body(js, func)
        assert "stale_after_days" not in body
        assert "Date.parse(" not in body


@pytest.mark.unit
def test_unknown_freshness_keeps_its_existing_rendering() -> None:
    """``stale`` is three-valued and ``null`` means unknown. Documents
    written before the write-time stamp (#637) are full of it, so the
    withholding must key off the VERDICT — never off the mere presence of a
    freshness block, which would blank almost every historical card."""
    logic = _read("reports_logic.js")
    row = _function_body(logic, "function reportsRowIsStale(")
    assert "f.stale === true" in row, (
        "reportsRowIsStale no longer requires an explicit true — `== true` "
        "or a truthiness test would read `null` (unknown) as a verdict"
    )


@pytest.mark.unit
def test_stale_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_stale_kpis_withheld",
        "dashboard.reports_stale_last_collected",
        "dashboard.reports_stale_last_collected_unknown",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_the_restated_figures_reach_the_dom_as_text() -> None:
    """The line interpolates figures and a localized age, and it is built the
    same way every other operator-visible string here is."""
    js = _read("dashboard_reports.js")
    helper = _function_body(js, "function buildStaleFiguresElement(")
    assert "el.textContent = MUREO.t(" in helper
    for name in _REPORTS_ASSETS:
        assert ".innerHTML" not in _read(name).replace("// innerHTML", ""), name


@pytest.mark.unit
def test_the_stale_blocks_have_styles_that_can_wrap() -> None:
    """Both new elements interpolate free-form figures and platform-supplied
    labels into a flex card, so they need the same break treatment every
    other note in the card does."""
    css = _read("app.css")
    for rule in (
        ".report-card-stale",
        ".report-card-stale-figures",
        ".reports-client-card-stale-figures",
    ):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"
