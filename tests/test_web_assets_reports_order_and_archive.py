"""Static-content guards for the Reports index reorder + archive controls.

There is still no JS build step, and the runner added in #540
(``node --test tests/js/``) covers only the DOM-free Reports logic that was
extracted into ``reports_logic.js``. The ordering and archive helpers below
touch ``localStorage`` and the grid DOM and were NOT extracted, so — like
``test_web_assets_reports_conflicts.py`` — these read the bundled assets in
``mureo/_data/web/`` and pin the *shape* of what ships: that the
identifiers, i18n keys, DOM hooks and CSS rules the feature depends on are
present, in both locales, and that nothing here reintroduces ``innerHTML``.

Two of them go past presence and read *structure*: the routing condition
must mention the archived clients, and the archive click handler's source
must confirm-then-return-then-POST in that order. Both would otherwise pass
against an implementation that had regressed to the obvious wrong thing.

**What they do NOT cover.** They execute no JavaScript. They cannot prove
that a drag actually reorders the grid, that a corrupt stored order really
degrades to the server order, that `await` genuinely suspends before the
POST, or that the routing branch is reached with the state it is written
for. Reading source order is not the same as observing behaviour: a
handler could satisfy the ordering pin and still, say, ignore the confirm's
resolved value. Those behaviours are argued in the code comments and were
verified by hand (plus, for the ordering rules, by running the extracted
helpers under node); treat these as anti-regression pins on the contract's
surface, not as behavioural tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _function_body(js: str, signature: str) -> str:
    """Source of the top-level function opened by ``signature``.

    Top-level helpers in dashboard.js sit at two-space indent, so the first
    ``\\n  }`` after the signature closes them; nested blocks close deeper.
    """
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


# ---------------------------------------------------------------------------
# Ordering — per-operator, browser-local, degrades to the server order
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_card_order_is_stored_per_operator_in_the_browser() -> None:
    """The order is purely visual: losing it breaks nothing and two operators
    reasonably want different ones, so it is localStorage — never server
    state that one operator's arrangement would impose on everyone."""
    js = _read("dashboard.js")
    assert "mureo.reports.client_order" in js
    assert "localStorage" in js
    assert "function readReportsOrder(" in js
    assert "function writeReportsOrder(" in js


@pytest.mark.unit
def test_a_stored_order_is_reconciled_rather_than_trusted() -> None:
    """A stored order naming clients that no longer exist, missing clients
    that now do, or corrupt JSON must all render a sane grid — the ordering
    helper filters and merges instead of indexing blindly."""
    js = _read("dashboard.js")
    assert "function orderReportsClients(" in js
    # Corrupt JSON / storage-disabled path: readReportsOrder swallows and
    # returns [] so the grid falls back to the server's order.
    body = js.split("function readReportsOrder(", 1)[1].split("\n  }", 1)[0]
    assert "JSON.parse" in body
    assert "catch" in body
    assert "Array.isArray" in body


@pytest.mark.unit
def test_reordering_persists_from_the_dom_not_from_a_shadow_list() -> None:
    """One source of truth for the new order — the grid itself — so the
    keyboard path and the drop handler can never disagree."""
    js = _read("dashboard.js")
    assert "function persistReportsOrderFromDom(" in js
    assert "function moveReportsCard(" in js


@pytest.mark.unit
def test_drag_and_drop_has_a_keyboard_equivalent() -> None:
    """A control only a mouse can work excludes operators who do not use
    one. The drag handle is a real button that moves the card with the arrow
    keys, and both paths go through moveReportsCard."""
    js = _read("dashboard.js")
    assert "dragstart" in js
    assert "dragover" in js
    assert "drop" in js
    assert "keydown" in js
    assert "ArrowUp" in js
    assert "ArrowDown" in js
    assert "dashboard.reports_reorder_handle" in js


# ---------------------------------------------------------------------------
# Archiving — server-side, capability-gated, reversible from this screen
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_archive_control_is_gated_on_the_backend_capability() -> None:
    """An OSS-only single-workspace install has no client registry to record
    the decision in, so the control is not rendered AT ALL there — not
    rendered-and-disabled, and never a browser-local flag that could not
    reach the digest process."""
    js = _read("dashboard.js")
    assert "can_archive" in js
    assert "reportsCanArchive" in js


@pytest.mark.unit
def test_archiving_posts_to_the_server_seam() -> None:
    js = _read("dashboard.js")
    assert "/api/reports/clients/archive" in js
    assert "function setReportsClientArchived(" in js
    assert "dashboard.reports_archive_failed" in js


@pytest.mark.unit
def test_the_archive_click_handler_confirms_before_it_posts() -> None:
    """Structure, not presence: inside the archive button's own handler the
    confirmation must come first, the negative branch must return, and only
    then may the client be archived. A handler that fired the request and
    confirmed afterwards — or that confirmed and ignored the answer — would
    satisfy a "these identifiers appear in the file" check."""
    js = _read("dashboard.js")
    handler = _function_body(js, "function buildReportsArchiveButton(")
    confirm_at = handler.find("MUREO.confirmAction(")
    bail_at = handler.find("if (!ok) return;")
    archive_at = handler.find("setReportsClientArchived(")
    assert confirm_at != -1, "the archive handler does not confirm at all"
    assert bail_at != -1, "the archive handler does not bail on a refusal"
    assert archive_at != -1, "the archive handler never archives"
    assert confirm_at < bail_at < archive_at, (
        "confirm → bail-on-no → archive is the required order; got "
        f"confirm@{confirm_at} bail@{bail_at} archive@{archive_at}"
    )
    # The confirmation is awaited, so the branch below reads a resolved
    # answer rather than a pending Promise (always truthy).
    assert "await MUREO.confirmAction(" in handler
    # And the request itself lives behind that one helper — the handler
    # cannot reach the endpoint by another path.
    assert "/api/reports/clients/archive" not in handler
    assert js.count("/api/reports/clients/archive") == 1


