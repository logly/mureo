"""Unit tests for the Creative Studio brand-kit loader.

The loader must NEVER raise on a malformed kit: quality of output must not
depend on config hygiene, so every field degrades to a tasteful default
independently and a warning is emitted instead of an exception.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mureo.creative_studio.brand_kit import (
    DEFAULT_BRAND_KIT,
    BrandKit,
    BrandKitWarning,
    load_brand_kit,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_kit(base: Path, text: str) -> None:
    kit_dir = base / "BRAND_KIT"
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yml").write_text(text, encoding="utf-8")


def _write_logo(base: Path, name: str = "logo.png") -> Path:
    kit_dir = base / "BRAND_KIT"
    kit_dir.mkdir(parents=True, exist_ok=True)
    logo = kit_dir / name
    logo.write_bytes(b"\x89PNG\r\n\x1a\n fake logo bytes")
    return logo


@pytest.mark.unit
def test_default_brand_kit_shape() -> None:
    assert isinstance(DEFAULT_BRAND_KIT, BrandKit)
    assert DEFAULT_BRAND_KIT.colors["primary"] == "#1a1d29"
    assert DEFAULT_BRAND_KIT.colors["accent"] == "#4f46e5"
    assert DEFAULT_BRAND_KIT.colors["text"] == "#111827"
    assert DEFAULT_BRAND_KIT.colors["background"] == "#ffffff"
    assert DEFAULT_BRAND_KIT.fonts["heading"] == "Noto Sans JP"
    assert DEFAULT_BRAND_KIT.fonts["body"] == "Noto Sans JP"
    assert DEFAULT_BRAND_KIT.logo_path is None
    assert DEFAULT_BRAND_KIT.logo_min_clear_px == 24


@pytest.mark.unit
def test_brand_kit_is_frozen() -> None:
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_BRAND_KIT.logo_min_clear_px = 1  # type: ignore[misc]


@pytest.mark.unit
def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    kit = load_brand_kit(base=tmp_path)
    assert kit == DEFAULT_BRAND_KIT


@pytest.mark.unit
def test_parses_kit_yml(tmp_path: Path) -> None:
    _write_kit(
        tmp_path,
        """
colors:
  primary: "#0055ff"
  accent: "#ff8800"
fonts:
  heading: "Zen Kaku Gothic New"
  body: "Noto Sans JP"
logo_min_clear_px: 40
""",
    )
    kit = load_brand_kit(base=tmp_path)
    assert kit.colors["primary"] == "#0055ff"
    assert kit.colors["accent"] == "#ff8800"
    # Unspecified colors keep defaults.
    assert kit.colors["text"] == DEFAULT_BRAND_KIT.colors["text"]
    assert kit.fonts["heading"] == "Zen Kaku Gothic New"
    assert kit.fonts["body"] == "Noto Sans JP"
    assert kit.logo_min_clear_px == 40


@pytest.mark.unit
def test_three_digit_hex_accepted(tmp_path: Path) -> None:
    _write_kit(tmp_path, 'colors:\n  primary: "#fa0"\n')
    kit = load_brand_kit(base=tmp_path)
    assert kit.colors["primary"] == "#fa0"


@pytest.mark.unit
def test_invalid_hex_falls_back_per_field(tmp_path: Path) -> None:
    _write_kit(
        tmp_path,
        'colors:\n  primary: "not-a-color"\n  accent: "#123456"\n',
    )
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    # The bad field degrades to its default; the good field is applied.
    assert kit.colors["primary"] == DEFAULT_BRAND_KIT.colors["primary"]
    assert kit.colors["accent"] == "#123456"


@pytest.mark.unit
def test_valid_logo_resolved(tmp_path: Path) -> None:
    logo = _write_logo(tmp_path)
    _write_kit(tmp_path, 'logo: "logo.png"\n')
    kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is not None
    assert kit.logo_path == logo.resolve()


@pytest.mark.unit
def test_invalid_logo_treated_as_absent(tmp_path: Path) -> None:
    # A .txt logo fails the image-file validation -> absent + warning.
    kit_dir = tmp_path / "BRAND_KIT"
    kit_dir.mkdir(parents=True)
    (kit_dir / "logo.txt").write_text("nope")
    (kit_dir / "kit.yml").write_text('logo: "logo.txt"\n', encoding="utf-8")
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_missing_logo_file_treated_as_absent(tmp_path: Path) -> None:
    _write_kit(tmp_path, 'logo: "does_not_exist.png"\n')
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_logo_traversal_rejected(tmp_path: Path) -> None:
    _write_kit(tmp_path, 'logo: "../../etc/passwd"\n')
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_unknown_keys_ignored(tmp_path: Path) -> None:
    _write_kit(
        tmp_path,
        'colors:\n  primary: "#010203"\n  bogus: "#ffffff"\nmystery: 42\n',
    )
    kit = load_brand_kit(base=tmp_path)
    assert kit.colors["primary"] == "#010203"
    assert "bogus" not in kit.colors


@pytest.mark.unit
def test_garbage_yaml_never_raises(tmp_path: Path) -> None:
    _write_kit(tmp_path, "colors: [unclosed, list\n  primary: nope::")
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit == DEFAULT_BRAND_KIT


@pytest.mark.unit
def test_non_mapping_yaml_never_raises(tmp_path: Path) -> None:
    _write_kit(tmp_path, "just a scalar string")
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit == DEFAULT_BRAND_KIT


@pytest.mark.unit
def test_empty_kit_yml_returns_defaults(tmp_path: Path) -> None:
    _write_kit(tmp_path, "")
    kit = load_brand_kit(base=tmp_path)
    assert kit == DEFAULT_BRAND_KIT


@pytest.mark.unit
def test_font_name_css_injection_rejected(tmp_path, recwarn):
    """A font name that could break out of the CSS string context (templates
    mark font names ``| safe``) is rejected and the default kept."""
    kit_dir = tmp_path / "BRAND_KIT"
    kit_dir.mkdir()
    (kit_dir / "kit.yml").write_text(
        "fonts:\n"
        '  heading: "\'; } </style><script>alert(1)</script>"\n'
        "  body: 'Zen Kaku Gothic New'\n",
        encoding="utf-8",
    )
    kit = load_brand_kit(tmp_path)
    assert kit.fonts["heading"] == DEFAULT_BRAND_KIT.fonts["heading"]
    assert kit.fonts["body"] == "Zen Kaku Gothic New"
    assert any("heading" in str(w.message) for w in recwarn.list)
