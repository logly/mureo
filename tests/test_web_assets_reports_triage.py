"""Static-content guards for the multi-client triage layer (#651).

**Read this with ``tests/js/reports_triage.test.js``.** The DECISIONS — which
findings a client raises, in what order, and what to run about each — live in
``mureo/_data/web/reports_triage.js`` and are *executed* by
``node --test tests/js/*.test.js``. The RENDERING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

What is pinned, and why each one is the thing that would break:

- the layer is built and rendered ONLY by ``renderReportsIndex``, the
  multi-client view. A single-workspace install never calls it, which is
  what makes the summary's own omission (``tests/test_web_reports_triage.py``)
  a complete answer rather than half of one;
- the heading's count and the marked cards come from ONE list, so a refactor
  cannot leave "3 clients need attention" above two marked cards;
- the layer sits ABOVE the grid — a triage layer below the cards it triages
  is not one;
- it is hidden when it holds nothing (no "0 alerts" banner competing with
  the cards), and hidden again whenever the view leaves the index;
- writer-supplied text (a collection-failure reason, a platform key) reaches
  the DOM as text, never as markup.

Same limits as every static guard here: these catch a deleted name, a
flipped condition or a string that moved branch. They cannot prove a card
rendered at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_WEB = _ROOT / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _function_body(js: str, signature: str) -> str:
    """Source of the top-level function opened by ``signature``.

    (Same helper as ``test_web_assets_reports_stale.py``.)
    """
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


# ---------------------------------------------------------------------------
# The module ships, and the renderer does not re-decide anything
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_module_is_served_and_loaded_before_the_dashboard() -> None:
    """It publishes one global that ``dashboard.js`` binds at load, so it has
    to be in the allow-list AND ahead of ``dashboard.js`` in the page."""
    from mureo.web.handlers import _STATIC_ALLOWLIST

    assert "reports_triage.js" in _STATIC_ALLOWLIST
    html = _read("app.html")
    assert html.index("/static/reports_triage.js") < html.index("/static/dashboard.js")
    # It reads reports_logic.js's decisions off the page, so that one first.
    assert html.index("/static/reports_logic.js") < html.index(
        "/static/reports_triage.js"
    )


@pytest.mark.unit
def test_the_renderer_binds_the_module_rather_than_re_deciding() -> None:
    """Ranking a finding and naming its next step are decisions the JS suite
    executes. A renderer that re-derived either would drift from it, and a
    substring pin cannot catch an inverted comparison."""
    js = _read("dashboard.js")
    for name in (
        "buildReportsTriage",
        "triageItemText",
        "triageItemNextStep",
        "triageMarksClient",
    ):
        assert f"{name} = REPORTS_TRIAGE.{name}" in js, f"{name} is not bound"
        assert f"function {name}(" not in js, f"{name} was copied into dashboard.js"


@pytest.mark.unit
def test_the_ranking_lives_in_the_module_and_nowhere_else() -> None:
    """ "State the ordering in code, do not leave it to render order." The
    renderer must not sort, slice or re-order the items it is handed."""
    render = _function_body(_read("dashboard.js"), "function renderReportsTriage(")
    for forbidden in (".sort(", ".reverse(", ".slice("):
        assert forbidden not in render, f"the renderer re-orders items ({forbidden})"
    triage = _read("reports_triage.js")
    assert "REPORTS_TRIAGE_KINDS" in triage
    assert ".sort(" in triage, "the module does not order its own items"


# ---------------------------------------------------------------------------
# Where it appears: the index view only, above the grid
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_only_the_multi_client_index_builds_the_layer() -> None:
    """The Agency seam is what supplies a second client, and
    ``renderReportsIndex`` is the only view that seam produces. A single
    workspace opens the detail directly and must be untouched."""
    js = _read("dashboard.js")
    assert js.count("buildReportsTriage(") == 1, "the layer is built in >1 place"
    index = _function_body(js, "async function renderReportsIndex(")
    assert "buildReportsTriage(rows, summaries)" in index
    assert "renderReportsTriage(" in index
    detail = _function_body(js, "async function renderReportsSummary(")
    assert "Triage" not in detail, "the single-client view renders the layer"


@pytest.mark.unit
def test_the_layer_sits_above_the_grid_it_triages() -> None:
    html = _read("app.html")
    assert html.index("data-reports-triage") < html.index("data-reports-clients")


@pytest.mark.unit
def test_leaving_the_index_hides_the_layer() -> None:
    """It describes the grid. Left behind over a detail view it would be
    stating findings about clients that are no longer on screen."""
    view = _function_body(_read("dashboard.js"), "function setReportsView(")
    assert "data-reports-triage" in view
    assert 'view !== "index"' in view


# ---------------------------------------------------------------------------
# Silence when there is nothing (requirement 4)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_empty_layer_renders_nothing_at_all() -> None:
    """No "0 alerts" banner competing for attention with the cards. The box
    is hidden and the list is emptied before the early return, so a stale row
    cannot survive a re-render that found nothing."""
    render = _function_body(_read("dashboard.js"), "function renderReportsTriage(")
    assert "box.hidden = !items.length" in render
    empty_at = render.index('list.textContent = ""')
    assert empty_at < render.index("box.hidden = !items.length")
    assert "if (!items.length) return;" in render
    assert render.index("if (!items.length) return;") < render.index(
        "dashboard.reports_triage_title"
    ), "the heading is written before the empty check"
    # Hidden by default in the markup, so a page that never reaches the
    # index (a single-workspace install) shows nothing either.
    html = _read("app.html")
    block = html.split("data-reports-triage", 1)[1].split(">", 1)[0]
    assert "hidden" in block


# ---------------------------------------------------------------------------
# The count equals the marked cards (acceptance)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_heading_count_and_the_card_marks_come_from_one_list() -> None:
    """ "If the layer says three clients need attention, exactly three cards
    are marked." The two cannot drift while they read the same array — the
    JS suite pins the array itself."""
    js = _read("dashboard.js")
    render = _function_body(js, "function renderReportsTriage(")
    assert "built.clients" in render, "the heading counts something else"
    assert "n: marked.length" in render, "the heading counts something else"
    index = _function_body(js, "async function renderReportsIndex(")
    assert "triageMarksClient(triage, i)" in index, "cards are marked from elsewhere"
    # The mark reaches the card item, which is the element the grid lays out.
    item = _function_body(js, "function buildClientCardItem(")
    assert "is-triaged" in item


@pytest.mark.unit
def test_a_marked_card_is_announced_and_not_only_coloured() -> None:
    """Colour alone is not a mark. The grid is a list of interactive cards,
    so the marker carries text an assistive technology can read."""
    item = _function_body(_read("dashboard.js"), "function buildClientCardItem(")
    assert "dashboard.reports_triage_card_marker" in item


# ---------------------------------------------------------------------------
# What reaches the DOM
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_rendered_row_carries_its_next_step() -> None:
    """ "An item with no next step is a bug in the item, not a display
    detail." The renderer asks for one on every row."""
    row = _function_body(_read("dashboard.js"), "function buildTriageRow(")
    assert "triageItemNextStep(item)" in row
    assert "triageItemText(item)" in row
    assert row.index("triageItemText(item)") < row.index("triageItemNextStep(item)")


