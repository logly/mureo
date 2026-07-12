"""Google Gemini image provider (``gemini-2.5-flash-image``, generate + edit).

Talks directly to the fixed Gemini ``generateContent`` REST endpoint via
``httpx`` — no vendor SDK. The API key is passed as the ``key`` query
parameter (Gemini's convention), so it appears in the request URL; error
redaction therefore scrubs the key from any surfaced message. The key is
read from the ``gemini_api_key`` field (env fallback ``GEMINI_API_KEY``).

The Gemini image model does not take an explicit output size, so the
``width``/``height`` arguments are accepted for interface parity but not
forwarded. Multiple images (``n``) are produced by ``n`` sequential calls.
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

_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-image:generateContent"
)
_MODEL = "gemini-2.5-flash-image"
_KEY_FIELD = "gemini_api_key"
_TIMEOUT = 60.0


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


class GoogleImageProvider:
    """Image provider backed by the Gemini image API."""

    name = "google"
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
        return {"edit": True, "max_size": [1024, 1024]}

    def _require_key(self) -> str:
        key = _creative_studio_secret(_KEY_FIELD)
        if not key:
            raise RuntimeError(
                "google provider is not configured: set the 'gemini_api_key' "
                "creative_studio credential or the GEMINI_API_KEY env var"
            )
        return key

    def _extract_image(self, payload: dict[str, Any]) -> bytes:
        for candidate in payload.get("candidates", []):
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return base64.b64decode(inline["data"])
        raise RuntimeError(f"{self.name} response contained no image data")

    async def _generate_one(
        self, client: httpx.AsyncClient, prompt: str, key: str
    ) -> bytes:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        try:
            resp = await client.post(_URL, params={"key": key}, json=body)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 — normalize + redact
            raise provider_error(self.name, exc, key) from exc
        return self._extract_image(payload)

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        key = self._require_key()
        async with self._client_factory() as client:
            return [await self._generate_one(client, prompt, key) for _ in range(n)]

    async def edit(self, image: bytes, instruction: str) -> bytes:
        key = self._require_key()
        encoded = base64.b64encode(image).decode("ascii")
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": instruction},
                        {
                            "inline_data": {
                                "mimeType": "image/png",
                                "data": encoded,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        async with self._client_factory() as client:
            try:
                resp = await client.post(_URL, params={"key": key}, json=body)
                resp.raise_for_status()
                payload = resp.json()
            except Exception as exc:  # noqa: BLE001 — normalize + redact
                raise provider_error(self.name, exc, key) from exc
        return self._extract_image(payload)


#: Exposed for the shared provider test-suite.
PROVIDER_CLASS = GoogleImageProvider
