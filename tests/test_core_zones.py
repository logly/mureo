"""``zone_or_none``: a platform-reported zone name never raises (#1008)."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pytest

from mureo.core.zones import zone_or_none


@pytest.mark.unit
@pytest.mark.parametrize("name", ["UTC", "Asia/Tokyo", "America/Los_Angeles"])
def test_a_known_name_resolves(name: str) -> None:
    assert zone_or_none(name) == ZoneInfo(name)


@pytest.mark.unit
@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "Not/AZone",
        # Not plain keys: ``ZoneInfo`` refuses these rather than opening them.
        "/etc/hosts",
        "../UTC",
        "Asia//Tokyo",
        # A directory of the zone database, not a zone.
        "America",
        "a" * 5000,
        "UTC\n",
        # An API answer can hold any JSON type where the name should be.
        9,
        ["UTC"],
        {"name": "UTC"},
    ],
)
def test_anything_else_is_none(value: Any) -> None:
    assert zone_or_none(value) is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [
        IsADirectoryError(21, "Is a directory"),
        PermissionError(13, "Permission denied"),
        OSError(36, "File name too long"),
    ],
)
def test_a_failed_open_of_the_zone_data_is_none(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    """With zone data read from the ``tzdata`` package, a key naming a
    directory or too long for a file name fails as the open does."""

    def _refuse(key: str) -> ZoneInfo:
        raise error

    monkeypatch.setattr("mureo.core.zones.ZoneInfo", _refuse)
    assert zone_or_none("America") is None
