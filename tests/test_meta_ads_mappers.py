"""Meta Ads mappers テスト

mappers.pyの各関数にモックデータを渡して正しく変換されることを確認する。
"""

from __future__ import annotations

import pytest

from mureo.meta_ads.mappers import (
    _cents_to_amount,
    _extract_conversions,
    _extract_cost_per_conversion,
    _safe_float,
    _safe_int,
    map_ad,
    map_ad_set,
    map_campaign,
    map_insights,
)


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCentsToAmount:
    def test_文字列のセントを変換(self) -> None:
        assert _cents_to_amount("100000") == 1000.0

    def test_整数のセントを変換(self) -> None:
        assert _cents_to_amount(50000) == 500.0

    def test_Noneの場合は0(self) -> None:
        assert _cents_to_amount(None) == 0.0

    def test_ゼロの場合(self) -> None:
        assert _cents_to_amount("0") == 0.0
        assert _cents_to_amount(0) == 0.0


@pytest.mark.unit
class TestSafeFloat:
    def test_文字列を変換(self) -> None:
        assert _safe_float("3.14") == 3.14

    def test_整数を変換(self) -> None:
        assert _safe_float(42) == 42.0

    def test_Noneは0(self) -> None:
        assert _safe_float(None) == 0.0

    def test_不正文字列は0(self) -> None:
        assert _safe_float("abc") == 0.0


@pytest.mark.unit
class TestSafeInt:
    def test_文字列を変換(self) -> None:
        assert _safe_int("100") == 100

    def test_Noneは0(self) -> None:
        assert _safe_int(None) == 0

    def test_不正文字列は0(self) -> None:
        assert _safe_int("abc") == 0


