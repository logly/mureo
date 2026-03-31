"""Common media file upload validation

File validation logic shared by Meta Ads / Google Ads (supports images and videos).
"""

from __future__ import annotations

from pathlib import Path


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


def validate_image_file(
    file_path: str,
    *,
    max_size_bytes: int,
    max_size_label: str,
    allowed_extensions: frozenset[str],
) -> Path:
    """Validate an image file.

    Args:
        file_path: Local image file path
        max_size_bytes: Maximum file size in bytes
        max_size_label: Size label for error messages (e.g. "30MB")
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
        media_type_label="image",
    )


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
