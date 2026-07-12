"""fal.ai FLUX image provider (generate only).

Talks directly to the fixed fal.ai ``fal-ai/flux-pro/v1.1`` endpoint via
``httpx`` — no vendor SDK. fal returns image *URLs* rather than inline
bytes, so each result is downloaded; to keep the download surface closed,
a result URL is fetched ONLY when its host is on a fixed allow-list
(``fal.media`` / ``fal.run`` and their subdomains). Any other host is
rejected, so a manipulated response cannot turn the download into an SSRF.

The key is read from the ``fal_key`` field (env fallback ``FAL_KEY``) and
sent as ``Authorization: Key <FAL_KEY>``. fal exposes no edit path, so
:meth:`edit` raises :class:`NotSupportedError`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from mureo.creative_studio.providers import (
    NotSupportedError,
    _creative_studio_secret,
    provider_error,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_URL = "https://fal.run/fal-ai/flux-pro/v1.1"
_MODEL = "fal-ai/flux-pro/v1.1"
_KEY_FIELD = "fal_key"
_TIMEOUT = 60.0

# Fixed allow-list of hosts a returned image URL may be downloaded from.
_ALLOWED_HOSTS: tuple[str, ...] = ("fal.media", "fal.run")


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT)


def _host_allowed(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower()
    return any(
        host == allowed or host.endswith("." + allowed) for allowed in _ALLOWED_HOSTS
    )


class FalImageProvider:
    """Image provider backed by fal.ai FLUX Pro."""

    name = "fal"
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
        return {"edit": False, "max_size": [1440, 1440]}

    def _require_key(self) -> str:
        key = _creative_studio_secret(_KEY_FIELD)
        if not key:
            raise RuntimeError(
                "fal provider is not configured: set the 'fal_key' "
                "creative_studio credential or the FAL_KEY env var"
            )
        return key

    @staticmethod
    def _require_allowed_host(url: str) -> None:
        host = urlparse(url).hostname
        if not _host_allowed(host):
            raise RuntimeError(
                f"fal refused to download image from disallowed host {host!r}"
            )

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        key = self._require_key()
        headers = {"Authorization": f"Key {key}"}
        payload = {
            "prompt": prompt,
            "image_size": {"width": width, "height": height},
            "num_images": n,
        }
        async with self._client_factory() as client:
            try:
                resp = await client.post(_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001 — normalize + redact
                raise provider_error(self.name, exc, key) from exc

            results: list[bytes] = []
            for item in data.get("images", []):
                url = item.get("url")
                if not url:
                    continue
                # Fixed-host allow-list: reject before any fetch is attempted.
                self._require_allowed_host(url)
                try:
                    img_resp = await client.get(url)
                    img_resp.raise_for_status()
                except Exception as exc:  # noqa: BLE001 — normalize + redact
                    raise provider_error(self.name, exc, key) from exc
                results.append(img_resp.content)
        return results

    async def edit(self, image: bytes, instruction: str) -> bytes:
        raise NotSupportedError("fal provider does not support image editing")


#: Exposed for the shared provider test-suite.
PROVIDER_CLASS = FalImageProvider
