"""Unit tests for ``mureo.core.skills.matcher`` (RED phase, Issue #89 P1-08).

These tests pin the pure-function contracts of:

- :func:`match_skills` — classify an iterable of :class:`SkillEntry` against
  one :class:`ProviderEntry` into ``executable`` / ``advisory_only`` /
  ``unavailable`` buckets.
- :func:`providers_for_skill` — the inverse: classify the providers in a
  :class:`Registry` against one skill, returning a parallel
  :class:`ProviderMatch` shaped result.

Marks: every test is ``@pytest.mark.unit`` — pure logic, no I/O, no
mocks (real :class:`Capability` members + constructed dataclasses).

NOTE: these imports are expected to FAIL during the RED phase — the
module ``mureo.core.skills.matcher`` does not exist yet.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mureo.core.providers.capabilities import Capability
from mureo.core.providers.registry import ProviderEntry, Registry
from mureo.core.skills.matcher import (  # noqa: E402 — RED-phase import
    ProviderMatch,
    SkillMatch,
    match_skills,
    providers_for_skill,
)
from mureo.core.skills.models import SkillEntry  # noqa: E402 — RED-phase import

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _skill(
    name: str,
    *,
    required: frozenset[Capability] = frozenset(),
    advisory: frozenset[Capability] = frozenset(),
) -> SkillEntry:
    return SkillEntry(
        name=name,
        description=f"Skill {name}.",
        required_capabilities=required,
        advisory_mode_capabilities=advisory,
        source_path=Path(f"/tmp/skills/{name}/SKILL.md"),
        source_distribution=None,
    )


class _FakeProvider:
    """Stand-in provider class for :class:`ProviderEntry` construction."""

    name = "p"
    display_name = "P"
    capabilities = frozenset()  # overridden per-entry


def _provider(name: str, caps: frozenset[Capability]) -> ProviderEntry:
    return ProviderEntry(
        name=name,
        display_name=name.replace("_", " ").title(),
        capabilities=caps,
        provider_class=_FakeProvider,
        source_distribution=None,
    )


# ---------------------------------------------------------------------------
# match_skills — Case 1: executable when required ⊆ provider.capabilities
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_executable_when_required_subset_of_provider() -> None:
    """Skill needs ``{READ_CAMPAIGNS}`` and provider has
    ``{READ_CAMPAIGNS, READ_PERFORMANCE}`` → ``executable``.
    """
    skill = _skill("s1", required=frozenset({Capability.READ_CAMPAIGNS}))
    provider = _provider(
        "p1",
        frozenset({Capability.READ_CAMPAIGNS, Capability.READ_PERFORMANCE}),
    )

    result = match_skills([skill], provider)

    assert result.executable == (skill,)
    assert result.advisory_only == ()
    assert result.unavailable == ()


# ---------------------------------------------------------------------------
# match_skills — Case 2: advisory_only
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_advisory_only_when_advisory_subset_but_required_not() -> None:
    """Skill needs ``{READ_CAMPAIGNS, WRITE_BUDGET}``, advisory
    ``{READ_CAMPAIGNS}``; provider has only ``{READ_CAMPAIGNS}`` →
    ``advisory_only``.
    """
    skill = _skill(
        "s1",
        required=frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET}),
        advisory=frozenset({Capability.READ_CAMPAIGNS}),
    )
    provider = _provider("p1", frozenset({Capability.READ_CAMPAIGNS}))

    result = match_skills([skill], provider)

    assert result.executable == ()
    assert result.advisory_only == (skill,)
    assert result.unavailable == ()


# ---------------------------------------------------------------------------
# match_skills — Case 3: unavailable when neither
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_unavailable_when_neither_matches() -> None:
    """Skill needs ``{WRITE_BUDGET}`` (no advisory); provider has
    ``{READ_CAMPAIGNS}`` → ``unavailable``.
    """
    skill = _skill("s1", required=frozenset({Capability.WRITE_BUDGET}))
    provider = _provider("p1", frozenset({Capability.READ_CAMPAIGNS}))

    result = match_skills([skill], provider)

    assert result.executable == ()
    assert result.advisory_only == ()
    assert result.unavailable == (skill,)


# ---------------------------------------------------------------------------
# match_skills — Case 4: empty required → executable everywhere (regression)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_empty_required_is_always_executable() -> None:
    """Skills with no declared ``required_capabilities`` are always
    executable regardless of provider. Critical regression guard for the
    16 existing in-tree SKILL.md files (none of them declare capabilities
    in Phase 1).
    """
    skill = _skill("legacy", required=frozenset(), advisory=frozenset())

    # Two extreme providers: one with no caps at all, one with all caps.
    bare_provider = _provider("bare", frozenset())
    fully_loaded = _provider("full", frozenset(Capability))

    assert match_skills([skill], bare_provider).executable == (skill,)
    assert match_skills([skill], fully_loaded).executable == (skill,)


# ---------------------------------------------------------------------------
# match_skills — Case 5: empty input iterable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_empty_input() -> None:
    """An empty iterable yields ``SkillMatch((), (), ())``."""
    provider = _provider("p1", frozenset({Capability.READ_CAMPAIGNS}))

    result = match_skills([], provider)

    assert result.executable == ()
    assert result.advisory_only == ()
    assert result.unavailable == ()


# ---------------------------------------------------------------------------
# match_skills — Case 6: deterministic ordering (sorted by name asc)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_match_skills_buckets_sorted_by_name() -> None:
    """Each bucket is sorted by ``name`` ascending regardless of input
    order.
    """
    s_zeta = _skill("zeta", required=frozenset({Capability.READ_CAMPAIGNS}))
    s_alpha = _skill("alpha", required=frozenset({Capability.READ_CAMPAIGNS}))
    s_mid = _skill("mid", required=frozenset({Capability.READ_CAMPAIGNS}))
    provider = _provider("p1", frozenset({Capability.READ_CAMPAIGNS}))

    result = match_skills([s_zeta, s_alpha, s_mid], provider)

    # All three are executable for this provider; check sort order.
    assert result.executable == (s_alpha, s_mid, s_zeta)


# ---------------------------------------------------------------------------
# match_skills — Case 7: SkillMatch is immutable
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skill_match_is_frozen() -> None:
    """Assigning to a field on :class:`SkillMatch` raises
    :class:`FrozenInstanceError`.
    """
    sm = SkillMatch(executable=(), advisory_only=(), unavailable=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        sm.executable = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# providers_for_skill — Case 8: pure read skill across mixed registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_providers_for_skill_pure_read_across_mixed_registry() -> None:
    """Skill needs ``{READ_CAMPAIGNS}``; registry has three providers
    (read-only, read+write, write-only). Result: 2 executable, 0
    advisory, 1 unavailable.
    """
    skill = _skill("read-only", required=frozenset({Capability.READ_CAMPAIGNS}))
    reg = Registry()
    p_read = _provider("p_read", frozenset({Capability.READ_CAMPAIGNS}))
    p_rw = _provider(
        "p_rw",
        frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET}),
    )
    p_write = _provider("p_write", frozenset({Capability.WRITE_BUDGET}))
    reg.register(p_read)
    reg.register(p_rw)
    reg.register(p_write)

    result = providers_for_skill(skill, reg)

    assert isinstance(result, ProviderMatch)
    assert set(result.executable) == {p_read, p_rw}
    assert result.advisory_only == ()
    assert result.unavailable == (p_write,)
    # Sorted by name ascending.
    assert result.executable == tuple(sorted({p_read, p_rw}, key=lambda e: e.name))


# ---------------------------------------------------------------------------
# providers_for_skill — Case 9: advisory split
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_providers_for_skill_advisory_bucket() -> None:
    """Skill needs ``{READ_CAMPAIGNS, WRITE_BUDGET}``, advisory
    ``{READ_CAMPAIGNS}``. A provider with only ``{READ_CAMPAIGNS}`` lands
    in ``advisory_only``.
    """
    skill = _skill(
        "advisory-skill",
        required=frozenset({Capability.READ_CAMPAIGNS, Capability.WRITE_BUDGET}),
        advisory=frozenset({Capability.READ_CAMPAIGNS}),
    )
    reg = Registry()
    p_read = _provider("p_read", frozenset({Capability.READ_CAMPAIGNS}))
    reg.register(p_read)

    result = providers_for_skill(skill, reg)

    assert result.executable == ()
    assert result.advisory_only == (p_read,)
    assert result.unavailable == ()


# ---------------------------------------------------------------------------
# providers_for_skill — Case 10: empty registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_providers_for_skill_empty_registry() -> None:
    """An empty registry yields ``ProviderMatch((), (), ())``."""
    skill = _skill("any", required=frozenset({Capability.READ_CAMPAIGNS}))
    reg = Registry()

    result = providers_for_skill(skill, reg)

    assert result.executable == ()
    assert result.advisory_only == ()
    assert result.unavailable == ()
