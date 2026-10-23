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
_ACCOUNT = AccountCredentialField(key="account_id", display_name="Account")

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
    # #220 — no fixed port by default (loopback uses an ephemeral port /
    # the operator-supplied callback URL, #216). Backward compatible.
    assert cfg.callback_port is None
    # Token-endpoint client auth defaults to HTTP Basic (Google et al.).
    assert cfg.token_auth_style == "basic"


@pytest.mark.unit
def test_config_accepts_body_token_auth_style() -> None:
    """A provider whose token endpoint rejects HTTP Basic (Yahoo! JAPAN
    biz-oauth) declares ``token_auth_style="body"`` so the client id/secret
    travel in the form body instead of the Authorization header."""
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        token_auth_style="body",
    )
    assert cfg.token_auth_style == "body"


@pytest.mark.unit
def test_config_accepts_fixed_callback_port() -> None:
    """#220 — a provider that requires an exact redirect_uri (Yahoo! JAPAN)
    declares the canonical loopback port; the configure UI pre-fills the
    callback URL from it so the operator registers the right value."""
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        callback_port=8765,
    )
    assert cfg.callback_port == 8765
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


# ---------------------------------------------------------------------------
# #336 — accounts_field validation + get_oauth_account_lister hook discovery.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_config_accounts_field_defaults_none() -> None:
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
    )
    assert cfg.accounts_field is None


@pytest.mark.unit
def test_reader_accepts_valid_accounts_field() -> None:
    class _Picker:
        name = "broker"
        account_credential_fields = (_CLIENT_ID, _CLIENT_SECRET, _REFRESH, _ACCOUNT)
        account_oauth = AccountOAuthConfig(
            authorize_url="https://a.test/authorize",
            token_url="https://a.test/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            accounts_field="account_id",
        )

    cfg = get_account_oauth_config(_Picker())
    assert cfg is not None and cfg.accounts_field == "account_id"


@pytest.mark.unit
def test_reader_unknown_accounts_field_raises_valueerror() -> None:
    """A typo'd accounts_field would silently disable the picker (#336) and
    the multi-account hide (#337) — fail loudly at the boundary instead."""

    class _Typo:
        name = "typo"
        account_credential_fields = (_CLIENT_ID, _CLIENT_SECRET, _REFRESH)
        account_oauth = AccountOAuthConfig(
            authorize_url="https://a.test/authorize",
            token_url="https://a.test/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            accounts_field="account_id",  # not declared
        )

    with pytest.raises(ValueError, match="accounts_field"):
        get_account_oauth_config(_Typo())


@pytest.mark.unit
def test_get_oauth_account_lister_returns_callable() -> None:
    from mureo.core.providers import get_oauth_account_lister

    class _WithHook:
        name = "broker"

        @staticmethod
        def list_oauth_accounts(creds: dict[str, str]) -> list[dict[str, str]]:
            return [{"id": "act_1"}]

    hook = get_oauth_account_lister(_WithHook())
    assert callable(hook)
    assert hook({}) == [{"id": "act_1"}]


@pytest.mark.unit
def test_get_oauth_account_lister_absent_returns_none() -> None:
    from mureo.core.providers import get_oauth_account_lister

    assert get_oauth_account_lister(_PlainProvider()) is None


@pytest.mark.unit
def test_get_oauth_account_lister_non_callable_returns_none() -> None:
    from mureo.core.providers import get_oauth_account_lister

    class _Bad:
        name = "bad"
        list_oauth_accounts = "not callable"

    assert get_oauth_account_lister(_Bad()) is None


# ---------------------------------------------------------------------------
# token_headers — extra HTTP headers for token requests, validated by the
# reader so a malformed declaration fails at the boundary, not mid-exchange.
# ---------------------------------------------------------------------------


def _headers_provider(token_headers: object) -> object:
    class _Headers:
        name = "broker"
        account_credential_fields = (_CLIENT_ID, _CLIENT_SECRET, _REFRESH)
        account_oauth = AccountOAuthConfig(
            authorize_url="https://a.test/authorize",
            token_url="https://a.test/token",
            client_id_field="client_id",
            client_secret_field="client_secret",
            target_field="refresh_token",
            token_headers=token_headers,  # type: ignore[arg-type]
        )

    return _Headers()


