"""Static-content guards for the reports period toggle (前日 / 30日, PR-C).

The configure UI's reporting dashboard renders a per-window toggle
(YESTERDAY / LAST_30_DAYS) sourced from the summary's ``periods`` union.
These tests pin the *shape* of the bundled web assets (no build step —
read directly from ``mureo/_data/web/``) so a future refactor that drops
the toggle wiring, the ``?period=`` request, or the default-window choice
flips red here before an operator notices the regression.

The toggle itself is rendering and has no runner. Two things it leans on do:
the KPI aggregation it re-requests moved to ``reports_logic.js`` in #540, and
the window/flag labelling moved to ``reports_format.js`` in #556. Both are
executed by ``node --test tests/js/``, so the pins below read each helper from
its own file and only check that ``dashboard.js`` still calls it — which is
the half no runner can see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_app_html_has_period_toggle_container() -> None:
    """The reports head carries the toggle mount point, hidden by default
    (renderReports reveals it only when >= 2 windows exist)."""
    html = _read("app.html")
    assert "data-reports-period" in html
    # role=group makes the segmented control a labelled grouping for AT.
    assert 'role="group"' in html


@pytest.mark.unit
def test_dashboard_js_renders_and_wires_period_toggle() -> None:
    js = _read("dashboard.js")
    assert "function renderReportsPeriodToggle(" in js
    assert "reports-period-btn" in js
    # The toggle and the active window state must exist.
    assert "reportsPeriod" in js


@pytest.mark.unit
def test_summary_request_sends_period_param() -> None:
    """The summary fetch must forward the selected window as ``?period=``
    (encoded), or the backend returns the default passthrough and the
    toggle is inert."""
    js = _read("dashboard.js")
    assert "encodeURIComponent(reportsPeriod)" in js
    assert '"period="' in js


@pytest.mark.unit
def test_default_window_is_yesterday() -> None:
    """Default view is the prior day — daily-check runs daily, so YESTERDAY
    is what an operator checks first."""
    js = _read("dashboard.js")
    assert 'let reportsPeriod = "YESTERDAY"' in js


@pytest.mark.unit
def test_toggle_hidden_without_a_real_choice() -> None:
    """A single-window account has nothing to switch — the toggle stays
    hidden rather than showing one lone button."""
    js = _read("dashboard.js")
    assert "list.length < 2" in js


@pytest.mark.unit
def test_period_label_keys_referenced() -> None:
    """Window buttons are localized via the canonical period label keys."""
    js = _read("reports_format.js")
    assert "dashboard.reports_period_yesterday" in js
    assert "dashboard.reports_period_last_30_days" in js
    # …and the button still gets its text from the labeller (#556).
    assert "reportsPeriodLabel(token)" in _read("dashboard.js")


@pytest.mark.unit
def test_the_browser_and_the_backend_agree_on_the_window_vocabulary() -> None:
    """``reports_format.js`` carries the label table the browser marks tabs
    from; ``mureo.core.metrics_windows`` carries the one the write guard
    refuses from. They are two copies of one fact, and a drift between them
    is exactly the #659 failure pointing the other way — a window mureo
    accepts and the dashboard treats as an agent's invention."""
    import re

    from mureo.core.metrics_windows import CANONICAL_METRICS_WINDOWS

    js = _read("reports_format.js")
    block = re.search(r"const REPORTS_PERIOD_LABELS = \{(.*?)\};", js, re.S)
    assert block is not None
    tokens = re.findall(r"^\s*([A-Z0-9_]+):", block.group(1), re.M)
    assert tokens == list(CANONICAL_METRICS_WINDOWS)


@pytest.mark.unit
def test_a_window_mureo_does_not_define_is_marked_not_hidden() -> None:
    """#659 — labels an agent invented are already on disk. Dropping their
    tab would hide figures mureo really collected; leaving them
    indistinguishable leaves an operator unable to tell which window their
    reports are keyed to. So the button renders, marked, with the reason."""
    js = _read("dashboard.js")
    assert "isCanonicalReportsPeriod(token)" in js
    assert '" is-adhoc"' in js
    assert "dashboard.reports_period_adhoc" in js
    # The decision itself lives in the module a runner can execute (#556),
    # not in an inline condition here.
    assert "function isCanonicalReportsPeriod(" in _read("reports_format.js")


@pytest.mark.unit
def test_the_adhoc_window_hint_is_localized() -> None:
    import json

    data = json.loads(_read("i18n.json"))
    key = "dashboard.reports_period_adhoc"
    for loc in ("en", "ja"):
        assert data[loc].get(key), f"{key} missing in {loc}"
    assert data["en"][key] != data["ja"][key]


