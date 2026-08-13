"""Static-content guards for the Reports conflict + freshness UI (#533/#535).

**Read this with ``tests/js/reports_logic.test.js``.** Since #540 the two
halves of this feature are guarded differently:

  - the DECISIONS — withhold the KPIs when an account is double-counted,
    take the oldest contributor's freshness, route on the conflict kind —
    live in ``mureo/_data/web/reports_logic.js`` and are *executed* by
    ``node --test tests/js/``. Inverted conditions and reordered branches
    are caught there, not here.
  - the RENDERING stays in ``dashboard.js``, still has no runner that can
    drive a DOM, and is guarded below by pinning the *shape* of the bundled
    assets read straight from ``mureo/_data/web/``.

Between the two sits the SEAM, and it is where the remaining money-safety
risk lives: the logic can withhold a figure correctly and the renderer can
still draw the wrong thing, because one comparison points the wrong way.
Neither guard sees that on its own — the JS suite never reaches the
renderer, and a substring check reads ``!= null`` and ``== null`` alike. The
last section of this file pins those on POLARITY and on which branch a
string is reachable from, the way ``test_web_assets_reports_order_and_archive``
pins the archive handler's confirm→bail→post ORDER.

So these remain substring/structure pins, with the limits that implies:
they catch a deleted name, string or selector, and they cannot tell you
whether a card actually rendered. What they protect:

  - the client card must not render a KPI total it knows is double-counted,
    and must not let a flagged card read as a healthy one;
  - the two findings (double-counted account vs unrecognisable key) keep
    separate strings, because the operator's next move differs;
  - per-platform freshness comes from the row's own ``freshness``, never from
    the document-level ``last_synced_at``;
  - everything operator-visible is localized in both ``en`` and ``ja``;
  - untrusted text keeps going through ``textContent``;
  - the extracted module is actually served and actually loaded, so the
    split cannot leave the page with a dashboard that cannot bind it;
  - the renderer draws the withheld/absent states the right way round, and
    asks the logic module rather than re-deciding for itself.

The reports frontend is TWO files that ship as one behaviour, so the pins
below grep the pair as a single source (``_REPORTS_ASSETS``) — the same way
``test_web_assets_meta_token_card.py`` greps the auth-wizard pair — rather
than asserting which of the two a given string sits in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"

# The pure logic module and the renderer that consumes it (#540).
_REPORTS_ASSETS = ("reports_logic.js", "dashboard.js")


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _read_reports() -> str:
    return "\n".join(_read(name) for name in _REPORTS_ASSETS)


def _function_body(js: str, signature: str) -> str:
    """Source of the top-level function opened by ``signature``.

    Top-level helpers in dashboard.js sit at two-space indent, so the first
    ``\\n  }`` after the signature closes them; nested blocks close deeper.
    (Same helper as ``test_web_assets_reports_order_and_archive.py``.)
    """
    assert signature in js, f"{signature} missing"
    tail = js.split(signature, 1)[1]
    assert "\n  }" in tail, f"{signature} has no two-space closing brace"
    return tail.split("\n  }", 1)[0]


@pytest.mark.unit
def test_dashboard_reads_the_conflict_marker_from_the_wire() -> None:
    """The grouping is done server-side (no account ids reach the browser),
    so the frontend consumes ``platform_conflicts`` rather than trying to
    join platform rows itself."""
    js = _read_reports()
    assert "platform_conflicts" in js
    assert '"duplicate_account"' in js
    assert '"unrecognized_key"' in js


@pytest.mark.unit
def test_client_card_withholds_kpis_when_an_account_is_double_counted() -> None:
    """Summing figures that are KNOWN to be wrong, even under a warning, is
    exactly the triage error the card causes today. The aggregate is refused
    instead; the per-platform detail is one click away and is not summed."""
    js = _read_reports()
    assert "doubleCounted" in js
    # The aggregate helper itself nulls the figures, so no future caller can
    # render the double-counted sum by forgetting to check the flag.
    assert "function aggregateClientKpis(" in js
    assert "hasFigures" in js
    # That the nulling CONDITION is the right way round is proved by
    # tests/js/reports_logic.test.js, which executes it; this pin only says
    # the helper still exists and is still where the card gets its figures.
    assert "aggregateClientKpis(summary)" in _read("dashboard.js")


@pytest.mark.unit
def test_a_flagged_card_cannot_read_as_a_healthy_one() -> None:
    """A conflicted card carries a visible modifier class AND a note, so the
    at-a-glance grid never shows a flagged client as ordinary."""
    js = _read_reports()
    css = _read("app.css")
    assert "reports-client-card-conflict" in js
    assert ".reports-client-card.is-conflicted" in css
    assert ".reports-client-card-conflict" in css


@pytest.mark.unit
def test_the_two_findings_keep_separate_strings() -> None:
    """Different findings, different operator next-moves: "these KPIs are
    double-counted right now" vs "this entry's identity cannot be
    established". Merging them into one warning loses that."""
    js = _read_reports()
    assert "dashboard.reports_conflict_double_counted" in js
    assert "dashboard.reports_conflict_unknown_key" in js


