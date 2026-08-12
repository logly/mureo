"""Tests for the Google Ads mappers.

Feeds mock data to each function in mappers.py and verifies the
conversions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from google.ads.googleads.v23.common import TagSnippet
from google.ads.googleads.v23.resources.types.campaign import Campaign

from mureo.google_ads.mappers import (
    _BIDDING_STRATEGY_MAP,
    _micros_to_currency,
    _safe_float,
    _safe_int,
    _safe_str,
    map_ad_group,
    map_ad_performance_report,
    map_approval_status,
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
# Helper functions
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
# Enum conversion
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
        """MAXIMIZE_CLICKS (merged into TARGET_SPEND in v23) is returned correctly."""
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
# Entity conversion
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapCampaign:
    def test_基本変換(self) -> None:
        campaign = MagicMock()
        campaign.id = 12345
        campaign.name = "テストキャンペーン"
        campaign.status = 2
        # On the real proto this is a resource-name string, not micros. It is
        # deliberately NOT surfaced by map_campaign: the true amount comes from
        # the sibling campaign_budget.amount_micros, injected by the client.
        campaign.campaign_budget = "customers/123/campaignBudgets/456"
        campaign.bidding_strategy_type = "TARGET_CPA"

        result = map_campaign(campaign)

        assert result["id"] == "12345"
        assert result["name"] == "テストキャンペーン"
        assert result["status"] == "ENABLED"
        # map_campaign must not emit budget_amount_micros — doing so with the
        # campaign proto would leak the resource-name string and crash the
        # adapter's int() coercion.
        assert "budget_amount_micros" not in result

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

        result = map_campaign(campaign)

        assert result["serving_status"] == "SERVING"
        assert result["primary_status"] == "LEARNING"

    def test_advertising_channel_type_SEARCH(self) -> None:
        """advertising_channel_type is returned as "SEARCH"."""
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
        """advertising_channel_type is returned as "DISPLAY"."""
        campaign = MagicMock()
        campaign.id = 200
        campaign.name = "Display Campaign"
        campaign.status = 2
        campaign.campaign_budget = 0
        campaign.bidding_strategy_type = 0
        campaign.advertising_channel_type = 3  # DISPLAY

        result = map_campaign(campaign)
        assert result["channel_type"] == "DISPLAY"

    # --- Flight dates: real proto only, never MagicMock -------------------
    #
    # MagicMock answers hasattr for ANY name, so a mock-based test passes
    # against fields that do not exist. The flight-date mapping is therefore
    # pinned against the vendored v23 proto.

    @staticmethod
    def _real_campaign() -> Campaign:
        """A real v23 Campaign with the minimum map_campaign() reads."""
        campaign = Campaign()
        campaign.id = 12345
        campaign.name = "Real Proto Campaign"
        campaign.status = 2  # ENABLED
        return campaign

    def test_flight_dates_are_narrowed_to_the_date_half(self) -> None:
        """start/end_date_time map to start_date/end_date without the time."""
        campaign = self._real_campaign()
        campaign.start_date_time = "2024-01-01 00:00:00"
        campaign.end_date_time = "2024-12-31 23:59:59"

        result = map_campaign(campaign)

        assert result["start_date"] == "2024-01-01"
        assert result["end_date"] == "2024-12-31"

    def test_flight_dates_accept_the_T_separator(self) -> None:
        """The ISO ``T`` separator is narrowed the same way as a space."""
        campaign = self._real_campaign()
        campaign.start_date_time = "2024-03-05T00:00:00"
        campaign.end_date_time = "2037-12-30T23:59:59"

        result = map_campaign(campaign)

        # 2037-12-30 is Google's "no end date"; it is passed through rather
        # than translated into a sentinel of mureo's own.
        assert result["start_date"] == "2024-03-05"
        assert result["end_date"] == "2037-12-30"

    def test_unset_flight_dates_omit_the_keys(self) -> None:
        """Unset flight dates emit no key at all, not an empty string.

        Consumers such as _diagnostics test the value for truthiness via
        ``.get(..., "")``; an empty-string key would be equally falsy, but
        omitting keeps the payload honest about what the API returned.
        """
        result = map_campaign(self._real_campaign())

        assert "start_date" not in result
        assert "end_date" not in result

    def test_v23_campaign_proto_has_no_start_date_or_end_date(self) -> None:
        """Regression pin for the silent-failure mode this mapper had.

        map_campaign used to read ``campaign.start_date`` / ``campaign.end_date``
        behind ``hasattr`` guards. Those fields do not exist on the v23 proto, so
        both keys were never populated and the campaign date-range diagnosis was
        permanently dead — silently, because every test used a MagicMock, which
        answers ``hasattr`` for any name. If someone reverts to the stale
        spelling, this fails loudly.
        """
        campaign = Campaign()

        assert not hasattr(campaign, "start_date")
        assert not hasattr(campaign, "end_date")
        assert hasattr(campaign, "start_date_time")
        assert hasattr(campaign, "end_date_time")


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
        """approval_status=0 (UNSPECIFIED) is still mapped."""
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
    # Real proto only, never MagicMock: a mock answers every attribute name,
    # so the previous mock-based test passed against ``page_header``, a field
    # the v23 TagSnippet does not have. The key was therefore always empty.

    def test_global_site_tag_populates_the_page_header_key(self) -> None:
        """The global site tag is returned under the ``page_header`` key."""
        snippet = TagSnippet()
        snippet.type_ = 2  # WEBPAGE
        snippet.global_site_tag = "<script>gtag</script>"
        snippet.event_snippet = "<script>event</script>"

        result = map_tag_snippet(snippet)

        assert result["type"] == "TrackingCodeType.WEBPAGE"
        assert result["page_header"] == "<script>gtag</script>"
        assert result["event_snippet"] == "<script>event</script>"

    def test_unset_snippets_map_to_empty_strings(self) -> None:
        """An unset snippet yields "", never a stale or missing value."""
        result = map_tag_snippet(TagSnippet())

        assert result["page_header"] == ""
        assert result["event_snippet"] == ""

    def test_v23_tag_snippet_proto_has_no_page_header(self) -> None:
        """Regression pin for the silent-failure mode this mapper had.

        map_tag_snippet used to read ``snippet.page_header``, which does not
        exist on the v23 proto, so the key was permanently empty. The output
        key keeps the ``page_header`` name for the documented tool contract,
        but the read must stay on ``global_site_tag``.
        """
        snippet = TagSnippet()

        assert not hasattr(snippet, "page_header")
        assert hasattr(snippet, "global_site_tag")


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

    def test_reads_real_proto_field_names(self) -> None:
        """Drive the mapper with a REAL ``ChangeEvent``, not a MagicMock.

        A MagicMock answers ``hasattr`` for anything and returns a new mock
        for any attribute, so a misspelt field name maps to a truthy value and
        every assertion in the test above still passes. That is exactly how
        ``changed_resource_name`` — which does not exist on the proto; the
        field is ``change_resource_name`` — reached a shipped tool and a GAQL
        SELECT that the server would reject.

        A real protobuf raises ``AttributeError`` for a name it does not have,
        so every key this asserts is a name the vendored SDK actually defines.
        """
        from google.ads.googleads.v23.resources.types.change_event import (
            ChangeEvent,
        )

        event = ChangeEvent(
            resource_name="customers/1/changeEvents/2026-08-05~1~2",
            change_date_time="2026-08-05 09:14:00",
            change_resource_name="customers/1/ads/999",
            user_email="operator@example.com",
            campaign="customers/1/campaigns/111",
            ad_group="customers/1/adGroups/222",
        )
        event.changed_fields.paths.append("status")

        result = map_change_event(event)

        assert result["resource_name"] == "customers/1/changeEvents/2026-08-05~1~2"
        assert result["change_date_time"] == "2026-08-05 09:14:00"
        assert result["change_resource_name"] == "customers/1/ads/999"
        assert result["user_email"] == "operator@example.com"
        assert result["campaign"] == "customers/1/campaigns/111"
        assert result["ad_group"] == "customers/1/adGroups/222"
        assert result["changed_fields"] == ["status"]
        # Enum-valued fields are present and stringified, not dropped.
        assert result["change_resource_type"] is not None
        assert result["resource_change_operation"] is not None
        assert result["client_type"] is not None

    def test_every_mapped_key_exists_on_the_proto(self) -> None:
        """No key the mapper emits may name a field the proto does not have.

        The general form of the bug above: a grep-proof guard that fails the
        moment someone adds a field name by hand rather than from the proto.
        Keys the mapper renames deliberately are listed as exceptions.
        """
        from google.ads.googleads.v23.resources.types.change_event import (
            ChangeEvent,
        )

        declared = {f.name for f in ChangeEvent.pb(ChangeEvent()).DESCRIPTOR.fields}
        emitted = set(map_change_event(ChangeEvent()))
        assert emitted <= declared, (
            f"map_change_event emits key(s) {sorted(emitted - declared)} that name "
            f"no field on ChangeEvent. Check the spelling against the vendored "
            f"proto — a name that does not exist reads as an empty value and "
            f"fails silently."
        )


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
