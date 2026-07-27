"""Static-content guards for the Meta connection-method chooser.

Field feedback: the Meta auth step used to render the prominent "Login with
Facebook" button with the system-user token card collapsed underneath, so
operators running a **Live** Meta app — for whom browser OAuth can never
succeed, Facebook rejects the localhost redirect — clicked the loud button
anyway and dead-ended. The two paths are mutually exclusive alternatives, so
the step now opens with an explicit either/or chooser and reveals **only**
the chosen flow.

No JS test harness ships in the repo, so the ``auth_wizards.js`` contract is
pinned by grepping the bundled asset: the chooser's ``data-i18n`` keys, its
radio semantics, its keyboard wiring, and — the actual bug fix — that
nothing is preselected and neither flow is visible until the operator picks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


# Every data-i18n key the chooser introduces. ADDITIVE only — no existing
# ``wizard.auth.meta_token_*`` key is renamed (downstream extensions bind to
# them; see tests/test_web_assets_meta_token_card.py).
_CHOOSER_KEYS = (
    "wizard.auth.meta_method_chooser_title",
    "wizard.auth.meta_method_chooser_subtitle",
    "wizard.auth.meta_method_recommended_badge",
    "wizard.auth.meta_method_token_title",
    "wizard.auth.meta_method_token_desc",
    "wizard.auth.meta_method_oauth_title",
    "wizard.auth.meta_method_oauth_desc",
)

_TOKEN_TITLE_KEY = "wizard.auth.meta_method_token_title"
_OAUTH_TITLE_KEY = "wizard.auth.meta_method_oauth_title"
_BADGE_KEY = "wizard.auth.meta_method_recommended_badge"


def _chooser_source(js: str) -> str:
    """Source of the chooser: its option table plus the builder helper.

    Scoped so the ordering assertions below mean "the order the operator
    sees", not "the order these strings happen to appear in the bundle".
    """
    start = js.index("const META_AUTH_METHODS = [")
    end = js.index("function buildMetaTokenCard(", start)
    return js[start:end]


@pytest.mark.unit
def test_chooser_helper_exists() -> None:
    js = _read("auth_wizards.js")
    assert "function buildMetaMethodChooser(" in js


@pytest.mark.unit
def test_option_card_construction_is_its_own_helper() -> None:
    """Card markup is built by a dedicated helper so the chooser body stays
    wiring-only (group + selection + keyboard) rather than growing past a
    readable length."""
    js = _read("auth_wizards.js")
    assert "function buildMethodOptionCard(" in js


@pytest.mark.unit
def test_chooser_data_i18n_keys_present_in_js() -> None:
    chooser = _chooser_source(_read("auth_wizards.js"))
    for key in _CHOOSER_KEYS:
        assert key in chooser, f"{key} missing from buildMetaMethodChooser"


@pytest.mark.unit
def test_chooser_keys_exist_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    en, ja = data["en"], data["ja"]
    for key in _CHOOSER_KEYS:
        assert key in en and en[key].strip(), f"{key} missing/empty in en"
        assert key in ja and ja[key].strip(), f"{key} missing/empty in ja"
        assert en[key] != ja[key], f"{key} not localized (en == ja)"


@pytest.mark.unit
class TestRadioSemantics:
    """Framework-free radio semantics — the chooser is a real radiogroup to
    assistive tech, not two divs that happen to look clickable."""

    def test_options_are_grouped_as_a_radiogroup(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert '"radiogroup"' in chooser

    def test_each_option_declares_the_radio_role(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert '"role", "radio"' in chooser

    def test_options_expose_aria_checked(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert "aria-checked" in chooser

    def test_options_are_focusable_and_key_operable(self) -> None:
        """Keyboard parity with a native radio group: the options are in the
        tab order and respond to keys (Space/Enter + arrows)."""
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert "tabIndex" in chooser
        assert '"keydown"' in chooser

    def test_home_and_end_jump_to_the_edges(self) -> None:
        """WAI-ARIA radiogroup pattern: Home/End select the first/last
        option, not just the arrow keys."""
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert '"Home"' in chooser
        assert '"End"' in chooser

    def test_clicking_an_option_also_focuses_it(self) -> None:
        """Safari does not focus a clicked ``tabindex`` div on its own, so
        without an explicit focus() the roving-tabindex "current" item lags
        the visible selection and the next arrow key jumps from the wrong
        place."""
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert "card.focus();" in chooser


@pytest.mark.unit
class TestNoDefaultSelection:
    """The mis-click fix: until the operator picks, neither flow is on
    screen, so there is no prominent-by-default button to click through."""

    def test_selection_starts_null(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert "let selectedMethod = null;" in chooser

    def test_no_option_is_checked_at_build_time(self) -> None:
        """Both options render ``aria-checked="false"``; nothing sets an
        option checked until a click/keypress handler runs."""
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert '"aria-checked", "false"' in chooser

    def test_both_panels_start_hidden(self) -> None:
        js = _read("auth_wizards.js")
        assert "tokenPanel.hidden = true;" in js
        assert "oauthPanel.hidden = true;" in js

    def test_choosing_swaps_which_panel_is_visible(self) -> None:
        """Idempotent either/or: a selection derives BOTH panels' visibility
        from the chosen method rather than only revealing one."""
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert 'tokenPanel.hidden = method !== "token";' in chooser
        assert 'oauthPanel.hidden = method !== "oauth";' in chooser


@pytest.mark.unit
class TestTokenOptionIsRecommendedAndFirst:
    """Live-mode apps are the common case in the field, so the token path
    leads and carries the Recommended badge."""

    def test_token_option_precedes_the_oauth_option(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert chooser.index(_TOKEN_TITLE_KEY) < chooser.index(_OAUTH_TITLE_KEY)

    def test_recommended_badge_belongs_to_the_token_option(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        assert chooser.index(_BADGE_KEY) < chooser.index(_OAUTH_TITLE_KEY)


@pytest.mark.unit
class TestChooserStyling:
    """Minimal, framework-free classes that exist in the bundled stylesheet
    (an unstyled chooser reads as two unrelated paragraphs)."""

    _CLASSES = (
        ".auth-method-chooser",
        ".auth-method-option",
        ".auth-method-option-badge",
    )

    def test_classes_are_applied_in_js(self) -> None:
        chooser = _chooser_source(_read("auth_wizards.js"))
        for cls in self._CLASSES:
            assert cls.lstrip(".") in chooser, f"{cls} not applied in JS"

    def test_classes_are_styled_in_app_css(self) -> None:
        css = _read("app.css")
        for cls in self._CLASSES:
            assert cls in css, f"{cls} missing from app.css"

    def test_selected_option_has_a_visual_state(self) -> None:
        css = _read("app.css")
        assert '.auth-method-option[aria-checked="true"]' in css
