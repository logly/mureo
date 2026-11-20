"""The Performance Max image swap reads a local file once (#1011).

``_uploaded_image_asset`` measures the dimensions from the very bytes it
sends: one bounded read through ``read_image_file``, the slot's shape rule
judged on those bytes, and the same bytes handed to ``_create_image_asset``.
The file is not reopened to measure it or to upload it, so a file replaced
in between cannot be the one that reaches Google.

The open count (``tests._image_open_count``) covers the descriptor
``read_image_file`` opens (``os.open``), ``Path.open`` (``Path.read_bytes``
included) and the builtin ``open``, for the one path under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests._image_open_count import OPENED_ONCE, _count_opens
from tests.test_google_ads_asset_group_images import (
    CUSTOMER_ID,
    _install_fake_mutate,
    _install_search,
    _make_client,
    _mutate_response,
    _swap_params,
    _write_png,
)

pytestmark = pytest.mark.unit


def _install_fake_create(client: Any) -> list[tuple[bytes, str]]:
    """Replace the asset creation; return the ``(bytes, name)`` it received."""
    captured: list[tuple[bytes, str]] = []

    async def _create(image_data: bytes, asset_name: str) -> dict[str, Any]:
        captured.append((image_data, asset_name))
        return {
            "resource_name": f"customers/{CUSTOMER_ID}/assets/888",
            "id": "888",
            "name": asset_name,
        }

    client._create_image_asset = _create
    return captured


async def test_the_bytes_measured_are_the_bytes_sent(tmp_path: Path) -> None:
    client = _make_client()
    _install_search(client)
    _install_fake_mutate(client, _mutate_response())
    created = _install_fake_create(client)
    image = _write_png(tmp_path / "hero.png", 1200, 628)

    result = await client.replace_asset_group_image_asset(
        _swap_params(new_asset_id=None, new_image_path=str(image))
    )

    assert created == [(image.read_bytes(), "hero.png")]
    assert result["added"]["width_pixels"] == 1200
    assert result["added"]["height_pixels"] == 628


async def test_the_file_is_opened_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client()
    _install_search(client)
    _install_fake_mutate(client, _mutate_response())
    created = _install_fake_create(client)
    image = _write_png(tmp_path / "hero.png", 1200, 628)
    counts = _count_opens(monkeypatch, image)

    await client.replace_asset_group_image_asset(
        _swap_params(new_asset_id=None, new_image_path=str(image))
    )

    assert counts == OPENED_ONCE
    assert len(created) == 1


async def test_content_that_is_not_the_declared_type_is_not_sent(
    tmp_path: Path,
) -> None:
    client = _make_client()
    _install_search(client)
    captured = _install_fake_mutate(client, _mutate_response())
    created = _install_fake_create(client)
    image = tmp_path / "hero.png"
    image.write_text("not an image", encoding="utf-8")

    with pytest.raises(ValueError, match="not a recognisable"):
        await client.replace_asset_group_image_asset(
            _swap_params(new_asset_id=None, new_image_path=str(image))
        )

    assert not created
    assert not captured


async def test_a_file_over_the_limit_is_not_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = _write_png(tmp_path / "hero.png", 1200, 628)
    monkeypatch.setattr(
        "mureo.google_ads._asset_groups_images._GOOGLE_MAX_IMAGE_SIZE_BYTES",
        image.stat().st_size - 1,
    )
    client = _make_client()
    _install_search(client)
    created = _install_fake_create(client)

    with pytest.raises(ValueError, match="File size exceeds the limit"):
        await client.replace_asset_group_image_asset(
            _swap_params(new_asset_id=None, new_image_path=str(image))
        )

    assert not created
