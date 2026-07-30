"""Amazon Ads bridge as a registry provider (TDD, #121 gap 3 phase A).

Amazon must be set-up-able from the configure web UI, which renders a
generic form for every ``default_registry`` provider declaring
``account_credential_fields``. That requires two things this module
pins:

1. ``AmazonAdsBridge`` declares every key
   :func:`mureo.auth.load_amazon_ads_credentials` reads, with the
   secret ones flagged ``secret=True``.
2. A single-sourced synthetic ``ProviderEntry`` is registered into
   ``default_registry`` — idempotently, so the MCP startup path and the
   configure-UI discovery path can both call it.

Round-trip: what the configure UI saves through
``save_plugin_credentials`` must be a section the loader accepts.
"""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING

import pytest

from mureo.amazon_ads.bridge import AmazonAdsBridge
from mureo.amazon_ads.provider import (
    AMAZON_SOURCE_DISTRIBUTION,
    provider_entry,
    register_amazon_provider,
)
from mureo.auth import load_amazon_ads_credentials
from mureo.core.providers import default_registry, get_account_credential_fields
from mureo.core.providers.registry import ProviderEntry, RegistryWarning
from mureo.core.secret_store import FilesystemSecretStore
from mureo.web.plugin_credentials import (
    list_plugin_credential_fields,
    save_plugin_credentials,
)

if TYPE_CHECKING:
    from pathlib import Path

#: Every key ``load_amazon_ads_credentials`` consumes from the section.
_LOADER_KEYS = (
    "client_id",
    "access_token",
    "refresh_token",
    "client_secret",
    "region",
    "account_mode",
    "profile_id",
    "account_id",
    "manager_account_id",
)

#: Keys carrying credential material — never a plain-text input.
_SECRET_KEYS = frozenset({"client_secret", "refresh_token", "access_token"})


