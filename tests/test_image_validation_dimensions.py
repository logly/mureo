"""Regression tests for image header validation.

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

import os
import struct
from typing import TYPE_CHECKING

import pytest

from mureo import _image_validation
from mureo._image_validation import read_image_file, validate_image_file

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


# ---------------------------------------------------------------------------
# read_image_dimensions (#626)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,payload,expected",
    [
        ("hero.png", _png(1200, 628), (1200, 628)),
        ("hero.jpg", _jpeg(600, 314), (600, 314)),
        ("hero.webp", _webp_vp8x(960, 1200), (960, 1200)),
    ],
)
def test_read_image_dimensions_measures_what_it_can(
    tmp_path: Path, name: str, payload: bytes, expected: tuple[int, int]
) -> None:
    """The P-MAX image swap refuses a wrongly shaped file before uploading
    it, which it can only do for the formats these probes cover."""
    from mureo._image_validation import read_image_dimensions

    img = tmp_path / name
    img.write_bytes(payload)
    assert read_image_dimensions(img) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,payload",
    [
        ("zero-size.gif", b"GIF89a" + b"\x00" * 32),
        ("placeholder.png", b"\x00" * 100),
        ("missing.png", None),
    ],
)
def test_read_image_dimensions_says_unknown_rather_than_guessing(
    tmp_path: Path, name: str, payload: bytes | None
) -> None:
    """``(None, None)`` is the honest answer for a header declaring no usable
    size, or content with no std-lib probe here. A caller enforcing a
    per-slot shape must read that as "not known", never as "not allowed" —
    mureo does not guess and does not resize."""
    from mureo._image_validation import read_image_dimensions

    img = tmp_path / name
    if payload is not None:
        img.write_bytes(payload)
    assert read_image_dimensions(img) == (None, None)


# --- read_image_file: the bytes that were checked, identified ------------


def _read(
    path: Path,
    *,
    max_size_bytes: int = 30 * 1024 * 1024,
    max_pixels: int = 100_000_000,
    allowed: frozenset[str] = _IMG_EXTS,
) -> tuple[Path, bytes]:
    return read_image_file(
        str(path),
        max_size_bytes=max_size_bytes,
        max_size_label="the cap",
        allowed_extensions=allowed,
        max_pixels=max_pixels,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "name,payload",
    [
        ("hero.png", _png(1200, 628)),
        ("hero.jpg", _jpeg(600, 314)),
        ("hero.jpeg", _jpeg(600, 314)),
        ("hero.webp", _webp_vp8x(960, 1200)),
    ],
)
def test_read_image_file_returns_the_checked_bytes(
    tmp_path: Path, name: str, payload: bytes
) -> None:
    img = tmp_path / name
    img.write_bytes(payload)
    path, content = _read(img)
    assert path == img
    assert content == payload


@pytest.mark.unit
@pytest.mark.parametrize("name", ["notes.png", "notes.jpg", "notes.webp"])
def test_read_image_file_refuses_content_it_cannot_identify(
    tmp_path: Path, name: str
) -> None:
    """Unlike ``validate_image_file``, an unidentified file is refused: the
    caller sends these bytes elsewhere and must not send a non-image."""
    secret = "not an image, and not to be quoted"
    img = tmp_path / name
    img.write_text(secret, encoding="utf-8")
    with pytest.raises(ValueError, match="not a recognisable") as excinfo:
        _read(img)
    assert secret not in str(excinfo.value)


@pytest.mark.unit
def test_read_image_file_refuses_an_extension_it_cannot_identify(
    tmp_path: Path,
) -> None:
    img = tmp_path / "favicon.ico"
    img.write_bytes(b"\x00\x00\x01\x00" + b"\x00" * 32)
    with pytest.raises(ValueError, match="not a recognisable"):
        _read(img, allowed=frozenset({"ico"}))


@pytest.mark.unit
def test_read_image_file_keeps_the_spoofing_error(tmp_path: Path) -> None:
    img = tmp_path / "fake.png"
    img.write_bytes(_jpeg(100, 100))
    with pytest.raises(ValueError, match="possible extension spoofing"):
        _read(img)


@pytest.mark.unit
def test_read_image_file_keeps_the_pixel_cap(tmp_path: Path) -> None:
    img = tmp_path / "bomb.png"
    img.write_bytes(_png(20_000, 20_000))
    with pytest.raises(ValueError, match="exceed the maximum allowed"):
        _read(img)


@pytest.mark.unit
def test_read_image_file_size_cap_is_inclusive(tmp_path: Path) -> None:
    payload = _png(10, 10)
    img = tmp_path / "small.png"
    img.write_bytes(payload)
    assert _read(img, max_size_bytes=len(payload))[1] == payload
    with pytest.raises(ValueError, match="File size exceeds the limit"):
        _read(img, max_size_bytes=len(payload) - 1)


@pytest.mark.unit
def test_read_image_file_caps_what_it_reads_not_what_stat_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that grows after it was measured is still refused: the read
    itself stops one byte past the cap."""
    payload = _png(10, 10) + b"\x00" * 100
    img = tmp_path / "growing.png"
    img.write_bytes(payload)
    real_fstat = os.fstat

    def small_fstat(fd: int) -> os.stat_result:
        st = real_fstat(fd)
        fields = list(st)
        fields[6] = 1  # st_size
        return os.stat_result(fields)

    real_stat = _image_validation.Path.stat

    def small_stat(self: Path, **kwargs: object) -> os.stat_result:
        st = real_stat(self, **kwargs)  # type: ignore[arg-type]
        fields = list(st)
        fields[6] = 1
        return os.stat_result(fields)

    monkeypatch.setattr(_image_validation.os, "fstat", small_fstat)
    monkeypatch.setattr(_image_validation.Path, "stat", small_stat)
    with pytest.raises(ValueError, match="File size exceeds the limit"):
        _read(img, max_size_bytes=50)


