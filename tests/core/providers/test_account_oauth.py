"""#201 — declarative per-account OAuth metadata for plugin providers.

A provider that supports the OAuth2 authorization-code grant declares an
:class:`AccountOAuthConfig` on the class (alongside its
``account_credential_fields``). The configure-UI generic OAuth wizard
reads it to drive a consent flow that obtains a ``refresh_token`` and
saves it to the named ``target_field`` — no plugin-specific code in OSS.

The declaration is metadata only; these tests pin the dataclass shape and
the defensive reader (``get_account_oauth_config``) that mirrors
``get_account_credential_fields``: absent attribute → ``None``, a
mis-typed attribute → ``TypeError``, and a field reference that does not
name a declared ``account_credential_fields`` key → ``ValueError`` (a
plugin wiring typo must fail loudly at the boundary, not silently produce
a dead "Authenticate" button).
"""

from __future__ import annotations

import pytest

from mureo.core.providers import (
    AccountCredentialField,
    AccountOAuthConfig,
    get_account_oauth_config,
)

# ---------------------------------------------------------------------------
# Representative provider stubs
# ---------------------------------------------------------------------------

_CLIENT_ID = AccountCredentialField(key="client_id", display_name="Client ID")
_CLIENT_SECRET = AccountCredentialField(
    key="client_secret", display_name="Client Secret", secret=True
)
_REFRESH = AccountCredentialField(
    key="refresh_token", display_name="Refresh Token", secret=True
)

_OAUTH = AccountOAuthConfig(
    authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
    token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
    client_id_field="client_id",
    client_secret_field="client_secret",
    target_field="refresh_token",
    scopes=("https://example.test/scope",),
)


class _OAuthProvider:
    name = "yahoo_ads"
    account_credential_fields = (_CLIENT_ID, _CLIENT_SECRET, _REFRESH)
    account_oauth = _OAUTH


class _PlainProvider:
    name = "demo_ads"
    account_credential_fields = (_CLIENT_ID,)
    # No account_oauth — manual entry only (the pre-#201 status quo).


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_defaults() -> None:
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
    )
    assert cfg.scopes == ()
    assert cfg.callback_path == "/oauth/callback"


@pytest.mark.unit
def test_config_is_frozen() -> None:
    with pytest.raises(Exception):  # noqa: B017 - FrozenInstanceError is fine
        _OAUTH.token_url = "https://evil.test/token"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_reader_returns_declared_config() -> None:
    assert get_account_oauth_config(_OAuthProvider()) is _OAUTH


@pytest.mark.unit
def test_reader_absent_attribute_returns_none() -> None:
    assert get_account_oauth_config(_PlainProvider()) is None


@pytest.mark.unit
def test_reader_wrong_type_raises_typeerror() -> None:
    class _Bad:
        name = "bad"
        account_credential_fields = (_CLIENT_ID,)
        account_oauth = {"authorize_url": "x"}  # dict, not AccountOAuthConfig

    with pytest.raises(TypeError):
        get_account_oauth_config(_Bad())


@pytest.mark.unit
def test_reader_unknown_field_reference_raises_valueerror() -> None:
    """A target_field that names no declared credential field is a plugin
    wiring typo — fail loudly so the UI never shows a dead button."""

    class _Typo:
        name = "typo"
        account_credential_fields = (_CLIENT_ID, _CLIENT_SECRET)
        account_oauth = AccountOAuthConfig(
            authorize_url="https://a.test/authorize",
            token_url="https://a.test/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",  # not in account_credential_fields
        )

    with pytest.raises(ValueError, match="refresh_token"):
        get_account_oauth_config(_Typo())