@pytest.fixture()
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test a private ``default_registry`` entry map."""
    monkeypatch.setattr(default_registry, "_entries", {})


@pytest.mark.unit
class TestAccountCredentialFields:
    def test_declares_every_key_the_loader_reads(self) -> None:
        fields = get_account_credential_fields(AmazonAdsBridge)
        assert tuple(f.key for f in fields) == _LOADER_KEYS

    def test_secret_material_is_flagged_secret(self) -> None:
        fields = get_account_credential_fields(AmazonAdsBridge)
        secret = {f.key for f in fields if f.secret}
        assert secret == _SECRET_KEYS

    def test_client_id_is_the_only_required_field(self) -> None:
        fields = get_account_credential_fields(AmazonAdsBridge)
        assert [f.key for f in fields if f.required] == ["client_id"]

    def test_region_and_account_mode_placeholders_list_the_options(self) -> None:
        by_key = {f.key: f for f in get_account_credential_fields(AmazonAdsBridge)}
        assert by_key["region"].placeholder == "na | eu | fe"
        assert by_key["account_mode"].placeholder == "dynamic | fixed"

    def test_every_field_ships_en_and_ja_copy(self) -> None:
        for field in get_account_credential_fields(AmazonAdsBridge):
            assert set(field.display_name_i18n) >= {"en", "ja"}, field.key
            assert set(field.description_i18n) >= {"en", "ja"}, field.key

    def test_access_token_description_says_it_is_optional(self) -> None:
        by_key = {f.key: f for f in get_account_credential_fields(AmazonAdsBridge)}
        access = by_key["access_token"]
        assert access.required is False
        assert "refresh_token" in access.description
        assert "client_secret" in access.description

    def test_heading_has_a_japanese_translation(self) -> None:
        assert AmazonAdsBridge.display_name_i18n["ja"]
        assert AmazonAdsBridge.display_name_i18n["en"] == "Amazon Ads"


@pytest.mark.unit
class TestProviderEntry:
    def test_entry_identifies_the_bridge(self) -> None:
        entry = provider_entry()
        assert isinstance(entry, ProviderEntry)
        assert entry.name == "amazon_ads"
        assert entry.display_name == "Amazon Ads"
        assert entry.provider_class is AmazonAdsBridge
        assert entry.source_distribution == AMAZON_SOURCE_DISTRIBUTION
        assert entry.capabilities == frozenset()

    def test_source_distribution_matches_the_audit_trail_name(self) -> None:
        # ``plugin:mureo-amazon-ads-bridge`` is already written into
        # STATE.json action_log entries; renaming it would orphan history.
        assert AMAZON_SOURCE_DISTRIBUTION == "mureo-amazon-ads-bridge"

    def test_register_inserts_into_the_default_registry(
        self, _isolated_registry: None
    ) -> None:
        assert "amazon_ads" not in default_registry
        entry = register_amazon_provider()
        assert "amazon_ads" in default_registry
        assert default_registry.get("amazon_ads") is entry

    def test_repeat_registration_is_a_silent_no_op(
        self, _isolated_registry: None
    ) -> None:
        first = register_amazon_provider()
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            second = register_amazon_provider()
        assert second is first
        assert len(default_registry) == 1
        assert not [w for w in captured if issubclass(w.category, RegistryWarning)]

    def test_a_prior_third_party_registration_wins(
        self, _isolated_registry: None
    ) -> None:
        """First-wins: an already-registered ``amazon_ads`` is not replaced."""

        class _Other:
            name = "amazon_ads"
            display_name = "Someone Else"
            capabilities = frozenset()

        squatter = ProviderEntry(
            name="amazon_ads",
            display_name="Someone Else",
            capabilities=frozenset(),
            provider_class=_Other,
            source_distribution="third-party",
        )
        default_registry.register(squatter)
        assert register_amazon_provider() is squatter


@pytest.mark.unit
class TestConfigureServerDiscovery:
    def test_configure_discovery_registers_amazon(
        self, _isolated_registry: None
    ) -> None:
        """``mureo configure`` startup must populate the Amazon card.

        The bridge is in-tree (no ``mureo.providers`` entry point), so
        entry-point discovery alone leaves the registry without it and
        the configure UI shows no Amazon section.
        """
        from mureo.web.server import ConfigureWizard

        ConfigureWizard._discover_providers_safely()
        assert "amazon_ads" in default_registry

    def test_configure_discovery_registers_amazon_even_if_plugins_fail(
        self, _isolated_registry: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.web.server import ConfigureWizard

        def _boom(*_a: object, **_kw: object) -> None:
            raise RuntimeError("entry_points exploded")

        # ``_discover_providers_safely`` resolves ``discover_providers``
        # through the module globals at call time, so patching the name
        # on the module intercepts it.
        monkeypatch.setattr("mureo.web.server.discover_providers", _boom)
        ConfigureWizard._discover_providers_safely()
        assert "amazon_ads" in default_registry


@pytest.mark.unit
class TestConfigureUiListing:
    def test_amazon_card_is_listed_with_the_loader_keys(
        self, _isolated_registry: None
    ) -> None:
        register_amazon_provider()
        cards = list_plugin_credential_fields()
        amazon = [c for c in cards if c["provider_name"] == "amazon_ads"]
        assert len(amazon) == 1
        card = amazon[0]
        assert card["display_name"] == "Amazon Ads"
        assert tuple(f["key"] for f in card["fields"]) == _LOADER_KEYS
        assert {f["key"] for f in card["fields"] if f["secret"]} == _SECRET_KEYS

    def test_japanese_locale_resolves_the_heading_and_labels(
        self, _isolated_registry: None
    ) -> None:
        register_amazon_provider()
        card = next(
            c
            for c in list_plugin_credential_fields("ja")
            if c["provider_name"] == "amazon_ads"
        )
        assert card["display_name"] == AmazonAdsBridge.display_name_i18n["ja"]
        labels = {f["key"]: f["display_name"] for f in card["fields"]}
        assert labels["client_id"] != "Client ID"  # translated, not the fallback

    def test_listing_never_leaks_a_stored_secret_value(
        self, _isolated_registry: None, tmp_path: Path
    ) -> None:
        register_amazon_provider()
        creds = tmp_path / "credentials.json"
        creds.write_text(
            json.dumps(
                {
                    "amazon_ads": {
                        "client_id": "amzn1.application-oa2-client.x",
                        "client_secret": "LEAK-SECRET",
                        "refresh_token": "LEAK-REFRESH",
                        "access_token": "LEAK-ACCESS",
                    }
                }
            ),
            encoding="utf-8",
        )
        payload = json.dumps(list_plugin_credential_fields())
        for leaked in ("LEAK-SECRET", "LEAK-REFRESH", "LEAK-ACCESS"):
            assert leaked not in payload


@pytest.mark.unit
class TestSaveRoundTrip:
    def test_saved_form_is_loadable_by_the_credential_loader(
        self, _isolated_registry: None, tmp_path: Path
    ) -> None:
        register_amazon_provider()
        creds = tmp_path / "credentials.json"
        store = FilesystemSecretStore(path=creds)

        save_plugin_credentials(
            "amazon_ads",
            {
                "client_id": "amzn1.application-oa2-client.x",
                "client_secret": "lwa-secret",
                "refresh_token": "Atzr|R",
                "access_token": "",
                "region": "eu",
                "account_mode": "fixed",
                "profile_id": "111",
                "account_id": "222",
                "manager_account_id": "333",
            },
            secret_store=store,
        )

        loaded = load_amazon_ads_credentials(path=creds)
        assert loaded is not None
        assert loaded.client_id == "amzn1.application-oa2-client.x"
        assert loaded.client_secret == "lwa-secret"
        assert loaded.refresh_token == "Atzr|R"
        assert loaded.access_token == ""  # minted on first use
        assert loaded.region == "eu"
        assert loaded.account_mode == "fixed"
        assert loaded.profile_id == "111"
        assert loaded.account_id == "222"
        assert loaded.manager_account_id == "333"

    def test_minimal_save_with_access_token_only_is_loadable(
        self, _isolated_registry: None, tmp_path: Path
    ) -> None:
        register_amazon_provider()
        creds = tmp_path / "credentials.json"
        save_plugin_credentials(
            "amazon_ads",
            {"client_id": "cid", "access_token": "Atza|T"},
            secret_store=FilesystemSecretStore(path=creds),
        )
        loaded = load_amazon_ads_credentials(path=creds)
        assert loaded is not None
        assert loaded.access_token == "Atza|T"
        assert loaded.region == "na"
        assert loaded.account_mode == "dynamic"

    def test_blank_secret_keeps_the_stored_value(
        self, _isolated_registry: None, tmp_path: Path
    ) -> None:
        register_amazon_provider()
        creds = tmp_path / "credentials.json"
        store = FilesystemSecretStore(path=creds)
        save_plugin_credentials(
            "amazon_ads",
            {"client_id": "cid", "refresh_token": "Atzr|R", "client_secret": "sec"},
            secret_store=store,
        )
        save_plugin_credentials(
            "amazon_ads",
            {"client_id": "cid", "refresh_token": "", "client_secret": ""},
            secret_store=store,
        )
        loaded = load_amazon_ads_credentials(path=creds)
        assert loaded is not None
        assert loaded.refresh_token == "Atzr|R"
        assert loaded.client_secret == "sec"
