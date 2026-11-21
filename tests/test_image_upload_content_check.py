"""Local image uploads send the bytes they checked (#1011).

``upload_ad_image_file`` (Meta Ads) and ``upload_image_asset`` (Google Ads)
read the file once through ``read_image_file``: what is sent is what was
checked, the read is bounded by the size limit, and content that is not the
image type its extension declares never reaches the platform.
"""

from __future__ import annotations

import base64
import os
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mureo import _image_validation
from mureo._image_validation import _read_regular_file
from tests._image_open_count import OPENED_ONCE, _count_opens
from tests.test_image_upload import _mock_shared_http
from tests.test_image_validation_dimensions import _jpeg, _png
from tests.test_image_validation_formats import _bmp, _gif, _tiff

pytestmark = pytest.mark.unit

_PNG = _png(640, 640)


def _meta_client() -> Any:
    from mureo.meta_ads.client import MetaAdsApiClient

    client = MetaAdsApiClient(access_token="test-token", ad_account_id="act_123456")
    client._http = _mock_shared_http(
        200, {"images": {"bytes": {"hash": "h", "url": "u"}}}
    )
    return client


def _google_client() -> Any:
    """A client whose SDK object is a mock that records the asset operation."""
    from mureo.google_ads.client import GoogleAdsApiClient

    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_gads.return_value = MagicMock()
        client = GoogleAdsApiClient(
            credentials=MagicMock(),
            customer_id="1234567890",
            developer_token="dev-token",
        )
    result = MagicMock()
    result.resource_name = "customers/1234567890/assets/789"
    service = MagicMock()
    service.mutate_assets.return_value.results = [result]
    client._client.get_service.return_value = service
    client._client.get_type.return_value = MagicMock()
    return client


def _sent_by_meta(client: Any) -> bytes:
    _, kwargs = client._http.post.call_args
    return base64.b64decode(kwargs["data"]["bytes"])


def _sent_by_google(client: Any) -> bytes:
    image_asset = client._client.get_type.return_value.create.image_asset
    assert image_asset.file_size == len(image_asset.data)
    return bytes(image_asset.data)


def _write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _symlink_to_text(tmp_path: Path) -> Path:
    text = _write(tmp_path, "notes.txt", b"plain text, not an image")
    link = tmp_path / "x.png"
    try:
        link.symlink_to(text)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    return link


