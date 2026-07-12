"""Unit tests for the Creative Studio built-in image providers.

All tests are hermetic: no real network calls are made. Each provider
takes an injectable ``client_factory`` so an :class:`httpx.MockTransport`
can stub every HTTP round-trip. Secret resolution is patched per-module
(``_creative_studio_secret``) so no credentials file is touched.
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Callable

import mureo.creative_studio.providers as registry
from mureo.creative_studio.providers import (
    ImageProvider,
    NotSupportedError,
    available_providers,
)
from mureo.creative_studio.providers import fal as fal_mod
from mureo.creative_studio.providers import google_images as google_mod
from mureo.creative_studio.providers import openai_images as openai_mod

# A tiny fake PNG payload (validation only checks extension/size, not magic).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n fake image bytes"
_B64_PNG = base64.b64encode(_PNG_BYTES).decode("ascii")


def _client_factory(handler: Callable[[httpx.Request], httpx.Response]):
    """Return a factory producing an AsyncClient backed by a MockTransport."""
    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, timeout=60.0)

    return factory


# ---------------------------------------------------------------------------
# Protocol conformance + registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_builtin_providers_conform_to_protocol() -> None:
    providers = available_providers()
    names = {p.name for p in providers}
    assert {"openai", "google", "fal"}.issubset(names)
    for provider in providers:
        assert isinstance(provider, ImageProvider)
        assert isinstance(provider.name, str) and provider.name
        assert isinstance(provider.models, tuple)
        caps = provider.capabilities()
        assert "edit" in caps and "max_size" in caps
        assert isinstance(caps["max_size"], list) and len(caps["max_size"]) == 2


@pytest.mark.unit
def test_available_providers_first_wins_dedupe() -> None:
    # No duplicate names among built-ins.
    names = [p.name for p in available_providers()]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_secret_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_store = type("S", (), {"load": lambda self, key: {}})()
    fake_ctx = type("C", (), {"secret_store": fake_store})()
    monkeypatch.setattr(registry, "get_runtime_context", lambda: fake_ctx)

    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-abc")
    assert registry._creative_studio_secret("openai_api_key") == "env-openai-abc"

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert registry._creative_studio_secret("openai_api_key") is None


@pytest.mark.unit
def test_secret_store_takes_precedence_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_store = type("S", (), {"load": lambda self, key: {"fal_key": "store-value"}})()
    fake_ctx = type("C", (), {"secret_store": fake_store})()
    monkeypatch.setattr(registry, "get_runtime_context", lambda: fake_ctx)
    monkeypatch.setenv("FAL_KEY", "env-value")
    assert registry._creative_studio_secret("fal_key") == "store-value"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module", "field"),
    [
        (openai_mod, "openai_api_key"),
        (google_mod, "gemini_api_key"),
        (fal_mod, "fal_key"),
    ],
)
def test_is_configured_false_without_key(
    monkeypatch: pytest.MonkeyPatch, module: object, field: str
) -> None:
    monkeypatch.setattr(module, "_creative_studio_secret", lambda _field: None)
    provider = module.PROVIDER_CLASS()
    assert provider.is_configured() is False


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_openai_generate_decodes_b64(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_mod, "_creative_studio_secret", lambda _f: "sk-test-KEY")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": _B64_PNG}]})

    provider = openai_mod.OpenAIImageProvider(client_factory=_client_factory(handler))
    images = await provider.generate("a cat", width=1024, height=1024, n=1)

    assert images == [_PNG_BYTES]
    assert captured["auth"] == "Bearer sk-test-KEY"
    assert captured["body"]["size"] == "1024x1024"
    assert captured["body"]["model"] == "gpt-image-1"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1024, 1024, "1024x1024"),
        (1920, 1080, "1536x1024"),
        (1080, 1920, "1024x1536"),
        (2000, 500, "1536x1024"),
    ],
)
async def test_openai_clamps_size_to_nearest_aspect(
    monkeypatch: pytest.MonkeyPatch, width: int, height: int, expected: str
) -> None:
    monkeypatch.setattr(openai_mod, "_creative_studio_secret", lambda _f: "sk-KEY")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["size"] = json.loads(request.content)["size"]
        return httpx.Response(200, json={"data": [{"b64_json": _B64_PNG}]})

    provider = openai_mod.OpenAIImageProvider(client_factory=_client_factory(handler))
    await provider.generate("x", width=width, height=height, n=1)
    assert seen["size"] == expected


@pytest.mark.unit
async def test_openai_edit_returns_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_mod, "_creative_studio_secret", lambda _f: "sk-KEY")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/images/edits"
        return httpx.Response(200, json={"data": [{"b64_json": _B64_PNG}]})

    provider = openai_mod.OpenAIImageProvider(client_factory=_client_factory(handler))
    out = await provider.edit(_PNG_BYTES, "brighten it")
    assert out == _PNG_BYTES


@pytest.mark.unit
async def test_openai_error_redacts_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "sk-SUPER-SECRET-123"
    monkeypatch.setattr(openai_mod, "_creative_studio_secret", lambda _f: key)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": f"bad token {key}"}})

    provider = openai_mod.OpenAIImageProvider(client_factory=_client_factory(handler))
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    text = str(excinfo.value)
    assert key not in text
    assert "***" in text
    assert "openai" in text
    assert "400" in text


# ---------------------------------------------------------------------------
# Google (Gemini) provider
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_google_generate_parses_inline_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(google_mod, "_creative_studio_secret", lambda _f: "gm-KEY")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"inlineData": {"data": _B64_PNG}}]}}
                ]
            },
        )

    provider = google_mod.GoogleImageProvider(client_factory=_client_factory(handler))
    images = await provider.generate("a dog", width=1024, height=1024, n=2)

    assert images == [_PNG_BYTES, _PNG_BYTES]
    assert len(calls) == 2  # n sequential calls
    assert "key=gm-KEY" in calls[0]


@pytest.mark.unit
async def test_google_error_redacts_key_in_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "gm-SECRET-XYZ"
    monkeypatch.setattr(google_mod, "_creative_studio_secret", lambda _f: key)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="permission denied")

    provider = google_mod.GoogleImageProvider(client_factory=_client_factory(handler))
    with pytest.raises(RuntimeError) as excinfo:
        await provider.generate("x", width=1024, height=1024, n=1)
    assert key not in str(excinfo.value)


# ---------------------------------------------------------------------------
# fal provider
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fal_capabilities_edit_false() -> None:
    assert fal_mod.FalImageProvider().capabilities()["edit"] is False


@pytest.mark.unit
async def test_fal_edit_raises_not_supported() -> None:
    provider = fal_mod.FalImageProvider()
    with pytest.raises(NotSupportedError):
        await provider.edit(b"data", "make it pop")


@pytest.mark.unit
async def test_fal_downloads_from_allowed_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fal_mod, "_creative_studio_secret", lambda _f: "fal-KEY")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fal.run":
            assert request.headers.get("authorization") == "Key fal-KEY"
            return httpx.Response(
                200,
                json={"images": [{"url": "https://v3.fal.media/files/x/out.png"}]},
            )
        if request.url.host.endswith("fal.media"):
            return httpx.Response(200, content=_PNG_BYTES)
        return httpx.Response(404)

    provider = fal_mod.FalImageProvider(client_factory=_client_factory(handler))
    images = await provider.generate("a bird", width=1080, height=1080, n=1)
    assert images == [_PNG_BYTES]


@pytest.mark.unit
async def test_fal_rejects_non_allowlisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fal_mod, "_creative_studio_secret", lambda _f: "fal-KEY")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fal.run":
            return httpx.Response(
                200, json={"images": [{"url": "https://evil.example/out.png"}]}
            )
        # Would succeed if the guard were bypassed — proves the guard blocks it.
        return httpx.Response(200, content=_PNG_BYTES)

    provider = fal_mod.FalImageProvider(client_factory=_client_factory(handler))
    with pytest.raises(RuntimeError):
        await provider.generate("x", width=1080, height=1080, n=1)


@pytest.mark.unit
async def test_fal_rejects_lookalike_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fal_mod, "_creative_studio_secret", lambda _f: "fal-KEY")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fal.run":
            return httpx.Response(
                200, json={"images": [{"url": "https://notfal.media/out.png"}]}
            )
        return httpx.Response(200, content=_PNG_BYTES)

    provider = fal_mod.FalImageProvider(client_factory=_client_factory(handler))
    with pytest.raises(RuntimeError):
        await provider.generate("x", width=1080, height=1080, n=1)


# ---------------------------------------------------------------------------
# Entry-point discovery fault isolation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_discovery_fault_isolation_keeps_builtins() -> None:
    class _BoomEP:
        name = "boom"
        dist = None

        def load(self) -> object:
            raise RuntimeError("plugin broke on load")

    def fake_entry_points(*, group: str) -> list[object]:
        assert group == "mureo.image_providers"
        return [_BoomEP()]

    with pytest.warns(registry.ImageProviderWarning):
        providers = available_providers(loader=fake_entry_points)

    names = {p.name for p in providers}
    assert {"openai", "google", "fal"}.issubset(names)


@pytest.mark.unit
def test_discovery_registers_valid_plugin() -> None:
    class _PluginProvider:
        name = "plugin_x"
        models = ("px-1",)

        def is_configured(self) -> bool:
            return True

        def capabilities(self) -> dict:
            return {"edit": False, "max_size": [512, 512]}

        async def generate(
            self, prompt: str, *, width: int, height: int, n: int = 1
        ) -> list[bytes]:
            return [b"x"]

        async def edit(self, image: bytes, instruction: str) -> bytes:
            raise NotSupportedError()

    class _EP:
        name = "plugin_x"
        dist = None

        def load(self) -> object:
            return _PluginProvider

    def fake_entry_points(*, group: str) -> list[object]:
        return [_EP()]

    providers = available_providers(loader=fake_entry_points)
    assert "plugin_x" in {p.name for p in providers}
