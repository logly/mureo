"""Entry-points-based provider discovery registry.

This module is the discovery + lookup layer for the mureo provider
abstraction (Issue #89, P1-07). It turns Python's
:func:`importlib.metadata.entry_points` plus an in-process registration
API into a single source of truth for "which providers exist, what they
can do, and where they came from."

Public surface
--------------
- :class:`ProviderEntry` — frozen dataclass capturing a registered
  provider's identity, declared capabilities, class object, and the pip
  distribution that supplied it.
- :class:`Registry` — explicit container with discovery, lookup, and
  capability-filter methods. The module exposes a single shared
  ``default_registry`` instance plus thin module-level wrappers.
- :class:`RegistryWarning` — :class:`UserWarning` subclass emitted on
  recoverable conditions (broken plugin, duplicate name, malformed
  shape). Callers can opt into strict mode with
  ``warnings.filterwarnings("error", category=RegistryWarning)``.
- :data:`PROVIDERS_ENTRY_POINT_GROUP` — the ``"mureo.providers"`` group
  iterated by :meth:`Registry.discover`.
- :data:`SKILLS_ENTRY_POINT_GROUP` — the ``"mureo.skills"`` group name,
  reserved for P1-08; this module does NOT iterate it.

Security posture
----------------
Discovery loads third-party Python code (``ep.load()`` triggers the
plugin's top-level module import). This is a known trust boundary. The
registry mitigates the risk by:

1. Wrapping every ``ep.load()`` plus the subsequent structural check in
   a per-entry try/except so one broken plugin cannot break discovery.
2. Validating loaded classes against :func:`validate_provider` before
   registration; malformed plugins are skipped with a warning.
3. Tracking ``source_distribution`` so users / support can identify the
   pip package each provider came from.
4. Following first-wins on duplicate names so a malicious plugin
   installed AFTER a legitimate one cannot silently take over the slot.
5. Deferring instantiation entirely; ``ProviderEntry.provider_class`` is
   the class object, not an instance, so plugin ``__init__`` side
   effects (network, FS, credential checks) are not invoked here.

Warning volume / log flood considerations:
    Each broken or duplicate plugin emits a :class:`RegistryWarning`.
    Since the warning message embeds attacker-controllable strings
    (entry point name, distribution name, exception ``repr``), Python's
    default warning deduplication does not coalesce them — every
    unique message is a fresh warning. A hostile environment that
    installs many malformed plugins can therefore flood logs by sheer
    volume even though no individual warning is malicious. Production
    deployments should either:

    * apply rate limits at the log sink layer (preferred), or
    * set ``warnings.filterwarnings("error", category=RegistryWarning)``
      to fail closed — the first malformed plugin becomes a startup
      failure instead of N log entries.

    Phase 2 may add in-module rate limiting (cap N warnings per
    discovery pass) — tracked separately and not addressed here.

Thread safety
-------------
The registry is NOT thread-safe (Phase 1 non-goal). Concurrent
discovery/registration is undefined behaviour. The documented use is
single-threaded CLI / MCP-server-startup discovery.

Foundation rule
---------------
Internal imports are restricted to :mod:`mureo.core.providers.base`,
:mod:`mureo.core.providers.capabilities`, and
:mod:`mureo.core.providers.models`. No imports of the four domain
Protocol modules — the registry treats providers structurally.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Final, cast

from mureo.core.providers.base import (
    BaseProvider,
    validate_provider,
    validate_provider_name,
)
from mureo.core.providers.capabilities import Capability

if TYPE_CHECKING:
    from collections.abc import Iterator

PROVIDERS_ENTRY_POINT_GROUP: Final[str] = "mureo.providers"
SKILLS_ENTRY_POINT_GROUP: Final[str] = "mureo.skills"


class RegistryWarning(UserWarning):
    """Emitted when a registered provider is skipped, shadowed, or
    otherwise mishandled at discovery / registration time.

    Distinct subclass of :class:`UserWarning` so security-conscious
    deployments can opt into strict mode via
    ``warnings.filterwarnings("error", category=RegistryWarning)``.
    """


@dataclass(frozen=True)
class ProviderEntry:
    """Frozen record of a registered provider.

    The field set and order are part of the public ABI; third-party
    callers may destructure positionally. Do not reorder or remove
    fields without a major-version bump.

    Attributes:
        name: Snake_case provider identifier (matches
            ``^[a-z][a-z0-9_]*$``). Used as the registry key.
        display_name: Human-readable provider label. Non-empty string.
        capabilities: Capabilities the provider declares it can serve.
            Must be a :class:`frozenset` of :class:`Capability` members.
        provider_class: The class object itself (NOT an instance).
            Instantiation is deferred to consumers.
        source_distribution: PEP 503 normalized pip package name that
            supplied this entry, or ``None`` when unknown (in-process
            registrations without an explicit hint, or entry points
            whose ``ep.dist`` is ``None``). Treat as untrusted data
            downstream — do not interpolate into shell commands.
    """

    name: str
    display_name: str
    capabilities: frozenset[Capability]
    provider_class: type
    source_distribution: str | None

    def __post_init__(self) -> None:
        """Validate the entry's identity attributes at construction.

        Raises:
            TypeError: ``name`` / ``display_name`` is not a ``str``,
                ``capabilities`` is not a ``frozenset[Capability]``, or
                ``provider_class`` is not a class.
            ValueError: ``name`` fails the snake_case regex, or
                ``display_name`` is empty.
        """
        if not isinstance(self.name, str):
            raise TypeError(
                f"ProviderEntry.name must be str, " f"got {type(self.name).__name__}"
            )
        validate_provider_name(self.name)

        if not isinstance(self.display_name, str):
            raise TypeError(
                f"ProviderEntry.display_name must be str, "
                f"got {type(self.display_name).__name__}"
            )
        if self.display_name == "":
            raise ValueError("ProviderEntry.display_name must be a non-empty string")

        if not isinstance(self.capabilities, frozenset):
            raise TypeError(
                f"ProviderEntry.capabilities must be a frozenset, "
                f"got {type(self.capabilities).__name__}"
            )
        bad_members = [c for c in self.capabilities if not isinstance(c, Capability)]
        if bad_members:
            bad_repr = ", ".join(repr(m) for m in bad_members)
            raise TypeError(
                f"ProviderEntry.capabilities must contain only Capability "
                f"members; got non-Capability element(s): {bad_repr}"
            )

        if not isinstance(self.provider_class, type):
            raise TypeError(
                f"ProviderEntry.provider_class must be a class, "
                f"got {type(self.provider_class).__name__}"
            )

        if self.source_distribution is not None and not isinstance(
            self.source_distribution, str
        ):
            raise TypeError(
                f"ProviderEntry.source_distribution must be str | None, "
                f"got {type(self.source_distribution).__name__}"
            )


def _is_provider_class(cls: object) -> bool:
    """Return ``True`` iff ``cls`` is a class satisfying the BaseProvider
    contract via :func:`validate_provider`.

    Calls ``validate_provider`` on the class object itself (BaseProvider
    recommends ``name`` / ``display_name`` / ``capabilities`` as class
    attributes, so ``getattr`` on the class works). Any exception is
    treated as "not a provider class".

    Note: a malicious plugin could ship a metaclass with a side-effectful
    ``__getattribute__`` that fires during these ``getattr`` calls. That
    is an accepted Phase 1 risk — the class is already loaded by this
    point, so arbitrary code execution has already happened at
    ``ep.load()``. The broad ``except Exception`` below is intentional
    fault isolation: third-party plugin code may raise arbitrary
    exception types (``RuntimeError`` from a malicious metaclass
    ``__getattribute__``, ``AttributeError`` from a half-built subclass,
    descriptors that raise on access, etc.); narrowing to
    ``(TypeError, ValueError)`` would let those escape and abort the
    discovery loop, violating the per-plugin fault-isolation contract.
    """
    if not isinstance(cls, type):
        return False
    try:
        validate_provider(cls)
    except Exception:  # noqa: BLE001 — fault isolation: see docstring above
        return False
    return True


def _warn_skip(message: str) -> None:
    """Emit a :class:`RegistryWarning` from inside the discovery loop.

    Centralizes the ``stacklevel=4`` so callers stay at one level above
    ``Registry.discover`` in user warning output.
    """
    warnings.warn(message, RegistryWarning, stacklevel=4)


def _resolve_source(ep: Any) -> str | None:
    """Extract ``ep.dist.name`` defensively; ``None`` when unresolvable."""
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    name = getattr(dist, "name", None)
    return name if isinstance(name, str) else None


class Registry:
    """In-process registry of discovered providers.

    Most callers should use the module-level wrapper functions
    (``register_provider_class``, ``discover_providers``,
    ``get_provider``, ``list_providers_by_capability``,
    ``clear_registry``) which delegate to the shared
    :data:`default_registry`. The :class:`Registry` class is exposed for
    tests and advanced cases that need an isolated instance.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ProviderEntry] = {}
        self._discovered: bool = False
        self._cached_result: tuple[ProviderEntry, ...] = ()

    # ------------------------------------------------------------------
    # Dunder methods — exposed in the public ABI for ergonomic checks.
    # ------------------------------------------------------------------

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries

    def __iter__(self) -> Iterator[ProviderEntry]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, entry: ProviderEntry) -> None:
        """Insert a pre-built :class:`ProviderEntry`.

        Follows first-wins: if ``entry.name`` is already registered, a
        :class:`RegistryWarning` is emitted and the new entry is dropped.

        Raises:
            TypeError: ``entry`` is not a :class:`ProviderEntry`.
        """
        if not isinstance(entry, ProviderEntry):
            raise TypeError(
                f"Registry.register requires a ProviderEntry, "
                f"got {type(entry).__name__}"
            )
        self._insert_or_warn(entry)

    def register_provider_class(
        self,
        cls: type,
        *,
        source_distribution: str | None = None,
    ) -> ProviderEntry:
        """Validate and register ``cls`` against :func:`validate_provider`.

        Unlike entry-point discovery (warn + skip on failure), this
        explicit registration API raises on a malformed class so callers
        get fast feedback.

        Args:
            cls: A class with class attributes ``name`` / ``display_name``
                / ``capabilities``.
            source_distribution: Pip package name that owns ``cls``.
                ``None`` when called for in-process / built-in providers.

        Returns:
            The newly created :class:`ProviderEntry`. When a duplicate
            name was detected, returns the EXISTING entry (first-wins).

        Raises:
            TypeError: ``cls`` is not a class.
            TypeError | ValueError: ``cls`` fails
                :func:`validate_provider`. The error message includes
                ``cls.__qualname__`` so the offending class is locatable.
        """
        if not isinstance(cls, type):
            raise TypeError(
                f"register_provider_class requires a class, "
                f"got {type(cls).__name__}"
            )
        try:
            validate_provider(cls)
        except (TypeError, ValueError) as exc:
            qualname = getattr(cls, "__qualname__", cls.__name__)
            raise type(exc)(f"register_provider_class({qualname}): {exc}") from exc

        # validate_provider guarantees the BaseProvider class attributes
        # are present and well-typed; cast for mypy.
        provider = cast("BaseProvider", cls)
        entry = ProviderEntry(
            name=provider.name,
            display_name=provider.display_name,
            capabilities=provider.capabilities,
            provider_class=cls,
            source_distribution=source_distribution,
        )
        return self._insert_or_warn(entry)

    def _insert_or_warn(self, entry: ProviderEntry) -> ProviderEntry:
        """Insert ``entry`` under ``entry.name``; warn + skip on duplicate.

        Returns the entry actually stored (the existing one on
        duplicate, the new one on first insertion). All three
        registration paths (``register``, ``register_provider_class``,
        the entry-points loop) funnel through here so the first-wins
        rule has a single source of truth.
        """
        existing = self._entries.get(entry.name)
        if existing is not None:
            warnings.warn(
                (
                    f"duplicate provider name {entry.name!r}: "
                    f"first-registered from {existing.source_distribution!r} "
                    f"wins; later registration from "
                    f"{entry.source_distribution!r} is dropped"
                ),
                RegistryWarning,
                stacklevel=3,
            )
            return existing
        self._entries[entry.name] = entry
        return entry

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, *, refresh: bool = False) -> tuple[ProviderEntry, ...]:
        """Iterate ``mureo.providers`` entry points and register the
        well-formed classes.

        Idempotent + cached: a second call without ``refresh=True`` does
        NOT re-iterate ``entry_points``. ``refresh=True`` clears the
        cache flag (but not the registration map) and re-iterates.

        For each entry point, the per-entry try/except isolates faults:
        a broken plugin (``ep.load()`` raises) or a malformed plugin
        (validation fails) emits :class:`RegistryWarning` and is
        skipped. ``# noqa: BLE001`` is required on the load-step
        ``except Exception`` because broad catching is the intended
        fault-isolation boundary.

        Args:
            refresh: When ``True``, re-iterate entry points even if a
                previous discovery cached a result.

        Returns:
            Tuple of registered entries from this discovery pass. The
            tuple reflects the registrations actually inserted into the
            registry (excluding those skipped due to duplicates).
        """
        if self._discovered and not refresh:
            return self._cached_result

        discovered: list[ProviderEntry] = []
        for ep in entry_points(group=PROVIDERS_ENTRY_POINT_GROUP):
            entry = self._load_entry_point(ep)
            if entry is not None:
                discovered.append(entry)

        self._cached_result = tuple(discovered)
        self._discovered = True
        return self._cached_result

    def _load_entry_point(self, ep: Any) -> ProviderEntry | None:
        """Load, validate, and register a single entry point.

        Returns the stored entry on success, ``None`` when the entry was
        skipped (load failure, validation failure, or duplicate-name
        first-wins drop).

        The try/except spans the entire load → validate → construct
        sequence (not just ``ep.load()``) so that adversarial plugins
        cannot bypass fault isolation via a TOCTOU pattern in which the
        class passes :func:`_is_provider_class` but a metaclass-driven
        side effect raises during attribute access in the
        :class:`ProviderEntry` constructor. ``# noqa: BLE001`` is
        required: broad catching is the intended fault-isolation
        boundary, not a code smell.
        """
        ep_name = getattr(ep, "name", "<unknown>")
        try:
            loaded = ep.load()
            if not _is_provider_class(loaded):
                _warn_skip(
                    f"entry point {ep_name!r} did not yield a valid "
                    f"provider class (got {type(loaded).__name__}); skipped"
                )
                return None

            # _is_provider_class guarantees `loaded` is a type satisfying
            # validate_provider; the cast is safe because the helper just
            # verified isinstance(loaded, type) and validate_provider(loaded).
            cls = cast("type", loaded)
            provider = cast("BaseProvider", cls)

            entry = ProviderEntry(
                name=provider.name,
                display_name=provider.display_name,
                capabilities=provider.capabilities,
                provider_class=cls,
                source_distribution=_resolve_source(ep),
            )
        except Exception as exc:  # noqa: BLE001 — per-plugin fault isolation
            _warn_skip(
                f"failed to load entry point {ep_name!r} in group "
                f"{PROVIDERS_ENTRY_POINT_GROUP!r}: {exc!r}"
            )
            return None

        stored = self._insert_or_warn(entry)
        # If a duplicate was rejected, _insert_or_warn returns the
        # pre-existing entry — exclude it from this discovery pass's
        # tuple to avoid double-counting.
        return stored if stored is entry else None

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> ProviderEntry:
        """Return the entry registered under ``name``.

        Raises:
            KeyError: ``name`` is not registered. The error message
                includes the requested name and the sorted list of
                known providers (mirrors ``parse_capability`` style).
        """
        entry = self._entries.get(name)
        if entry is None:
            known = sorted(self._entries.keys())
            raise KeyError(f"unknown provider: {name!r}. Known providers: {known}")
        return entry

    def list_by_capability(self, cap: Capability) -> tuple[ProviderEntry, ...]:
        """Return entries declaring ``cap``, sorted by ``name`` ascending.

        Args:
            cap: A :class:`Capability` member.

        Returns:
            Tuple of matching entries (empty when none match).

        Raises:
            TypeError: ``cap`` is not a :class:`Capability` member.
                Defensive contract for third-party callers who may pass
                a string token.
        """
        if not isinstance(cap, Capability):
            raise TypeError(
                f"list_by_capability requires a Capability member, "
                f"got {type(cap).__name__}"
            )
        matches = [e for e in self._entries.values() if cap in e.capabilities]
        matches.sort(key=lambda e: e.name)
        return tuple(matches)

    def clear(self) -> None:
        """Remove all registrations AND invalidate the discovery cache.

        Used by tests to enforce isolation between cases and by callers
        who need a clean slate before a manual re-registration sequence.
        """
        self._entries.clear()
        self._discovered = False
        self._cached_result = ()


