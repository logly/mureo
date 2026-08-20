"""Static-content guards for the "why the figures did not move" note (#638).

**Read this with ``tests/js/reports_not_collected.test.js``.** The DECISION —
is there a note, and what does it say? — lives in
``mureo/_data/web/reports_logic.js`` and is *executed* by
``node --test tests/js/*.test.js``. The RENDERING lives in ``dashboard.js``,
has no runner that can drive a DOM, and is pinned here.

What #639 fixed was the card asserting a stale figure as the selected
window's answer. What it could not fix is that the operator still has no
idea why the figure is stale — a stopped ad account and a stopped collector
produce the identical card, and the one that sat for eleven days was the
second. So the note has to appear where the reader already is: directly
under the sentence that says the figures are being withheld, and above the
hint that says what to run.

Order is therefore the thing pinned here, not wording: three notes now share
that space (conflict → stale → why), and the repair hint stays last of them.

Same limits as every static guard here: these catch a deleted name, a
flipped condition or a string that moved branch. They cannot prove a card
rendered at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"

_REPORTS_ASSETS = ("reports_logic.js", "dashboard.js")


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


@pytest.mark.unit
def test_the_renderer_binds_the_logic_module_rather_than_re_deciding() -> None:
    """Whether a row HAS a usable note — and which localized sentence states
    it — is one decision, made in the module the JS suite executes. A
    renderer that re-derived it would drift from the shape the read side
    whitelists."""
    js = _read("dashboard.js")
    for name in ("reportsNotCollectedNotes", "reportsNotCollectedText"):
        assert f"{name} = REPORTS_LOGIC.{name}" in js, f"{name} is not bound"
        assert f"function {name}(" not in js, f"{name} was copied into dashboard.js"


@pytest.mark.unit
def test_the_index_states_the_reason_without_opening_the_client() -> None:
    """ "These figures were collected before the window shown" is where the
    operator stops reading. The reason belongs in the next sentence — and in
    a place they reach WITHOUT opening the client.

    It is no longer inside the card. On a 27-client grid the same sentence
    was rendered twice on one screen: once in the card and once in the alert
    row above it. It now lives only in the alert row — still on the index,
    still one screen, still not behind a click into the client."""
    js = _read("dashboard.js")
    # reports_triage.js raises one item per platform that said why (its own
    # suite executes that); the row renders it.
    assert "not_collected" in _read("reports_triage.js")
    assert "dashboard.reports_triage_not_collected" in _read("reports_triage.js")
    row = _function_body(js, "function buildTriageRow(")
    assert "triageItemText(item)" in row


@pytest.mark.unit
def test_the_reason_comes_before_what_to_run_about_it() -> None:
    """The order is the argument the row makes: what is wrong, then what to
    run. The next step is what an operator ACTS on, so nothing may be
    appended after it."""
    row = _function_body(_read("dashboard.js"), "function buildTriageRow(")
    assert row.index("triageItemText(item)") < row.index("triageItemNextStep(item)")
    # And the client's own detail view still states both, per platform.
    platform_card = _function_body(_read("dashboard.js"), "function buildReportCard(")
    assert "reportsNotCollectedNote(" in platform_card
    assert "report-card-not-collected" in platform_card
    assert "reportsRepairHint(conflicts)" in platform_card


@pytest.mark.unit
def test_the_platform_card_carries_its_own_reason() -> None:
    """A single-client (OSS) install never renders the client index, so the
    platform card is the ONLY place this can surface there — the same reason
    the conflict note is repeated on it."""
    card = _function_body(_read("dashboard.js"), "function buildReportCard(")
    assert "reportsNotCollectedNote(platform)" in card
    # Above the headline, because it explains the figure (or its absence) —
    # and before the two branches that RETURN early (no metrics at all, and
    # the stale one), or the platform it is most true of would never show it.
    assert card.index("reportsNotCollectedNote(platform)") < card.index(
        "const hasMetrics ="
    )


@pytest.mark.unit
def test_the_note_never_touches_the_figures() -> None:
    """It explains the numbers; it is not evidence that they are wrong. They
    are the last ones truly collected, so nothing here may withhold or
    restate them — that decision belongs to staleness alone."""
    logic = _read("reports_logic.js")
    aggregate = _function_body(logic, "function aggregateClientKpis(")
    assert "not_collected" not in aggregate
    assert "reportsNotCollected" not in aggregate


@pytest.mark.unit
def test_the_reason_reaches_the_dom_as_text() -> None:
    """The reason is writer-supplied text from STATE.json — an API error
    string, in practice. It is set as text, never as markup."""
    js = _read("dashboard.js")
    # Twice over: the alert row above the index grid, and the per-platform
    # card in the client's detail view.
    row = _function_body(js, "function buildTriageRow(")
    assert ".textContent = triageItemText(item)" in row
    platform_card = _function_body(js, "function buildReportCard(")
    assert ".textContent = reportsNotCollectedText(" in platform_card
    for name in _REPORTS_ASSETS:
        assert ".innerHTML" not in _read(name).replace("// innerHTML", ""), name


@pytest.mark.unit
def test_the_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_not_collected",
        "dashboard.reports_not_collected_undated",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_the_strings_say_the_figures_are_older_not_wrong() -> None:
    """The one thing the wording must not do. The stored figures are the last
    ones that were truly collected; a sentence that reads as "these numbers
    are wrong" would send an operator to fix a number instead of a
    collector."""
    data = json.loads(_read("i18n.json"))
    en = data["en"]["dashboard.reports_not_collected"]
    ja = data["ja"]["dashboard.reports_not_collected"]
    assert "not wrong" in en, en
    assert "older" in en, en
    assert "誤り" in ja and "古い" in ja, ja


@pytest.mark.unit
def test_the_note_blocks_have_styles_that_can_wrap() -> None:
    """Both elements interpolate a free-form reason and a platform-supplied
    label into a flex card, so they need the same break treatment every other
    note in the card does."""
    css = _read("app.css")
    for rule in (".report-card-not-collected", ".reports-triage-detail-row"):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"
