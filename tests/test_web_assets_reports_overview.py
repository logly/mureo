"""Static-content guards for the Reports index as an account overview.

**Read this with ``tests/js/reports_overview.test.js``.** The DECISIONS —
what the roster's figures are, over how many clients each was stated, and
how the spend splits by platform — live in
``mureo/_data/web/reports_overview.js`` and are *executed* by
``node --test tests/js/*.test.js``. The RENDERING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

What is pinned, and why each one is the thing that would break:

- a cross-client figure is the easiest place in the product to hide a
  number mureo cannot vouch for (#636, #638): a client whose totals are
  withheld would contribute a silent zero. So the strip renders "—" plus
  the reason, never a bare dash and never a 0, and it carries the coverage;
- the strip, the filter and the platform panel are the multi-client index's,
  and a single-workspace install must be untouched by all three;
- the grid's health filter reads the TRIAGE layer's findings, so a card the
  alert list calls urgent cannot be filtered away as a healthy one;
- a client's health reaches the card as a tag as well as a colour;
- writer- and registry-supplied text (a platform display name) reaches the
  DOM as text, never as markup.

Same limits as every static guard here: these catch a deleted name, a
flipped condition or a string that moved branch. They cannot prove a card
rendered at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_WEB = _ROOT / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


#: The Reports rendering layer, split three ways by #687. A test that asserts
#: about symbols on both sides of that split reads the whole layer rather than
#: guessing which file a given renderer ended up in.
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


# ---------------------------------------------------------------------------
# The renderer does not re-decide anything
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_renderer_binds_the_module_rather_than_re_deciding() -> None:
    """Summing other clients' money and deciding whose may be summed at all
    are decisions the JS suite executes. A renderer that re-derived either
    would drift from the module, and a substring pin cannot catch an
    inverted comparison."""
    js = _read("dashboard_reports_state.js")
    for name in ("buildReportsPortfolio", "clientPlatformSplit", "platformColorSlot"):
        assert f"{name} = REPORTS_OVERVIEW.{name}" in js, f"{name} is not bound"
        assert f"function {name}(" not in js, f"{name} was copied into dashboard.js"


@pytest.mark.unit
def test_the_portfolio_is_built_once_from_the_cards_own_summaries() -> None:
    """The strip and the grid must be two views of ONE fetch. Built twice —
    or from a second request — they could state different windows."""
    model = _read("reports_index.js")
    assert (
        model.count("buildReportsPortfolio(") == 1
    ), "the portfolio is built in >1 place"
    assert "buildReportsPortfolio(clients, bodies)" in model
    assert "buildReportsTriage(clients, bodies)" in model
    # …and the renderer builds neither: the model is composed once, from the
    # rows and the summaries the grid is drawn from, before a node exists.
    js = _read("dashboard_reports.js")
    assert "buildReportsPortfolio(" not in js
    assert "buildReportsTriage(" not in js
    index = _function_body(js, "async function renderReportsIndex(")
    assert "buildReportsIndexModel(rows, summaries)" in index


# ---------------------------------------------------------------------------
# A figure mureo cannot state (#638)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_an_unstated_total_is_a_dash_with_a_reason_never_a_zero() -> None:
    """The constraint the whole view is built on. A roster total is where a
    withheld client would otherwise be summed in as nothing."""
    cell = _function_body(
        _read("dashboard_reports_overview.js"), "function buildPortfolioFigureCell("
    )
    assert 'value != null ? format(value) : "—"' in cell
    assert "dashboard.reports_portfolio_unstated" in cell
    # …and a figure that IS stated says over how many clients, whenever that
    # is not all of them.
    assert "stated < total" in cell
    assert "dashboard.reports_portfolio_coverage" in cell


@pytest.mark.unit
def test_an_empty_roster_gets_no_strip_rather_than_four_dashes() -> None:
    render = _function_body(
        _read("dashboard_reports_overview.js"), "function renderReportsPortfolio("
    )
    assert "strip.hidden = !portfolio.total" in render
    assert "if (!portfolio.total) return;" in render
    # Cleared before the early return, so a row from a previous render cannot
    # survive one that found nothing.
    assert render.index('strip.textContent = ""') < render.index(
        "strip.hidden = !portfolio.total"
    )


@pytest.mark.unit
def test_the_platform_panel_is_hidden_rather_than_drawn_empty() -> None:
    """A panel of zero-width bars says nothing; a panel of bars drawn from
    withheld figures says something false. The module returns no split in
    either case, and the panel follows it."""
    render = _function_body(
        _read("dashboard_reports_overview.js"), "function renderReportsPlatforms("
    )
    assert "panel.hidden = !portfolio.platforms.length" in render
    assert "if (panel.hidden) return;" in render
    assert (
        "dashboard.reports_portfolio_coverage" in render
    ), "the panel states no coverage"


# ---------------------------------------------------------------------------
# Index only — a single-workspace install is untouched
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_only_the_multi_client_index_renders_the_overview() -> None:
    """The Agency seam is what supplies a second client. A single workspace
    opens the detail directly and must never see a roster figure."""
    js = _read_layer()
    # The index render, in the three functions #715 split it into: the entry
    # point, the bands above and beside the grid, and the grid itself.
    drawn = "\n".join(
        _function_body(js, signature)
        for signature in (
            "async function renderReportsIndex(",
            "function renderReportsIndexBands(",
            "function renderReportsIndexGrid(",
        )
    )
    for call in (
        "renderReportsPortfolio(",
        "renderReportsPlatforms(",
        "renderReportsFilters(",
        "renderReportsActionFeed(",
    ):
        assert js.count(call) == 2, f"{call} is called from more than the index"
        assert call in drawn, f"{call} is not the index's"
    detail = _function_body(js, "async function renderReportsSummary(")
    assert "Portfolio" not in detail, "the single-client view renders the strip"
    assert "Platforms" not in detail
    assert "ActionFeed" not in detail


@pytest.mark.unit
def test_leaving_the_index_hides_the_overview() -> None:
    """The strip states figures ABOUT the grid. Left behind over a detail
    view, a roster total reads as that one client's."""
    view = _function_body(_read("dashboard_reports.js"), "function setReportsView(")
    for target in ("data-reports-kpis", "data-reports-index-grid", "data-reports-feed"):
        assert target in view, f"{target} survives a view change"
    assert 'view !== "index"' in view
    # Hidden in the markup too, so a page that never reaches the index shows
    # nothing either.
    html = _read("app.html")
    for target in (
        "data-reports-kpis",
        "data-reports-index-grid",
        "data-reports-filters",
    ):
        block = html.split(target, 1)[1].split(">", 1)[0]
        assert "hidden" in block, f"{target} is not hidden by default"