@pytest.mark.unit
def test_the_unrecognised_key_note_branches_on_the_account_fact() -> None:
    """#606 — the note must not tell an operator the ad account cannot be
    identified when the duplicate-account note directly above it just
    identified it. The renderer picks between two strings on the wire fact
    (``account_known``), so the wording can never outrun the condition."""
    js = _read_reports()
    assert "account_known" in js
    assert "dashboard.reports_conflict_unknown_key_no_account" in js
    # The narrow string is reachable only from the account-KNOWN branch: an
    # inverted test would put the "review it by hand" clause back on exactly
    # the rows the duplicate finding has already explained.
    logic = _read("reports_logic.js")
    assert "row.account_known === true" in logic


@pytest.mark.unit
def test_platform_cards_show_the_conflict_too() -> None:
    """The index card only renders for multi-client installs, so a
    single-client (OSS) setup would otherwise never see the finding at all —
    the per-platform card is the shared surface."""
    js = _read_reports()
    css = _read("app.css")
    assert "report-card-conflict" in js
    assert ".report-card-conflict" in css


@pytest.mark.unit
def test_per_platform_freshness_comes_from_the_row_not_last_synced_at() -> None:
    """``last_synced_at`` is re-stamped on ANY platform write, so it cannot
    stand in for per-platform freshness (#535). The card reads the row's own
    ``freshness`` block."""
    js = _read_reports()
    assert "freshness" in js
    assert "dashboard.reports_platform_updated" in js
    assert "dashboard.reports_platform_stale" in js
    assert "dashboard.reports_platform_age_unknown" in js
    # Mixed case: some contributor stale, some with no fetched_at. The card is
    # marked stale (a fresh sibling must never hide a stale one) so the LABEL
    # has to say something true of that state rather than "unknown" in red.
    assert "dashboard.reports_platform_stale_partial" in js
    # The detail view's document-level line keeps its own, correctly labelled
    # string — that fact is unchanged.
    assert "dashboard.reports_synced" in js


@pytest.mark.unit
def test_freshness_and_conflict_strings_are_localized_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_conflict_double_counted",
        "dashboard.reports_conflict_kpis_withheld",
        "dashboard.reports_conflict_unknown_key",
        "dashboard.reports_conflict_unknown_key_no_account",
        "dashboard.reports_platform_updated",
        "dashboard.reports_platform_stale",
        "dashboard.reports_platform_stale_partial",
        "dashboard.reports_platform_age_unknown",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_untrusted_keys_and_names_can_wrap() -> None:
    """A platform key is free-form and mureo does not control who writes it,
    so a long space-free one has no break point of its own. Inside the flex
    card heads that would push a card wider than its grid track and distort
    the whole index. Every rule that renders one needs an explicit break —
    plus ``min-width: 0``, without which a flex item refuses to shrink below
    its content and the wrapping never takes effect."""
    css = _read("app.css")
    for rule in (
        ".report-card-name",
        ".report-card-conflict",
        ".reports-client-card-name",
        ".reports-client-card-conflict",
    ):
        body = css.split(rule + " {", 1)
        assert len(body) == 2, f"{rule} rule missing"
        block = body[1].split("}", 1)[0]
        assert "overflow-wrap" in block, f"{rule} has no overflow-wrap"
        assert "min-width: 0" in block, f"{rule} has no min-width: 0"


@pytest.mark.unit
def test_conflict_and_freshness_text_is_rendered_via_text_content() -> None:
    """Platform keys are free-form operator/agent input. They reach the DOM
    through ``textContent`` only — nothing in either file ever ASSIGNS
    ``innerHTML`` (the one occurrence is the comment saying so)."""
    for name in _REPORTS_ASSETS:
        js = _read(name)
        assert ".innerHTML =" not in js, name
        assert ".innerHTML=" not in js, name


