"""Static-content guards for the Amazon Ads configure-UI parity work.

No JS test harness runs THIS code — ``node --test tests/js/`` covers only the DOM-free Reports logic extracted in #540, so the contract here is pinned by
grepping the bundled assets (the same convention as
``test_web_assets_plugin_credentials_render.py``):

- the dashboard's connected-platforms list carries an Amazon row driven
  by the existing ``credentials_present`` snapshot;
- the ``AMAZON_ADS_*`` names are filtered OUT of the generic advanced
  env list, exactly as the Creative Studio keys are, because Amazon has
  a first-class credential card;
- the Amazon card gets a manifest-refresh button, keyed off
  ``provider_name`` so no other plugin card grows one;
- the wizard offers Amazon as a selectable platform and collects its
  credentials from the SERVER-declared field list (no hand-copied field
  definitions in the JS).

EN/JA parity for every new i18n key is asserted here too.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

_WEB = Path(__file__).resolve().parent.parent / "mureo" / "_data" / "web"


def _read(name: str) -> str:
    return (_WEB / name).read_text(encoding="utf-8")


def _load_i18n() -> dict[str, Any]:
    ref = resources.files("mureo") / "_data" / "web" / "i18n.json"
    with resources.as_file(ref) as path:
        return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestDashboardAmazonRow:
    def test_native_sections_carry_an_amazon_row(self) -> None:
        js = _read("dashboard_workspace.js")
        assert '"amazon_ads"' in js
        assert "wizard.platforms.amazon_ads" in js
        # Driven by the existing status snapshot row, not a second probe.
        assert "present.amazon_ads" in js

    def test_amazon_env_names_are_excluded_from_the_generic_list(self) -> None:
        """Amazon has a first-class card — the generic advanced env list must
        not render a second, worse form for the same fields (the precedent
        Creative Studio set)."""
        js = _read("dashboard_setup.js")
        assert "AMAZON_ENV_NAMES" in js
        assert "!AMAZON_ENV_NAMES[name]" in js

    def test_amazon_env_names_cover_every_amazon_allow_list_entry(self) -> None:
        """The filter must list every allow-listed AMAZON_ADS_* name, or a
        stray field reappears in the generic list."""
        from mureo.web.env_var_writer import allowed_env_var_names

        js = _read("dashboard_setup.js")
        for name in allowed_env_var_names():
            if name.startswith("AMAZON_ADS_"):
                assert name in js, f"{name} missing from dashboard.js"

    def test_refresh_manifest_button_is_amazon_only(self) -> None:
        js = _read("dashboard_plugins.js")
        assert "/api/amazon/refresh-manifest" in js
        # Keyed off the provider name so no other plugin card grows a button.
        assert 'AMAZON_PROVIDER_NAME = "amazon_ads"' in js
        assert "plugin.provider_name === AMAZON_PROVIDER_NAME" in js
        assert "dashboard.amazon_refresh_manifest" in js
        # "Not configured yet" stays a distinct, actionable outcome.
        assert "amazon_credentials_missing" in js


@pytest.mark.unit
class TestWizardAmazonPlatform:
    def test_amazon_is_a_selectable_wizard_platform(self) -> None:
        js = _read("wizard.js")
        assert '"amazon_ads"' in js
        assert "amazon_ads: false" in js

    def test_amazon_credentials_come_from_the_server_declared_fields(self) -> None:
        """Single-sourced from ``account_credential_fields`` via the plugin
        list endpoint — a hand-copied field list in the JS would drift from
        the loader."""
        js = _read("auth_wizards.js")
        assert "/api/credentials/plugins" in js
        assert "pluginProvider" in js
        assert "/api/credentials/plugins/save" in js

    def test_wizard_does_not_hardcode_amazon_field_keys(self) -> None:
        js = _read("wizard.js") + _read("auth_wizards.js")
        for hardcoded in ("client_secret", "refresh_token", "manager_account_id"):
            assert hardcoded not in js, f"{hardcoded} hand-copied into the wizard JS"

    def test_amazon_configured_state_reads_the_status_snapshot(self) -> None:
        js = _read("wizard.js")
        assert "credentials_present" in js


@pytest.mark.unit
class TestAmazonAuthorizeControls:
    """The paste-code authorization flow (#121 phase B).

    Amazon's direct-advertiser consent has no loopback callback, so the
    UI walks the operator through opening consent and pasting the
    redirected address back. The controls are shared by the dashboard
    card and the wizard step, which is what these guards pin.
    """

    def test_shared_module_owns_the_endpoints(self) -> None:
        js = _read("amazon_oauth.js")
        assert "/api/amazon/oauth/authorize-url" in js
        assert "/api/amazon/oauth/exchange" in js
        assert "window.MUREO_AMAZON_OAUTH" in js
        assert "buildAuthorizeSection" in js
        assert "window.open(" in js

    def test_both_surfaces_reuse_the_shared_module(self) -> None:
        """No second copy of the flow: the dashboard card and the wizard
        step must both go through amazon_oauth.js."""
        for name in ("dashboard_plugins.js", "auth_wizards.js"):
            js = _read(name)
            assert "MUREO_AMAZON_OAUTH" in js, f"{name} does not reuse the module"
            assert "/api/amazon/oauth/" not in js, f"{name} re-implements the flow"

    def test_dashboard_authorize_stays_amazon_only(self) -> None:
        js = _read("dashboard_plugins.js")
        block = js.split("plugin.provider_name === AMAZON_PROVIDER_NAME")[1][:600]
        assert "buildAuthorizeSection" in block

    def test_module_is_served_and_loaded_before_its_consumers(self) -> None:
        from mureo.web.handlers import _STATIC_ALLOWLIST

        assert "amazon_oauth.js" in _STATIC_ALLOWLIST
        html = _read("app.html")
        position = html.index("/static/amazon_oauth.js")
        for consumer in ("/static/auth_wizards.js", "/static/dashboard.js"):
            assert position < html.index(consumer), f"{consumer} loads first"

    def test_dynamic_strings_go_through_textcontent(self) -> None:
        """Server detail / pasted input must never be interpolated as HTML."""
        js = _read("amazon_oauth.js")
        assert "innerHTML" not in js
        assert "insertAdjacentHTML" not in js

    def test_expiring_hint_reads_the_status_snapshot(self) -> None:
        js = _read("amazon_oauth.js")
        assert "amazon_token" in js
        assert "refresh_token_expiring" in js
        assert "dashboard.amazon_refresh_token_expiring" in js

    def test_expired_code_has_its_own_message(self) -> None:
        js = _read("amazon_oauth.js")
        assert "authorization_code_invalid" in js
        assert "dashboard.amazon_exchange_code_expired" in js

    def test_missing_credentials_stays_actionable(self) -> None:
        js = _read("amazon_oauth.js")
        assert "amazon_client_id_missing" in js
        assert "amazon_client_credentials_missing" in js


@pytest.mark.unit
class TestAmazonI18nParity:
    """Every new key must exist in BOTH locales, or the UI shows a bare key."""

    # Prose — must be genuinely translated.
    _KEYS = (
        "dashboard.amazon_refresh_manifest",
        "dashboard.amazon_refresh_manifest_hint",
        "dashboard.amazon_refresh_manifest_running",
        "dashboard.amazon_refresh_manifest_done",
        "dashboard.amazon_refresh_manifest_failed",
        "dashboard.amazon_refresh_manifest_no_credentials",
        "dashboard.amazon_authorize_title",
        "dashboard.amazon_authorize_hint",
        "dashboard.amazon_authorize_button",
        "dashboard.amazon_authorize_opening",
        "dashboard.amazon_authorize_failed",
        "dashboard.amazon_authorize_no_credentials",
        "dashboard.amazon_exchange_label",
        "dashboard.amazon_exchange_button",
        "dashboard.amazon_exchange_running",
        "dashboard.amazon_exchange_done",
        "dashboard.amazon_exchange_done_manifest_failed",
        "dashboard.amazon_exchange_code_expired",
        "dashboard.amazon_exchange_code_required",
        "dashboard.amazon_exchange_no_credentials",
        "dashboard.amazon_exchange_invalid_redirect",
        "dashboard.amazon_exchange_failed",
        "dashboard.amazon_refresh_token_expiring",
        "wizard.auth.amazon_saved_now_authorize",
        "wizard.auth.amazon_ads_title",
        "wizard.auth.amazon_ads_desc",
        "wizard.completed.pending_amazon",
    )

    # The platform label. No ``wizard.provider_banner.amazon_ads``
    # counterpart: Amazon has neither a provider_choice card nor a
    # providers_install slot (mureo brokers the official MCP itself), so a
    # banner key would be a dead string. The paste placeholder is an
    # example URL — identical in both locales on purpose.
    _PRESENCE_KEYS = (
        "wizard.platforms.amazon_ads",
        "dashboard.amazon_exchange_placeholder",
    )

    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in self._KEYS + self._PRESENCE_KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_prose_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in self._KEYS:
            assert data["en"][key] != data["ja"][key], f"{key} not localized"
