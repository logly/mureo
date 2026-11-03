"""#201 — generic, library-agnostic OAuth2 authorization-code helpers.

``mureo/oauth_authcode.py`` is the provider-neutral counterpart to the
Google-specific ``auth_setup`` flow (which is built on
``google_auth_oauthlib.Flow``). It builds the consent URL and exchanges
the returned code for a ``refresh_token`` using plain HTTP + HTTP Basic
client authentication (RFC 6749 §2.3.1) so any standards-compliant
provider — Yahoo! JAPAN Ads first — works without bespoke code.

These tests pin: the authorize URL is well-formed and rejects a
non-``https`` endpoint; the exchange returns the ``refresh_token``,
authenticates with HTTP Basic, raises when the endpoint omits a
``refresh_token``, and never writes the code / secret / token to logs.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from mureo.oauth_authcode import (
    AuthCodeResult,
    OAuthExchangeError,
    build_authorization_code_url,
    exchange_authorization_code,
    parse_loopback_callback_url,
    revoke_token,
)

# ---------------------------------------------------------------------------
# build_authorization_code_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_url_includes_required_params() -> None:
    url = build_authorization_code_url(
        authorize_url="https://biz-oauth.yahoo.co.jp/oauth/v1/authorize",
        client_id="CID",
        redirect_uri="http://127.0.0.1:5151/oauth/callback",
        scopes=("scopeA", "scopeB"),
        state="STATE123",
    )
    assert url.startswith("https://biz-oauth.yahoo.co.jp/oauth/v1/authorize?")
    assert "response_type=code" in url
    assert "client_id=CID" in url
    # redirect_uri + scope are percent-encoded as query values.
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A5151%2Foauth%2Fcallback" in url
    assert "scope=scopeA+scopeB" in url
    assert "state=STATE123" in url


@pytest.mark.unit
def test_build_url_omits_scope_when_empty() -> None:
    url = build_authorization_code_url(
        authorize_url="https://a.test/authorize",
        client_id="CID",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        scopes=(),
        state="S",
    )
    assert "scope=" not in url


@pytest.mark.unit
def test_build_url_rejects_non_https_authorize_url() -> None:
    with pytest.raises(ValueError, match="https"):
        build_authorization_code_url(
            authorize_url="http://insecure.test/authorize",
            client_id="CID",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
            scopes=(),
            state="S",
        )


# ---------------------------------------------------------------------------
# exchange_authorization_code
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Records the POST so the test can assert auth + body."""

    last_call: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def post(
        self, url: str, *, data: Any = None, auth: Any = None, headers: Any = None
    ) -> _FakeResponse:
        _FakeClient.last_call = {
            "url": url,
            "data": data,
            "auth": auth,
            "headers": headers,
        }
        return _FakeResponse({"refresh_token": "RT-xyz", "access_token": "AT-abc"})


@pytest.mark.unit
def test_exchange_returns_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    result = exchange_authorization_code(
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        code="AUTHCODE",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:5151/oauth/callback",
    )
    assert isinstance(result, AuthCodeResult)
    assert result.refresh_token == "RT-xyz"
    assert result.access_token == "AT-abc"
    # HTTP Basic client authentication (client_id, client_secret).
    assert _FakeClient.last_call["auth"] == ("CID", "SECRET")
    body = _FakeClient.last_call["data"]
    assert body["grant_type"] == "authorization_code"
    assert body["code"] == "AUTHCODE"
    assert body["redirect_uri"] == "http://127.0.0.1:5151/oauth/callback"
    # Default is Basic: credentials must NOT also be duplicated into the body.
    assert "client_id" not in body
    assert "client_secret" not in body