@pytest.mark.unit
def test_the_pure_logic_is_served_and_loaded_before_its_consumer() -> None:
    """#540 split the money-safety logic into its own asset so a test runner
    can execute it, and #556 split two more the same way. That only holds if
    the browser still gets them: each has to be on the static allow-list and
    its ``<script>`` has to come BEFORE dashboard.js, which binds all three at
    load. Miss either and the dashboard is a blank page — so this pins the
    shipping half of the splits.

    The module list is DISCOVERED, not declared: every ``reports_*.js`` in
    ``mureo/_data/web/`` must satisfy this. A module extracted but never
    served is the failure being guarded, and a hand-maintained list is
    exactly what a person forgets to add the new name to."""
    from mureo.web.handlers import _STATIC_ALLOWLIST

    modules = sorted(p.name for p in _WEB.glob("reports_*.js"))
    assert modules, "no reports_*.js modules found — did the layout change?"
    html = _read("app.html")
    for name in modules:
        assert name in _STATIC_ALLOWLIST, f"{name} is not served"
        assert html.index(f"/static/{name}") < html.index("/static/dashboard.js")
        # It stays a plain <script>: no type="module", no bundler entry point.
        assert f'src="/static/{name}"></script>' in html
    assert 'type="module"' not in html


@pytest.mark.unit
def test_the_extracted_logic_is_not_re_implemented_in_the_renderer() -> None:
    """One definition, executed by ``node --test tests/js/``. A copy left
    behind in dashboard.js would shadow the tested one and drift from it
    silently — which is the exact failure #540 exists to end."""
    dashboard = _read("dashboard.js")
    logic = _read("reports_logic.js")
    for fn in (
        "aggregateClientKpis",
        "reportsCardFreshness",
        "reportsFreshnessLabel",
        "reportsConflictText",
        "reportsConflictsOfKind",
        "reportsHasDoubleCount",
        "relativeAge",
    ):
        assert f"function {fn}(" in logic, f"{fn} is not in reports_logic.js"
        assert f"function {fn}(" not in dashboard, f"{fn} is duplicated"
    # The module publishes itself the way amazon_oauth.js does — a global on
    # `window`, not a module system the served page would have to grow.
    assert "window.MUREO_REPORTS_LOGIC = api" in logic
    assert "window.MUREO_REPORTS_LOGIC" in dashboard


# ---------------------------------------------------------------------------
# The logic/renderer seam
#
# reports_logic.js decides whether a figure may be shown; buildClientCard
# decides what is drawn. Between them sit a handful of one-character flips
# that BOTH guards would miss: the JS suite never reaches the renderer, and
# a substring pin sees `kpis.spend != null` and `kpis.spend == null` alike.
# Two of them put a wrong figure in front of an operator, which is the whole
# point of #533 — so they are pinned on POLARITY, the way #552 pinned the
# archive handler's confirm→bail→post ORDER rather than its identifiers.
#
# **What these still cannot catch.** They read source, not behaviour. They
# cannot prove the card renders at all, that the withheld note is appended
# to the card the operator is looking at, that the KPI cell reaches the DOM,
# or that CSS makes `is-stale` visible. A renderer that satisfied every
# assertion below and then dropped the node on the floor would pass. Closing
# that needs a DOM runner, which #540 deliberately did not buy.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_the_card_renders_a_spend_only_when_one_was_not_withheld() -> None:
    """Polarity, not presence. `aggregateClientKpis` returns ``null`` for a
    figure it refuses to state, so the card must render the number on
    NOT-null and the em dash on null. Inverting this single comparison is
    the worst outcome in the feature: a healthy client reads "—" while the
    double-counted one — whose figures were withheld precisely so nobody
    triages by them — is the only card showing a number."""
    js = _read("dashboard.js")
    card = _function_body(js, "function buildClientCard(")
    assert "kpis.spend != null ? formatNumber(kpis.spend) : " in card, (
        "the spend cell no longer tests `kpis.spend != null` first — a "
        "flipped comparison renders the withheld figure and hides the real one"
    )
    # The absent case is an em dash, never a 0: this is a triage view and a
    # no-data client must not read as zero spend.
    spend_cell = card.split("kpis.spend != null ?", 1)[1].split("\n", 1)[0]
    assert '"—"' in spend_cell, spend_cell
    assert "0" not in spend_cell, spend_cell
    # The secondary cells are rendered only when a figure survived, so a
    # withheld conversions/CPA leaves no cell rather than an empty one.
    for metric in ("conversions", "cpa"):
        assert (
            f"if (kpis.{metric} != null) {{" in card
        ), f"the {metric} cell no longer gates on a non-null figure"


