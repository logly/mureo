"""Tests for Meta Ads video uploads, carousel, and collection creatives.

TDD: tests are written first; the implementation is added until the
tests pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import MetaAdsCredentials

# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture()
def meta_client() -> Any:
    """Create a MetaAdsApiClient for tests."""
    from mureo.meta_ads.client import MetaAdsApiClient

    return MetaAdsApiClient(
        access_token="test-token",
        ad_account_id="act_123456",
    )


@pytest.fixture()
def sample_video(tmp_path: Path) -> Path:
    """Create a dummy video file (mp4) for tests."""
    video = tmp_path / "test_video.mp4"
    video.write_bytes(b"\x00\x00\x00\x1cftypisom" + b"\x00" * 100)
    return video


@pytest.fixture()
def sample_mov(tmp_path: Path) -> Path:
    """Create a dummy MOV file for tests."""
    video = tmp_path / "test_video.mov"
    video.write_bytes(b"\x00" * 100)
    return video


# ---------------------------------------------------------------------------
# 1. test_upload_ad_video — upload video via URL
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadAdVideo:
    """Upload video via a URL."""

    @pytest.mark.asyncio()
    async def test_upload_ad_video(self, meta_client: Any) -> None:
        """Upload a video by URL and receive a video_id."""
        meta_client._post = AsyncMock(return_value={"id": "video_123"})

        result = await meta_client.upload_ad_video(
            video_url="https://example.com/video.mp4",
            title="テスト動画",
        )

        assert result["id"] == "video_123"
        meta_client._post.assert_awaited_once()
        call_args = meta_client._post.call_args
        assert "/advideos" in call_args[0][0]
        data = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
        )
        assert data.get("file_url") == "https://example.com/video.mp4"
        assert data.get("title") == "テスト動画"

    @pytest.mark.asyncio()
    async def test_upload_ad_video_without_title(self, meta_client: Any) -> None:
        """Upload succeeds even when title is omitted."""
        meta_client._post = AsyncMock(return_value={"id": "video_456"})

        result = await meta_client.upload_ad_video(
            video_url="https://example.com/video.mp4",
        )

        assert result["id"] == "video_456"
        call_args = meta_client._post.call_args
        data = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
        )
        assert "title" not in data


# ---------------------------------------------------------------------------
# 2. test_upload_ad_video_file — upload video from a local file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadAdVideoFile:
    """Upload video from a local file."""

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file(
        self, meta_client: Any, sample_video: Path
    ) -> None:
        """Successful upload returns a video_id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "video_789"}
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "mureo.meta_ads._creatives.httpx.AsyncClient",
            return_value=mock_http_client,
        ):
            result = await meta_client.upload_ad_video_file(str(sample_video))

        assert result["id"] == "video_789"

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_with_title(
        self, meta_client: Any, sample_video: Path
    ) -> None:
        """When title is supplied, that value is sent."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "video_789"}
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "mureo.meta_ads._creatives.httpx.AsyncClient",
            return_value=mock_http_client,
        ):
            result = await meta_client.upload_ad_video_file(
                str(sample_video), title="カスタムタイトル"
            )

        assert result["id"] == "video_789"


# ---------------------------------------------------------------------------
# 3. test_upload_ad_video_file_too_large — size exceeded
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadAdVideoFileTooLarge:
    """Video file size limit."""

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_too_large(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for files larger than 100MB."""
        large_file = tmp_path / "large.mp4"
        # 100MB + 1 byte
        large_file.write_bytes(b"\x00" * (100 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="100MB"):
            await meta_client.upload_ad_video_file(str(large_file))


# ---------------------------------------------------------------------------
# 4. test_upload_ad_video_file_invalid_format — unsupported format
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUploadAdVideoFileInvalidFormat:
    """Video file-format check."""

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_invalid_format(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for unsupported formats (e.g. txt)."""
        txt_file = tmp_path / "document.txt"
        txt_file.write_bytes(b"not a video")

        with pytest.raises(ValueError, match="Unsupported video format"):
            await meta_client.upload_ad_video_file(str(txt_file))

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_supported_formats(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """mp4, mov, avi, wmv, mkv are all allowed."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "v1"}
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        for ext in ("mp4", "mov", "avi", "wmv", "mkv"):
            video = tmp_path / f"test.{ext}"
            video.write_bytes(b"\x00" * 100)
            with patch(
                "mureo.meta_ads._creatives.httpx.AsyncClient",
                return_value=mock_http_client,
            ):
                result = await meta_client.upload_ad_video_file(str(video))
                assert "id" in result

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_not_found(self, meta_client: Any) -> None:
        """Raises FileNotFoundError when the file does not exist."""
        with pytest.raises(FileNotFoundError):
            await meta_client.upload_ad_video_file("/nonexistent/path/video.mp4")

    @pytest.mark.asyncio()
    async def test_upload_ad_video_file_path_traversal(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Paths containing path-traversal segments are rejected."""
        with pytest.raises(ValueError, match="Invalid file path"):
            await meta_client.upload_ad_video_file(
                str(tmp_path / ".." / ".." / "etc" / "passwd")
            )


# ---------------------------------------------------------------------------
# 5. test_create_carousel_creative — create a carousel (happy path)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCarouselCreative:
    """Create a carousel creative."""

    @pytest.mark.asyncio()
    async def test_create_carousel_creative(self, meta_client: Any) -> None:
        """A carousel with 3 cards can be created."""
        meta_client._post = AsyncMock(return_value={"id": "creative_carousel_1"})

        cards = [
            {
                "link": "https://example.com/product1",
                "name": "商品1",
                "description": "説明1",
                "image_hash": "abc123",
            },
            {
                "link": "https://example.com/product2",
                "name": "商品2",
                "description": "説明2",
                "image_hash": "def456",
            },
            {
                "link": "https://example.com/product3",
                "name": "商品3",
                "description": "説明3",
                "image_hash": "ghi789",
            },
        ]

        result = await meta_client.create_carousel_creative(
            page_id="page_123",
            cards=cards,
            link="https://example.com",
            name="カルーセル広告テスト",
        )

        assert result["id"] == "creative_carousel_1"
        meta_client._post.assert_awaited_once()
        call_args = meta_client._post.call_args
        assert "/adcreatives" in call_args[0][0]
        data = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
        )
        # object_story_spec must include child_attachments.
        oss = json.loads(data["object_story_spec"])
        assert oss["page_id"] == "page_123"
        assert len(oss["link_data"]["child_attachments"]) == 3
        assert oss["link_data"]["link"] == "https://example.com"


# ---------------------------------------------------------------------------
# 6. test_create_carousel_creative_min_cards — minimum (2 cards)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCarouselCreativeMinCards:
    """Carousel minimum card count."""

    @pytest.mark.asyncio()
    async def test_create_carousel_creative_min_cards(self, meta_client: Any) -> None:
        """A carousel with 2 cards can be created."""
        meta_client._post = AsyncMock(return_value={"id": "creative_carousel_min"})

        cards = [
            {
                "link": "https://example.com/p1",
                "name": "商品1",
                "image_hash": "hash1",
            },
            {
                "link": "https://example.com/p2",
                "name": "商品2",
                "image_hash": "hash2",
            },
        ]

        result = await meta_client.create_carousel_creative(
            page_id="page_123",
            cards=cards,
            link="https://example.com",
        )

        assert result["id"] == "creative_carousel_min"


# ---------------------------------------------------------------------------
# 7. test_create_carousel_creative_too_few — 1 card is an error
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCarouselCreativeTooFew:
    """Carousel card-count validation."""

    @pytest.mark.asyncio()
    async def test_create_carousel_creative_too_few(self, meta_client: Any) -> None:
        """Raises ValueError when there is only 1 card."""
        cards = [
            {
                "link": "https://example.com/p1",
                "name": "商品1",
                "image_hash": "hash1",
            },
        ]

        with pytest.raises(ValueError, match="2.+10"):
            await meta_client.create_carousel_creative(
                page_id="page_123",
                cards=cards,
                link="https://example.com",
            )

    @pytest.mark.asyncio()
    async def test_create_carousel_creative_too_many(self, meta_client: Any) -> None:
        """Raises ValueError for 11 cards."""
        cards = [
            {
                "link": f"https://example.com/p{i}",
                "name": f"商品{i}",
                "image_hash": f"hash{i}",
            }
            for i in range(11)
        ]

        with pytest.raises(ValueError, match="2.+10"):
            await meta_client.create_carousel_creative(
                page_id="page_123",
                cards=cards,
                link="https://example.com",
            )

    @pytest.mark.asyncio()
    async def test_create_carousel_creative_max_cards(self, meta_client: Any) -> None:
        """A carousel with 10 cards can be created."""
        meta_client._post = AsyncMock(return_value={"id": "creative_carousel_max"})

        cards = [
            {
                "link": f"https://example.com/p{i}",
                "name": f"商品{i}",
                "image_hash": f"hash{i}",
            }
            for i in range(10)
        ]

        result = await meta_client.create_carousel_creative(
            page_id="page_123",
            cards=cards,
            link="https://example.com",
        )

        assert result["id"] == "creative_carousel_max"


# ---------------------------------------------------------------------------
# 8. test_create_collection_creative — create a collection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCollectionCreative:
    """Create a collection creative."""

    @pytest.mark.asyncio()
    async def test_create_collection_creative(self, meta_client: Any) -> None:
        """A collection with an image cover can be created."""
        meta_client._post = AsyncMock(return_value={"id": "creative_collection_1"})

        result = await meta_client.create_collection_creative(
            page_id="page_123",
            product_ids=["product_1", "product_2", "product_3"],
            link="https://example.com",
            cover_image_hash="cover_hash_abc",
            name="コレクション広告テスト",
        )

        assert result["id"] == "creative_collection_1"
        meta_client._post.assert_awaited_once()
        call_args = meta_client._post.call_args
        assert "/adcreatives" in call_args[0][0]
        data = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
        )
        oss = json.loads(data["object_story_spec"])
        assert oss["page_id"] == "page_123"
        td = oss["template_data"]
        assert td["retailer_item_ids"] == ["product_1", "product_2", "product_3"]
        assert td["call_to_action"]["value"]["link"] == "https://example.com"


# ---------------------------------------------------------------------------
# 9. test_create_collection_creative_with_video — with a video cover
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateCollectionCreativeWithVideo:
    """Collection creative with a video cover."""

    @pytest.mark.asyncio()
    async def test_create_collection_creative_with_video(
        self, meta_client: Any
    ) -> None:
        """A collection with a video cover can be created."""
        meta_client._post = AsyncMock(return_value={"id": "creative_collection_video"})

        result = await meta_client.create_collection_creative(
            page_id="page_123",
            product_ids=["product_1", "product_2"],
            link="https://example.com",
            cover_video_id="video_cover_123",
            name="動画コレクション",
        )

        assert result["id"] == "creative_collection_video"
        call_args = meta_client._post.call_args
        data = (
            call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
        )
        oss = json.loads(data["object_story_spec"])
        td = oss["template_data"]
        assert td["format_option"] == "collection_video"

    @pytest.mark.asyncio()
    async def test_create_collection_creative_no_cover(self, meta_client: Any) -> None:
        """A collection can be created even without a cover."""
        meta_client._post = AsyncMock(
            return_value={"id": "creative_collection_nocover"}
        )

        result = await meta_client.create_collection_creative(
            page_id="page_123",
            product_ids=["product_1", "product_2"],
            link="https://example.com",
        )

        assert result["id"] == "creative_collection_nocover"


# ---------------------------------------------------------------------------
# MCP tool-definition tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsMediaToolDefinitions:
    """MCP tool-definition tests for videos, carousels, and collections."""

    def _get_tools(self) -> list[Any]:
        from mureo.mcp.tools_meta_ads import TOOLS

        return TOOLS

    def _get_tool(self, name: str) -> Any:
        tools = self._get_tools()
        tool = next((t for t in tools if t.name == name), None)
        assert tool is not None, f"Tool {name} not found"
        return tool

    def test_videos_upload_tool_exists(self) -> None:
        """meta_ads_videos_upload is defined in TOOLS."""
        self._get_tool("meta_ads_videos_upload")

    def test_videos_upload_required_fields(self) -> None:
        """The required parameters of videos.upload are correct."""
        tool = self._get_tool("meta_ads_videos_upload")
        assert set(tool.inputSchema["required"]) == {"video_url"}

    def test_videos_upload_file_tool_exists(self) -> None:
        """meta_ads_videos_upload_file is defined in TOOLS."""
        self._get_tool("meta_ads_videos_upload_file")

    def test_videos_upload_file_required_fields(self) -> None:
        """The required parameters of videos.upload_file are correct."""
        tool = self._get_tool("meta_ads_videos_upload_file")
        assert set(tool.inputSchema["required"]) == {"file_path"}

    def test_creatives_create_carousel_tool_exists(self) -> None:
        """meta_ads_creatives_create_carousel is defined in TOOLS."""
        self._get_tool("meta_ads_creatives_create_carousel")

    def test_creatives_create_carousel_required_fields(self) -> None:
        """The required parameters of create_carousel are correct."""
        tool = self._get_tool("meta_ads_creatives_create_carousel")
        assert set(tool.inputSchema["required"]) == {
            "page_id",
            "cards",
            "link",
        }

    def test_creatives_create_collection_tool_exists(self) -> None:
        """meta_ads_creatives_create_collection is defined in TOOLS."""
        self._get_tool("meta_ads_creatives_create_collection")

    def test_creatives_create_collection_required_fields(self) -> None:
        """The required parameters of create_collection are correct."""
        tool = self._get_tool("meta_ads_creatives_create_collection")
        assert set(tool.inputSchema["required"]) == {
            "page_id",
            "product_ids",
            "link",
        }


# ---------------------------------------------------------------------------
# MCP handler tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetaAdsMediaHandlers:
    """MCP handler tests for videos, carousels, and collections."""

    @pytest.mark.asyncio()
    async def test_handle_videos_upload(self) -> None:
        """The videos.upload handler invokes the client correctly."""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_ad_video.return_value = {"id": "video_mcp_1"}

        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=MetaAdsCredentials(access_token="tok"),
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "meta_ads_videos_upload",
                {
                    "account_id": "act_123",
                    "video_url": "https://example.com/video.mp4",
                    "title": "MCP動画",
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == "video_mcp_1"
        mock_client.upload_ad_video.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_handle_videos_upload_file(self, sample_video: Path) -> None:
        """The videos.upload_file handler invokes the client correctly."""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_ad_video_file.return_value = {"id": "video_file_1"}

        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=MetaAdsCredentials(access_token="tok"),
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "meta_ads_videos_upload_file",
                {
                    "account_id": "act_123",
                    "file_path": str(sample_video),
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == "video_file_1"

    @pytest.mark.asyncio()
    async def test_handle_creatives_create_carousel(self) -> None:
        """The create_carousel handler invokes the client correctly."""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.create_carousel_creative.return_value = {"id": "carousel_mcp_1"}

        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=MetaAdsCredentials(access_token="tok"),
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "meta_ads_creatives_create_carousel",
                {
                    "account_id": "act_123",
                    "page_id": "page_1",
                    "cards": [
                        {"link": "https://a.com", "name": "A", "image_hash": "h1"},
                        {"link": "https://b.com", "name": "B", "image_hash": "h2"},
                    ],
                    "link": "https://example.com",
                    "name": "テストカルーセル",
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == "carousel_mcp_1"

    @pytest.mark.asyncio()
    async def test_handle_creatives_create_collection(self) -> None:
        """The create_collection handler invokes the client correctly."""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.create_collection_creative.return_value = {"id": "collection_mcp_1"}

        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=MetaAdsCredentials(access_token="tok"),
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "meta_ads_creatives_create_collection",
                {
                    "account_id": "act_123",
                    "page_id": "page_1",
                    "product_ids": ["p1", "p2"],
                    "link": "https://example.com",
                    "cover_image_hash": "cover_h",
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["id"] == "collection_mcp_1"
