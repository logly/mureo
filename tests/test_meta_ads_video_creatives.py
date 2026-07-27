"""Tests for Meta Ads VIDEO creative support.

Covers the video branch of ``create_ad_creative`` (object_story_spec.video_data),
its MCP tool schema / handler, and the two read-only video tools
(``meta_ads_videos_get`` / ``meta_ads_videos_thumbnails``) used to poll
processing status and pick a thumbnail before creating the creative.

TDD: tests are written first; the implementation follows.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth import MetaAdsCredentials


@pytest.fixture(autouse=True)
def _standalone_meta_ads():
    """Pin these handler tests to STANDALONE (untenanted) Meta Ads.

    Mirrors the fixture used across the other Meta handler suites: with a
    ``mureo.runtime_context_factory`` plugin installed, an undeclared
    ``meta_account_ids`` fail-closes every account_id and breaks the
    standalone assertions here.
    """
    with patch(
        "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
        return_value=None,
    ):
        yield


@pytest.fixture()
def meta_client() -> Any:
    from mureo.meta_ads.client import MetaAdsApiClient

    return MetaAdsApiClient(access_token="test-token", ad_account_id="act_123456")


def _mock_creds_and_client() -> tuple[Any, Any]:
    return MetaAdsCredentials(access_token="tok"), AsyncMock()


def _sent_object_story_spec(post_mock: AsyncMock) -> dict[str, Any]:
    """Decode ``object_story_spec`` from the captured ``_post`` call."""
    call_args = post_mock.call_args
    data = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("data", {})
    return json.loads(data["object_story_spec"])  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# create_ad_creative — video branch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAdCreativeVideo:
    """``create_ad_creative`` builds object_story_spec.video_data for videos."""

    @pytest.mark.asyncio()
    async def test_video_creative_with_image_hash_thumbnail(
        self, meta_client: Any
    ) -> None:
        """video_id + thumbnail hash produces the documented video_data shape."""
        meta_client._post = AsyncMock(return_value={"id": "cr_video_1"})

        result = await meta_client.create_ad_creative(
            name="Video creative",
            page_id="page_1",
            link_url="https://example.com/lp",
            video_id="video_42",
            video_thumbnail_image_hash="thumb_hash",
            message="body text",
            headline="Headline",
            description="Caption",
            call_to_action="LEARN_MORE",
        )

        assert result["id"] == "cr_video_1"
        assert "/adcreatives" in meta_client._post.call_args[0][0]
        oss = _sent_object_story_spec(meta_client._post)
        assert oss["page_id"] == "page_1"
        assert "link_data" not in oss
        assert oss["video_data"] == {
            "video_id": "video_42",
            "image_hash": "thumb_hash",
            "title": "Headline",
            "message": "body text",
            "link_description": "Caption",
            "call_to_action": {
                "type": "LEARN_MORE",
                "value": {"link": "https://example.com/lp"},
            },
        }

    @pytest.mark.asyncio()
    async def test_video_creative_with_image_url_thumbnail(
        self, meta_client: Any
    ) -> None:
        """The image_url thumbnail variant maps to video_data.image_url.

        ``meta_ads_videos_thumbnails`` returns Meta-hosted ``uri`` values, so
        the url variant is the natural output of the poll-then-pick flow.
        """
        meta_client._post = AsyncMock(return_value={"id": "cr_video_2"})

        await meta_client.create_ad_creative(
            name="Video creative",
            page_id="page_1",
            link_url="https://example.com/lp",
            video_id="video_42",
            video_thumbnail_image_url="https://scontent.example/thumb.jpg",
            call_to_action="LEARN_MORE",
        )

        video_data = _sent_object_story_spec(meta_client._post)["video_data"]
        assert video_data["image_url"] == "https://scontent.example/thumb.jpg"
        assert "image_hash" not in video_data
        # Optional copy fields are omitted rather than sent as null/empty;
        # call_to_action is mandatory in video mode so it is always present.
        assert set(video_data) == {"video_id", "image_url", "call_to_action"}

    @pytest.mark.asyncio()
    async def test_video_creative_requires_call_to_action(
        self, meta_client: Any
    ) -> None:
        """Video mode without call_to_action is rejected locally.

        ``video_data`` has no ``link`` field — the destination lives only at
        ``call_to_action.value.link``. Accepting a CTA-less video creative
        would silently discard the (required) link_url, so this is a hard
        requirement enforced here rather than a documented footgun.
        """
        meta_client._post = AsyncMock(return_value={"id": "never"})

        with pytest.raises(ValueError, match="call_to_action"):
            await meta_client.create_ad_creative(
                name="Video creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                video_id="video_42",
                video_thumbnail_image_hash="thumb_hash",
            )

        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_video_creative_cta_link_is_auto_injected(
        self, meta_client: Any
    ) -> None:
        """link_url is auto-injected into call_to_action.value.link.

        The caller supplies only the CTA type string (same shape as the image
        path) — it must never have to duplicate the link inside the CTA.
        """
        meta_client._post = AsyncMock(return_value={"id": "cr_video_3"})

        await meta_client.create_ad_creative(
            name="Video creative",
            page_id="page_1",
            link_url="https://example.com/deep/landing?utm=x",
            video_id="video_42",
            video_thumbnail_image_hash="thumb_hash",
            call_to_action="SHOP_NOW",
        )

        cta = _sent_object_story_spec(meta_client._post)["video_data"]["call_to_action"]
        assert cta == {
            "type": "SHOP_NOW",
            "value": {"link": "https://example.com/deep/landing?utm=x"},
        }

    @pytest.mark.asyncio()
    async def test_video_creative_requires_thumbnail(self, meta_client: Any) -> None:
        """Meta requires a thumbnail on video creatives — fail fast locally."""
        meta_client._post = AsyncMock(return_value={"id": "never"})

        with pytest.raises(ValueError, match="thumbnail"):
            await meta_client.create_ad_creative(
                name="Video creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                video_id="video_42",
            )

        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_video_thumbnail_variants_mutually_exclusive(
        self, meta_client: Any
    ) -> None:
        """Supplying both thumbnail forms is ambiguous and rejected."""
        meta_client._post = AsyncMock(return_value={"id": "never"})

        with pytest.raises(ValueError, match="mutually exclusive"):
            await meta_client.create_ad_creative(
                name="Video creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                video_id="video_42",
                video_thumbnail_image_hash="h",
                video_thumbnail_image_url="https://scontent.example/t.jpg",
            )

        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_video_and_image_params_mutually_exclusive(
        self, meta_client: Any
    ) -> None:
        """A creative is either video or image — the conflict names the keys."""
        meta_client._post = AsyncMock(return_value={"id": "never"})

        with pytest.raises(ValueError) as excinfo:
            await meta_client.create_ad_creative(
                name="Video creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                video_id="video_42",
                video_thumbnail_image_hash="thumb_hash",
                image_hash="img_hash",
            )

        message = str(excinfo.value)
        assert "video_id" in message
        assert "image_hash" in message
        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_video_and_image_url_mutually_exclusive_no_upload(
        self, meta_client: Any
    ) -> None:
        """image_url + video_id must raise BEFORE the image auto-upload runs."""
        meta_client._post = AsyncMock(return_value={"id": "never"})
        meta_client.upload_ad_image = AsyncMock(return_value={"hash": "h"})

        with pytest.raises(ValueError, match="image_url"):
            await meta_client.create_ad_creative(
                name="Video creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                video_id="video_42",
                video_thumbnail_image_hash="thumb_hash",
                image_url="https://example.com/img.png",
            )

        meta_client.upload_ad_image.assert_not_awaited()
        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_thumbnail_without_video_id_rejected(self, meta_client: Any) -> None:
        """A thumbnail param without video_id would be silently dropped."""
        meta_client._post = AsyncMock(return_value={"id": "never"})

        with pytest.raises(ValueError, match="video_id"):
            await meta_client.create_ad_creative(
                name="Image creative",
                page_id="page_1",
                link_url="https://example.com/lp",
                image_hash="img_hash",
                video_thumbnail_image_hash="thumb_hash",
            )

        meta_client._post.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_image_path_unchanged(self, meta_client: Any) -> None:
        """The pre-existing image path still builds link_data (no regression)."""
        meta_client._post = AsyncMock(return_value={"id": "cr_img"})

        await meta_client.create_ad_creative(
            name="Image creative",
            page_id="page_1",
            link_url="https://example.com/lp",
            image_hash="img_hash",
            headline="Head",
            call_to_action="SHOP_NOW",
        )

        oss = _sent_object_story_spec(meta_client._post)
        assert "video_data" not in oss
        assert oss["link_data"]["image_hash"] == "img_hash"
        assert oss["link_data"]["name"] == "Head"
        assert oss["link_data"]["call_to_action"] == {"type": "SHOP_NOW"}


# ---------------------------------------------------------------------------
# Video read tools — client methods
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoReadClientMethods:
    """``get_ad_video`` / ``list_ad_video_thumbnails`` hit node-level paths."""

    @pytest.mark.asyncio()
    async def test_get_ad_video_path_and_fields(self, meta_client: Any) -> None:
        """GET /{video_id} — a node path, NOT act_-scoped."""
        meta_client._get = AsyncMock(
            return_value={
                "id": "video_42",
                "status": {"video_status": "processing", "processing_phase": {}},
                "title": "t",
                "length": 15.0,
                "created_time": "2026-07-01T00:00:00+0000",
            }
        )

        result = await meta_client.get_ad_video("video_42")

        assert result["status"]["video_status"] == "processing"
        path, params = meta_client._get.call_args[0]
        assert path == "/video_42"
        assert "act_" not in path
        fields = set(params["fields"].split(","))
        assert fields == {"status", "id", "title", "length", "created_time"}

    @pytest.mark.asyncio()
    async def test_list_ad_video_thumbnails(self, meta_client: Any) -> None:
        """GET /{video_id}/thumbnails returns the unwrapped data list."""
        meta_client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "t1",
                        "uri": "https://scontent.example/t1.jpg",
                        "is_preferred": True,
                        "height": 720,
                        "width": 1280,
                    },
                    {
                        "id": "t2",
                        "uri": "https://scontent.example/t2.jpg",
                        "is_preferred": False,
                        "height": 720,
                        "width": 1280,
                    },
                ]
            }
        )

        result = await meta_client.list_ad_video_thumbnails("video_42")

        assert [t["id"] for t in result] == ["t1", "t2"]
        assert result[0]["is_preferred"] is True
        path, params = meta_client._get.call_args[0]
        assert path == "/video_42/thumbnails"
        assert "act_" not in path
        assert set(params["fields"].split(",")) == {
            "id",
            "uri",
            "is_preferred",
            "height",
            "width",
        }

    @pytest.mark.asyncio()
    async def test_list_ad_video_thumbnails_empty(self, meta_client: Any) -> None:
        """A video with no thumbnails yet yields an empty list, not a KeyError."""
        meta_client._get = AsyncMock(return_value={})

        assert await meta_client.list_ad_video_thumbnails("video_42") == []


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoToolDefinitions:
    """Schema-level pins for the new/changed tools."""

    def _tool(self, name: str) -> Any:
        from mureo.mcp.tools_meta_ads import TOOLS

        tool = next((t for t in TOOLS if t.name == name), None)
        assert tool is not None, f"Tool {name} not found"
        return tool

    def test_videos_get_schema(self) -> None:
        tool = self._tool("meta_ads_videos_get")
        assert set(tool.inputSchema["required"]) == {"video_id"}
        assert tool.inputSchema["additionalProperties"] is False
        assert "account_id" in tool.inputSchema["properties"]

    def test_videos_thumbnails_schema(self) -> None:
        tool = self._tool("meta_ads_videos_thumbnails")
        assert set(tool.inputSchema["required"]) == {"video_id"}
        assert tool.inputSchema["additionalProperties"] is False

    def test_creatives_create_exposes_video_params(self) -> None:
        """The video params are declared and the schema stays strict."""
        schema = self._tool("meta_ads_creatives_create").inputSchema
        for key in (
            "video_id",
            "video_thumbnail_image_hash",
            "video_thumbnail_image_url",
        ):
            assert key in schema["properties"], key
        assert schema["additionalProperties"] is False
        # required is unchanged — video mode is opt-in. The video-mode
        # extras (thumbnail, call_to_action) are conditional requirements
        # that JSON Schema `required` cannot express, so they are enforced
        # in the client layer and documented in the descriptions.
        assert set(schema["required"]) == {"name", "page_id", "link_url"}

    def test_creatives_create_documents_video_cta_requirement(self) -> None:
        """The conditional CTA requirement is stated where an agent will read it.

        It cannot live in `required`, so the tool description, the video_id
        description and the call_to_action description must each carry it.
        """
        tool = self._tool("meta_ads_creatives_create")
        props = tool.inputSchema["properties"]

        assert "call_to_action" in tool.description
        assert "call_to_action" in props["video_id"]["description"]
        for token in ("REQUIRED", "video_id"):
            assert token in props["call_to_action"]["description"], token

    def test_creatives_create_rejects_unknown_param(self) -> None:
        """additionalProperties: false still rejects a typo'd video param."""
        schema = self._tool("meta_ads_creatives_create").inputSchema
        assert "video_thumbnail" not in schema["properties"]
        assert "video_hash" not in schema["properties"]

    def test_video_upload_descriptions_state_real_limits(self) -> None:
        """Both upload tools document the real extensions and the 1 GB cap."""
        for name in ("meta_ads_videos_upload", "meta_ads_videos_upload_file"):
            description = (
                json.dumps(self._tool(name).inputSchema) + self._tool(name).description
            )
            assert "1 GB" in description, name
            assert "resumable" in description, name
            assert "MKV" in description, name
            assert "4 GB" not in description, name


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoHandlers:
    """Handler dispatch for the video tools."""

    async def _dispatch(self, client: Any, name: str, args: dict[str, Any]) -> Any:
        from mureo.mcp.tools_meta_ads import handle_tool

        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=MetaAdsCredentials(access_token="tok"),
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=client,
            ),
        ):
            return await handle_tool(name, args)

    @pytest.mark.asyncio()
    async def test_handle_videos_get(self) -> None:
        client = AsyncMock()
        client.get_ad_video.return_value = {
            "id": "video_42",
            "status": {"video_status": "ready"},
        }

        result = await self._dispatch(
            client,
            "meta_ads_videos_get",
            {"account_id": "act_123", "video_id": "video_42"},
        )

        client.get_ad_video.assert_awaited_once_with("video_42")
        parsed = json.loads(result[0].text)
        assert parsed["status"]["video_status"] == "ready"

    @pytest.mark.asyncio()
    async def test_handle_videos_get_requires_video_id(self) -> None:
        client = AsyncMock()

        with pytest.raises(ValueError, match="video_id"):
            await self._dispatch(client, "meta_ads_videos_get", {"account_id": "act_1"})

    @pytest.mark.asyncio()
    async def test_handle_videos_get_missing_creds(self) -> None:
        from mureo.mcp.tools_meta_ads import handle_tool

        with patch(
            "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
            return_value=None,
        ):
            result = await handle_tool("meta_ads_videos_get", {"video_id": "video_42"})

        assert "META_ADS" in result[0].text or "credentials" in result[0].text.lower()

    @pytest.mark.asyncio()
    async def test_handle_videos_thumbnails(self) -> None:
        client = AsyncMock()
        client.list_ad_video_thumbnails.return_value = [
            {"id": "t1", "uri": "https://scontent.example/t1.jpg", "is_preferred": True}
        ]

        result = await self._dispatch(
            client,
            "meta_ads_videos_thumbnails",
            {"account_id": "act_123", "video_id": "video_42"},
        )

        client.list_ad_video_thumbnails.assert_awaited_once_with("video_42")
        parsed = json.loads(result[0].text)
        assert parsed[0]["is_preferred"] is True

    @pytest.mark.asyncio()
    async def test_handle_videos_thumbnails_requires_video_id(self) -> None:
        client = AsyncMock()

        with pytest.raises(ValueError, match="video_id"):
            await self._dispatch(
                client, "meta_ads_videos_thumbnails", {"account_id": "act_1"}
            )

    @pytest.mark.asyncio()
    async def test_handle_videos_thumbnails_missing_creds(self) -> None:
        from mureo.mcp.tools_meta_ads import handle_tool

        with patch(
            "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
            return_value=None,
        ):
            result = await handle_tool(
                "meta_ads_videos_thumbnails", {"video_id": "video_42"}
            )

        assert "META_ADS" in result[0].text or "credentials" in result[0].text.lower()

    @pytest.mark.asyncio()
    async def test_handle_creatives_create_forwards_video_params(self) -> None:
        """The creatives_create handler round-trips the three video keys."""
        client = AsyncMock()
        client.create_ad_creative.return_value = {"id": "cr_video"}

        result = await self._dispatch(
            client,
            "meta_ads_creatives_create",
            {
                "account_id": "act_123",
                "name": "Video creative",
                "page_id": "pg_1",
                "link_url": "https://example.com",
                "video_id": "video_42",
                "video_thumbnail_image_url": "https://scontent.example/t.jpg",
                "call_to_action": "LEARN_MORE",
            },
        )

        kwargs = client.create_ad_creative.call_args.kwargs
        assert kwargs["video_id"] == "video_42"
        assert kwargs["video_thumbnail_image_url"] == "https://scontent.example/t.jpg"
        assert "video_thumbnail_image_hash" not in kwargs
        assert json.loads(result[0].text)["id"] == "cr_video"

    @pytest.mark.asyncio()
    async def test_handle_creatives_create_forwards_thumbnail_hash(self) -> None:
        client = AsyncMock()
        client.create_ad_creative.return_value = {"id": "cr_video"}

        await self._dispatch(
            client,
            "meta_ads_creatives_create",
            {
                "account_id": "act_123",
                "name": "Video creative",
                "page_id": "pg_1",
                "link_url": "https://example.com",
                "video_id": "video_42",
                "video_thumbnail_image_hash": "thumb_hash",
                "call_to_action": "SIGN_UP",
            },
        )

        kwargs = client.create_ad_creative.call_args.kwargs
        assert kwargs["video_thumbnail_image_hash"] == "thumb_hash"
        assert kwargs["call_to_action"] == "SIGN_UP"
        assert "video_thumbnail_image_url" not in kwargs


