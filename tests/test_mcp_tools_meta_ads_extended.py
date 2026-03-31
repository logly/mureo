"""Meta Ads 拡張ハンドラーテスト

キャンペーン、広告セット、広告、オーディエンス、クリエイティブ、ピクセル
ハンドラーをカバーする。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Meta Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# キャンペーン pause / enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCampaignPauseEnableHandlers:
    """キャンペーン pause/enable ハンドラーテスト"""

    async def test_campaigns_pause(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.pause_campaign.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.pause",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.pause_campaign.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True

    async def test_campaigns_enable(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.enable_campaign.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.campaigns.enable",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.enable_campaign.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# 広告セット get / pause / enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdSetExtendedHandlers:
    """広告セット get/pause/enable ハンドラーテスト"""

    async def test_ad_sets_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_ad_set.return_value = {"id": "20", "name": "AdSet1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.get",
                {"account_id": "act_123", "ad_set_id": "20"},
            )

        client.get_ad_set.assert_awaited_once_with("20")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "20"

    async def test_ad_sets_pause(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.pause_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.pause",
                {"account_id": "act_123", "ad_set_id": "20"},
            )

        client.pause_ad_set.assert_awaited_once_with("20")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True

    async def test_ad_sets_enable(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.enable_ad_set.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ad_sets.enable",
                {"account_id": "act_123", "ad_set_id": "20"},
            )

        client.enable_ad_set.assert_awaited_once_with("20")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# 広告 get / pause / enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdExtendedHandlers:
    """広告 get/pause/enable ハンドラーテスト"""

    async def test_ads_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_ad.return_value = {"id": "40", "name": "Ad1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.get",
                {"account_id": "act_123", "ad_id": "40"},
            )

        client.get_ad.assert_awaited_once_with("40")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "40"

    async def test_ads_pause(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.pause_ad.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.pause",
                {"account_id": "act_123", "ad_id": "40"},
            )

        client.pause_ad.assert_awaited_once_with("40")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True

    async def test_ads_enable(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.enable_ad.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.ads.enable",
                {"account_id": "act_123", "ad_id": "40"},
            )

        client.enable_ad.assert_awaited_once_with("40")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# オーディエンス get / delete / create_lookalike
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAudienceExtendedHandlers:
    """オーディエンス get/delete/create_lookalike ハンドラーテスト"""

    async def test_audiences_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_custom_audience.return_value = {"id": "50", "name": "Aud1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.audiences.get",
                {"account_id": "act_123", "audience_id": "50"},
            )

        client.get_custom_audience.assert_awaited_once_with("50")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "50"

    async def test_audiences_delete(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.delete_custom_audience.return_value = {"success": True}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.audiences.delete",
                {"account_id": "act_123", "audience_id": "50"},
            )

        client.delete_custom_audience.assert_awaited_once_with("50")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True

    async def test_audiences_create_lookalike(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_lookalike_audience.return_value = {"id": "70"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.audiences.create_lookalike",
                {
                    "account_id": "act_123",
                    "name": "Lookalike",
                    "source_audience_id": "50",
                    "country": "JP",
                    "ratio": 0.01,
                },
            )

        client.create_lookalike_audience.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "70"


# ---------------------------------------------------------------------------
# クリエイティブ list / create / create_dynamic / upload_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreativeHandlers:
    """クリエイティブ系ハンドラーテスト"""

    async def test_creatives_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_ad_creatives.return_value = [{"id": "cr_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.creatives.list",
                {"account_id": "act_123"},
            )

        client.list_ad_creatives.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "cr_1"

    async def test_creatives_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_ad_creative.return_value = {"id": "cr_2"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.creatives.create",
                {
                    "account_id": "act_123",
                    "name": "Creative1",
                    "page_id": "pg_1",
                    "link_url": "https://example.com",
                },
            )

        client.create_ad_creative.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "cr_2"

    async def test_creatives_create_dynamic(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_dynamic_creative.return_value = {"id": "cr_3"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.creatives.create_dynamic",
                {
                    "account_id": "act_123",
                    "name": "Dynamic1",
                    "page_id": "pg_1",
                    "image_hashes": ["hash1", "hash2"],
                    "bodies": ["body1"],
                    "titles": ["title1"],
                    "link_url": "https://example.com",
                },
            )

        client.create_dynamic_creative.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "cr_3"

    async def test_creatives_upload_image(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.upload_ad_image.return_value = {"hash": "abc123"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.creatives.upload_image",
                {
                    "account_id": "act_123",
                    "image_url": "https://example.com/img.png",
                },
            )

        client.upload_ad_image.assert_awaited_once_with("https://example.com/img.png")
        parsed = json.loads(result[0].text)
        assert parsed["hash"] == "abc123"


# ---------------------------------------------------------------------------
# ピクセル list / get / stats / events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPixelHandlers:
    """ピクセル系ハンドラーテスト"""

    async def test_pixels_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_ad_pixels.return_value = [{"id": "px_1"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.pixels.list",
                {"account_id": "act_123"},
            )

        client.list_ad_pixels.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "px_1"

    async def test_pixels_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_pixel.return_value = {"id": "px_1", "name": "Pixel1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.pixels.get",
                {"account_id": "act_123", "pixel_id": "px_1"},
            )

        client.get_pixel.assert_awaited_once_with("px_1")
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "px_1"

    async def test_pixels_stats(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_pixel_stats.return_value = {"events": 100}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.pixels.stats",
                {"account_id": "act_123", "pixel_id": "px_1"},
            )

        client.get_pixel_stats.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["events"] == 100

    async def test_pixels_events(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_pixel_events.return_value = [{"event": "PageView"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.pixels.events",
                {"account_id": "act_123", "pixel_id": "px_1"},
            )

        client.get_pixel_events.assert_awaited_once_with("px_1")
        parsed = json.loads(result[0].text)
        assert parsed[0]["event"] == "PageView"
