"""Tests for Meta Ads ``list_page_photos`` (Instant Form cover photo, #703).

A form intro screen's ``context_card.cover_photo_id`` needs a PAGE photo id,
NOT the ad-account ``image_hash`` returned by ``upload_ad_image*`` (#151).
mureo used to mint that id by uploading a new Page photo, which cost the
``pages_manage_posts`` scope Meta's App Review rejected twice. The operator now
picks an EXISTING Page photo instead: a plain read that needs only
``pages_read_engagement`` + ``pages_show_list`` and a Page Access Token, both
of which mureo already holds. These tests pin that read contract and the
absence of the upload path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def meta_client() -> Any:
    from mureo.meta_ads.client import MetaAdsApiClient

    client = MetaAdsApiClient(access_token="test-token", ad_account_id="act_123456")
    # Page token resolution is exercised elsewhere; stub the Page-token GET so
    # these tests focus on the request shape and the returned selection rows.
    client._get_as_page = AsyncMock(return_value={"data": []})  # type: ignore[method-assign]
    return client


def _photo(**overrides: Any) -> dict[str, Any]:
    photo: dict[str, Any] = {
        "id": "999_888",
        "name": "Spring campaign key visual",
        "created_time": "2026-08-01T09:00:00+0000",
        "images": [
            {"width": 1200, "height": 628, "source": "https://scontent/large.jpg"},
            {"width": 320, "height": 168, "source": "https://scontent/small.jpg"},
        ],
    }
    photo.update(overrides)
    return photo


@pytest.mark.unit
class TestListPagePhotos:
    @pytest.mark.asyncio()
    async def test_returns_id_and_the_minimum_needed_to_choose(
        self, meta_client: Any
    ) -> None:
        """The operator picks by looking: id plus a preview URL and its size.

        The raw ``images`` array carries every rendition Meta stores, which is
        noise for a picker — the largest (first) entry is the one worth showing.
        """
        meta_client._get_as_page.return_value = {"data": [_photo()]}

        result = await meta_client.list_page_photos("111")

        assert result == [
            {
                "id": "999_888",
                "name": "Spring campaign key visual",
                "created_time": "2026-08-01T09:00:00+0000",
                "width": 1200,
                "height": 628,
                "url": "https://scontent/large.jpg",
            }
        ]

    @pytest.mark.asyncio()
    async def test_reads_uploaded_page_photos_with_the_page_token(
        self, meta_client: Any
    ) -> None:
        """``type=uploaded`` is what limits the read to photos the Page owns —
        without it Meta also returns photos the Page was merely tagged in,
        which cannot be used as a form cover."""
        await meta_client.list_page_photos("111")

        args, kwargs = meta_client._get_as_page.call_args
        page_id, path, params = args
        assert page_id == "111"
        assert path == "/111/photos"
        assert params["type"] == "uploaded"
        assert params["fields"] == "id,name,created_time,images"

    @pytest.mark.asyncio()
    async def test_limit_defaults_to_25_and_is_forwarded(
        self, meta_client: Any
    ) -> None:
        await meta_client.list_page_photos("111")
        assert meta_client._get_as_page.call_args[0][2]["limit"] == 25

        await meta_client.list_page_photos("111", limit=5)
        assert meta_client._get_as_page.call_args[0][2]["limit"] == 5

    @pytest.mark.asyncio()
    async def test_largest_rendition_wins_regardless_of_order(
        self, meta_client: Any
    ) -> None:
        """Meta usually returns renditions largest-first but does not document
        that order, so the size is measured rather than assumed — a thumbnail
        shown as the preview would make every photo look the same."""
        meta_client._get_as_page.return_value = {
            "data": [
                _photo(
                    images=[
                        {"width": 320, "height": 168, "source": "https://s/small.jpg"},
                        {"width": 1200, "height": 628, "source": "https://s/large.jpg"},
                    ]
                )
            ]
        }

        result = await meta_client.list_page_photos("111")

        assert result[0]["url"] == "https://s/large.jpg"
        assert result[0]["width"] == 1200

    @pytest.mark.asyncio()
    async def test_photo_without_renditions_still_offers_its_id(
        self, meta_client: Any
    ) -> None:
        """A photo Meta returns no ``images`` for is still selectable — the id
        is the only field ``cover_photo_id`` actually needs."""
        meta_client._get_as_page.return_value = {
            "data": [_photo(images=[]), _photo(id="777", images=None)]
        }

        result = await meta_client.list_page_photos("111")

        assert [row["id"] for row in result] == ["999_888", "777"]
        for row in result:
            assert "url" not in row
            assert "width" not in row

    @pytest.mark.asyncio()
    async def test_photo_without_an_id_is_dropped(self, meta_client: Any) -> None:
        """An id-less row cannot be passed as ``cover_photo_id``, so offering
        it to the operator could only waste a pick."""
        meta_client._get_as_page.return_value = {"data": [_photo(id=""), _photo()]}

        result = await meta_client.list_page_photos("111")

        assert [row["id"] for row in result] == ["999_888"]

    @pytest.mark.asyncio()
    async def test_optional_fields_are_omitted_rather_than_nulled(
        self, meta_client: Any
    ) -> None:
        meta_client._get_as_page.return_value = {"data": [{"id": "555"}]}

        result = await meta_client.list_page_photos("111")

        assert result == [{"id": "555"}]

    @pytest.mark.asyncio()
    async def test_no_photos_returns_empty_list(self, meta_client: Any) -> None:
        meta_client._get_as_page.return_value = {}
        assert await meta_client.list_page_photos("111") == []

    def test_upload_path_is_gone(self, meta_client: Any) -> None:
        """#703 removed the upload entirely — a leftover method would keep the
        ``pages_manage_posts`` dependency alive in the client."""
        assert not hasattr(meta_client, "upload_page_photo")


@pytest.mark.unit
class TestPagesPhotosListToolDefinition:
    """Schema pins taken from the shipped tool registry, not a local literal."""

    def _tool(self) -> Any:
        from mureo.mcp import tools_meta_ads

        return next(
            t for t in tools_meta_ads.TOOLS if t.name == "meta_ads_pages_photos_list"
        )

    def test_registered_and_dispatchable(self) -> None:
        from mureo.mcp import tools_meta_ads

        assert "meta_ads_pages_photos_list" in tools_meta_ads._HANDLERS

    def test_name_puts_the_read_verb_last_like_its_siblings(self) -> None:
        """mureo names its own reads verb-LAST (meta_ads_page_posts_list,
        meta_ads_lead_forms_list), and ``reads_as_a_report_only_action`` — the
        rollback planner's "is there anything to undo?" test — only recognises
        a read verb at the start or the end of a name. A mid-word verb
        (``..._list_photos``) would read as a mutation there and land this
        tool among the entries an operator "cannot revert"."""
        from mureo.core.tool_names import reads_as_a_report_only_action

        assert reads_as_a_report_only_action("meta_ads_pages_photos_list")

    def test_upload_tool_is_deregistered(self) -> None:
        from mureo.mcp import tools_meta_ads

        names = {t.name for t in tools_meta_ads.TOOLS}
        assert "meta_ads_pages_upload_photo" not in names
        assert "meta_ads_pages_upload_photo" not in tools_meta_ads._HANDLERS

    def test_declares_itself_read_only(self) -> None:
        """The tool replaced a mutating one; an agent that still reads it as a
        write would gate it behind a confirmation it no longer needs."""
        assert "Read-only." in self._tool().description

    def test_schema_requires_page_id_and_is_strict(self) -> None:
        schema = self._tool().inputSchema
        assert schema["required"] == ["page_id"]
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {"account_id", "page_id", "limit"}

    def test_limit_is_bounded(self) -> None:
        limit = self._tool().inputSchema["properties"]["limit"]
        assert limit["type"] == "integer"
        assert limit["minimum"] == 1
        assert limit["maximum"] == 100
