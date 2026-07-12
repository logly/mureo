"""Unit tests for the Creative Studio HTML/CSS composition engine.

Template rendering (``render_html``) is pure and exercised directly. The
browser step (``compose``) is driven with a FAKE ``browser_factory`` that
records viewports and returns a constant PNG, so Playwright is never
launched. Font embedding is stubbed so no network is touched.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from mureo.creative_studio import composer as composer_mod
from mureo.creative_studio.brand_kit import DEFAULT_BRAND_KIT
from mureo.creative_studio.composer import TEMPLATES, CopySpec, compose, render_html
from mureo.creative_studio.formats import FORMATS_BY_ID

_VISUAL_URI = "data:image/png;base64,QUJD"
_LOGO_URI = "data:image/png;base64,TE9HTw=="
# 1x1 transparent PNG — a constant the fake browser "screenshots".
_ONE_PX_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def _copy(**over: object) -> CopySpec:
    base = {
        "headline": "強力な見出し",
        "body": "本文の説明",
        "cta": "今すぐ購入",
        "badge": None,
    }
    base.update(over)
    return CopySpec(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_templates_constant() -> None:
    assert TEMPLATES == ("hero_overlay", "split", "minimal_badge")


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_exact_viewport(template: str) -> None:
    fmt = FORMATS_BY_ID["meta_feed_1x1"]
    html = render_html(
        template=template,
        fmt=fmt,
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "1080px" in html
    # Body must not scroll: exact size + hidden overflow.
    assert "overflow:hidden" in html.replace(" ", "")
    assert "box-sizing:border-box" in html.replace(" ", "")


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_small_format_dimensions(template: str) -> None:
    fmt = FORMATS_BY_ID["gdn_728x90"]
    html = render_html(
        template=template,
        fmt=fmt,
        copy=_copy(badge="SALE"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "728px" in html
    assert "90px" in html
    assert "--u" in html  # clamp unit custom property present


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_autoescapes_headline(template: str) -> None:
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(headline="<script>alert(1)</script>", badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_default_safe_area_4pct(template: str) -> None:
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "4%" in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_story_safe_area(template: str) -> None:
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["story_9x16"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    # story_9x16 reserves extra chrome room top/bottom.
    assert "14%" in html
    assert "20%" in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_embeds_visual_data_uri(template: str) -> None:
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert _VISUAL_URI in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_cta_present(template: str) -> None:
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(cta="ここをクリック", badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "ここをクリック" in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_body_conditional(template: str) -> None:
    with_body = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(body="ユニークな本文マーカー", badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "ユニークな本文マーカー" in with_body

    without_body = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(body=None, badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "ユニークな本文マーカー" not in without_body


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_logo_conditional(template: str) -> None:
    with_logo = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
        logo_data_uri=_LOGO_URI,
    )
    assert _LOGO_URI in with_logo

    without_logo = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
        logo_data_uri=None,
    )
    assert _LOGO_URI not in without_logo


@pytest.mark.unit
def test_render_html_badge_on_minimal_badge() -> None:
    html = render_html(
        template="minimal_badge",
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定オファー"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
    )
    assert "限定オファー" in html


@pytest.mark.unit
@pytest.mark.parametrize("template", TEMPLATES)
def test_render_html_injects_font_css(template: str) -> None:
    marker = "@font-face{font-family:'MARKERFONT'}"
    html = render_html(
        template=template,
        fmt=FORMATS_BY_ID["meta_feed_1x1"],
        copy=_copy(badge="限定"),
        brand=DEFAULT_BRAND_KIT,
        visual_data_uri=_VISUAL_URI,
        font_css=marker,
    )
    assert marker in html


@pytest.mark.unit
def test_render_html_unknown_template_raises() -> None:
    with pytest.raises(ValueError, match="template"):
        render_html(
            template="does_not_exist",
            fmt=FORMATS_BY_ID["meta_feed_1x1"],
            copy=_copy(),
            brand=DEFAULT_BRAND_KIT,
            visual_data_uri=_VISUAL_URI,
        )


@pytest.mark.unit
def test_render_html_missing_jinja_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = importlib.import_module

    def fake_import(name: str, *args: object, **kwargs: object):
        if name == "jinja2":
            raise ImportError("no jinja2")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(composer_mod.importlib, "import_module", fake_import)
    with pytest.raises(RuntimeError, match=r"mureo\[creative\]"):
        render_html(
            template="hero_overlay",
            fmt=FORMATS_BY_ID["meta_feed_1x1"],
            copy=_copy(),
            brand=DEFAULT_BRAND_KIT,
            visual_data_uri=_VISUAL_URI,
        )


# ---------------------------------------------------------------------------
# compose (orchestration) with a fake browser
# ---------------------------------------------------------------------------


class _FakePage:
    def __init__(self, owner: _FakeBrowser) -> None:
        self._owner = owner

    async def set_content(self, html: str) -> None:
        self._owner.htmls.append(html)

    async def evaluate(self, script: str) -> bool:
        self._owner.evaluated.append(script)
        return True

    async def screenshot(self, *, type: str = "png") -> bytes:  # noqa: A002
        self._owner.screenshot_types.append(type)
        return _ONE_PX_PNG

    async def close(self) -> None:
        return None


class _FakeBrowser:
    def __init__(self) -> None:
        self.viewports: list[dict[str, int]] = []
        self.htmls: list[str] = []
        self.evaluated: list[str] = []
        self.screenshot_types: list[str] = []

    async def new_page(self, *, viewport: dict[str, int]) -> _FakePage:
        self.viewports.append(viewport)
        return _FakePage(self)


def _fake_factory(browser: _FakeBrowser):
    @asynccontextmanager
    async def factory():
        yield browser

    return factory


@pytest.mark.unit
async def test_compose_writes_files_per_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composer_mod, "_embedded_font_css", lambda: "")
    visual = tmp_path / "visual.png"
    visual.write_bytes(b"\x89PNG\r\n\x1a\n visual bytes")
    out = tmp_path / "out"
    out.mkdir()

    browser = _FakeBrowser()
    fmt_ids = ["meta_feed_1x1", "gdn_300x250"]
    results = await compose(
        visual,
        _copy(),
        "hero_overlay",
        fmt_ids,
        DEFAULT_BRAND_KIT,
        out,
        browser_factory=_fake_factory(browser),
    )

    assert [r["format"] for r in results] == fmt_ids
    for entry, fid in zip(results, fmt_ids, strict=True):
        path = Path(entry["path"])
        assert path.exists()
        assert path.name == f"{fid}_hero_overlay.png"
        assert entry["sha256"]
        fmt = FORMATS_BY_ID[fid]
        assert entry["width"] == fmt.width
        assert entry["height"] == fmt.height

    # One page per format, with the exact viewport of that format.
    assert browser.viewports == [
        {"width": 1080, "height": 1080},
        {"width": 300, "height": 250},
    ]
    # Fonts-ready gate is awaited once per format.
    assert len(browser.evaluated) == 2


@pytest.mark.unit
async def test_compose_embeds_logo_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dataclasses

    monkeypatch.setattr(composer_mod, "_embedded_font_css", lambda: "")
    visual = tmp_path / "visual.png"
    visual.write_bytes(b"\x89PNG visual")
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"\x89PNG logo")
    brand = dataclasses.replace(DEFAULT_BRAND_KIT, logo_path=logo)
    out = tmp_path / "out"
    out.mkdir()

    browser = _FakeBrowser()
    await compose(
        visual,
        _copy(),
        "hero_overlay",
        ["meta_feed_1x1"],
        brand,
        out,
        browser_factory=_fake_factory(browser),
    )
    # The composed HTML embeds a logo data URI.
    assert "data:image/png;base64," in browser.htmls[0]
    # Two data URIs at minimum: the visual and the logo.
    assert browser.htmls[0].count("data:image/png;base64,") >= 2


@pytest.mark.unit
async def test_compose_resolves_fonts_via_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fonts unavailable (offline): the resolver returns "" but compose still
    # succeeds, and the (potentially blocking) resolution is offloaded to a
    # worker thread so the event loop is never blocked.
    monkeypatch.setattr(composer_mod, "_embedded_font_css", lambda: "")
    recorded: list[object] = []
    real_to_thread = composer_mod.asyncio.to_thread

    async def recording_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        recorded.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(composer_mod.asyncio, "to_thread", recording_to_thread)

    visual = tmp_path / "visual.png"
    visual.write_bytes(b"\x89PNG visual")
    out = tmp_path / "out"
    out.mkdir()

    browser = _FakeBrowser()
    results = await compose(
        visual,
        _copy(),
        "hero_overlay",
        ["meta_feed_1x1"],
        DEFAULT_BRAND_KIT,
        out,
        browser_factory=_fake_factory(browser),
    )
    assert len(results) == 1
    # Font resolution was routed through asyncio.to_thread.
    assert composer_mod._embedded_font_css in recorded


@pytest.mark.unit
async def test_compose_unknown_template_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(composer_mod, "_embedded_font_css", lambda: "")
    visual = tmp_path / "visual.png"
    visual.write_bytes(b"\x89PNG visual")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="template"):
        await compose(
            visual,
            _copy(),
            "nope",
            ["meta_feed_1x1"],
            DEFAULT_BRAND_KIT,
            out,
            browser_factory=_fake_factory(_FakeBrowser()),
        )


@pytest.mark.unit
def test_copy_spec_is_frozen() -> None:
    import dataclasses

    spec = _copy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.headline = "x"  # type: ignore[misc]


@pytest.mark.unit
def test_manifest_helper_round_trip(tmp_path: Path) -> None:
    # Sanity guard that json metadata survives (used by the MCP compose tool).
    data = {"kind": "compose", "template": "split", "files": []}
    (tmp_path / "m.json").write_text(json.dumps(data), encoding="utf-8")
    assert json.loads((tmp_path / "m.json").read_text())["kind"] == "compose"
