"""Common media file upload validation

File validation logic shared by Meta Ads / Google Ads (supports images and videos).
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

# Reject images whose declared pixel area could exhaust CPU/memory when a
# downstream consumer decodes them (Creative Studio hands validated images
# straight to headless Chromium). 100 megapixels (~10000x10000) sits far above
# any real ad creative — the largest format in this project is 1200x1920
# (~2.3 MP) — yet well below the giant canvases used in decompression-bomb
# attacks (a few KB of compressed data expanding to gigabytes of bitmap).
_MAX_IMAGE_PIXELS = 100_000_000

# Bytes read to sniff a format signature + dimensions. PNG needs 24 (8-byte
# signature + IHDR), WebP needs 30 (RIFF/WEBP header + VP8/VP8L/VP8X dims).
_PROBE_BYTES = 32

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Maps a declared extension to the format its magic bytes must identify as, so
# a mismatch (e.g. a JPEG renamed to .png) can be rejected as extension
# spoofing. Only the formats this module can positively identify are listed;
# other allowed extensions (gif/bmp/tiff) are not sniffed and are left alone.
_EXT_TO_FORMAT: dict[str, str] = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "webp": "webp",
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
        raise ValueError(
            f"File size exceeds the limit: " f"{size:,} bytes (limit: {max_size_label})"
        )

    return path


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


def _probe_image(path: Path) -> tuple[str, int | None, int | None] | None:
    """Identify a PNG/JPEG/WebP file by magic bytes and read its dimensions.

    Returns ``(format, width, height)`` where ``width``/``height`` may be
    ``None`` when the header is recognised but the dimensions cannot be parsed
    (a truncated or placeholder file). Returns ``None`` when the bytes match no
    known image signature. Std-lib only — this project intentionally has no
    image-library dependency (see pyproject).
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(_PROBE_BYTES)
            if header.startswith(_PNG_SIGNATURE):
                return ("png", *_png_dimensions(header))
            if header[:3] == b"\xff\xd8\xff":
                return ("jpeg", *_jpeg_dimensions(fh))
            if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                return ("webp", *_webp_dimensions(header))
    except OSError:
        return None
    return None


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
        raise ValueError(
            f"Image content ({fmt}) does not match its .{declared} extension "
            "(possible extension spoofing)"
        )
    if width is not None and height is not None and width * height > max_pixels:
        raise ValueError(
            f"Image dimensions {width}x{height} exceed the maximum allowed "
            f"{max_pixels:,} pixels"
        )


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
