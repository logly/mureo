"""Image-provider abstraction + registry for Creative Studio.

An :class:`ImageProvider` is a thin, swappable adapter over an
image-generation backend. mureo ships four built-ins: three hosted-API
providers (OpenAI, Google Gemini, fal.ai) plus a local Codex CLI provider
that needs no API key (only ``codex login``); third parties can register
more under the ``mureo.image_providers`` entry-point group. Discovery is
fault-isolated — a broken plugin is skipped with an
:class:`ImageProviderWarning`, never breaking the built-ins.

Hosted-provider secrets live in the ``creative_studio`` section of the
credential store (``OPENAI_API_KEY`` / ``GEMINI_API_KEY`` / ``FAL_KEY`` also
work as environment-variable fallbacks). Keys are read via
:func:`._base._creative_studio_secret` and are NEVER logged. The Codex CLI provider
has no secret — auth is the user's local ``codex login``.
"""

from __future__ import annotations

import inspect
import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, cast

from mureo.creative_studio.providers._base import (
    CREATIVE_STUDIO_SECTION,
    ImageProvider,
    NotSupportedError,
    provider_error,
)
from mureo.creative_studio.providers.codex_cli import CodexCliImageProvider
from mureo.creative_studio.providers.fal import FalImageProvider
from mureo.creative_studio.providers.google_images import GoogleImageProvider
from mureo.creative_studio.providers.openai_images import OpenAIImageProvider

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: Entry-point group third-party image providers register under.
IMAGE_PROVIDERS_ENTRY_POINT_GROUP = "mureo.image_providers"


class ImageProviderWarning(UserWarning):
    """Emitted when an image-provider entry point is skipped during discovery.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=ImageProviderWarning)``.
    """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def _builtin_providers() -> list[ImageProvider]:
    """Instantiate the built-in providers."""
    return [
        OpenAIImageProvider(),
        GoogleImageProvider(),
        FalImageProvider(),
        CodexCliImageProvider(),
    ]


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