@pytest.mark.unit
def test_read_image_file_follows_a_link_only_to_an_image(tmp_path: Path) -> None:
    real = tmp_path / "real.png"
    real.write_bytes(_png(10, 10))
    text = tmp_path / "notes.txt"
    text.write_text("plain text", encoding="utf-8")
    to_image = tmp_path / "to_image.png"
    to_text = tmp_path / "to_text.png"
    try:
        to_image.symlink_to(real)
        to_text.symlink_to(text)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    assert _read(to_image)[1] == real.read_bytes()
    with pytest.raises(ValueError, match="not a recognisable"):
        _read(to_text)


@pytest.mark.unit
def test_read_image_file_refuses_a_directory(tmp_path: Path) -> None:
    folder = tmp_path / "folder.png"
    folder.mkdir()
    with pytest.raises(ValueError, match="not a regular file"):
        _read(folder)


@pytest.mark.unit
def test_read_image_file_refuses_a_fifo(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")
    fifo = tmp_path / "pipe.png"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="not a regular file"):
        _read(fifo)


@pytest.mark.unit
def test_read_image_file_checks_the_open_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The type is judged on what was opened, not on the earlier path check:
    a name swapped for a FIFO after that check is refused without blocking."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("os.mkfifo is not available on this platform")
    real = tmp_path / "real.png"
    real.write_bytes(_png(10, 10))
    fifo = tmp_path / "pipe.png"
    os.mkfifo(fifo)
    real_open = os.open

    def swapped_open(path: object, flags: int, *args: object) -> int:
        return real_open(fifo if str(path).endswith("real.png") else path, flags)

    monkeypatch.setattr(_image_validation.os, "open", swapped_open)
    with pytest.raises(ValueError, match="not a regular file"):
        _read(real)


@pytest.mark.unit
def test_read_image_file_keeps_the_path_rules(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _read(tmp_path / "missing.png")
    with pytest.raises(ValueError, match="must not contain"):
        _read(tmp_path / ".." / "x.png")
    other = tmp_path / "x.bmp"
    other.write_bytes(b"BM")
    with pytest.raises(ValueError, match="Unsupported image format"):
        _read(other)
