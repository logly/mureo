"""``AccountOAuthConfig.callback_hint`` reaches the dashboard (#828).

The configure UI renders a hint under the OAuth callback URL input. The
generic text tells the operator to register that exact URL provider-side,
which is wrong for a brokered flow: there the authorization server
redirects to the broker's own registered callback, and the loopback URL is
only the second hop. A provider can therefore supply its own hint, or an
empty string to drop the hint row.

:func:`list_plugin_credential_fields` exposes the provider's choice as
``oauth.callback_hint``:

- unset (``None``) → key omitted, so the dashboard keeps the generic hint;
- ``""``           → ``""``, so the dashboard renders no hint row;
- any other string → that string, locale-resolved through
  ``callback_hint_i18n`` with the same chain as field labels.
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.core.providers import (
    AccountCredentialField,
    AccountOAuthConfig,
    default_registry,
)
from mureo.core.providers.registry import ProviderEntry
from mureo.web.plugin_credentials import list_plugin_credential_fields

_FIELDS = (
    AccountCredentialField(key="client_id", display_name="Client ID"),
    AccountCredentialField(
        key="client_secret", display_name="Client Secret", secret=True
    ),
    AccountCredentialField(
        key="refresh_token", display_name="Refresh Token", secret=True
    ),
)

_BROKERED_HINT = (
    "The broker handles the provider-side redirect. Nothing to register; "
    "click Authenticate."
)


def _oauth(**overrides: Any) -> AccountOAuthConfig:
    return AccountOAuthConfig(
        authorize_url="https://broker.example.test/authorize",
        token_url="https://broker.example.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        **overrides,
    )


def _register(monkeypatch: pytest.MonkeyPatch, oauth: AccountOAuthConfig) -> None:
    class _Fake:
        name = "example_ads"
        display_name = "Example Ads"
        capabilities: frozenset[str] = frozenset()
        account_credential_fields = _FIELDS
        account_oauth = oauth

    entry = ProviderEntry(
        name="example_ads",
        display_name="Example Ads",
        capabilities=frozenset(),
        provider_class=_Fake,
        source_distribution=None,
    )
    monkeypatch.setattr(default_registry, "_entries", {"example_ads": entry})


def _oauth_block(monkeypatch: pytest.MonkeyPatch, locale: str = "en", **kw: Any) -> Any:
    _register(monkeypatch, _oauth(**kw))
    [plugin] = list_plugin_credential_fields(locale)
    return plugin["oauth"]


@pytest.mark.unit
def test_config_defaults_leave_the_hint_unset() -> None:
    config = _oauth()
    assert config.callback_hint is None
    assert dict(config.callback_hint_i18n) == {}


@pytest.mark.unit
def test_block_omits_callback_hint_when_provider_sets_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(monkeypatch)
    assert "callback_hint" not in block
    # The original three keys are untouched.
    assert block == {
        "target_field": "refresh_token",
        "client_id_field": "client_id",
        "client_secret_field": "client_secret",
    }


@pytest.mark.unit
def test_block_carries_the_provider_hint_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(monkeypatch, callback_hint=_BROKERED_HINT)
    assert block["callback_hint"] == _BROKERED_HINT


@pytest.mark.unit
def test_block_carries_an_empty_hint_as_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(monkeypatch, callback_hint="")
    assert block["callback_hint"] == ""


@pytest.mark.unit
def test_empty_hint_suppresses_even_with_translations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``""`` is a decision to drop the row; a translation must not revive it."""
    block = _oauth_block(
        monkeypatch, "ja", callback_hint="", callback_hint_i18n={"ja": "X"}
    )
    assert block["callback_hint"] == ""


@pytest.mark.unit
def test_hint_resolves_the_active_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    block = _oauth_block(
        monkeypatch,
        "ja",
        callback_hint=_BROKERED_HINT,
        callback_hint_i18n={"ja": "JA hint"},
    )
    assert block["callback_hint"] == "JA hint"


@pytest.mark.unit
def test_hint_falls_back_to_en_then_the_bare_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(
        monkeypatch,
        "fr",
        callback_hint=_BROKERED_HINT,
        callback_hint_i18n={"en": "EN hint"},
    )
    assert block["callback_hint"] == "EN hint"
    block = _oauth_block(
        monkeypatch,
        "fr",
        callback_hint=_BROKERED_HINT,
        callback_hint_i18n={"ja": "JA hint"},
    )
    assert block["callback_hint"] == _BROKERED_HINT


@pytest.mark.unit
def test_translations_without_a_base_hint_keep_the_generic_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``callback_hint`` is the switch; ``callback_hint_i18n`` only localises it."""
    block = _oauth_block(monkeypatch, "ja", callback_hint_i18n={"ja": "JA hint"})
    assert "callback_hint" not in block


@pytest.mark.unit
def test_non_string_hint_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mistyped declaration falls back to the generic hint, not a 500."""
    block = _oauth_block(monkeypatch, callback_hint=42)
    assert "callback_hint" not in block


@pytest.mark.unit
def test_non_mapping_translations_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(
        monkeypatch, "ja", callback_hint=_BROKERED_HINT, callback_hint_i18n=["ja"]
    )
    assert block["callback_hint"] == _BROKERED_HINT


@pytest.mark.unit
def test_non_string_translation_value_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block = _oauth_block(
        monkeypatch,
        "ja",
        callback_hint=_BROKERED_HINT,
        callback_hint_i18n={"ja": 7},
    )
    assert block["callback_hint"] == _BROKERED_HINT