# ---------------------------------------------------------------------------
# _extract_conversions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractConversions:
    def test_コンバージョンアクションを正しく集計(self) -> None:
        actions = [
            {"action_type": "purchase", "value": "5"},
            {"action_type": "lead", "value": "3"},
            {"action_type": "link_click", "value": "100"},
        ]
        assert _extract_conversions(actions) == 8.0

    def test_Noneは0(self) -> None:
        assert _extract_conversions(None) == 0.0

    def test_空リストは0(self) -> None:
        assert _extract_conversions([]) == 0.0

    def test_複数のCV種別を集計(self) -> None:
        actions = [
            {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "2"},
            {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
            {"action_type": "complete_registration", "value": "1"},
        ]
        assert _extract_conversions(actions) == 7.0

    def test_CV以外は無視(self) -> None:
        actions = [
            {"action_type": "post_engagement", "value": "50"},
            {"action_type": "video_view", "value": "200"},
        ]
        assert _extract_conversions(actions) == 0.0


# ---------------------------------------------------------------------------
# _extract_cost_per_conversion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractCostPerConversion:
    def test_CPAを正しく抽出(self) -> None:
        cost_per_action = [
            {"action_type": "purchase", "value": "1500.50"},
        ]
        assert _extract_cost_per_conversion(cost_per_action) == 1500.50

    def test_Noneの場合(self) -> None:
        assert _extract_cost_per_conversion(None) is None

    def test_空リスト(self) -> None:
        assert _extract_cost_per_conversion([]) is None

    def test_該当アクション無し(self) -> None:
        cost_per_action = [
            {"action_type": "link_click", "value": "100"},
        ]
        assert _extract_cost_per_conversion(cost_per_action) is None


# ---------------------------------------------------------------------------
# map_campaign
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapCampaign:
    def test_基本変換(self) -> None:
        raw = {
            "id": "campaign_123",
            "name": "テストキャンペーン",
            "status": "ACTIVE",
            "objective": "CONVERSIONS",
            "daily_budget": "500000",
            "lifetime_budget": "0",
            "budget_remaining": "300000",
            "bid_strategy": "LOWEST_COST_WITH_BID_CAP",
            "special_ad_categories": [],
            "created_time": "2024-01-01T00:00:00",
            "updated_time": "2024-06-01T00:00:00",
            "start_time": "2024-01-01T00:00:00",
            "stop_time": "",
        }

        result = map_campaign(raw)

        assert result["campaign_id"] == "campaign_123"
        assert result["campaign_name"] == "テストキャンペーン"
        assert result["status"] == "ACTIVE"
        assert result["objective"] == "CONVERSIONS"
        assert result["daily_budget"] == 5000.0
        assert result["budget_remaining"] == 3000.0

    def test_空の辞書(self) -> None:
        result = map_campaign({})

        assert result["campaign_id"] == ""
        assert result["campaign_name"] == ""
        assert result["daily_budget"] == 0.0


# ---------------------------------------------------------------------------
# map_ad_set
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapAdSet:
    def test_基本変換(self) -> None:
        raw = {
            "id": "adset_456",
            "name": "テスト広告セット",
            "status": "ACTIVE",
            "campaign_id": "campaign_123",
            "daily_budget": "200000",
            "lifetime_budget": "0",
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "REACH",
            "targeting": {"age_min": 25, "age_max": 55},
            "bid_amount": "5000",
            "created_time": "2024-01-01T00:00:00",
            "updated_time": "2024-06-01T00:00:00",
            "start_time": "2024-01-01T00:00:00",
            "end_time": "",
        }

        result = map_ad_set(raw)

        assert result["ad_set_id"] == "adset_456"
        assert result["ad_set_name"] == "テスト広告セット"
        assert result["daily_budget"] == 2000.0
        assert result["bid_amount"] == 50.0
        assert result["targeting"] == {"age_min": 25, "age_max": 55}

    def test_空の辞書(self) -> None:
        result = map_ad_set({})

        assert result["ad_set_id"] == ""
        assert result["daily_budget"] == 0.0


# ---------------------------------------------------------------------------
# map_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapAd:
    def test_基本変換(self) -> None:
        raw = {
            "id": "ad_789",
            "name": "テスト広告",
            "status": "ACTIVE",
            "adset_id": "adset_456",
            "campaign_id": "campaign_123",
            "creative": {"id": "creative_001", "name": "クリエイティブ1"},
            "created_time": "2024-01-01T00:00:00",
            "updated_time": "2024-06-01T00:00:00",
        }

        result = map_ad(raw)

        assert result["ad_id"] == "ad_789"
        assert result["ad_name"] == "テスト広告"
        assert result["status"] == "ACTIVE"
        assert result["creative_id"] == "creative_001"

    def test_creative無し(self) -> None:
        raw = {
            "id": "ad_999",
            "name": "テスト",
            "status": "PAUSED",
        }

        result = map_ad(raw)

        assert result["creative_id"] == ""
        assert result["creative_name"] == ""


# ---------------------------------------------------------------------------
# map_insights
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapInsights:
    def test_基本変換(self) -> None:
        raw = {
            "campaign_id": "campaign_123",
            "campaign_name": "テスト",
            "adset_id": "",
            "adset_name": "",
            "ad_id": "",
            "ad_name": "",
            "impressions": "10000",
            "clicks": "500",
            "spend": "15000.50",
            "cpc": "30.001",
            "cpm": "1500.05",
            "ctr": "5.0",
            "reach": "8000",
            "frequency": "1.25",
            "actions": [
                {"action_type": "purchase", "value": "3"},
                {"action_type": "lead", "value": "2"},
            ],
            "cost_per_action_type": [
                {"action_type": "purchase", "value": "5000.17"},
            ],
        }

        result = map_insights(raw)

        assert result["impressions"] == 10000
        assert result["clicks"] == 500
        assert result["spend"] == 15000.50
        assert result["conversions"] == 5.0
        assert result["cpa"] == 5000.17

    def test_ブレイクダウンフィールド(self) -> None:
        raw = {
            "impressions": "100",
            "clicks": "10",
            "spend": "500",
            "cpc": "50",
            "cpm": "5000",
            "ctr": "10",
            "reach": "80",
            "frequency": "1.2",
            "age": "25-34",
            "gender": "male",
        }

        result = map_insights(raw)

        assert result["age"] == "25-34"
        assert result["gender"] == "male"
        assert "country" not in result

    def test_actionsなし(self) -> None:
        raw = {
            "impressions": "100",
            "clicks": "10",
            "spend": "500",
            "cpc": "50",
            "cpm": "5000",
            "ctr": "10",
            "reach": "80",
            "frequency": "1.2",
        }

        result = map_insights(raw)

        assert result["conversions"] == 0.0
        assert result["cpa"] is None
