"""Static-content guards for the reports period toggle (前日 / 30日, PR-C).

The configure UI's reporting dashboard renders a per-window toggle
(YESTERDAY / LAST_30_DAYS) sourced from the summary's ``periods`` union.
These tests pin the *shape* of the bundled web assets (no build step —
read directly from ``mureo/_data/web/``) so a future refactor that drops
the toggle wiring, the ``?period=`` request, or the default-window choice
flips red here before an operator notices the regression.
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
    js = _read("dashboard.js")
    assert "dashboard.reports_period_yesterday" in js
    assert "dashboard.reports_period_last_30_days" in js


@pytest.mark.unit
def test_css_styles_active_period_segment() -> None:
    css = _read("app.css")
    assert ".reports-period-btn" in css
    assert ".reports-period-btn.is-active" in css


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
    `cpa_over_target_logly` never reaches the operator."""
    js = _read("dashboard.js")
    assert "function humanizeReportFlag(" in js
    assert "REPORTS_FLAG_BASES" in js
    # The chip text must go through the humanizer for bare-string flags.
    assert "humanizeReportFlag(flag)" in js


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
    not all neutral grey."""
    js = _read("dashboard.js")
    assert "function reportFlagKind(" in js
    assert "reportFlagKind(flag)" in js
    assert '"is-warn"' in js
    assert '"is-danger"' in js
