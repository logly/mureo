"""OpenAI ``gpt-image-1`` image provider (generate + edit).

Talks directly to the fixed OpenAI REST endpoints via ``httpx`` — no vendor
SDK. The endpoints are hard-coded vendor hosts, so there is no
caller-supplied URL surface (no new SSRF surface). The API key is read from the
``openai_api_key`` field (env fallback ``OPENAI_API_KEY``) and is redacted
from any error surfaced to the caller.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import httpx

from mureo.creative_studio.providers import (
    _creative_studio_secret,
    provider_error,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_GENERATE_URL = "https://api.openai.com/v1/images/generations"
_EDIT_URL = "https://api.openai.com/v1/images/edits"
_MODEL = "gpt-image-1"
_KEY_FIELD = "openai_api_key"
_TIMEOUT = 60.0

# Sizes gpt-image-1 supports, one per aspect class. A requested width/height
# is clamped to the nearest of these by orientation.
_SIZE_SQUARE = "1024x1024"
_SIZE_LANDSCAPE = "1536x1024"
_SIZE_PORTRAIT = "1024x1536"


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


class OpenAIImageProvider:
    """Image provider backed by the OpenAI Images API."""

    name = "openai"
    models: tuple[str, ...] = (_MODEL,)

    def __init__(
        self,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory

    def is_configured(self) -> bool:
        return _creative_studio_secret(_KEY_FIELD) is not None

    def capabilities(self) -> dict[str, Any]:
        return {"edit": True, "max_size": [1536, 1536]}

    @staticmethod
    def _clamp_size(width: int, height: int) -> str:
        """Clamp an arbitrary ``width``/``height`` to the nearest supported
        aspect. Square when equal, else landscape/portrait by orientation."""
        if width == height:
            return _SIZE_SQUARE
        return _SIZE_LANDSCAPE if width > height else _SIZE_PORTRAIT

    def _require_key(self) -> str:
        key = _creative_studio_secret(_KEY_FIELD)
        if not key:
            raise RuntimeError(
                "openai provider is not configured: set the 'openai_api_key' "
                "creative_studio credential or the OPENAI_API_KEY env var"
            )
        return key

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        key = self._require_key()
        payload = {
            "model": _MODEL,
            "prompt": prompt,
            "n": n,
            "size": self._clamp_size(width, height),
            "quality": "high",
        }
        headers = {"Authorization": f"Bearer {key}"}
        async with self._client_factory() as client:
            try:
                resp = await client.post(_GENERATE_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001 — normalize + redact
                raise provider_error(self.name, exc, key) from exc
        return [base64.b64decode(item["b64_json"]) for item in data.get("data", [])]

    async def edit(self, image: bytes, instruction: str) -> bytes:
        key = self._require_key()
        headers = {"Authorization": f"Bearer {key}"}
        files = {"image": ("image.png", image, "image/png")}
        form = {"model": _MODEL, "prompt": instruction}
        async with self._client_factory() as client:
            try:
                resp = await client.post(
                    _EDIT_URL, headers=headers, data=form, files=files
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001 — normalize + redact
                raise provider_error(self.name, exc, key) from exc
        return base64.b64decode(data["data"][0]["b64_json"])


#: Exposed so the shared provider test-suite can instantiate without knowing
#: the concrete class name.
PROVIDER_CLASS = OpenAIImageProvider