@pytest.mark.unit
def test_the_overview_sits_above_and_beside_the_grid_it_describes() -> None:
    html = _read("app.html")
    # The grid itself, not the count badge that shares its prefix.
    grid = html.index('class="dashboard-reports-clients"')
    assert html.index("data-reports-kpis") < html.index("data-reports-index-grid")
    assert html.index("data-reports-index-grid") < html.index("data-reports-triage")
    assert html.index("data-reports-triage") < grid
    assert html.index("data-reports-filters") < grid
    assert grid < html.index("data-reports-platforms")


# ---------------------------------------------------------------------------
# The health filter is the triage layer's own verdict
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_grid_filters_on_the_triage_layers_health() -> None:
    """A second opinion about the same payload is how a card the alert list
    calls urgent ends up filtered away as a healthy one."""
    js = _read_layer()
    # The verdict is reached once per client per render (#715) and every card
    # is painted from that array — never from a second reading of the payload.
    model = _read("reports_index.js")
    assert "triageClientHealth(built, i)" in model
    assert "triageHealthCounts(built, clients.length, healthByIndex)" in model
    grid = _function_body(js, "function renderReportsIndexGrid(")
    assert "model.healthByIndex[i]" in grid
    item = _function_body(js, "function buildClientCardItem(")
    assert 'item.setAttribute("data-health"' in item


@pytest.mark.unit
def test_filtering_hides_cards_rather_than_rebuilding_the_grid() -> None:
    """The grid is also the operator's own card order (#556). Rebuilding it
    from a filtered list would reorder it."""
    apply_fn = _function_body(
        _read("dashboard_reports_overview.js"), "function applyReportsHealthFilter("
    )
    assert "item.hidden =" in apply_fn
    assert 'textContent = ""' not in apply_fn
    assert "removeChild" not in apply_fn


