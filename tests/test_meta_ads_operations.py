"""Unit tests for Meta Ads operations.

Tests CampaignsMixin / AdSetsMixin / AdsMixin / CreativesMixin /
AudiencesMixin / PixelsMixin / InsightsMixin / AnalysisMixin with
_get / _post / _delete mocked.
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
# Helpers: factory producing mock classes wrapping each Mixin for test isolation
# ---------------------------------------------------------------------------


def _make_mock_class(mixin_cls):
    """Build a class with mocked _get/_post/_delete/_ad_account_id."""

    class MockClient(mixin_cls):
        def __init__(self):
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})
            self._delete = AsyncMock(return_value={"success": True})

    return MockClient


# ===========================================================================
# CampaignsMixin tests
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
# AdSetsMixin tests
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
        # Default targeting
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
    async def test_update_ad_set_targeting_merges_with_existing(self, client) -> None:
        # Meta replaces the whole targeting spec on write. A partial delta
        # must be merged onto the current spec so unrelated facets survive.
        client._get = AsyncMock(
            return_value={
                "id": "1",
                "targeting": {
                    "geo_locations": {"countries": ["JP"]},
                    "interests": [{"id": "6003", "name": "Tech"}],
                },
            }
        )
        await client.update_ad_set("1", targeting={"age_min": 25})
        merged = json.loads(client._post.call_args[0][1]["targeting"])
        # Unrelated keys must survive — this is the data-loss fix (#273).
        assert merged["geo_locations"] == {"countries": ["JP"]}
        assert merged["interests"] == [{"id": "6003", "name": "Tech"}]
        assert merged["age_min"] == 25

    @pytest.mark.asyncio
    async def test_update_ad_set_targeting_merge_no_existing_spec(self, client) -> None:
        # Ad set has no targeting yet (get returns no 'targeting' key): the
        # merge must fall back to {} and write the delta as-is, not crash.
        client._get = AsyncMock(return_value={"id": "1"})
        await client.update_ad_set("1", targeting={"age_min": 25})
        merged = json.loads(client._post.call_args[0][1]["targeting"])
        assert merged == {"age_min": 25}

    @pytest.mark.asyncio
    async def test_update_ad_set_targeting_delta_overrides_key(self, client) -> None:
        client._get = AsyncMock(
            return_value={
                "id": "1",
                "targeting": {"geo_locations": {"countries": ["JP"]}},
            }
        )
        await client.update_ad_set(
            "1", targeting={"geo_locations": {"countries": ["US"]}}
        )
        merged = json.loads(client._post.call_args[0][1]["targeting"])
        # A supplied top-level key replaces that key wholesale.
        assert merged["geo_locations"] == {"countries": ["US"]}

    @pytest.mark.asyncio
    async def test_update_ad_set_targeting_replace_bypasses_merge(self, client) -> None:
        client._get = AsyncMock(
            return_value={"id": "1", "targeting": {"interests": [{"id": "6003"}]}}
        )
        await client.update_ad_set(
            "1",
            targeting={"geo_locations": {"countries": ["US"]}},
            replace_targeting=True,
        )
        merged = json.loads(client._post.call_args[0][1]["targeting"])
        # Explicit opt-in to full replacement: no read, only supplied keys.
        assert merged == {"geo_locations": {"countries": ["US"]}}
        client._get.assert_not_called()

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
# AdsMixin tests
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
# CreativesMixin tests
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
        # The uploader follows redirects manually (validating each hop) and
        # gates on has_redirect_location; a terminal response must report False
        # rather than a truthy MagicMock.
        mock_resp.has_redirect_location = False

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
    async def test_create_lead_ad_creative_attaches_form_id(self, client) -> None:
        """Lead Ad creative must surface ``lead_gen_form_id`` inside
        ``link_data`` — this is the API contract that turns a normal
        link creative into a Lead Ad."""
        await client.create_lead_ad_creative(
            "LeadCreative1",
            "page1",
            "form_99",
            "https://example.com/landing",
        )
        data = client._post.call_args[0][1]
        spec = json.loads(data["object_story_spec"])
        assert spec["page_id"] == "page1"
        assert spec["link_data"]["lead_gen_form_id"] == "form_99"
        assert spec["link_data"]["link"] == "https://example.com/landing"

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_defaults_cta_to_sign_up(
        self, client
    ) -> None:
        """``SIGN_UP`` is the canonical CTA for Lead Ads — must be the
        default so the operator does not have to remember it."""
        await client.create_lead_ad_creative(
            "LeadCreative2",
            "page1",
            "form_42",
            "https://example.com",
        )
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert spec["link_data"]["call_to_action"] == {"type": "SIGN_UP"}

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_accepts_alternate_cta(self, client) -> None:
        """Lead Ads support several CTAs (LEARN_MORE, APPLY_NOW,
        GET_QUOTE, SUBSCRIBE, ...) — the helper must pass through
        whatever the caller chooses without validation."""
        await client.create_lead_ad_creative(
            "LeadCreative3",
            "page1",
            "form_42",
            "https://example.com",
            call_to_action="APPLY_NOW",
        )
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert spec["link_data"]["call_to_action"] == {"type": "APPLY_NOW"}

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_with_image_hash(self, client) -> None:
        """image_hash flows into link_data unchanged — no auto-upload."""
        await client.create_lead_ad_creative(
            "LeadCreative4",
            "page1",
            "form_42",
            "https://example.com",
            image_hash="hash_abc",
            message="本文",
            headline="見出し",
            description="説明",
        )
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert spec["link_data"]["image_hash"] == "hash_abc"
        assert spec["link_data"]["message"] == "本文"
        assert spec["link_data"]["name"] == "見出し"
        assert spec["link_data"]["description"] == "説明"

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_with_image_url_auto_uploads(
        self, client
    ) -> None:
        """An image_url triggers auto-upload (same convention as
        ``create_ad_creative``) so the operator does not need a
        separate step."""
        client.upload_ad_image = AsyncMock(
            return_value={"hash": "uploaded_hash", "url": "https://cdn/x.jpg"}
        )
        await client.create_lead_ad_creative(
            "LeadCreative5",
            "page1",
            "form_42",
            "https://example.com",
            image_url="https://img.example.com/x.jpg",
        )
        client.upload_ad_image.assert_awaited_once_with("https://img.example.com/x.jpg")
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert spec["link_data"]["image_hash"] == "uploaded_hash"

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_link_url_present_without_image(
        self, client
    ) -> None:
        """Meta requires ``link_data.link`` even on pure Lead Ads
        (used as fallback landing page on placements that cannot
        render the in-app form). The helper must surface it
        regardless of whether an image is supplied."""
        await client.create_lead_ad_creative(
            "LeadCreativeNoImage",
            "page1",
            "form_42",
            "https://example.com/fallback",
        )
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert spec["link_data"]["link"] == "https://example.com/fallback"
        # No image fields when neither image_hash nor image_url supplied.
        assert "image_hash" not in spec["link_data"]

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_calls_correct_endpoint(self, client) -> None:
        """The POST goes to ``/<ad_account_id>/adcreatives`` — same
        endpoint as ``create_ad_creative``, only the payload differs."""
        await client.create_lead_ad_creative(
            "LeadCreative6",
            "page1",
            "form_42",
            "https://example.com",
        )
        path = client._post.call_args[0][0]
        assert path == "/act_123/adcreatives"

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_with_video_uses_video_data(
        self, client
    ) -> None:
        """Lead Ad with video_id uses ``video_data`` payload with the
        lead_gen_form_id nested under ``call_to_action.value`` — that's
        how Meta routes the Instant Form attachment for video creatives
        (not under ``link_data`` like image creatives)."""
        await client.create_lead_ad_creative(
            "LeadCreativeVideo",
            "page1",
            "form_99",
            "https://example.com/landing",
            video_id="video_abc",
            image_hash="thumb_hash",
            message="本文",
            headline="見出し",
        )
        spec = json.loads(client._post.call_args[0][1]["object_story_spec"])
        assert "video_data" in spec
        assert "link_data" not in spec
        vd = spec["video_data"]
        assert vd["video_id"] == "video_abc"
        # thumbnail
        assert vd["image_hash"] == "thumb_hash"
        # message / title
        assert vd["message"] == "本文"
        assert vd["title"] == "見出し"
        # CTA value carries lead_gen_form_id + link
        assert vd["call_to_action"]["type"] == "SIGN_UP"
        assert vd["call_to_action"]["value"]["lead_gen_form_id"] == "form_99"
        assert vd["call_to_action"]["value"]["link"] == "https://example.com/landing"

    @pytest.mark.asyncio
    async def test_create_lead_ad_creative_rejects_video_and_image_together(
        self, client
    ) -> None:
        """``video_id`` plus ``image_url`` is ambiguous. ``image_url``'s
        auto-upload semantics belong to image mode; video mode wants
        an explicit thumbnail ``image_hash``. The helper rejects
        the combination at the call site rather than silently
        picking one branch."""
        with pytest.raises(ValueError) as excinfo:
            await client.create_lead_ad_creative(
                "LeadCreativeBoth",
                "page1",
                "form_99",
                "https://example.com",
                video_id="video_abc",
                image_url="https://img.example.com/x.jpg",
            )
        assert "image_url" in str(excinfo.value) and "video_id" in str(excinfo.value)

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
# AudiencesMixin tests
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
        # subtype not sent to API (replaced by rule in v21+)
        assert "subtype" not in data
        assert data["customer_file_source"] == "USER_PROVIDED_ONLY"
        # WEBSITE + pixel_id auto-generates a rule
        assert "rule" in data
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
# PixelsMixin tests
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
        # Verify the path
        assert "/px1/stats" in client._get.call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_pixel_stats_default_period(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        await client.get_pixel_stats("px1")
        # Default: last_7d → 7 days

    @pytest.mark.asyncio
    async def test_get_pixel_events(self, client) -> None:
        client._get = AsyncMock(
            return_value={"data": [{"event_name": "Purchase", "count": 50}]}
        )
        result = await client.get_pixel_events("px1")
        assert len(result) == 1


# ===========================================================================
# InsightsMixin tests
# ===========================================================================


@pytest.mark.unit
class TestInsightsMixin:
    @pytest.fixture()
    def client(self):
        cls = _make_mock_class(InsightsMixin)
        # InsightsMixin also exposes get_breakdown_report.
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
    async def test_get_performance_report_forwards_custom_range_as_time_range(
        self, client
    ) -> None:
        """Issue #134 regression: ``YYYY-MM-DD..YYYY-MM-DD`` must be
        forwarded to Meta as ``time_range``, not silently degraded to
        ``last_7d`` via ``date_preset``."""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_performance_report(period="2026-05-01..2026-05-14")
        params = client._get.call_args[0][1]
        assert "date_preset" not in params, (
            f"custom range must not be coerced into a date_preset; "
            f"got params={params}"
        )
        assert params["time_range"] == json.dumps(
            {"since": "2026-05-01", "until": "2026-05-14"}
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("preset", ["last_14d", "last_90d"])
    async def test_get_performance_report_accepts_documented_presets(
        self, client, preset
    ) -> None:
        """``last_14d`` and ``last_90d`` are advertised in the tool
        description; #134 was that they silently fell back to
        ``last_7d``. Now they must round-trip into ``date_preset``."""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_performance_report(period=preset)
        params = client._get.call_args[0][1]
        assert params.get("date_preset") == preset

    @pytest.mark.asyncio
    async def test_get_performance_report_rejects_unknown_period(self, client) -> None:
        """No silent fallback. The pre-fix code accepted any string and
        returned last_7d data — silently misleading. Now an unknown
        ``period`` must raise so the operator hears about it."""
        client._get = AsyncMock(return_value={"data": []})
        with pytest.raises(ValueError):
            await client.get_performance_report(period="last_60d")

    @pytest.mark.asyncio
    async def test_analyze_performance_no_data(self, client) -> None:
        client._get = AsyncMock(return_value={"data": []})
        result = await client.analyze_performance()
        assert result["current"]["impressions"] == 0
        assert result["insights"] == []

    @pytest.mark.asyncio
    async def test_analyze_performance_with_decline(self, client) -> None:
        """Insight when impressions drop 20% or more."""

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
        # analyze_audience calls get_breakdown_report, so it must be implemented.
        # InsightsMixin.get_breakdown_report uses _get.
        result = await client.analyze_audience("camp1")
        assert len(result["segments"]) == 2
        # Insight for CV=0 and spend > 0.
        assert any("0 CV" in i for i in result["insights"])

    @pytest.mark.asyncio
    async def test_get_breakdown_report(self, client) -> None:
        client._get = AsyncMock(return_value={"data": [{"age": "25-34"}]})
        result = await client.get_breakdown_report("camp1", "age", "last_7d")
        assert len(result) == 1


# ===========================================================================
# AnalysisMixin helper-function tests
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
# AnalysisMixin tests
# ===========================================================================


@pytest.mark.unit
class TestAnalysisMixin:
    @pytest.fixture()
    def client(self):
        class MockAnalysisClient(AnalysisMixin):
            def __init__(self):
                self._ad_account_id = "act_123"
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
        # Instagram has CV=0 with non-zero cost → insight.
        assert any("instagram" in i for i in result["insights"])

    @pytest.mark.asyncio
    async def test_investigate_cost_no_data(self, client) -> None:
        result = await client.investigate_cost("camp1")
        assert "No performance data" in result["message"]

    @pytest.mark.asyncio
    async def test_investigate_cost_with_increase(self, client) -> None:
        """Detect an ad-spend increase."""

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
    async def test_investigate_cost_previous_window_does_not_overlap_current(
        self, client
    ) -> None:
        """Issue #134 regression: the pre-fix code mapped
        ``last_7d``-as-current to ``last_30d``-as-previous, which is a
        SUPERSET (it overlaps last_7d entirely). Now the previous
        window must be a same-length block that does not overlap.

        We capture the ``period`` strings passed to
        ``get_performance_report`` and verify the previous one parses
        to a 7-day range immediately before today's last 7 days."""
        from datetime import date

        from mureo.meta_ads._period import resolve_period

        captured: list[str] = []

        async def fake_report(**kwargs):
            captured.append(kwargs.get("period", ""))
            return [{"spend": "1", "cpc": "1", "clicks": "1"}]

        client.get_performance_report = AsyncMock(side_effect=fake_report)
        await client.investigate_cost("camp1", period="last_7d")
        assert captured[0] == "last_7d"
        prev_str = captured[1]
        # Must NOT be the broken pre-fix value.
        assert prev_str != "last_30d", (
            "previous-window must not be the last_30d superset of "
            "last_7d (pre-#134 bug)"
        )
        prev_rp = resolve_period(prev_str)
        # And the parsed window must be 7 days long and end before today.
        assert prev_rp.days == 7
        assert prev_rp.time_range is not None
        prev_until_str = prev_rp.time_range[1]
        assert date.fromisoformat(prev_until_str) < date.today()

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
        """Detect ads whose CTR is at most half of the average."""
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
        """Detect high-cost ads with zero conversions."""
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
        """Detect CPA disparity."""
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