@pytest.mark.unit
def test_the_withheld_warning_fires_on_the_conflicted_card() -> None:
    """The other flip: `if (!kpis.doubleCounted)` would put "these figures
    are withheld" on every healthy card and remove it from the one card it
    describes — leaving the conflicted client silently short of KPIs with no
    stated reason. Pinned as: the branch tests the TRUTHY case, and the
    withheld string is reachable only from inside it."""
    js = _read("dashboard.js")
    card = _function_body(js, "function buildClientCard(")
    assert "if (kpis.doubleCounted) {" in card, (
        "the withheld-KPIs warning no longer branches on the truthy "
        "doubleCounted case"
    )
    branch = card.split("if (kpis.doubleCounted) {", 1)[1].split("\n    }", 1)[0]
    assert "dashboard.reports_conflict_kpis_withheld" in branch
    # …and nowhere else, so it cannot also be emitted on a healthy card.
    assert js.count("dashboard.reports_conflict_kpis_withheld") == 1


@pytest.mark.unit
def test_a_stale_freshness_marks_the_card_stale() -> None:
    """Same class of flip on #535's half: `reportsCardFreshness` returns
    ``stale: true`` and the card must add the modifier on TRUE. Inverted,
    every up-to-date card renders in stale-red and the stale one renders
    clean — the failure mode the freshness work exists to prevent. Both the
    client card and the per-platform card carry it."""
    js = _read("dashboard.js")
    client_card = _function_body(js, "function buildClientCard(")
    assert (
        '(cardFresh.stale ? " is-stale" : "")' in client_card
    ), "the client card's stale modifier no longer keys off the truthy case"
    # The per-platform card carries its own, from the row's own freshness.
    platform_foot = _function_body(js, "function buildReportCardFoot(")
    assert (
        '(fresh.stale ? " is-stale" : "")' in platform_foot
    ), "the platform card's stale modifier no longer keys off the truthy case"
    assert "reportsFreshnessLabel(platform.freshness)" in platform_foot
    # The label always comes from the same object as the flag, so the text
    # and the styling cannot disagree.
    assert "fresh.textContent = cardFresh.text" in client_card
    assert ".is-stale" in _read("app.css")


@pytest.mark.unit
def test_the_renderer_asks_the_logic_module_rather_than_re_deciding() -> None:
    """The withholding must stay a property of the aggregate, not of the
    card. A renderer that re-derived "is this double-counted?" from
    ``platform_conflicts`` itself would drift from the tested condition the
    first time the wire grows a third kind."""
    js = _read("dashboard.js")
    card = _function_body(js, "function buildClientCard(")
    assert "aggregateClientKpis(summary)" in card
    assert "reportsCardFreshness(summary)" in card
    # The card reads the flag it was handed; it does not re-inspect kinds.
    assert '"duplicate_account"' not in js
    assert "REPORTS_CONFLICT_DUPLICATE_ACCOUNT" not in js


@pytest.mark.unit
def test_the_period_fallback_asks_hasfigures_not_the_rendered_values() -> None:
    """``fetchClientCardSummary`` re-requests a different period window when
    the selected one has no data. It must decide that on ``hasFigures`` —
    the RAW presence of data — and never on the rendered values: a
    conflicted client HAS figures, they are just withheld, and the conflict
    is a property of the document rather than of the window, so re-fetching
    would spin and then show a window the operator did not select.

    Pinned separately from the card because ``aggregateClientKpis`` has two
    call sites, and a structure pin on one of them says nothing about the
    other."""
    js = _read("dashboard.js")
    fetch = _function_body(js, "async function fetchClientCardSummary(")
    assert (
        "aggregateClientKpis(summary)" in fetch
    ), "the period fallback no longer consults the aggregate at all"
    assert "if (!kpis.hasFigures && periods.length) {" in fetch, (
        "the period fallback no longer branches on hasFigures — branching on "
        "kpis.spend/conversions would re-fetch for every conflicted client"
    )
    # It must not re-decide from the withheld figures.
    fallback = fetch.split("if (!kpis.hasFigures", 1)[1]
    for withheld in ("kpis.spend", "kpis.conversions", "kpis.cpa"):
        assert withheld not in fallback, f"the fallback reads {withheld}"
