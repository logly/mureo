"""The files in ``mureo/_data/web/`` that ``GET /static/<name>`` may serve.

``_STATIC_ALLOWLIST`` is the closed list of servable filenames (nothing
outside it is ever read from disk) and ``_STATIC_CONTENT_TYPES`` maps each
served suffix to its ``Content-Type``. :mod:`mureo.web.handlers` imports both
under these names.
"""

from __future__ import annotations

_STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

# Filenames inside ``mureo/_data/web/`` that may be served by GET /static/<name>.
_STATIC_ALLOWLIST: tuple[str, ...] = (
    "app.html",
    "app.css",
    "app.js",
    "landing.js",
    "wizard_provider_choice.js",
    "wizard.js",
    "amazon_oauth.js",
    "auth_wizards_meta.js",
    "auth_wizards_plugin.js",
    "auth_wizards.js",
    "reports_logic.js",
    "reports_format.js",
    "outcome_text.js",
    "reports_sparkline.js",
    "reports_display.js",
    "reports_chart.js",
    "reports_order.js",
    "reports_triage.js",
    "reports_overview.js",
    "reports_hero.js",
    "reports_index.js",
    "dashboard_setup.js",
    "dashboard_workspace.js",
    "dashboard_guardrails.js",
    "dashboard_ops_history.js",
    "dashboard_about.js",
    "dashboard_advisors.js",
    "dashboard_reports_state.js",
    "dashboard_reports_report.js",
    "dashboard_reports_changes.js",
    "dashboard_reports_chart.js",
    "dashboard_reports_detail.js",
    "dashboard_ops_history_detail.js",
    "dashboard_ops_history_section.js",
    "dashboard_reports_overview.js",
    "dashboard_reports_hero.js",
    "dashboard_reports_cards.js",
    "dashboard_reports_triage.js",
    "dashboard_reports_table.js",
    "dashboard_reports.js",
    "dashboard_creative.js",
    "dashboard_plugins.js",
    "dashboard.js",
    "extensions.js",
    "i18n.json",
    "logo.png",
    "logo-dark.png",
)
