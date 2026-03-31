from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from mureo.meta_ads._ad_rules import AdRulesMixin
from mureo.meta_ads._ad_sets import AdSetsMixin
from mureo.meta_ads._ads import AdsMixin
from mureo.meta_ads._analysis import AnalysisMixin
from mureo.meta_ads._audiences import AudiencesMixin
from mureo.meta_ads._campaigns import CampaignsMixin
from mureo.meta_ads._catalog import CatalogMixin
from mureo.meta_ads._conversions import ConversionsMixin
from mureo.meta_ads._creatives import CreativesMixin
from mureo.meta_ads._insights import InsightsMixin
from mureo.meta_ads._instagram import InstagramMixin
from mureo.meta_ads._leads import LeadsMixin
from mureo.meta_ads._page_posts import PagePostsMixin
from mureo.meta_ads._pixels import PixelsMixin
from mureo.meta_ads._split_test import SplitTestMixin

logger = logging.getLogger(__name__)

# レート制限の警告閾値（使用率%）
_RATE_LIMIT_WARNING_THRESHOLD = 80

# リトライ設定
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 1.0


class MetaAdsApiClient(
    CampaignsMixin,
    AdSetsMixin,
    AdsMixin,
    CreativesMixin,
    AudiencesMixin,
    PixelsMixin,
    InsightsMixin,
    AnalysisMixin,
    CatalogMixin,
    ConversionsMixin,
    LeadsMixin,
    PagePostsMixin,
    InstagramMixin,
    SplitTestMixin,
    AdRulesMixin,
):
    """Meta Marketing API クライアント

    Graph API v21.0を使用してMeta Ads（Facebook/Instagram）を操作する。
    レート制限の監視と指数バックオフによるリトライを内蔵。
    Mixin多重継承でキャンペーン・広告セット・広告・インサイト操作を提供。
    """

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
    ) -> None:
        """
        Args:
            access_token: Meta Graph API アクセストークン（平文）
            ad_account_id: 広告アカウントID（"act_XXXX" 形式）
        """
        if not access_token:
            raise ValueError("access_tokenは必須です")
        if not ad_account_id:
            raise ValueError("ad_account_idは必須です")
        if not ad_account_id.startswith("act_"):
            raise ValueError(
                f"ad_account_idは 'act_' で始まる形式が必要です: {ad_account_id}"
            )

        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GETリクエスト（レート制限対応付き）

        Args:
            path: APIパス（例: "/{ad_account_id}/campaigns"）
            params: クエリパラメータ

        Returns:
            APIレスポンスのJSON

        Raises:
            RuntimeError: APIリクエストに失敗した場合
        """
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """POSTリクエスト（レート制限対応付き）

        Args:
            path: APIパス
            data: リクエストボディ

        Returns:
            APIレスポンスのJSON

        Raises:
            RuntimeError: APIリクエストに失敗した場合
        """
        return await self._request("POST", path, data=data)

    async def _delete(self, path: str) -> dict[str, Any]:
        """DELETEリクエスト（レート制限対応付き）"""
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HTTPリクエストを実行（レート制限対応・指数バックオフリトライ付き）

        Args:
            method: HTTPメソッド
            path: APIパス
            params: クエリパラメータ
            data: リクエストボディ

        Returns:
            APIレスポンスのJSON

        Raises:
            RuntimeError: 最大リトライ回数を超えた場合
        """
        url = f"{self.BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        if params is None:
            params = {}

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                if method == "GET":
                    resp = await self._http.get(url, params=params, headers=headers)
                elif method == "POST":
                    resp = await self._http.post(
                        url, params=params, data=data, headers=headers
                    )
                elif method == "DELETE":
                    resp = await self._http.delete(
                        url, params=params, headers=headers
                    )
                else:
                    raise ValueError(f"未対応のHTTPメソッド: {method}")

                # レート制限ヘッダーを監視
                self._check_rate_limit(resp)

                # 429 Too Many Requests → バックオフリトライ
                if resp.status_code == 429:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API レート制限 (429): %s秒後にリトライ (試行 %d/%d)",
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if resp.status_code != 200:
                    error_body = resp.text[:500]
                    logger.error(
                        "Meta API エラー: method=%s, path=%s, status=%d, body=%s",
                        method,
                        path,
                        resp.status_code,
                        error_body,
                    )
                    raise RuntimeError(
                        f"Meta API リクエストに失敗しました "
                        f"(status={resp.status_code}, path={path})"
                    )

                return resp.json()  # type: ignore[no-any-return]

            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    backoff = _INITIAL_BACKOFF_SECONDS * (2**attempt)
                    logger.warning(
                        "Meta API 通信エラー: %s。%s秒後にリトライ (試行 %d/%d)",
                        exc,
                        backoff,
                        attempt + 1,
                        _MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise RuntimeError(
                    f"Meta API リクエストに失敗しました (path={path}): {exc}"
                ) from exc

        raise RuntimeError(
            f"Meta API リクエストが最大リトライ回数 ({_MAX_RETRIES}) を超えました: "
            f"path={path}"
        ) from last_error

    def _check_rate_limit(self, resp: httpx.Response) -> None:
        """レスポンスヘッダーからレート制限使用率を確認する

        x-business-use-case-usage ヘッダーを解析し、
        使用率が閾値を超えている場合は警告ログを出力する。

        Args:
            resp: HTTPレスポンス
        """
        usage_header = resp.headers.get("x-business-use-case-usage")
        if not usage_header:
            return

        try:
            usage_data = json.loads(usage_header)
            for business_id, usage_list in usage_data.items():
                if not isinstance(usage_list, list):
                    continue
                for usage in usage_list:
                    call_count = usage.get("call_count", 0)
                    total_cputime = usage.get("total_cputime", 0)
                    total_time = usage.get("total_time", 0)

                    max_usage = max(call_count, total_cputime, total_time)
                    if max_usage >= _RATE_LIMIT_WARNING_THRESHOLD:
                        logger.warning(
                            "Meta API レート制限使用率が高い: "
                            "business_id=%s, call_count=%d%%, "
                            "cputime=%d%%, time=%d%%",
                            business_id,
                            call_count,
                            total_cputime,
                            total_time,
                        )
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.debug(
                "x-business-use-case-usage ヘッダーの解析に失敗: %s",
                usage_header[:200],
            )

    async def close(self) -> None:
        """HTTPクライアントを閉じる"""
        await self._http.aclose()

    async def __aenter__(self) -> MetaAdsApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
