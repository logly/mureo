"""Tests for the extended Meta Ads handlers.

Covers the campaign, ad set, ad, audience, creative, and pixel
handlers.
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
# Helpers
# ---------------------------------------------------------------------------


def _mock_meta_ads_context():
    """Return mocks for Meta Ads credentials and the API client."""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


# ---------------------------------------------------------------------------
# Campaign pause / enable
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _standalone_meta_ads():
    """Pin these handler tests to STANDALONE (untenanted) Meta Ads.

    Meta Ads gained workspace scoping (#411, mirroring Search Console's
    #375): when a ``mureo.runtime_context_factory`` is installed AND its
    store is a shared-auth multi-account backend, an undeclared
    ``meta_account_ids`` fail-closes every account_id. A dev box carrying such a
    plugin would therefore break these standalone assertions. Neutralize
    the scoping seam so this module always exercises the unrestricted
    path; the scoped behavior lives in test_account_id_tenant_scope.py.
    """
    with patch(
        "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
        return_value=None,
    ):
        yield


@pytest.mark.unit
class TestCampaignPauseEnableHandlers:
    """Campaign pause/enable handler tests."""

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
                "meta_ads_campaigns_pause",
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
                "meta_ads_campaigns_enable",
                {"account_id": "act_123", "campaign_id": "456"},
            )

        client.enable_campaign.assert_awaited_once_with("456")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# Ad set get / pause / enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdSetExtendedHandlers:
    """Ad set get/pause/enable handler tests."""

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
                "meta_ads_ad_sets_get",
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
                "meta_ads_ad_sets_pause",
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
                "meta_ads_ad_sets_enable",
                {"account_id": "act_123", "ad_set_id": "20"},
            )

        client.enable_ad_set.assert_awaited_once_with("20")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# Ad get / pause / enable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdExtendedHandlers:
    """Ad get/pause/enable handler tests."""

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
                "meta_ads_ads_get",
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
                "meta_ads_ads_pause",
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
                "meta_ads_ads_enable",
                {"account_id": "act_123", "ad_id": "40"},
            )

        client.enable_ad.assert_awaited_once_with("40")
        parsed = json.loads(result[0].text)
        assert parsed["success"] is True


# ---------------------------------------------------------------------------
# Audience get / delete / create_lookalike
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAudienceExtendedHandlers:
    """Audience get/delete/create_lookalike handler tests."""

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
                "meta_ads_audiences_get",
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
                "meta_ads_audiences_delete",
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
                "meta_ads_audiences_create_lookalike",
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
# Creative list / create / create_dynamic / upload_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreativeHandlers:
    """Creative-related handler tests."""

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
                "meta_ads_creatives_list",
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
                "meta_ads_creatives_create",
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

    async def test_creatives_create_lead(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_lead_ad_creative.return_value = {"id": "cr_lead_1"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_creatives_create_lead",
                {
                    "account_id": "act_123",
                    "name": "LeadCreative",
                    "page_id": "pg_1",
                    "form_id": "form_42",
                    "link_url": "https://example.com",
                    "call_to_action": "APPLY_NOW",
                },
            )

        client.create_lead_ad_creative.assert_awaited_once()
        kwargs = client.create_lead_ad_creative.call_args.kwargs
        assert kwargs["form_id"] == "form_42"
        assert kwargs["call_to_action"] == "APPLY_NOW"
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "cr_lead_1"

    async def test_creatives_create_lead_requires_form_id(self) -> None:
        """form_id is a hard requirement of the Lead Ad spec — omit it
        and the handler must raise rather than POST a malformed
        payload."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            with pytest.raises(Exception):  # noqa: B017, PT011
                await mod.handle_tool(
                    "meta_ads_creatives_create_lead",
                    {
                        "account_id": "act_123",
                        "name": "LeadCreative",
                        "page_id": "pg_1",
                        # form_id missing
                        "link_url": "https://example.com",
                    },
                )

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
                "meta_ads_creatives_create_dynamic",
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
                "meta_ads_creatives_upload_image",
                {
                    "account_id": "act_123",
                    "image_url": "https://example.com/img.png",
                },
            )

        client.upload_ad_image.assert_awaited_once_with("https://example.com/img.png")
        parsed = json.loads(result[0].text)
        assert parsed["hash"] == "abc123"


# ---------------------------------------------------------------------------
# Pixel list / get / stats / events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPixelHandlers:
    """Pixel-related handler tests."""

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
                "meta_ads_pixels_list",
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
                "meta_ads_pixels_get",
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
                "meta_ads_pixels_stats",
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
                "meta_ads_pixels_events",
                {"account_id": "act_123", "pixel_id": "px_1"},
            )

        client.get_pixel_events.assert_awaited_once_with("px_1")
        parsed = json.loads(result[0].text)
        assert parsed[0]["event"] == "PageView"
