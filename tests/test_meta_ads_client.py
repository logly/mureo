"""Unit tests for Meta Ads client.py.

Covers MetaAdsApiClient initialization, _request, _check_rate_limit,
and the context manager.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mureo.core.auth_failure import PlatformAuthError
from mureo.meta_ads._graph_error import GRAPH_ERROR_NO_DETAIL
from mureo.meta_ads.client import (
    MetaAdsApiClient,
)

# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsApiClientInit:
    def test_valid_init(self) -> None:
        client = MetaAdsApiClient("token123", "act_123")
        assert client._access_token == "token123"
        assert client._ad_account_id == "act_123"

    def test_empty_token_raises(self) -> None:
        with pytest.raises(ValueError, match="access_token is required"):
            MetaAdsApiClient("", "act_123")

    def test_empty_account_id_raises(self) -> None:
        with pytest.raises(ValueError, match="ad_account_id is required"):
            MetaAdsApiClient("token", "")

    def test_invalid_account_id_format(self) -> None:
        with pytest.raises(ValueError, match="act_"):
            MetaAdsApiClient("token", "123456")


# ---------------------------------------------------------------------------
# _check_rate_limit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRateLimit:
    @pytest.fixture()
    def client(self) -> MetaAdsApiClient:
        return MetaAdsApiClient("token", "act_123")

    def test_no_header(self, client: MetaAdsApiClient) -> None:
        """Does nothing when the header is missing."""
        resp = MagicMock()
        resp.headers = {}
        client._check_rate_limit(resp)  # no exception

    def test_high_usage_warning(self, client: MetaAdsApiClient) -> None:
        """Logs a warning when usage exceeds the threshold."""
        usage = {"biz1": [{"call_count": 90, "total_cputime": 10, "total_time": 10}]}
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": json.dumps(usage)}

        with patch("mureo.meta_ads.client.logger") as mock_logger:
            client._check_rate_limit(resp)
            mock_logger.warning.assert_called_once()

    def test_low_usage_no_warning(self, client: MetaAdsApiClient) -> None:
        """No warning when usage is at or below the threshold."""
        usage = {"biz1": [{"call_count": 10, "total_cputime": 5, "total_time": 5}]}
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": json.dumps(usage)}

        with patch("mureo.meta_ads.client.logger") as mock_logger:
            client._check_rate_limit(resp)
            mock_logger.warning.assert_not_called()

    def test_malformed_header(self, client: MetaAdsApiClient) -> None:
        """A malformed JSON header does not raise an exception."""
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": "not-json"}
        client._check_rate_limit(resp)  # no exception


# ---------------------------------------------------------------------------
# _request tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRequest:
    @pytest.fixture()
    def client(self) -> MetaAdsApiClient:
        return MetaAdsApiClient("token", "act_123")

    @pytest.mark.asyncio
    async def test_get_success(self, client: MetaAdsApiClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.headers = {}
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        result = await client._get("/test")
        assert result == {"data": []}

    @pytest.mark.asyncio
    async def test_post_success(self, client: MetaAdsApiClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "123"}
        mock_resp.headers = {}
        client._http = MagicMock()
        client._http.post = AsyncMock(return_value=mock_resp)

        result = await client._post("/test", {"name": "test"})
        assert result == {"id": "123"}

    @pytest.mark.asyncio
    async def test_delete_success(self, client: MetaAdsApiClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        mock_resp.headers = {}
        client._http = MagicMock()
        client._http.delete = AsyncMock(return_value=mock_resp)

        result = await client._delete("/test")
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_non_200_raises(self, client: MetaAdsApiClient) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_resp.headers = {}
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(RuntimeError, match="status=400"):
            await client._get("/test")

    @pytest.mark.asyncio
    async def test_429_retry(self, client: MetaAdsApiClient) -> None:
        """Retries with exponential backoff on a 429 response."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"ok": True}
        mock_200.headers = {}

        client._http = MagicMock()
        client._http.get = AsyncMock(side_effect=[mock_429, mock_200])

        with patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get("/test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, client: MetaAdsApiClient) -> None:
        """Behaviour when the maximum retry count is exceeded."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {}

        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_429)

        with (
            patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="maximum retry count"),
        ):
            await client._get("/test")

    @pytest.mark.asyncio
    async def test_http_error_retry(self, client: MetaAdsApiClient) -> None:
        """Retries on HTTP errors."""
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"ok": True}
        mock_200.headers = {}

        client._http = MagicMock()
        client._http.get = AsyncMock(
            side_effect=[httpx.ConnectError("connect fail"), mock_200]
        )

        with patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._get("/test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_http_error_max_retries(self, client: MetaAdsApiClient) -> None:
        """Behaviour when HTTP errors exceed the maximum retry count."""
        client._http = MagicMock()
        client._http.get = AsyncMock(side_effect=httpx.ConnectError("always fail"))

        with (
            patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="request failed") as excinfo,
        ):
            await client._get("/test")
        # Class name only, not the transport error text (#900).
        assert str(excinfo.value) == (
            "Meta API request failed (path=/test): ConnectError"
        )

    @pytest.mark.asyncio
    async def test_unsupported_method_raises(self, client: MetaAdsApiClient) -> None:
        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            await client._request("PATCH", "/test")


# ---------------------------------------------------------------------------
# Auth-failure classification (#580)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuthFailureClassification:
    """Meta answers an expired token with HTTP 400, not 401.

    So the status code alone cannot tell a dead credential from a bad
    request, and both used to arrive downstream as the same untyped
    ``API error: ...`` string. ``OAuthException`` / code 190 is the
    discriminator, and raising :class:`PlatformAuthError` is what lets
    ``api_error_handler`` stamp the machine-readable envelope a report
    skill can branch on (#580).
    """

    @pytest.fixture()
    def client(self) -> MetaAdsApiClient:
        return MetaAdsApiClient("token", "act_123")

    @staticmethod
    def _respond(client: MetaAdsApiClient, status: int, body: dict) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = status
        mock_resp.text = json.dumps(body)
        mock_resp.headers = {}
        mock_resp.json.return_value = body
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_resp)

    @pytest.mark.asyncio
    async def test_expired_token_400_is_an_auth_error(
        self, client: MetaAdsApiClient
    ) -> None:
        self._respond(
            client,
            400,
            {
                "error": {
                    "message": "Error validating access token: Session has expired",
                    "type": "OAuthException",
                    "code": 190,
                    "error_subcode": 463,
                }
            },
        )
        with pytest.raises(PlatformAuthError, match="status=400"):
            await client._get("/test")

    @pytest.mark.asyncio
    async def test_401_is_an_auth_error_whatever_the_body(
        self, client: MetaAdsApiClient
    ) -> None:
        self._respond(client, 401, {"error": {"message": "Unauthorized"}})
        with pytest.raises(PlatformAuthError):
            await client._get("/test")

    @pytest.mark.asyncio
    async def test_ordinary_400_stays_a_plain_runtime_error(
        self, client: MetaAdsApiClient
    ) -> None:
        """A validation failure must NOT be reported as a credential problem —
        it would send the operator to re-authorize a healthy account."""
        self._respond(
            client,
            400,
            {
                "error": {
                    "message": "Invalid parameter",
                    "type": "GraphMethodException",
                    "code": 100,
                }
            },
        )
        with pytest.raises(RuntimeError) as excinfo:
            await client._get("/test")
        assert not isinstance(excinfo.value, PlatformAuthError)


@pytest.mark.unit
class TestErrorDetail:
    """The detail after ``path=...):`` is the shared Graph error format, and
    never the raw response body (#605, #866)."""

    _MARKER = "RAW-BODY-MARKER-c0ffee"

    @pytest.fixture()
    def client(self) -> MetaAdsApiClient:
        return MetaAdsApiClient("token", "act_123")

    def _resp(self, body: object) -> MagicMock:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.headers = {}
        mock_resp.text = f"<html>{self._MARKER}</html>"
        if body is None:
            mock_resp.json.side_effect = ValueError("not JSON")
        else:
            mock_resp.json.return_value = body
        return mock_resp

    @pytest.mark.asyncio
    async def test_envelope_fields_in_the_shared_format(
        self, client: MetaAdsApiClient
    ) -> None:
        body = {
            "error": {
                "message": "Invalid parameter",
                "error_user_title": "Bad budget",
                "error_user_msg": "Budget too low.",
                "code": 100,
                "error_subcode": 1885650,
                "fbtrace_id": "AbC123",
            }
        }
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=self._resp(body))
        with pytest.raises(RuntimeError) as excinfo:
            await client._get("/test")
        assert str(excinfo.value) == (
            "Meta API request failed (status=400, path=/test): Invalid parameter | "
            "Bad budget | Budget too low. | code=100 | subcode=1885650 | "
            "fbtrace_id=AbC123"
        )

    @pytest.mark.asyncio
    async def test_non_json_body_is_not_echoed(self, client: MetaAdsApiClient) -> None:
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=self._resp(None))
        with pytest.raises(RuntimeError) as excinfo:
            await client._get("/test")
        assert self._MARKER not in str(excinfo.value)
        assert str(excinfo.value).endswith(f"): {GRAPH_ERROR_NO_DETAIL}")

    @pytest.mark.asyncio
    async def test_error_log_carries_the_detail_not_the_body(
        self, client: MetaAdsApiClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = {"error": {"message": "Invalid parameter", "code": 100}}
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=self._resp(body))
        with (
            caplog.at_level(logging.ERROR, logger="mureo.meta_ads.client"),
            pytest.raises(RuntimeError),
        ):
            await client._get("/test")
        assert self._MARKER not in caplog.text
        assert "detail=Invalid parameter | code=100" in caplog.text

    @pytest.mark.asyncio
    async def test_page_token_request_does_not_echo_the_body(
        self, client: MetaAdsApiClient
    ) -> None:
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=self._resp(None))
        with (
            patch.object(
                client, "get_page_access_token", AsyncMock(return_value="page-tok")
            ),
            pytest.raises(RuntimeError) as excinfo,
        ):
            await client._get_as_page("123", "/123/feed")
        assert self._MARKER not in str(excinfo.value)
        assert str(excinfo.value).endswith(f"): {GRAPH_ERROR_NO_DETAIL}")


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        client = MetaAdsApiClient("token", "act_123")
        client._http = MagicMock()
        client._http.aclose = AsyncMock()

        async with client as c:
            assert c is client

        client._http.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        client = MetaAdsApiClient("token", "act_123")
        client._http = MagicMock()
        client._http.aclose = AsyncMock()

        await client.close()
        client._http.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# #468 — ad-level delivery status: wire-level request + passthrough
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdDeliveryStatusWire:
    """End-to-end over an ``httpx.MockTransport``: the ad-status fields must
    be asked for on the wire AND survive unchanged into the client's result.

    A mixin-level assertion only proves the ``fields`` string; this proves
    that what Meta returns for those fields reaches the MCP response, which
    is what makes an out-of-mureo pause visible to the agent.
    """

    @staticmethod
    def _client(handler) -> MetaAdsApiClient:
        client = MetaAdsApiClient("token", "act_123")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    _AD_PAYLOAD = {
        "id": "ad_1",
        "name": "Creative A",
        "status": "ACTIVE",
        "effective_status": "CAMPAIGN_PAUSED",
        "configured_status": "ACTIVE",
        "issues_info": [{"level": "AD", "error_summary": "Ad set is paused"}],
        "ad_review_feedback": {"global": {"CIRCUMVENTION": "Policy hit"}},
    }

    @pytest.mark.asyncio
    async def test_list_ads_requests_and_returns_delivery_status(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["fields"] = request.url.params["fields"]
            return httpx.Response(200, json={"data": [self._AD_PAYLOAD]})

        client = self._client(handler)
        try:
            ads = await client.list_ads()
        finally:
            await client._http.aclose()

        for name in (
            "effective_status",
            "configured_status",
            "issues_info",
            "ad_review_feedback",
        ):
            assert name in seen["fields"]
        assert ads[0]["effective_status"] == "CAMPAIGN_PAUSED"
        assert ads[0]["configured_status"] == "ACTIVE"
        assert ads[0]["issues_info"][0]["error_summary"] == "Ad set is paused"
        assert ads[0]["ad_review_feedback"]["global"]["CIRCUMVENTION"] == "Policy hit"

    @pytest.mark.asyncio
    async def test_get_ad_requests_and_returns_delivery_status(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["fields"] = request.url.params["fields"]
            return httpx.Response(200, json=self._AD_PAYLOAD)

        client = self._client(handler)
        try:
            ad = await client.get_ad("ad_1")
        finally:
            await client._http.aclose()

        assert "effective_status" in seen["fields"]
        assert ad["effective_status"] == "CAMPAIGN_PAUSED"