@pytest.mark.unit
def test_writer_supplied_text_reaches_the_dom_as_text() -> None:
    """A collection-failure reason is an API error string out of STATE.json
    and a platform key is registry-controlled. Both are interpolated into
    these rows."""
    row = _function_body(_read("dashboard.js"), "function buildTriageRow(")
    assert ".textContent = triageItemText(item)" in row
    for name in ("reports_triage.js", "dashboard.js"):
        assert ".innerHTML" not in _read(name).replace("// innerHTML", ""), name


@pytest.mark.unit
def test_the_row_styles_can_wrap() -> None:
    """The rows interpolate a free-form reason and a platform-supplied label
    into a flex block, so they need the break treatment every other note in
    this view has."""
    css = _read("app.css")
    for rule in (".reports-triage-row", ".reports-triage-what"):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"


@pytest.mark.unit
def test_the_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_triage_title",
        "dashboard.reports_triage_card_marker",
        "dashboard.reports_triage_double_counted",
        "dashboard.reports_triage_stale",
        "dashboard.reports_triage_stale_undated",
        "dashboard.reports_triage_not_collected",
        "dashboard.reports_triage_unknown_key",
        "dashboard.reports_triage_observation_due",
        "dashboard.reports_triage_next_collect",
        "dashboard.reports_triage_next_not_collected",
        "dashboard.reports_triage_next_observations",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_a_withheld_figure_is_stated_as_withheld_in_both_locales() -> None:
    """The constraint that matters most (#638): mureo does not present a
    number it cannot vouch for, so the layer needs a first-class "we cannot
    say" — never an empty cell that reads as zero or as fine. Both withholding
    kinds must say so in words."""
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_triage_double_counted",
        "dashboard.reports_triage_stale",
        "dashboard.reports_triage_stale_undated",
    ):
        assert "cannot" in data["en"][key], data["en"][key]
        assert "できません" in data["ja"][key], data["ja"][key]


@pytest.mark.unit
def test_every_next_step_names_something_runnable() -> None:
    """#636 was reported because the dashboard said "resolve this" and no
    command existed that could. Each next-step string names a command."""
    data = json.loads(_read("i18n.json"))
    runnable = {
        "dashboard.reports_triage_next_collect": "/sync-state",
        "dashboard.reports_triage_next_not_collected": "/sync-state",
        "dashboard.reports_triage_next_observations": "/daily-check",
    }
    for key, command in runnable.items():
        for loc in ("en", "ja"):
            assert command in data[loc][key], f"{key} ({loc}) names no command"
    # The two conflict kinds reuse the vocabulary the client card already
    # renders rather than forking it: the command's spelling, its dry-run
    # promise and the "only you can say which entry is right" clause are one
    # string in the product, so a change to the command cannot leave a second
    # copy behind saying something else.
    triage = _read("reports_triage.js")
    assert "dashboard.reports_conflict_duplicate_repair_hint" in triage
    assert "dashboard.reports_conflict_repair_hint" in triage
    forked = [
        key
        for key in data["en"]
        if key.startswith("dashboard.reports_triage_")
        and "mureo repair platform-key" in data["en"][key]
    ]
    assert forked == [], f"the repair command is spelled out again in {forked}"