@pytest.mark.unit
def test_the_confirm_states_the_real_consequence() -> None:
    """Not "hide from this view": while archived, that client's figures are
    never collected, and un-archiving does not backfill the gap. The confirm
    string has to say so in both locales."""
    js = _read("dashboard.js")
    assert "dashboard.reports_archive_confirm" in js
    data = json.loads(_read("i18n.json"))
    en = data["en"]["dashboard.reports_archive_confirm"]
    assert "backfill" in en.lower()
    assert "hide" not in en.lower()
    ja = data["ja"]["dashboard.reports_archive_confirm"]
    assert "補完" in ja


@pytest.mark.unit
def test_un_archiving_is_reachable_from_this_screen() -> None:
    """If the only way back is hand-editing the client registry, the feature
    is a trap. A disclosure listing the archived clients, each with a restore
    control, is enough — it does not have to be prominent."""
    js = _read("dashboard.js")
    html = _read("app.html")
    assert "data-reports-archived" in html
    assert "data-reports-archived-list" in html
    assert "<details" in html
    assert "dashboard.reports_archive_restore" in js
    assert "dashboard.reports_archived_title" in js


@pytest.mark.unit
def test_archived_clients_are_off_the_index_but_still_count_for_routing() -> None:
    """Archiving down to one visible client must NOT drop the operator into
    that client's detail view: the index is the only place an archived client
    can be restored from, so the routing decision counts the whole registry.

    Pinned on the condition itself, not on the helpers' existence — the
    regression to guard against is a routing test written against the
    *visible* count, which would still see both helpers defined."""
    js = _read("dashboard.js")
    assert "function visibleReportsClients(" in js
    assert "function archivedReportsClients(" in js
    assert "dashboard.reports_all_archived" in js

    routing = _function_body(js, "async function renderReports(")
    # The single-client shortcut: the condition that skips the index.
    assert "if (reportsClients.length" in routing, "routing condition missing"
    condition = routing.split("if (reportsClients.length", 1)[1].split(") {", 1)[0]
    assert "archivedReportsClients()" in condition, (
        "the detail-vs-index decision ignores archived clients: " + condition
    )
    # …and it is indeed the branch that skips the index.
    branch = routing.split("if (reportsClients.length", 1)[1].split("}", 1)[0]
    assert "showReportsClientDetail(" in branch

    # An archived client is not a live selection either, so archiving the one
    # on screen returns to the index rather than staying on its detail view.
    selection = routing.split("const selectionAlive =", 1)[1].split(";", 1)[0]
    assert "visibleReportsClients()" in selection, (
        "an archived client still counts as a live selection: " + selection
    )

    # The grid renders the visible clients, in the operator's order.
    index = _function_body(js, "async function renderReportsIndex(")
    rows = index.split("const rows =", 1)[1].split(";", 1)[0]
    assert "visibleReportsClients()" in rows
    assert "orderReportsClients(" in rows


# ---------------------------------------------------------------------------
# Localization + safety
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_order_and_archive_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_reorder_handle",
        "dashboard.reports_reorder_hint",
        "dashboard.reports_archive_action",
        "dashboard.reports_archive_label",
        "dashboard.reports_archive_confirm",
        "dashboard.reports_archive_failed",
        "dashboard.reports_archive_restore",
        "dashboard.reports_archive_restore_label",
        "dashboard.reports_archived_title",
        "dashboard.reports_archived_hint",
        "dashboard.reports_all_archived",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_client_names_still_reach_the_dom_via_text_content() -> None:
    """Client names come from the Agency registry, which mureo does not
    control. The archived list renders them like every other untrusted
    string — nothing in the file ever ASSIGNS innerHTML (#533)."""
    js = _read("dashboard.js")
    assert ".innerHTML =" not in js
    assert ".innerHTML=" not in js


@pytest.mark.unit
def test_the_new_controls_are_styled_and_can_wrap() -> None:
    """The controls live OUTSIDE the card button (a button may not nest
    interactive children), and the archived list interpolates an untrusted
    client name, so it needs the same break treatment as the card name."""
    css = _read("app.css")
    for rule in (
        ".reports-client-card-item",
        ".reports-client-tools",
        ".reports-client-drag",
        ".reports-client-archive",
        ".reports-archived",
        ".reports-archived-restore",
    ):
        assert rule + " {" in css, f"{rule} rule missing"
    block = css.split(".reports-archived-name {", 1)
    assert len(block) == 2, ".reports-archived-name rule missing"
    body = block[1].split("}", 1)[0]
    assert "overflow-wrap" in body
    assert "min-width: 0" in body
