"""Static-content guards for the Guardrails card (#786, #790).

The card writes to the operator's STRATEGY.md, so the pieces that make it
reachable at all are pinned here: where it SITS (a sub-card of Advanced,
not a left-nav entry of its own), the controls the module addresses by
data attribute, the `<script>` tag in the one position that resolves
(after its dependency, before `dashboard.js`), the static allowlist entry
that makes the file servable, and EN/JA cover for every
`dashboard.guardrails_*` key the markup or the module asks for.

Since #790 two more things are static content: the card carries NO client
control of any kind, and it is delimited by the markers
`mureo/web/app_html.py` cuts it out on for a multi-client backend. Both
are pinned below — a lost marker would turn that omission into a silent
no-op and put a live, workspace-scoped write control on an agency
operator's screen.
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
            "data-guardrails-currency",
            "data-guardrails-save",
            "data-guardrails-result",
            "data-guardrails-path",
        ):
            assert attribute in html, f"{attribute} missing from app.html"

    def test_the_card_carries_no_client_control(self) -> None:
        """#790: one card, one file — the ACTIVE workspace's STRATEGY.md.

        Replaces the pins on the hidden client row. Per-client currency
        belongs on the multi-client layer's own client edit form; a picker
        here would read as "this setting has one value" while belonging to
        whichever client it happened to be on.
        """
        html = _read("app.html")
        assert "data-guardrails-client" not in html
        assert "dashboard-guardrails-client" not in html
        # The row's own `[hidden]` display rule went with it.
        assert "dashboard-guardrails-client" not in _read("app.css")

    def test_the_module_asks_for_no_roster_and_sends_no_client(self) -> None:
        js = _read("dashboard_guardrails.js")
        assert "/api/reports/clients" not in js
        assert "client=" not in js
        assert "data-guardrails-client" not in js


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

    def test_the_retired_client_picker_key_is_gone_from_both_locales(self) -> None:
        """The picker went with #790, and so does its label."""
        i18n = json.loads(_read("i18n.json"))
        for locale in ("en", "ja"):
            assert "dashboard.guardrails_client_label" not in i18n[locale]


@pytest.mark.unit
class TestGuardrailsCardOmission:
    """The markers a multi-client backend's copy of the page is cut on.

    The card is omitted SERVER-SIDE (#790) — see `mureo/web/app_html.py`
    for why — which makes these two comments in `app.html` load-bearing
    markup. Lose one and the strip either no-ops (a live control that
    writes the operator's ambient workspace lands on an agency screen) or
    eats the wrong span.
    """

    def test_the_markers_wrap_the_card_and_only_the_card(self) -> None:
        from mureo.web.app_html import GUARDRAILS_CARD_END, GUARDRAILS_CARD_START

        html = _read("app.html")
        start = html.index(GUARDRAILS_CARD_START)
        end = html.index(GUARDRAILS_CARD_END)
        assert start < html.index("data-dashboard-guardrails") < end
        assert html.index("data-dashboard-advisors") < start
        assert end < html.index('data-dashboard-group="demo"')

    def test_stripping_takes_the_whole_card_and_nothing_else(self) -> None:
        from mureo.web.app_html import strip_guardrails_card

        html = _read("app.html")
        stripped = strip_guardrails_card(html)
        for attribute in (
            "data-dashboard-guardrails",
            "data-guardrails-currency",
            "data-guardrails-save",
            "data-guardrails-result",
            "data-guardrails-path",
        ):
            assert attribute not in stripped
        # The cards either side of it, and the rest of the document, stay.
        assert "data-dashboard-advisors" in stripped
        assert 'data-dashboard-group="demo"' in stripped
        assert stripped.count("data-dashboard-nav") == html.count("data-dashboard-nav")

    def test_markers_that_are_not_there_are_an_error_not_a_no_op(self) -> None:
        """A silent no-op is the one outcome that must not happen: it ships
        the card to exactly the backend the omission exists for."""
        from mureo.web.app_html import AppHtmlError, strip_guardrails_card

        with pytest.raises(AppHtmlError) as excinfo:
            strip_guardrails_card("<html><body>no card here</body></html>")
        assert excinfo.value.code == "guardrails_card_markers_missing"

    def test_a_second_start_marker_is_refused_not_guessed_at(self) -> None:
        """Cutting to the FIRST end would swallow whatever sits between the
        two starts — a neighbouring card eaten as if it were this one."""
        from mureo.web.app_html import (
            GUARDRAILS_CARD_START,
            AppHtmlError,
            strip_guardrails_card,
        )

        doubled = _read("app.html").replace(
            GUARDRAILS_CARD_START,
            f"{GUARDRAILS_CARD_START}\n<div data-other-card></div>\n"
            f"{GUARDRAILS_CARD_START}",
            1,
        )
        with pytest.raises(AppHtmlError) as excinfo:
            strip_guardrails_card(doubled)
        assert excinfo.value.code == "guardrails_card_markers_ambiguous"

    def test_a_second_end_marker_is_refused_not_guessed_at(self) -> None:
        """Cutting to the first end would leave the stray end-marker comment
        behind in the document the operator is served."""
        from mureo.web.app_html import (
            GUARDRAILS_CARD_END,
            AppHtmlError,
            strip_guardrails_card,
        )

        doubled = _read("app.html").replace(
            GUARDRAILS_CARD_END,
            f"{GUARDRAILS_CARD_END}\n{GUARDRAILS_CARD_END}",
            1,
        )
        with pytest.raises(AppHtmlError) as excinfo:
            strip_guardrails_card(doubled)
        assert excinfo.value.code == "guardrails_card_markers_ambiguous"

    def test_markers_in_the_wrong_order_are_refused(self) -> None:
        from mureo.web.app_html import (
            GUARDRAILS_CARD_END,
            GUARDRAILS_CARD_START,
            AppHtmlError,
            strip_guardrails_card,
        )

        reversed_pair = f"<html>{GUARDRAILS_CARD_END}card{GUARDRAILS_CARD_START}</html>"
        with pytest.raises(AppHtmlError) as excinfo:
            strip_guardrails_card(reversed_pair)
        assert excinfo.value.code == "guardrails_card_markers_ambiguous"
