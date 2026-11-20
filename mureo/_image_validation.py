"""Common media file upload validation

File validation logic shared by Meta Ads / Google Ads (supports images and videos),
and the bounded one-open read every local image upload uses (Meta Ads, Google
Ads, ChatGPT Ads), plus the same read for the ChatGPT Ads text file of audience
identifiers.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import BinaryIO

#: Size cap for a local image upload, and its label in error messages.
#: Shared by the Meta Ads and ChatGPT Ads file uploads so one number
#: governs both; neither platform's own limit is the reason for it.
LOCAL_UPLOAD_MAX_IMAGE_BYTES = 30 * 1024 * 1024
LOCAL_UPLOAD_MAX_IMAGE_LABEL = "30MB"

# Reject images whose declared pixel area could exhaust CPU/memory when a
# downstream consumer decodes them (Creative Studio hands validated images
# straight to headless Chromium). 100 megapixels (~10000x10000) sits far above
# any real ad creative — the largest format in this project is 1200x1920
# (~2.3 MP) — yet well below the giant canvases used in decompression-bomb
# attacks (a few KB of compressed data expanding to gigabytes of bitmap).
_MAX_IMAGE_PIXELS = 100_000_000

# Bytes read to sniff a format signature + dimensions. PNG needs 24 (8-byte
# signature + IHDR), WebP needs 30 (RIFF/WEBP header + VP8/VP8L/VP8X dims),
# BMP needs 26 (file header + DIB header size + width/height), GIF needs 10.
_PROBE_BYTES = 32

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")
_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*")

# BITMAPCOREHEADER (OS/2 1.x) carries 16-bit dimensions; every later DIB
# header (BITMAPINFOHEADER and its V4/V5 extensions) is at least 40 bytes
# and carries 32-bit signed ones at the same offset.
_BMP_CORE_HEADER_SIZE = 12
_BMP_INFO_HEADER_MIN_SIZE = 40
# BITMAPV5HEADER, the largest DIB header there is. The two-letter "BM"
# signature also opens ordinary text, so a stream counts as BMP only when
# its DIB header size is one a bitmap can have.
_BMP_MAX_HEADER_SIZE = 124
_BMP_DIB_SIZE_END = 18

# Maps a declared extension to the format its magic bytes must identify as, so
# a mismatch (e.g. a JPEG renamed to .png) can be rejected as extension
# spoofing. Every image extension the uploads accept is listed, so none of
# them escapes the check.
_EXT_TO_FORMAT: dict[str, str] = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "webp": "webp",
    "gif": "gif",
    "bmp": "bmp",
    "tiff": "tiff",
    "tif": "tiff",
}

# Cap the JPEG segment walk so a crafted marker stream cannot spin the loop.
_MAX_JPEG_SEGMENTS = 256


def _validate_media_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
    media_type_label: str,
) -> Path:
    """Validate a media file (shared by images and videos).

    Args:
        file_path: Local file path
        max_size_bytes: Maximum file size in bytes
        max_size_label: Size label for error messages (e.g. "30MB")
        allowed_extensions: Set of allowed extensions (lowercase, no dot)
        media_type_label: Media type label for error messages (e.g. "image", "video")

    Returns:
        Validated Path object.

    Raises:
        ValueError: Path traversal, unsupported format, or size exceeded.
        FileNotFoundError: File does not exist.
    """
    # Prevent path traversal (.. check + resolve() normalization)
    if ".." in file_path:
        raise ValueError(f"Invalid file path: path must not contain '..' : {file_path}")

    path = Path(file_path)

    # File existence check
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Verify it is a regular file after resolving symlinks
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"Invalid file path: not a regular file: {file_path}")

    # Extension check
    ext = path.suffix.lower().lstrip(".")
    if ext not in allowed_extensions:
        allowed_str = ", ".join(sorted(allowed_extensions))
        raise ValueError(
            f"Unsupported {media_type_label} format: .{ext} "
            f"(supported formats: {allowed_str})"
        )

    # File size check
    size = path.stat().st_size
    if size > max_size_bytes:
        raise _size_error(size, max_size_label)

    return path


def _size_error(size: int, max_size_label: str) -> ValueError:
    return ValueError(
        f"File size exceeds the limit: " f"{size:,} bytes (limit: {max_size_label})"
    )


def _png_dimensions(header: bytes) -> tuple[int | None, int | None]:
    """Read ``(width, height)`` from a PNG IHDR, or ``(None, None)``.

    The IHDR chunk immediately follows the 8-byte signature:
    ``[length(4)][b"IHDR"][width(4, big-endian)][height(4, big-endian)]``.
    """
    if len(header) < 24 or header[12:16] != b"IHDR":
        return (None, None)
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width <= 0 or height <= 0:
        return (None, None)
    return (width, height)


def _jpeg_dimensions(fh: BinaryIO) -> tuple[int | None, int | None]:
    """Walk JPEG segments to the first SOF marker and read its dimensions.

    Returns ``(None, None)`` when no frame header is found within the segment
    budget (a truncated or malformed file cannot be a decompression bomb).
    """
    fh.seek(2)  # skip the SOI marker (0xFFD8)
    for _ in range(_MAX_JPEG_SEGMENTS):
        marker = fh.read(2)
        if len(marker) < 2 or marker[0] != 0xFF:
            return (None, None)
        code = marker[1]
        if code == 0xFF:  # fill byte before the real marker; back up one
            fh.seek(-1, 1)
            continue
        if code == 0xD9:  # EOI — no frame header present
            return (None, None)
        if code == 0x01 or 0xD0 <= code <= 0xD7:  # standalone markers, no payload
            continue
        length_bytes = fh.read(2)
        if len(length_bytes) < 2:
            return (None, None)
        seg_len = int.from_bytes(length_bytes, "big")
        if seg_len < 2:
            return (None, None)
        # SOF markers (0xC0-0xCF) carry the frame size, except DHT (0xC4),
        # JPGn (0xC8) and DAC (0xCC) which share the range but are not frames.
        if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
            frame = fh.read(5)  # [precision(1)][height(2)][width(2)]
            if len(frame) < 5:
                return (None, None)
            height = int.from_bytes(frame[1:3], "big")
            width = int.from_bytes(frame[3:5], "big")
            if width <= 0 or height <= 0:
                return (None, None)
            return (width, height)
        fh.seek(seg_len - 2, 1)  # skip this segment's payload
    return (None, None)


def _webp_dimensions(header: bytes) -> tuple[int | None, int | None]:
    """Read ``(width, height)`` from a RIFF/WEBP header, or ``(None, None)``.

    Handles the three WebP bitstreams: lossy (``VP8 ``), lossless (``VP8L``)
    and extended (``VP8X``). The chunk fourcc is at byte 12.
    """
    if len(header) < 30:
        return (None, None)
    fourcc = header[12:16]
    if fourcc == b"VP8X":
        width = 1 + int.from_bytes(header[24:27], "little")
        height = 1 + int.from_bytes(header[27:30], "little")
        return (width, height)
    if fourcc == b"VP8L":
        if header[20] != 0x2F:
            return (None, None)
        bits = int.from_bytes(header[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return (width, height)
    if fourcc == b"VP8 ":
        if header[23:26] != b"\x9d\x01\x2a":
            return (None, None)
        width = int.from_bytes(header[26:28], "little") & 0x3FFF
        height = int.from_bytes(header[28:30], "little") & 0x3FFF
        if width <= 0 or height <= 0:
            return (None, None)
        return (width, height)
    return (None, None)


def _gif_dimensions(header: bytes) -> tuple[int | None, int | None]:
    """Read ``(width, height)`` from a GIF logical screen descriptor.

    Both are little-endian uint16, right after the 6-byte signature.
    """
    if len(header) < 10:
        return (None, None)
    width = int.from_bytes(header[6:8], "little")
    height = int.from_bytes(header[8:10], "little")
    if width <= 0 or height <= 0:
        return (None, None)
    return (width, height)


def _is_bmp(header: bytes) -> bool:
    """``BM`` followed, at offset 14, by a DIB header size a bitmap can have."""
    if header[:2] != b"BM" or len(header) < _BMP_DIB_SIZE_END:
        return False
    dib_size = int.from_bytes(header[14:_BMP_DIB_SIZE_END], "little")
    return _BMP_CORE_HEADER_SIZE <= dib_size <= _BMP_MAX_HEADER_SIZE


def _bmp_dimensions(header: bytes) -> tuple[int | None, int | None]:
    """Read ``(width, height)`` from a BMP DIB header, or ``(None, None)``.

    The DIB header size (uint32 LE at offset 14) says which layout follows.
    A negative height marks a top-down bitmap, so its magnitude is the size.
    """
    if len(header) < 26:
        return (None, None)
    dib_size = int.from_bytes(header[14:18], "little")
    if dib_size == _BMP_CORE_HEADER_SIZE:
        width = int.from_bytes(header[18:20], "little")
        height = int.from_bytes(header[20:22], "little")
    elif dib_size >= _BMP_INFO_HEADER_MIN_SIZE:
        width = int.from_bytes(header[18:22], "little", signed=True)
        height = abs(int.from_bytes(header[22:26], "little", signed=True))
    else:
        return (None, None)
    if width <= 0 or height <= 0:
        return (None, None)
    return (width, height)


def _probe_stream(fh: BinaryIO) -> tuple[str, int | None, int | None] | None:
    """Identify an image stream by magic bytes and read its dimensions.

    PNG, JPEG, WebP, GIF, BMP and TIFF are identified. TIFF dimensions live
    in an IFD this probe does not walk, so they are always ``None``. BigTIFF
    and the OS/2 bitmap-array containers have signatures of their own and
    are not identified.

    Returns ``(format, width, height)`` where ``width``/``height`` may be
    ``None`` when the header is recognised but the dimensions cannot be parsed
    (a truncated or placeholder file). Returns ``None`` when the bytes match no
    known image signature. Std-lib only — this project intentionally has no
    image-library dependency (see pyproject).
    """
    header = fh.read(_PROBE_BYTES)
    if header.startswith(_PNG_SIGNATURE):
        return ("png", *_png_dimensions(header))
    if header[:3] == b"\xff\xd8\xff":
        return ("jpeg", *_jpeg_dimensions(fh))
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ("webp", *_webp_dimensions(header))
    if header[:6] in _GIF_SIGNATURES:
        return ("gif", *_gif_dimensions(header))
    if _is_bmp(header):
        return ("bmp", *_bmp_dimensions(header))
    if header[:4] in _TIFF_SIGNATURES:
        return ("tiff", None, None)
    return None


def _probe_image(path: Path) -> tuple[str, int | None, int | None] | None:
    """:func:`_probe_stream` over the file at ``path``; ``None`` when it
    cannot be read."""
    try:
        with path.open("rb") as fh:
            return _probe_stream(fh)
    except OSError:
        return None


def _spoofing_error(fmt: str, declared: str) -> ValueError:
    return ValueError(
        f"Image content ({fmt}) does not match its .{declared} extension "
        "(possible extension spoofing)"
    )


def _enforce_pixel_cap(width: int | None, height: int | None, max_pixels: int) -> None:
    if width is not None and height is not None and width * height > max_pixels:
        raise ValueError(
            f"Image dimensions {width}x{height} exceed the maximum allowed "
            f"{max_pixels:,} pixels"
        )


def _enforce_image_header(path: Path, *, max_pixels: int) -> None:
    """Reject extension spoofing and oversized (decompression-bomb) images.

    Raises ``ValueError`` when the magic bytes identify a *different* known
    image format than the extension claims, or when the parsed dimensions
    exceed ``max_pixels``. A header that matches no known signature is passed
    through: an undecodable file cannot expand into a giant bitmap, and
    rejecting it would break deliberately-forgiving callers (e.g. the brand-kit
    loader). This is the conservative choice for the "unknown format" case.
    """
    probed = _probe_image(path)
    if probed is None:
        return
    fmt, width, height = probed
    declared = path.suffix.lower().lstrip(".")
    expected = _EXT_TO_FORMAT.get(declared)
    if expected is not None and fmt != expected:
        raise _spoofing_error(fmt, declared)
    _enforce_pixel_cap(width, height, max_pixels)


def read_image_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Return ``(width, height)`` for an image file, else ``(None, None)``.

    Measured for PNG, JPEG, WebP, GIF and BMP. The honest answer for anything
    else: this project has no image-library dependency, so a TIFF, or a
    header these std-lib probes cannot parse, yields ``(None, None)`` rather
    than a guess. Callers that enforce a per-slot dimension rule must treat
    that as "not known", never as "not allowed" — see
    ``mureo.google_ads._asset_groups._validate_image_dimensions``.
    """
    probed = _probe_image(path)
    if probed is None:
        return (None, None)
    _, width, height = probed
    return (width, height)


