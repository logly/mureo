"""Tests for Meta Ads ``upload_page_photo`` (Instant Form cover photo, #151).

A form intro screen's ``context_card.cover_photo_id`` needs a PAGE photo id
(from ``POST /{page_id}/photos`` with the Page Access Token), NOT the
ad-account ``image_hash`` returned by ``upload_ad_image*``. These tests pin
that distinction and the upload contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def meta_client() -> Any:
    from mureo.meta_ads.client import MetaAdsApiClient

    client = MetaAdsApiClient(access_token="test-token", ad_account_id="act_123456")
    # Page token resolution is exercised elsewhere; stub it here so these
    # tests focus on the photo upload itself.
    client.get_page_access_token = AsyncMock(return_value="page-token")  # type: ignore[method-assign]
    return client


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    img = tmp_path / "cover.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return img


def _mock_http(status_code: int, payload: dict[str, Any]) -> Any:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    http = AsyncMock()
    http.post.return_value = resp
    http.__aenter__ = AsyncMock(return_value=http)
    http.__aexit__ = AsyncMock(return_value=False)
    return http


@pytest.mark.unit
class TestUploadPagePhoto:
    @pytest.mark.asyncio()
    async def test_upload_via_image_url_returns_photo_id(
        self, meta_client: Any
    ) -> None:
        http = _mock_http(200, {"id": "999_888"})
        with patch("mureo.meta_ads._page_posts.httpx.AsyncClient", return_value=http):
            result = await meta_client.upload_page_photo(
                "111", image_url="https://example.com/banner.png"
            )
        assert result == {"photo_id": "999_888"}
        # Posted to the page photos endpoint, unpublished, with the page token.
        _, kwargs = http.post.call_args
        assert kwargs["data"]["published"] == "false"
        assert kwargs["data"]["access_token"] == "page-token"

    @pytest.mark.asyncio()
    async def test_upload_via_file_path_returns_photo_id(
        self, meta_client: Any, sample_image: Path
    ) -> None:
        http = _mock_http(200, {"id": "777"})
        with patch("mureo.meta_ads._page_posts.httpx.AsyncClient", return_value=http):
            result = await meta_client.upload_page_photo(
                "111", file_path=str(sample_image)
            )
        assert result == {"photo_id": "777"}
        # The whole point of #151: this must hit the PAGE /photos endpoint as
        # a multipart Page photo (not the ad-account adimages hash path).
        args, kwargs = http.post.call_args
        assert args[0].endswith("/111/photos")
        assert "source" in kwargs["files"]
        assert kwargs["data"]["published"] == "false"
        assert kwargs["data"]["access_token"] == "page-token"

    @pytest.mark.asyncio()
    async def test_bad_extension_file_rejected(
        self, meta_client: Any, tmp_path: Path
    ) -> None:
        bad = tmp_path / "cover.txt"
        bad.write_text("not an image", encoding="utf-8")
        with pytest.raises(ValueError):
            await meta_client.upload_page_photo("111", file_path=str(bad))

    @pytest.mark.asyncio()
    async def test_both_inputs_raises(self, meta_client: Any) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            await meta_client.upload_page_photo(
                "111", image_url="https://x/y.png", file_path="/tmp/z.png"
            )

    @pytest.mark.asyncio()
    async def test_neither_input_raises(self, meta_client: Any) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            await meta_client.upload_page_photo("111")

    @pytest.mark.asyncio()
    async def test_api_error_returns_error_dict(self, meta_client: Any) -> None:
        http = _mock_http(403, {"error": {"message": "requires pages_manage_posts"}})
        with patch("mureo.meta_ads._page_posts.httpx.AsyncClient", return_value=http):
            result = await meta_client.upload_page_photo(
                "111", image_url="https://example.com/banner.png"
            )
        assert "error" in result
        assert "pages_manage_posts" in result["error"]

    @pytest.mark.asyncio()
    async def test_error_text_fallback_redacts_page_token(
        self, meta_client: Any
    ) -> None:
        """A non-JSON error body must never leak the page token (defense-in-depth)."""
        resp = MagicMock()
        resp.status_code = 500
        resp.json.side_effect = ValueError("not json")
        resp.text = "upstream error for token page-token boom"
        http = AsyncMock()
        http.post.return_value = resp
        http.__aenter__ = AsyncMock(return_value=http)
        http.__aexit__ = AsyncMock(return_value=False)
        with patch("mureo.meta_ads._page_posts.httpx.AsyncClient", return_value=http):
            result = await meta_client.upload_page_photo(
                "111", image_url="https://example.com/banner.png"
            )
        assert "error" in result
        assert "page-token" not in result["error"]

    @pytest.mark.asyncio()
    async def test_missing_id_returns_error(self, meta_client: Any) -> None:
        http = _mock_http(200, {})
        with patch("mureo.meta_ads._page_posts.httpx.AsyncClient", return_value=http):
            result = await meta_client.upload_page_photo(
                "111", image_url="https://example.com/banner.png"
            )
        assert "error" in result