@pytest.mark.unit
def test_css_styles_active_period_segment() -> None:
    css = _read("app.css")
    assert ".reports-period-btn" in css
    assert ".reports-period-btn.is-active" in css
    # A window mureo does not define reads as a foreign tab, not a peer.
    assert ".reports-period-btn.is-adhoc" in css


@pytest.mark.unit
def test_hidden_attribute_collapses_reports_header_controls() -> None:
    """The client selector and the period toggle both set ``display``
    explicitly, which overrides the UA ``[hidden] { display: none }`` — so
    each needs a targeted ``[hidden]`` rule, or it renders an empty control
    when JS hides it (a single client / fewer than two windows). Regression
    guard for the empty client dropdown that shipped in the reports UI.
    """
    css = _read("app.css")
    assert ".dashboard-reports-client[hidden]" in css
    assert ".dashboard-reports-period[hidden]" in css


@pytest.mark.unit
def test_report_flags_are_humanized_not_raw() -> None:
    """Free-form snake_case report flags (reports.daily.flags) must be mapped
    to friendly labels, not rendered raw. The dashboard humanizes them via a
    base→i18n-label map with a generic fallback, so a raw tag like
    `cpa_over_target_logly` never reaches the operator.

    That the LONGEST base wins and that an unknown code degrades to a
    humanized token rather than a raw i18n key is *executed* by
    ``tests/js/reports_format.test.js``; this only pins that the helper
    exists and that the chip text still goes through it."""
    js = _read("reports_format.js")
    assert "function humanizeReportFlag(" in js
    assert "REPORTS_FLAG_BASES" in js
    # The chip text must go through the humanizer for bare-string flags.
    assert "humanizeReportFlag(flag)" in _read("dashboard.js")


@pytest.mark.unit
def test_common_flag_labels_present_in_both_locales() -> None:
    import json

    data = json.loads(_read("i18n.json"))
    for key in (
        "dashboard.reports_flag_cpa_over_target",
        "dashboard.reports_flag_cv_below_target",
        "dashboard.reports_flag_operation_mode_mismatch",
    ):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


@pytest.mark.unit
def test_report_flags_get_severity_colored_chips() -> None:
    """Flags render as coloured tags: each known base carries a severity
    (is-warn / is-danger / is-success) and the chip class comes from
    reportFlagKind(), not raw keyword inference alone — so issue flags are
    not all neutral grey.

    Which severity each base carries is *executed* by
    ``tests/js/reports_format.test.js``; this pins that the renderer asks
    for a kind at all."""
    js = _read("reports_format.js")
    assert "function reportFlagKind(" in js
    assert '"is-warn"' in js
    assert '"is-danger"' in js
    assert "reportFlagKind(flag)" in _read("dashboard.js")


@pytest.mark.unit
def test_reports_index_detail_navigation() -> None:
    """#307: the Reports tab is an index (client card grid) ↔ detail (one
    client) navigation — not a single-select dropdown. Clicking a card opens
    its detail; a back bar returns to the index. The old <select> is gone."""
    html = _read("app.html")
    js = _read("dashboard.js")
    css = _read("app.css")
    # Index grid + detail container present; old dropdown removed.
    assert "data-reports-clients" in html  # index grid
    assert "data-reports-detail" in html  # detail view wrapper
    assert "data-reports-back" in html  # back-to-index button
    assert "data-reports-client-wrap" not in html
    assert "<select data-reports-client>" not in html
    # The back link sits under the "Reports" heading (its own head column).
    assert "dashboard-reports-head-title" in html
    # JS builds the index, aggregates KPIs, opens detail, and toggles views.
    assert "function renderReportsIndex(" in js
    assert "function buildClientCard(" in js
    assert "function aggregateClientKpis(" in _read("reports_logic.js")
    assert "aggregateClientKpis(summary)" in js
    assert "function showReportsClientDetail(" in js
    assert "function setReportsView(" in js
    assert "renderReportsClientSelector" not in js
    # Card + back-link styling exists.
    assert ".reports-client-card" in css
    assert ".dashboard-reports-head-title" in css


@pytest.mark.unit
def test_reports_single_client_skips_index() -> None:
    """A single-client (OSS) install opens the detail directly — no index page,
    no back bar — while >1 client (Agency) defaults to the index."""
    js = _read("dashboard.js")
    assert "reportsClients.length <= 1" in js
    # The back bar only appears when there is an index to return to.
    assert "reportsClients.length > 1" in js


@pytest.mark.unit
def test_reports_client_card_flags_are_severity_capped() -> None:
    """Client cards reuse the humanized + severity-coloured flag chips, sorted
    most-urgent-first and capped with a +N overflow."""
    js = _read("dashboard.js")
    assert "REPORTS_CLIENT_FLAG_CAP" in js
    assert "flagSeverityRank" in js
    assert "humanizeReportFlag(flag)" in js
    assert "reports-client-flag-more" in js
