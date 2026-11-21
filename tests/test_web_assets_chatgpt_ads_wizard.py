"""Static-content guards for ChatGPT Ads in the configure step wizard.

ChatGPT Ads is a bundled provider whose one credential is an API key, so the
wizard offers it on the platform step and collects the key through the same
declarative credential slot Amazon Ads uses. The field list comes from the
server; these guards pin the wiring and the EN/JA strings the slot looks up.
The slot's behavior is covered by the node tests under ``tests/js/``.
"""

from __future__ import annotations

import pytest

from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from tests.test_web_assets_amazon_ux import _load_i18n, _read

_KEYS = (
    "wizard.platforms.chatgpt_ads",
    "wizard.auth.chatgpt_ads_title",
    "wizard.auth.chatgpt_ads_desc",
)


@pytest.mark.unit
class TestWizardChatgptAdsPlatform:
    def test_chatgpt_ads_is_a_selectable_wizard_platform(self) -> None:
        js = _read("wizard.js")
        platforms = js.split("const PLATFORMS = [")[1].split("];")[0]
        assert '"chatgpt_ads"' in platforms
        assert "chatgpt_ads: false" in js

    def test_selecting_chatgpt_ads_queues_the_auth_step(self) -> None:
        js = _read("wizard.js")
        block = js.split("function hasAuthQueued()")[1].split("function ")[0]
        assert "STATE.platforms.chatgpt_ads" in block

    def test_auth_queue_queues_the_declarative_slot(self) -> None:
        js = _read("wizard_auth_queue.js")
        assert "state.platforms.chatgpt_ads" in js
        assert '{ key: "chatgpt_ads", pluginProvider: "chatgpt_ads" }' in js

    def test_wizard_does_not_hardcode_the_api_key_field(self) -> None:
        """The field comes from ``account_credential_fields`` through the
        plugin list endpoint, like Amazon's."""
        for name in ("wizard.js", "wizard_auth_queue.js", "wizard_plugin_slot.js"):
            assert "api_key" not in _read(name), f"api_key hand-copied into {name}"


@pytest.mark.unit
class TestChatgptAdsWizardI18n:
    def test_keys_present_and_nonempty_in_both_locales(self) -> None:
        data = _load_i18n()
        for locale in ("en", "ja"):
            block = data[locale]
            for key in _KEYS:
                assert key in block, f"{key} missing from i18n.json '{locale}'"
                assert (
                    isinstance(block[key], str) and block[key].strip()
                ), f"{key} empty in '{locale}'"

    def test_platform_label_is_the_provider_display_name(self) -> None:
        """The dashboard card shows the provider's ``display_name`` in both
        locales; the wizard's platform label matches it."""
        data = _load_i18n()
        for locale in ("en", "ja"):
            label = data[locale]["wizard.platforms.chatgpt_ads"]
            assert label == ChatGPTAdsProvider.display_name

    def test_prose_keys_are_distinct_translations(self) -> None:
        data = _load_i18n()
        for key in ("wizard.auth.chatgpt_ads_title", "wizard.auth.chatgpt_ads_desc"):
            assert data["en"][key] != data["ja"][key], f"{key} not localized"
