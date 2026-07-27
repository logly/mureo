"""Static-content guards for the manual Meta system-user token card (#458).

No JS test harness ships in the repo, so the ``auth_wizards.js`` contract
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
    js = _read("auth_wizards.js")
    assert "/api/credentials/meta/token" in js


@pytest.mark.unit
def test_card_uses_password_input_with_new_password_autocomplete() -> None:
    """The token field must not be a plain text box and must opt out of
    autofill (never-expiring secret)."""
    js = _read("auth_wizards.js")
    assert "new-password" in js
    # A password-typed input is used for the token entry.
    assert 'type = "password"' in js or 'type="password"' in js


@pytest.mark.unit
def test_card_sends_validate_only_probe_then_save() -> None:
    js = _read("auth_wizards.js")
    assert "validate_only" in js


@pytest.mark.unit
def test_card_data_i18n_keys_present_in_js() -> None:
    js = _read("auth_wizards.js")
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
        render = _render_probe_source(_read("auth_wizards.js"))
        assert (
            _PLACEHOLDER_KEY in render
        ), f"renderProbe must build a placeholder option from {_PLACEHOLDER_KEY}"

    def test_placeholder_carries_an_empty_value(self) -> None:
        """An empty value is what makes ``accountSelect.value || null`` post
        ``account_id: null`` when the placeholder is left selected."""
        render = _render_probe_source(_read("auth_wizards.js"))
        assert '.value = "";' in render, (
            "the placeholder option must have an empty value so saving "
            "without a choice posts account_id: null"
        )

    def test_placeholder_precedes_the_real_accounts(self) -> None:
        """Appended FIRST, so it is the default selection: a <select> with
        no explicit selection defaults to its first option."""
        render = _render_probe_source(_read("auth_wizards.js"))
        placeholder_at = render.index(_PLACEHOLDER_KEY)
        accounts_at = render.index("(body.accounts || []).forEach")
        assert placeholder_at < accounts_at, (
            "the placeholder option must be appended before the probed "
            "accounts, otherwise the first real account stays pre-selected"
        )

    def test_optional_helper_line_rendered_with_the_picker(self) -> None:
        js = _read("auth_wizards.js")
        assert _ACCOUNT_HINT_KEY in js
        # Rendered as a data-i18n node so the locale switcher re-translates it.
        assert f'"{_ACCOUNT_HINT_KEY}"' in js

    def test_save_still_maps_empty_selection_to_null(self) -> None:
        js = _read("auth_wizards.js")
        assert "account_id: accountSelect.value || null" in js


@pytest.mark.unit
def test_localhost_hint_shown_for_meta_only() -> None:
    """The pollOAuth timeout/failure branch surfaces the system-user-token
    hint for the meta provider (Google keeps the generic message)."""
    js = _read("auth_wizards.js")
    assert "meta_oauth_localhost_hint" in js
    # Guarded on the meta provider inside pollOAuth.
    assert 'provider === "meta"' in js