@pytest.mark.unit
def test_a_filter_never_survives_a_re_render() -> None:
    """Cards missing with no visible reason is worse than no filter at all."""
    grid = _function_body(
        _read("dashboard_reports.js"), "function renderReportsIndexGrid("
    )
    assert 'reportsHealthFilter = "all"' in grid


@pytest.mark.unit
def test_a_cards_health_is_announced_and_not_only_coloured() -> None:
    """Colour alone is not a status. The grid is a list of buttons an
    operator may reach by keyboard."""
    card = _function_body(
        _read("dashboard_reports_cards.js"), "function buildClientCard("
    )
    assert '"reports-client-card is-health-"' in card
    assert 'MUREO.t("dashboard.reports_health_"' in card


# ---------------------------------------------------------------------------
# What reaches the DOM
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_platform_names_reach_the_dom_as_text() -> None:
    """A platform display name is registry- and plugin-controlled."""
    js = _read("dashboard_reports_overview.js")
    panel = _function_body(js, "function renderReportsPlatforms(")
    assert "name.textContent = row.label" in panel
    for name in (
        "reports_overview.js",
        "dashboard_reports_overview.js",
        "dashboard_reports_overview.js",
        "dashboard_reports_overview.js",
    ):
        assert ".innerHTML" not in _read(name).replace("// innerHTML", ""), name


@pytest.mark.unit
def test_a_platforms_colour_follows_its_key_and_the_stylesheet_has_the_slots() -> None:
    """The split is ranked by spend, so a colour taken from the row's
    position would change from card to card and leave the legend as the only
    way to read the bar."""
    js = _read("dashboard_reports_overview.js")
    slice_fn = _function_body(js, "function buildPlatformSlice(")
    assert "platformColorSlot(row.key)" in slice_fn
    css = _read("app.css")
    overview = _read("reports_overview.js")
    slots = int(
        overview.split("REPORTS_PLATFORM_COLOR_SLOTS = ", 1)[1].split(";", 1)[0]
    )
    for i in range(slots):
        assert f".is-platform-{i} {{" in css, f"the palette has no slot {i}"


@pytest.mark.unit
def test_the_new_rows_can_wrap() -> None:
    """These rows interpolate a platform-supplied label into a flex block, so
    they need the break treatment every other note in this view has."""
    css = _read("app.css")
    for rule in (
        ".reports-platform-name",
        ".reports-client-split-entry",
        ".reports-client-card-badge",
    ):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"


@pytest.mark.unit
def test_the_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_clients_title",
        "dashboard.reports_clients_count",
        "dashboard.reports_filter_all",
        "dashboard.reports_health_attention",
        "dashboard.reports_health_watch",
        "dashboard.reports_health_ok",
        "dashboard.reports_platform_split_title",
        "dashboard.reports_portfolio_attention",
        "dashboard.reports_portfolio_coverage",
        "dashboard.reports_portfolio_health_note",
        "dashboard.reports_portfolio_unstated",
        "dashboard.reports_triage_count",
        "dashboard.reports_triage_tag_double_counted",
        "dashboard.reports_triage_tag_not_collected",
        "dashboard.reports_triage_tag_observation_due",
        "dashboard.reports_triage_tag_stale",
        "dashboard.reports_triage_tag_unknown_key",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_the_unstated_string_says_mureo_cannot_state_it() -> None:
    """#638 again: "we cannot say" is a first-class thing the operator reads,
    never an empty cell that reads as zero, or as fine."""
    data = json.loads(_read("i18n.json"))
    key = "dashboard.reports_portfolio_unstated"
    assert "cannot" in data["en"][key], data["en"][key]
    assert "できません" in data["ja"][key], data["ja"][key]