def image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    """:func:`read_image_dimensions` for image bytes already in memory.

    A caller holding the bytes :func:`read_image_file` checked measures
    those, rather than reopening a file that may have changed since.
    """
    probed = _probe_stream(io.BytesIO(content))
    if probed is None:
        return (None, None)
    _, width, height = probed
    return (width, height)


def validate_image_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
    max_pixels: int = _MAX_IMAGE_PIXELS,
) -> Path:
    """Validate an image file.

    Args:
        file_path: Local image file path
        max_size_bytes: Maximum file size in bytes
        max_size_label: Size label for error messages (e.g. "30MB")
        allowed_extensions: Set of allowed extensions (lowercase, no dot)
        max_pixels: Maximum decoded pixel area (width * height). Guards against
            decompression bombs; defaults to :data:`_MAX_IMAGE_PIXELS`.

    Returns:
        Validated Path object.

    Raises:
        ValueError: Path traversal, unsupported format, size exceeded,
            extension spoofing, or dimensions over ``max_pixels``.
        FileNotFoundError: File does not exist.
    """
    path = _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="image",
    )
    _enforce_image_header(path, max_pixels=max_pixels)
    return path


#: Open flags for :func:`read_image_file` and :func:`read_data_file`:
#: read-only; non-blocking where the platform has it, so a name swapped for a
#: FIFO cannot block the open; and binary where the platform distinguishes it
#: (Windows), so no byte is translated on the way in.
_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)


