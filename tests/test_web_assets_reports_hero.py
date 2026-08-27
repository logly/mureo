"""Static-content guards for the list screen's band (#706 step 3-b).

**Read this with ``tests/js/reports_hero_list.test.js``.** The DECISIONS —
what the band counts, which block a client lands in, and whether the band is
drawn at all — live in ``mureo/_data/web/reports_hero.js`` and are *executed*
by ``node --test tests/js/*.test.js`` against the real ``app.html`` and the
real ``app.css``. What is pinned here is what a substring is actually good
for: that the two new assets SHIP (allow-list + ``<script>`` order), that the
band's markup and its i18n keys exist in both locales, and that the renderer
binds the decisions rather than re-deciding them.

The one that matters most is the last. The health of a client has exactly one
answer in this product — reports_triage.js's — and the band is handed
``triageHealthCounts``'s object rather than grading the roster itself. A
renderer that counted for itself would be a fourth opinion beside the cards,
the roster table and the filter chips, and a grep pin is precisely what
catches a copy of the logic reappearing.

Same limits as every static guard here: these catch a deleted name, a flipped
condition or a string that moved branch. They cannot prove the band rendered.
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
    """Source of the top-level function opened by ``signature``."""
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


@pytest.mark.unit
def test_both_new_modules_are_served_and_loaded_before_their_consumers() -> None:
    """``reports_hero.js`` publishes a global ``dashboard.js`` checks for at
    load, and ``dashboard_reports_hero.js`` is called mid-render by
    ``dashboard_reports.js`` — so both have to be in the allow-list AND in
    the right place in the page."""
    from mureo.web.handlers import _STATIC_ALLOWLIST

    assert "reports_hero.js" in _STATIC_ALLOWLIST
    assert "dashboard_reports_hero.js" in _STATIC_ALLOWLIST
    html = _read("app.html")
    # The pure module reads reports_logic.js and reports_overview.js off the
    # page at call time; both must already be there.
    assert html.index("/static/reports_overview.js") < html.index(
        "/static/reports_hero.js"
    )
    assert html.index("/static/reports_hero.js") < html.index("/static/dashboard.js")
    # The DOM half binds dashboard_reports_state.js at LOAD, and is bound by
    # dashboard_reports.js at load in turn.
    assert html.index("/static/dashboard_reports_state.js") < html.index(
        "/static/dashboard_reports_hero.js"
    )
    assert html.index("/static/dashboard_reports_hero.js") < html.index(
        "/static/dashboard_reports.js"
    )


@pytest.mark.unit
def test_the_band_is_handed_the_triage_layers_counts_and_grades_nothing() -> None:
    """One answer to "is this client healthy?", not a second one.

    ``triageHealthCounts`` is called ONCE per render and the same object goes
    to the band and to the filter chips; the per-client verdict the band is
    handed is ``triageClientHealth``, which is what the cards and the roster
    rows are painted with.
    """
    js = _read("dashboard_reports.js")
    body = _function_body(js, "async function renderReportsIndex(")
    assert "const healthCounts = triageHealthCounts(triage, rows.length);" in body
    assert "buildReportsHero(healthCounts, summaries," in body
    assert "renderReportsFilters(healthCounts);" in body
    # Exactly one call: two would be two answers the moment either caller
    # learned to pass something different.
    assert body.count("triageHealthCounts(") == 1
    # …and no copy of the decision in the renderer.
    hero = _read("dashboard_reports_hero.js")
    assert "triageClientHealth" not in hero
    assert "aggregateClientKpis" not in hero


@pytest.mark.unit
def test_the_band_is_drawn_for_a_roster_and_hidden_below_two_clients() -> None:
    """The staff review's decision, explicitly: one client keeps the index it
    had. `.reports-hero` declares its own `display`, so it needs a
    `[hidden]` rule of its own or the band stays on screen (#712)."""
    hero = _read("reports_hero.js")
    assert "REPORTS_HERO_MIN_CLIENTS = 2" in hero
    assert "total >= REPORTS_HERO_MIN_CLIENTS" in hero
    js = _read("dashboard_reports_hero.js")
    assert "band.hidden = !(model && model.show);" in js
    css = _read("app.css")
    assert ".reports-hero[hidden]" in css


@pytest.mark.unit
def test_the_fourth_block_is_carved_out_of_ok_and_nothing_else() -> None:
    """ "Not running" is not a health verdict. A client the triage layer
    marked keeps its mark whatever its figures look like, so the carve-out
    runs only over the clients it did not mark — which is also what keeps the
    four blocks a partition of the roster."""
    hero = _read("reports_hero.js")
    body = _function_body(hero, "function buildReportsHero(")
    assert 'if (health && health(i) !== "ok") continue;' in body
    assert "if (isIdle(bodies[i])) idle += 1;" in body
    assert "ok: Math.max(0, count(c.ok) - idle)," in body


@pytest.mark.unit
def test_a_summary_that_never_arrived_is_not_a_client_that_is_not_running() -> None:
    """`fetchClientCardSummary` yields `null` when the request failed, and
    that null must reach the band intact: collapsing it into `{}` made an
    unreachable client indistinguishable from one that reported no
    platforms, so a restarting daemon painted the whole roster "not running
    yet". The fetch keeps the null; the band requires a RECEIVED summary
    before it calls anything idle."""
    cards = _read("dashboard_reports_cards.js")
    fetch = _function_body(cards, "async function fetchClientCardSummary(")
    assert "|| {}" not in fetch, "a failed fetch is collapsed into an empty object"
    hero = _read("reports_hero.js")
    idle = _function_body(hero, "function isIdle(")
    assert 'if (!summary || typeof summary !== "object") return false;' in idle


@pytest.mark.unit
def test_the_band_says_a_word_beside_every_colour() -> None:
    """Colour never carries the meaning alone on these screens, and the three
    words the band shares with the filter chips are the SAME keys — a client
    is not "watch" in the band and something else 60px below it."""
    js = _read("dashboard_reports_hero.js")
    for key in (
        "dashboard.reports_health_ok",
        "dashboard.reports_health_watch",
        "dashboard.reports_health_attention",
        "dashboard.reports_health_idle",
    ):
        assert key in js, f"{key} is not on a block"
    body = _function_body(js, "function buildHeroBlock(")
    assert "reports-hero-block-label" in body
    assert "reports-hero-block-count" in body


@pytest.mark.unit
def test_the_band_and_the_feed_speak_both_locales() -> None:
    """A key present in one locale only reaches an operator as the key."""
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_health_idle",
        "dashboard.reports_hero_title",
        "dashboard.reports_hero_ratio_label",
        "dashboard.reports_feed_empty",
    ):
        for locale in ("en", "ja"):
            value = data[locale].get(key)
            assert (
                isinstance(value, str) and value.strip()
            ), f"{key} missing in {locale}"
            assert value != key


