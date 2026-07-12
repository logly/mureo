"""Creative format matrix + aspect/master-size helpers for Creative Studio.

Defines the static banner-format matrix (Meta feed / stories, Google
display sizes, responsive display assets) as frozen
:class:`CreativeFormat` records, and the mapping from an aspect class
(``square`` / ``portrait`` / ``landscape`` / ``vertical``) to the
recommended master-generation size a provider should render at before the
composer (PR-B) crops per format.

Safe-area definitions are per-format keep-out margins (fractional insets)
consumed by the composer (PR-B) to keep every headline / CTA / logo clear of
the format's edges and any platform UI chrome.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The four aspect classes the generation tool exposes.
SQUARE = "square"
PORTRAIT = "portrait"
LANDSCAPE = "landscape"
VERTICAL = "vertical"


@dataclass(frozen=True)
class CreativeFormat:
    """A single target banner format.

    Attributes:
        id: Stable identifier (e.g. ``"meta_feed_1x1"``).
        width: Pixel width of the final asset.
        height: Pixel height of the final asset.
        aspect: Aspect class used to pick a master-generation size.
        platform: Owning platform / surface (``"meta"``, ``"gdn"``, ``"rda"``).
    """

    id: str
    width: int
    height: int
    aspect: str
    platform: str


# The format matrix. Aspect class is chosen by orientation: near-square →
# ``square``; mildly tall (4:5) → ``portrait``; very tall (9:16, skyscraper)
# → ``vertical``; wide → ``landscape``.
FORMATS: tuple[CreativeFormat, ...] = (
    CreativeFormat("meta_feed_1x1", 1080, 1080, SQUARE, "meta"),
    CreativeFormat("meta_feed_4x5", 1080, 1350, PORTRAIT, "meta"),
    CreativeFormat("story_9x16", 1080, 1920, VERTICAL, "meta"),
    CreativeFormat("gdn_300x250", 300, 250, LANDSCAPE, "gdn"),
    CreativeFormat("gdn_336x280", 336, 280, LANDSCAPE, "gdn"),
    CreativeFormat("gdn_728x90", 728, 90, LANDSCAPE, "gdn"),
    CreativeFormat("gdn_160x600", 160, 600, VERTICAL, "gdn"),
    CreativeFormat("rda_landscape", 1200, 628, LANDSCAPE, "rda"),
    CreativeFormat("rda_square", 1200, 1200, SQUARE, "rda"),
)

#: Format lookup by id.
FORMATS_BY_ID: dict[str, CreativeFormat] = {f.id: f for f in FORMATS}


# Recommended master-generation size per aspect class. Providers clamp these
# to their own supported sizes; the composer (PR-B) crops the master to each
# concrete format's dimensions.
_GENERATION_SIZE_BY_ASPECT: dict[str, tuple[int, int]] = {
    SQUARE: (1024, 1024),
    PORTRAIT: (1024, 1536),
    LANDSCAPE: (1536, 1024),
    VERTICAL: (1024, 1536),
}


# Per-format safe-area (headline / CTA / logo keep-out) definitions, expressed
# as fractional margins (top, right, bottom, left) of the format's own
# dimensions. These are per FORMAT id — not per aspect class — because two
# formats sharing an aspect can need very different insets: a 9:16 story
# reserves large top/bottom bands for platform UI chrome, whereas a 160x600
# skyscraper (same "vertical" aspect) wants a tight 2% margin to use every
# scarce pixel. The composer converts these fractions to CSS padding.
#
# Defaults: 4% each side. Overrides:
#   - story_9x16: 14% top / 20% bottom (Instagram/Facebook story UI chrome).
#   - gdn_728x90 & gdn_160x600: 2% (very small canvases, maximise usable area).
_DEFAULT_INSET = 0.04


def _uniform(value: float) -> dict[str, float]:
    """Return an inset dict with the same margin on all four sides."""
    return {"top": value, "right": value, "bottom": value, "left": value}


SAFE_AREAS: dict[str, dict[str, float]] = {
    "meta_feed_1x1": _uniform(_DEFAULT_INSET),
    "meta_feed_4x5": _uniform(_DEFAULT_INSET),
    "story_9x16": {"top": 0.14, "right": 0.04, "bottom": 0.20, "left": 0.04},
    "gdn_300x250": _uniform(_DEFAULT_INSET),
    "gdn_336x280": _uniform(_DEFAULT_INSET),
    "gdn_728x90": _uniform(0.02),
    "gdn_160x600": _uniform(0.02),
    "rda_landscape": _uniform(_DEFAULT_INSET),
    "rda_square": _uniform(_DEFAULT_INSET),
}


def safe_area_for(format_id: str) -> dict[str, float]:
    """Return a fresh copy of the safe-area insets for ``format_id``.

    A copy is returned so a caller mutating the result never corrupts the
    shared table.

    Raises:
        KeyError: When ``format_id`` is not a known format.
    """
    return dict(SAFE_AREAS[format_id])


def aspect_for(format_id: str) -> str:
    """Return the aspect class for ``format_id``.

    Raises:
        KeyError: When ``format_id`` is not a known format.
    """
    return FORMATS_BY_ID[format_id].aspect


def generation_size_for_aspect(aspect: str) -> tuple[int, int]:
    """Return the recommended ``(width, height)`` master size for ``aspect``.

    Raises:
        ValueError: When ``aspect`` is not one of the four known classes.
    """
    try:
        return _GENERATION_SIZE_BY_ASPECT[aspect]
    except KeyError:
        valid = ", ".join(sorted(_GENERATION_SIZE_BY_ASPECT))
        raise ValueError(
            f"unknown aspect {aspect!r}; expected one of: {valid}"
        ) from None


__all__ = [
    "FORMATS",
    "FORMATS_BY_ID",
    "LANDSCAPE",
    "PORTRAIT",
    "SAFE_AREAS",
    "SQUARE",
    "VERTICAL",
    "CreativeFormat",
    "aspect_for",
    "generation_size_for_aspect",
    "safe_area_for",
]