def _read_regular_file(
    path: Path, file_path: str, max_size_bytes: int, max_size_label: str
) -> bytes:
    """The bytes of the regular file at ``path``, read through one descriptor.

    The type and size are judged on the open descriptor, and the read stops
    one byte past the cap, so a file swapped or grown after the path checks
    is still refused. The type is judged on the raw descriptor, before a
    file object wraps it: ``os.fdopen`` raises on a directory and leaves the
    descriptor it was handed open.
    """
    fd = os.open(path, _READ_FLAGS)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Invalid file path: not a regular file: {file_path}")
        if info.st_size > max_size_bytes:
            raise _size_error(info.st_size, max_size_label)
        with os.fdopen(fd, "rb", closefd=False) as fh:
            content = fh.read(max_size_bytes + 1)
    finally:
        os.close(fd)
    if len(content) > max_size_bytes:
        raise _size_error(len(content), max_size_label)
    return content


def _require_identified(content: bytes, declared: str, max_pixels: int) -> None:
    """``content`` must identify as the format its extension names."""
    expected = _EXT_TO_FORMAT.get(declared)
    probed = _probe_stream(io.BytesIO(content))
    if expected is None or probed is None:
        raise ValueError(
            f"Image content is not a recognisable {expected or declared} image"
        )
    fmt, width, height = probed
    if fmt != expected:
        raise _spoofing_error(fmt, declared)
    _enforce_pixel_cap(width, height, max_pixels)