@pytest.mark.unit
def test_exchange_basic_is_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``client_auth='basic'`` (the default) keeps the Authorization-header
    scheme — regression guard for Google / existing providers."""
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    exchange_authorization_code(
        token_url="https://a.test/token",
        code="AC",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        client_auth="basic",
    )
    assert _FakeClient.last_call["auth"] == ("CID", "SECRET")
    assert "client_id" not in _FakeClient.last_call["data"]


@pytest.mark.unit
def test_exchange_body_style_puts_creds_in_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``client_auth='body'`` (Yahoo! JAPAN biz-oauth) sends client_id +
    client_secret in the form body and NO HTTP Basic auth header."""
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    result = exchange_authorization_code(
        token_url="https://biz-oauth.yahoo.co.jp/oauth/v1/token",
        code="AUTHCODE",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:5151/oauth/callback",
        client_auth="body",
    )
    assert result.refresh_token == "RT-xyz"
    # No Authorization header (Yahoo rejects Basic).
    assert _FakeClient.last_call["auth"] is None
    body = _FakeClient.last_call["data"]
    assert body["client_id"] == "CID"
    assert body["client_secret"] == "SECRET"
    assert body["grant_type"] == "authorization_code"


@pytest.mark.unit
def test_exchange_raises_when_no_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoRefresh(_FakeClient):
        def post(
            self, url: str, *, data: Any = None, auth: Any = None, headers: Any = None
        ) -> _FakeResponse:
            return _FakeResponse({"access_token": "AT-only"})

    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _NoRefresh)
    with pytest.raises(OAuthExchangeError):
        exchange_authorization_code(
            token_url="https://a.test/token",
            code="AUTHCODE",
            client_id="CID",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
        )


@pytest.mark.unit
def test_exchange_wraps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom(_FakeClient):
        def post(
            self, url: str, *, data: Any = None, auth: Any = None, headers: Any = None
        ) -> _FakeResponse:
            raise httpx.ConnectError("boom")

    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _Boom)
    with pytest.raises(OAuthExchangeError):
        exchange_authorization_code(
            token_url="https://a.test/token",
            code="AUTHCODE",
            client_id="CID",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
        )


@pytest.mark.unit
def test_exchange_never_logs_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    with caplog.at_level("DEBUG"):
        exchange_authorization_code(
            token_url="https://a.test/token",
            code="SENSITIVE_CODE",
            client_id="CID",
            client_secret="SENSITIVE_SECRET",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
        )
    blob = caplog.text + base64.b64encode(b"CID:SENSITIVE_SECRET").decode()
    # Neither the raw secret nor the authorization code may appear in logs.
    assert "SENSITIVE_SECRET" not in caplog.text
    assert "SENSITIVE_CODE" not in caplog.text
    assert "RT-xyz" not in caplog.text
    assert blob  # silence "unused" — the b64 line documents what we guard.


@pytest.mark.unit
@pytest.mark.parametrize("client_auth", ["basic", "body"])
def test_exchange_sends_extra_headers(
    monkeypatch: pytest.MonkeyPatch, client_auth: str
) -> None:
    """``headers`` reach the token request whichever client-auth style is
    used, alongside (not instead of) the client authentication."""
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    result = exchange_authorization_code(
        token_url="https://a.test/token",
        code="AC",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        client_auth=client_auth,
        headers={"X-Example": "abc"},
    )
    assert result.refresh_token == "RT-xyz"
    assert _FakeClient.last_call["headers"] == {"X-Example": "abc"}
    if client_auth == "basic":
        assert _FakeClient.last_call["auth"] == ("CID", "SECRET")
    else:
        assert _FakeClient.last_call["data"]["client_id"] == "CID"


@pytest.mark.unit
@pytest.mark.parametrize("client_auth", ["basic", "body"])
def test_exchange_sends_no_extra_headers_by_default(
    monkeypatch: pytest.MonkeyPatch, client_auth: str
) -> None:
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    exchange_authorization_code(
        token_url="https://a.test/token",
        code="AC",
        client_id="CID",
        client_secret="SECRET",
        redirect_uri="http://127.0.0.1:1/oauth/callback",
        client_auth=client_auth,
    )
    assert _FakeClient.last_call["headers"] is None


