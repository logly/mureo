"""Google Ads mappers テスト

mappers.pyの各関数にモックデータを渡して正しく変換されることを確認する。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.ads.googleads.v23.enums.types.bidding_strategy_type import (
    BiddingStrategyTypeEnum,
)

from mureo.google_ads.mappers import (
    _BIDDING_STRATEGY_MAP,
    _micros_to_currency,
    _safe_float,
    _safe_int,
    _safe_str,
    map_ad_group,
    map_ad_performance_report,
    map_approval_status,
    map_bidding_strategy_type,
    map_bidding_system_status,
    map_callout,
    map_campaign,
    map_change_event,
    map_conversion_action,
    map_criterion_approval_status,
    map_entity_status,
    map_keyword,
    map_keyword_quality_info,
    map_negative_keyword,
    map_performance_report,
    map_primary_status,
    map_primary_status_reason,
    map_recommendation,
    map_review_status,
    map_search_term,
    map_serving_status,
    map_sitelink,
    map_tag_snippet,
)


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMicrosToCurrency:
    def test_正常変換(self) -> None:
        assert _micros_to_currency(1_000_000) == 1.0

    def test_ゼロ(self) -> None:
        assert _micros_to_currency(0) == 0.0


@pytest.mark.unit
class TestSafeInt:
    def test_属性あり(self) -> None:
        obj = MagicMock()
        obj.impressions = 100
        assert _safe_int(obj, "impressions") == 100

    def test_属性なし(self) -> None:
        obj = MagicMock(spec=[])
        assert _safe_int(obj, "impressions") == 0


@pytest.mark.unit
class TestSafeFloat:
    def test_属性あり(self) -> None:
        obj = MagicMock()
        obj.ctr = 0.05
        assert _safe_float(obj, "ctr") == 0.05

    def test_属性なし(self) -> None:
        obj = MagicMock(spec=[])
        assert _safe_float(obj, "ctr") == 0.0


@pytest.mark.unit
class TestSafeStr:
    def test_属性あり(self) -> None:
        obj = MagicMock()
        obj.name = "test"
        assert _safe_str(obj, "name") == "test"

    def test_属性なし(self) -> None:
        obj = MagicMock(spec=[])
        assert _safe_str(obj, "name") == ""


# ---------------------------------------------------------------------------
# enum変換
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnumMappers:
    def test_map_entity_status_enabled(self) -> None:
        assert map_entity_status(2) == "ENABLED"

    def test_map_entity_status_paused(self) -> None:
        assert map_entity_status(3) == "PAUSED"

    def test_map_entity_status_string(self) -> None:
        assert map_entity_status("ENABLED") == "ENABLED"

    def test_map_serving_status_serving(self) -> None:
        assert map_serving_status(2) == "SERVING"

    def test_map_approval_status_approved(self) -> None:
        assert map_approval_status(4) == "APPROVED"

    def test_map_review_status_reviewed(self) -> None:
        assert map_review_status(3) == "REVIEWED"

    def test_map_primary_status_eligible(self) -> None:
        assert map_primary_status(2) == "ELIGIBLE"

    def test_map_primary_status_learning(self) -> None:
        assert map_primary_status(9) == "LEARNING"

    def test_map_bidding_strategy_type_maximize_clicks(self) -> None:
        """v23でTARGET_SPENDに統合されたMAXIMIZE_CLICKSが正しく返る"""
        assert _BIDDING_STRATEGY_MAP[9] == "MAXIMIZE_CLICKS"

    def test_map_criterion_approval_status_int(self) -> None:
        # APPROVED = 2 for AdGroupCriterionApprovalStatus
        result = map_criterion_approval_status(2)
        assert result == "APPROVED"

    def test_map_bidding_system_status_int(self) -> None:
        result = map_bidding_system_status(0)
        assert result == "UNSPECIFIED"

    def test_map_primary_status_reason_int(self) -> None:
        result = map_primary_status_reason(0)
        assert result == "UNSPECIFIED"


# ---------------------------------------------------------------------------
# エンティティ変換
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapCampaign:
    def test_基本変換(self) -> None:
        campaign = MagicMock()
        campaign.id = 12345
        campaign.name = "テストキャンペーン"
        campaign.status = 2
        campaign.campaign_budget = 5_000_000
        campaign.bidding_strategy_type = "TARGET_CPA"

        result = map_campaign(campaign)

        assert result["id"] == "12345"
        assert result["name"] == "テストキャンペーン"
        assert result["status"] == "ENABLED"
        assert result["budget_amount_micros"] == 5_000_000

    def test_オプションフィールド付き(self) -> None:
        campaign = MagicMock()
        campaign.id = 1
        campaign.name = "C1"
        campaign.status = 3
        campaign.campaign_budget = 0
        campaign.bidding_strategy_type = 2
        campaign.serving_status = 2
        campaign.primary_status = 9
        campaign.primary_status_reasons = [0]
        campaign.bidding_strategy_system_status = 0
        campaign.start_date = "2024-01-01"
        campaign.end_date = "2024-12-31"

        result = map_campaign(campaign)

        assert result["serving_status"] == "SERVING"
        assert result["primary_status"] == "LEARNING"
        assert result["start_date"] == "2024-01-01"
        assert result["end_date"] == "2024-12-31"

    def test_advertising_channel_type_SEARCH(self) -> None:
        """advertising_channel_type が "SEARCH" として返ること。"""
        campaign = MagicMock()
        campaign.id = 100
        campaign.name = "Search Campaign"
        campaign.status = 2
        campaign.campaign_budget = 0
        campaign.bidding_strategy_type = 0
        campaign.advertising_channel_type = 2  # SEARCH

        result = map_campaign(campaign)
        assert result["channel_type"] == "SEARCH"

    def test_advertising_channel_type_DISPLAY(self) -> None:
        """advertising_channel_type が "DISPLAY" として返ること。"""
        campaign = MagicMock()
        campaign.id = 200
        campaign.name = "Display Campaign"
        campaign.status = 2
        campaign.campaign_budget = 0
        campaign.bidding_strategy_type = 0
        campaign.advertising_channel_type = 3  # DISPLAY

        result = map_campaign(campaign)
        assert result["channel_type"] == "DISPLAY"


@pytest.mark.unit
class TestMapAdGroup:
    def test_基本変換(self) -> None:
        ad_group = MagicMock()
        ad_group.id = 67890
        ad_group.name = "テスト広告グループ"
        ad_group.status = 2
        ad_group.campaign = "customers/123/campaigns/456"
        ad_group.cpc_bid_micros = 100_000_000

        result = map_ad_group(ad_group)

        assert result["id"] == "67890"
        assert result["name"] == "テスト広告グループ"
        assert result["status"] == "ENABLED"

    def test_キャンペーン情報付き(self) -> None:
        ad_group = MagicMock()
        ad_group.id = 1
        ad_group.name = "AG1"
        ad_group.status = 2

        campaign = MagicMock()
        campaign.id = 999
        campaign.name = "C999"
        campaign.status = 2

        result = map_ad_group(ad_group, campaign)

        assert result["campaign_id"] == "999"
        assert result["campaign_name"] == "C999"
        assert result["campaign_status"] == "ENABLED"


@pytest.mark.unit
class TestMapKeyword:
    def test_基本変換(self) -> None:
        keyword = MagicMock()
        keyword.criterion_id = 11111
        keyword.keyword.text = "ランニングシューズ"
        keyword.keyword.match_type = "BROAD"
        keyword.status = 2
        keyword.approval_status = 2  # APPROVED (criterion)

        result = map_keyword(keyword)

        assert result["text"] == "ランニングシューズ"
        assert result["match_type"] == "BROAD"
        assert result["status"] == "ENABLED"
        assert result["approval_status"] == "APPROVED"

    def test_approval_statusなし(self) -> None:
        keyword = MagicMock(spec=["criterion_id", "keyword", "status"])
        keyword.criterion_id = 22222
        keyword.keyword.text = "テスト"
        keyword.keyword.match_type = "EXACT"
        keyword.status = 2

        result = map_keyword(keyword)

        assert "approval_status" not in result

    def test_approval_status_unspecified(self) -> None:
        """approval_status=0(UNSPECIFIED)でもマッピングされる"""
        keyword = MagicMock()
        keyword.criterion_id = 33333
        keyword.keyword.text = "テスト"
        keyword.keyword.match_type = "EXACT"
        keyword.status = 2
        keyword.approval_status = 0

        result = map_keyword(keyword)

        assert result["approval_status"] == "UNSPECIFIED"

    def test_キャンペーン_広告グループ情報付き(self) -> None:
        keyword = MagicMock()
        keyword.criterion_id = 44444
        keyword.keyword.text = "テスト"
        keyword.keyword.match_type = "PHRASE"
        keyword.status = 2
        keyword.approval_status = 2

        campaign = MagicMock()
        campaign.id = 100
        campaign.name = "C100"

        ad_group = MagicMock()
        ad_group.id = 200
        ad_group.name = "AG200"

        result = map_keyword(keyword, campaign, ad_group)

        assert result["campaign_id"] == "100"
        assert result["campaign_name"] == "C100"
        assert result["ad_group_id"] == "200"
        assert result["ad_group_name"] == "AG200"


@pytest.mark.unit
class TestMapKeywordQualityInfo:
    def test_品質スコア付きキーワード(self) -> None:
        keyword = MagicMock()
        keyword.criterion_id = 55555
        keyword.keyword.text = "テスト"
        keyword.keyword.match_type = "BROAD"
        keyword.status = 2
        keyword.approval_status = 2
        keyword.system_serving_status = 2  # ELIGIBLE
        keyword.quality_info.quality_score = 7
        keyword.quality_info.creative_quality_score = 3  # AVERAGE
        keyword.quality_info.post_click_quality_score = 4  # ABOVE_AVERAGE
        keyword.quality_info.search_predicted_ctr = 2  # BELOW_AVERAGE

        result = map_keyword_quality_info(keyword)

        assert result["quality_score"] == 7
        assert result["creative_quality_score"] == "AVERAGE"
        assert result["post_click_quality_score"] == "ABOVE_AVERAGE"
        assert result["search_predicted_ctr"] == "BELOW_AVERAGE"
        assert result["system_serving_status"] == "ELIGIBLE"

    def test_品質情報なし(self) -> None:
        keyword = MagicMock(spec=["criterion_id", "keyword", "status"])
        keyword.criterion_id = 66666
        keyword.keyword.text = "テスト"
        keyword.keyword.match_type = "EXACT"
        keyword.status = 2

        result = map_keyword_quality_info(keyword)

        assert result["quality_score"] is None
        assert result["creative_quality_score"] == "UNSPECIFIED"


@pytest.mark.unit
class TestMapPerformanceReport:
    def test_基本変換(self) -> None:
        row = MagicMock()
        row.campaign.name = "テストキャンペーン"
        row.campaign.id = 123
        row.metrics.impressions = 1000
        row.metrics.clicks = 50
        row.metrics.cost_micros = 5_000_000
        row.metrics.conversions = 3.0
        row.metrics.ctr = 0.05
        row.metrics.average_cpc = 100_000
        row.metrics.cost_per_conversion = 1_666_667

        result = map_performance_report([row])

        assert len(result) == 1
        assert result[0]["campaign_name"] == "テストキャンペーン"
        assert result[0]["metrics"]["impressions"] == 1000
        assert result[0]["metrics"]["clicks"] == 50
        assert result[0]["metrics"]["cost"] == 5.0


@pytest.mark.unit
class TestMapNegativeKeyword:
    def test_基本変換(self) -> None:
        criterion = MagicMock()
        criterion.criterion_id = 77777
        criterion.keyword.text = "無料"
        criterion.keyword.match_type = "EXACT"

        result = map_negative_keyword(criterion)

        assert result["criterion_id"] == "77777"
        assert result["keyword_text"] == "無料"
        assert result["match_type"] == "EXACT"


@pytest.mark.unit
class TestMapSearchTerm:
    def test_基本変換(self) -> None:
        row = MagicMock()
        row.search_term_view.search_term = "テスト検索語句"
        row.metrics.impressions = 500
        row.metrics.clicks = 25
        row.metrics.cost_micros = 2_500_000
        row.metrics.conversions = 1.0
        row.metrics.ctr = 0.05

        result = map_search_term(row)

        assert result["search_term"] == "テスト検索語句"
        assert result["metrics"]["impressions"] == 500
        assert result["metrics"]["cost"] == 2.5


@pytest.mark.unit
class TestMapSitelink:
    def test_基本変換(self) -> None:
        asset = MagicMock()
        asset.asset.id = 88888
        asset.asset.resource_name = "customers/123/assets/88888"
        asset.asset.sitelink_asset.link_text = "詳細はこちら"
        asset.asset.sitelink_asset.description1 = "説明1"
        asset.asset.sitelink_asset.description2 = "説明2"
        asset.asset.final_urls = ["https://example.com"]

        result = map_sitelink(asset)

        assert result["id"] == "88888"
        assert result["link_text"] == "詳細はこちら"
        assert result["final_urls"] == ["https://example.com"]


@pytest.mark.unit
class TestMapCallout:
    def test_基本変換(self) -> None:
        asset = MagicMock()
        asset.asset.id = 99999
        asset.asset.resource_name = "customers/123/assets/99999"
        asset.asset.callout_asset.callout_text = "送料無料"

        result = map_callout(asset)

        assert result["id"] == "99999"
        assert result["callout_text"] == "送料無料"


@pytest.mark.unit
class TestMapConversionAction:
    def test_基本変換(self) -> None:
        action = MagicMock()
        action.id = 10001
        action.name = "購入完了"
        action.type_ = "WEBPAGE"
        action.status = 2
        action.category = "PURCHASE"

        result = map_conversion_action(action)

        assert result["id"] == "10001"
        assert result["name"] == "購入完了"
        assert result["status"] == "ENABLED"


@pytest.mark.unit
class TestMapTagSnippet:
    def test_基本変換(self) -> None:
        snippet = MagicMock()
        snippet.type_ = "PAGE_LOAD"
        snippet.page_header = "<header>"
        snippet.event_snippet = "<event>"

        result = map_tag_snippet(snippet)

        assert result["type"] == "PAGE_LOAD"
        assert result["page_header"] == "<header>"


@pytest.mark.unit
class TestMapRecommendation:
    def test_基本変換(self) -> None:
        rec = MagicMock()
        rec.resource_name = "customers/123/recommendations/456"
        rec.type_ = "KEYWORD"
        rec.impact.base_metrics.impressions = 1000.0
        rec.impact.base_metrics.clicks = 50.0
        rec.impact.base_metrics.cost_micros = 100000
        rec.campaign = "customers/123/campaigns/789"

        result = map_recommendation(rec)

        assert result["resource_name"] == "customers/123/recommendations/456"
        assert result["impact"]["base_metrics"]["impressions"] == 1000.0


@pytest.mark.unit
class TestMapChangeEvent:
    def test_基本変換(self) -> None:
        event = MagicMock()
        event.change_date_time = "2024-01-01 12:00:00"
        event.change_resource_type = "CAMPAIGN"
        event.resource_change_operation = "UPDATE"
        event.changed_fields.paths = ["budget"]
        event.user_email = "test@example.com"

        result = map_change_event(event)

        assert result["change_date_time"] == "2024-01-01 12:00:00"
        assert result["change_resource_type"] == "CAMPAIGN"
        assert result["changed_fields"] == ["budget"]


@pytest.mark.unit
class TestMapAdPerformanceReport:
    def test_基本変換(self) -> None:
        row = MagicMock()
        row.ad_group_ad.ad.id = 111
        row.ad_group_ad.ad.type_ = 3  # RSA
        row.ad_group_ad.status = 2
        row.ad_group.id = 222
        row.ad_group.name = "AG"
        row.campaign.id = 333
        row.campaign.name = "C"
        row.metrics.impressions = 100
        row.metrics.clicks = 10
        row.metrics.cost_micros = 1_000_000
        row.metrics.conversions = 1.0
        row.metrics.ctr = 0.1
        row.metrics.average_cpc = 100_000
        row.metrics.cost_per_conversion = 1_000_000

        result = map_ad_performance_report([row])

        assert len(result) == 1
        assert result[0]["ad_id"] == "111"
        assert result[0]["campaign_name"] == "C"
        assert result[0]["metrics"]["cost"] == 1.0
