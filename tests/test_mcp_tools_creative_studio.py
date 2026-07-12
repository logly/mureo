"""Tests for the ``creative_studio_*`` MCP tool family.

The tools live in a single self-contained module
(:mod:`mureo.mcp.tools_creative_studio`) mirroring
``tools_analytics_registry``. All tests are hermetic: a fake in-memory
provider is injected in place of the real HTTP-backed built-ins, so no
network call is made and no credential file is read.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

import mureo.mcp.tools_creative_studio as mod
from mureo.creative_studio.providers import NotSupportedError


class _FakeProvider:
    """Minimal in-memory ImageProvider used to drive the handler."""

    name = "fake"
    models = ("fake-model-1",)

    def __init__(
        self, *, configured: bool = True, images: list[bytes] | None = None
    ) -> None:
        self._configured = configured
        self._images = images if images is not None else [b"IMG-A", b"IMG-B"]
        self.calls: list[dict[str, object]] = []

    def is_configured(self) -> bool:
        return self._configured

    def capabilities(self) -> dict:
        return {"edit": False, "max_size": [1024, 1024]}

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        self.calls.append({"prompt": prompt, "width": width, "height": height, "n": n})
        return list(self._images[:n])

    async def edit(self, image: bytes, instruction: str) -> bytes:
        raise NotSupportedError()


def _payload(result: list) -> dict:
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# Tool definitions / schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_tool_names_are_prefixed() -> None:
    names = {t.name for t in mod.TOOLS}
    assert names == {
        "creative_studio_providers_list",
        "creative_studio_generate_visual",
    }
    for tool in mod.TOOLS:
        assert tool.name.startswith("creative_studio_")


@pytest.mark.unit
def test_all_schemas_are_valid_json_schema() -> None:
    for tool in mod.TOOLS:
        Draft202012Validator.check_schema(tool.inputSchema)


@pytest.mark.unit
def test_generate_visual_schema_constraints() -> None:
    tool = next(t for t in mod.TOOLS if t.name == "creative_studio_generate_visual")
    props = tool.inputSchema["properties"]
    assert props["prompt"]["type"] == "string"
    assert props["prompt"]["minLength"] == 1
    assert set(props["aspect"]["enum"]) == {
        "square",
        "portrait",
        "landscape",
        "vertical",
    }
    assert props["aspect"]["default"] == "square"
    assert props["n"]["minimum"] == 1
    assert props["n"]["maximum"] == 6
    assert props["n"]["default"] == 2
    assert "provider" in props
    assert tool.inputSchema["required"] == ["prompt"]


# ---------------------------------------------------------------------------
# build_visual_prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_visual_prompt_appends_no_text_constraint() -> None:
    out = mod.build_visual_prompt("a serene mountain lake at dawn")
    assert "a serene mountain lake at dawn" in out
    lowered = out.lower()
    assert "no text" in lowered
    assert "no letters" in lowered
    assert "negative space" in lowered


# ---------------------------------------------------------------------------
# providers_list handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_providers_list_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeProvider()
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    result = await mod.handle_tool("creative_studio_providers_list", {})
    payload = _payload(result)
    assert payload["providers"] == [
        {
            "name": "fake",
            "configured": True,
            "capabilities": {"edit": False, "max_size": [1024, 1024]},
            "models": ["fake-model-1"],
        }
    ]


# ---------------------------------------------------------------------------
# generate_visual handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_generate_visual_no_provider_error_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        mod, "available_providers", lambda: [_FakeProvider(configured=False)]
    )
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual", {"prompt": "a cat"}
    )
    payload = _payload(result)
    assert "error" in payload
    assert "creative_studio" in payload["error"]
    for env in ("OPENAI_API_KEY", "GEMINI_API_KEY", "FAL_KEY"):
        assert env in payload["error"]


@pytest.mark.unit
async def test_generate_visual_happy_path_writes_files_and_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeProvider(images=[b"IMG-A", b"IMG-B"])
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)

    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "a cat", "aspect": "square", "n": 2},
    )
    payload = _payload(result)

    assert "run_id" in payload
    assert Path(payload["run_dir"]).is_dir()
    assert len(payload["files"]) == 2
    for entry in payload["files"]:
        p = Path(entry["path"])
        assert p.exists()
        assert p.suffix == ".png"
        assert entry["sha256"]
        assert entry["provider"] == "fake"

    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["run_id"] == payload["run_id"]
    assert manifest["prompt"] == "a cat"
    assert manifest["aspect"] == "square"
    assert manifest["n"] == 2
    assert len(manifest["files"]) == 2
    assert "created_at" in manifest

    # The provider received the wrapped no-text prompt at the square master size.
    assert len(fake.calls) == 1
    assert "no text" in str(fake.calls[0]["prompt"]).lower()
    assert fake.calls[0]["width"] == 1024
    assert fake.calls[0]["height"] == 1024


@pytest.mark.unit
async def test_generate_visual_acquires_throttle_before_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeProvider(images=[b"IMG"])
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)

    acquire = AsyncMock()
    monkeypatch.setattr(mod._THROTTLER, "acquire", acquire)

    await mod.handle_tool("creative_studio_generate_visual", {"prompt": "x", "n": 1})
    acquire.assert_awaited()


@pytest.mark.unit
async def test_generate_visual_all_fans_out_one_per_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    a = _FakeProvider(images=[b"A1", b"A2"])
    b = _FakeProvider(images=[b"B1", b"B2"])
    b.name = "fake2"
    monkeypatch.setattr(mod, "available_providers", lambda: [a, b])
    monkeypatch.chdir(tmp_path)

    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "x", "provider": "all", "n": 3},
    )
    payload = _payload(result)
    # One image per configured provider regardless of n.
    assert len(payload["files"]) == 2
    assert a.calls[0]["n"] == 1
    assert b.calls[0]["n"] == 1


@pytest.mark.unit
async def test_generate_visual_named_unconfigured_provider_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeProvider(configured=False)
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "x", "provider": "fake"},
    )
    assert "error" in _payload(result)


@pytest.mark.unit
async def test_handle_tool_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await mod.handle_tool("creative_studio_nope", {})
