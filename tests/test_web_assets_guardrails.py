"""Static-content guards for the Guardrails card (#786).

The card writes to the operator's STRATEGY.md, so the pieces that make it
reachable at all are pinned here: where it SITS (a sub-card of Advanced,
not a left-nav entry of its own), the controls the module addresses by
data attribute, the `<script>` tag in the one position that resolves
(after its dependency, before `dashboard.js`), the static allowlist entry
that makes the file servable, and EN/JA cover for every
`dashboard.guardrails_*` key the markup or the module asks for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


@pytest.mark.unit
class TestGuardrailsMarkup:
    def test_it_is_a_sub_card_of_advanced_not_a_nav_entry_of_its_own(
        self,
    ) -> None:
        """One control does not earn a top-level menu item. It sits inside
        the Advanced section, after the External advisor MCP sub-card."""
        html = _read("app.html")
        start = html.index("data-dashboard-advanced")
        end = html.index('data-dashboard-group="demo"')
        assert start < html.index("data-dashboard-guardrails") < end
        assert html.index("data-dashboard-advisors") < html.index(
            "data-dashboard-guardrails"
        )

    def test_no_nav_item_or_group_of_its_own_remains(self) -> None:
        html = _read("app.html")
        assert 'data-dashboard-nav="guardrails"' not in html
        assert 'data-dashboard-group="guardrails"' not in html
        assert "nav_guardrails" not in html

    def test_the_card_keeps_its_own_heading(self) -> None:
        html = _read("app.html")
        assert 'data-i18n="dashboard.guardrails_title"' in html

    def test_the_card_has_the_controls_the_module_addresses(self) -> None:
        html = _read("app.html")
        for attribute in (
            "data-guardrails-client-row",
            "data-guardrails-client",
            "data-guardrails-currency",
            "data-guardrails-save",
            "data-guardrails-result",
            "data-guardrails-path",
        ):
            assert attribute in html, f"{attribute} missing from app.html"

    def test_the_hidden_client_row_is_actually_hidden(self) -> None:
        """`.dashboard-section label` sets an explicit `display`, which beats
        the UA `[hidden] { display: none }` — so the row needs its own rule
        or the single-workspace case ships an empty dropdown on screen."""
        css = _read("app.css")
        assert ".dashboard-guardrails-client[hidden]" in css
        assert "dashboard-guardrails-client" in _read("app.html")


@pytest.mark.unit
class TestGuardrailsAssetWiring:
    def test_the_script_tag_is_in_load_order(self) -> None:
        html = _read("app.html")
        assert html.index("dashboard_workspace.js") < html.index(
            "/static/dashboard_guardrails.js"
        )
        assert html.index("/static/dashboard_guardrails.js") < html.index(
            "/static/dashboard.js"
        )

    def test_the_file_is_served(self) -> None:
        from mureo.web.handlers import _STATIC_ALLOWLIST

        assert "dashboard_guardrails.js" in _STATIC_ALLOWLIST

    def test_the_module_publishes_one_global(self) -> None:
        js = _read("dashboard_guardrails.js")
        assert "window.MUREO_DASHBOARD_GUARDRAILS" in js
        assert "module.exports" in js

    def test_dashboard_js_binds_both_entry_points(self) -> None:
        js = _read("dashboard.js")
        assert "MUREO_DASHBOARD_GUARDRAILS" in js
        assert "renderGuardrails()" in js
        assert "wireGuardrails()" in js

    def test_the_harness_loads_it(self) -> None:
        harness = (Path(__file__).resolve().parent / "js" / "dom_harness.js").read_text(
            encoding="utf-8"
        )
        assert harness.index('"dashboard_workspace.js"') < harness.index(
            '"dashboard_guardrails.js"'
        )


_KEY_RE = re.compile(r"dashboard\.guardrails_[a-z_]+")


@pytest.mark.unit
class TestGuardrailsI18nParity:
    def _keys(self) -> set[str]:
        used = set(_KEY_RE.findall(_read("app.html")))
        used |= set(_KEY_RE.findall(_read("dashboard_guardrails.js")))
        return used

    def test_the_markup_and_the_module_use_keys_at_all(self) -> None:
        assert len(self._keys()) >= 10

    def test_every_key_is_translated_in_both_locales(self) -> None:
        i18n = json.loads(_read("i18n.json"))
        for locale in ("en", "ja"):
            for key in sorted(self._keys()):
                assert key in i18n[locale], f"{key} missing from i18n.json {locale!r}"
                assert str(i18n[locale][key]).strip() != ""

    def test_the_title_is_really_localised(self) -> None:
        i18n = json.loads(_read("i18n.json"))
        assert i18n["en"]["dashboard.guardrails_title"] != (
            i18n["ja"]["dashboard.guardrails_title"]
        )

    def test_the_retired_nav_key_is_gone_from_both_locales(self) -> None:
        """The card is a sub-card of Advanced now; a stale nav label would
        be a translated string nothing renders."""
        i18n = json.loads(_read("i18n.json"))
        assert "dashboard.nav_guardrails" not in i18n["en"]
        assert "dashboard.nav_guardrails" not in i18n["ja"]
