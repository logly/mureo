"""Unit tests for the Creative Studio format matrix."""

from __future__ import annotations

import dataclasses

import pytest

from mureo.creative_studio.formats import (
    FORMATS,
    FORMATS_BY_ID,
    SAFE_AREAS,
    CreativeFormat,
    aspect_for,
    generation_size_for_aspect,
    safe_area_for,
)

_EXPECTED_IDS = {
    "meta_feed_1x1",
    "meta_feed_4x5",
    "story_9x16",
    "gdn_300x250",
    "gdn_336x280",
    "gdn_728x90",
    "gdn_160x600",
    "rda_landscape",
    "rda_square",
}


@pytest.mark.unit
def test_all_expected_formats_present() -> None:
    assert {f.id for f in FORMATS} == _EXPECTED_IDS
    assert set(FORMATS_BY_ID) == _EXPECTED_IDS


@pytest.mark.unit
def test_ids_unique() -> None:
    ids = [f.id for f in FORMATS]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_dimensions_positive() -> None:
    for f in FORMATS:
        assert f.width > 0
        assert f.height > 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("format_id", "width", "height"),
    [
        ("meta_feed_1x1", 1080, 1080),
        ("meta_feed_4x5", 1080, 1350),
        ("story_9x16", 1080, 1920),
        ("gdn_300x250", 300, 250),
        ("gdn_336x280", 336, 280),
        ("gdn_728x90", 728, 90),
        ("gdn_160x600", 160, 600),
        ("rda_landscape", 1200, 628),
        ("rda_square", 1200, 1200),
    ],
)
def test_known_dimensions(format_id: str, width: int, height: int) -> None:
    fmt = FORMATS_BY_ID[format_id]
    assert (fmt.width, fmt.height) == (width, height)


@pytest.mark.unit
def test_format_is_frozen() -> None:
    fmt = FORMATS[0]
    assert isinstance(fmt, CreativeFormat)
    with pytest.raises(dataclasses.FrozenInstanceError):
        fmt.width = 1  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("format_id", "aspect"),
    [
        ("meta_feed_1x1", "square"),
        ("rda_square", "square"),
        ("meta_feed_4x5", "portrait"),
        ("story_9x16", "vertical"),
        ("gdn_160x600", "vertical"),
        ("gdn_300x250", "landscape"),
        ("gdn_336x280", "landscape"),
        ("gdn_728x90", "landscape"),
        ("rda_landscape", "landscape"),
    ],
)
def test_aspect_for(format_id: str, aspect: str) -> None:
    assert aspect_for(format_id) == aspect


@pytest.mark.unit
def test_aspect_for_unknown_raises() -> None:
    with pytest.raises(KeyError):
        aspect_for("does_not_exist")


@pytest.mark.unit
def test_generation_size_for_aspect() -> None:
    assert generation_size_for_aspect("square") == (1024, 1024)

    lw, lh = generation_size_for_aspect("landscape")
    assert lw > lh

    pw, ph = generation_size_for_aspect("portrait")
    assert ph > pw

    vw, vh = generation_size_for_aspect("vertical")
    assert vh > vw

    for aspect in ("square", "portrait", "landscape", "vertical"):
        w, h = generation_size_for_aspect(aspect)
        assert w > 0 and h > 0


@pytest.mark.unit
def test_generation_size_for_aspect_unknown_raises() -> None:
    with pytest.raises(ValueError):
        generation_size_for_aspect("bogus")


# ---------------------------------------------------------------------------
# Per-format safe areas (PR-B)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_safe_areas_cover_every_format() -> None:
    assert set(SAFE_AREAS) == _EXPECTED_IDS
    for insets in SAFE_AREAS.values():
        assert set(insets) == {"top", "right", "bottom", "left"}
        for value in insets.values():
            assert 0.0 <= value < 0.5


@pytest.mark.unit
def test_safe_area_for_default_is_four_percent() -> None:
    insets = safe_area_for("meta_feed_1x1")
    assert insets == {"top": 0.04, "right": 0.04, "bottom": 0.04, "left": 0.04}


@pytest.mark.unit
def test_safe_area_for_story_reserves_platform_chrome() -> None:
    insets = safe_area_for("story_9x16")
    assert insets["top"] == 0.14
    assert insets["bottom"] == 0.20


@pytest.mark.unit
@pytest.mark.parametrize("format_id", ["gdn_728x90", "gdn_160x600"])
def test_safe_area_for_small_gdn_units(format_id: str) -> None:
    insets = safe_area_for(format_id)
    assert insets == {"top": 0.02, "right": 0.02, "bottom": 0.02, "left": 0.02}


@pytest.mark.unit
def test_safe_area_for_returns_copy(format_id: str = "meta_feed_1x1") -> None:
    a = safe_area_for(format_id)
    a["top"] = 0.99
    assert safe_area_for(format_id)["top"] == 0.04  # not mutated by caller


@pytest.mark.unit
def test_safe_area_for_unknown_raises() -> None:
    with pytest.raises(KeyError):
        safe_area_for("does_not_exist")
