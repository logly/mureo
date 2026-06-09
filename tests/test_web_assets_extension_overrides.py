"""Static-content guards for the #189 surface-override wiring in
``extensions.js``.

The renderer-side half of #189 lives in a bundled JS asset with no
build step, so these tests pin the load-bearing strings the same way
``test_web_assets_dashboard_cards_and_toasts.py`` pins the #183/#184
fixes — a refactor that silently drops the override plumbing flips a
test red here long before an operator notices built-in tabs
reappearing next to a full-surface plugin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _js() -> str:
    return (_WEB / "extensions.js").read_text(encoding="utf-8")


@pytest.mark.unit
def test_extensions_js_reads_hidden_builtin_tabs() -> None:
    """The renderer must consume the ``hidden_builtin_tabs`` wire key."""
    assert "hidden_builtin_tabs" in _js()


@pytest.mark.unit
def test_extensions_js_reads_replaces_landing() -> None:
    """The renderer must consume the ``replaces_landing`` wire key and
    target the built-in landing section."""
    js = _js()
    assert "replaces_landing" in js
    assert "[data-landing]" in js


@pytest.mark.unit
def test_extensions_js_has_builtin_tab_allowlist() -> None:
    """Client-side allowlist mirrors BUILTIN_DASHBOARD_TABS so a
    malformed payload cannot hide arbitrary nodes."""
    js = _js()
    for key in ("setup", "demo", "byod", "danger"):
        assert f'"{key}"' in js


@pytest.mark.unit
def test_extensions_js_inits_on_app_ready() -> None:
    """Discovery must run at app boot (``mureo:ready``), not only on
    first dashboard show — otherwise ``replaces_landing`` can never
    take effect on first load."""
    assert "mureo:ready" in _js()


@pytest.mark.unit
def test_extensions_js_prefers_landing_replacer_for_default_selection() -> None:
    """When a hidden tab was the default selection, the landing-owning
    extension must win over an arbitrary first-rendered extension —
    review finding on #189: ``replacer || _extensions[0]``."""
    assert "replacer || _extensions[0]" in _js()