@pytest.mark.unit
def test_config_token_headers_defaults_empty() -> None:
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
    )
    assert cfg.token_headers == ()


@pytest.mark.unit
def test_reader_accepts_valid_token_headers() -> None:
    headers = (("X-Example", "abc"), ("X-Other.Name_2", "v a l u e"))
    cfg = get_account_oauth_config(_headers_provider(headers))
    assert cfg is not None and cfg.token_headers == headers


@pytest.mark.unit
@pytest.mark.parametrize(
    "headers",
    [
        [("X-Example", "abc")],  # list, not tuple
        ("X-Example", "abc"),  # a bare pair, not a tuple of pairs
        (("X-Example",),),  # one-element entry
        (("X-Example", "abc", "extra"),),  # three-element entry
        (("X-Example", 1),),  # non-str value
        ((b"X-Example", "abc"),),  # non-str name
    ],
)
def test_reader_rejects_mis_typed_token_headers(headers: object) -> None:
    with pytest.raises(TypeError, match="token_headers"):
        get_account_oauth_config(_headers_provider(headers))


@pytest.mark.unit
@pytest.mark.parametrize(
    "headers",
    [
        (("", "abc"),),  # empty name
        (("X-Example", ""),),  # empty value
        (("X Example", "abc"),),  # space is not a token character
        (("X-Example:", "abc"),),  # colon is not a token character
        (("X-Exämple", "abc"),),  # non-ASCII name
        (("X-Example", "abc\r\nX-Injected: 1"),),  # CRLF header injection
        (("X-Example", "abc\ndef"),),  # bare LF
        (("X-Example", "abc\rdef"),),  # bare CR
    ],
)
def test_reader_rejects_invalid_token_headers(headers: object) -> None:
    with pytest.raises(ValueError, match="token_headers"):
        get_account_oauth_config(_headers_provider(headers))


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "Host",
        "Content-Type",
        "content-length",  # case-insensitive
        "TRANSFER-ENCODING",
        "Connection",
        "Cookie",
    ],
)
def test_reader_rejects_reserved_token_header_names(name: str) -> None:
    """Headers the token request sets itself would replace or be dropped in
    favour of the request's own; declaring one fails at the boundary."""
    with pytest.raises(ValueError, match="is set by the token request itself"):
        get_account_oauth_config(_headers_provider(((name, "abc"),)))


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        "",  # empty
        " abc",  # leading space
        "abc ",  # trailing space
        "a\tb",  # tab
        "a\x00b",  # NUL
        "caf\u00e9",  # non-ASCII
    ],
)
def test_reader_rejects_non_visible_ascii_token_header_values(value: str) -> None:
    with pytest.raises(ValueError, match="must be non-empty visible ASCII"):
        get_account_oauth_config(_headers_provider((("X-Example", value),)))


@pytest.mark.unit
def test_reader_rejects_repeated_token_header_names() -> None:
    with pytest.raises(ValueError, match="declared more than once"):
        get_account_oauth_config(
            _headers_provider((("X-Example", "a"), ("x-example", "b")))
        )


@pytest.mark.unit
def test_token_headers_hidden_from_repr() -> None:
    cfg = AccountOAuthConfig(
        authorize_url="https://a.test/authorize",
        token_url="https://a.test/token",
        client_id_field="client_id",
        client_secret_field="client_secret",
        target_field="refresh_token",
        token_headers=(("X-Example", "SENSITIVE"),),
    )
    assert "SENSITIVE" not in repr(cfg)


@pytest.mark.unit
def test_reader_invalid_token_header_message_omits_value() -> None:
    """Header values may be identifiers a broker relies on; the error names
    the offending header, never its value."""
    with pytest.raises(ValueError) as exc:
        get_account_oauth_config(
            _headers_provider((("X-Example", "SENSITIVE\r\nX: 1"),))
        )
    assert "X-Example" in str(exc.value)
    assert "SENSITIVE" not in str(exc.value)
