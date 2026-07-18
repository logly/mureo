"""Regression tests for boundary validation in the Creative Studio tools.

Covers two gaps where malformed arguments bypassed the structured ``_error``
envelope and either crashed (``int(None)`` / ``generation_size_for_aspect``
ValueError) or were silently accepted:

* generate_visual — ``n`` and ``aspect`` are now validated symmetrically with
  ``template`` (M8);
* compose — an explicit empty ``formats: []`` is rejected instead of being
  replaced by the default (LOW).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mureo.mcp.tools_creative_studio as mod


class _FakeProvider:
    """Minimal configured provider so generate_visual can reach validation."""

    name = "fake"
    models = ("fake-model-1",)

    def is_configured(self) -> bool:
        return True

    def capabilities(self) -> dict:
        return {"edit": False, "max_size": [1024, 1024]}

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        return [b"\x89PNG\r\n\x1a\n" + b"\x00" * 32] * n

    async def edit(self, image: bytes, instruction: str) -> bytes:  # pragma: no cover
        raise NotImplementedError


def _payload(result: list) -> dict:
    return json.loads(result[0].text)


# --- M8: generate_visual n / aspect validation ---------------------------


@pytest.mark.unit
async def test_generate_visual_null_n_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual", {"prompt": "a cat", "n": None}
    )
    payload = _payload(result)
    assert "error" in payload
    assert "n must be an integer" in payload["error"]


@pytest.mark.unit
async def test_generate_visual_non_numeric_n_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual", {"prompt": "a cat", "n": "lots"}
    )
    assert "error" in _payload(result)


@pytest.mark.unit
@pytest.mark.parametrize("bad_n", [0, 7, -1])
async def test_generate_visual_out_of_range_n_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bad_n: int
) -> None:
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual", {"prompt": "a cat", "n": bad_n}
    )
    assert "error" in _payload(result)


@pytest.mark.unit
async def test_generate_visual_unknown_aspect_returns_error_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "a cat", "aspect": "diagonal"},
    )
    payload = _payload(result)
    assert "error" in payload
    assert "diagonal" in payload["error"]


@pytest.mark.unit
async def test_generate_visual_valid_n_and_aspect_still_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "a cat", "aspect": "landscape", "n": 3},
    )
    payload = _payload(result)
    assert "error" not in payload
    assert len(payload["files"]) == 3


# --- LOW: compose formats empty-array validation -------------------------


async def _fake_compose(
    visual_path: Path,
    copy: object,
    template: str,
    formats: list[str],
    brand: object,
    out_dir: Path,
    **_kwargs: object,
) -> list[dict]:
    files = []
    for fid in formats:
        p = Path(out_dir) / f"{fid}_{template}.png"
        p.write_bytes(b"\x89PNG composed")
        files.append(
            {"format": fid, "path": str(p), "sha256": "d", "width": 1, "height": 1}
        )
    return files


@pytest.mark.unit
async def test_compose_explicit_empty_formats_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.composer, "compose", _fake_compose)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    result = await mod.handle_tool(
        "creative_studio_compose",
        {"visual_path": str(visual), "headline": "H", "cta": "C", "formats": []},
    )
    payload = _payload(result)
    assert "error" in payload
    assert "non-empty" in payload["error"]


@pytest.mark.unit
async def test_compose_omitted_formats_applies_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.composer, "compose", _fake_compose)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    result = await mod.handle_tool(
        "creative_studio_compose",
        {"visual_path": str(visual), "headline": "H", "cta": "C"},
    )
    payload = _payload(result)
    assert "error" not in payload
    assert len(payload["files"]) == 1
    assert payload["files"][0]["format"] == "meta_feed_1x1"
