"""Image-provider abstraction + registry for Creative Studio.

An :class:`ImageProvider` is a thin, swappable adapter over a hosted
image-generation API. mureo ships three built-ins (OpenAI, Google Gemini,
fal.ai); third parties can register more under the
``mureo.image_providers`` entry-point group. Discovery is fault-isolated —
a broken plugin is skipped with an :class:`ImageProviderWarning`, never
breaking the built-ins.

Provider secrets live in the ``creative_studio`` section of the credential
store (``OPENAI_API_KEY`` / ``GEMINI_API_KEY`` / ``FAL_KEY`` also work as
environment-variable fallbacks). Keys are read via
:func:`_creative_studio_secret` and are NEVER logged.
"""

from __future__ import annotations

import inspect
import os
import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from mureo.core.runtime_context import get_runtime_context

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: Entry-point group third-party image providers register under.
IMAGE_PROVIDERS_ENTRY_POINT_GROUP = "mureo.image_providers"

#: Credential-store section holding every Creative Studio provider key.
CREATIVE_STUDIO_SECTION = "creative_studio"

#: Maps a credential field to its environment-variable fallback name.
_FIELD_TO_ENV: dict[str, str] = {
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "fal_key": "FAL_KEY",
}


class NotSupportedError(Exception):
    """Raised when a provider does not implement an optional capability.

    The canonical case is a provider without an ``edit`` path (e.g. fal):
    :meth:`ImageProvider.edit` raises this rather than silently degrading.
    """


class ImageProviderWarning(UserWarning):
    """Emitted when an image-provider entry point is skipped during discovery.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=ImageProviderWarning)``.
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
        """Return ``{"edit": bool, "max_size": [width, height]}``."""
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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _builtin_providers() -> list[ImageProvider]:
    """Instantiate the built-in providers (import-local to avoid cycles)."""
    from mureo.creative_studio.providers.fal import FalImageProvider
    from mureo.creative_studio.providers.google_images import GoogleImageProvider
    from mureo.creative_studio.providers.openai_images import OpenAIImageProvider

    return [OpenAIImageProvider(), GoogleImageProvider(), FalImageProvider()]


def _is_valid_provider(instance: object) -> bool:
    """Return ``True`` when ``instance`` has the structural provider shape."""
    name = getattr(instance, "name", None)
    if not isinstance(name, str) or not name:
        return False
    if not isinstance(getattr(instance, "models", None), tuple):
        return False
    for method in ("is_configured", "capabilities", "generate", "edit"):
        if not callable(getattr(instance, method, None)):
            return False
    return True


def _load_one(ep: Any) -> ImageProvider | None:
    """Load → instantiate → validate one entry point, fault-isolated."""
    ep_name = getattr(ep, "name", "<unknown>")
    try:
        loaded = ep.load()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
        warnings.warn(
            f"image provider {ep_name!r}: load failed; skipped ({exc!r})",
            ImageProviderWarning,
            stacklevel=3,
        )
        return None

    try:
        instance = loaded() if inspect.isclass(loaded) else loaded
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
        warnings.warn(
            f"image provider {ep_name!r}: not instantiable; skipped ({exc!r})",
            ImageProviderWarning,
            stacklevel=3,
        )
        return None

    if not _is_valid_provider(instance):
        warnings.warn(
            f"image provider {ep_name!r}: invalid provider shape; skipped",
            ImageProviderWarning,
            stacklevel=3,
        )
        return None
    return cast("ImageProvider", instance)


def _discover_plugin_providers(
    loader: Callable[..., Iterable[Any]] | None = None,
) -> list[ImageProvider]:
    """Discover providers from the entry-point group, fault-isolated.

    A failure enumerating the group, or loading any single plugin, is
    contained with an :class:`ImageProviderWarning`; the built-ins are never
    affected.
    """
    load = loader or entry_points
    try:
        eps = tuple(load(group=IMAGE_PROVIDERS_ENTRY_POINT_GROUP))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — discovery must not crash
        warnings.warn(
            f"image-provider discovery failed; no plugin providers loaded: {exc!r}",
            ImageProviderWarning,
            stacklevel=2,
        )
        return []

    providers: list[ImageProvider] = []
    for ep in eps:
        provider = _load_one(ep)
        if provider is not None:
            providers.append(provider)
    return providers


def available_providers(
    loader: Callable[..., Iterable[Any]] | None = None,
) -> list[ImageProvider]:
    """Return every usable provider — built-ins first, then plugins.

    First-wins name dedupe: a built-in always wins over a plugin claiming the
    same ``name``, and the first-discovered plugin wins over later duplicates.

    Args:
        loader: Injectable replacement for
            :func:`importlib.metadata.entry_points` (tests / advanced use).
    """
    providers: list[ImageProvider] = []
    seen: set[str] = set()
    for provider in _builtin_providers():
        if provider.name not in seen:
            seen.add(provider.name)
            providers.append(provider)
    for provider in _discover_plugin_providers(loader):
        if provider.name not in seen:
            seen.add(provider.name)
            providers.append(provider)
    return providers


__all__ = [
    "CREATIVE_STUDIO_SECTION",
    "IMAGE_PROVIDERS_ENTRY_POINT_GROUP",
    "ImageProvider",
    "ImageProviderWarning",
    "NotSupportedError",
    "available_providers",
    "provider_error",
]
