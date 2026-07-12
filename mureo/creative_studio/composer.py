"""HTML/CSS composition engine for Creative Studio (PR-B).

The typography & layout layer: it takes a text-free key visual (from the
provider layer, PR-A) plus ad copy and a brand kit, renders a professional
banner via Jinja2 HTML/CSS templates, and rasterises each target format with
headless Chromium (Playwright) so Japanese text is pixel-perfect.

Design mirrors :class:`mureo.google_ads._message_match.LPScreenshotter`:
Playwright (and Jinja2) are imported lazily so the core install stays lean;
when the optional extra is missing a clear :class:`RuntimeError` tells the
operator to install ``mureo[creative]``.

Two entry points:

- :func:`render_html` — pure template rendering (no browser), so template
  logic is unit-testable without Playwright.
- :func:`compose` — the full pipeline; accepts an injectable
  ``browser_factory`` so orchestration is testable with a fake browser.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo._image_validation import validate_image_file
from mureo.creative_studio.fonts import (
    FALLBACK_STACK,
    FONT_MANIFEST,
    ensure_font,
    font_face_css,
)
from mureo.creative_studio.formats import (
    FORMATS_BY_ID as _FORMATS_BY_ID,
)
from mureo.creative_studio.formats import (
    PORTRAIT,
    VERTICAL,
    CreativeFormat,
    aspect_for,
    safe_area_for,
)
from mureo.creative_studio.workspace import sha256_of, write_bytes

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager

    from mureo.creative_studio.brand_kit import BrandKit

logger = logging.getLogger(__name__)

#: The three shipped layout templates, chosen by the operator per compose call.
TEMPLATES: tuple[str, ...] = ("hero_overlay", "split", "minimal_badge")

#: Raised (as a RuntimeError) when the composition extra is not installed.
_MISSING_EXTRA = (
    "Creative Studio composition requires the 'creative' extra: "
    "pip install 'mureo[creative]'"
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Composed PNGs are validated before being returned downstream.
_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_MAX_IMAGE_LABEL = "30MB"
_ALLOWED_IMAGE_EXTENSIONS = frozenset({"png"})

#: Panel proportion for the split layout.
_SPLIT_PANEL_PCT = 42


@dataclass(frozen=True)
class CopySpec:
    """The ad copy overlaid on a visual.

    Attributes:
        headline: The primary line (required).
        body: An optional supporting line.
        cta: The call-to-action button label (required).
        badge: An optional short badge chip (e.g. a limited-offer flag).
    """

    headline: str
    body: str | None
    cta: str
    badge: str | None


# ---------------------------------------------------------------------------
# Lazy dependency imports (mirrors LPScreenshotter's pattern)
# ---------------------------------------------------------------------------


def _import_jinja() -> Any:
    try:
        return importlib.import_module("jinja2")
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise RuntimeError(_MISSING_EXTRA) from exc


def _import_playwright() -> Any:
    try:
        return importlib.import_module("playwright.async_api")
    except ImportError as exc:  # pragma: no cover - requires the extra absent
        raise RuntimeError(_MISSING_EXTRA) from exc


def _build_environment() -> Any:
    """Build a Jinja2 environment with autoescape + StrictUndefined."""
    jinja2 = _import_jinja()
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
    )


# ---------------------------------------------------------------------------
# Data-URI + template rendering
# ---------------------------------------------------------------------------


def _mime_for(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in (".jpg", ".jpeg"):
        return "image/jpeg"
    if lowered == ".webp":
        return "image/webp"
    return "image/png"


def _data_uri(path: Path) -> str:
    """Return a base64 ``data:`` URI for the image at ``path``."""
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{_mime_for(Path(path).suffix)};base64,{encoded}"


def _pct(fraction: float) -> str:
    """Format a fractional inset as a CSS percentage string (0.04 -> ``4%``)."""
    return f"{fraction * 100:g}%"


def render_html(
    *,
    template: str,
    fmt: CreativeFormat,
    copy: CopySpec,
    brand: BrandKit,
    visual_data_uri: str,
    logo_data_uri: str | None = None,
    font_css: str = "",
) -> str:
    """Render one format's banner HTML. Pure — no browser, no file writes.

    Args:
        template: One of :data:`TEMPLATES`.
        fmt: The target :class:`CreativeFormat` (drives viewport + safe area).
        copy: The ad copy to overlay.
        brand: The resolved brand kit (colours / fonts / logo clear-space).
        visual_data_uri: The background key visual as a ``data:`` URI.
        logo_data_uri: The brand logo as a ``data:`` URI, or ``None``.
        font_css: ``@font-face`` CSS to inline (empty falls back to system).

    Raises:
        ValueError: When ``template`` is not a known template.
        RuntimeError: When Jinja2 (the ``creative`` extra) is not installed.
    """
    if template not in TEMPLATES:
        raise ValueError(
            f"unknown template {template!r}; valid templates: {', '.join(TEMPLATES)}"
        )

    env = _build_environment()
    jinja_template = env.get_template(f"{template}.html.j2")

    insets = safe_area_for(fmt.id)
    stack_vertical = aspect_for(fmt.id) in (PORTRAIT, VERTICAL)

    return str(
        jinja_template.render(
            width=fmt.width,
            height=fmt.height,
            pad_top=_pct(insets["top"]),
            pad_right=_pct(insets["right"]),
            pad_bottom=_pct(insets["bottom"]),
            pad_left=_pct(insets["left"]),
            colors=brand.colors,
            fonts=brand.fonts,
            font_css=font_css,
            fallback_stack=FALLBACK_STACK,
            visual_uri=visual_data_uri,
            logo_uri=logo_data_uri,
            logo_min_clear_px=brand.logo_min_clear_px,
            headline=copy.headline,
            body=copy.body,
            cta=copy.cta,
            badge=copy.badge,
            stack_vertical=stack_vertical,
            panel_pct=_SPLIT_PANEL_PCT,
        )
    )


# ---------------------------------------------------------------------------
# Font embedding
# ---------------------------------------------------------------------------


def _embedded_font_css() -> str:
    """Resolve the manifest fonts and return inlined ``@font-face`` CSS.

    Best-effort: any font that cannot be resolved is skipped; if none can be
    resolved the composer falls back to the system font stack (empty string).
    """
    available: dict[str, Path] = {}
    for spec in FONT_MANIFEST:
        path = ensure_font(spec)
        if path is not None:
            available[spec.name] = path
    if not available:
        return ""
    try:
        return font_face_css(available)
    except Exception:  # noqa: BLE001 — fonts must never block composition
        logger.debug(
            "font_face_css failed; falling back to system fonts", exc_info=True
        )
        return ""


# ---------------------------------------------------------------------------
# Browser step
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _default_browser_factory() -> AsyncIterator[Any]:
    """Launch one headless Chromium for the whole compose call."""
    playwright_api = _import_playwright()
    async with playwright_api.async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--force-color-profile=srgb"],
        )
        try:
            yield browser
        finally:
            await browser.close()


async def compose(
    visual_path: Path,
    copy: CopySpec,
    template: str,
    formats: list[str],
    brand: BrandKit,
    out_dir: Path,
    *,
    browser_factory: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
) -> list[dict[str, Any]]:
    """Render ``copy`` over ``visual_path`` into every requested format.

    Launches a single Chromium instance for the whole call; per format it
    opens a page at the exact viewport, sets the rendered HTML, waits for
    fonts, screenshots to PNG, writes it via the workspace helpers, validates
    it, and records ``{format, path, sha256, width, height}``.

    Args:
        visual_path: The text-free background key visual.
        copy: The ad copy to overlay.
        template: One of :data:`TEMPLATES`.
        formats: Target format ids (must exist in the format matrix).
        brand: The resolved brand kit.
        out_dir: Directory to write composed PNGs into.
        browser_factory: Injectable async-context-manager factory yielding a
            browser (tests pass a fake; default launches Playwright Chromium).

    Raises:
        ValueError: When ``template`` is unknown.
        RuntimeError: When the ``creative`` extra is not installed.
    """
    if template not in TEMPLATES:
        raise ValueError(
            f"unknown template {template!r}; valid templates: {', '.join(TEMPLATES)}"
        )

    visual_uri = _data_uri(Path(visual_path))
    logo_uri = _data_uri(brand.logo_path) if brand.logo_path is not None else None
    # Font resolution may hit the network (synchronous httpx). Offload it to a
    # worker thread so it never blocks the event loop this coroutine runs on.
    font_css = await asyncio.to_thread(_embedded_font_css)

    factory = browser_factory or _default_browser_factory
    results: list[dict[str, Any]] = []

    async with factory() as browser:
        for format_id in formats:
            fmt = _FORMATS_BY_ID[format_id]
            html = render_html(
                template=template,
                fmt=fmt,
                copy=copy,
                brand=brand,
                visual_data_uri=visual_uri,
                logo_data_uri=logo_uri,
                font_css=font_css,
            )
            page = await browser.new_page(
                viewport={"width": fmt.width, "height": fmt.height}
            )
            try:
                await page.set_content(html)
                # Wait for embedded/system fonts to be ready before capture so
                # Japanese glyphs render, not tofu boxes.
                await page.evaluate("document.fonts.ready.then(() => true)")
                png = await page.screenshot(type="png")
            finally:
                await page.close()

            out_path = write_bytes(Path(out_dir) / f"{format_id}_{template}.png", png)
            validate_image_file(
                str(out_path),
                max_size_bytes=_MAX_IMAGE_BYTES,
                max_size_label=_MAX_IMAGE_LABEL,
                allowed_extensions=_ALLOWED_IMAGE_EXTENSIONS,
            )
            results.append(
                {
                    "format": format_id,
                    "path": str(out_path),
                    "sha256": sha256_of(out_path),
                    "width": fmt.width,
                    "height": fmt.height,
                }
            )
    return results


__all__ = [
    "TEMPLATES",
    "CopySpec",
    "compose",
    "render_html",
]
