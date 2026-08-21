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
    js = _read("dashboard_reports.js")
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
    render = _function_body(
        _read("dashboard_reports.js"), "function renderReportsTriage("
    )
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
    js = _read("dashboard_reports.js")
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
    view = _function_body(_read("dashboard_reports.js"), "function setReportsView(")
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
    render = _function_body(
        _read("dashboard_reports.js"), "function renderReportsTriage("
    )
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
    js = _read("dashboard_reports.js")
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
    item = _function_body(
        _read("dashboard_reports.js"), "function buildClientCardItem("
    )
    assert "dashboard.reports_triage_card_marker" in item


# ---------------------------------------------------------------------------
# What reaches the DOM
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_rendered_row_carries_its_next_step() -> None:
    """ "An item with no next step is a bug in the item, not a display
    detail." The renderer asks for one on every row."""
    row = _function_body(_read("dashboard_reports.js"), "function buildTriageRow(")
    assert "triageItemNextStep(item)" in row
    assert "triageItemText(item)" in row
    assert row.index("triageItemText(item)") < row.index("triageItemNextStep(item)")


@pytest.mark.unit
def test_writer_supplied_text_reaches_the_dom_as_text() -> None:
    """A collection-failure reason is an API error string out of STATE.json
    and a platform key is registry-controlled. Both are interpolated into
    these rows."""
    row = _function_body(_read("dashboard_reports.js"), "function buildTriageRow(")
    assert ".textContent = triageItemText(item)" in row
    for name in ("reports_triage.js", "dashboard_reports.js"):
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


# ---------------------------------------------------------------------------
# One row per kind, opened short, and closable without going silent
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_rows_are_grouped_and_collapsed_by_the_module() -> None:
    """A 27-client install rendered sixteen rows, six of them the same
    sentence under six names. Grouping by kind and opening at the top few are
    both decisions — which clients a row covers, and which rows survive the
    collapse — so both live where the JS suite executes them."""
    js = _read("dashboard_reports.js")
    for name in ("groupReportsTriage", "collapseTriageGroups", "partitionTriageGroups"):
        assert f"{name} = REPORTS_TRIAGE.{name}" in js, f"{name} is not bound"
        assert f"function {name}(" not in js, f"{name} was copied into dashboard.js"
    render = _function_body(js, "function renderReportsTriage(")
    assert "groupReportsTriage(built)" in render
    assert "collapseTriageGroups(split.visible, reportsTriageShowAll)" in render


@pytest.mark.unit
def test_neither_grouping_nor_collapsing_nor_hiding_moves_the_count() -> None:
    """The acceptance criterion #651 shipped with, under three new ways to
    show fewer rows. The heading, the KPI cell and the marked cards read
    ``built.clients`` — which none of the three touches."""
    js = _read("dashboard_reports.js")
    render = _function_body(js, "function renderReportsTriage(")
    # The count is taken BEFORE anything is grouped, collapsed or filtered.
    assert render.index("built.clients") < render.index("groupReportsTriage(built)")
    assert "n: marked.length" in render
    index = _function_body(js, "async function renderReportsIndex(")
    assert "triageMarksClient(triage, i)" in index
    assert "triageHealthCounts(triage, rows.length)" in index


@pytest.mark.unit
def test_a_row_is_one_line_and_keeps_its_full_text() -> None:
    """The sentence wrapping to three lines inside a bordered box was most of
    the height an operator complained about. Clipping it is only acceptable
    because the whole text is one click away — and, meanwhile, on a title."""
    js = _read("dashboard_reports.js")
    row = _function_body(js, "function buildTriageRow(")
    assert "reports-triage-summary" in row
    assert "summary.title = summary.textContent" in row
    css = _read("app.css")
    block = css.split(".reports-triage-summary {", 1)[1].split("}", 1)[0]
    assert "text-overflow: ellipsis" in block
    assert "white-space: nowrap" in block
    toggle = css.split(".reports-triage-toggle {", 1)[1].split("}", 1)[0]
    assert "flex-wrap: nowrap" in toggle
    # The expanded per-client lines still wrap — that is where the full text
    # of every item on the row is.
    detail = css.split(".reports-triage-detail-row {", 1)[1].split("}", 1)[0]
    assert "overflow-wrap" in detail


