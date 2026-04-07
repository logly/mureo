"""Meta Ads operations ユニットテスト

CampaignsMixin / AdSetsMixin / AdsMixin / CreativesMixin /
AudiencesMixin / PixelsMixin / InsightsMixin / AnalysisMixin を
_get / _post / _delete をモックしてテストする。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.meta_ads._campaigns import CampaignsMixin
from mureo.meta_ads._ad_sets import AdSetsMixin
from mureo.meta_ads._ads import AdsMixin
from mureo.meta_ads._creatives import CreativesMixin
from mureo.meta_ads._audiences import AudiencesMixin
from mureo.meta_ads._pixels import PixelsMixin
from mureo.meta_ads._insights import InsightsMixin
from mureo.meta_ads._analysis import AnalysisMixin, _safe_float, _extract_cv


# ---------------------------------------------------------------------------
# ヘルパー: 各Mixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_mock_class(mixin_cls):
    """Mixinにモック _get/_post/_delete/_ad_account_id を付与したクラスを生成"""

    class MockClient(mixin_cls):
        def __init__(self):
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})
            self._delete = AsyncMock(return_value={"success": True})

    return MockClient


# ===========================================================================
# CampaignsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestCampaignsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(CampaignsMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_campaigns(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "1", "name": "C1"}]})
        result = await client.list_campaigns()
        assert len(result) == 1
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/act_123/campaigns" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_campaigns_with_status_filter(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.list_campaigns(status_filter="ACTIVE")
        call_args = client._get.call_args
        params = call_args[0][1]
        assert "filtering" in params

    @pytest.mark.asyncio
    async def test_get_campaign(self, client) -> None:
        client._get = AsyncMock(return_value={"id": "1", "name": "C1"})
        result = await client.get_campaign("1")
        assert result["id"] == "1"

    @pytest.mark.asyncio
    async def test_create_campaign(self, client) -> None:
        result = await client.create_campaign("Test", "CONVERSIONS")
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/act_123/campaigns" in call_args[0][0]
        data = call_args[0][1]
        assert data["name"] == "Test"
        assert data["objective"] == "CONVERSIONS"
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_create_campaign_with_budget(self, client) -> None:
        await client.create_campaign("Test", "CONVERSIONS", daily_budget=5000)
        data = client._post.call_args[0][1]
        assert data["daily_budget"] == 5000

    @pytest.mark.asyncio
    async def test_create_campaign_special_ad_categories(self, client) -> None:
        await client.create_campaign(
            "Test", "CONVERSIONS", special_ad_categories=["HOUSING"]
        )
        data = client._post.call_args[0][1]
        assert json.loads(data["special_ad_categories"]) == ["HOUSING"]

    @pytest.mark.asyncio
    async def test_update_campaign(self, client) -> None:
        await client.update_campaign("1", name="Updated", status="ACTIVE")
        call_args = client._post.call_args
        assert "/1" in call_args[0][0]
        data = call_args[0][1]
        assert data["name"] == "Updated"
        assert data["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_update_campaign_skips_none(self, client) -> None:
        await client.update_campaign("1", name=None, status="ACTIVE")
        data = client._post.call_args[0][1]
        assert "name" not in data

    @pytest.mark.asyncio
    async def test_pause_campaign(self, client) -> None:
        await client.pause_campaign("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_enable_campaign(self, client) -> None:
        await client.enable_campaign("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "ACTIVE"


# ===========================================================================
# AdSetsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestAdSetsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(AdSetsMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_ad_sets_account_level(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "1"}]})
        result = await client.list_ad_sets()
        assert len(result) == 1
        assert "/act_123/adsets" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_ad_sets_by_campaign(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.list_ad_sets("camp1")
        assert "/camp1/adsets" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_ad_set(self, client) -> None:
        client._get = AsyncMock(return_value={"id": "1"})
        result = await client.get_ad_set("1")
        assert result["id"] == "1"

    @pytest.mark.asyncio
    async def test_create_ad_set(self, client) -> None:
        await client.create_ad_set("camp1", "AdSet1", 5000)
        data = client._post.call_args[0][1]
        assert data["campaign_id"] == "camp1"
        assert data["name"] == "AdSet1"
        assert data["daily_budget"] == 5000
        # デフォルトターゲティング
        targeting = json.loads(data["targeting"])
        assert targeting["geo_locations"]["countries"] == ["JP"]

    @pytest.mark.asyncio
    async def test_create_ad_set_with_dynamic_creative(self, client) -> None:
        await client.create_ad_set("camp1", "DC Set", 3000, use_dynamic_creative=True)
        data = client._post.call_args[0][1]
        assert data["use_dynamic_creative"] is True

    @pytest.mark.asyncio
    async def test_create_ad_set_custom_targeting(self, client) -> None:
        targeting = {"geo_locations": {"countries": ["US"]}}
        await client.create_ad_set("camp1", "US Set", 3000, targeting=targeting)
        data = client._post.call_args[0][1]
        assert json.loads(data["targeting"]) == targeting

    @pytest.mark.asyncio
    async def test_update_ad_set(self, client) -> None:
        await client.update_ad_set("1", name="Updated")
        data = client._post.call_args[0][1]
        assert data["name"] == "Updated"

    @pytest.mark.asyncio
    async def test_update_ad_set_targeting_serialized(self, client) -> None:
        targeting = {"geo_locations": {"countries": ["JP"]}}
        await client.update_ad_set("1", targeting=targeting)
        data = client._post.call_args[0][1]
        assert json.loads(data["targeting"]) == targeting

    @pytest.mark.asyncio
    async def test_pause_ad_set(self, client) -> None:
        await client.pause_ad_set("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_enable_ad_set(self, client) -> None:
        await client.enable_ad_set("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "ACTIVE"


# ===========================================================================
# AdsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestAdsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(AdsMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_ads_account_level(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "1"}]})
        result = await client.list_ads()
        assert len(result) == 1
        assert "/act_123/ads" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_ads_by_ad_set(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.list_ads("adset1")
        assert "/adset1/ads" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_ad(self, client) -> None:
        client._get = AsyncMock(return_value={"id": "1"})
        result = await client.get_ad("1")
        assert result["id"] == "1"

    @pytest.mark.asyncio
    async def test_create_ad(self, client) -> None:
        await client.create_ad("adset1", "Ad1", "creative1")
        data = client._post.call_args[0][1]
        assert data["name"] == "Ad1"
        assert data["adset_id"] == "adset1"
        creative = json.loads(data["creative"])
        assert creative["creative_id"] == "creative1"

    @pytest.mark.asyncio
    async def test_update_ad(self, client) -> None:
        await client.update_ad("1", name="Updated", status="ACTIVE")
        data = client._post.call_args[0][1]
        assert data["name"] == "Updated"
        assert data["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_pause_ad(self, client) -> None:
        await client.pause_ad("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_enable_ad(self, client) -> None:
        await client.enable_ad("1")
        data = client._post.call_args[0][1]
        assert data["status"] == "ACTIVE"


# ===========================================================================
# CreativesMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestCreativesMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(CreativesMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_ad_creatives(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "1"}]})
        result = await client.list_ad_creatives()
        assert len(result) == 1
        assert "/act_123/adcreatives" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_create_ad_creative_with_image_url(self, client) -> None:
        # image_url is auto-uploaded to get image_hash
        client.upload_ad_image = AsyncMock(
            return_value={"hash": "abc123", "url": "https://img.example.com/img.jpg"}
        )
        await client.create_ad_creative(
            "Creative1",
            "page1",
            "https://example.com",
            image_url="https://img.example.com/img.jpg",
            headline="見出し",
            message="本文",
            description="説明",
            call_to_action="LEARN_MORE",
        )
        client.upload_ad_image.assert_awaited_once_with(
            "https://img.example.com/img.jpg"
        )
        data = client._post.call_args[0][1]
        assert data["name"] == "Creative1"
        spec = json.loads(data["object_story_spec"])
        assert spec["page_id"] == "page1"
        assert spec["link_data"]["image_hash"] == "abc123"
        assert spec["link_data"]["name"] == "見出し"
        assert spec["link_data"]["call_to_action"] == {"type": "LEARN_MORE"}

    @pytest.mark.asyncio
    async def test_create_ad_creative_with_image_hash(self, client) -> None:
        await client.create_ad_creative(
            "Creative2",
            "page1",
            "https://example.com",
            image_hash="abc123",
        )
        data = client._post.call_args[0][1]
        spec = json.loads(data["object_story_spec"])
        assert spec["link_data"]["image_hash"] == "abc123"
        assert "image_url" not in spec["link_data"]

    @pytest.mark.asyncio
    async def test_upload_ad_image_success(self, client) -> None:
        # Mock image download
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-image-bytes"
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        client._post = AsyncMock(
            return_value={
                "images": {"img.jpg": {"hash": "abc", "url": "https://cdn/img.jpg"}}
            }
        )
        with patch(
            "mureo.meta_ads._creatives.httpx.AsyncClient", return_value=mock_http
        ):
            result = await client.upload_ad_image("https://example.com/img.jpg")
        assert result["hash"] == "abc"
        assert result["url"] == "https://cdn/img.jpg"
        # Verify base64 bytes were sent
        post_data = client._post.call_args[0][1]
        assert "bytes" in post_data

    @pytest.mark.asyncio
    async def test_upload_ad_image_failure(self, client) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-image-bytes"
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        client._post = AsyncMock(return_value={"images": None})
        with patch(
            "mureo.meta_ads._creatives.httpx.AsyncClient", return_value=mock_http
        ):
            result = await client.upload_ad_image("https://example.com/bad.jpg")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_dynamic_creative(self, client) -> None:
        await client.create_dynamic_creative(
            "DC1",
            "page1",
            image_hashes=["h1", "h2"],
            bodies=["body1", "body2"],
            titles=["title1", "title2"],
            link_url="https://example.com",
            descriptions=["desc1"],
            call_to_actions=["LEARN_MORE", "SIGN_UP"],
        )
        data = client._post.call_args[0][1]
        spec = json.loads(data["object_story_spec"])
        assert spec["page_id"] == "page1"
        feed = json.loads(data["asset_feed_spec"])
        assert len(feed["images"]) == 2
        assert len(feed["bodies"]) == 2
        assert len(feed["titles"]) == 2
        assert len(feed["descriptions"]) == 1
        assert feed["call_to_action_types"] == ["LEARN_MORE", "SIGN_UP"]


# ===========================================================================
# AudiencesMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestAudiencesMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(AudiencesMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_custom_audiences(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "1"}]})
        result = await client.list_custom_audiences()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_custom_audience(self, client) -> None:
        client._get = AsyncMock(return_value={"id": "1", "name": "Audience1"})
        result = await client.get_custom_audience("1")
        assert result["name"] == "Audience1"

    @pytest.mark.asyncio
    async def test_create_custom_audience(self, client) -> None:
        await client.create_custom_audience(
            "WebVisitors",
            "WEBSITE",
            description="サイト訪問者",
            retention_days=30,
            rule={"inclusions": {"operator": "or"}},
            pixel_id="pixel1",
        )
        data = client._post.call_args[0][1]
        assert data["name"] == "WebVisitors"
        assert data["subtype"] == "WEBSITE"
        assert data["retention_days"] == 30
        assert data["pixel_id"] == "pixel1"
        assert json.loads(data["rule"]) == {"inclusions": {"operator": "or"}}

    @pytest.mark.asyncio
    async def test_delete_custom_audience(self, client) -> None:
        result = await client.delete_custom_audience("1")
        client._delete.assert_called_once_with("/1")
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_create_lookalike_audience(self, client) -> None:
        await client.create_lookalike_audience("Lookalike1", "source1", "JP", 0.05)
        data = client._post.call_args[0][1]
        assert data["name"] == "Lookalike1"
        assert data["subtype"] == "LOOKALIKE"
        spec = json.loads(data["lookalike_spec"])
        assert spec["origin_audience_id"] == "source1"
        assert spec["ratio"] == 0.05
        assert spec["country"] == "JP"

    @pytest.mark.asyncio
    async def test_create_lookalike_audience_multi_country(self, client) -> None:
        await client.create_lookalike_audience(
            "Lookalike2", "source1", ["JP", "US"], 0.10, starting_ratio=0.02
        )
        data = client._post.call_args[0][1]
        spec = json.loads(data["lookalike_spec"])
        assert spec["country"] == ["JP", "US"]
        assert spec["starting_ratio"] == 0.02


# ===========================================================================
# PixelsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestPixelsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(PixelsMixin)
        return cls()

    @pytest.mark.asyncio
    async def test_list_ad_pixels(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"id": "px1"}]})
        result = await client.list_ad_pixels()
        assert len(result) == 1
        assert "/act_123/adspixels" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_pixel(self, client) -> None:
        client._get = AsyncMock(return_value={"id": "px1", "name": "Main Pixel"})
        result = await client.get_pixel("px1")
        assert result["name"] == "Main Pixel"

    @pytest.mark.asyncio
    async def test_get_pixel_stats(self, client) -> None:
        client._get = AsyncMock(
            return_value={"data": [{"event": "PageView", "count": 100}]}
        )
        result = await client.get_pixel_stats("px1", "last_30d")
        assert len(result) == 1
        # パスの確認
        assert "/px1/stats" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_pixel_stats_default_period(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.get_pixel_stats("px1")
        # デフォルト: last_7d → 7日間

    @pytest.mark.asyncio
    async def test_get_pixel_events(self, client) -> None:
        client._get = AsyncMock(
            return_value={"data": [{"event_name": "Purchase", "count": 50}]}
        )
        result = await client.get_pixel_events("px1")
        assert len(result) == 1


# ===========================================================================
# InsightsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestInsightsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(InsightsMixin)
        # InsightsMixinはget_breakdown_reportも持つ
        return cls()

    @pytest.mark.asyncio
    async def test_get_performance_report_account_level(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"campaign_id": "1"}]})
        result = await client.get_performance_report()
        assert len(result) == 1
        assert "/act_123/insights" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_performance_report_campaign_level(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.get_performance_report(campaign_id="camp1")
        assert "/camp1/insights" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_analyze_performance_no_data(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        result = await client.analyze_performance()
        assert result["current"]["impressions"] == 0
        assert result["insights"] == []

    @pytest.mark.asyncio
    async def test_analyze_performance_with_decline(self, client) -> None:
        """表示回数が20%以上減少した場合のインサイト"""

        async def fake_get(path, params):
            period = params.get("date_preset", "")
            if period == "last_7d":
                return {
                    "data": [{"impressions": "800", "clicks": "40", "spend": "5000"}]
                }
            else:
                return {
                    "data": [{"impressions": "1200", "clicks": "60", "spend": "3000"}]
                }

        client._get = AsyncMock(side_effect=fake_get)
        result = await client.analyze_performance(period="last_7d")
        assert any("decreased" in i.lower() for i in result["insights"])

    @pytest.mark.asyncio
    async def test_analyze_audience_no_data(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        result = await client.analyze_audience("camp1")
        assert result["message"] == "No breakdown data available"

    @pytest.mark.asyncio
    async def test_analyze_audience_with_segments(self, client) -> None:
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "age": "25-34",
                        "gender": "male",
                        "impressions": "1000",
                        "clicks": "50",
                        "spend": "500",
                        "ctr": "5.0",
                        "actions": [{"action_type": "purchase", "value": "3"}],
                    },
                    {
                        "age": "35-44",
                        "gender": "female",
                        "impressions": "800",
                        "clicks": "20",
                        "spend": "1000",
                        "ctr": "2.5",
                        "actions": [],
                    },
                ]
            }
        )
        # analyze_audience は get_breakdown_report を呼ぶので実装が必要
        # InsightsMixin.get_breakdown_report は _get を使う
        result = await client.analyze_audience("camp1")
        assert len(result["segments"]) == 2
        # CV0 + spend > 0 のインサイト
        assert any("0 CV" in i for i in result["insights"])

    @pytest.mark.asyncio
    async def test_get_breakdown_report(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"age": "25-34"}]})
        result = await client.get_breakdown_report("camp1", "age", "last_7d")
        assert len(result) == 1


# ===========================================================================
# AnalysisMixin ヘルパー関数テスト
# ===========================================================================


@pytest.mark.unit
class TestAnalysisHelpers:
    def test_safe_float(self) -> None:
        assert _safe_float("3.14") == 3.14
        assert _safe_float(None) == 0.0
        assert _safe_float("") == 0.0
        assert _safe_float("bad") == 0.0
        assert _safe_float(0) == 0.0

    def test_extract_cv(self) -> None:
        row = {
            "actions": [
                {"action_type": "purchase", "value": "5"},
                {"action_type": "lead", "value": "3"},
                {"action_type": "link_click", "value": "100"},
            ]
        }
        assert _extract_cv(row) == 8.0

    def test_extract_cv_no_actions(self) -> None:
        assert _extract_cv({}) == 0.0
        assert _extract_cv({"actions": None}) == 0.0
        assert _extract_cv({"actions": "invalid"}) == 0.0


# ===========================================================================
# AnalysisMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestAnalysisMixin:
    @pytest.fixture()
    def client(self):
        class MockAnalysisClient(AnalysisMixin):
            def __init__(self):
                self.get_performance_report = AsyncMock(return_value=[])
                self.get_breakdown_report = AsyncMock(return_value=[])

        return MockAnalysisClient()

    @pytest.mark.asyncio
    async def test_analyze_placements_no_data(self, client) -> None:
        result = await client.analyze_placements("camp1")
        assert result["message"] == "No placement data available"

    @pytest.mark.asyncio
    async def test_analyze_placements_with_data(self, client) -> None:
        client.get_breakdown_report = AsyncMock(
            return_value=[
                {
                    "publisher_platform": "facebook",
                    "impressions": "1000",
                    "clicks": "50",
                    "spend": "500",
                    "ctr": "5.0",
                    "actions": [{"action_type": "purchase", "value": "5"}],
                },
                {
                    "publisher_platform": "instagram",
                    "impressions": "500",
                    "clicks": "10",
                    "spend": "300",
                    "ctr": "2.0",
                    "actions": [],
                },
            ]
        )
        result = await client.analyze_placements("camp1")
        assert len(result["placements"]) == 2
        # instagramはCV0でコスト発生 → insight
        assert any("instagram" in i for i in result["insights"])

    @pytest.mark.asyncio
    async def test_investigate_cost_no_data(self, client) -> None:
        result = await client.investigate_cost("camp1")
        assert "No performance data" in result["message"]

    @pytest.mark.asyncio
    async def test_investigate_cost_with_increase(self, client) -> None:
        """広告費増加の検出"""

        async def fake_report(**kwargs):
            period = kwargs.get("period", "")
            if period == "last_7d":
                return [{"spend": "1000", "cpc": "100", "clicks": "10"}]
            else:
                return [{"spend": "500", "cpc": "50", "clicks": "5"}]

        client.get_performance_report = AsyncMock(side_effect=fake_report)
        result = await client.investigate_cost("camp1")
        assert len(result["findings"]) > 0
        assert any("increased" in f.lower() for f in result["findings"])

    @pytest.mark.asyncio
    async def test_compare_ads_no_data(self, client) -> None:
        result = await client.compare_ads("adset1")
        assert result["error"] == "No ads found for the specified ad_set_id"
        assert result["ads"] == []

    @pytest.mark.asyncio
    async def test_compare_ads_with_data(self, client) -> None:
        client.get_performance_report = AsyncMock(
            return_value=[
                {
                    "ad_id": "1",
                    "ad_name": "Ad A",
                    "adset_id": "adset1",
                    "impressions": "1000",
                    "clicks": "50",
                    "spend": "500",
                    "ctr": "5.0",
                    "cpc": "10",
                    "actions": [{"action_type": "purchase", "value": "5"}],
                },
                {
                    "ad_id": "2",
                    "ad_name": "Ad B",
                    "adset_id": "adset1",
                    "impressions": "1000",
                    "clicks": "20",
                    "spend": "400",
                    "ctr": "2.0",
                    "cpc": "20",
                    "actions": [],
                },
            ]
        )
        result = await client.compare_ads("adset1")
        assert result["winner"] is not None
        assert len(result["ads"]) == 2

    @pytest.mark.asyncio
    async def test_suggest_creative_improvements_no_data(self, client) -> None:
        result = await client.suggest_creative_improvements("camp1")
        assert result["ad_count"] == 0
        assert result["suggestions"] == []

    @pytest.mark.asyncio
    async def test_suggest_creative_improvements_low_ctr(self, client) -> None:
        """平均CTRの半分以下の広告を検出"""
        client.get_performance_report = AsyncMock(
            return_value=[
                {
                    "ad_id": "1",
                    "ad_name": "Good Ad",
                    "ctr": "5.0",
                    "spend": "500",
                    "actions": [{"action_type": "purchase", "value": "5"}],
                },
                {
                    "ad_id": "2",
                    "ad_name": "Bad Ad",
                    "ctr": "0.5",
                    "spend": "300",
                    "actions": [],
                },
            ]
        )
        result = await client.suggest_creative_improvements("camp1")
        low_ctr = [s for s in result["suggestions"] if s["type"] == "low_ctr"]
        assert len(low_ctr) >= 1
        assert low_ctr[0]["ad_name"] == "Bad Ad"

    @pytest.mark.asyncio
    async def test_suggest_creative_improvements_zero_cv(self, client) -> None:
        """CV0で高コストの広告を検出"""
        client.get_performance_report = AsyncMock(
            return_value=[
                {
                    "ad_id": "1",
                    "ad_name": "CV0 Ad",
                    "ctr": "3.0",
                    "spend": "1000",
                    "actions": [],
                },
            ]
        )
        result = await client.suggest_creative_improvements("camp1")
        zero_cv = [s for s in result["suggestions"] if s["type"] == "zero_cv"]
        assert len(zero_cv) >= 1

    @pytest.mark.asyncio
    async def test_suggest_creative_improvements_high_cpa(self, client) -> None:
        """CPA格差の検出"""
        client.get_performance_report = AsyncMock(
            return_value=[
                {
                    "ad_id": "1",
                    "ad_name": "Efficient",
                    "ctr": "5.0",
                    "spend": "1000",
                    "actions": [{"action_type": "purchase", "value": "10"}],
                },
                {
                    "ad_id": "2",
                    "ad_name": "Expensive",
                    "ctr": "3.0",
                    "spend": "5000",
                    "actions": [{"action_type": "purchase", "value": "5"}],
                },
            ]
        )
        result = await client.suggest_creative_improvements("camp1")
        high_cpa = [s for s in result["suggestions"] if s["type"] == "high_cpa"]
        assert len(high_cpa) >= 1
