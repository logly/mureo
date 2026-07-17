"""Regression tests for image header validation (M9).

``validate_image_file`` decodes only the format header (std-lib only — this
project intentionally has no image-library dependency) to reject two classes
of hostile input before a downstream consumer (headless Chromium) decodes the
file:

* extension spoofing — magic bytes identifying a different known image format
  than the extension claims;
* decompression bombs — a tiny file declaring enormous pixel dimensions.

An unrecognised header is passed through (an undecodable file cannot expand
into a giant bitmap), preserving the behaviour forgiving callers rely on.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from mureo._image_validation import validate_image_file

if TYPE_CHECKING:
    from pathlib import Path

_IMG_EXTS = frozenset({"png", "jpg", "jpeg", "webp"})


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height)
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"\x08\x06\x00\x00\x00" + b"\x00" * 4


def _jpeg(width: int, height: int) -> bytes:
    # SOI + a SOF0 frame header carrying the dimensions.
    sof = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + sof


def _webp_vp8x(width: int, height: int) -> bytes:
    chunk = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return b"RIFF" + struct.pack("<I", len(chunk) + 4) + b"WEBP" + chunk


def _validate(path: Path, *, max_pixels: int = 100_000_000) -> Path:
    return validate_image_file(
        str(path),
        max_size_bytes=30 * 1024 * 1024,
        max_size_label="30MB",
        allowed_extensions=_IMG_EXTS,
        max_pixels=max_pixels,
    )


# --- extension spoofing --------------------------------------------------


@pytest.mark.unit
def test_jpeg_bytes_with_png_extension_rejected(tmp_path: Path) -> None:
    spoof = tmp_path / "fake.png"
    spoof.write_bytes(_jpeg(100, 100))
    with pytest.raises(ValueError, match="spoofing"):
        _validate(spoof)


@pytest.mark.unit
def test_png_bytes_with_jpg_extension_rejected(tmp_path: Path) -> None:
    spoof = tmp_path / "fake.jpg"
    spoof.write_bytes(_png(100, 100))
    with pytest.raises(ValueError, match="spoofing"):
        _validate(spoof)


# --- decompression-bomb dimension cap ------------------------------------


@pytest.mark.unit
def test_oversized_png_dimensions_rejected(tmp_path: Path) -> None:
    """A tiny file declaring 20000x20000 (400 MP) is rejected."""
    bomb = tmp_path / "bomb.png"
    bomb.write_bytes(_png(20000, 20000))
    assert bomb.stat().st_size < 1024  # tiny on disk, huge when decoded
    with pytest.raises(ValueError, match="exceed"):
        _validate(bomb)


@pytest.mark.unit
def test_oversized_jpeg_dimensions_rejected(tmp_path: Path) -> None:
    bomb = tmp_path / "bomb.jpg"
    bomb.write_bytes(_jpeg(12000, 12000))
    with pytest.raises(ValueError, match="exceed"):
        _validate(bomb)


@pytest.mark.unit
def test_oversized_webp_dimensions_rejected(tmp_path: Path) -> None:
    bomb = tmp_path / "bomb.webp"
    bomb.write_bytes(_webp_vp8x(15000, 15000))
    with pytest.raises(ValueError, match="exceed"):
        _validate(bomb)


@pytest.mark.unit
def test_custom_low_pixel_cap_enforced(tmp_path: Path) -> None:
    """A modest image is rejected under a deliberately low cap."""
    img = tmp_path / "ok.png"
    img.write_bytes(_png(1000, 1000))
    with pytest.raises(ValueError, match="exceed"):
        _validate(img, max_pixels=100)


# --- valid / benign inputs pass ------------------------------------------


@pytest.mark.unit
def test_valid_small_png_accepted(tmp_path: Path) -> None:
    img = tmp_path / "logo.png"
    img.write_bytes(_png(1080, 1080))
    assert _validate(img) == img


@pytest.mark.unit
def test_valid_small_jpeg_accepted(tmp_path: Path) -> None:
    img = tmp_path / "photo.jpg"
    img.write_bytes(_jpeg(800, 600))
    assert _validate(img) == img


@pytest.mark.unit
def test_valid_webp_accepted(tmp_path: Path) -> None:
    img = tmp_path / "banner.webp"
    img.write_bytes(_webp_vp8x(1200, 628))
    assert _validate(img) == img


@pytest.mark.unit
def test_unrecognised_header_passes_through(tmp_path: Path) -> None:
    """A placeholder file with no known signature is not rejected (forgiving)."""
    img = tmp_path / "placeholder.png"
    img.write_bytes(b"\x00" * 100)
    assert _validate(img) == img


@pytest.mark.unit
def test_truncated_png_signature_passes_through(tmp_path: Path) -> None:
    """PNG-prefixed but signature-incomplete bytes are treated as unknown."""
    img = tmp_path / "raw.png"
    img.write_bytes(b"\x89PNG raw visual")  # not the full 8-byte signature
    assert _validate(img) == img
