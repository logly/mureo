"""``BaseProvider`` Protocol and structural validators.

This module defines the runtime-checkable :class:`BaseProvider` Protocol
that every mureo provider plugin (built-in ``google_ads``, ``meta_ads``,
and third-party plugins discovered via entry points) must satisfy. It is
the second foundational layer of the provider abstraction (Issue #89,
P1-02), built on top of :mod:`mureo.core.providers.capabilities`.

Foundation rule
---------------
This module's only allowed internal import is
:mod:`mureo.core.providers.capabilities`. Everything else may depend on
it; it depends on nothing else inside ``mureo``. This rule is enforced by
an AST scan in the test suite.

Class-attribute recommendation
------------------------------
``name`` and ``capabilities`` are part of a provider's static identity.
Real provider implementations should declare them as **class attributes**
so the registry, the skill matcher, and tooling can introspect them
without instantiating the provider. ``display_name`` is also typically a
class attribute. The Protocol itself permits either class or instance
attributes (``runtime_checkable`` uses structural ``hasattr`` checks).

``runtime_checkable`` is structural only
----------------------------------------
``isinstance(obj, BaseProvider)`` returns ``True`` for *any* object
exposing the three named attributes regardless of their types. For deep
type validation, use :func:`validate_provider`. ``isinstance`` is the
cheap discriminator; ``validate_provider`` is the contract enforcer.

Capabilities are the *declared* set
-----------------------------------
``capabilities`` lists the capabilities the provider *declares it can*
serve. Some real providers expose more capabilities once authenticated
(e.g., write scopes); for Phase 1 the registry / skill matcher gates
purely against this declared set. Runtime authorization checks happen
elsewhere (future ``permit()`` API).

Non-goal: authentication
------------------------
Authentication is intentionally **not** part of this contract. Phase 1
keeps :class:`BaseProvider` minimal so adapters can wrap existing
``GoogleAdsApiClient`` / ``MetaAdsApiClient`` instances without churn.
A future ``AuthenticatedProvider`` Protocol (or credentials abstraction)
will layer on top.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from mureo.core.providers.capabilities import Capability

# Snake_case identifier: starts with a lowercase ASCII letter, followed
# by lowercase letters, digits, or underscores. Anchored both ends; no
# user-controlled regex pattern, so no ReDoS risk.
_PROVIDER_NAME_PATTERN: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9_]*$")


@runtime_checkable
class BaseProvider(Protocol):
    """Structural contract for a mureo provider plugin.

    Every provider — built-in or third-party — must expose these three
    attributes. They form the public ABI consumed by the registry, the
    skill matcher, and any tooling that introspects providers.

    Attributes:
        name: Stable snake_case identifier (e.g., ``"google_ads"``).
            Used as the registry key and in skill frontmatter. Must
            match ``^[a-z][a-z0-9_]*$``. Recommended to be a class
            attribute.
        display_name: Human-readable provider label (e.g.,
            ``"Google Ads"``). Used in CLI output and error messages.
            Must be a non-empty string.
        capabilities: The set of capabilities the provider declares it
            can serve. ``frozenset`` (not ``set``) so it is hashable and
            cannot be mutated after construction. Recommended to be a
            class attribute.

    No methods are declared in Phase 1. Adding required methods later
    would be a breaking change for installed plugins; new behaviour
    should be added via secondary Protocols rather than expanding this
    one.
    """

    name: str
    display_name: str
    capabilities: frozenset[Capability]


def validate_provider_name(name: str) -> str:
    """Validate a provider's ``name`` against the snake_case contract.

    The contract — ``^[a-z][a-z0-9_]*$`` — matches the snake_case rule
    that :class:`Capability` values already follow, so a single style
    spans both halves of the ABI.

    Args:
        name: The candidate provider name.

    Returns:
        The validated name unchanged (handy for inline use).

    Raises:
        ValueError: If ``name`` is not a non-empty string matching the
            pattern. The error message includes ``repr(name)`` so the
            offending input is locatable in logs.
    """
    if not isinstance(name, str) or not _PROVIDER_NAME_PATTERN.match(name):
        raise ValueError(
            f"invalid provider name: {name!r} "
            f"(must match {_PROVIDER_NAME_PATTERN.pattern!r})"
        )
    return name


def _identity_hint(provider: object) -> str:
    """Return a short identifier for ``provider`` to embed in errors.

    Prefers the provider's own ``name`` (when it is a non-empty string),
    falling back to ``repr(provider)`` so callers can always locate the
    bad provider in logs even when ``name`` itself is malformed.
    """
    raw_name = getattr(provider, "name", None)
    if isinstance(raw_name, str) and raw_name:
        return raw_name
    return repr(provider)


def validate_provider(provider: object) -> None:
    """Deeply validate a provider object against :class:`BaseProvider`.

    Goes beyond the structural ``isinstance(obj, BaseProvider)`` check
    by verifying attribute *types* and *values*. Use this whenever a
    provider crosses a trust boundary (registration, plugin discovery,
    test fixtures asserting contract conformance).

    Args:
        provider: The object to validate.

    Returns:
        ``None`` on success.

    Raises:
        TypeError: If any attribute has the wrong type — e.g., ``name``
            is not ``str``, ``display_name`` is not ``str``,
            ``capabilities`` is not a ``frozenset``, or ``capabilities``
            contains a non-:class:`Capability` element.
        ValueError: If a string attribute is empty or fails its value
            contract — e.g., ``name`` does not match
            ``^[a-z][a-z0-9_]*$``, or ``display_name`` is the empty
            string.

    All error messages embed an identity hint (the provider's ``name``
    when valid, otherwise ``repr(provider)``) so the offending provider
    is locatable.
    """
    identity = _identity_hint(provider)

    # ---- name -----------------------------------------------------------
    name = getattr(provider, "name", None)
    if not isinstance(name, str):
        raise TypeError(
            f"provider {identity}: 'name' must be str, " f"got {type(name).__name__}"
        )
    # Reuse the regex validator; surface the bad provider's identity.
    try:
        validate_provider_name(name)
    except ValueError as exc:
        raise ValueError(f"provider {identity}: 'name' is invalid — {exc}") from exc

    # ---- display_name ---------------------------------------------------
    display_name = getattr(provider, "display_name", None)
    if not isinstance(display_name, str):
        raise TypeError(
            f"provider {identity}: 'display_name' must be str, "
            f"got {type(display_name).__name__}"
        )
    if display_name == "":
        raise ValueError(
            f"provider {identity}: 'display_name' must be a non-empty string"
        )

    # ---- capabilities ---------------------------------------------------
    # Order matters: the frozenset type check must precede element
    # inspection so that a plain ``set`` produces a 'frozenset' hint
    # rather than triggering element-type checks.
    capabilities = getattr(provider, "capabilities", None)
    if not isinstance(capabilities, frozenset):
        raise TypeError(
            f"provider {identity}: 'capabilities' must be a frozenset, "
            f"got {type(capabilities).__name__}"
        )
    bad_members = [c for c in capabilities if not isinstance(c, Capability)]
    if bad_members:
        bad_repr = ", ".join(repr(m) for m in bad_members)
        raise TypeError(
            f"provider {identity}: 'capabilities' must contain only "
            f"Capability members; got non-Capability element(s): {bad_repr}"
        )


__all__ = [
    "BaseProvider",
    "validate_provider",
    "validate_provider_name",
]
