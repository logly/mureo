"""LwA access-token refresh (TDD, #113 Phase 2A).

Spec verified from official Amazon Ads docs (2026-05-19):
regional token hosts; POST grant_type=refresh_token; 400 invalid_grant
on a dead refresh token. Tokens must never appear in error text/logs.
"""

from __future__ import annotations

import pytest

from mureo.amazon_ads.lwa import (
    AmazonAuthError,
    LwaTokens,
    refresh_access_token,
    token_endpoint,
)
from mureo.auth import AmazonAdsCredentials


class _Resp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._p = payload

    def json(self) -> dict:
        return self._p


def _creds(**kw) -> AmazonAdsCredentials:
    base = {
        "client_id": "cid",
        "access_token": "Atza|OLD",
        "refresh_token": "Atzr|REFRESH",
        "client_secret": "lwa-secret",
    }
    base.update(kw)
    return AmazonAdsCredentials(**base)


@pytest.mark.unit
class TestTokenEndpoint:
    def test_regional_hosts(self) -> None:
        assert token_endpoint("na") == "https://api.amazon.com/auth/o2/token"
        assert token_endpoint("eu") == "https://api.amazon.co.uk/auth/o2/token"
        assert token_endpoint("fe") == "https://api.amazon.co.jp/auth/o2/token"

    def test_unknown_region_raises(self) -> None:
        with pytest.raises(ValueError):
            token_endpoint("zz")


@pytest.mark.unit
class TestRefreshAccessToken:
    def test_success_returns_new_tokens(self) -> None:
        captured: dict = {}

        def post(url, data):
            captured["url"] = url
            captured["data"] = data
            return _Resp(
                200,
                {
                    "access_token": "Atza|NEW",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "refresh_token": "Atzr|REFRESH",
                },
            )

        tok = refresh_access_token(_creds(region="eu"), http_post=post)
        assert isinstance(tok, LwaTokens)
        assert tok.access_token == "Atza|NEW"
        assert tok.refresh_token == "Atzr|REFRESH"
        assert tok.expires_in == 3600
        assert captured["url"] == "https://api.amazon.co.uk/auth/o2/token"
        assert captured["data"] == {
            "grant_type": "refresh_token",
            "refresh_token": "Atzr|REFRESH",
            "client_id": "cid",
            "client_secret": "lwa-secret",
        }

    def test_missing_refresh_token_raises_before_http(self) -> None:
        called = []
        with pytest.raises(AmazonAuthError, match="refresh"):
            refresh_access_token(
                _creds(refresh_token=None),
                http_post=lambda *a, **k: called.append(1),
            )
        assert called == []

    def test_missing_client_secret_raises_before_http(self) -> None:
        with pytest.raises(AmazonAuthError, match="client_secret"):
            refresh_access_token(
                _creds(client_secret=None), http_post=lambda *a, **k: None
            )

    def test_invalid_grant_raises_reauthorize(self) -> None:
        def post(url, data):
            return _Resp(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "User may have revoked...",
                },
            )

        with pytest.raises(AmazonAuthError, match="re-authorize|invalid_grant"):
            refresh_access_token(_creds(), http_post=post)

    def test_other_http_error_raises(self) -> None:
        def post(url, data):
            return _Resp(500, {"error": "server_error"})

        with pytest.raises(AmazonAuthError):
            refresh_access_token(_creds(), http_post=post)

    def test_tokens_not_leaked_in_error_text(self) -> None:
        def post(url, data):
            return _Resp(400, {"error": "invalid_grant"})

        try:
            refresh_access_token(_creds(), http_post=post)
        except AmazonAuthError as e:
            assert "Atzr|REFRESH" not in str(e)
            assert "lwa-secret" not in str(e)

    def test_network_failure_propagates_as_auth_error(self) -> None:
        def post(url, data):
            raise OSError("connection reset")

        with pytest.raises(AmazonAuthError):
            refresh_access_token(_creds(), http_post=post)
