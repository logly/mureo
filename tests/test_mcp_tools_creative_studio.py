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
        "creative_studio_brand_kit_get",
        "creative_studio_edit_visual",
        "creative_studio_compose",
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
    # Template-aware negative space: enum of the three layout ids, NO default
    # (unknown/None stays backward compatible).
    assert set(props["template"]["enum"]) == set(mod.composer.TEMPLATES)
    assert "default" not in props["template"]
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


@pytest.mark.unit
def test_template_negative_space_covers_every_template() -> None:
    """Every composer template must map to one guidance sentence."""
    assert set(mod.TEMPLATE_NEGATIVE_SPACE) == set(mod.composer.TEMPLATES)
    for sentence in mod.TEMPLATE_NEGATIVE_SPACE.values():
        assert sentence and sentence == sentence.strip()


@pytest.mark.unit
def test_build_visual_prompt_hero_overlay_injects_lower_third() -> None:
    out = mod.build_visual_prompt("a cat on a sofa", "hero_overlay")
    lowered = out.lower()
    # User prompt, then the negative-space sentence, then the no-text constraint.
    assert "a cat on a sofa" in out
    assert "lower third visually calm and uncluttered" in out
    assert out.index("a cat on a sofa") < out.index("lower third")
    # Compare within one string so the ordering assertion is robust.
    assert lowered.index("lower third") < lowered.index("no text")


@pytest.mark.unit
def test_build_visual_prompt_split_injects_half_frame() -> None:
    out = mod.build_visual_prompt("a product", "split")
    assert "cropped to one half of the frame" in out
    assert "clean edges" in out


@pytest.mark.unit
def test_build_visual_prompt_minimal_badge_injects_center_weight() -> None:
    out = mod.build_visual_prompt("a texture", "minimal_badge")
    assert "Center-weighted subject" in out
    assert "centered card overlay" in out


@pytest.mark.unit
def test_build_visual_prompt_none_template_is_backward_compatible() -> None:
    assert mod.build_visual_prompt("a cat", None) == mod.build_visual_prompt("a cat")


@pytest.mark.unit
def test_build_visual_prompt_unknown_template_adds_nothing() -> None:
    assert mod.build_visual_prompt("a cat", "bogus") == mod.build_visual_prompt("a cat")


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
async def test_generate_visual_passes_template_negative_space_and_records_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeProvider(images=[b"IMG"])
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)

    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "a cat", "template": "hero_overlay", "n": 1},
    )
    payload = _payload(result)
    assert "error" not in payload

    # The fake provider saw the template negative-space sentence in the prompt.
    prompt_seen = str(fake.calls[0]["prompt"])
    assert "lower third visually calm and uncluttered" in prompt_seen
    assert "no text" in prompt_seen.lower()

    # The chosen template is recorded in the run manifest.
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["template"] == "hero_overlay"


@pytest.mark.unit
async def test_generate_visual_manifest_records_template_none_when_omitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeProvider(images=[b"IMG"])
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)

    result = await mod.handle_tool(
        "creative_studio_generate_visual", {"prompt": "a cat", "n": 1}
    )
    payload = _payload(result)
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["template"] is None
    # No negative-space sentence leaked into the prompt.
    assert "lower third" not in str(fake.calls[0]["prompt"])


