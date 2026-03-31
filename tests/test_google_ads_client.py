"""Google Ads client.py テスト

GoogleAdsApiClientのコンストラクタ、バリデーション、キャンペーン/広告グループ/予算/レポート関連メソッドのテスト。
Google Ads APIの呼び出しはすべてモックする。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from google.ads.googleads.errors import GoogleAdsException

from mureo.google_ads.client import (
    GoogleAdsApiClient,
    _wrap_mutate_error,
    PARTNER_CPA_WARNING_RATIO,
    _VALID_STATUSES,
    _VALID_MATCH_TYPES,
)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_client(
    customer_id: str = "1234567890",
    developer_token: str = "test-dev-token",
    login_customer_id: str | None = None,
) -> GoogleAdsApiClient:
    """テスト用のGoogleAdsApiClientを生成（GoogleAdsClient自体をモック）"""
    creds = MagicMock()
    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_instance = MagicMock()
        mock_gads.return_value = mock_instance
        client = GoogleAdsApiClient(
            credentials=creds,
            customer_id=customer_id,
            developer_token=developer_token,
            login_customer_id=login_customer_id,
        )
    return client


def _make_google_ads_exception(
    message: str = "test error",
    attr_name: str | None = None,
    error_name: str | None = None,
) -> GoogleAdsException:
    """モック GoogleAdsException を生成"""
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
    # failure プロパティをモック
    type(exc).failure = property(lambda self: self._failure)
    return exc


def _make_search_row(**kwargs: Any) -> MagicMock:
    """GAQL検索結果行のモック"""
    row = MagicMock()
    for key, value in kwargs.items():
        parts = key.split(".")
        obj = row
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], value)
    return row


# ---------------------------------------------------------------------------
# コンストラクタ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoogleAdsApiClientInit:
    def test_コンストラクタ_customer_idからハイフン除去(self) -> None:
        client = _make_client(customer_id="123-456-7890")
        assert client._customer_id == "1234567890"

    def test_コンストラクタ_login_customer_id指定(self) -> None:
        creds = MagicMock()
        with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
            GoogleAdsApiClient(
                credentials=creds,
                customer_id="1234567890",
                developer_token="tok",
                login_customer_id="9999999999",
            )
            mock_gads.assert_called_once_with(
                credentials=creds,
                developer_token="tok",
                login_customer_id="9999999999",
            )

    def test_コンストラクタ_login_customer_id未指定時はcustomer_id(self) -> None:
        creds = MagicMock()
        with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
            GoogleAdsApiClient(
                credentials=creds,
                customer_id="123-456-7890",
                developer_token="tok",
            )
            mock_gads.assert_called_once_with(
                credentials=creds,
                developer_token="tok",
                login_customer_id="1234567890",
            )


# ---------------------------------------------------------------------------
# 静的バリデーションメソッド
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateId:
    def test_数値のみ_正常(self) -> None:
        assert GoogleAdsApiClient._validate_id("12345", "test") == "12345"

    def test_非数値_エラー(self) -> None:
        with pytest.raises(ValueError, match="Invalid test"):
            GoogleAdsApiClient._validate_id("abc", "test")

    def test_空文字_エラー(self) -> None:
        with pytest.raises(ValueError):
            GoogleAdsApiClient._validate_id("", "test")

    def test_ハイフン付き_エラー(self) -> None:
        with pytest.raises(ValueError):
            GoogleAdsApiClient._validate_id("123-456", "test")


@pytest.mark.unit
class TestValidateStatus:
    def test_有効なステータス(self) -> None:
        for s in _VALID_STATUSES:
            assert GoogleAdsApiClient._validate_status(s) == s

    def test_小文字入力_大文字に変換(self) -> None:
        assert GoogleAdsApiClient._validate_status("enabled") == "ENABLED"

    def test_無効なステータス(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            GoogleAdsApiClient._validate_status("INVALID")


@pytest.mark.unit
class TestValidateMatchType:
    def test_有効なマッチタイプ(self) -> None:
        for mt in _VALID_MATCH_TYPES:
            assert GoogleAdsApiClient._validate_match_type(mt) == mt

    def test_小文字入力(self) -> None:
        assert GoogleAdsApiClient._validate_match_type("broad") == "BROAD"

    def test_無効なマッチタイプ(self) -> None:
        with pytest.raises(ValueError, match="Invalid match_type"):
            GoogleAdsApiClient._validate_match_type("INVALID")


@pytest.mark.unit
class TestValidateDate:
    def test_正常なYYYY_MM_DD(self) -> None:
        assert GoogleAdsApiClient._validate_date("2024-01-15", "start") == "2024-01-15"

    def test_不正なフォーマット(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            GoogleAdsApiClient._validate_date("2024/01/15", "start")


@pytest.mark.unit
class TestValidateRecommendationType:
    def test_有効なタイプ(self) -> None:
        assert GoogleAdsApiClient._validate_recommendation_type("KEYWORD") == "KEYWORD"

    def test_無効なタイプ(self) -> None:
        with pytest.raises(ValueError, match="Invalid recommendation_type"):
            GoogleAdsApiClient._validate_recommendation_type("INVALID")


@pytest.mark.unit
class TestValidateResourceName:
    def test_正常(self) -> None:
        import re
        pattern = re.compile(r"customers/\d+/campaigns/\d+")
        result = GoogleAdsApiClient._validate_resource_name(
            "customers/123/campaigns/456", pattern, "resource"
        )
        assert result == "customers/123/campaigns/456"

    def test_不正(self) -> None:
        import re
        pattern = re.compile(r"customers/\d+/campaigns/\d+")
        with pytest.raises(ValueError, match="Invalid resource"):
            GoogleAdsApiClient._validate_resource_name("invalid", pattern, "resource")


# ---------------------------------------------------------------------------
# ユーティリティメソッド
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEscapeGaqlString:
    def test_シングルクォートエスケープ(self) -> None:
        assert GoogleAdsApiClient._escape_gaql_string("it's") == "it\\'s"

    def test_バックスラッシュエスケープ(self) -> None:
        assert GoogleAdsApiClient._escape_gaql_string("a\\b") == "a\\\\b"

    def test_エスケープ不要(self) -> None:
        assert GoogleAdsApiClient._escape_gaql_string("hello") == "hello"


@pytest.mark.unit
class TestExtractErrorDetail:
    def test_メッセージあり(self) -> None:
        exc = _make_google_ads_exception("テストエラー")
        assert GoogleAdsApiClient._extract_error_detail(exc) == "テストエラー"

    def test_メッセージなし(self) -> None:
        exc = _make_google_ads_exception()
        # message属性がある場合はそれを返す
        result = GoogleAdsApiClient._extract_error_detail(exc)
        assert isinstance(result, str)


@pytest.mark.unit
class TestHasErrorCode:
    def test_一致するエラーコード(self) -> None:
        exc = _make_google_ads_exception(
            attr_name="mutate_error", error_name="RESOURCE_NOT_FOUND"
        )
        assert GoogleAdsApiClient._has_error_code(exc, "mutate_error", "RESOURCE_NOT_FOUND")

    def test_一致しないエラーコード(self) -> None:
        exc = _make_google_ads_exception(
            attr_name="mutate_error", error_name="OTHER_ERROR"
        )
        assert not GoogleAdsApiClient._has_error_code(exc, "mutate_error", "RESOURCE_NOT_FOUND")


@pytest.mark.unit
class TestExtractEvidences:
    def test_エビデンスあり(self) -> None:
        entry = MagicMock()
        ev = MagicMock()
        ev.text_list.texts = ["証拠1", "証拠2"]
        entry.evidences = [ev]
        result = GoogleAdsApiClient._extract_evidences(entry)
        assert result == ["証拠1", "証拠2"]

    def test_エビデンスなし(self) -> None:
        entry = MagicMock()
        entry.evidences = []
        assert GoogleAdsApiClient._extract_evidences(entry) == []

    def test_evidences属性なし(self) -> None:
        entry = MagicMock()
        entry.evidences = None
        assert GoogleAdsApiClient._extract_evidences(entry) == []


# ---------------------------------------------------------------------------
# _search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearch:
    @pytest.mark.asyncio
    async def test_search_正常(self) -> None:
        client = _make_client()
        mock_row = MagicMock()
        mock_service = MagicMock()
        mock_service.search.return_value = [mock_row]
        client._client.get_service.return_value = mock_service

        result = await client._search("SELECT campaign.id FROM campaign")
        assert len(result) == 1
        assert result[0] is mock_row


# ---------------------------------------------------------------------------
# _period_to_date_clause
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPeriodToDateClause:
    def test_定義済み期間(self) -> None:
        client = _make_client()
        assert client._period_to_date_clause("LAST_30_DAYS") == "DURING LAST_30_DAYS"
        assert client._period_to_date_clause("TODAY") == "DURING TODAY"
        assert client._period_to_date_clause("YESTERDAY") == "DURING YESTERDAY"

    def test_大文字小文字無視(self) -> None:
        client = _make_client()
        assert client._period_to_date_clause("last_7_days") == "DURING LAST_7_DAYS"

    def test_BETWEEN指定(self) -> None:
        client = _make_client()
        result = client._period_to_date_clause("BETWEEN '2024-01-01' AND '2024-01-31'")
        assert result == "BETWEEN '2024-01-01' AND '2024-01-31'"

    def test_不正なperiod(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid period"):
            client._period_to_date_clause("INVALID")


# ---------------------------------------------------------------------------
# list_accounts
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAccounts:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_service = MagicMock()
        mock_response = MagicMock()
        mock_response.resource_names = [
            "customers/111",
            "customers/222",
        ]
        mock_service.list_accessible_customers.return_value = mock_response
        client._client.get_service.return_value = mock_service

        result = await client.list_accounts()
        assert len(result) == 2
        assert result[0] == {"customer_id": "customers/111"}


# ---------------------------------------------------------------------------
# list_campaigns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListCampaigns:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign.id = 111
        row.campaign.name = "テストキャンペーン"
        row.campaign.status = 2  # ENABLED
        row.campaign.serving_status = 2
        row.campaign.bidding_strategy_type = 9
        row.campaign.primary_status = 0
        row.campaign.primary_status_reasons = []
        row.campaign_budget.amount_micros = 5000_000_000  # 5000円

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_campaigns()

        assert len(result) == 1
        assert result[0]["id"] == "111"
        assert result[0]["daily_budget"] == 5000.0

    @pytest.mark.asyncio
    async def test_ステータスフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_campaigns(status_filter="ENABLED")
            query = mock_search.call_args[0][0]
            assert "campaign.status = 'ENABLED'" in query

    @pytest.mark.asyncio
    async def test_不正なステータスフィルタ(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid status"):
            await client.list_campaigns(status_filter="INVALID")


# ---------------------------------------------------------------------------
# get_campaign
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetCampaign:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign.id = 111
        row.campaign.name = "テスト"
        row.campaign.status = 2
        row.campaign.serving_status = 2
        row.campaign.bidding_strategy_type = 9
        row.campaign.primary_status = 0
        row.campaign.primary_status_reasons = []
        row.campaign_budget.amount_micros = 3000_000_000
        row.campaign_budget.status = 2
        row.campaign.target_impression_share.location = 0
        row.campaign.target_impression_share.location_fraction_micros = 0
        row.campaign.target_impression_share.cpc_bid_ceiling_micros = 0

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_campaign("111")

        assert result is not None
        assert result["id"] == "111"
        assert result["budget_daily"] == 3000.0

    @pytest.mark.asyncio
    async def test_見つからない(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            result = await client.get_campaign("999")
        assert result is None

    @pytest.mark.asyncio
    async def test_不正なID(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid campaign_id"):
            await client.get_campaign("abc")


# ---------------------------------------------------------------------------
# create_campaign
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCampaign:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaigns/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaigns.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.create_campaign({"name": "新規", "bidding_strategy": "MAXIMIZE_CLICKS"})
        assert result["resource_name"] == "customers/123/campaigns/456"

    @pytest.mark.asyncio
    async def test_名前256文字超_エラー(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="256 characters"):
            await client.create_campaign({"name": "a" * 257})

    @pytest.mark.asyncio
    async def test_重複名_既存返却(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception(
            attr_name="campaign_error",
            error_name="DUPLICATE_CAMPAIGN_NAME",
        )
        mock_service = MagicMock()
        mock_service.mutate_campaigns.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with patch.object(
            client, "_find_campaign_by_name",
            return_value={"resource_name": "existing", "campaign_id": "1", "note": "既存"},
        ):
            result = await client.create_campaign({"name": "既存キャンペーン"})
            assert result["note"] == "既存"


# ---------------------------------------------------------------------------
# update_campaign_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateCampaignStatus:
    @pytest.mark.asyncio
    async def test_ENABLED(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaigns/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaigns.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.update_campaign_status("111", "ENABLED")
        assert result["resource_name"] == "customers/123/campaigns/456"

    @pytest.mark.asyncio
    async def test_REMOVED_removeオペレーション使用(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaigns/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaigns.return_value = mock_response
        mock_service.campaign_path.return_value = "customers/123/campaigns/111"
        client._client.get_service.return_value = mock_service
        op = MagicMock()
        client._client.get_type.return_value = op
        client._client.enums = MagicMock()

        result = await client.update_campaign_status("111", "REMOVED")
        assert result["resource_name"] == "customers/123/campaigns/456"

    @pytest.mark.asyncio
    async def test_GoogleAdsException_RuntimeError(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("mutateエラー")
        mock_service = MagicMock()
        mock_service.mutate_campaigns.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="error occurred"):
            await client.update_campaign_status("111", "PAUSED")


# ---------------------------------------------------------------------------
# list_ad_groups
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAdGroups:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.ad_group.id = 10
        row.ad_group.name = "テストグループ"
        row.ad_group.status = 2
        row.ad_group.cpc_bid_micros = 100_000_000
        row.campaign.id = 1
        row.campaign.name = "テスト"
        row.campaign.status = 2

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ad_groups()

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_campaign_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_ad_groups(campaign_id="111")
            query = mock_search.call_args[0][0]
            assert "campaigns/111" in query


# ---------------------------------------------------------------------------
# create_ad_group
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAdGroup:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroups/789"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_groups.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.create_ad_group({
            "name": "新規グループ",
            "campaign_id": "111",
        })
        assert result["resource_name"] == "customers/123/adGroups/789"


# ---------------------------------------------------------------------------
# update_ad_group
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAdGroup:
    @pytest.mark.asyncio
    async def test_name更新(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroups/789"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_groups.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.update_ad_group({
            "ad_group_id": "789",
            "name": "更新名",
        })
        assert result["resource_name"] == "customers/123/adGroups/789"

    @pytest.mark.asyncio
    async def test_フィールド未指定_エラー(self) -> None:
        client = _make_client()
        client._client.get_service.return_value = MagicMock()
        client._client.get_type.return_value = MagicMock()

        result = await client.update_ad_group({"ad_group_id": "789"})
        assert result["error"] is True

    @pytest.mark.asyncio
    async def test_無効なstatus(self) -> None:
        client = _make_client()
        client._client.get_service.return_value = MagicMock()
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.update_ad_group({
            "ad_group_id": "789",
            "status": "INVALID",
        })
        assert result["error"] is True
        assert "Invalid status" in result["message"]


# ---------------------------------------------------------------------------
# get_budget / update_budget / create_budget
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBudget:
    @pytest.mark.asyncio
    async def test_get_budget_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign_budget.id = 100
        row.campaign_budget.amount_micros = 10000_000_000
        row.campaign_budget.status = 2

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_budget("111")

        assert result is not None
        assert result["daily_budget"] == 10000.0

    @pytest.mark.asyncio
    async def test_get_budget_見つからない(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            result = await client.get_budget("999")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_budget_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/budgets/100"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaign_budgets.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.update_budget({
            "budget_id": "100",
            "amount": 5000,
        })
        assert result["resource_name"] == "customers/123/budgets/100"

    @pytest.mark.asyncio
    async def test_create_budget_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/budgets/200"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaign_budgets.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.create_budget({
            "name": "テスト予算",
            "amount": 3000,
        })
        assert result["resource_name"] == "customers/123/budgets/200"

    @pytest.mark.asyncio
    async def test_create_budget_名前256文字超(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="256 characters"):
            await client.create_budget({"name": "a" * 257, "amount": 1000})

    @pytest.mark.asyncio
    async def test_create_budget_金額0以下(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="positive number"):
            await client.create_budget({"name": "test", "amount": 0})

    @pytest.mark.asyncio
    async def test_create_budget_重複名(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception(
            attr_name="campaign_budget_error",
            error_name="DUPLICATE_NAME",
        )
        mock_service = MagicMock()
        mock_service.mutate_campaign_budgets.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with patch.object(
            client, "_find_budget_by_name",
            return_value={"resource_name": "existing", "budget_id": "100", "note": "既存"},
        ):
            result = await client.create_budget({"name": "既存", "amount": 1000})
            assert result["note"] == "既存"


# ---------------------------------------------------------------------------
# update_campaign
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateCampaign:
    @pytest.mark.asyncio
    async def test_name更新(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/campaigns/111"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_campaigns.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        result = await client.update_campaign({
            "campaign_id": "111",
            "name": "新名前",
        })
        assert result["resource_name"] == "customers/123/campaigns/111"

    @pytest.mark.asyncio
    async def test_フィールド未指定_エラー(self) -> None:
        client = _make_client()
        client._client.get_service.return_value = MagicMock()
        client._client.get_type.return_value = MagicMock()

        with pytest.raises(ValueError, match="No fields specified"):
            await client.update_campaign({"campaign_id": "111"})

    @pytest.mark.asyncio
    async def test_MAXIMIZE_CLICKSにtarget_cpa_不正組み合わせ(self) -> None:
        client = _make_client()
        client._client.get_service.return_value = MagicMock()
        client._client.get_type.return_value = MagicMock()

        with pytest.raises(ValueError, match="MAXIMIZE_CLICKS"):
            await client.update_campaign({
                "campaign_id": "111",
                "bidding_strategy": "MAXIMIZE_CLICKS",
                "target_cpa_micros": 1000,
            })


# ---------------------------------------------------------------------------
# _set_bidding_strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetBiddingStrategy:
    def test_未サポート戦略_エラー(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        with pytest.raises(ValueError, match="Unsupported bidding strategy"):
            client._set_bidding_strategy(campaign, "INVALID_STRATEGY", {})

    def test_TARGET_CPA_パラメータ不足(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        with pytest.raises(ValueError, match="target_cpa_micros"):
            client._set_bidding_strategy(campaign, "TARGET_CPA", {})

    def test_TARGET_CPA_負の値(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        with pytest.raises(ValueError, match="positive integer"):
            client._set_bidding_strategy(
                campaign, "TARGET_CPA", {"target_cpa_micros": -1}
            )

    def test_TARGET_ROAS_パラメータ不足(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        with pytest.raises(ValueError, match="target_roas_value"):
            client._set_bidding_strategy(campaign, "TARGET_ROAS", {})

    def test_TARGET_ROAS_負の値(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        with pytest.raises(ValueError, match="positive number"):
            client._set_bidding_strategy(
                campaign, "TARGET_ROAS", {"target_roas_value": -1.0}
            )

    def test_MAXIMIZE_CLICKS_上限CPC負の値(self) -> None:
        client = _make_client()
        campaign = MagicMock()
        client._client.get_type.return_value = MagicMock()
        with pytest.raises(ValueError, match="positive integer"):
            client._set_bidding_strategy(
                campaign, "MAXIMIZE_CLICKS", {"cpc_bid_ceiling_micros": -100}
            )


# ---------------------------------------------------------------------------
# get_performance_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPerformanceReport:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign.id = 111
        row.campaign.name = "テスト"
        row.metrics.impressions = 1000
        row.metrics.clicks = 50
        row.metrics.cost_micros = 5000_000_000
        row.metrics.conversions = 5
        row.metrics.ctr = 0.05
        row.metrics.average_cpc = 100_000_000
        row.metrics.cost_per_conversion = 1000_000_000

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_performance_report()

        assert len(result) >= 1


# ---------------------------------------------------------------------------
# get_network_performance_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetNetworkPerformanceReport:
    @pytest.mark.asyncio
    async def test_正常_SEARCH(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign.id = 111
        row.campaign.name = "テスト"
        row.segments.ad_network_type = "SEARCH"
        row.metrics.impressions = 1000
        row.metrics.clicks = 50
        row.metrics.cost_micros = 5000_000_000
        row.metrics.conversions = 5.0
        row.metrics.ctr = 0.05
        row.metrics.average_cpc = 100_000_000
        row.metrics.cost_per_conversion = 1000_000_000

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_network_performance_report()

        assert len(result) == 1
        assert result[0]["network_type"] == "SEARCH"
        assert result[0]["network_label"] == "Google Search"

    @pytest.mark.asyncio
    async def test_DISPLAY等はスキップ(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.segments.ad_network_type = "DISPLAY"

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_network_performance_report()

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_conversions_0でCPA_0(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign.id = 111
        row.campaign.name = "テスト"
        row.segments.ad_network_type = "SEARCH_PARTNERS"
        row.metrics.impressions = 100
        row.metrics.clicks = 10
        row.metrics.cost_micros = 1000_000_000
        row.metrics.conversions = 0.0
        row.metrics.ctr = 0.1
        row.metrics.average_cpc = 100_000_000
        row.metrics.cost_per_conversion = 0

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_network_performance_report()

        assert result[0]["cost_per_conversion"] == 0


# ---------------------------------------------------------------------------
# _wrap_mutate_error デコレータ
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWrapMutateError:
    @pytest.mark.asyncio
    async def test_正常実行(self) -> None:
        """デコレータが正常実行を妨げないこと"""

        class FakeClient:
            _customer_id = "123"

            @staticmethod
            def _extract_error_detail(exc: Any) -> str:
                return "detail"

            @staticmethod
            def _has_error_code(exc: Any, attr: str, name: str) -> bool:
                return False

            @_wrap_mutate_error("テスト操作")
            async def do_something(self) -> dict[str, str]:
                return {"ok": "true"}

        client = FakeClient()
        result = await client.do_something()
        assert result == {"ok": "true"}

    @pytest.mark.asyncio
    async def test_RESOURCE_NOT_FOUND(self) -> None:
        """RESOURCE_NOT_FOUNDの場合に具体的なヒントを返す"""
        exc = _make_google_ads_exception(
            attr_name="mutate_error",
            error_name="RESOURCE_NOT_FOUND",
        )

        class FakeClient:
            _customer_id = "123"

            @staticmethod
            def _extract_error_detail(e: Any) -> str:
                return "not found"

            @staticmethod
            def _has_error_code(e: Any, attr: str, name: str) -> bool:
                return attr == "mutate_error" and name == "RESOURCE_NOT_FOUND"

            @_wrap_mutate_error("テスト操作")
            async def do_something(self) -> dict[str, str]:
                raise exc

        client = FakeClient()
        with pytest.raises(RuntimeError, match="not found"):
            await client.do_something()

    @pytest.mark.asyncio
    async def test_一般的なGoogleAdsException(self) -> None:
        exc = _make_google_ads_exception("一般エラー")

        class FakeClient:
            _customer_id = "123"

            @staticmethod
            def _extract_error_detail(e: Any) -> str:
                return "general error"

            @staticmethod
            def _has_error_code(e: Any, attr: str, name: str) -> bool:
                return False

            @_wrap_mutate_error("テスト操作")
            async def do_something(self) -> dict[str, str]:
                raise exc

        client = FakeClient()
        with pytest.raises(RuntimeError, match="error occurred"):
            await client.do_something()


# ---------------------------------------------------------------------------
# _check_budget_bidding_compatibility
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckBudgetBiddingCompatibility:
    @pytest.mark.asyncio
    async def test_共有予算でスマート入札_エラー(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign_budget.explicitly_shared = True

        with patch.object(client, "_search", return_value=[row]):
            with pytest.raises(ValueError, match="not compatible with shared budget"):
                await client._check_budget_bidding_compatibility("100", "MAXIMIZE_CONVERSIONS")

    @pytest.mark.asyncio
    async def test_非共有予算_OK(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.campaign_budget.explicitly_shared = False

        with patch.object(client, "_search", return_value=[row]):
            await client._check_budget_bidding_compatibility("100", "TARGET_CPA")

    @pytest.mark.asyncio
    async def test_非スマート入札_チェックスキップ(self) -> None:
        client = _make_client()
        # _searchが呼ばれないことを確認
        with patch.object(client, "_search") as mock_search:
            await client._check_budget_bidding_compatibility("100", "MANUAL_CPC")
            mock_search.assert_not_called()


# ---------------------------------------------------------------------------
# PARTNER_CPA_WARNING_RATIO 定数
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    def test_partner_cpa_warning_ratio(self) -> None:
        assert PARTNER_CPA_WARNING_RATIO == 2.0
