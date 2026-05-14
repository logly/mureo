"""Skill × provider capability matching (Issue #89 P1-08).

Two pure functions form the public surface:

- :func:`match_skills` — given an iterable of :class:`SkillEntry` and
  one :class:`ProviderEntry`, classify each skill into one of three
  buckets: ``executable`` / ``advisory_only`` / ``unavailable``.
- :func:`providers_for_skill` — the inverse: given one skill and a
  :class:`Registry`, classify each provider into the same three
  buckets, returned as a :class:`ProviderMatch` for type clarity.

Classification rules (single source of truth)
---------------------------------------------
- A skill is **executable** against a provider iff
  ``skill.required_capabilities <= provider.capabilities``.
  Skills with an empty ``required_capabilities`` are executable against
  every provider — this is the regression contract for the 16 shipped
  in-tree SKILL.md files (none of them declare ``capabilities`` yet).
- A skill is **advisory_only** when it is NOT executable AND
  ``skill.advisory_mode_capabilities`` is non-empty AND
  ``skill.advisory_mode_capabilities <= provider.capabilities``.
- A skill is **unavailable** otherwise.

Ordering
--------
All output tuples are sorted by ``name`` ascending so callers get
deterministic results.

Foundation rule
---------------
Only imports :class:`ProviderEntry` / :class:`Registry` from
:mod:`mureo.core.providers.registry` and :class:`SkillEntry` from
:mod:`mureo.core.skills.models`. No domain Protocol imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mureo.core.providers.registry import ProviderEntry, Registry
    from mureo.core.skills.models import SkillEntry


@dataclass(frozen=True)
class SkillMatch:
    """Three-bucket classification of skills against one provider.

    All three tuples are sorted by :attr:`SkillEntry.name` ascending.

    Attributes:
        executable: Skills whose ``required_capabilities`` are a subset
            of the provider's capabilities (or that declare no
            requirements at all).
        advisory_only: Skills the provider cannot execute in full but
            can serve in advisory mode.
        unavailable: Skills the provider cannot serve at all.
    """

    executable: tuple[SkillEntry, ...]
    advisory_only: tuple[SkillEntry, ...]
    unavailable: tuple[SkillEntry, ...]


@dataclass(frozen=True)
class ProviderMatch:
    """Three-bucket classification of providers against one skill.

    Mirror of :class:`SkillMatch` for the inverse query
    (:func:`providers_for_skill`). All three tuples are sorted by
    :attr:`ProviderEntry.name` ascending.

    Attributes:
        executable: Providers that satisfy the skill's
            ``required_capabilities`` in full.
        advisory_only: Providers that cannot fully execute the skill
            but satisfy its declared ``advisory_mode_capabilities``.
        unavailable: Providers that cannot serve the skill at all.
    """

    executable: tuple[ProviderEntry, ...]
    advisory_only: tuple[ProviderEntry, ...]
    unavailable: tuple[ProviderEntry, ...]


def match_skills(skills: Iterable[SkillEntry], provider: ProviderEntry) -> SkillMatch:
    """Classify ``skills`` against ``provider``'s capabilities.

    Pure function — no I/O, no mutation. See module docstring for the
    classification rules.

    Args:
        skills: Iterable of :class:`SkillEntry`. May be empty.
        provider: A :class:`ProviderEntry` from the registry.

    Returns:
        A :class:`SkillMatch` with three sorted tuples.
    """
    provider_caps = provider.capabilities
    executable: list[SkillEntry] = []
    advisory: list[SkillEntry] = []
    unavailable: list[SkillEntry] = []

    for skill in skills:
        if skill.required_capabilities <= provider_caps:
            executable.append(skill)
        elif (
            skill.advisory_mode_capabilities
            and skill.advisory_mode_capabilities <= provider_caps
        ):
            advisory.append(skill)
        else:
            unavailable.append(skill)

    executable.sort(key=lambda s: s.name)
    advisory.sort(key=lambda s: s.name)
    unavailable.sort(key=lambda s: s.name)
    return SkillMatch(
        executable=tuple(executable),
        advisory_only=tuple(advisory),
        unavailable=tuple(unavailable),
    )


def providers_for_skill(skill: SkillEntry, registry: Registry) -> ProviderMatch:
    """Classify every provider in ``registry`` against one skill.

    Pure function — iterates ``registry`` read-only via ``__iter__``;
    does not mutate the registry, does not instantiate any provider
    class.

    Args:
        skill: The :class:`SkillEntry` to query.
        registry: A :class:`Registry` (or any iterable of
            :class:`ProviderEntry`, since the implementation only uses
            ``__iter__``).

    Returns:
        A :class:`ProviderMatch` with three tuples sorted by provider
        name ascending.
    """
    required = skill.required_capabilities
    advisory_caps = skill.advisory_mode_capabilities

    executable: list[ProviderEntry] = []
    advisory: list[ProviderEntry] = []
    unavailable: list[ProviderEntry] = []

    for provider in registry:
        provider_caps = provider.capabilities
        if required <= provider_caps:
            executable.append(provider)
        elif advisory_caps and advisory_caps <= provider_caps:
            advisory.append(provider)
        else:
            unavailable.append(provider)

    executable.sort(key=lambda p: p.name)
    advisory.sort(key=lambda p: p.name)
    unavailable.sort(key=lambda p: p.name)
    return ProviderMatch(
        executable=tuple(executable),
        advisory_only=tuple(advisory),
        unavailable=tuple(unavailable),
    )


__all__ = [
    "ProviderMatch",
    "SkillMatch",
    "match_skills",
    "providers_for_skill",
]
