"""Regression tests for BRAND_KIT logo sandbox containment (H6).

A brand kit may be client-supplied (e.g. in an agency workspace), so the
``logo`` field must stay strictly inside the BRAND_KIT directory. An absolute
path, a ``..`` traversal, or a symlink pointing outside the directory must all
be rejected (logo treated as absent) — the string-level ".." check in the
shared media validator is blind to absolute paths and symlink escapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mureo.creative_studio.brand_kit import BrandKitWarning, load_brand_kit

if TYPE_CHECKING:
    from pathlib import Path

# A minimal byte string that clears the image-file validator: a valid PNG
# signature (so magic-byte checks pass) with unparseable dimensions (skipped).
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _write_kit(base: Path, logo_line: str) -> Path:
    kit_dir = base / "BRAND_KIT"
    kit_dir.mkdir(parents=True, exist_ok=True)
    (kit_dir / "kit.yml").write_text(f"logo: {logo_line}\n", encoding="utf-8")
    return kit_dir


@pytest.mark.unit
def test_absolute_logo_path_rejected(tmp_path: Path) -> None:
    """An absolute logo path escapes the sandbox and must be refused."""
    secret = tmp_path / "secret.png"
    secret.write_bytes(_FAKE_PNG)
    _write_kit(tmp_path, f'"{secret}"')
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_absolute_system_path_rejected(tmp_path: Path) -> None:
    """The canonical '/etc/hosts' escape is refused before validation."""
    _write_kit(tmp_path, '"/etc/hosts"')
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_parent_traversal_rejected(tmp_path: Path) -> None:
    """A ``..`` traversal to a real image outside BRAND_KIT is refused."""
    outside = tmp_path / "secret.png"
    outside.write_bytes(_FAKE_PNG)
    _write_kit(tmp_path, '"../secret.png"')
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_symlink_escape_rejected(tmp_path: Path) -> None:
    """A symlink inside BRAND_KIT pointing outside it is refused."""
    outside = tmp_path / "outside.png"
    outside.write_bytes(_FAKE_PNG)
    kit_dir = _write_kit(tmp_path, '"logo.png"')
    (kit_dir / "logo.png").symlink_to(outside)
    with pytest.warns(BrandKitWarning):
        kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path is None


@pytest.mark.unit
def test_valid_relative_logo_accepted(tmp_path: Path) -> None:
    """A plain in-directory relative logo still resolves normally."""
    kit_dir = _write_kit(tmp_path, '"logo.png"')
    logo = kit_dir / "logo.png"
    logo.write_bytes(_FAKE_PNG)
    kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path == logo.resolve()


@pytest.mark.unit
def test_in_directory_symlink_accepted(tmp_path: Path) -> None:
    """A symlink whose target stays inside BRAND_KIT is allowed."""
    kit_dir = _write_kit(tmp_path, '"logo.png"')
    assets = kit_dir / "assets"
    assets.mkdir()
    real = assets / "real.png"
    real.write_bytes(_FAKE_PNG)
    (kit_dir / "logo.png").symlink_to(real)
    kit = load_brand_kit(base=tmp_path)
    assert kit.logo_path == real.resolve()
