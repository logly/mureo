"""Discovery and lookup for :class:`ChangeFeedProvider` implementations (#545).

Two registration paths, mirroring :mod:`mureo.analytics.registry` so plugin
authors meet one set of rules across mureo's opt-in registries:

1. **Built-in adapters** are registered the first time
   :func:`default_change_feed_registry` is called, from the instances
   :func:`mureo.change_import.builtin.builtin_change_feeds` builds.
2. **Third-party bridges and plugins** ship an entry point in the
   :data:`~mureo.change_import.protocol.CHANGE_FEED_ENTRY_POINT_GROUP` group
   (``"mureo.change_feeds"``). Each entry's class is instantiated with no
   arguments, validated, and inserted under ``instance.platform``.

Shared contract: a broken feed (exception on import, instantiation, or
attribute access) is skipped with a :class:`ChangeFeedWarning`. Discovery
never raises — a third-party plugin cannot take change import offline for
every other platform.

First-wins on platform collisions. Built-ins register before discovery runs
and therefore cannot be shadowed by a plugin claiming the same platform.

Validation is **explicit and attribute-based**, not Protocol ``isinstance``.
``typing.runtime_checkable`` short-circuits nominal subclasses, so a plugin
that inherits :class:`ChangeFeedProvider` and forgets the method would pass
``isinstance`` and then raise ``AttributeError`` outside the fault-isolation
boundary. The same reasoning, and the same fix, as the analytics registry.
"""

from __future__ import annotations

import inspect
import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

