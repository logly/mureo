"""Discovery + lookup for :class:`AnalyticsModule` implementations.

Two registration paths:

1. **Built-in adapters** register via :func:`register_analytics_module`
   the first time :func:`default_analytics_registry` is called (the
   ``register_builtin_analytics_modules`` helper invokes it). A
   subsequent :func:`clear_analytics_registry` call rearms the
   bootstrap so test isolation works.

2. **Third-party plugins** ship an entry point in the
   :data:`ANALYTICS_ENTRY_POINT_GROUP` group (``"mureo.analytics"``).
   :meth:`AnalyticsRegistry.discover` instantiates each entry's class
   with no arguments, validates it via :func:`_module_validation_error`,
   and inserts it under ``instance.platform``.

Both paths share the same fault-isolation contract: a broken module
(exception on import, instantiation, or attribute access) is skipped
with an :class:`AnalyticsModuleWarning`. Discovery never raises.

First-wins on platform-name collisions: a built-in is registered before
discovery runs and therefore cannot be shadowed by a later plugin. Two
plugins claiming the same platform name → the first-discovered wins.

Validation is **explicit and attribute-based**, not Protocol
``isinstance``. ``typing.runtime_checkable`` short-circuits nominal
subclasses, so a plugin that inherits :class:`AnalyticsModule` and
omits a required method would pass ``isinstance`` unconditionally and
later raise ``AttributeError`` outside the fault-isolation boundary.
:func:`_module_validation_error` enumerates the required attributes
and coroutine-function methods directly, closing that gap.

Source-distribution breadcrumbs are stored in a process-wide side-table
keyed by ``id(instance)`` rather than stamped onto the instance, so
plugins implemented as ``@dataclass(frozen=True)`` (which the docs
encourage) retain their attribution.
"""

from __future__ import annotations

import inspect
import warnings
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.analytics.protocol import AnalyticsModule

ANALYTICS_ENTRY_POINT_GROUP = "mureo.analytics"


_REQUIRED_MODULE_ATTRS: tuple[str, ...] = (
    "platform",
    "capabilities",
    "detect_anomalies",
    "diagnose_performance",
    "audit_creative",
    "analyze_budget_efficiency",
)

# Methods that MUST be async coroutine functions (the four Protocol
# methods, but not ``platform`` or ``capabilities``).
_REQUIRED_ASYNC_METHODS: tuple[str, ...] = (
    "detect_anomalies",
    "diagnose_performance",
    "audit_creative",
    "analyze_budget_efficiency",
)


# Side-table for source-distribution attribution; see module docstring.
_SOURCE_DISTRIBUTIONS: dict[int, str] = {}


def plugin_source(module: object) -> str:
    """Return the pip distribution that registered ``module``, or ``""``.

    Parallel to :func:`mureo.mcp.tool_provider.plugin_source` but keyed
    off a side-table rather than instance attribute mutation, so a
    frozen plugin instance does not silently lose its breadcrumb.
    """
    return _SOURCE_DISTRIBUTIONS.get(id(module), "")


def _is_inherited_protocol_stub(method: object, method_name: str) -> bool:
    """Return ``True`` if ``method`` is the un-overridden Protocol stub.

    The Protocol's ``async def detect_anomalies(...) -> ...: ...``
    inherits as a real coroutine function whose body is the Ellipsis
    no-op (returning ``None``). A subclass that forgets to override
    the method still passes ``hasattr`` / ``iscoroutinefunction`` —
    detecting the inherited stub by qualified name catches that case
    rather than letting a no-op masquerade as an implementation.
    """
    # Local import to avoid a hard cycle at module import time
    # (registry.py is imported via the analytics package's __init__,
    # which would otherwise pull protocol.py twice).
    from mureo.analytics.protocol import AnalyticsModule

    func = getattr(method, "__func__", method)
    qualname = getattr(func, "__qualname__", "")
    expected_stub_qualname = f"{AnalyticsModule.__name__}.{method_name}"
    return qualname == expected_stub_qualname