# ---------------------------------------------------------------------------
# Dispatch registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVideoToolRegistration:
    """The new tools are wired into both the registry and the dispatch map."""

    def test_tools_registered(self) -> None:
        from mureo.mcp.tools_meta_ads import TOOLS

        names = {t.name for t in TOOLS}
        assert "meta_ads_videos_get" in names
        assert "meta_ads_videos_thumbnails" in names

    def test_handlers_registered(self) -> None:
        from mureo.mcp.tools_meta_ads import _HANDLERS

        assert "meta_ads_videos_get" in _HANDLERS
        assert "meta_ads_videos_thumbnails" in _HANDLERS

    def test_video_read_tools_not_classified_mutating(self) -> None:
        """Read-only tools must not trigger the strategy reminder."""
        from mureo.core.strategy_reminder import is_mutating_builtin_tool

        assert is_mutating_builtin_tool("meta_ads_videos_get") is False
        assert is_mutating_builtin_tool("meta_ads_videos_thumbnails") is False


# ---------------------------------------------------------------------------
# _request files= plumbing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRequestFilesSupport:
    """``_post(files=...)`` passes straight through to httpx."""

    @pytest.mark.asyncio()
    async def test_post_forwards_files(self, meta_client: Any) -> None:
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"ok": True}
        meta_client._http = MagicMock()
        meta_client._http.post = AsyncMock(return_value=resp)

        files = {"source": ("a.mp4", b"bytes", "video/mp4")}
        await meta_client._post("/act_123456/advideos", {"title": "t"}, files=files)

        _, kwargs = meta_client._http.post.call_args
        assert kwargs["files"] == files
        assert kwargs["data"] == {"title": "t"}

    @pytest.mark.asyncio()
    async def test_post_without_files_omits_kwarg(self, meta_client: Any) -> None:
        """Non-multipart callers must not gain a stray ``files`` kwarg."""
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.return_value = {"ok": True}
        meta_client._http = MagicMock()
        meta_client._http.post = AsyncMock(return_value=resp)

        await meta_client._post("/act_123456/adimages", {"bytes": "abc"})

        _, kwargs = meta_client._http.post.call_args
        assert "files" not in kwargs