def read_image_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
    max_pixels: int = _MAX_IMAGE_PIXELS,
) -> tuple[Path, bytes]:
    """Validate an image file and return it with the very bytes that were checked.

    :func:`validate_image_file` checks a path and lets a file it cannot
    identify through, which suits callers that hand the path to a local
    consumer. A caller that sends the file elsewhere needs more: it must send
    what was checked, not whatever the name points at by the time it reads
    it, and it must not send a file it could not identify. This opens the
    file once, judges type and size on that descriptor, and identifies the
    bytes read: the declared extension must be one this module can identify
    and the content must be that format.

    Raises:
        ValueError: Path traversal, unsupported or unidentified format, not a
            regular file, size exceeded, extension spoofing, or dimensions
            over ``max_pixels``. No file content appears in a message.
        FileNotFoundError: File does not exist.
    """
    path = _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="image",
    )
    content = _read_regular_file(path, file_path, max_size_bytes, max_size_label)
    _require_identified(content, path.suffix.lower().lstrip("."), max_pixels)
    return path, content


def read_data_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
) -> tuple[Path, bytes]:
    """Validate a local data file and return it with the very bytes read.

    The read of :func:`read_image_file` without the image check: the same
    path rules, one open, type and size judged on that descriptor, and a read
    that stops one byte past the cap, so what the caller parses is what was
    checked. Used for files whose content is parsed rather than forwarded
    (a list of audience identifiers).

    Raises:
        ValueError: Path traversal, unsupported extension, not a regular
            file, or size exceeded. No file content appears in a message.
        FileNotFoundError: File does not exist.
    """
    path = _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="data",
    )
    return path, _read_regular_file(path, file_path, max_size_bytes, max_size_label)


def validate_video_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
) -> Path:
    """Validate a video file.

    Args:
        file_path: Local video file path
        max_size_bytes: Maximum file size in bytes
        max_size_label: Size label for error messages (e.g. "100MB")
        allowed_extensions: Set of allowed extensions (lowercase, no dot)

    Returns:
        Validated Path object.

    Raises:
        ValueError: Path traversal, unsupported format, or size exceeded.
        FileNotFoundError: File does not exist.
    """
    return _validate_media_file(
        file_path,
        max_size_bytes=max_size_bytes,
        max_size_label=max_size_label,
        allowed_extensions=allowed_extensions,
        media_type_label="video",
    )