@pytest.mark.unit
def test_the_band_carries_no_figure_about_an_ad_account() -> None:
    """Everything in the band is a COUNT OF CLIENTS. The money lives in the
    portfolio strip under it, where every figure states how many clients it
    was summed over (#636, #638) — a band restating a total without that
    coverage is exactly the shape both of those bugs had."""
    js = _read("dashboard_reports_hero.js")
    for name in ("spend", "conversions", "cpa", "ctr", "formatKpi"):
        assert name not in js, f"the band states {name}"


@pytest.mark.unit
def test_the_day_on_the_band_is_the_servers() -> None:
    """A band headed with the READER's date over a feed dated by the host's
    is the timezone bug reports_overview.js exists to keep off this screen.
    There is one answer to "what day is it", and the band asks for it."""
    hero = _read("reports_hero.js")
    assert "statedServerDate(bodies)" in hero
    assert "Date.now()" not in hero
    assert "new Date(" not in hero
    js = _read("dashboard_reports_hero.js")
    assert "new Date(" not in js


@pytest.mark.unit
def test_the_feed_shows_the_entrys_own_display_line() -> None:
    """A row's shape is decided by the ENTRY, not by the client: a
    ``display_title`` was written for a row exactly like this one, and an
    entry that predates the contract shows its work-journal summary with the
    markdown emphasis stripped and cut — the same helper the detail view
    uses, rather than a second copy of the rule."""
    js = _read("reports_overview.js")
    body = _function_body(js, "function actionText(")
    assert "display().actionLine(row)" in body
    assert "line.title" in body
    assert "line.summary" in body
    # No second implementation of the strip or the cut here — both are
    # reports_display.js's, and a copy would drift from the detail view's.
    assert "stripEmphasis" not in js
    assert "LEGACY_SUMMARY_CHARS" not in js
    assert "slice(0, 120)" not in js
