"""Tests for Meta Ads ad-set publisher exclusions (#544).

Meta's analogue of Google's excluded placements / app categories lives in
the ad set's targeting spec (``excluded_publisher_categories``,
``excluded_publisher_list_ids``, ``excluded_brand_safety_content_types``).
Covers ``PlacementExclusionsMixin``, the tool schemas and the handlers.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mureo.meta_ads.client import MetaAdsApiClient


def _make_client() -> MetaAdsApiClient:
    return MetaAdsApiClient(access_token="token", ad_account_id="act_1")


# ---------------------------------------------------------------------------
# get_excluded_placements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetExcludedPlacements:
    @pytest.mark.asyncio
    async def test_reads_the_three_exclusion_facets(self) -> None:
        client = _make_client()
        client.get_ad_set = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "id": "s1",
                "targeting": {
                    "geo_locations": {"countries": ["JP"]},
                    "excluded_publisher_categories": ["dating"],
                    "excluded_publisher_list_ids": ["9001"],
                },
            }
        )
        result = await client.get_excluded_placements("s1")
        assert result == {
            "ad_set_id": "s1",
            "excluded_publisher_categories": ["dating"],
            "excluded_publisher_list_ids": ["9001"],
            "excluded_brand_safety_content_types": [],
        }

    @pytest.mark.asyncio
    async def test_missing_targeting_reads_as_no_exclusions(self) -> None:
        client = _make_client()
        client.get_ad_set = AsyncMock(return_value={"id": "s1"})  # type: ignore[method-assign]
        result = await client.get_excluded_placements("s1")
        assert result["excluded_publisher_categories"] == []
        assert result["excluded_publisher_list_ids"] == []


# ---------------------------------------------------------------------------
# set_excluded_placements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetExcludedPlacements:
    @pytest.mark.asyncio
    async def test_writes_only_the_supplied_facets_via_the_targeting_merge(
        self,
    ) -> None:
        client = _make_client()
        client.update_ad_set = AsyncMock(return_value={"success": True})  # type: ignore[method-assign]

        result = await client.set_excluded_placements(
            "s1", excluded_publisher_categories=["dating", "gambling"]
        )
        client.update_ad_set.assert_awaited_once_with(
            "s1", targeting={"excluded_publisher_categories": ["dating", "gambling"]}
        )
        assert result["ad_set_id"] == "s1"
        assert result["applied"] == {
            "excluded_publisher_categories": ["dating", "gambling"]
        }

    @pytest.mark.asyncio
    async def test_empty_list_clears_a_facet(self) -> None:
        client = _make_client()
        client.update_ad_set = AsyncMock(return_value={})  # type: ignore[method-assign]
        await client.set_excluded_placements("s1", excluded_publisher_list_ids=[])
        client.update_ad_set.assert_awaited_once_with(
            "s1", targeting={"excluded_publisher_list_ids": []}
        )

    @pytest.mark.asyncio
    async def test_no_facet_supplied_is_refused(self) -> None:
        client = _make_client()
        client.update_ad_set = AsyncMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="At least one"):
            await client.set_excluded_placements("s1")
        client.update_ad_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_never_replaces_the_whole_targeting_spec(self) -> None:
        """A partial targeting write would silently clear geo/audience keys."""
        client = _make_client()
        captured: dict[str, Any] = {}

        async def _update(ad_set_id: str, **kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {}

        client.update_ad_set = _update  # type: ignore[method-assign]
        await client.set_excluded_placements(
            "s1", excluded_brand_safety_content_types=["LIVE_STREAMING"]
        )
        assert "replace_targeting" not in captured


# ---------------------------------------------------------------------------
# MCP surface
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolSchemas:
    def test_set_schema_exposes_the_three_facets(self) -> None:
        from mureo.mcp.tools_meta_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "meta_ads_excluded_placements_set")
        props = tool.inputSchema["properties"]
        for key in (
            "excluded_publisher_categories",
            "excluded_publisher_list_ids",
            "excluded_brand_safety_content_types",
        ):
            assert props[key]["type"] == "array"
        assert tool.inputSchema["required"] == ["ad_set_id"]


@pytest.mark.unit
class TestHandlers:
    @pytest.mark.asyncio
    async def test_get_handler_returns_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import _handlers_meta_ads_extended as h

        client = MagicMock()
        client.get_excluded_placements = AsyncMock(
            return_value={"ad_set_id": "s1", "excluded_publisher_categories": []}
        )
        monkeypatch.setattr(h, "_get_client", AsyncMock(return_value=client))
        result = await h.handle_excluded_placements_get({"ad_set_id": "s1"})
        assert json.loads(result[0].text)["ad_set_id"] == "s1"

    @pytest.mark.asyncio
    async def test_set_handler_forwards_only_supplied_facets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp import _handlers_meta_ads_extended as h

        client = MagicMock()
        client.set_excluded_placements = AsyncMock(return_value={"ad_set_id": "s1"})
        monkeypatch.setattr(h, "_get_client", AsyncMock(return_value=client))
        await h.handle_excluded_placements_set(
            {"ad_set_id": "s1", "excluded_publisher_categories": ["dating"]}
        )
        client.set_excluded_placements.assert_awaited_once_with(
            "s1", excluded_publisher_categories=["dating"]
        )