class TestMetaUploadAdImageFile:
    @pytest.mark.parametrize(
        "name,payload",
        [
            ("a.png", _PNG),
            ("a.jpg", _jpeg(320, 200)),
            ("a.jpeg", _jpeg(320, 200)),
            ("a.gif", _gif(320, 200)),
            ("a.bmp", _bmp(320, 200)),
            ("a.tiff", _tiff()),
        ],
    )
    async def test_sends_exactly_the_file_bytes(
        self, tmp_path: Path, name: str, payload: bytes
    ) -> None:
        client = _meta_client()
        await client.upload_ad_image_file(str(_write(tmp_path, name, payload)))
        assert _sent_by_meta(client) == payload

    @pytest.mark.parametrize("name", ["a.png", "a.jpg", "a.gif", "a.bmp", "a.tiff"])
    async def test_refuses_content_that_matches_no_signature(
        self, tmp_path: Path, name: str
    ) -> None:
        client = _meta_client()
        path = _write(tmp_path, name, b"\x00" * 100)
        with pytest.raises(ValueError, match="not a recognisable"):
            await client.upload_ad_image_file(str(path))
        client._http.post.assert_not_called()

    @pytest.mark.parametrize(
        "name,payload", [("png.gif", _PNG), ("gif.png", _gif(10, 10))]
    )
    async def test_refuses_a_type_that_contradicts_the_extension(
        self, tmp_path: Path, name: str, payload: bytes
    ) -> None:
        client = _meta_client()
        with pytest.raises(ValueError, match="possible extension spoofing"):
            await client.upload_ad_image_file(str(_write(tmp_path, name, payload)))
        client._http.post.assert_not_called()

    async def test_refuses_a_png_named_link_to_a_text_file(
        self, tmp_path: Path
    ) -> None:
        client = _meta_client()
        with pytest.raises(ValueError, match="not a recognisable"):
            await client.upload_ad_image_file(str(_symlink_to_text(tmp_path)))
        client._http.post.assert_not_called()

    async def test_refuses_a_file_one_byte_over_the_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mureo.meta_ads._creatives.LOCAL_UPLOAD_MAX_IMAGE_BYTES", len(_PNG) - 1
        )
        client = _meta_client()
        with pytest.raises(ValueError, match="File size exceeds the limit"):
            await client.upload_ad_image_file(str(_write(tmp_path, "a.png", _PNG)))
        client._http.post.assert_not_called()

    async def test_accepts_a_file_exactly_at_the_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mureo.meta_ads._creatives.LOCAL_UPLOAD_MAX_IMAGE_BYTES", len(_PNG)
        )
        client = _meta_client()
        await client.upload_ad_image_file(str(_write(tmp_path, "a.png", _PNG)))
        assert _sent_by_meta(client) == _PNG

    async def test_the_file_is_opened_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second open could see a different file from the one checked."""
        client = _meta_client()
        path = _write(tmp_path, "a.png", _PNG)
        counts = _count_opens(monkeypatch, path)
        await client.upload_ad_image_file(str(path))
        assert counts == OPENED_ONCE
        client._http.post.assert_called_once()
        assert _sent_by_meta(client) == _PNG


class TestGoogleUploadImageAsset:
    @pytest.mark.parametrize(
        "name,payload",
        [("a.png", _PNG), ("a.jpg", _jpeg(320, 200)), ("a.gif", _gif(320, 200))],
    )
    async def test_sends_exactly_the_file_bytes(
        self, tmp_path: Path, name: str, payload: bytes
    ) -> None:
        client = _google_client()
        result = await client.upload_image_asset(str(_write(tmp_path, name, payload)))
        assert _sent_by_google(client) == payload
        assert result == {
            "resource_name": "customers/1234567890/assets/789",
            "id": "789",
            "name": name,
        }

    @pytest.mark.parametrize("name", ["a.png", "a.jpg", "a.gif"])
    async def test_refuses_content_that_matches_no_signature(
        self, tmp_path: Path, name: str
    ) -> None:
        client = _google_client()
        path = _write(tmp_path, name, b"\x00" * 100)
        with pytest.raises(ValueError, match="not a recognisable"):
            await client.upload_image_asset(str(path))
        client._client.get_service.return_value.mutate_assets.assert_not_called()

    @pytest.mark.parametrize(
        "name,payload", [("png.gif", _PNG), ("gif.png", _gif(10, 10))]
    )
    async def test_refuses_a_type_that_contradicts_the_extension(
        self, tmp_path: Path, name: str, payload: bytes
    ) -> None:
        client = _google_client()
        with pytest.raises(ValueError, match="possible extension spoofing"):
            await client.upload_image_asset(str(_write(tmp_path, name, payload)))
        client._client.get_service.return_value.mutate_assets.assert_not_called()

    async def test_refuses_a_png_named_link_to_a_text_file(
        self, tmp_path: Path
    ) -> None:
        client = _google_client()
        with pytest.raises(ValueError, match="not a recognisable"):
            await client.upload_image_asset(str(_symlink_to_text(tmp_path)))
        client._client.get_service.return_value.mutate_assets.assert_not_called()

    async def test_refuses_a_file_one_byte_over_the_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mureo.google_ads._media._GOOGLE_MAX_IMAGE_SIZE_BYTES", len(_PNG) - 1
        )
        client = _google_client()
        with pytest.raises(ValueError, match="File size exceeds the limit"):
            await client.upload_image_asset(str(_write(tmp_path, "a.png", _PNG)))
        client._client.get_service.return_value.mutate_assets.assert_not_called()

    async def test_accepts_a_file_exactly_at_the_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "mureo.google_ads._media._GOOGLE_MAX_IMAGE_SIZE_BYTES", len(_PNG)
        )
        client = _google_client()
        await client.upload_image_asset(str(_write(tmp_path, "a.png", _PNG)))
        assert _sent_by_google(client) == _PNG

    async def test_the_file_is_opened_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second open could see a different file from the one checked."""
        client = _google_client()
        path = _write(tmp_path, "a.png", _PNG)
        counts = _count_opens(monkeypatch, path)
        await client.upload_image_asset(str(path))
        assert counts == OPENED_ONCE
        service = client._client.get_service.return_value
        service.mutate_assets.assert_called_once()
        assert _sent_by_google(client) == _PNG


def _fstat_reporting_size(monkeypatch: pytest.MonkeyPatch, st_size: int) -> list[int]:
    """Make ``fstat`` report ``st_size``; return the descriptors it was asked about.

    Stands in for a file that grows, or is replaced, after its size is taken:
    the type stays the real one, only the size is stale.
    """
    asked: list[int] = []
    real_fstat = os.fstat

    def _stale_fstat(fd: int) -> Any:
        asked.append(fd)
        info = real_fstat(fd)
        return types.SimpleNamespace(st_mode=info.st_mode, st_size=st_size)

    monkeypatch.setattr(_image_validation.os, "fstat", _stale_fstat)
    return asked


def test_a_file_that_grew_past_the_cap_after_fstat_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounded read, not the stale size, is what refuses the file."""
    path = _write(tmp_path, "a.png", b"x" * 1025)
    asked = _fstat_reporting_size(monkeypatch, 10)
    with pytest.raises(ValueError, match="File size exceeds the limit"):
        _read_regular_file(path, "a.png", 1024, "1KB")
    monkeypatch.undo()

    assert len(asked) == 1
    with pytest.raises(OSError):
        os.fstat(asked[0])


def test_a_file_exactly_at_the_cap_after_fstat_is_read_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading one byte past the cap refuses only what is over it."""
    payload = b"x" * 1024
    path = _write(tmp_path, "a.png", payload)
    _fstat_reporting_size(monkeypatch, 10)
    assert _read_regular_file(path, "a.png", 1024, "1KB") == payload


@pytest.mark.skipif(
    sys.platform == "win32", reason="a directory cannot be opened with os.open"
)
def test_a_name_swapped_for_a_directory_leaves_no_descriptor_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal closes what it opened, however often it is provoked."""
    opened: list[int] = []
    real_open = os.open

    def _recording_open(*args: Any, **kwargs: Any) -> int:
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(os, "open", _recording_open)
    with pytest.raises(ValueError, match="not a regular file"):
        _read_regular_file(tmp_path, "hero.png", 1024, "1KB")
    monkeypatch.undo()

    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