@pytest.mark.unit
async def test_generate_visual_unknown_template_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An out-of-enum template is rejected at the boundary (the schema enum is
    advisory only) so the manifest never claims a template that did nothing."""
    fake = _FakeProvider(images=[b"IMG"])
    monkeypatch.setattr(mod, "available_providers", lambda: [fake])
    monkeypatch.chdir(tmp_path)

    result = await mod.handle_tool(
        "creative_studio_generate_visual",
        {"prompt": "a cat", "template": "bogus", "n": 1},
    )
    payload = _payload(result)
    assert "error" in payload
    assert "bogus" in payload["error"]
    # No provider call happened — we failed fast on bad input.
    assert fake.calls == []


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


# ---------------------------------------------------------------------------
# PR-B: schemas for the composer / brand-kit / edit tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_compose_schema_constraints() -> None:
    tool = next(t for t in mod.TOOLS if t.name == "creative_studio_compose")
    props = tool.inputSchema["properties"]
    assert props["visual_path"]["type"] == "string"
    assert props["headline"]["minLength"] == 1
    assert props["cta"]["type"] == "string"
    assert set(props["template"]["enum"]) == set(mod.composer.TEMPLATES)
    assert props["template"]["default"] == "hero_overlay"
    assert props["formats"]["type"] == "array"
    assert props["formats"]["default"] == ["meta_feed_1x1"]
    assert props["formats"]["uniqueItems"] is True
    assert set(tool.inputSchema["required"]) == {"visual_path", "headline", "cta"}


@pytest.mark.unit
def test_edit_visual_schema_constraints() -> None:
    tool = next(t for t in mod.TOOLS if t.name == "creative_studio_edit_visual")
    props = tool.inputSchema["properties"]
    assert props["path"]["type"] == "string"
    assert props["instruction"]["minLength"] == 1
    assert "provider" in props
    assert set(tool.inputSchema["required"]) == {"path", "instruction"}


@pytest.mark.unit
def test_brand_kit_get_schema_takes_no_args() -> None:
    tool = next(t for t in mod.TOOLS if t.name == "creative_studio_brand_kit_get")
    assert tool.inputSchema.get("properties", {}) == {}


# ---------------------------------------------------------------------------
# brand_kit_get handler
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_brand_kit_get_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    result = await mod.handle_tool("creative_studio_brand_kit_get", {})
    payload = _payload(result)
    assert set(payload["colors"]) >= {
        "primary",
        "secondary",
        "accent",
        "text",
        "background",
    }
    assert set(payload["fonts"]) == {"heading", "body"}
    assert payload["logo"] is None
    assert payload["defaults_used"] is True


# ---------------------------------------------------------------------------
# compose handler (fake composer — no Playwright)
# ---------------------------------------------------------------------------


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
            {
                "format": fid,
                "path": str(p),
                "sha256": "deadbeef",
                "width": 1,
                "height": 1,
            }
        )
    return files


@pytest.mark.unit
async def test_compose_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.composer, "compose", _fake_compose)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG raw visual")

    result = await mod.handle_tool(
        "creative_studio_compose",
        {
            "visual_path": str(visual),
            "headline": "H",
            "cta": "C",
            "body": "B",
            "template": "split",
            "formats": ["meta_feed_1x1", "gdn_300x250"],
        },
    )
    payload = _payload(result)
    assert "run_id" in payload
    assert Path(payload["run_dir"]).is_dir()
    assert len(payload["files"]) == 2
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8"))
    assert manifest["kind"] == "compose"
    assert manifest["template"] == "split"
    assert manifest["copy"]["headline"] == "H"
    assert manifest["inputs"]["visual_sha256"]
    assert len(manifest["files"]) == 2


@pytest.mark.unit
async def test_compose_dedupes_duplicate_formats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    recorded_formats: list[list[str]] = []

    async def _recording_compose(
        visual_path: Path,
        copy: object,
        template: str,
        formats: list[str],
        brand: object,
        out_dir: Path,
        **_kwargs: object,
    ) -> list[dict]:
        recorded_formats.append(list(formats))
        files = []
        for fid in formats:
            p = Path(out_dir) / f"{fid}_{template}.png"
            p.write_bytes(b"\x89PNG composed")
            files.append(
                {
                    "format": fid,
                    "path": str(p),
                    "sha256": "deadbeef",
                    "width": 1,
                    "height": 1,
                }
            )
        return files

    monkeypatch.setattr(mod.composer, "compose", _recording_compose)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG raw visual")

    result = await mod.handle_tool(
        "creative_studio_compose",
        {
            "visual_path": str(visual),
            "headline": "H",
            "cta": "C",
            "formats": ["meta_feed_1x1", "meta_feed_1x1", "gdn_300x250"],
        },
    )
    payload = _payload(result)
    assert "error" not in payload
    # compose was invoked exactly once, with duplicates removed (order kept).
    assert len(recorded_formats) == 1
    assert recorded_formats[0] == ["meta_feed_1x1", "gdn_300x250"]
    assert len(payload["files"]) == 2


@pytest.mark.unit
async def test_compose_unknown_format_lists_valid_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.composer, "compose", _fake_compose)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG raw visual")

    result = await mod.handle_tool(
        "creative_studio_compose",
        {"visual_path": str(visual), "headline": "H", "cta": "C", "formats": ["bogus"]},
    )
    payload = _payload(result)
    assert "error" in payload
    assert "bogus" in payload["error"]
    assert "meta_feed_1x1" in payload["error"]  # valid ids are listed


@pytest.mark.unit
async def test_compose_missing_extra_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    async def _raise(*_a: object, **_k: object) -> list[dict]:
        raise RuntimeError(
            "Creative Studio composition requires the 'creative' extra: "
            "pip install 'mureo[creative]'"
        )

    monkeypatch.setattr(mod.composer, "compose", _raise)
    visual = tmp_path / "v.png"
    visual.write_bytes(b"\x89PNG raw visual")

    result = await mod.handle_tool(
        "creative_studio_compose",
        {"visual_path": str(visual), "headline": "H", "cta": "C"},
    )
    payload = _payload(result)
    assert "error" in payload
    assert "mureo[creative]" in payload["error"]


@pytest.mark.unit
async def test_compose_rejects_bad_visual_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod.composer, "compose", _fake_compose)
    bad = tmp_path / "v.txt"
    bad.write_text("not an image")
    result = await mod.handle_tool(
        "creative_studio_compose",
        {"visual_path": str(bad), "headline": "H", "cta": "C"},
    )
    assert "error" in _payload(result)


# ---------------------------------------------------------------------------
# edit_visual handler
# ---------------------------------------------------------------------------


class _EditProvider(_FakeProvider):
    """A configured, edit-capable provider that returns edited bytes."""

    def capabilities(self) -> dict:
        return {"edit": True, "max_size": [1024, 1024]}

    async def edit(self, image: bytes, instruction: str) -> bytes:
        self.calls.append({"edit": instruction})
        return b"EDITED-BYTES"


class _LyingProvider(_FakeProvider):
    """Advertises edit support but raises NotSupportedError at call time."""

    def capabilities(self) -> dict:
        return {"edit": True, "max_size": [1024, 1024]}

    async def edit(self, image: bytes, instruction: str) -> bytes:
        raise NotSupportedError("edit not actually supported")


@pytest.mark.unit
async def test_edit_visual_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    prov = _EditProvider()
    monkeypatch.setattr(mod, "available_providers", lambda: [prov])
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG original")

    result = await mod.handle_tool(
        "creative_studio_edit_visual",
        {"path": str(img), "instruction": "brighten the sky"},
    )
    payload = _payload(result)
    assert payload["provider"] == "fake"
    out = Path(payload["path"])
    assert out.exists()
    assert out.name == "pic_edit_1.png"
    assert out.read_bytes() == b"EDITED-BYTES"
    assert payload["sha256"]


@pytest.mark.unit
async def test_edit_visual_increments_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "available_providers", lambda: [_EditProvider()])
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG original")
    (tmp_path / "pic_edit_1.png").write_bytes(b"existing")

    result = await mod.handle_tool(
        "creative_studio_edit_visual",
        {"path": str(img), "instruction": "x"},
    )
    assert Path(_payload(result)["path"]).name == "pic_edit_2.png"


@pytest.mark.unit
async def test_edit_visual_no_edit_capable_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    # _FakeProvider advertises edit=False.
    monkeypatch.setattr(mod, "available_providers", lambda: [_FakeProvider()])
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG original")
    result = await mod.handle_tool(
        "creative_studio_edit_visual",
        {"path": str(img), "instruction": "x"},
    )
    assert "error" in _payload(result)


@pytest.mark.unit
async def test_edit_visual_not_supported_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "available_providers", lambda: [_LyingProvider()])
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG original")
    result = await mod.handle_tool(
        "creative_studio_edit_visual",
        {"path": str(img), "instruction": "x"},
    )
    assert "error" in _payload(result)


@pytest.mark.unit
async def test_edit_visual_rejects_bad_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "available_providers", lambda: [_EditProvider()])
    bad = tmp_path / "pic.txt"
    bad.write_text("not an image")
    result = await mod.handle_tool(
        "creative_studio_edit_visual",
        {"path": str(bad), "instruction": "x"},
    )
    assert "error" in _payload(result)
