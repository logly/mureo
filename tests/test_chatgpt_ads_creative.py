"""The ChatGPT Ads image upload, ad preview and location search tools (#995).

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request. Pinned here: the multipart upload
(field, filename, content type, no ``purpose``), the local file checks that
run before any request (the shared image validator, the size cap of the
other local image uploads), the preview as a retried read, and the location
search arguments.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mureo._image_validation import (
    LOCAL_UPLOAD_MAX_IMAGE_BYTES,
    LOCAL_UPLOAD_MAX_IMAGE_LABEL,
)
from mureo.chatgpt_ads import handlers_creative
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_creative import CREATIVE_TOOLS
from mureo.mcp.plugin_semantics import derive_semantics
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    by_name,
    call_tool,
    fail_tool,
    install_fake_api,
    is_multipart,
    multipart_parts,
    schema_errors,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_BY_NAME = by_name(CREATIVE_TOOLS)
_UPLOAD = "chatgpt_ads_images_upload_file"
_PREVIEW = "chatgpt_ads_ads_preview"
_SEARCH = "chatgpt_ads_locations_search"
_PREVIEW_ANSWER = {"data": [{"body": "<iframe src='https://x'></iframe>"}]}
_GEO_ANSWER = {
    "query": "calif",
    "count": 1,
    "results": [{"id": "1014044", "name": "California", "type": "region"}],
}


def _png(width: int = 640, height: int = 640) -> bytes:
    ihdr = struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"\x08\x06\x00\x00\x00" + b"\x00" * 4


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


class TestDefinitions:
    def test_the_three_tools(self) -> None:
        assert tuple(_BY_NAME) == (_UPLOAD, _PREVIEW, _SEARCH)

    @pytest.mark.parametrize(
        ("name", "mutating"), [(_UPLOAD, True), (_PREVIEW, False), (_SEARCH, False)]
    )
    def test_closed_throttled_and_flagged(self, name: str, mutating: bool) -> None:
        tool = _BY_NAME[name]
        semantics = derive_semantics(tool)
        assert tool.inputSchema["additionalProperties"] is False
        assert semantics.mutating is mutating
        assert semantics.throttle is not None
        assert semantics.identity is None

    @pytest.mark.parametrize(
        ("name", "phrases"),
        [
            (_UPLOAD, ("JPEG", "PNG", "WebP", "640", "creative.file_id", "30MB")),
            (_PREVIEW, ("iframe", "24 hours", "draft")),
            (_SEARCH, ("targeting.locations.include", "id")),
        ],
    )
    def test_descriptions_state_what_the_operator_must_know(
        self, name: str, phrases: tuple[str, ...]
    ) -> None:
        description = _BY_NAME[name].description or ""
        for phrase in phrases:
            assert phrase in description, phrase


class TestUpload:
    @pytest.mark.parametrize(
        ("suffix", "content_type"),
        [
            (".png", "image/png"),
            (".PNG", "image/png"),
            (".jpg", "image/jpeg"),
            (".jpeg", "image/jpeg"),
            (".webp", "image/webp"),
        ],
    )
    async def test_multipart_field_filename_and_content_type(
        self, api: FakeAPI, tmp_path: Path, suffix: str, content_type: str
    ) -> None:
        image = tmp_path / f"card{suffix}"
        # Each body carries its format's signature: the shared validator
        # refuses a file whose bytes contradict its extension.
        data = {
            "image/png": _png(),
            "image/jpeg": b"\xff\xd8\xff\xd9",
            "image/webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16,
        }[content_type]
        image.write_bytes(data)
        api.add("/upload", body={"file_id": "file_1"})
        assert await call_tool(_UPLOAD, {"file_path": str(image)}) == {
            "file_id": "file_1"
        }
        sent = api.requests[0]
        assert (sent.method, sent.url.path) == ("POST", "/v1/upload")
        assert is_multipart(sent)
        parts = multipart_parts(sent)
        assert list(parts) == ["file"]
        disposition = parts["file"]["headers"]["Content-Disposition"]
        assert f'filename="card{suffix}"' in disposition
        assert parts["file"]["headers"]["Content-Type"] == content_type
        assert parts["file"]["content"] == data

    def test_the_cap_is_the_local_upload_cap(self) -> None:
        assert LOCAL_UPLOAD_MAX_IMAGE_BYTES == 30 * 1024 * 1024
        assert LOCAL_UPLOAD_MAX_IMAGE_LABEL == "30MB"

    async def test_a_file_over_the_cap_sends_nothing(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        image = tmp_path / "big.png"
        with image.open("wb") as handle:
            handle.write(_png())
            handle.truncate(LOCAL_UPLOAD_MAX_IMAGE_BYTES + 1)
        with pytest.raises(ValueError, match="30MB"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(image)}
            )
        assert api.requests == []

    @pytest.mark.parametrize(
        ("name", "data", "error"),
        [
            ("card.gif", b"GIF89a" + b"\x00" * 10, ValueError),
            ("card.svg", b"<svg/>", ValueError),
            ("card.png", b"\xff\xd8\xff\xd9", ValueError),
        ],
        ids=["gif", "svg", "jpeg-named-png"],
    )
    async def test_an_unsupported_file_sends_nothing(
        self,
        api: FakeAPI,
        tmp_path: Path,
        name: str,
        data: bytes,
        error: type[Exception],
    ) -> None:
        image = tmp_path / name
        image.write_bytes(data)
        with pytest.raises(error):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(image)}
            )
        assert api.requests == []

    async def test_a_missing_file_sends_nothing(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        with pytest.raises(FileNotFoundError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(tmp_path / "nope.png")}
            )
        assert api.requests == []

    async def test_a_directory_sends_nothing(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        folder = tmp_path / "folder.png"
        folder.mkdir()
        with pytest.raises(ValueError, match="not a regular file"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(folder)}
            )
        assert api.requests == []

    async def test_a_traversing_path_is_refused_like_the_other_uploads(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        (tmp_path / "card.png").write_bytes(_png())
        path = str(tmp_path / "sub" / ".." / "card.png")
        with pytest.raises(ValueError, match="must not contain '..'"):
            await ChatGPTAdsProvider().handle_mcp_tool(_UPLOAD, {"file_path": path})
        assert api.requests == []

    @pytest.mark.parametrize("value", [None, "", 7])
    async def test_no_usable_path_sends_nothing(
        self, api: FakeAPI, value: object
    ) -> None:
        with pytest.raises(ValueError, match="file_path"):
            await ChatGPTAdsProvider().handle_mcp_tool(_UPLOAD, {"file_path": value})
        assert api.requests == []

    async def test_a_5xx_is_final_and_quotes_nothing_of_the_file(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        image = tmp_path / "secret-dir" / "card.png"
        image.parent.mkdir()
        marker = b"FILE-CONTENT-MARKER"
        image.write_bytes(_png() + marker)
        api.add("/upload", 500, {"error": {"message": "upload failed"}})
        failure = await fail_tool(_UPLOAD, {"file_path": str(image)})
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)
        assert "FILE-CONTENT-MARKER" not in failure.detail
        assert "secret-dir" not in failure.detail

    @pytest.mark.parametrize("name", ["notes.png", "notes.jpg", "notes.webp"])
    async def test_a_text_file_with_an_image_name_sends_nothing(
        self, api: FakeAPI, tmp_path: Path, name: str
    ) -> None:
        image = tmp_path / name
        image.write_text("not an image", encoding="utf-8")
        with pytest.raises(ValueError, match="not a recognisable"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(image)}
            )
        assert api.requests == []

    async def test_a_link_is_followed_only_to_an_image(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        real = tmp_path / "real.png"
        real.write_bytes(_png())
        text = tmp_path / "notes.txt"
        text.write_text("plain text", encoding="utf-8")
        to_image = tmp_path / "to_image.png"
        to_text = tmp_path / "to_text.png"
        try:
            to_image.symlink_to(real)
            to_text.symlink_to(text)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        with pytest.raises(ValueError, match="not a recognisable"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                _UPLOAD, {"file_path": str(to_text)}
            )
        assert api.requests == []
        api.add("/upload", body={"file_id": "file_1"})
        await call_tool(_UPLOAD, {"file_path": str(to_image)})
        assert multipart_parts(api.requests[0])["file"]["content"] == _png()

    async def test_the_bytes_sent_are_the_bytes_checked(
        self, api: FakeAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The file is not read again by name after the check: what the
        shared check returned is what goes into the multipart body."""
        image = tmp_path / "card.png"
        image.write_bytes(_png())
        checked = _png(800, 800)

        def read_checked(file_path: str, **_kwargs: Any) -> tuple[Path, bytes]:
            return image, checked

        monkeypatch.setattr(handlers_creative, "read_image_file", read_checked)
        api.add("/upload", body={"file_id": "file_1"})
        await call_tool(_UPLOAD, {"file_path": str(image)})
        assert multipart_parts(api.requests[0])["file"]["content"] == checked

    async def test_a_transport_error_is_final(
        self, api: FakeAPI, tmp_path: Path
    ) -> None:
        image = tmp_path / "card.png"
        image.write_bytes(_png())
        api.raise_on["/v1/upload"] = httpx.ConnectError("down")
        failure = await fail_tool(_UPLOAD, {"file_path": str(image)})
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)

    async def test_a_429_is_retried(self, api: FakeAPI, tmp_path: Path) -> None:
        image = tmp_path / "card.png"
        image.write_bytes(_png())
        api.add("/upload", 429, {"error": {"message": "slow down"}})
        api.add("/upload", body={"file_id": "file_1"})
        assert await call_tool(_UPLOAD, {"file_path": str(image)}) == {
            "file_id": "file_1"
        }
        assert len(api.requests) == 2

    def test_the_schema_takes_a_path_only(self) -> None:
        assert schema_errors(_BY_NAME[_UPLOAD], {"file_path": "/x/card.png"}) == []
        assert schema_errors(_BY_NAME[_UPLOAD], {}) != []
        assert schema_errors(_BY_NAME[_UPLOAD], {"file_path": ""}) != []
        assert (
            schema_errors(_BY_NAME[_UPLOAD], {"file_path": "/x.png", "purpose": "x"})
            != []
        )


