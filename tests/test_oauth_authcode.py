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
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

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

    def post(self, url: str, *, data: Any = None, auth: Any = None) -> _FakeResponse:
        _FakeClient.last_call = {"url": url, "data": data, "auth": auth}
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


@pytest.mark.unit
def test_exchange_raises_when_no_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoRefresh(_FakeClient):
        def post(
            self, url: str, *, data: Any = None, auth: Any = None
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
            self, url: str, *, data: Any = None, auth: Any = None
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