def _module_validation_error(instance: object) -> str | None:
    """Return a human-readable error if ``instance`` is not a valid
    analytics module, or ``None`` when the structural shape passes.

    Centralised so both direct ``register`` and entry-point
    ``_collect_one`` apply the same rules — an asymmetric check would
    let bad plugins slip through when registered via one path but not
    the other.
    """
    for attr in _REQUIRED_MODULE_ATTRS:
        if not hasattr(instance, attr):
            return f"missing required attribute {attr!r}"

    platform = getattr(instance, "platform", None)
    if not isinstance(platform, str) or not platform:
        return "`platform` attribute must be a non-empty string"

    capabilities = getattr(instance, "capabilities", None)
    if not callable(capabilities):
        return "`capabilities` must be callable"

    for method_name in _REQUIRED_ASYNC_METHODS:
        method = getattr(instance, method_name, None)
        if not inspect.iscoroutinefunction(method):
            return f"{method_name!r} must be an async coroutine function"
        if _is_inherited_protocol_stub(method, method_name):
            return (
                f"{method_name!r} is the un-overridden AnalyticsModule "
                f"stub — implement it or raise NotImplementedError"
            )

    return None


class AnalyticsModuleWarning(UserWarning):
    """Emitted when an analytics module is skipped during discovery.

    A distinct subclass so strict deployments can opt into
    ``warnings.filterwarnings("error", category=AnalyticsModuleWarning)``.
    """


def _warn(message: str) -> None:
    warnings.warn(message, AnalyticsModuleWarning, stacklevel=3)


class AnalyticsRegistry:
    """In-process registry of :class:`AnalyticsModule` instances.

    Not thread-safe — registration is expected to happen at process
    startup (built-in bootstrap + first discovery call). Lookups are
    O(1) on the platform name.
    """

    def __init__(self) -> None:
        self._modules: dict[str, AnalyticsModule] = {}
        self._discovered: bool = False

    def register(self, module: AnalyticsModule) -> None:
        """Register ``module`` under ``module.platform``.

        First-wins: if a module is already registered for that platform
        the second call is a silent no-op so built-in re-bootstrap is
        idempotent. A structurally invalid module is skipped with an
        :class:`AnalyticsModuleWarning` rather than registered.
        """
        error = _module_validation_error(module)
        if error is not None:
            _warn(f"analytics module {module!r}: {error}; not registered")
            return

        platform = module.platform
        self._modules.setdefault(platform, module)

    def get(self, platform: str) -> AnalyticsModule | None:
        """Return the registered module for ``platform`` or ``None``."""
        return self._modules.get(platform)

    def platforms(self) -> tuple[str, ...]:
        """Return the sorted tuple of registered platform names."""
        return tuple(sorted(self._modules))

    def clear(self) -> None:
        """Drop all registrations (test helper)."""
        for module in self._modules.values():
            _SOURCE_DISTRIBUTIONS.pop(id(module), None)
        self._modules.clear()
        self._discovered = False

    def discover(
        self,
        *,
        refresh: bool = False,
        loader: Callable[..., Any] | None = None,
    ) -> tuple[str, ...]:
        """Iterate the ``mureo.analytics`` entry-point group.

        Idempotent: a second call without ``refresh=True`` is a no-op.
        Returns the tuple of platform names registered by this pass
        (excluding pre-existing built-ins and duplicates).

        Args:
            refresh: When ``True``, re-iterate even if a previous call
                already discovered.
            loader: Injectable replacement for
                :func:`importlib.metadata.entry_points` (used by tests).
        """
        if self._discovered and not refresh:
            return ()

        load = loader or entry_points
        try:
            eps = tuple(load(group=ANALYTICS_ENTRY_POINT_GROUP))
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — discovery must not crash
            _warn(
                f"analytics-module discovery failed; no plugin modules "
                f"loaded: {exc!r}"
            )
            self._discovered = True
            return ()

        registered: list[str] = []
        for ep in eps:
            platform = self._collect_one(ep)
            if platform is not None:
                registered.append(platform)

        self._discovered = True
        return tuple(registered)

    def _collect_one(self, ep: Any) -> str | None:
        """Load → validate → register one entry point, fault-isolated."""
        ep_name = getattr(ep, "name", "<unknown>")
        try:
            loaded = ep.load()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
            _warn(
                f"analytics entry point {ep_name!r}: load failed; " f"skipped ({exc!r})"
            )
            return None

        if not inspect.isclass(loaded):
            _warn(
                f"analytics entry point {ep_name!r}: must yield a class "
                f"(got {type(loaded).__name__}); skipped"
            )
            return None

        try:
            instance = loaded()
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 — per-plugin isolation
            _warn(
                f"analytics entry point {ep_name!r}: not instantiable "
                f"with no arguments; skipped ({exc!r})"
            )
            return None

        # The order matters: check `platform` shape first so we have a
        # useful identifier for downstream messages, then run the full
        # structural validator. Both routes through
        # `_module_validation_error` so direct `register` cannot diverge.
        platform = getattr(instance, "platform", None)
        if not isinstance(platform, str) or not platform:
            _warn(
                f"analytics entry point {ep_name!r}: instance has no "
                f"`platform` attribute; skipped"
            )
            return None

        error = _module_validation_error(instance)
        if error is not None:
            _warn(f"analytics entry point {ep_name!r}: {error}; skipped")
            return None

        if platform in self._modules:
            _warn(
                f"analytics entry point {ep_name!r}: platform "
                f"{platform!r} already registered; duplicate dropped "
                f"(first wins)"
            )
            return None

        # Record attribution in the side-table so frozen instances do
        # not lose the breadcrumb. ``ep.dist`` may be ``None`` in
        # weirdly-installed environments — keep that case as an empty
        # string rather than crashing.
        dist = getattr(ep, "dist", None)
        distribution = getattr(dist, "name", "") if dist is not None else ""
        _SOURCE_DISTRIBUTIONS[id(instance)] = distribution

        self._modules[platform] = instance
        return platform


