"""Static-content guards for the structured report-flag rendering (PR-C).

The Reports dashboard renders a report's ``flags`` as coloured chips. PR-A
introduced a canonical vocabulary of flag CODES (each with a severity) and a
``custom`` escape hatch; a structured flag ``{code, severity, params}`` keeps
its detail in ``params`` so the chip stays coarse and localizable while the
detail moves to a drill-down. These tests pin the bundled web assets (no build
step — read directly from ``mureo/_data/web/``) so a regression that drops the
localized labels, the severity colouring, or the drill-down flips red here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"

# Canonical flag codes introduced/aligned in PR-A that the frontend must be
# able to render as a localized label (object flag by ``code``, or a bare
# string flag by base match).
_NEW_FLAG_LABEL_KEYS = (
    "dashboard.reports_flag_goals_met",
    "dashboard.reports_flag_cpa_spike",
    "dashboard.reports_flag_invalid_traffic_suspected",
    "dashboard.reports_flag_zero_cv_adspots",
    "dashboard.reports_flag_budget_drift",
    "dashboard.reports_flag_supply_tools_unconfigured",
    "dashboard.reports_flag_anomaly_baseline_insufficient",
    "dashboard.reports_flag_pending_observations",
    "dashboard.reports_flag_search_console_no_property",
    "dashboard.reports_flag_ga4_not_configured",
)

# Param-label keys the drill-down renders (``params`` detail). Any key the
# frontend does not localize falls back to a humanized token, but these common
# ones are localized so the Japanese UI reads in Japanese.
_PARAM_LABEL_KEYS = (
    "dashboard.reports_param_adspot",
    "dashboard.reports_param_adspots",
    "dashboard.reports_param_spend",
    "dashboard.reports_param_cpa",
    "dashboard.reports_param_ctr",
    "dashboard.reports_param_live",
    "dashboard.reports_param_configured",
    "dashboard.reports_param_pool_ratio",
)


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# i18n — new keys present + localized in both locales
# ---------------------------------------------------------------------------


def test_new_flag_label_keys_present_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in _NEW_FLAG_LABEL_KEYS:
        for loc in ("en", "ja"):
            value = data[loc].get(key)
            assert value, f"{key} missing/empty in {loc}"
            assert value != key, f"{key} is an untranslated placeholder in {loc}"
        assert data["en"][key] != data["ja"][key], f"{key} not localized"


def test_param_label_keys_present_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    for key in _PARAM_LABEL_KEYS:
        for loc in ("en", "ja"):
            value = data[loc].get(key)
            assert value, f"{key} missing/empty in {loc}"


# ---------------------------------------------------------------------------
# dashboard.js — structured flag rendering
# ---------------------------------------------------------------------------


def test_object_flags_localized_by_code() -> None:
    """An object flag renders its label from ``dashboard.reports_flag_<code>``,
    not the raw slug — so it is coarse and localized."""
    js = _read("dashboard.js")
    assert "function humanizeReportFlag(" in js
    assert '"dashboard.reports_flag_" + ' in js
    assert "flag.code" in js


def test_custom_flag_label_is_locale_picked() -> None:
    """A ``custom`` flag carries an author label (string or {locale: text});
    the frontend picks the active locale via documentElement.lang."""
    js = _read("dashboard.js")
    assert "function pickLocalizedLabel(" in js
    assert "documentElement.lang" in js


def test_severity_maps_to_chip_class_including_info() -> None:
    """The four canonical severities map to chip classes, including the new
    neutral ``is-info`` bucket so info / positive flags are not styled as
    alarms."""
    js = _read("dashboard.js")
    assert "function reportFlagKind(" in js
    assert "flag.severity" in js
    assert '"is-info"' in js
    # The severity → chip mapping must cover all four buckets.
    for sev in ("action", "watch", "info", "positive"):
        assert sev in js, f"severity {sev} not referenced in dashboard.js"


def test_new_canonical_bases_registered() -> None:
    """The bare-string base map is aligned with the canonical vocabulary so a
    flag emitted as a plain code string still maps to its localized label."""
    js = _read("dashboard.js")
    for code in (
        "invalid_traffic_suspected",
        "budget_drift",
        "zero_cv_adspots",
        "goals_met",
        "anomaly_baseline_insufficient",
    ):
        assert code in js, f"canonical base {code} not in dashboard.js"


def test_flag_detail_drilldown_present() -> None:
    """Detail (adspot ids / yen / ctr) is rendered on a drill-down, never on
    the chip face: an interactive chip toggles a detail element built from
    ``params``, wired as an ARIA disclosure (aria-expanded + aria-controls)."""
    js = _read("dashboard.js")
    assert "function buildFlagDetail(" in js
    assert "function buildFlagChipElement(" in js
    assert '"dashboard.reports_param_" + ' in js
    assert "is-interactive" in js
    assert "report-flag-detail" in js
    assert 'setAttribute("aria-expanded"' in js
    assert 'setAttribute("aria-controls"' in js


def test_boolean_params_are_localized() -> None:
    """A boolean param (e.g. budget_drift's ``unlogged``) renders a localized
    yes/no, not raw English ``true`` / ``false`` in the Japanese UI."""
    js = _read("dashboard.js")
    assert 'typeof value === "boolean"' in js
    data = json.loads(_read("i18n.json"))
    for key in ("dashboard.reports_param_yes", "dashboard.reports_param_no"):
        for loc in ("en", "ja"):
            assert data[loc].get(key), f"{key} missing/empty in {loc}"


def test_severity_order_includes_info() -> None:
    """The client-card sort order ranks the new ``is-info`` bucket (below the
    coloured severities) so info flags do not jump above alarms."""
    js = _read("dashboard.js")
    assert "REPORTS_FLAG_SEVERITY_ORDER" in js
    order_line = next(
        line for line in js.splitlines() if "REPORTS_FLAG_SEVERITY_ORDER =" in line
    )
    assert "is-info" in order_line


# ---------------------------------------------------------------------------
# app.css — is-info chip + drill-down styling
# ---------------------------------------------------------------------------


def test_css_has_info_chip_and_detail_styles() -> None:
    css = _read("app.css")
    assert ".report-chip.is-info" in css
    assert ".report-chip.is-interactive" in css
    assert ".report-flag-detail" in css