class TestPreview:
    async def test_posts_without_a_body_and_passes_the_answer_through(
        self, api: FakeAPI
    ) -> None:
        api.add("/ads/ad_1/preview", body=_PREVIEW_ANSWER)
        assert await call_tool(_PREVIEW, {"ad_id": "ad_1"}) == _PREVIEW_ANSWER
        sent = api.requests[0]
        assert (sent.method, sent.url.path, sent.content) == (
            "POST",
            "/v1/ads/ad_1/preview",
            b"",
        )
        assert "idempotency-key" not in sent.headers

    async def test_a_5xx_is_retried_like_a_read(self, api: FakeAPI) -> None:
        api.add("/ads/ad_1/preview", 503, {})
        api.add("/ads/ad_1/preview", body=_PREVIEW_ANSWER)
        assert await call_tool(_PREVIEW, {"ad_id": "ad_1"}) == _PREVIEW_ANSWER
        assert len(api.requests) == 2

    async def test_a_final_5xx_never_says_applied(self, api: FakeAPI) -> None:
        api.add("/ads/ad_1/preview", 500, {"error": {"message": "boom"}})
        failure = await fail_tool(_PREVIEW, {"ad_id": "ad_1"})
        assert len(api.requests) == 3
        assert MAY_HAVE_BEEN_APPLIED not in failure.detail

    @pytest.mark.parametrize("arguments", [{}, {"ad_id": "a/b"}, {"ad_id": 7}])
    async def test_a_bad_id_sends_nothing(
        self, api: FakeAPI, arguments: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(_PREVIEW, arguments)
        assert api.requests == []
        assert schema_errors(_BY_NAME[_PREVIEW], arguments) != []


class TestLocationSearch:
    async def test_query_is_sent_as_q_with_the_default_limit(
        self, api: FakeAPI
    ) -> None:
        api.add("/geo_lookup/search", body=_GEO_ANSWER)
        assert await call_tool(_SEARCH, {"query": "calif"}) == _GEO_ANSWER
        assert api.requests[0].method == "GET"
        assert api.params() == [("q", "calif"), ("limit", "20")]

    async def test_the_given_limit_is_sent(self, api: FakeAPI) -> None:
        api.add("/geo_lookup/search", body=_GEO_ANSWER)
        await call_tool(_SEARCH, {"query": "  New York ", "limit": 100})
        assert api.params() == [("q", "  New York "), ("limit", "100")]

    @pytest.mark.parametrize(
        "arguments",
        [
            {},
            {"query": ""},
            {"query": "   "},
            {"query": "x" * 201},
            {"query": 7},
            {"query": "calif", "limit": 0},
            {"query": "calif", "limit": 101},
            {"query": "calif", "limit": True},
        ],
        ids=[
            "no-query",
            "empty",
            "blank",
            "too-long",
            "not-text",
            "limit-zero",
            "limit-over",
            "limit-bool",
        ],
    )
    async def test_bad_arguments_send_nothing(
        self, api: FakeAPI, arguments: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(_SEARCH, arguments)
        assert api.requests == []
        assert schema_errors(_BY_NAME[_SEARCH], arguments) != []