from mureo.change_import.builtin import builtin_change_feeds
from mureo.change_import.protocol import CHANGE_FEED_ENTRY_POINT_GROUP
from mureo.core.platform_keys import (
    PLUGIN_PLATFORM_PREFIX,
    is_plugin_platform_key,
    plugin_platform_key,
    plugin_platform_key_matches,
    plugin_platform_parts,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.change_import.protocol import ChangeFeedProvider


class ChangeFeedWarning(UserWarning):
    """Emitted when a change feed is skipped during registration/discovery.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=ChangeFeedWarning)``.
    """


def _warn(message: str) -> None:
    warnings.warn(message, ChangeFeedWarning, stacklevel=3)


# Side-table for source-distribution attribution, keyed by ``id(instance)``
# rather than stamped onto the instance so a ``@dataclass(frozen=True)``
# plugin (which the docs encourage) keeps its breadcrumb.
_SOURCE_DISTRIBUTIONS: dict[int, str] = {}


def plugin_source(feed: object) -> str:
    """Return the pip distribution that registered ``feed``, or ``""``."""
    return _SOURCE_DISTRIBUTIONS.get(id(feed), "")


def _feed_validation_error(instance: object) -> str | None:
    """Return why ``instance`` is not a usable change feed, or ``None``."""
    platform = getattr(instance, "platform", None)
    if not isinstance(platform, str) or not platform:
        return "`platform` attribute must be a non-empty string"
    # #481 / #537: ``platform`` is a REGISTRY NAME. The ``plugin:`` namespace
    # is reserved for keys mureo builds from the installing distribution — a
    # feed allowed to name itself ``plugin:<other-dist>`` could shadow another
    # distribution's key on any name-keyed lookup. Fail closed.
    if platform.startswith(PLUGIN_PLATFORM_PREFIX):
        return (
            f"`platform` must not start with {PLUGIN_PLATFORM_PREFIX!r} — that "
            f"shape is reserved for canonical plugin platform keys, which "
            f"mureo builds from your distribution; use a plain registry name"
        )
    method = getattr(instance, "fetch_change_events", None)
    if method is None:
        return "missing required method 'fetch_change_events'"
    if not inspect.iscoroutinefunction(method):
        return "'fetch_change_events' must be an async coroutine function"
    return None


class ChangeFeedRegistry:
    """In-process registry of :class:`ChangeFeedProvider` instances.

    Not thread-safe — registration happens at process startup (built-in
    bootstrap plus the first discovery call). Lookups are O(1) on platform.
    """

    def __init__(self) -> None:
        self._feeds: dict[str, ChangeFeedProvider] = {}
        self._discovered: bool = False

    def register(
        self, feed: ChangeFeedProvider, *, source_distribution: str = ""
    ) -> None:
        """Register ``feed`` under ``feed.platform``.

        First-wins, so the built-in bootstrap is idempotent. A structurally
        invalid feed is skipped with a :class:`ChangeFeedWarning` rather than
        registered — a feed that cannot be called would otherwise turn into
        an ``ERROR`` outcome on every import pass forever.

        ``source_distribution`` is the pip distribution registering ``feed``
        in-process; it is what lets :func:`resolve_change_feed` match the feed
        to its canonical ``plugin:<distribution>:<platform>`` key, the same
        breadcrumb entry-point discovery records from ``ep.dist``. It is
        recorded only for a feed that is actually stored: a duplicate that
        first-wins drops must not leave a breadcrumb behind.
        """
        error = _feed_validation_error(feed)
        if error is not None:
            _warn(f"change feed {feed!r}: {error}; not registered")
            return
        if feed.platform in self._feeds:
            return
        self._feeds[feed.platform] = feed
        if source_distribution:
            _SOURCE_DISTRIBUTIONS[id(feed)] = source_distribution

    def get(self, platform: str) -> ChangeFeedProvider | None:
        """Return the registered feed for ``platform``, or ``None``."""
        return self._feeds.get(platform)

    def platforms(self) -> tuple[str, ...]:
        """Return the sorted tuple of platforms with a registered feed."""
        return tuple(sorted(self._feeds))

    def feeds(self) -> tuple[tuple[str, ChangeFeedProvider], ...]:
        """Return ``(platform, feed)`` pairs, sorted by platform."""
        return tuple(sorted(self._feeds.items(), key=lambda item: item[0]))

    def clear(self) -> None:
        """Drop all registrations (test helper)."""
        for feed in self._feeds.values():
            _SOURCE_DISTRIBUTIONS.pop(id(feed), None)
        self._feeds.clear()
        self._discovered = False

    def discover(
        self,
        *,
        refresh: bool = False,
        loader: Callable[..., Any] | None = None,
    ) -> tuple[str, ...]:
        """Iterate the ``mureo.change_feeds`` entry-point group.

        Idempotent: a second call without ``refresh=True`` is a no-op.
        Returns the platforms registered by this pass.
        """
        if self._discovered and not refresh:
            return ()

        load = loader or entry_points
        try:
            eps = tuple(load(group=CHANGE_FEED_ENTRY_POINT_GROUP))
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — discovery must not crash
            _warn(f"change-feed discovery failed; no plugin feeds loaded: {exc!r}")
            self._discovered = True
            return ()

        registered = [
            platform
            for platform in (self._collect_one(ep) for ep in eps)
            if platform is not None
        ]
        self._discovered = True
        return tuple(registered)

    def _collect_one(self, ep: Any) -> str | None:
        """Load -> validate -> register one entry point, fault-isolated."""
        ep_name = getattr(ep, "name", "<unknown>")
        try:
            loaded = ep.load()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
            _warn(f"change-feed entry point {ep_name!r}: load failed ({exc!r})")
            return None

        if not inspect.isclass(loaded):
            _warn(
                f"change-feed entry point {ep_name!r}: must yield a class "
                f"(got {type(loaded).__name__}); skipped"
            )
            return None

        try:
            instance = loaded()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
            _warn(
                f"change-feed entry point {ep_name!r}: not instantiable with no "
                f"arguments; skipped ({exc!r})"
            )
            return None

        error = _feed_validation_error(instance)
        if error is not None:
            _warn(f"change-feed entry point {ep_name!r}: {error}; skipped")
            return None

        platform: str = instance.platform
        if platform in self._feeds:
            _warn(
                f"change-feed entry point {ep_name!r}: platform {platform!r} "
                f"already registered; duplicate dropped (first wins)"
            )
            return None

        dist = getattr(ep, "dist", None)
        _SOURCE_DISTRIBUTIONS[id(instance)] = (
            getattr(dist, "name", "") if dist is not None else ""
        )
        self._feeds[platform] = instance
        return platform


# ---------------------------------------------------------------------------
# Module-level facade
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY: ChangeFeedRegistry | None = None
_BUILTIN_LOADED = False


def default_change_feed_registry() -> ChangeFeedRegistry:
    """Return the lazily-initialised process-wide registry.

    The first call registers the feeds
    :func:`~mureo.change_import.builtin.builtin_change_feeds` builds, on the
    registry object directly, so the bootstrap never calls back into this
    function. ``_BUILTIN_LOADED`` flips only on success, so a transient
    failure is retried on the next call rather than permanently disabling the
    built-in feeds.
    """
    global _DEFAULT_REGISTRY, _BUILTIN_LOADED
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ChangeFeedRegistry()
    if not _BUILTIN_LOADED:
        try:
            for feed in builtin_change_feeds():
                _DEFAULT_REGISTRY.register(feed)
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — must not crash callers
            _warn(f"built-in change feeds failed to load: {exc!r}")
        else:
            _BUILTIN_LOADED = True
    return _DEFAULT_REGISTRY


def clear_change_feed_registry() -> None:
    """Reset the process-wide registry and rearm the bootstrap. Test helper."""
    global _DEFAULT_REGISTRY, _BUILTIN_LOADED
    if _DEFAULT_REGISTRY is not None:
        _DEFAULT_REGISTRY.clear()
    _BUILTIN_LOADED = False


def register_change_feed(
    feed: ChangeFeedProvider, *, source_distribution: str = ""
) -> None:
    """Register ``feed`` on the default registry."""
    default_change_feed_registry().register(
        feed, source_distribution=source_distribution
    )


def get_change_feed(platform: str) -> ChangeFeedProvider | None:
    """Return the registered feed for ``platform``, or ``None``.

    ``None`` is the whole honest-degradation contract: the importer turns it
    into ``change_import_unavailable_for_<platform>`` rather than an empty
    success. Triggers entry-point discovery on first call (idempotent).
    """
    registry = default_change_feed_registry()
    registry.discover()
    return registry.get(platform)


def resolve_change_feed(platform_key: str) -> ChangeFeedProvider | None:
    """Return the feed that answers for the STATE.json key ``platform_key``.

    A feed registers under its plain registry name, but a provider-served
    platform's STATE.json key is ``plugin:<distribution>:<name>`` (#481,
    #537), so the two need reconciling — the same join
    ``mureo_analytics_run`` makes for analytics modules, with one difference
    in the ambiguous case below.

    The two input shapes are resolved by **disjoint** paths, never by falling
    through from one to the other:

    - A plugin platform key resolves **only** against feeds whose recorded
      source distribution is the key's distribution and whose registry name
      the key names. The distribution is authoritative because mureo records
      it from the registering distribution, not from the feed. There is no
      direct-lookup attempt first, so a feed with no recorded distribution,
      or one from another distribution that happens to share the name, never
      answers for this key.
    - Anything else (a built-in key, a registry name) uses the direct lookup
      of :func:`get_change_feed`, unchanged.

    The legacy ``plugin:<distribution>`` short form names a distribution, not
    a platform. With exactly one feed for that distribution it resolves; with
    several it is ``None``. Analytics takes the first module in sorted
    registry-name order there; an import refuses instead, because a window of
    changes filed under the wrong platform is written into ``action_log``, and
    nothing a reader does later can tell it was misfiled or undo it.

    Triggers entry-point discovery on first call (idempotent).
    """
    if not is_plugin_platform_key(platform_key):
        return get_change_feed(platform_key)
    registry = default_change_feed_registry()
    registry.discover()
    distribution, _provider = plugin_platform_parts(platform_key)
    candidates = [
        feed
        for name, feed in registry.feeds()
        if plugin_source(feed) == distribution
        and plugin_platform_key_matches(platform_key, distribution, name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def change_feed_platform_keys() -> tuple[str, ...]:
    """Return, sorted, the STATE.json platform key each registered feed serves.

    A feed with a recorded source distribution serves its canonical
    ``plugin:<distribution>:<name>`` key; any other feed serves its plain
    name, which for a built-in is the STATE.json key. This is the vocabulary
    an import outcome's ``platform`` uses, so a caller can compare the two
    directly — unlike :func:`list_change_feed_platforms`, which lists
    registry names.
    """
    registry = default_change_feed_registry()
    registry.discover()
    return tuple(
        sorted(
            (
                plugin_platform_key(source, name)
                if (source := plugin_source(feed))
                else name
            )
            for name, feed in registry.feeds()
        )
    )


def list_change_feed_platforms() -> tuple[str, ...]:
    """Return the sorted platforms that have a registered change feed."""
    registry = default_change_feed_registry()
    registry.discover()
    return registry.platforms()


def discover_change_feeds(
    *, refresh: bool = False, loader: Callable[..., Any] | None = None
) -> tuple[str, ...]:
    """Force entry-point discovery on the default registry."""
    return default_change_feed_registry().discover(refresh=refresh, loader=loader)


__all__ = [
    "ChangeFeedRegistry",
    "ChangeFeedWarning",
    "change_feed_platform_keys",
    "clear_change_feed_registry",
    "default_change_feed_registry",
    "discover_change_feeds",
    "get_change_feed",
    "list_change_feed_platforms",
    "plugin_source",
    "register_change_feed",
    "resolve_change_feed",
]