@pytest.mark.unit
def test_the_rest_of_the_list_is_one_click_away_and_never_zero() -> None:
    """No "show all (0)" on a list that already fits, for the same reason
    there is no "0 alerts" banner."""
    js = _read("dashboard_reports.js")
    more = _function_body(js, "function renderTriageMore(")
    assert "more.hidden = !shown.collapsed" in more
    assert "if (!shown.collapsed) return;" in more
    assert "dashboard.reports_triage_show_all" in more
    # It opens short again on every arrival — the state is not remembered.
    index = _function_body(js, "async function renderReportsIndex(")
    assert "reportsTriageShowAll = false" in index


@pytest.mark.unit
def test_closing_an_alert_is_never_silent() -> None:
    """The one thing the ✕ may not do. Hiding does not resolve the condition
    behind it, and a finding that left NO trace when it was closed is the
    failure mode this whole layer was built against (#636, #638). So while
    anything is hidden: the count is on screen, the words say hiding resolved
    nothing, and one button brings them all back.

    The count is of MESSAGES. The rows group by kind and one can cover six
    clients, so counting rows would report "1" for six findings nobody can
    see — see ``tests/js/reports_dismiss_interaction.test.js``, which closes
    them one at a time and reads the line."""
    js = _read("dashboard_reports.js")
    row = _function_body(js, "function buildTriageRow(")
    assert "dismissTriageItem(item)" in row, "a message has no control of its own"
    assert "dismissTriageGroup(group)" in row
    assert "reports-triage-dismiss" in row
    hidden = _function_body(js, "function renderTriageDismissed(")
    assert "box.hidden = !hiddenCount" in hidden
    assert "dashboard.reports_triage_hidden_title" in hidden
    assert "dashboard.reports_triage_hidden_note" in hidden
    assert "restoreTriageDismissals()" in hidden
    html = _read("app.html")
    assert "data-reports-triage-hidden" in html


@pytest.mark.unit
def test_the_hidden_note_says_the_condition_is_still_true() -> None:
    """In words, in both locales. "It is hidden" and "it is fixed" must not
    be possible to confuse."""
    data = json.loads(_read("i18n.json"))
    note = "dashboard.reports_triage_hidden_note"
    assert "not resolve" in data["en"][note], data["en"][note]
    assert "解決していません" in data["ja"][note], data["ja"][note]
    for key in (
        "dashboard.reports_triage_show_all",
        "dashboard.reports_triage_hidden_title",
        "dashboard.reports_triage_hidden_note",
        "dashboard.reports_triage_restore",
        "dashboard.reports_triage_dismiss",
        "dashboard.reports_triage_dismiss_group",
        "dashboard.reports_triage_client_separator",
        "dashboard.reports_triage_tag_stale_aged",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_a_dismissal_is_keyed_to_what_the_message_said() -> None:
    """Hiding must not outlive the message's content: a stale figure that has
    aged another eighteen days is a different, worse fact and comes back on
    its own. ``tests/js/reports_triage.test.js`` executes the fingerprint;
    this pins that it is a fingerprint of ONE MESSAGE and not of a kind.

    Per message, because the rows group by kind: closing "unknown key" as a
    category would take five findings the operator never read with it."""
    triage = _read("reports_triage.js")
    assert "function triageItemFingerprint(" in triage
    assert "function triageItemKey(" in triage
    assert "function triageGroupKey(" not in triage, "dismissal is per row again"
    body = _function_body(triage, "function triageItemKey(")
    assert "triageItemFingerprint(row)" in body
    # The row-level control is the message-level one applied to each message,
    # so the two cannot mean different things.
    group = _function_body(triage, "function dismissTriageGroup(")
    assert "items.forEach(dismissTriageItem)" in group
    # Storage that cannot be read hides NOTHING — the other direction would
    # silence the layer on a browser with storage disabled.
    read = _function_body(triage, "function readDismissedTriage(")
    assert "return [];" in read
