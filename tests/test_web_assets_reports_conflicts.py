"""Static-content guards for the Reports conflict + freshness UI (#533/#535).

There is no JS build step and no JS test runner in this repo, so — as with
``test_web_assets_reports_period_toggle.py`` — these pin the *shape* of the
bundled assets read straight from ``mureo/_data/web/``. The behaviour they
protect:

  - the client card must not render a KPI total it knows is double-counted,
    and must not let a flagged card read as a healthy one;
  - the two findings (double-counted account vs unrecognisable key) keep
    separate strings, because the operator's next move differs;
  - per-platform freshness comes from the row's own ``freshness``, never from
    the document-level ``last_synced_at``;
  - everything operator-visible is localized in both ``en`` and ``ja``;
  - untrusted text keeps going through ``textContent``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_dashboard_reads_the_conflict_marker_from_the_wire() -> None:
    """The grouping is done server-side (no account ids reach the browser),
    so the frontend consumes ``platform_conflicts`` rather than trying to
    join platform rows itself."""
    js = _read("dashboard.js")
    assert "platform_conflicts" in js
    assert '"duplicate_account"' in js
    assert '"unrecognized_key"' in js


@pytest.mark.unit
def test_client_card_withholds_kpis_when_an_account_is_double_counted() -> None:
    """Summing figures that are KNOWN to be wrong, even under a warning, is
    exactly the triage error the card causes today. The aggregate is refused
    instead; the per-platform detail is one click away and is not summed."""
    js = _read("dashboard.js")
    assert "doubleCounted" in js
    # The aggregate helper itself nulls the figures, so no future caller can
    # render the double-counted sum by forgetting to check the flag.
    assert "function aggregateClientKpis(" in js
    assert "hasFigures" in js


@pytest.mark.unit
def test_a_flagged_card_cannot_read_as_a_healthy_one() -> None:
    """A conflicted card carries a visible modifier class AND a note, so the
    at-a-glance grid never shows a flagged client as ordinary."""
    js = _read("dashboard.js")
    css = _read("app.css")
    assert "reports-client-card-conflict" in js
    assert ".reports-client-card.is-conflicted" in css
    assert ".reports-client-card-conflict" in css


@pytest.mark.unit
def test_the_two_findings_keep_separate_strings() -> None:
    """Different findings, different operator next-moves: "these KPIs are
    double-counted right now" vs "this entry's identity cannot be
    established". Merging them into one warning loses that."""
    js = _read("dashboard.js")
    assert "dashboard.reports_conflict_double_counted" in js
    assert "dashboard.reports_conflict_unknown_key" in js


@pytest.mark.unit
def test_platform_cards_show_the_conflict_too() -> None:
    """The index card only renders for multi-client installs, so a
    single-client (OSS) setup would otherwise never see the finding at all —
    the per-platform card is the shared surface."""
    js = _read("dashboard.js")
    css = _read("app.css")
    assert "report-card-conflict" in js
    assert ".report-card-conflict" in css


@pytest.mark.unit
def test_per_platform_freshness_comes_from_the_row_not_last_synced_at() -> None:
    """``last_synced_at`` is re-stamped on ANY platform write, so it cannot
    stand in for per-platform freshness (#535). The card reads the row's own
    ``freshness`` block."""
    js = _read("dashboard.js")
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
    through ``textContent`` only — nothing in the file ever ASSIGNS
    ``innerHTML`` (the one occurrence is the comment saying so)."""
    js = _read("dashboard.js")
    assert ".innerHTML =" not in js
    assert ".innerHTML=" not in js
