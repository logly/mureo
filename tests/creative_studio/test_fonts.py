"""Unit tests for the Creative Studio Japanese-font pipeline.

No real network is used: an :class:`httpx.MockTransport` is injected via the
``client_factory`` seam so the download path is exercised deterministically.
``ensure_font`` must never raise — every failure degrades to ``None`` plus a
warning so an offline machine still composes (falling back to system fonts).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest

from mureo.creative_studio import fonts as fonts_mod
from mureo.creative_studio.fonts import (
    FALLBACK_STACK,
    FONT_MANIFEST,
    FontSpec,
    FontWarning,
    ensure_font,
    font_face_css,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# A minimal valid TrueType header (magic 0x00010000) padded past the 10KB floor.
_TTF_MAGIC = b"\x00\x01\x00\x00"
_VALID_TTF = _TTF_MAGIC + b"\x00" * 11_000


def _factory(handler: Callable[[httpx.Request], httpx.Response]):
    transport = httpx.MockTransport(handler)

    def make() -> httpx.Client:
        return httpx.Client(transport=transport)

    return make


def _ok_handler(content: bytes) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content)

    return handler


@pytest.mark.unit
def test_manifest_has_two_faces() -> None:
    names = {spec.name for spec in FONT_MANIFEST}
    assert "Noto Sans JP" in names
    assert "Zen Kaku Gothic New" in names
    for spec in FONT_MANIFEST:
        assert isinstance(spec, FontSpec)
        assert spec.url.startswith("https://")
        assert spec.filename
        assert spec.format


@pytest.mark.unit
def test_ensure_font_returns_existing_without_download(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]
    dest = tmp_path / spec.filename
    dest.write_bytes(_VALID_TTF)

    def exploding() -> httpx.Client:
        raise AssertionError("should not download when the font already exists")

    result = ensure_font(spec, dest_dir=tmp_path, client_factory=exploding)
    assert result == dest


@pytest.mark.unit
def test_ensure_font_downloads_and_records_lockfile(tmp_path: Path) -> None:
    import hashlib

    spec = FONT_MANIFEST[0]
    result = ensure_font(
        spec, dest_dir=tmp_path, client_factory=_factory(_ok_handler(_VALID_TTF))
    )
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == _VALID_TTF

    lock = json.loads((tmp_path / "manifest.lock.json").read_text(encoding="utf-8"))
    entry = lock[spec.filename]
    assert entry["filename"] == spec.filename
    assert entry["source_url"] == spec.url
    assert entry["sha256"] == hashlib.sha256(_VALID_TTF).hexdigest()
    assert entry["fetched_at"]


@pytest.mark.unit
def test_ensure_font_rejects_bad_magic(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]
    garbage = b"NOT-A-FONT" + b"\x00" * 11_000
    with pytest.warns(FontWarning):
        result = ensure_font(
            spec, dest_dir=tmp_path, client_factory=_factory(_ok_handler(garbage))
        )
    assert result is None
    assert not (tmp_path / spec.filename).exists()


@pytest.mark.unit
def test_ensure_font_rejects_too_small(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]
    tiny = _TTF_MAGIC + b"\x00" * 10  # valid magic but well under 10KB
    with pytest.warns(FontWarning):
        result = ensure_font(
            spec, dest_dir=tmp_path, client_factory=_factory(_ok_handler(tiny))
        )
    assert result is None


@pytest.mark.unit
def test_ensure_font_rejects_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = FONT_MANIFEST[0]
    # Shrink the ceiling so the test needn't allocate 40MB.
    monkeypatch.setattr(fonts_mod, "_MAX_FONT_BYTES", 12_000)
    oversized = _TTF_MAGIC + b"\x00" * 20_000
    with pytest.warns(FontWarning):
        result = ensure_font(
            spec, dest_dir=tmp_path, client_factory=_factory(_ok_handler(oversized))
        )
    assert result is None


@pytest.mark.unit
def test_ensure_font_network_failure_returns_none(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]

    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    with pytest.warns(FontWarning):
        result = ensure_font(spec, dest_dir=tmp_path, client_factory=_factory(boom))
    assert result is None


@pytest.mark.unit
def test_ensure_font_http_error_returns_none(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]

    def not_found(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"missing")

    with pytest.warns(FontWarning):
        result = ensure_font(
            spec, dest_dir=tmp_path, client_factory=_factory(not_found)
        )
    assert result is None


@pytest.mark.unit
def test_font_face_css_embeds_data_uri_and_fallback(tmp_path: Path) -> None:
    spec = FONT_MANIFEST[0]
    font_file = tmp_path / spec.filename
    font_file.write_bytes(_VALID_TTF)

    css = font_face_css({spec.name: font_file})
    assert "@font-face" in css
    assert "data:font/ttf;base64," in css
    assert spec.name in css
    assert FALLBACK_STACK in css


@pytest.mark.unit
def test_font_face_css_empty_when_no_fonts() -> None:
    css = font_face_css({})
    # Still surfaces the fallback stack so callers can reference it.
    assert FALLBACK_STACK in css


@pytest.mark.unit
def test_fallback_stack_contents() -> None:
    assert "Noto Sans JP" in FALLBACK_STACK
    assert "sans-serif" in FALLBACK_STACK
