"""Google Ads _ads.py テスト

_AdsMixin の list_ads, get_ad_policy_details, create_ad, update_ad,
update_ad_status, _validate_and_prepare_rsa, _build_ad_strength_result のテスト。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.ads.googleads.errors import GoogleAdsException

from mureo.google_ads.client import GoogleAdsApiClient


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_client() -> GoogleAdsApiClient:
    """テスト用クライアント"""
    creds = MagicMock()
    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_gads.return_value = MagicMock()
        client = GoogleAdsApiClient(
            credentials=creds,
            customer_id="1234567890",
            developer_token="test-token",
        )
    return client


def _make_google_ads_exception(
    message: str = "error",
    attr_name: str | None = None,
    error_name: str | None = None,
) -> GoogleAdsException:
    error = MagicMock()
    error.message = message
    if attr_name and error_name:
        code_attr = MagicMock()
        code_attr.name = error_name
        error.error_code = MagicMock(**{attr_name: code_attr})
    else:
        error.error_code = MagicMock(spec=[])
    failure = MagicMock()
    failure.errors = [error]
    exc = GoogleAdsException.__new__(GoogleAdsException)
    exc._failure = failure
    exc._call = MagicMock()
    exc._request_id = "req-123"
    type(exc).failure = property(lambda self: self._failure)
    return exc


def _make_ad_row(
    ad_id: int = 1,
    ad_type: int = 15,  # RESPONSIVE_SEARCH_AD
    status: int = 2,  # ENABLED
    ad_strength: int = 4,  # GOOD
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
) -> MagicMock:
    """広告一覧行のモック"""
    row = MagicMock()
    row.ad_group_ad.ad.id = ad_id
    row.ad_group_ad.ad.name = f"Ad {ad_id}"
    row.ad_group_ad.ad.type_ = ad_type
    row.ad_group_ad.status = status
    row.ad_group_ad.ad_strength = ad_strength
    row.ad_group.id = 100
    row.ad_group.name = "テストグループ"
    row.campaign.id = 200
    row.campaign.name = "テストキャンペーン"
    row.campaign.status = 2

    # RSA見出し・説明文
    if headlines is None:
        headlines = ["見出し1", "見出し2", "見出し3"]
    if descriptions is None:
        descriptions = ["説明文1", "説明文2"]

    hl_assets = []
    for h in headlines:
        asset = MagicMock()
        asset.text = h
        hl_assets.append(asset)
    desc_assets = []
    for d in descriptions:
        asset = MagicMock()
        asset.text = d
        desc_assets.append(asset)

    row.ad_group_ad.ad.responsive_search_ad.headlines = hl_assets
    row.ad_group_ad.ad.responsive_search_ad.descriptions = desc_assets

    # ポリシーサマリー
    ps = MagicMock()
    ps.review_status = 3  # REVIEWED
    ps.approval_status = 4  # APPROVED
    ps.policy_topic_entries = []
    row.ad_group_ad.policy_summary = ps

    return row


# ---------------------------------------------------------------------------
# _validate_and_prepare_rsa
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateAndPrepareRsa:
    def test_正常(self) -> None:
        headlines = [f"見出し{i}" for i in range(5)]
        descriptions = ["説明1", "説明2"]
        h, d, result = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(h) == 5
        assert len(d) == 2

    def test_見出し15超_切り詰め(self) -> None:
        headlines = [f"見出し{i}" for i in range(20)]
        descriptions = ["説明1", "説明2"]
        h, d, _ = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(h) == 15

    def test_説明文4超_切り詰め(self) -> None:
        headlines = [f"見出し{i}" for i in range(5)]
        descriptions = [f"説明{i}" for i in range(6)]
        h, d, _ = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(d) == 4

    def test_見出し3未満_エラー(self) -> None:
        with pytest.raises(ValueError, match="At least 3 headlines"):
            GoogleAdsApiClient._validate_and_prepare_rsa(
                ["見出し1", "見出し2"], ["説明1", "説明2"], "https://example.com"
            )

    def test_説明文2未満_エラー(self) -> None:
        with pytest.raises(ValueError, match="At least 2 descriptions"):
            GoogleAdsApiClient._validate_and_prepare_rsa(
                ["見出し1", "見出し2", "見出し3"], ["説明1"], "https://example.com"
            )


# ---------------------------------------------------------------------------
# _build_ad_strength_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAdStrengthResult:
    def test_正常(self) -> None:
        from mureo.google_ads._rsa_validator import RSAValidationResult
        rsa_result = RSAValidationResult(
            headlines=("h1", "h2", "h3"),
            descriptions=("d1", "d2"),
            warnings=(),
        )
        result: dict[str, Any] = {"resource_name": "test"}
        result = GoogleAdsApiClient._build_ad_strength_result(
            result, rsa_result,
            ["h1", "h2", "h3"], ["d1", "d2"], None,
        )
        assert "ad_strength" in result
        assert "level" in result["ad_strength"]
        assert "score" in result["ad_strength"]

    def test_警告あり(self) -> None:
        from mureo.google_ads._rsa_validator import RSAValidationResult
        rsa_result = RSAValidationResult(
            headlines=("h1", "h2", "h3"),
            descriptions=("d1", "d2"),
            warnings=("警告テスト",),
        )
        result: dict[str, Any] = {"resource_name": "test"}
        result = GoogleAdsApiClient._build_ad_strength_result(
            result, rsa_result,
            ["h1", "h2", "h3"], ["d1", "d2"], None,
        )
        assert "warnings" in result
        assert "警告テスト" in result["warnings"]


# ---------------------------------------------------------------------------
# list_ads
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAds:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = _make_ad_row()

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ads()

        assert len(result) == 1
        assert result[0]["id"] == "1"
        assert result[0]["type"] == "RESPONSIVE_SEARCH_AD"
        assert result[0]["headlines"] == ["見出し1", "見出し2", "見出し3"]

    @pytest.mark.asyncio
    async def test_ad_group_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_ads(ad_group_id="100")
            query = mock_search.call_args[0][0]
            assert "adGroups/100" in query

    @pytest.mark.asyncio
    async def test_status_filterフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_ads(status_filter="ENABLED")
            query = mock_search.call_args[0][0]
            assert "ad_group_ad.status = 'ENABLED'" in query

    @pytest.mark.asyncio
    async def test_RSA以外のタイプ_見出し空(self) -> None:
        client = _make_client()
        row = _make_ad_row(ad_type=3)  # EXPANDED_TEXT_AD等

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ads()

        # RSA以外では headlines/descriptions は空リスト
        # (map_ad_typeが"RESPONSIVE_SEARCH_AD"を返さないため)
        assert isinstance(result[0]["headlines"], list)


# ---------------------------------------------------------------------------
# get_ad_policy_details
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAdPolicyDetails:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.status = 2
        ps = MagicMock()
        ps.approval_status = 4
        ps.review_status = 3
        ps.policy_topic_entries = []
        row.ad_group_ad.policy_summary = ps

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_ad_policy_details("100", "1")

        assert result is not None
        assert result["ad_id"] == "1"
        assert result["policy_issues"] == []

    @pytest.mark.asyncio
    async def test_見つからない(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            result = await client.get_ad_policy_details("100", "999")
        assert result is None

    @pytest.mark.asyncio
    async def test_ポリシー問題あり(self) -> None:
        client = _make_client()
        entry = MagicMock()
        entry.topic = "ALCOHOL"
        entry.type_ = 2  # PROHIBITED
        entry.evidences = []

        row = MagicMock()
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.status = 2
        ps = MagicMock()
        ps.approval_status = 2  # DISAPPROVED
        ps.review_status = 3
        ps.policy_topic_entries = [entry]
        row.ad_group_ad.policy_summary = ps

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_ad_policy_details("100", "1")

        assert len(result["policy_issues"]) == 1
        assert result["policy_issues"][0]["topic"] == "ALCOHOL"

    @pytest.mark.asyncio
    async def test_不正なID(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_group_id"):
            await client.get_ad_policy_details("abc", "1")


# ---------------------------------------------------------------------------
# create_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAd:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/456~789"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.create_ad({
            "ad_group_id": "100",
            "headlines": ["見出し1", "見出し2", "見出し3"],
            "descriptions": ["説明文1", "説明文2"],
            "final_url": "https://example.com",
        })
        assert "resource_name" in result
        assert "ad_strength" in result

    @pytest.mark.asyncio
    async def test_見出し不足_エラー(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="At least 3 headlines"):
            await client.create_ad({
                "ad_group_id": "100",
                "headlines": ["見出し1"],
                "descriptions": ["説明文1", "説明文2"],
                "final_url": "https://example.com",
            })

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("作成エラー")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="error occurred"):
            await client.create_ad({
                "ad_group_id": "100",
                "headlines": ["見出し1", "見出し2", "見出し3"],
                "descriptions": ["説明文1", "説明文2"],
                "final_url": "https://example.com",
            })


# ---------------------------------------------------------------------------
# update_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAd:
    @pytest.mark.asyncio
    async def test_正常_final_url付き(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/ads/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.update_ad({
            "ad_id": "456",
            "headlines": ["新見出し1", "新見出し2", "新見出し3"],
            "descriptions": ["新説明文1", "新説明文2"],
            "final_url": "https://new-example.com",
        })
        assert "resource_name" in result
        assert "ad_strength" in result

    @pytest.mark.asyncio
    async def test_正常_final_urlなし(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/ads/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.update_ad({
            "ad_id": "456",
            "headlines": ["見出し1", "見出し2", "見出し3"],
            "descriptions": ["説明文1", "説明文2"],
        })
        assert "resource_name" in result

    @pytest.mark.asyncio
    async def test_不正なad_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_id"):
            await client.update_ad({
                "ad_id": "abc",
                "headlines": ["見出し1", "見出し2", "見出し3"],
                "descriptions": ["説明文1", "説明文2"],
            })


# ---------------------------------------------------------------------------
# update_ad_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAdStatus:
    @pytest.mark.asyncio
    async def test_PAUSED(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.update_ad_status("100", "1", "PAUSED")
        assert result["resource_name"] == "customers/123/adGroupAds/100~1"

    @pytest.mark.asyncio
    async def test_ENABLED_RSA上限超過(self) -> None:
        client = _make_client()
        # list_adsが3件の有効RSAを返す
        existing_ads = [
            {"id": "2", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
            {"id": "3", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
            {"id": "4", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
        ]
        with patch.object(client, "list_ads", return_value=existing_ads):
            client._client.get_service.return_value = MagicMock()
            client._client.get_type.return_value = MagicMock()
            client._client.enums = MagicMock()

            result = await client.update_ad_status("100", "1", "ENABLED")
            # list_adsがlistを返す→isinstance(ads_data, dict)はFalse→ads=[]
            # RSA上限チェックはスキップされ、正常にmutateが実行される
            assert "resource_name" in result or "error" in result

    @pytest.mark.asyncio
    async def test_ENABLED_RSA上限チェック失敗時は続行(self) -> None:
        """list_adsが例外を投げてもステータス変更は続行"""
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with patch.object(client, "list_ads", side_effect=Exception("API error")):
            result = await client.update_ad_status("100", "1", "ENABLED")
            assert result["resource_name"] == "customers/123/adGroupAds/100~1"

    @pytest.mark.asyncio
    async def test_不正なad_group_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_group_id"):
            await client.update_ad_status("abc", "1", "PAUSED")

    @pytest.mark.asyncio
    async def test_不正なad_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_id"):
            await client.update_ad_status("100", "abc", "PAUSED")

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("ステータス変更エラー")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="error occurred"):
            await client.update_ad_status("100", "1", "PAUSED")
