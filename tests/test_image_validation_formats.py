"""GIF, BMP and TIFF identification, and dimensions from bytes in memory (#1011).

Every extension the Meta Ads and Google Ads uploads accept is identified by
its signature, so the extension-spoofing check and the "content must be the
declared image type" rule of ``read_image_file`` cover all of them, and the
pixel cap reaches the formats whose header carries dimensions (GIF, BMP).
TIFF keeps its dimensions in an IFD the std-lib probe does not walk, so they
are reported as not known rather than guessed.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from mureo._image_validation import (
    image_dimensions,
    read_image_dimensions,
    read_image_file,
    validate_image_file,
)
from tests.test_image_validation_dimensions import _jpeg, _png

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_ALL_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "tif"})


def _gif(width: int, height: int, version: bytes = b"89a") -> bytes:
    """A GIF logical screen descriptor followed by the trailer."""
    return b"GIF" + version + struct.pack("<HH", width, height) + b"\x00\x00\x00;"


def _bmp(width: int, height: int, dib_size: int = 40) -> bytes:
    """A BMP file header plus a DIB header of ``dib_size`` bytes."""
    if dib_size == 12:
        dib = struct.pack("<IHHHH", 12, width, height, 1, 24)
    else:
        dib = struct.pack("<Iii", dib_size, width, height) + b"\x00" * (dib_size - 12)
    return b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 14 + len(dib)) + dib


def _tiff(big_endian: bool = False) -> bytes:
    """A TIFF header pointing at an empty IFD."""
    if big_endian:
        return b"MM\x00*" + struct.pack(">IH", 8, 0) + b"\x00" * 4
    return b"II*\x00" + struct.pack("<IH", 8, 0) + b"\x00" * 4


def _validate(path: Path, *, max_pixels: int = 100_000_000) -> Path:
    return validate_image_file(
        str(path),
        max_size_bytes=30 * 1024 * 1024,
        max_size_label="30MB",
        allowed_extensions=_ALL_EXTS,
        max_pixels=max_pixels,
    )


def _read(path: Path, *, max_pixels: int = 100_000_000) -> tuple[Path, bytes]:
    return read_image_file(
        str(path),
        max_size_bytes=30 * 1024 * 1024,
        max_size_label="30MB",
        allowed_extensions=_ALL_EXTS,
        max_pixels=max_pixels,
    )


@pytest.mark.parametrize(
    "name,payload",
    [
        ("anim.gif", _gif(10, 10)),
        ("old.gif", _gif(10, 10, b"87a")),
        ("scan.bmp", _bmp(10, 10)),
        ("os2.bmp", _bmp(10, 10, dib_size=12)),
        ("photo.tiff", _tiff()),
        ("photo.tif", _tiff(big_endian=True)),
    ],
)
def test_gif_bmp_and_tiff_are_identified(
    tmp_path: Path, name: str, payload: bytes
) -> None:
    img = tmp_path / name
    img.write_bytes(payload)
    assert _read(img)[1] == payload


@pytest.mark.parametrize(
    "payload,expected",
    [
        (_gif(1200, 628), (1200, 628)),
        (_bmp(640, 480), (640, 480)),
        (_bmp(640, -480), (640, 480)),
        (_bmp(320, 200, dib_size=12), (320, 200)),
        (_bmp(640, 480, dib_size=124), (640, 480)),
        (_tiff(), (None, None)),
        (_tiff(big_endian=True), (None, None)),
        (_gif(0, 10), (None, None)),
        (_bmp(0, 10), (None, None)),
        (_bmp(10, 10, dib_size=16), (None, None)),
        (b"\x00" * 64, (None, None)),
        (b"not an image at all", (None, None)),
        (b"", (None, None)),
    ],
)
def test_image_dimensions_reads_the_header(
    payload: bytes, expected: tuple[int | None, int | None]
) -> None:
    """A negative BMP height means a top-down bitmap, not a negative size;
    an unknown DIB header, a non-positive size or an unknown signature is
    "not known"."""
    assert image_dimensions(payload) == expected


@pytest.mark.parametrize(
    "name,payload",
    [
        ("hero.png", _png(1200, 628)),
        ("hero.jpg", _jpeg(600, 314)),
        ("hero.gif", _gif(960, 1200)),
        ("hero.bmp", _bmp(300, -250)),
        ("hero.tiff", _tiff()),
        ("hero.png", b"\x00" * 64),
    ],
)
def test_image_dimensions_agrees_with_the_file_probe(
    tmp_path: Path, name: str, payload: bytes
) -> None:
    img = tmp_path / name
    img.write_bytes(payload)
    assert image_dimensions(payload) == read_image_dimensions(img)


@pytest.mark.parametrize(
    "name,payload",
    [
        ("fake.gif", _png(10, 10)),
        ("fake.bmp", _png(10, 10)),
        ("fake.tiff", _jpeg(10, 10)),
        ("fake.tif", _gif(10, 10)),
        ("fake.png", _gif(10, 10)),
        ("fake.jpg", _bmp(10, 10)),
    ],
)
def test_a_contradicting_extension_is_refused(
    tmp_path: Path, name: str, payload: bytes
) -> None:
    """Both checks, the forgiving path check and the read that is sent."""
    img = tmp_path / name
    img.write_bytes(payload)
    with pytest.raises(ValueError, match="possible extension spoofing"):
        _validate(img)
    with pytest.raises(ValueError, match="possible extension spoofing"):
        _read(img)


@pytest.mark.parametrize(
    "name,payload",
    [("bomb.gif", _gif(20_000, 20_000)), ("bomb.bmp", _bmp(20_000, -20_000))],
)
def test_the_pixel_cap_applies_to_gif_and_bmp(
    tmp_path: Path, name: str, payload: bytes
) -> None:
    img = tmp_path / name
    img.write_bytes(payload)
    assert img.stat().st_size < 1024
    with pytest.raises(ValueError, match="exceed the maximum allowed"):
        _validate(img)
    with pytest.raises(ValueError, match="exceed the maximum allowed"):
        _read(img)


@pytest.mark.parametrize(
    "payload",
    [
        b"BM" + b"x" * 36,
        b"BMW dealers, by region\n" + b"-" * 40,
        # A DIB header size no bitmap has.
        b"BM" + struct.pack("<IHHI", 54, 0, 0, 54) + struct.pack("<I", 4000),
        # Too short to carry a DIB header size at all.
        b"BM\x00\x00",
    ],
)
def test_text_that_opens_with_the_bmp_signature_is_not_a_bitmap(
    tmp_path: Path, payload: bytes
) -> None:
    """The two-letter signature alone identifies nothing and measures nothing."""
    assert image_dimensions(payload) == (None, None)
    img = tmp_path / "list.bmp"
    img.write_bytes(payload)
    with pytest.raises(ValueError, match="not a recognisable bmp image"):
        _read(img)
    renamed = tmp_path / "list.png"
    renamed.write_bytes(payload)
    assert _validate(renamed) == renamed


def test_a_tiff_is_not_refused_on_dimensions_it_cannot_read(tmp_path: Path) -> None:
    img = tmp_path / "scan.tiff"
    img.write_bytes(_tiff())
    assert _read(img, max_pixels=1)[1] == _tiff()