# ---------------------------------------------------------------------------
# Module-level façade
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY: AnalyticsRegistry | None = None
_BUILTIN_LOADED = False
# Re-entrance guard. ``register_builtin_analytics_modules`` ultimately
# calls back into :func:`default_analytics_registry` (via
# :func:`register_analytics_module` → ``default_registry().register``),
# so the bootstrap must be marked "in progress" before that call to
# stop the re-entry from firing the bootstrap again. The flag is
# separate from ``_BUILTIN_LOADED`` because we only want the latter
# to flip on success — a transient failure should leave both False so
# the next outer call retries.
_BUILTIN_LOADING = False


def default_analytics_registry() -> AnalyticsRegistry:
    """Return the lazily-initialised process-wide registry.

    The first call invokes ``register_builtin_analytics_modules`` so
    built-in adapters are present without the caller having to do it.
    ``_BUILTIN_LOADED`` flips only on success: a transient failure is
    retried on the next outer call rather than permanently disabling
    the built-ins. ``_BUILTIN_LOADING`` guards against the re-entrance
    that arises because the bootstrap calls back into this function
    via :func:`register_analytics_module`.
    """
    global _DEFAULT_REGISTRY, _BUILTIN_LOADED, _BUILTIN_LOADING
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = AnalyticsRegistry()
    if not _BUILTIN_LOADED and not _BUILTIN_LOADING:
        _BUILTIN_LOADING = True
        try:
            from mureo.analytics.builtin import (
                register_builtin_analytics_modules,
            )

            register_builtin_analytics_modules()
        except (KeyboardInterrupt, SystemExit):
            _BUILTIN_LOADING = False
            raise
        except BaseException as exc:  # noqa: BLE001 — built-in load must not crash
            _warn(f"built-in analytics modules failed to load: {exc!r}")
        else:
            _BUILTIN_LOADED = True
        finally:
            _BUILTIN_LOADING = False
    return _DEFAULT_REGISTRY


def clear_analytics_registry() -> None:
    """Reset the process-wide registry. Test helper.

    Also rearms the built-in bootstrap so the next
    :func:`default_analytics_registry` call re-registers them.
    """
    global _DEFAULT_REGISTRY, _BUILTIN_LOADED, _BUILTIN_LOADING
    if _DEFAULT_REGISTRY is not None:
        _DEFAULT_REGISTRY.clear()
    _BUILTIN_LOADED = False
    _BUILTIN_LOADING = False


def register_analytics_module(module: AnalyticsModule) -> None:
    """Register ``module`` on the default registry.

    Used by built-in adapters at bootstrap time and exposed for tests /
    advanced in-process registration.
    """
    default_analytics_registry().register(module)


def get_analytics_module(platform: str) -> AnalyticsModule | None:
    """Return the registered module for ``platform`` or ``None``.

    Triggers entry-point discovery on first call (idempotent).
    """
    registry = default_analytics_registry()
    registry.discover()
    return registry.get(platform)


def list_analytics_platforms() -> tuple[str, ...]:
    """Return the sorted tuple of platforms with a registered module."""
    registry = default_analytics_registry()
    registry.discover()
    return registry.platforms()


def discover_analytics_modules(*, refresh: bool = False) -> tuple[str, ...]:
    """Force entry-point discovery on the default registry."""
    return default_analytics_registry().discover(refresh=refresh)


__all__ = [
    "ANALYTICS_ENTRY_POINT_GROUP",
    "AnalyticsModuleWarning",
    "AnalyticsRegistry",
    "clear_analytics_registry",
    "default_analytics_registry",
    "discover_analytics_modules",
    "get_analytics_module",
    "list_analytics_platforms",
    "plugin_source",
    "register_analytics_module",
]
