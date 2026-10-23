"""Shared base for the Creative Studio image providers (#879).

The :class:`ImageProvider` protocol, :class:`NotSupportedError`, and the
helpers the built-in providers share (secret lookup, size capabilities,
redacted errors). They live here, below both the package ``__init__`` (the
registry, which instantiates the built-ins) and the four provider modules
(which use these names), so the registry can import the providers at top
level without the providers importing the half-initialised package back.

:mod:`mureo.creative_studio.providers` re-exports the public names, which
stays the import path for everything outside the package.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from mureo.core.runtime_context import get_runtime_context

#: Credential-store section holding every Creative Studio provider key.
CREATIVE_STUDIO_SECTION = "creative_studio"

#: Maps a credential field to its environment-variable fallback name.
_FIELD_TO_ENV: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "fal_key": "FAL_KEY",
}

#: GPT Image's exact output-size menu, ordered square, landscape, portrait.
#: Single source of truth for both providers that drive that model — the
#: hosted OpenAI ``gpt-image-1`` adapter and the local Codex CLI one — so the
#: sizes they advertise and the sizes they clamp to can never drift apart.
#: Note there is no 1536x1536 square: see ``max_size`` in
#: :meth:`ImageProvider.capabilities`.
_GPT_IMAGE_SIZES: tuple[tuple[int, int], ...] = (
    (1024, 1024),
    (1536, 1024),
    (1024, 1536),
)


class NotSupportedError(Exception):
    """Raised when a provider does not implement an optional capability.

    The canonical case is a provider without an ``edit`` path (e.g. fal):
    :meth:`ImageProvider.edit` raises this rather than silently degrading.
    """


@runtime_checkable
class ImageProvider(Protocol):
    """Adapter over a hosted image-generation API.

    Attributes:
        name: Stable short identifier (``"openai"``, ``"google"``, ``"fal"``).
        models: Model identifiers the provider generates with.
    """

    name: str
    models: tuple[str, ...]

    def is_configured(self) -> bool:
        """Return ``True`` when an API key is present (store or env var)."""
        ...

    def capabilities(self) -> dict[str, Any]:
        """Return ``{"edit": bool, "max_size": [width, height], ...}``.

        ``max_size`` is the **per-axis maximum** — the largest width and the
        largest height the provider can produce — NOT a jointly achievable
        size: a provider may max out at 1536 on each axis while offering no
        1536x1536 square. It is a bound, never a menu.

        ``supported_sizes`` is optional and, when present, is the exact menu:
        a list of ``[width, height]`` pairs the provider actually renders,
        every other request being clamped to one of them. Its absence means
        the provider takes arbitrary sizes up to ``max_size`` rather than a
        fixed menu. Consumers needing exact sizes MUST read
        ``supported_sizes`` and must not infer one from ``max_size``.

        Providers may add further honest keys (the Codex CLI one reports
        ``requires_api_key`` / ``auth``); consumers ignore unknown keys.
        """
        ...

    async def generate(
        self, prompt: str, *, width: int, height: int, n: int = 1
    ) -> list[bytes]:
        """Generate ``n`` images and return their raw bytes."""
        ...

    async def edit(self, image: bytes, instruction: str) -> bytes:
        """Edit ``image`` per ``instruction``; raise :class:`NotSupportedError`
        when the provider has no edit path."""
        ...


# ---------------------------------------------------------------------------
# Capability helpers (shared by the built-in providers)
# ---------------------------------------------------------------------------


def _size_capabilities(sizes: tuple[tuple[int, int], ...]) -> dict[str, Any]:
    """Return the ``supported_sizes`` / ``max_size`` pair for a discrete menu.

    ``max_size`` is derived as the per-axis maximum across ``sizes``, matching
    the contract documented on :meth:`ImageProvider.capabilities`. Fresh lists
    are built on every call so a caller cannot mutate a provider's constants.
    """
    return {
        "supported_sizes": [[width, height] for width, height in sizes],
        "max_size": [
            max(width for width, _ in sizes),
            max(height for _, height in sizes),
        ],
    }


# ---------------------------------------------------------------------------
# Secret access
# ---------------------------------------------------------------------------


def _creative_studio_secret(field: str) -> str | None:
    """Return the Creative Studio secret ``field``, or ``None``.

    Resolution order: the ``creative_studio`` section of the active
    ``RuntimeContext``'s secret store first, then the matching environment
    variable (so a shell-exported ``OPENAI_API_KEY`` also works). The value
    is NEVER logged.
    """
    try:
        section = get_runtime_context().secret_store.load(CREATIVE_STUDIO_SECTION)
    except Exception:  # noqa: BLE001 — a backend hiccup must not leak / crash
        section = {}
    value = section.get(field) if isinstance(section, dict) else None
    if isinstance(value, str) and value:
        return value

    env_name = _FIELD_TO_ENV.get(field)
    if env_name:
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value
    return None


# ---------------------------------------------------------------------------
# Error redaction (shared by the built-in providers)
# ---------------------------------------------------------------------------


def _redact(text: str, secret: str | None) -> str:
    """Replace ``secret`` with ``"***"`` in ``text`` (no-op when falsy)."""
    if secret:
        return text.replace(secret, "***")
    return text


def provider_error(
    provider: str, exc: BaseException, secret: str | None
) -> RuntimeError:
    """Build a redacted :class:`RuntimeError` describing a provider failure.

    Includes the HTTP status and response body when available (both scrubbed
    of ``secret``) but never the request's ``Authorization`` header — only the
    response body / exception string are surfaced, and the key is redacted from
    both (the Gemini API carries the key in the URL query string, so redaction
    is load-bearing there).
    """
    status: int | None = None
    body = ""
    response = getattr(exc, "response", None)
    if response is not None:
        status = getattr(response, "status_code", None)
        try:
            body = getattr(response, "text", "") or ""
        except Exception:  # noqa: BLE001 — reading the body must not re-raise
            body = ""
    detail = _redact(body or str(exc), secret)
    if status is not None:
        return RuntimeError(f"{provider} image API error (HTTP {status}): {detail}")
    return RuntimeError(f"{provider} image API error: {detail}")


__all__ = [
    "CREATIVE_STUDIO_SECTION",
    "ImageProvider",
    "NotSupportedError",
    "provider_error",
]
