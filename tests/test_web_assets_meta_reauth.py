"""Static-content guards for the Meta re-authentication control (#579).

No JS test harness runs THIS code — ``node --test tests/js/`` covers only
the DOM-free Reports logic extracted in #540 — so the contract is pinned
by grepping the bundled assets, the convention
``test_web_assets_amazon_ux.py`` set for the Amazon equivalent:

- the dashboard's Meta credential row carries a re-authenticate control
  and an expiry hint driven by the new ``meta_token`` status row, the way
  the Amazon plugin card carries its authorize section and hint;
- the control opens the existing system-user token card **directly**
  rather than routing through the wizard, which resets to step 0 and
  gates the Meta auth slot on state the dashboard never hydrates;
- an access token Meta rejects is reported in mureo's own words, with
  Graph's ``fbtrace_id`` body kept as secondary detail.

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


# Every key the re-authentication control and the reworded failure paths
# introduce; each must exist in BOTH locales.
_NEW_KEYS = (
    "dashboard.meta_access_token_expiring",
    "dashboard.meta_reauth_button",
    "wizard.auth.meta_token_invalid",
    "wizard.auth.meta_token_account_fetch_failed",
)


@pytest.mark.unit
class TestMetaRowCarriesTheControl:
    def test_dashboard_builds_the_meta_reauth_section(self) -> None:
        js = _read("dashboard_workspace.js")
        assert "MUREO_AUTH_META.buildMetaReauthSection" in js
        # Keyed off the Meta row so no other credential row grows one.
        assert 'row.key === "meta_ads"' in js

    def test_dashboard_renders_the_expiry_hint(self) -> None:
        js = _read("dashboard_workspace.js")
        assert "MUREO_AUTH_META.buildMetaExpiringHint" in js

    def test_saving_a_new_token_refreshes_the_dashboard(self) -> None:
        """The row must re-render after a save, or the operator is left
        looking at the warning that sent them there."""
        js = _read("dashboard_workspace.js")
        start = js.index("buildMetaReauthSection")
        block = js[start : start + 400]
        assert "MUREO.loadStatus()" in block
        assert "renderAll()" in block


@pytest.mark.unit
class TestReauthSectionOpensTheCardDirectly:
    def test_section_and_hint_are_exported(self) -> None:
        js = _read("auth_wizards_meta.js")
        assert "buildMetaReauthSection: buildMetaReauthSection" in js
        assert "buildMetaExpiringHint: buildMetaExpiringHint" in js

    def test_section_builds_the_existing_token_card(self) -> None:
        """Not a second paste form, and not a trip through the wizard."""
        js = _read("auth_wizards_meta.js")
        start = js.index("function buildMetaReauthSection(")
        end = js.index("function buildMetaExpiringHint(", start)
        block = js[start:end]
        assert "buildMetaTokenCard(" in block
        assert "dashboard.meta_reauth_button" in block
        # The wizard is not a route back here.
        assert "mureo:wizard_start" not in block
        assert "navigateToWizard" not in block

    def test_card_is_revealed_expanded(self) -> None:
        """The <details> summary is de-emphasized chrome — a card that
        opens collapsed hides the very form the button promised."""
        js = _read("auth_wizards_meta.js")
        start = js.index("function buildMetaReauthSection(")
        end = js.index("function buildMetaExpiringHint(", start)
        assert "open = true" in js[start:end]

    def test_hint_is_driven_by_the_meta_token_status_row(self) -> None:
        js = _read("auth_wizards_meta.js")
        start = js.index("function buildMetaExpiringHint(")
        block = js[start : start + 700]
        assert "status.meta_token" in block
        assert "access_token_expiring !== true" in block
        assert "access_token_age_days" in block
        assert "dashboard.meta_access_token_expiring" in block


@pytest.mark.unit
class TestFailuresAreReportedInMureosWords:
    def test_token_invalid_maps_to_a_mureo_authored_key(self) -> None:
        js = _read("auth_wizards_meta.js")
        assert 'token_invalid: "wizard.auth.meta_token_invalid"' in js
        assert (
            'account_fetch_failed: "wizard.auth.meta_token_account_fetch_failed"' in js
        )

    def test_graph_detail_is_no_longer_the_headline(self) -> None:
        """The old code put ``res.body.detail`` — an error 190 string with
        an fbtrace_id — straight into the status line and the toast."""
        js = _read("auth_wizards_meta.js")
        assert "const msg = (res.body && res.body.detail) ||" not in js

    def test_graph_detail_is_still_available_as_secondary_text(self) -> None:
        js = _read("auth_wizards_meta.js")
        start = js.index("function reportError(")
        block = js[start : start + 500]
        assert "res.body.detail" in block
        assert "MUREO.toast(msg" in block


@pytest.mark.unit
class TestI18nParity:
    def test_new_keys_exist_in_both_locales(self) -> None:
        data = _load_i18n()
        for key in _NEW_KEYS:
            for locale in ("en", "ja"):
                assert key in data[locale], f"{key} missing from '{locale}'"
                value = data[locale][key]
                assert isinstance(value, str)
                assert value.strip() != ""
                assert value != key

    def test_locales_stay_balanced(self) -> None:
        data = _load_i18n()
        assert set(data["en"]) == set(data["ja"])

    def test_expiry_string_names_platform_cause_and_action(self) -> None:
        """The Amazon string is the model: how old, why it matters, and
        the one thing to do about it."""
        data = _load_i18n()
        en = data["en"]["dashboard.meta_access_token_expiring"]
        assert "{days}" in en
        assert "Meta" in en
        assert "{days}" in data["ja"]["dashboard.meta_access_token_expiring"]

    def test_invalid_token_string_does_not_leak_graph_wording(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            value = data[locale]["wizard.auth.meta_token_invalid"]
            assert "fbtrace" not in value.lower()
