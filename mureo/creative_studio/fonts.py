"""Japanese-font resolution for the Creative Studio composer.

Headless-Chromium rendering needs the display font **available locally at
render time** to guarantee crisp Japanese glyphs without a live network
round-trip. This module keeps a small, fixed manifest of two faces (Noto
Sans JP for body/most copy, Zen Kaku Gothic New Bold as a display face),
downloads them once into ``~/.mureo/fonts`` on first use, verifies them, and
records a lockfile of checksums.

Robustness is the contract: a font download that fails for ANY reason
(offline, bad bytes, wrong size) returns ``None`` with a warning so the
composer falls back to the system font stack — a network hiccup must never
block composition. Download URLs are fixed manifest constants (never
caller-supplied), so there is no SSRF surface.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0
_LOCKFILE = "manifest.lock.json"
_FILE_MODE = 0o644

# Font byte-size sanity bounds. Below the floor is almost certainly an error
# page; above the ceiling is not a web font we would ship.
_MIN_FONT_BYTES = 10 * 1024
_MAX_FONT_BYTES = 40 * 1024 * 1024

# Accepted sfnt/WOFF2 magic numbers: TrueType (0x00010000), OpenType ('OTTO'),
# and WOFF2 ('wOF2').
_FONT_MAGIC: tuple[bytes, ...] = (b"\x00\x01\x00\x00", b"OTTO", b"wOF2")

#: System-font fallback chain used when an embedded face is unavailable.
FALLBACK_STACK = (
    "'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', Meiryo, sans-serif"
)


class FontSpec(NamedTuple):
    """One downloadable font face.

    Attributes:
        name: CSS ``font-family`` name (e.g. ``"Noto Sans JP"``).
        filename: Local filename under the fonts directory.
        url: Fixed https download URL (never caller-supplied).
        format: CSS ``@font-face`` ``format()`` hint (e.g. ``"truetype"``).
    """

    name: str
    filename: str
    url: str
    format: str


#: The two faces the composer relies on. Both are variable/bold TrueType files
#: served from the official Google Fonts GitHub mirror.
FONT_MANIFEST: tuple[FontSpec, ...] = (
    FontSpec(
        name="Noto Sans JP",
        filename="NotoSansJP-wght.ttf",
        url=(
            "https://github.com/google/fonts/raw/main/ofl/notosansjp/"
            "NotoSansJP%5Bwght%5D.ttf"
        ),
        format="truetype",
    ),
    FontSpec(
        name="Zen Kaku Gothic New",
        filename="ZenKakuGothicNew-Bold.ttf",
        url=(
            "https://github.com/google/fonts/raw/main/ofl/zenkakugothicnew/"
            "ZenKakuGothicNew-Bold.ttf"
        ),
        format="truetype",
    ),
)

#: Fast name -> spec lookup for :func:`font_face_css`.
_SPEC_BY_NAME: dict[str, FontSpec] = {spec.name: spec for spec in FONT_MANIFEST}


def _default_client_factory() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)


def _warn(message: str) -> None:
    warnings.warn(message, FontWarning, stacklevel=3)


class FontWarning(UserWarning):
    """Emitted when a font cannot be resolved and the composer must fall back.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=FontWarning)``.
    """


def _has_font_magic(data: bytes) -> bool:
    return data[:4] in _FONT_MAGIC


def _record_lock(dest_dir: Path, spec: FontSpec, data: bytes) -> None:
    """Best-effort append of a checksum entry to ``manifest.lock.json``.

    Never raises: a lockfile write failure must not discard a font that was
    downloaded and validated successfully.
    """
    try:
        lock_path = dest_dir / _LOCKFILE
        existing: dict[str, object] = {}
        if lock_path.is_file():
            loaded = json.loads(lock_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        existing[spec.filename] = {
            "filename": spec.filename,
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_url": spec.url,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        lock_path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.chmod(lock_path, _FILE_MODE)
    except Exception:  # noqa: BLE001 — lockfile bookkeeping is best-effort
        logger.debug("font lockfile update failed", exc_info=True)


def ensure_font(
    spec: FontSpec,
    dest_dir: Path | None = None,
    *,
    client_factory: Callable[[], httpx.Client] | None = None,
) -> Path | None:
    """Return a local path to ``spec``'s font, downloading it once if needed.

    Returns the existing file without any network call when it is already
    present. Otherwise downloads from the fixed manifest URL, verifies the
    magic bytes and size, writes it ``0o644``, and records a checksum in
    ``manifest.lock.json``. On ANY failure returns ``None`` with a
    :class:`FontWarning` so the caller falls back to system fonts.

    Args:
        spec: The font to ensure.
        dest_dir: Directory to cache into (default ``~/.mureo/fonts``).
        client_factory: Injectable ``httpx.Client`` factory (tests / advanced).
    """
    try:
        base = (
            Path(dest_dir) if dest_dir is not None else Path.home() / ".mureo" / "fonts"
        )
        dest = base / spec.filename
        if dest.is_file() and dest.stat().st_size > 0:
            return dest

        if not spec.url.startswith("https://"):
            _warn(f"font {spec.name!r}: refusing non-https url; skipped")
            return None

        factory = client_factory or _default_client_factory
        with factory() as client:
            response = client.get(spec.url, follow_redirects=True)
            response.raise_for_status()
            data = response.content

        if not _has_font_magic(data):
            _warn(f"font {spec.name!r}: download failed magic-byte check; skipped")
            return None
        if not (_MIN_FONT_BYTES <= len(data) <= _MAX_FONT_BYTES):
            _warn(
                f"font {spec.name!r}: download size {len(data)} bytes out of "
                f"bounds [{_MIN_FONT_BYTES}, {_MAX_FONT_BYTES}]; skipped"
            )
            return None

        base.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        os.chmod(dest, _FILE_MODE)
        _record_lock(base, spec, data)
        return dest
    except Exception as exc:  # noqa: BLE001 — never block composition on fonts
        _warn(f"font {spec.name!r}: could not be resolved ({exc}); skipped")
        return None


def font_face_css(available: dict[str, Path]) -> str:
    """Return ``@font-face`` CSS embedding each available font as a data URI.

    Base64 data-URI embedding lets Playwright's ``set_content`` render with
    no file server. The returned CSS always ends with a ``:root`` custom
    property carrying :data:`FALLBACK_STACK` so templates can reference the
    same system fallback chain.

    Args:
        available: Mapping of font-family name to a local font file path.
    """
    blocks: list[str] = []
    for name, path in available.items():
        try:
            encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:  # noqa: PERF203 — skip an unreadable face, keep the rest
            _warn(f"font {name!r}: could not read {path} for embedding; skipped")
            continue
        spec = _SPEC_BY_NAME.get(name)
        fmt = spec.format if spec is not None else "truetype"
        blocks.append(
            "@font-face {\n"
            f"  font-family: '{name}';\n"
            f"  src: url(data:font/ttf;base64,{encoded}) format('{fmt}');\n"
            "  font-weight: 100 900;\n"
            "  font-display: swap;\n"
            "}"
        )
    blocks.append(f":root {{ --mureo-font-fallback: {FALLBACK_STACK}; }}")
    return "\n".join(blocks)


__all__ = [
    "FALLBACK_STACK",
    "FONT_MANIFEST",
    "FontSpec",
    "FontWarning",
    "ensure_font",
    "font_face_css",
]
