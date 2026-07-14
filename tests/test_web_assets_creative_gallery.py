"""Static-content guards for the Creative Studio gallery tab (#409).

Pin the shape of the shipped web assets: the left-nav item, the group
shell containers the renderer populates, the dashboard.js wiring, and the
thumbnail-grid CSS. A refactor that drops any of these silently blanks
the gallery long before an operator notices.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
def test_creative_nav_item_ordered_after_reports() -> None:
    """Left-nav order must be Setup → Reports → Creative Studio → Advanced."""
    html = _read("app.html")
    assert 'data-dashboard-nav="creative"' in html
    assert 'data-i18n="dashboard.nav_creative"' in html
    reports_idx = html.index('data-dashboard-nav="reports"')
    creative_idx = html.index('data-dashboard-nav="creative"')
    advanced_idx = html.index('data-dashboard-nav="advanced"')
    assert reports_idx < creative_idx < advanced_idx


@pytest.mark.unit
def test_creative_section_shell_present() -> None:
    """The group + containers renderCreativeGallery() populates must exist."""
    html = _read("app.html")
    assert 'data-dashboard-group="creative"' in html
    assert "data-creative-clients" in html
    assert "data-creative-runs" in html
    assert "data-creative-empty" in html


@pytest.mark.unit
def test_creative_render_wired_in_dashboard_js() -> None:
    js = _read("dashboard.js")
    assert "function renderCreativeGallery(" in js
    assert "renderCreativeGallery()" in js  # wired into renderAll
    assert "/api/creative/runs" in js
    assert "/api/creative/clients" in js


@pytest.mark.unit
def test_creative_image_urls_are_encoded() -> None:
    """run/file/client ride in a query string — they must be URI-encoded so
    a hostile-looking name cannot break out of the query component."""
    js = _read("dashboard.js")
    assert "/api/creative/image?" in js
    start = js.index("/api/creative/image?")
    window = js[max(0, start - 400) : start + 400]
    assert "encodeURIComponent" in window


@pytest.mark.unit
def test_creative_grid_css_present() -> None:
    css = _read("app.css")
    assert ".creative-run-grid" in css
    assert ".creative-thumb" in css
