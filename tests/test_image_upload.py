"""Tests for the image-upload feature.

Meta Ads: upload_ad_image_file
Google Ads: upload_image_asset
MCP tools: meta_ads_images_upload_file, google_ads_assets_upload_image
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Meta Ads: upload_ad_image_file
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _standalone_account_scoping():
    """Pin these tests to STANDALONE (untenanted) Google/Meta handlers.

    #411 added workspace scoping: with a ``mureo.runtime_context_factory``
    installed whose store is a shared-auth multi-account backend, an
    undeclared allow-list fail-closes every account id. A dev box carrying
    such a plugin would break these standalone assertions. Neutralize both
    seams; scoped behavior lives in test_account_id_tenant_scope.py.
    """
    with (
        patch(
            "mureo.mcp._handlers_google_ads.runtime_google_ads_customer_ids",
            return_value=None,
        ),
        patch(
            "mureo.mcp._handlers_meta_ads.runtime_meta_account_ids",
            return_value=None,
        ),
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
def sample_image(tmp_path: Path) -> Path:
    """Create a dummy image file for tests."""
    img = tmp_path / "test_image.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return img


@pytest.fixture()
def sample_jpg(tmp_path: Path) -> Path:
    """Create a dummy JPG file for tests."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return img


def _mock_shared_http(
    status_code: int = 200, payload: dict[str, Any] | None = None
) -> Any:
    """Mock the client's shared ``self._http`` (the ``_request`` seam).

    ``upload_ad_image_file`` routes through the shared ``_request``/``_post``
    machinery (so Meta's error JSON, retries and rate-limit handling apply)
    instead of building a one-off ``httpx.AsyncClient``. Tests therefore mock
    ``client._http.post`` rather than ``_creatives.httpx.AsyncClient``.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    resp.text = json.dumps(payload if payload is not None else {})
    resp.headers = {}
    http = MagicMock()
    http.post = AsyncMock(return_value=resp)
    http.get = AsyncMock(return_value=resp)
    http.delete = AsyncMock(return_value=resp)
    return http


class TestMetaUploadAdImageFile:
    """Tests for Meta Ads upload_ad_image_file.

    The uploader sends the image as a base64 ``bytes`` form field (the same
    shape the URL-based ``upload_ad_image`` path uses in production). Multipart
    uploads to /adimages were rejected by Meta with ``FileTypeNotSupported``
    (subcode 1487411) even when provably well-formed, so the multipart approach
    was abandoned.
    """

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """Successful upload returns hash/url."""
        meta_client._http = _mock_shared_http(
            200,
            {
                "images": {
                    "bytes": {
                        "hash": "abc123hash",
                        "url": "https://example.com/image.png",
                    }
                }
            },
        )

        result = await meta_client.upload_ad_image_file(str(sample_image))

        assert result["hash"] == "abc123hash"
        assert result["url"] == "https://example.com/image.png"

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_bytes_form_body(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """The file is uploaded as a base64 ``bytes`` form field (not multipart).

        Multipart to /adimages was rejected by Meta with ``FileTypeNotSupported``
        (subcode 1487411) even when the multipart body was provably well-formed,
        so the uploader uses the documented base64 ``bytes`` form-body variant --
        the same shape the URL-based ``upload_ad_image`` path already uses
        successfully in production.
        """
        meta_client._http = _mock_shared_http(
            200, {"images": {"bytes": {"hash": "h", "url": "u"}}}
        )

        await meta_client.upload_ad_image_file(str(sample_image))

        _, kwargs = meta_client._http.post.call_args
        expected_b64 = base64.b64encode(sample_image.read_bytes()).decode("utf-8")
        # Plain form body carrying only the base64 bytes -- no multipart.
        assert kwargs["data"] == {"bytes": expected_b64}
        assert kwargs.get("files") is None
        # Auth on the Bearer header only; never as an access_token form field.
        assert kwargs["headers"]["Authorization"] == "Bearer test-token"
        assert "access_token" not in kwargs["data"]

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_name_not_sent_on_wire(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """``name`` is accepted for API compatibility but not transmitted.

        The base64 ``bytes`` variant of /adimages has no documented ``name``
        form field, so the parameter is kept in the signature but dropped from
        the request body.
        """
        meta_client._http = _mock_shared_http(
            200, {"images": {"bytes": {"hash": "h", "url": "u"}}}
        )

        await meta_client.upload_ad_image_file(str(sample_image), name="my custom name")

        _, kwargs = meta_client._http.post.call_args
        assert list(kwargs["data"].keys()) == ["bytes"]
        assert "my custom name" not in str(kwargs["data"])

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_uses_60s_timeout(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """The upload is issued with the explicit 60s per-request timeout.

        validate_image_file allows files up to 30MB; base64 of that is ~40MB of
        body, and the shared client's default timeout is only 30s. Routing
        uploads through _request must not drop the previous standalone 60s
        timeout, or a large image on a slow link that used to succeed would now
        time out.
        """
        meta_client._http = _mock_shared_http(
            200, {"images": {"bytes": {"hash": "h", "url": "u"}}}
        )

        await meta_client.upload_ad_image_file(str(sample_image))

        _, kwargs = meta_client._http.post.call_args
        assert kwargs["timeout"] == 60.0

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_retry_resends_body(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """A 429-then-200 retry re-sends the identical, non-empty base64 body.

        ``_request`` reuses the same ``data`` dict across retry attempts; both
        attempts must carry the full base64 image body.
        """
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {}
        resp_429.json.return_value = {}
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.json.return_value = {"images": {"bytes": {"hash": "h", "url": "u"}}}
        responses = [resp_429, resp_200]

        sent_bodies: list[str] = []

        def _capture(*_args: Any, **kwargs: Any) -> Any:
            sent_bodies.append(kwargs["data"]["bytes"])
            return responses.pop(0)

        meta_client._http = MagicMock()
        meta_client._http.post = AsyncMock(side_effect=_capture)

        # Don't actually sleep through the 429 backoff.
        with patch("mureo.meta_ads.client.asyncio.sleep", new=AsyncMock()):
            result = await meta_client.upload_ad_image_file(str(sample_image))

        expected_b64 = base64.b64encode(sample_image.read_bytes()).decode("utf-8")
        assert result == {"hash": "h", "url": "u"}
        assert len(sent_bodies) == 2  # 429 attempt + 200 retry
        assert sent_bodies[0] == expected_b64  # non-empty, full body
        assert sent_bodies[0] == sent_bodies[1]  # identical on retry

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_non_ascii_path(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """A non-ASCII file path still uploads and parses back.

        The filename never travels on the wire in the ``bytes`` variant (only
        the base64 content does), so a Japanese path must upload fine.
        """
        img = tmp_path / "テスト画像.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        meta_client._http = _mock_shared_http(
            200, {"images": {"bytes": {"hash": "jp-hash", "url": "jp-url"}}}
        )

        result = await meta_client.upload_ad_image_file(str(img))

        assert result == {"hash": "jp-hash", "url": "jp-url"}
        _, kwargs = meta_client._http.post.call_args
        expected_b64 = base64.b64encode(img.read_bytes()).decode("utf-8")
        assert kwargs["data"]["bytes"] == expected_b64

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_surfaces_meta_error(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """A 400 carrying Meta's error JSON surfaces message + fbtrace_id.

        Regression for the error-swallowing complaint: the old code called
        ``response.raise_for_status()`` directly, so the user only ever saw
        httpx's generic ``Client error '400 Bad Request'`` and Meta's real
        diagnostics (error.message / error_subcode / fbtrace_id) were lost.
        Routing through ``_request`` must surface them.
        """
        meta_client._http = _mock_shared_http(
            400,
            {
                "error": {
                    "message": "Invalid parameter",
                    "error_subcode": 1487411,
                    "fbtrace_id": "AbCdEf123XYZ",
                }
            },
        )

        with pytest.raises(RuntimeError) as excinfo:
            await meta_client.upload_ad_image_file(str(sample_image))

        message = str(excinfo.value)
        assert "status=400" in message
        assert "Invalid parameter" in message
        assert "AbCdEf123XYZ" in message

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_not_found(self, meta_client: Any) -> None:
        """Raises FileNotFoundError when the file does not exist."""
        with pytest.raises(FileNotFoundError):
            await meta_client.upload_ad_image_file("/nonexistent/path/image.png")

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_too_large(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for files larger than 30MB."""
        large_file = tmp_path / "large.png"
        # 30MB + 1 byte
        large_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (30 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="30MB"):
            await meta_client.upload_ad_image_file(str(large_file))

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_invalid_format(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for unsupported file formats."""
        txt_file = tmp_path / "document.txt"
        txt_file.write_bytes(b"not an image")

        with pytest.raises(ValueError, match="Unsupported image format"):
            await meta_client.upload_ad_image_file(str(txt_file))

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_path_traversal(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """Paths containing path-traversal segments are rejected."""
        with pytest.raises(ValueError, match="Invalid file path"):
            await meta_client.upload_ad_image_file(
                str(tmp_path / ".." / ".." / "etc" / "passwd")
            )

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_supported_formats(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """jpg, jpeg, png, gif, bmp, tiff all upload as base64 ``bytes``."""
        for ext in ("jpg", "jpeg", "png", "gif", "bmp", "tiff"):
            img = tmp_path / f"test.{ext}"
            content = b"\x00" * 100
            img.write_bytes(content)
            meta_client._http = _mock_shared_http(
                200, {"images": {"bytes": {"hash": "h", "url": "u"}}}
            )
            result = await meta_client.upload_ad_image_file(str(img))
            assert "hash" in result
            _, kwargs = meta_client._http.post.call_args
            assert kwargs["data"] == {
                "bytes": base64.b64encode(content).decode("utf-8")
            }
            assert kwargs.get("files") is None


# ---------------------------------------------------------------------------
# Google Ads: upload_image_asset
# ---------------------------------------------------------------------------


class TestGoogleAdsUploadImageAsset:
    """Tests for Google Ads upload_image_asset."""

    @pytest.fixture()
    def google_client(self) -> Any:
        """Create a mocked GoogleAdsApiClient for tests."""
        from mureo.google_ads.client import GoogleAdsApiClient

        with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
            mock_instance = MagicMock()
            mock_gads.return_value = mock_instance
            mock_creds = MagicMock()
            client = GoogleAdsApiClient(
                credentials=mock_creds,
                customer_id="1234567890",
                developer_token="dev-token",
            )
        return client

    @pytest.mark.asyncio()
    async def test_upload_image_asset(
        self, google_client: Any, sample_image: Path
    ) -> None:
        """Successful upload returns resource_name/id/name."""
        # Mock AssetService
        mock_asset_service = MagicMock()
        mock_response = MagicMock()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/1234567890/assets/789"
        mock_response.results = [mock_result]
        mock_asset_service.mutate_assets.return_value = mock_response

        google_client._client.get_service.return_value = mock_asset_service

        # Mock AssetOperation
        mock_operation = MagicMock()
        mock_asset = MagicMock()
        mock_operation.create = mock_asset
        google_client._client.get_type.return_value = mock_operation

        # Mock enums
        mock_enum = MagicMock()
        mock_enum.IMAGE = 1
        google_client._client.enums.AssetTypeEnum.AssetType = mock_enum

        import asyncio

        loop = asyncio.get_event_loop()
        with patch.object(loop, "run_in_executor", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_response
            result = await google_client.upload_image_asset(str(sample_image))

        assert result["resource_name"] == "customers/1234567890/assets/789"
        assert result["id"] == "789"

    @pytest.mark.asyncio()
    async def test_upload_image_asset_not_found(self, google_client: Any) -> None:
        """Raises FileNotFoundError when the file does not exist."""
        with pytest.raises(FileNotFoundError):
            await google_client.upload_image_asset("/nonexistent/image.png")

    @pytest.mark.asyncio()
    async def test_upload_image_asset_too_large(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for files larger than 5MB."""
        large_file = tmp_path / "large.png"
        large_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="5MB"):
            await google_client.upload_image_asset(str(large_file))

    @pytest.mark.asyncio()
    async def test_upload_image_asset_invalid_format(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """Raises ValueError for unsupported formats (e.g. bmp)."""
        bmp_file = tmp_path / "image.bmp"
        bmp_file.write_bytes(b"\x00" * 100)

        with pytest.raises(ValueError, match="Unsupported image format"):
            await google_client.upload_image_asset(str(bmp_file))

    @pytest.mark.asyncio()
    async def test_upload_image_asset_path_traversal(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """Paths containing path-traversal segments are rejected."""
        with pytest.raises(ValueError, match="Invalid file path"):
            await google_client.upload_image_asset(
                str(tmp_path / ".." / ".." / "etc" / "passwd")
            )

    @pytest.mark.asyncio()
    async def test_upload_image_asset_with_name(
        self, google_client: Any, sample_image: Path
    ) -> None:
        """When `name` is provided, that value is used as the asset name."""
        mock_asset_service = MagicMock()
        mock_response = MagicMock()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/1234567890/assets/789"
        mock_response.results = [mock_result]
        mock_asset_service.mutate_assets.return_value = mock_response

        google_client._client.get_service.return_value = mock_asset_service

        mock_operation = MagicMock()
        mock_asset = MagicMock()
        mock_operation.create = mock_asset
        google_client._client.get_type.return_value = mock_operation

        mock_enum = MagicMock()
        mock_enum.IMAGE = 1
        google_client._client.enums.AssetTypeEnum.AssetType = mock_enum

        import asyncio

        loop = asyncio.get_event_loop()
        with patch.object(loop, "run_in_executor", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_response
            result = await google_client.upload_image_asset(
                str(sample_image), name="my-asset"
            )

        assert result["name"] == "my-asset"


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


class TestMcpMetaUploadFile:
    """Tests for the MCP meta_ads_images_upload_file tool."""

    def test_tool_definition_exists(self) -> None:
        """meta_ads_images_upload_file is defined in TOOLS."""
        from mureo.mcp.tools_meta_ads import TOOLS

        names = [t.name for t in TOOLS]
        assert "meta_ads_images_upload_file" in names

    def test_tool_schema(self) -> None:
        """The tool schema includes file_path as a required parameter."""
        from mureo.mcp.tools_meta_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "meta_ads_images_upload_file")
        assert "file_path" in tool.inputSchema["properties"]
        assert "file_path" in tool.inputSchema["required"]

    @pytest.mark.asyncio()
    async def test_mcp_meta_upload_file(self, sample_image: Path) -> None:
        """The MCP handler invokes the client correctly."""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_ad_image_file.return_value = {
            "hash": "abc",
            "url": "https://example.com/img.png",
        }

        from mureo.auth import MetaAdsCredentials

        creds = MetaAdsCredentials(access_token="tok")
        with (
            patch(
                "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
                return_value=creds,
            ),
            patch(
                "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "meta_ads_images_upload_file",
                {
                    "account_id": "act_123",
                    "file_path": str(sample_image),
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["hash"] == "abc"


class TestMcpGoogleUploadImage:
    """Tests for the MCP google_ads_assets_upload_image tool."""

    def test_tool_definition_exists(self) -> None:
        """google_ads_assets_upload_image is defined in TOOLS."""
        from mureo.mcp.tools_google_ads import TOOLS

        names = [t.name for t in TOOLS]
        assert "google_ads_assets_upload_image" in names

    def test_tool_schema(self) -> None:
        """The tool schema includes file_path as a required parameter."""
        from mureo.mcp.tools_google_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "google_ads_assets_upload_image")
        assert "file_path" in tool.inputSchema["properties"]
        assert "file_path" in tool.inputSchema["required"]

    @pytest.mark.asyncio()
    async def test_mcp_google_upload_image(self, sample_image: Path) -> None:
        """The MCP handler invokes the client correctly."""
        from mureo.mcp.tools_google_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_image_asset.return_value = {
            "resource_name": "customers/123/assets/456",
            "id": "456",
            "name": "test_image.png",
        }

        with (
            patch(
                "mureo.mcp._handlers_google_ads.load_google_ads_credentials",
                return_value={"developer_token": "tok"},
            ),
            patch(
                "mureo.mcp._handlers_google_ads.create_google_ads_client",
                return_value=mock_client,
            ),
        ):
            result = await handle_tool(
                "google_ads_assets_upload_image",
                {
                    "customer_id": "1234567890",
                    "file_path": str(sample_image),
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["resource_name"] == "customers/123/assets/456"