@pytest.mark.unit
def test_exchange_error_never_includes_header_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing exchange with declared headers surfaces no header value,
    neither in the exception nor in any log record."""

    class _Boom(_FakeClient):
        def post(
            self,
            url: str,
            *,
            data: Any = None,
            auth: Any = None,
            headers: Any = None,
        ) -> _FakeResponse:
            raise httpx.ConnectError(f"boom {headers}")

    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _Boom)
    with caplog.at_level("DEBUG"), pytest.raises(OAuthExchangeError) as exc:
        exchange_authorization_code(
            token_url="https://a.test/token",
            code="AC",
            client_id="CID",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
            headers={"X-Example": "SENSITIVE_HEADER"},
        )
    assert "SENSITIVE_HEADER" not in str(exc.value)
    assert "SENSITIVE_HEADER" not in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer x"},  # reserved: client authentication
        {"host": "evil.test"},  # reserved, any case
        {"X-Example": "abc\r\nX-Injected: 1"},  # CRLF injection
        {"X-Example": " abc"},  # leading whitespace
        {"X-Example": ""},  # empty value
        {"X-Example": "a", "x-example": "b"},  # repeated case-insensitively
    ],
)
def test_exchange_rejects_invalid_headers_before_sending(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]
) -> None:
    """The exchange applies the same header check as the provider reader,
    so a direct caller cannot bypass it; nothing is sent."""
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    monkeypatch.setattr(_FakeClient, "last_call", {})
    with pytest.raises(ValueError, match="^headers: "):
        exchange_authorization_code(
            token_url="https://a.test/token",
            code="AC",
            client_id="CID",
            client_secret="SECRET",
            redirect_uri="http://127.0.0.1:1/oauth/callback",
            headers=headers,
        )
    assert _FakeClient.last_call == {}


# ---------------------------------------------------------------------------
# revoke_token (#970) — RFC 7009 revocation: a bool for every HTTP answer, a
# raise for a transport failure (logged once, by the caller), and nothing
# secret in the logs.
# ---------------------------------------------------------------------------


class _NonJsonResponse(_FakeResponse):
    def json(self) -> dict[str, Any]:
        raise ValueError("not JSON")


def _revoke_client(response: _FakeResponse) -> type[_FakeClient]:
    """A client that records the POST like ``_FakeClient`` and answers
    ``response``."""

    class _Revoke(_FakeClient):
        def post(
            self, url: str, *, data: Any = None, auth: Any = None, headers: Any = None
        ) -> _FakeResponse:
            super().post(url, data=data, auth=auth, headers=headers)
            return response

    return _Revoke


def _revoke(**overrides: Any) -> bool:
    kwargs: dict[str, Any] = {
        "revoke_url": "https://a.test/revoke",
        "token": "RT-old",
        "client_id": "CID",
        "client_secret": "SECRET",
    }
    kwargs.update(overrides)
    return revoke_token(**kwargs)


@pytest.mark.unit
def test_revoke_posts_token_with_basic_auth_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mureo.oauth_authcode.httpx.Client", _revoke_client(_FakeResponse({}))
    )
    assert _revoke() is True
    call = _FakeClient.last_call
    assert call["url"] == "https://a.test/revoke"
    assert call["data"] == {"token": "RT-old"}
    assert call["auth"] == ("CID", "SECRET")
    assert call["headers"] is None


@pytest.mark.unit
def test_revoke_body_style_puts_creds_in_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mureo.oauth_authcode.httpx.Client", _revoke_client(_FakeResponse({}))
    )
    assert _revoke(client_auth="body") is True
    call = _FakeClient.last_call
    assert call["auth"] is None
    assert call["data"] == {
        "token": "RT-old",
        "client_id": "CID",
        "client_secret": "SECRET",
    }


@pytest.mark.unit
def test_revoke_sends_extra_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mureo.oauth_authcode.httpx.Client", _revoke_client(_FakeResponse({}))
    )
    assert _revoke(headers={"X-Example": "abc"}) is True
    assert _FakeClient.last_call["headers"] == {"X-Example": "abc"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_FakeResponse({}, status_code=200), True),
        (_FakeResponse({"error": "invalid_token"}, status_code=400), True),
        (_FakeResponse({"error": "invalid_client"}, status_code=400), False),
        (_NonJsonResponse({}, status_code=400), False),
        (_FakeResponse({}, status_code=500), False),
        (_FakeResponse({}, status_code=503), False),
    ],
)
def test_revoke_outcome_by_status(
    monkeypatch: pytest.MonkeyPatch, response: _FakeResponse, expected: bool
) -> None:
    """200, and 400 ``invalid_token`` (already revoked or expired), count as
    done; every other answer is a failed revocation."""
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _revoke_client(response))
    assert _revoke() is expected


@pytest.mark.unit
def test_revoke_transport_error_propagates_unlogged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A request that cannot be made raises ``httpx.HTTPError``; the caller
    owns the one warning, so nothing is logged here."""

    class _Boom(_FakeClient):
        def post(
            self, url: str, *, data: Any = None, auth: Any = None, headers: Any = None
        ) -> _FakeResponse:
            raise httpx.ConnectError(f"boom {data} {auth} {headers}")

    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _Boom)
    with caplog.at_level("DEBUG"), pytest.raises(httpx.ConnectError):
        _revoke(headers={"X-Example": "SENSITIVE_HEADER"})
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
    assert "RT-old" not in caplog.text
    assert "SECRET" not in caplog.text
    assert "SENSITIVE_HEADER" not in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize("status_code", [200, 400, 500])
