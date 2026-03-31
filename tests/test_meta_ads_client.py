"""Meta Ads client.py ユニットテスト

MetaAdsApiClient の初期化・_request・_check_rate_limit・
コンテキストマネージャをテストする。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mureo.meta_ads.client import (
    MetaAdsApiClient,
    _INITIAL_BACKOFF_SECONDS,
    _MAX_RETRIES,
    _RATE_LIMIT_WARNING_THRESHOLD,
)


# ---------------------------------------------------------------------------
# 初期化テスト
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
# _check_rate_limit テスト
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckRateLimit:
    @pytest.fixture()
    def client(self) -> MetaAdsApiClient:
        return MetaAdsApiClient("token", "act_123")

    def test_no_header(self, client: MetaAdsApiClient) -> None:
        """ヘッダーがない場合は何もしない"""
        resp = MagicMock()
        resp.headers = {}
        client._check_rate_limit(resp)  # 例外なし

    def test_high_usage_warning(self, client: MetaAdsApiClient) -> None:
        """使用率が閾値超の場合は警告ログ"""
        usage = {
            "biz1": [{"call_count": 90, "total_cputime": 10, "total_time": 10}]
        }
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": json.dumps(usage)}

        with patch("mureo.meta_ads.client.logger") as mock_logger:
            client._check_rate_limit(resp)
            mock_logger.warning.assert_called_once()

    def test_low_usage_no_warning(self, client: MetaAdsApiClient) -> None:
        """使用率が閾値以下の場合は警告なし"""
        usage = {
            "biz1": [{"call_count": 10, "total_cputime": 5, "total_time": 5}]
        }
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": json.dumps(usage)}

        with patch("mureo.meta_ads.client.logger") as mock_logger:
            client._check_rate_limit(resp)
            mock_logger.warning.assert_not_called()

    def test_malformed_header(self, client: MetaAdsApiClient) -> None:
        """不正なJSONヘッダーでも例外にならない"""
        resp = MagicMock()
        resp.headers = {"x-business-use-case-usage": "not-json"}
        client._check_rate_limit(resp)  # 例外なし


# ---------------------------------------------------------------------------
# _request テスト
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
        """429応答で指数バックオフリトライする"""
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
        """最大リトライ回数を超えた場合"""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {}

        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=mock_429)

        with patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="maximum retry count"):
                await client._get("/test")

    @pytest.mark.asyncio
    async def test_http_error_retry(self, client: MetaAdsApiClient) -> None:
        """HTTPエラーでリトライ"""
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
        """HTTPエラーが最大回数を超えた場合"""
        client._http = MagicMock()
        client._http.get = AsyncMock(
            side_effect=httpx.ConnectError("always fail")
        )

        with patch("mureo.meta_ads.client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="request failed"):
                await client._get("/test")

    @pytest.mark.asyncio
    async def test_unsupported_method_raises(self, client: MetaAdsApiClient) -> None:
        with pytest.raises(ValueError, match="Unsupported HTTP method"):
            await client._request("PATCH", "/test")


# ---------------------------------------------------------------------------
# コンテキストマネージャ テスト
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
