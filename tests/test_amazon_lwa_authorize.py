"""LwA authorization-code flow (TDD, #121 setup-UX phase B).

Spec verified from the official Amazon Ads authorization docs
(2026-07-31):

- Regional authorize URL prefixes:
    NA https://www.amazon.com/ap/oa
    EU https://eu.account.amazon.com/ap/oa
    FE https://apac.account.amazon.com/ap/oa
  Query: ``client_id`` + ``scope=advertising::campaign_management`` +
  ``response_type=code`` + ``redirect_uri`` (which must be listed in the
  LwA security profile's Allowed Return URLs).
- Token exchange: POST form ``grant_type=authorization_code`` + ``code``
  + ``redirect_uri`` + ``client_id`` + ``client_secret`` to the SAME
  regional token host the refresh flow uses.
- Authorization codes expire 5 minutes after consent, so a dead code is
  a distinct, actionable outcome rather than a generic failure.

Tokens / secrets must never reach exception text.
"""

from __future__ import annotations

import urllib.parse

import pytest

from mureo.amazon_ads.lwa import (
    ADVERTISING_SCOPE,
    DEFAULT_REDIRECT_URI,
    AmazonAuthCodeError,
    AmazonAuthError,
    LwaTokens,
    authorize_endpoint,
    build_authorization_url,
    exchange_authorization_code,
    normalize_region,
)


class _Resp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._p = payload

    def json(self) -> dict:
        return self._p