# ---------------------------------------------------------------------------
# Height: the index has to fit on a screen an operator can read
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_index_body_is_two_columns_with_a_rail() -> None:
    """Stacking every section full width made the index two screens tall
    before the operator had read anything. The alerts and the grid they
    triage share the main column; where the money went is a rail beside
    them, and the whole thing stacks again on a narrow screen."""
    html = _read("app.html")
    css = _read("app.css")
    # The alerts live INSIDE the main column now, still above the grid.
    main = html.index('class="reports-index-main"')
    assert main < html.index("data-reports-triage")
    assert html.index("data-reports-triage") < html.index(
        'class="dashboard-reports-clients"'
    )
    # …and the platform panel is outside it, in the rail.
    assert html.index("data-reports-platforms") > html.index(
        'class="dashboard-reports-clients"'
    )
    grid = css.split(".reports-index-grid {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: minmax(0, 1fr) 340px" in grid
    assert "@media (max-width: 960px)" in css


@pytest.mark.unit
def test_a_kpi_note_is_one_clipped_line_that_keeps_its_full_text() -> None:
    """Four cells each wrapping a sentence is a strip taller than the alerts
    under it. The note is clipped — and the whole sentence stays reachable,
    because it is the half of the figure that says whose numbers are in it.
    Shortened, never dropped."""
    css = _read("app.css")
    block = css.split(".reports-kpi-note {", 1)[1].split("}", 1)[0]
    assert "text-overflow: ellipsis" in block
    assert "white-space: nowrap" in block
    # Reserved even when empty, so the four cells stay one height.
    assert "min-height" in block
    js = _read("dashboard_reports_overview.js")
    cell = _function_body(js, "function buildPortfolioCell(")
    assert "cell.title = full" in cell
    figure = _function_body(js, "function buildPortfolioFigureCell(")
    for key in (
        "dashboard.reports_portfolio_unstated_short",
        "dashboard.reports_portfolio_unstated",
        "dashboard.reports_portfolio_coverage_short",
        "dashboard.reports_portfolio_coverage",
    ):
        assert key in figure, f"{key} is not offered by the cell"


@pytest.mark.unit
def test_the_short_and_long_coverage_strings_are_localized() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_portfolio_coverage_short",
        "dashboard.reports_portfolio_unstated_short",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"
    # The short form still says mureo CANNOT state it — an empty cell that
    # reads as zero is the one thing this view must never produce (#638).
    assert "cannot" in data["en"]["dashboard.reports_portfolio_unstated_short"]
    assert "できません" in data["ja"]["dashboard.reports_portfolio_unstated_short"]


# ---------------------------------------------------------------------------
# What mureo did today
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_feed_costs_no_request_and_is_built_once() -> None:
    """Every client's ``recent_actions`` is already on the wire — the index
    fetches all of them in parallel to draw the cards. A feed that re-asked
    would scale a second round of requests with the roster, on the screen
    a twenty-seven-client operator opens."""
    js = _read_layer()
    assert js.count("buildReportsActionFeed(") == 1
    bands = _function_body(js, "function renderReportsIndexBands(")
    assert "buildReportsActionFeed(rows, summaries)" in bands
    feed = _function_body(js, "function renderReportsActionFeed(")
    assert "fetch(" not in feed


@pytest.mark.unit
def test_the_browser_never_decides_what_today_is() -> None:
    """An action-log ``timestamp`` is stamped server-side from ``server_now``
    — the HOST's local wall clock. A browser drawing the day boundary with
    its own clock lists nine hours of yesterday's work as today's for an
    operator outside the host's timezone.

    So: the date comes from the summary's ``server_today``, the comparison is
    between two strings out of that one clock, and this module never asks the
    browser what time it is. ``tests/js/reports_overview.test.js`` executes
    the boundary; the pin below is that there is no second opinion to
    execute."""
    overview = _read("reports_overview.js")
    assert "server_today" in overview
    # Comments are stripped first: the module explains at length why it does
    # NOT call `new Date(ts)`, and the explanation must not read as the call.
    code = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/", "", overview)
    assert "new Date(" not in code, "the feed constructs a browser Date"
    assert "Date.now(" not in code, "the feed reads the browser's clock"
    js = _read_layer()
    for name in ("renderReportsActionFeed", "buildReportsFeedRow"):
        body = _function_body(js, f"function {name}(")
        assert "Date" not in body, f"{name} decides a date of its own"
    assert "buildReportsActionFeed = REPORTS_OVERVIEW.buildReportsActionFeed" in js
    assert "function buildReportsActionFeed(" not in js


@pytest.mark.unit
def test_a_quiet_day_says_so_on_a_roster_and_is_absent_below_one() -> None:
    """On a ROSTER the rail stays and says the day is quiet in one line
    (#706 step 3-b); below two clients the panel is absent as before.

    The asymmetry is the point. On a roster the rail is where an operator
    looks to see mureo working, and an absent panel and a quiet day are
    indistinguishable — "did nothing happen, or is this broken?" is the
    question the line answers, and one line costs the platform split under it
    nothing. A single-client index is not a roster, and there the default is
    the same silence the alert layer keeps.
    """
    feed = _function_body(
        _read("dashboard_reports_overview.js"), "function renderReportsActionFeed("
    )
    assert "panel.hidden = !feed.items.length && !rostered" in feed
    assert "if (empty) empty.hidden = !!feed.items.length;" in feed
    # Cleared before the early return, so yesterday's rows cannot survive a
    # render that found nothing.
    assert feed.index('list.textContent = ""') < feed.index("panel.hidden =")
    html = _read("app.html")
    block = html.split("data-reports-feed", 1)[1].split(">", 1)[0]
    assert "hidden" in block
    # The empty line is a node of its own, hidden by default, with its own
    # `[hidden]` rule — anything hidden that way needs one (#712).
    assert "data-reports-feed-empty" in html
    assert "dashboard.reports_feed_empty" in html
    assert ".reports-feed-empty[hidden]" in _read("app.css")


@pytest.mark.unit
def test_the_feed_is_capped_and_says_how_many_it_held_back() -> None:
    """A rail is a glance at the day, not the log. What it does not show it
    counts — the alternative is an operator believing six actions were all of
    them."""
    overview = _read("reports_overview.js")
    assert "REPORTS_ACTION_FEED_CAP" in overview
    feed = _function_body(
        _read("dashboard_reports_overview.js"), "function renderReportsActionFeed("
    )
    assert "dashboard.reports_feed_more" in feed
    assert "feed.remaining" in feed
    assert "dashboard.reports_feed_count" in feed


@pytest.mark.unit
def test_the_feed_sits_above_the_platform_split_in_the_rail() -> None:
    html = _read("app.html")
    assert html.index("data-reports-feed") < html.index("data-reports-platforms")
    # …and both are in the rail, beside the grid rather than under it.
    rail = html.index('class="reports-index-rail"')
    assert rail > html.index('class="dashboard-reports-clients"')
    assert rail < html.index("data-reports-feed")


@pytest.mark.unit
def test_the_action_text_and_client_name_reach_the_dom_as_text() -> None:
    """An action ``summary`` is writer-supplied text out of STATE.json and a
    client name is registry-controlled."""
    row = _function_body(
        _read("dashboard_reports_overview.js"), "function buildReportsFeedRow("
    )
    assert "who.textContent = item.name" in row
    assert "what.textContent = item.text" in row
    assert ".innerHTML" not in row


@pytest.mark.unit
def test_the_feed_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_feed_title",
        "dashboard.reports_feed_count",
        "dashboard.reports_feed_more",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_a_feed_row_is_clamped_to_two_lines_and_keeps_its_full_text() -> None:
    """An action-log ``summary`` is free-form text a skill wrote, and real
    ones run to several hundred characters — one of them turned this rail
    into a wall of prose, which is the failure the index redesign exists to
    end.

    A clamp is not a truncated record: the string is unaltered, the whole of
    it is on the element's ``title``, and the action log is rendered in full
    on the client's own detail view. The rule about never truncating silently
    (#659) is about a stored VALUE mureo would be altering; how many lines of
    an unchanged string a 340px rail shows is a display decision — the same
    one the alert rows above already make at one line.
    """
    css = _read("app.css")
    block = css.split(".reports-feed-body {", 1)[1].split("}", 1)[0]
    assert "-webkit-line-clamp: 2" in block, "the feed body is not clamped"
    assert "line-clamp: 2" in block
    assert "overflow: hidden" in block
    assert "-webkit-box" in block, "line-clamp needs the box display to apply"
    # The name flows INTO the clamped box rather than taking one of its two
    # lines for itself.
    name = css.split(".reports-feed-client {", 1)[1].split("}", 1)[0]
    assert "display: inline" in name
    # …and the whole sentence is one hover away.
    row = _function_body(
        _read("dashboard_reports_overview.js"), "function buildReportsFeedRow("
    )
    # `item.text` is the line that fits the rail; `item.full` is the line as
    # it was written, which is what the hover has to carry (#706 step 3-b —
    # a legacy summary is cut at 120 characters for the row itself).
    assert "body.title = item.full || item.text" in row


@pytest.mark.unit
def test_the_feed_rows_can_wrap() -> None:
    """An action summary is a free-form sentence in a 340px rail."""
    css = _read("app.css")
    for rule in (".reports-feed-body", ".reports-feed-text"):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"
