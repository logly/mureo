"""ChatGPT Ads as a bundled registry provider (#993).

Pins the identifiers that end up in ``STATE.json`` history, the registration
contract shared with the other bundled providers (idempotent, first-wins,
switched off by ``MUREO_DISABLE_CHATGPT_ADS``), the credential card the
configure UI renders, the read-only classification of the nine read tools
(the mutations are pinned in ``test_chatgpt_ads_mutations.py``) and the
platform delivery model.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import warnings
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from mureo.chatgpt_ads import credentials as credentials_module
from mureo.chatgpt_ads.credentials import load_chatgpt_ads_credentials
from mureo.chatgpt_ads.handlers import ALL_TOOLS
from mureo.chatgpt_ads.provider import (
    CHATGPT_ADS_DISABLE_ENV_VAR,
    CHATGPT_ADS_PLATFORM_MODEL,
    CHATGPT_ADS_PROVIDER_NAME,
    CHATGPT_ADS_SOURCE_DISTRIBUTION,
    ChatGPTAdsProvider,
    chatgpt_ads_disabled,
    provider_entry,
    register_chatgpt_ads_provider,
)
from mureo.chatgpt_ads.tools import TOOLS
from mureo.core.platform_keys import plugin_platform_key
from mureo.core.providers import default_registry, get_account_credential_fields
from mureo.core.providers.registry import ProviderEntry, RegistryWarning
from mureo.core.secret_store import FilesystemSecretStore
from mureo.mcp.plugin_semantics import derive_semantics
from mureo.policy.platform_model import (
    MAX_STATEMENT_CHARS,
    models_in_scope,
    register_platform_model,
    reset_platform_models,
)
from mureo.web.plugin_credentials import (
    list_plugin_credential_fields,
    save_plugin_credentials,
)
from tests._runtime_context_fakes import MultiAccountStore, install_runtime_store
from tests.test_amazon_provider_registration import _isolated_registry  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

_TOOL_NAMES = (
    "chatgpt_ads_account_get",
    "chatgpt_ads_campaigns_list",
    "chatgpt_ads_campaigns_get",
    "chatgpt_ads_ad_groups_list",
    "chatgpt_ads_ad_groups_get",
    "chatgpt_ads_ads_list",
    "chatgpt_ads_ads_get",
    "chatgpt_ads_insights_report",
    "chatgpt_ads_change_history_list",
)


class TestIdentifiers:
    def test_names_that_reach_history(self) -> None:
        assert CHATGPT_ADS_PROVIDER_NAME == "chatgpt_ads"
        assert CHATGPT_ADS_SOURCE_DISTRIBUTION == "mureo-chatgpt-ads"
        assert CHATGPT_ADS_DISABLE_ENV_VAR == "MUREO_DISABLE_CHATGPT_ADS"
        assert (
            plugin_platform_key(
                CHATGPT_ADS_SOURCE_DISTRIBUTION, CHATGPT_ADS_PROVIDER_NAME
            )
            == "plugin:mureo-chatgpt-ads:chatgpt_ads"
        )

    def test_provider_class_attributes(self) -> None:
        assert ChatGPTAdsProvider.name == "chatgpt_ads"
        assert ChatGPTAdsProvider.display_name == "ChatGPT Ads"

    def test_no_identifier_names_the_vendor(self) -> None:
        names = [
            *_TOOL_NAMES,
            *(t.name for t in ALL_TOOLS),
            CHATGPT_ADS_PROVIDER_NAME,
            CHATGPT_ADS_DISABLE_ENV_VAR,
        ]
        assert not [n for n in names if "openai" in n.lower()]


class TestTools:
    def test_nine_tools_in_order(self) -> None:
        assert tuple(t.name for t in TOOLS) == _TOOL_NAMES

    def test_mcp_tools_needs_no_credentials_or_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise AssertionError("touched credentials")

        monkeypatch.setattr(credentials_module, "get_runtime_context", _boom)
        assert ChatGPTAdsProvider().mcp_tools() == ALL_TOOLS

    @pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
    def test_every_tool_is_read_only_with_a_closed_schema(self, tool) -> None:  # type: ignore[no-untyped-def]
        semantics = derive_semantics(tool)
        assert semantics.mutating is False
        assert semantics.read_only_hint is True
        assert semantics.throttle is not None
        assert (semantics.throttle.rate, semantics.throttle.burst) == (8.0, 5)
        assert tool.inputSchema["additionalProperties"] is False
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tool.name)

    def test_descriptions_state_units_and_freshness(self) -> None:
        by_name = {t.name: t for t in TOOLS}
        insights = by_name["chatgpt_ads_insights_report"].description or ""
        assert "major currency units" in insights
        assert "one-day" in insights or "one day" in insights
        assert "provisional" in insights
        campaigns = by_name["chatgpt_ads_campaigns_get"].description or ""
        assert "micros" in campaigns


class TestRegistration:
    def test_entry(self) -> None:
        entry = provider_entry()
        assert entry.name == "chatgpt_ads"
        assert entry.display_name == "ChatGPT Ads"
        assert entry.provider_class is ChatGPTAdsProvider
        assert entry.source_distribution == "mureo-chatgpt-ads"
        assert entry.capabilities == frozenset()

    @pytest.mark.usefixtures("_isolated_registry")
    def test_register_is_idempotent_and_silent(self) -> None:
        first = register_chatgpt_ads_provider()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            second = register_chatgpt_ads_provider()
        assert second is first
        assert default_registry.get("chatgpt_ads") is first
        assert not [w for w in captured if issubclass(w.category, RegistryWarning)]

    @pytest.mark.usefixtures("_isolated_registry")
    def test_a_prior_registration_wins(self) -> None:
        class _Other:
            name = "chatgpt_ads"

        squatter = ProviderEntry(
            name="chatgpt_ads",
            display_name="Other",
            capabilities=frozenset(),
            provider_class=_Other,
            source_distribution="third-party",
        )
        default_registry.register(squatter)
        assert register_chatgpt_ads_provider() is squatter

    def test_no_arg_construction(self) -> None:
        assert ChatGPTAdsProvider().mcp_tools()

    @pytest.mark.parametrize(
        ("value", "off"),
        [("1", True), ("0", False), ("", False), ("true", False), (" 1 ", False)],
    )
    def test_disable_switch_is_the_exact_string(
        self, monkeypatch: pytest.MonkeyPatch, value: str, off: bool
    ) -> None:
        monkeypatch.setenv("MUREO_DISABLE_CHATGPT_ADS", value)
        assert chatgpt_ads_disabled() is off


class TestCredentials:
    def test_one_secret_required_api_key_field(self) -> None:
        fields = get_account_credential_fields(ChatGPTAdsProvider)
        assert [(f.key, f.secret, f.required) for f in fields] == [
            ("api_key", True, True)
        ]
        field = fields[0]
        assert "Ads Manager" in field.description
        assert field.display_name_i18n["ja"]
        assert field.description_i18n["ja"]

    @pytest.mark.usefixtures("_isolated_registry")
    def test_configure_card_shows_a_secret_api_key(self) -> None:
        register_chatgpt_ads_provider()
        cards = [
            c
            for c in list_plugin_credential_fields()
            if c["provider_name"] == "chatgpt_ads"
        ]
        assert len(cards) == 1
        assert [(f["key"], f["secret"]) for f in cards[0]["fields"]] == [
            ("api_key", True)
        ]

    @pytest.mark.usefixtures("_isolated_registry")
    def test_saved_card_is_read_by_the_loader(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        register_chatgpt_ads_provider()
        store = FilesystemSecretStore(path=tmp_path / "store.json")
        save_plugin_credentials("chatgpt_ads", {"api_key": "k-1"}, secret_store=store)
        monkeypatch.setattr(
            credentials_module,
            "get_runtime_context",
            lambda: SimpleNamespace(secret_store=store),
        )
        monkeypatch.delenv("CHATGPT_ADS_API_KEY", raising=False)
        loaded = load_chatgpt_ads_credentials()
        assert loaded is not None and loaded.api_key == "k-1"

    def test_store_wins_over_env_and_blank_counts_as_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = FilesystemSecretStore(path=tmp_path / "store.json")
        monkeypatch.setattr(
            credentials_module,
            "get_runtime_context",
            lambda: SimpleNamespace(secret_store=store),
        )
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", "from-env")
        store.save("chatgpt_ads", {"api_key": "   "})
        assert load_chatgpt_ads_credentials().api_key == "from-env"  # type: ignore[union-attr]
        store.save("chatgpt_ads", {"api_key": "from-store"})
        assert load_chatgpt_ads_credentials().api_key == "from-store"  # type: ignore[union-attr]
        store.save("chatgpt_ads", {"api_key": 7})
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", " ")
        assert load_chatgpt_ads_credentials() is None

    def test_the_image_generation_key_is_never_read(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CHATGPT_ADS_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "image-key")
        assert load_chatgpt_ads_credentials() is None


class TestEnvironmentFallbackPerBackend:
    """``CHATGPT_ADS_API_KEY`` names one ad account (#1057)."""

    @staticmethod
    def _single_account_store(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> FilesystemSecretStore:
        """No factory registered (the root conftest hides installed ones)."""
        store = FilesystemSecretStore(path=tmp_path / "store.json")
        monkeypatch.setattr(
            credentials_module,
            "get_runtime_context",
            lambda: SimpleNamespace(secret_store=store),
        )
        return store

    def test_env_key_is_used_without_a_factory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._single_account_store(monkeypatch, tmp_path)
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", "from-env")
        loaded = load_chatgpt_ads_credentials()
        assert loaded is not None and loaded.api_key == "from-env"

    def test_env_key_is_not_read_for_a_multi_account_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install_runtime_store(monkeypatch, MultiAccountStore({}))
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", "another-account")
        assert load_chatgpt_ads_credentials() is None

    def test_the_store_section_is_used_without_a_factory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = self._single_account_store(monkeypatch, tmp_path)
        store.save("chatgpt_ads", {"api_key": "from-store"})
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", "from-env")
        loaded = load_chatgpt_ads_credentials()
        assert loaded is not None and loaded.api_key == "from-store"

    def test_the_store_section_is_used_for_a_multi_account_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = MultiAccountStore({"chatgpt_ads": {"api_key": "from-store"}})
        install_runtime_store(monkeypatch, store)
        monkeypatch.setenv("CHATGPT_ADS_API_KEY", "from-env")
        loaded = load_chatgpt_ads_credentials()
        assert loaded is not None and loaded.api_key == "from-store"


class TestPlatformModel:
    @pytest.fixture()
    def _models(self) -> Iterator[None]:
        reset_platform_models()
        yield
        reset_platform_models()

    @pytest.mark.usefixtures("_models")
    def test_model_registers_and_renders_only_for_its_own_tools(self) -> None:
        register_platform_model(CHATGPT_ADS_PLATFORM_MODEL)
        owned = {"chatgpt_ads_account_get": "chatgpt_ads"}
        assert models_in_scope(owned) == (CHATGPT_ADS_PLATFORM_MODEL,)
        assert models_in_scope({"chatgpt_ads_account_get": "someone_else"}) == ()

    def test_model_content(self) -> None:
        model = CHATGPT_ADS_PLATFORM_MODEL
        assert model.platform == "chatgpt_ads"
        assert model.tool_prefix == "chatgpt_ads_"
        assert len(model.statement) <= MAX_STATEMENT_CHARS
        assert model.evidence.source.startswith("https://developers.openai.com/ads/")
        for word in ("auction", "micros", "one day"):
            assert word in model.statement

    def test_importing_the_provider_registers_the_model(self) -> None:
        code = (
            "import json, mureo.chatgpt_ads.provider\n"
            "from mureo.policy.platform_model import platform_model\n"
            "print(json.dumps(platform_model('chatgpt_ads') is not None))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        assert json.loads(out.stdout.strip().splitlines()[-1]) is True