def _query(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(url)
    return {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}


@pytest.mark.unit
class TestAuthorizeEndpoint:
    def test_regional_hosts(self) -> None:
        assert authorize_endpoint("na") == "https://www.amazon.com/ap/oa"
        assert authorize_endpoint("eu") == "https://eu.account.amazon.com/ap/oa"
        assert authorize_endpoint("fe") == "https://apac.account.amazon.com/ap/oa"

    def test_unknown_region_raises(self) -> None:
        """Same contract as ``endpoints.endpoint_url`` / ``token_endpoint``:
        an unknown region is a programming error, not a silent default."""
        with pytest.raises(ValueError):
            authorize_endpoint("zz")


@pytest.mark.unit
class TestNormalizeRegion:
    def test_known_regions_pass_through(self) -> None:
        for region in ("na", "eu", "fe"):
            assert normalize_region(region) == region

    def test_case_and_whitespace_are_tolerated(self) -> None:
        assert normalize_region(" EU ") == "eu"

    def test_unknown_and_absent_default_to_na(self) -> None:
        assert normalize_region("zz") == "na"
        assert normalize_region(None) == "na"
        assert normalize_region("") == "na"


@pytest.mark.unit
class TestBuildAuthorizationUrl:
    def test_url_carries_the_documented_query(self) -> None:
        url = build_authorization_url(
            client_id="amzn1.application-oa2-client.abc",
            region="na",
            redirect_uri=DEFAULT_REDIRECT_URI,
        )
        assert url.startswith("https://www.amazon.com/ap/oa?")
        assert _query(url) == {
            "client_id": "amzn1.application-oa2-client.abc",
            "scope": ADVERTISING_SCOPE,
            "response_type": "code",
            "redirect_uri": DEFAULT_REDIRECT_URI,
        }

    def test_scope_is_the_campaign_management_scope(self) -> None:
        assert ADVERTISING_SCOPE == "advertising::campaign_management"

    def test_region_selects_the_prefix(self) -> None:
        for region, prefix in (
            ("eu", "https://eu.account.amazon.com/ap/oa?"),
            ("fe", "https://apac.account.amazon.com/ap/oa?"),
        ):
            url = build_authorization_url(
                client_id="cid", region=region, redirect_uri="https://amazon.com"
            )
            assert url.startswith(prefix)

    def test_redirect_uri_is_percent_encoded(self) -> None:
        url = build_authorization_url(
            client_id="cid",
            region="na",
            redirect_uri="https://example.com/cb?x=1 2",
        )
        assert "https://example.com/cb?x=1 2" not in url
        assert _query(url)["redirect_uri"] == "https://example.com/cb?x=1 2"

    def test_default_redirect_uri_is_the_documented_pattern(self) -> None:
        assert DEFAULT_REDIRECT_URI == "https://amazon.com"

    def test_blank_client_id_is_refused(self) -> None:
        with pytest.raises(ValueError):
            build_authorization_url(
                client_id="  ", region="na", redirect_uri=DEFAULT_REDIRECT_URI
            )

    def test_blank_redirect_uri_is_refused(self) -> None:
        with pytest.raises(ValueError):
            build_authorization_url(client_id="cid", region="na", redirect_uri="")


@pytest.mark.unit
class TestExchangeAuthorizationCode:
    def test_success_returns_both_tokens(self) -> None:
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
                    "refresh_token": "Atzr|NEW",
                },
            )

        tokens = exchange_authorization_code(
            code="ANtoken",
            redirect_uri="https://amazon.com",
            client_id="cid",
            client_secret="lwa-secret",
            region="eu",
            http_post=post,
        )

        assert isinstance(tokens, LwaTokens)
        assert tokens.access_token == "Atza|NEW"
        assert tokens.refresh_token == "Atzr|NEW"
        assert tokens.expires_in == 3600
        # Same regional token host the refresh flow posts to.
        assert captured["url"] == "https://api.amazon.co.uk/auth/o2/token"
        assert captured["data"] == {
            "grant_type": "authorization_code",
            "code": "ANtoken",
            "redirect_uri": "https://amazon.com",
            "client_id": "cid",
            "client_secret": "lwa-secret",
        }

    def test_missing_code_raises_before_http(self) -> None:
        called: list[int] = []
        with pytest.raises(AmazonAuthError, match="code"):
            exchange_authorization_code(
                code="   ",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=lambda *a, **k: called.append(1),
            )
        assert called == []

    def test_missing_client_secret_raises_before_http(self) -> None:
        called: list[int] = []
        with pytest.raises(AmazonAuthError, match="client_secret"):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="",
                region="na",
                http_post=lambda *a, **k: called.append(1),
            )
        assert called == []

    def test_missing_client_id_raises_before_http(self) -> None:
        with pytest.raises(AmazonAuthError, match="client_id"):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="",
                client_secret="secret",
                region="na",
                http_post=lambda *a, **k: None,
            )

    def test_expired_code_is_its_own_error_with_the_5_minute_hint(self) -> None:
        """Amazon answers a stale/reused code with 400 invalid_grant. The
        overwhelmingly likely cause is the 5-minute code lifetime, so it must
        be a distinct type the UI can turn into an actionable hint."""

        def post(url, data):
            return _Resp(
                400,
                {
                    "error": "invalid_grant",
                    "error_description": "The authorization code is invalid",
                },
            )

        with pytest.raises(AmazonAuthCodeError) as exc:
            exchange_authorization_code(
                code="ANstale",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )
        assert "5 minutes" in str(exc.value)
        # Still an AmazonAuthError for callers that only know the base type.
        assert isinstance(exc.value, AmazonAuthError)

    def test_invalid_request_on_the_code_is_also_a_code_error(self) -> None:
        def post(url, data):
            return _Resp(
                400,
                {
                    "error": "invalid_request",
                    "error_description": "invalid parameter value for code",
                },
            )

        with pytest.raises(AmazonAuthCodeError):
            exchange_authorization_code(
                code="ANstale",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )

    def test_other_http_error_is_a_plain_auth_error(self) -> None:
        def post(url, data):
            return _Resp(500, {"error": "server_error"})

        with pytest.raises(AmazonAuthError) as exc:
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )
        assert not isinstance(exc.value, AmazonAuthCodeError)

    def test_missing_refresh_token_in_response_is_an_error(self) -> None:
        """A code exchange whose response carries no refresh token leaves the
        operator with a 60-minute setup — refuse rather than persist it."""

        def post(url, data):
            return _Resp(200, {"access_token": "Atza|NEW", "expires_in": 3600})

        with pytest.raises(AmazonAuthError, match="refresh_token"):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )

    def test_missing_access_token_in_response_is_an_error(self) -> None:
        def post(url, data):
            return _Resp(200, {"refresh_token": "Atzr|NEW"})

        with pytest.raises(AmazonAuthError, match="access_token"):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )

    def test_non_json_error_body_is_tolerated(self) -> None:
        class _Broken:
            status_code = 503

            def json(self) -> dict:
                raise ValueError("not json")

        with pytest.raises(AmazonAuthError):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=lambda *a, **k: _Broken(),
            )

    def test_network_failure_propagates_as_auth_error_without_detail(self) -> None:
        def post(url, data):
            raise OSError("connection reset while sending code=ANtoken")

        with pytest.raises(AmazonAuthError) as exc:
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="na",
                http_post=post,
            )
        assert "ANtoken" not in str(exc.value)
        assert "OSError" in str(exc.value)

    def test_secrets_never_reach_the_error_text(self) -> None:
        def post(url, data):
            return _Resp(
                400,
                {
                    "error": "invalid_client",
                    "error_description": "client_secret SUPER-SECRET rejected",
                },
            )

        with pytest.raises(AmazonAuthError) as exc:
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="SUPER-SECRET",
                region="na",
                http_post=post,
            )
        text = str(exc.value)
        assert "SUPER-SECRET" not in text
        assert "ANtoken" not in text

    def test_unknown_region_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            exchange_authorization_code(
                code="ANtoken",
                redirect_uri="https://amazon.com",
                client_id="cid",
                client_secret="secret",
                region="zz",
                http_post=lambda *a, **k: None,
            )
