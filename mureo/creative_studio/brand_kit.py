"""Brand-kit loading for Creative Studio.

A brand kit gives the composer the colours, fonts, and logo that make a
generated banner look like it belongs to a specific brand rather than a
generic template. It is read from ``<cwd or base>/BRAND_KIT/kit.yml``.

The loader is deliberately forgiving: **quality of output must not depend on
config hygiene**, so a missing, malformed, or partially-invalid kit NEVER
raises. Every field degrades to a tasteful default independently (a bad hex
colour falls back only for that colour, an unreadable logo is treated as
absent) and a :class:`BrandKitWarning` is emitted instead of an exception.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mureo._image_validation import validate_image_file

#: ``#rgb`` or ``#rrggbb`` (case-insensitive).
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: Colour roles a kit may define. Unknown keys are ignored.
_COLOR_KEYS: tuple[str, ...] = ("primary", "secondary", "accent", "text", "background")
#: Font roles a kit may define.
_FONT_KEYS: tuple[str, ...] = ("heading", "body")

# Logo validation bounds (mirrors the platform upload validators).
_LOGO_MAX_BYTES = 10 * 1024 * 1024
_LOGO_MAX_LABEL = "10MB"
_LOGO_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "webp"})

_DEFAULT_LOGO_CLEAR_PX = 24

# Tasteful neutral defaults: near-black primary, muted grey secondary, indigo
# accent, near-black text on white, with Noto Sans JP for crisp Japanese text.
_DEFAULT_COLORS: dict[str, str] = {
    "primary": "#1a1d29",
    "secondary": "#6b7280",
    "accent": "#4f46e5",
    "text": "#111827",
    "background": "#ffffff",
}
_DEFAULT_FONTS: dict[str, str] = {
    "heading": "Noto Sans JP",
    "body": "Noto Sans JP",
}


class BrandKitWarning(UserWarning):
    """Emitted when a brand kit is malformed and a field degrades to default.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=BrandKitWarning)``.
    """


@dataclass(frozen=True)
class BrandKit:
    """A resolved brand kit.

    Attributes:
        colors: Role -> hex string (``primary`` / ``secondary`` / ``accent`` /
            ``text`` / ``background``); always fully populated.
        fonts: Role -> font-family name (``heading`` / ``body``).
        logo_path: Absolute path to a validated logo image, or ``None``.
        logo_min_clear_px: Minimum clear-space padding around the logo, in px.
    """

    colors: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_COLORS))
    fonts: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_FONTS))
    logo_path: Path | None = None
    logo_min_clear_px: int = _DEFAULT_LOGO_CLEAR_PX


#: The kit used when no ``kit.yml`` exists or it cannot be parsed at all.
DEFAULT_BRAND_KIT = BrandKit(
    colors=dict(_DEFAULT_COLORS),
    fonts=dict(_DEFAULT_FONTS),
    logo_path=None,
    logo_min_clear_px=_DEFAULT_LOGO_CLEAR_PX,
)


def _warn(message: str) -> None:
    warnings.warn(message, BrandKitWarning, stacklevel=3)


def _resolve_colors(raw: Any) -> dict[str, str]:
    """Merge a raw ``colors`` mapping onto the defaults, per-field validated."""
    colors = dict(_DEFAULT_COLORS)
    if not isinstance(raw, dict):
        if raw is not None:
            _warn("brand kit 'colors' is not a mapping; using default colours")
        return colors
    for key in _COLOR_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, str) and _HEX_RE.match(value.strip()):
            colors[key] = value.strip()
        else:
            _warn(
                f"brand kit colour {key!r} is not a valid hex value "
                f"({value!r}); keeping the default {colors[key]}"
            )
    return colors


def _resolve_fonts(raw: Any) -> dict[str, str]:
    """Merge a raw ``fonts`` mapping onto the defaults, per-field validated."""
    fonts = dict(_DEFAULT_FONTS)
    if not isinstance(raw, dict):
        if raw is not None:
            _warn("brand kit 'fonts' is not a mapping; using default fonts")
        return fonts
    for key in _FONT_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(value, str) and value.strip():
            fonts[key] = value.strip()
        else:
            _warn(
                f"brand kit font {key!r} is not a non-empty string "
                f"({value!r}); keeping the default {fonts[key]!r}"
            )
    return fonts


def _resolve_logo(raw: Any, kit_dir: Path) -> Path | None:
    """Resolve + validate the logo path relative to the BRAND_KIT dir.

    Returns ``None`` (with a warning) for anything that is not a valid,
    supported, in-bounds image file.
    """
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        _warn(f"brand kit 'logo' is not a path string ({raw!r}); ignoring")
        return None
    candidate = kit_dir / raw.strip()
    try:
        validated = validate_image_file(
            str(candidate),
            max_size_bytes=_LOGO_MAX_BYTES,
            max_size_label=_LOGO_MAX_LABEL,
            allowed_extensions=_LOGO_EXTENSIONS,
        )
    except (ValueError, FileNotFoundError, OSError) as exc:
        _warn(f"brand kit logo {raw!r} is unusable ({exc}); treating as absent")
        return None
    return validated.resolve()


def _resolve_clear_px(raw: Any) -> int:
    """Resolve ``logo_min_clear_px``; degrade to the default when invalid."""
    if raw is None:
        return _DEFAULT_LOGO_CLEAR_PX
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        _warn(
            f"brand kit 'logo_min_clear_px' must be a non-negative integer "
            f"({raw!r}); using {_DEFAULT_LOGO_CLEAR_PX}"
        )
        return _DEFAULT_LOGO_CLEAR_PX
    return int(raw)


def load_brand_kit(base: Path | None = None) -> BrandKit:
    """Load the brand kit from ``<base or cwd>/BRAND_KIT/kit.yml``.

    Never raises. A missing file returns :data:`DEFAULT_BRAND_KIT`; a
    malformed file degrades field-by-field to defaults with a
    :class:`BrandKitWarning`.

    Args:
        base: Directory containing the ``BRAND_KIT`` folder. Defaults to the
            current working directory.
    """
    root = base if base is not None else Path.cwd()
    kit_dir = root / "BRAND_KIT"
    kit_file = kit_dir / "kit.yml"

    if not kit_file.is_file():
        return DEFAULT_BRAND_KIT

    try:
        text = kit_file.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        _warn(f"brand kit could not be parsed ({exc}); using defaults")
        return DEFAULT_BRAND_KIT

    if data is None:
        # Empty file — nothing to override.
        return DEFAULT_BRAND_KIT
    if not isinstance(data, dict):
        _warn("brand kit kit.yml is not a mapping; using defaults")
        return DEFAULT_BRAND_KIT

    return BrandKit(
        colors=_resolve_colors(data.get("colors")),
        fonts=_resolve_fonts(data.get("fonts")),
        logo_path=_resolve_logo(data.get("logo"), kit_dir),
        logo_min_clear_px=_resolve_clear_px(data.get("logo_min_clear_px")),
    )


__all__ = [
    "DEFAULT_BRAND_KIT",
    "BrandKit",
    "BrandKitWarning",
    "load_brand_kit",
]
