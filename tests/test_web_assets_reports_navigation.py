"""Static-content guards for the Reports section's view routing.

**Read this with ``tests/js/reports_overview.test.js``.** The DECISION —
which view the section shows, from why the render happened — lives in
``mureo/_data/web/reports_overview.js`` and is *executed* by
``node --test tests/js/*.test.js``. The WIRING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

The bug this pins shut: an operator opened a client's report, clicked
"Reports" in the left menu, and landed back on that same client. The menu
was the only global way back to the list, so the list had no way back at
all.

What is pinned, and why each one is the thing that would break:

- the menu item is the ONLY caller that forces the index. If a re-render
  forced it too, a period switch or a status poll would eject an operator
  from the report they are reading — the same bug pointing the other way;
- the renderer does not re-decide the routing, so an inverted condition
  cannot appear in a file no test runner executes;
- the module ships and is loaded ahead of ``dashboard.js``.

Same limits as every static guard here: these catch a deleted name, a
flipped condition or a call that moved. They cannot prove a click routed.
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
def test_the_module_is_served_and_loaded_before_the_dashboard() -> None:
    """It publishes one global that ``dashboard.js`` binds at load, so it has
    to be in the allow-list AND ahead of ``dashboard.js`` in the page."""
    from mureo.web.handlers import _STATIC_ALLOWLIST

    assert "reports_overview.js" in _STATIC_ALLOWLIST
    html = _read("app.html")
    assert html.index("/static/reports_overview.js") < html.index(
        "/static/dashboard.js"
    )


@pytest.mark.unit
def test_the_renderer_binds_the_routing_rather_than_re_deciding_it() -> None:
    """Which view to show is a decision the JS suite executes. A renderer
    that re-derived it would drift from the module, and a substring pin
    cannot catch an inverted comparison."""
    js = _read("dashboard_reports.js")
    assert "reportsViewToShow = REPORTS_OVERVIEW.reportsViewToShow" in js
    assert "function reportsViewToShow(" not in js


@pytest.mark.unit
def test_the_menu_asks_for_the_index_and_nothing_else_does() -> None:
    """The left-nav handler is the ONE place that says "the operator asked
    for the section". Every other caller is a redraw, and a redraw that
    forced the index would eject a reader from the report they are on."""
    js = _read("dashboard.js")
    nav = _function_body(js, "function selectNavGroup(")
    assert 'if (name === "reports") enterReportsSection();' in nav
    reports_js = _read("dashboard_reports.js")
    entry = _function_body(reports_js, "function enterReportsSection(")
    assert "REPORTS_OVERVIEW.REPORTS_ENTRY_MENU" in entry
    # Exactly one caller passes the menu token: the entry point above.
    assert reports_js.count("REPORTS_ENTRY_MENU") == 1


@pytest.mark.unit
def test_a_re_render_states_no_entry_and_so_keeps_the_view() -> None:
    """The period toggle, the status refresh and the archive round-trip all
    re-enter ``renderReports``. None of them may pass an entry token — the
    module reads "not the menu" as "redraw what is on screen"."""
    js = _read("dashboard_reports.js")
    # renderReports() is called with no argument everywhere except the menu
    # entry point, which passes the token through its own function.
    assert "renderReports()" in js
    assert "renderReports(REPORTS_OVERVIEW.REPORTS_ENTRY_MENU)" in js
    for bad in ('renderReports("index")', 'renderReports("detail")'):
        assert bad not in js, f"{bad} routes by view rather than by entry"


@pytest.mark.unit
def test_the_routing_reads_the_whole_registry_including_archived_rows() -> None:
    """A registry that has ever held more than one client keeps its index —
    the index is the only place an archived client can be restored from, so
    counting only the visible ones would trap an operator who archived down
    to one."""
    body = _function_body(
        _read("dashboard_reports.js"), "async function renderReports("
    )
    assert "archivedReportsClients().length > 0" in body
    assert "hasIndex: hasIndex" in body