# ---------------------------------------------------------------------------
# Module-level singleton + thin wrappers
# ---------------------------------------------------------------------------


default_registry: Registry = Registry()


def register_provider_class(
    cls: type,
    *,
    source_distribution: str | None = None,
) -> ProviderEntry:
    """Module-level wrapper around :meth:`Registry.register_provider_class`."""
    return default_registry.register_provider_class(
        cls, source_distribution=source_distribution
    )


def discover_providers(*, refresh: bool = False) -> tuple[ProviderEntry, ...]:
    """Module-level wrapper around :meth:`Registry.discover`."""
    return default_registry.discover(refresh=refresh)


def get_provider(name: str) -> ProviderEntry:
    """Module-level wrapper around :meth:`Registry.get`."""
    return default_registry.get(name)


def list_providers_by_capability(
    cap: Capability,
) -> tuple[ProviderEntry, ...]:
    """Module-level wrapper around :meth:`Registry.list_by_capability`."""
    return default_registry.list_by_capability(cap)


def clear_registry() -> None:
    """Module-level wrapper around :meth:`Registry.clear`."""
    default_registry.clear()


__all__ = [
    "PROVIDERS_ENTRY_POINT_GROUP",
    "SKILLS_ENTRY_POINT_GROUP",
    "ProviderEntry",
    "Registry",
    "RegistryWarning",
    "clear_registry",
    "default_registry",
    "discover_providers",
    "get_provider",
    "list_providers_by_capability",
    "register_provider_class",
]