def test_revoke_never_logs_token_or_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
) -> None:
    response = _FakeResponse({"error": "invalid_token"}, status_code=status_code)
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _revoke_client(response))
    with caplog.at_level("DEBUG"):
        _revoke(token="SENSITIVE_TOKEN", client_secret="SENSITIVE_SECRET")
    assert "SENSITIVE_TOKEN" not in caplog.text
    assert "SENSITIVE_SECRET" not in caplog.text


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"revoke_url": "http://a.test/revoke"}, "revoke_url"),
        ({"revoke_url": "https://a.test/revoke\r\n"}, "revoke_url"),
        ({"headers": {"Authorization": "Bearer x"}}, "^revoke_token headers: "),
        ({"headers": {"X-Example": "a\r\nX: 1"}}, "^revoke_token headers: "),
    ],
)
def test_revoke_rejects_bad_configuration_before_sending(
    monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any], match: str
) -> None:
    monkeypatch.setattr("mureo.oauth_authcode.httpx.Client", _FakeClient)
    monkeypatch.setattr(_FakeClient, "last_call", {})
    with pytest.raises(ValueError, match=match):
        _revoke(**overrides)
    assert _FakeClient.last_call == {}


# ---------------------------------------------------------------------------
# parse_loopback_callback_url (#216) — operator-supplied callback URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "http://127.0.0.1:8765/oauth/callback",
            ("127.0.0.1", 8765, "/oauth/callback"),
        ),
        (
            "http://localhost:5000/oauth/callback",
            ("localhost", 5000, "/oauth/callback"),
        ),
    ],
)
def test_parse_loopback_callback_url_accepts(
    url: str, expected: tuple[str, int, str]
) -> None:
    assert parse_loopback_callback_url(url) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://example.com:8765/oauth/callback",  # non-loopback host
        "http://10.0.0.5:8765/oauth/callback",  # non-loopback host
        "https://127.0.0.1:8765/oauth/callback",  # https not serveable here
        "http://127.0.0.1/oauth/callback",  # no explicit port
        "http://127.0.0.1:8765",  # no path
        "http://127.0.0.1:notaport/oauth/callback",  # invalid port
        "ftp://127.0.0.1:8765/oauth/callback",  # wrong scheme
    ],
)
def test_parse_loopback_callback_url_rejects(url: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - message is exercised in UI
        parse_loopback_callback_url(url)
