"""画像アップロード機能のテスト

Meta Ads: upload_ad_image_file
Google Ads: upload_image_asset
MCPツール: meta_ads.images.upload_file, google_ads.assets.upload_image
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Meta Ads: upload_ad_image_file
# ---------------------------------------------------------------------------


@pytest.fixture()
def meta_client() -> Any:
    """テスト用MetaAdsApiClientを作成する"""
    from mureo.meta_ads.client import MetaAdsApiClient

    return MetaAdsApiClient(
        access_token="test-token",
        ad_account_id="act_123456",
    )


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    """テスト用のダミー画像ファイルを作成する"""
    img = tmp_path / "test_image.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return img


@pytest.fixture()
def sample_jpg(tmp_path: Path) -> Path:
    """テスト用のダミーJPGファイルを作成する"""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    return img


class TestMetaUploadAdImageFile:
    """Meta Ads upload_ad_image_file のテスト"""

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """正常アップロードでhash/urlが返ること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "images": {
                "test_image.png": {
                    "hash": "abc123hash",
                    "url": "https://example.com/image.png",
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mureo.meta_ads._creatives.httpx.AsyncClient", return_value=mock_http_client):
            result = await meta_client.upload_ad_image_file(str(sample_image))

        assert result["hash"] == "abc123hash"
        assert result["url"] == "https://example.com/image.png"

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_with_name(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        """name指定時にそのnameが使われること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "images": {
                "custom_name.png": {
                    "hash": "abc123hash",
                    "url": "https://example.com/image.png",
                }
            }
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mureo.meta_ads._creatives.httpx.AsyncClient", return_value=mock_http_client):
            result = await meta_client.upload_ad_image_file(
                str(sample_image), name="custom_name.png"
            )

        assert result["hash"] == "abc123hash"

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_not_found(
        self, meta_client: Any
    ) -> None:
        """ファイルが存在しない場合にFileNotFoundErrorが発生すること"""
        with pytest.raises(FileNotFoundError):
            await meta_client.upload_ad_image_file("/nonexistent/path/image.png")

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_too_large(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """30MB超のファイルでValueErrorが発生すること"""
        large_file = tmp_path / "large.png"
        # 30MB + 1 byte
        large_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (30 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="30MB"):
            await meta_client.upload_ad_image_file(str(large_file))

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_invalid_format(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """未対応形式でValueErrorが発生すること"""
        txt_file = tmp_path / "document.txt"
        txt_file.write_bytes(b"not an image")

        with pytest.raises(ValueError, match="Unsupported image format"):
            await meta_client.upload_ad_image_file(str(txt_file))

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_path_traversal(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """パストラバーサルを含むパスが拒否されること"""
        with pytest.raises(ValueError, match="Invalid file path"):
            await meta_client.upload_ad_image_file(
                str(tmp_path / ".." / ".." / "etc" / "passwd")
            )

    @pytest.mark.asyncio()
    async def test_upload_ad_image_file_supported_formats(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        """jpg, jpeg, png, gif, bmp, tiffが許可されること"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "images": {"img": {"hash": "h", "url": "u"}}
        }
        mock_response.raise_for_status = MagicMock()

        mock_http_client = AsyncMock()
        mock_http_client.post.return_value = mock_response
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        for ext in ("jpg", "jpeg", "png", "gif", "bmp", "tiff"):
            img = tmp_path / f"test.{ext}"
            img.write_bytes(b"\x00" * 100)
            with patch(
                "mureo.meta_ads._creatives.httpx.AsyncClient",
                return_value=mock_http_client,
            ):
                result = await meta_client.upload_ad_image_file(str(img))
                assert "hash" in result


# ---------------------------------------------------------------------------
# Google Ads: upload_image_asset
# ---------------------------------------------------------------------------


class TestGoogleAdsUploadImageAsset:
    """Google Ads upload_image_asset のテスト"""

    @pytest.fixture()
    def google_client(self) -> Any:
        """テスト用GoogleAdsApiClientをモックで作成する"""
        from mureo.google_ads.client import GoogleAdsApiClient

        with patch(
            "mureo.google_ads.client.GoogleAdsClient"
        ) as mock_gads:
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
        """正常アップロードでresource_name/id/nameが返ること"""
        # AssetServiceのモック
        mock_asset_service = MagicMock()
        mock_response = MagicMock()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/1234567890/assets/789"
        mock_response.results = [mock_result]
        mock_asset_service.mutate_assets.return_value = mock_response

        google_client._client.get_service.return_value = mock_asset_service

        # AssetOperation のモック
        mock_operation = MagicMock()
        mock_asset = MagicMock()
        mock_operation.create = mock_asset
        google_client._client.get_type.return_value = mock_operation

        # enums のモック
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
    async def test_upload_image_asset_not_found(
        self, google_client: Any
    ) -> None:
        """ファイルが存在しない場合にFileNotFoundErrorが発生すること"""
        with pytest.raises(FileNotFoundError):
            await google_client.upload_image_asset("/nonexistent/image.png")

    @pytest.mark.asyncio()
    async def test_upload_image_asset_too_large(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """5MB超のファイルでValueErrorが発生すること"""
        large_file = tmp_path / "large.png"
        large_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024 + 1))

        with pytest.raises(ValueError, match="5MB"):
            await google_client.upload_image_asset(str(large_file))

    @pytest.mark.asyncio()
    async def test_upload_image_asset_invalid_format(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """未対応形式（bmp等）でValueErrorが発生すること"""
        bmp_file = tmp_path / "image.bmp"
        bmp_file.write_bytes(b"\x00" * 100)

        with pytest.raises(ValueError, match="Unsupported image format"):
            await google_client.upload_image_asset(str(bmp_file))

    @pytest.mark.asyncio()
    async def test_upload_image_asset_path_traversal(
        self, google_client: Any, tmp_path: Path
    ) -> None:
        """パストラバーサルを含むパスが拒否されること"""
        with pytest.raises(ValueError, match="Invalid file path"):
            await google_client.upload_image_asset(
                str(tmp_path / ".." / ".." / "etc" / "passwd")
            )

    @pytest.mark.asyncio()
    async def test_upload_image_asset_with_name(
        self, google_client: Any, sample_image: Path
    ) -> None:
        """name指定時にそのnameがアセット名として使われること"""
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
# MCP ツール
# ---------------------------------------------------------------------------


class TestMcpMetaUploadFile:
    """MCP meta_ads.images.upload_file ツールのテスト"""

    def test_tool_definition_exists(self) -> None:
        """meta_ads.images.upload_file がTOOLSに定義されていること"""
        from mureo.mcp.tools_meta_ads import TOOLS

        names = [t.name for t in TOOLS]
        assert "meta_ads.images.upload_file" in names

    def test_tool_schema(self) -> None:
        """ツールスキーマにfile_pathが必須パラメータとして含まれること"""
        from mureo.mcp.tools_meta_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "meta_ads.images.upload_file")
        assert "file_path" in tool.inputSchema["properties"]
        assert "file_path" in tool.inputSchema["required"]

    @pytest.mark.asyncio()
    async def test_mcp_meta_upload_file(self, sample_image: Path) -> None:
        """MCPハンドラーが正常にクライアントを呼び出すこと"""
        from mureo.mcp.tools_meta_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_ad_image_file.return_value = {
            "hash": "abc", "url": "https://example.com/img.png"
        }

        with patch(
            "mureo.mcp._handlers_meta_ads.load_meta_ads_credentials",
            return_value={"access_token": "tok"},
        ), patch(
            "mureo.mcp._handlers_meta_ads.create_meta_ads_client",
            return_value=mock_client,
        ):
            result = await handle_tool(
                "meta_ads.images.upload_file",
                {
                    "account_id": "act_123",
                    "file_path": str(sample_image),
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["hash"] == "abc"


class TestMcpGoogleUploadImage:
    """MCP google_ads.assets.upload_image ツールのテスト"""

    def test_tool_definition_exists(self) -> None:
        """google_ads.assets.upload_image がTOOLSに定義されていること"""
        from mureo.mcp.tools_google_ads import TOOLS

        names = [t.name for t in TOOLS]
        assert "google_ads.assets.upload_image" in names

    def test_tool_schema(self) -> None:
        """ツールスキーマにfile_pathが必須パラメータとして含まれること"""
        from mureo.mcp.tools_google_ads import TOOLS

        tool = next(t for t in TOOLS if t.name == "google_ads.assets.upload_image")
        assert "file_path" in tool.inputSchema["properties"]
        assert "file_path" in tool.inputSchema["required"]

    @pytest.mark.asyncio()
    async def test_mcp_google_upload_image(self, sample_image: Path) -> None:
        """MCPハンドラーが正常にクライアントを呼び出すこと"""
        from mureo.mcp.tools_google_ads import handle_tool

        mock_client = AsyncMock()
        mock_client.upload_image_asset.return_value = {
            "resource_name": "customers/123/assets/456",
            "id": "456",
            "name": "test_image.png",
        }

        with patch(
            "mureo.mcp._handlers_google_ads.load_google_ads_credentials",
            return_value={"developer_token": "tok"},
        ), patch(
            "mureo.mcp._handlers_google_ads.create_google_ads_client",
            return_value=mock_client,
        ):
            result = await handle_tool(
                "google_ads.assets.upload_image",
                {
                    "customer_id": "1234567890",
                    "file_path": str(sample_image),
                },
            )

        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["resource_name"] == "customers/123/assets/456"
