"""Static-content guards for the manual Meta system-user token card (#458).

No JS test harness runs THIS code — ``node --test tests/js/`` covers only the DOM-free Reports logic extracted in #540, so the ``auth_wizards.js`` contract
for the "paste a system-user token" card is pinned by grepping the bundled
asset. A refactor that drops the card, its Validate/Save wiring to
``/api/credentials/meta/token``, the account-picker, the localhost-OAuth
timeout hint, or any of the card's ``data-i18n`` keys flips a test red here
before an operator hits the regression in the configure UI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


# The auth wizards ship as two assets: ``auth_wizards_meta.js`` (the Meta
# connector card, method chooser and token card) is loaded before
# ``auth_wizards.js`` (queue + step wiring). Grep the pair as one source so
# the contracts below stay indifferent to which half holds them.
_AUTH_WIZARD_ASSETS = ("auth_wizards_meta.js", "auth_wizards.js")


def _read_auth_js() -> str:
    return "\n".join(_read(name) for name in _AUTH_WIZARD_ASSETS)


# data-i18n keys the card introduces; every one must exist in BOTH locales.
_CARD_KEYS = (
    "wizard.auth.meta_token_card_title",
    "wizard.auth.meta_token_card_intro",
    "wizard.auth.meta_token_label",
    "wizard.auth.meta_token_validate_button",
    "wizard.auth.meta_token_save_button",
    "wizard.auth.meta_token_account_label",
    "wizard.auth.meta_token_scopes_granted",
    "wizard.auth.meta_token_scopes_missing",
    "wizard.auth.meta_token_saved",
    "wizard.auth.meta_token_guide_1",
    "wizard.auth.meta_token_guide_2",
    "wizard.auth.meta_token_guide_3",
    "wizard.auth.meta_token_guide_4",
    "wizard.auth.meta_oauth_localhost_hint",
    # The account picker is OPTIONAL: a placeholder option is the default
    # selection and a helper line explains when to leave it unset.
    "wizard.auth.meta_token_account_placeholder",
    "wizard.auth.meta_token_account_hint",
)

_PLACEHOLDER_KEY = "wizard.auth.meta_token_account_placeholder"
_ACCOUNT_HINT_KEY = "wizard.auth.meta_token_account_hint"


def _render_probe_source(js: str) -> str:
    """Source of the ``renderProbe`` helper that fills the account picker."""
    start = js.index("function renderProbe(")
    end = js.index("validateBtn.addEventListener", start)
    return js[start:end]


@pytest.mark.unit
def test_card_posts_to_the_new_route() -> None:
    js = _read_auth_js()
    assert "/api/credentials/meta/token" in js


@pytest.mark.unit
def test_card_uses_password_input_with_new_password_autocomplete() -> None:
    """The token field must not be a plain text box and must opt out of
    autofill (never-expiring secret)."""
    js = _read_auth_js()
    assert "new-password" in js
    # A password-typed input is used for the token entry.
    assert 'type = "password"' in js or 'type="password"' in js


@pytest.mark.unit
def test_card_sends_validate_only_probe_then_save() -> None:
    js = _read_auth_js()
    assert "validate_only" in js


@pytest.mark.unit
def test_card_data_i18n_keys_present_in_js() -> None:
    js = _read_auth_js()
    for key in _CARD_KEYS:
        assert key in js, f"{key} missing from auth_wizards.js"


@pytest.mark.unit
def test_card_keys_exist_in_both_locales() -> None:
    data = json.loads(_read("i18n.json"))
    en, ja = data["en"], data["ja"]
    for key in _CARD_KEYS:
        assert key in en and en[key].strip(), f"{key} missing/empty in en"
        assert key in ja and ja[key].strip(), f"{key} missing/empty in ja"
        assert en[key] != ja[key], f"{key} not localized (en == ja)"


@pytest.mark.unit
class TestAccountPickerIsOptional:
    """The ad account is optional. Without a placeholder the browser silently
    pre-selects the first probed account, so Save persists an account the
    operator never chose — inert noise under mureo-agency (accounts are
    assigned per client in the Clients menu) and a silent-wrong-selection
    hazard in plain OSS. See ``tests/test_web_meta_token.py`` for the
    server-side half of the contract (``account_id: null`` -> saved, no key).
    """

    def test_placeholder_option_is_rendered(self) -> None:
        render = _render_probe_source(_read_auth_js())
        assert (
            _PLACEHOLDER_KEY in render
        ), f"renderProbe must build a placeholder option from {_PLACEHOLDER_KEY}"

    def test_placeholder_carries_an_empty_value(self) -> None:
        """An empty value is what makes ``accountSelect.value || null`` post
        ``account_id: null`` when the placeholder is left selected."""
        render = _render_probe_source(_read_auth_js())
        assert '.value = "";' in render, (
            "the placeholder option must have an empty value so saving "
            "without a choice posts account_id: null"
        )

    def test_placeholder_precedes_the_real_accounts(self) -> None:
        """Appended FIRST, so it is the default selection: a <select> with
        no explicit selection defaults to its first option."""
        render = _render_probe_source(_read_auth_js())
        placeholder_at = render.index(_PLACEHOLDER_KEY)
        accounts_at = render.index("(body.accounts || []).forEach")
        assert placeholder_at < accounts_at, (
            "the placeholder option must be appended before the probed "
            "accounts, otherwise the first real account stays pre-selected"
        )

    def test_optional_helper_line_rendered_with_the_picker(self) -> None:
        js = _read_auth_js()
        assert _ACCOUNT_HINT_KEY in js
        # Rendered as a data-i18n node so the locale switcher re-translates it.
        assert f'"{_ACCOUNT_HINT_KEY}"' in js

    def test_save_still_maps_empty_selection_to_null(self) -> None:
        js = _read_auth_js()
        assert "account_id: accountSelect.value || null" in js


@pytest.mark.unit
def test_localhost_hint_shown_for_meta_only() -> None:
    """The pollOAuth timeout/failure branch surfaces the system-user-token
    hint for the meta provider (Google keeps the generic message)."""
    js = _read_auth_js()
    assert "meta_oauth_localhost_hint" in js
    # Guarded on the meta provider inside pollOAuth.
    assert 'provider === "meta"' in js


@pytest.mark.unit
class TestLocalhostHintMatchesTheChooser:
    """The OAuth dead-end guidance names the chooser the operator can
    actually see. It used to say "the option below", which described the
    old collapsed-card layout; the token option now sits ABOVE the Facebook
    flow, inside the connection-method chooser."""

    def test_hint_points_at_the_option_above(self) -> None:
        data = json.loads(_read("i18n.json"))
        en = data["en"]["wizard.auth.meta_oauth_localhost_hint"]
        assert "above" in en.lower()
        assert "below" not in en.lower(), (
            "the token option is rendered above the Facebook flow now — "
            "'below' describes the pre-chooser layout"
        )

    def test_japanese_hint_points_upward_too(self) -> None:
        data = json.loads(_read("i18n.json"))
        ja = data["ja"]["wizard.auth.meta_oauth_localhost_hint"]
        assert "上" in ja
        assert "下" not in ja


@pytest.mark.unit
class TestDownstreamMarkupContract:
    """Hooks a downstream extension binds to. These are NOT free to move:
    the card is located by ``details.meta-token-card`` and its account row by
    the ``wizard.auth.meta_token_account`` key prefix, and the picker is
    hidden by walking from the ``<select>`` to its enclosing ``<label>``."""

    def test_card_is_still_a_details_element_with_the_pinned_class(self) -> None:
        js = _read_auth_js()
        assert 'createElement("details")' in js
        assert 'className = "meta-token-card"' in js

    def test_summary_toggle_element_is_retained(self) -> None:
        """De-emphasized visually once the token option is chosen, but the
        element (and its data-i18n key) must survive."""
        js = _read_auth_js()
        assert 'createElement("summary")' in js
        assert "wizard.auth.meta_token_card_title" in js

    def test_account_select_stays_inside_its_label(self) -> None:
        js = _read_auth_js()
        assert "accountLabel.appendChild(accountSelect)" in js

    def test_account_scoped_i18n_keys_are_all_still_present(self) -> None:
        js = _read_auth_js()
        for key in (
            "wizard.auth.meta_token_account_label",
            "wizard.auth.meta_token_account_hint",
            "wizard.auth.meta_token_account_placeholder",
        ):
            assert key in js, f"{key} dropped — downstream picker hook breaks"


@pytest.mark.unit
def test_card_is_expanded_when_the_token_method_is_chosen() -> None:
    """Choosing the token option must not leave the operator with a second
    collapsed disclosure to discover — the card opens with the choice."""
    js = _read_auth_js()
    assert "tokenCard.open = true;" in js
