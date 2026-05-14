"""Unit tests for ``mureo.core.skills.models.SkillEntry`` (RED phase, P1-08).

These tests pin the invariants of the :class:`SkillEntry` frozen
dataclass — types, regex on ``name``, ``advisory_mode`` ⊆ ``required``,
absolute ``source_path``, immutability, and hashability.

Marks: every test is ``@pytest.mark.unit``.

NOTE: these imports are expected to FAIL during the RED phase — the
module ``mureo.core.skills.models`` does not exist yet.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

import pytest

from mureo.core.providers.capabilities import Capability
from mureo.core.skills.models import SkillEntry  # noqa: E402 — RED-phase import

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build(
    *,
    name: str = "valid-skill",
    description: str = "A valid skill.",
    required: frozenset[Capability] = frozenset(),
    advisory: frozenset[Capability] = frozenset(),
    source_path: Path | None = None,
    source_distribution: str | None = None,
) -> SkillEntry:
    if source_path is None:
        source_path = Path("/tmp/skills/valid-skill/SKILL.md")
    return SkillEntry(
        name=name,
        description=description,
        required_capabilities=required,
        advisory_mode_capabilities=advisory,
        source_path=source_path,
        source_distribution=source_distribution,
    )


# ---------------------------------------------------------------------------
# Case 1 — valid construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_valid_construction() -> None:
    """All six fields well-typed: construction succeeds and round-trips."""
    entry = _build(
        name="cap-skill",
        description="Declares one cap.",
        required=frozenset({Capability.READ_CAMPAIGNS}),
        advisory=frozenset({Capability.READ_CAMPAIGNS}),
        source_path=Path("/tmp/skills/cap-skill/SKILL.md"),
        source_distribution="mureo",
    )

    assert entry.name == "cap-skill"
    assert entry.description == "Declares one cap."
    assert entry.required_capabilities == frozenset({Capability.READ_CAMPAIGNS})
    assert entry.advisory_mode_capabilities == frozenset({Capability.READ_CAMPAIGNS})
    assert entry.source_path == Path("/tmp/skills/cap-skill/SKILL.md")
    assert entry.source_distribution == "mureo"


# ---------------------------------------------------------------------------
# Case 2 — frozen mutation rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_frozen_mutation_rejected() -> None:
    """Assigning to a field on a constructed ``SkillEntry`` raises
    :class:`dataclasses.FrozenInstanceError`.
    """
    entry = _build()
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Case 3 — advisory must be a subset of required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_advisory_must_be_subset_of_required() -> None:
    """``__post_init__`` raises :class:`ValueError` when
    ``advisory_mode_capabilities`` is not a subset of
    ``required_capabilities``.
    """
    with pytest.raises(ValueError):
        _build(
            required=frozenset({Capability.READ_CAMPAIGNS}),
            advisory=frozenset({Capability.READ_PERFORMANCE}),
        )


# ---------------------------------------------------------------------------
# Case 4 — non-frozenset capabilities rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_frozenset_capabilities_rejected() -> None:
    """Passing a plain ``set`` (mutable) for ``required_capabilities``
    raises :class:`TypeError`.
    """
    with pytest.raises(TypeError):
        SkillEntry(
            name="bad",
            description="bad",
            required_capabilities={Capability.READ_CAMPAIGNS},  # type: ignore[arg-type]
            advisory_mode_capabilities=frozenset(),
            source_path=Path("/tmp/skills/bad/SKILL.md"),
            source_distribution=None,
        )


# ---------------------------------------------------------------------------
# Case 5 — non-absolute path rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_non_absolute_path_rejected() -> None:
    """``source_path`` must be absolute; relative paths raise
    :class:`ValueError`.
    """
    with pytest.raises(ValueError):
        _build(source_path=Path("rel/path/SKILL.md"))


# ---------------------------------------------------------------------------
# Case 6 — invalid name regex rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_name",
    [
        "BadName",  # uppercase
        "1leading-digit",
        "spaces here",
        "exclaim!",
        "",
        "-leading-hyphen",
        "__double_underscore",
    ],
)
def test_invalid_name_rejected(bad_name: str) -> None:
    """Names that do not match ``^_?[a-z][a-z0-9_-]*$`` raise
    :class:`ValueError`.
    """
    with pytest.raises(ValueError):
        _build(name=bad_name)


# ---------------------------------------------------------------------------
# Case 7 — empty description rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_description_rejected() -> None:
    """``description`` must be a non-empty string; empty raises
    :class:`ValueError`.
    """
    with pytest.raises(ValueError):
        _build(description="")


# ---------------------------------------------------------------------------
# Case 8 — equality + hashability
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_equality_and_hashability() -> None:
    """Two ``SkillEntry`` instances with identical fields compare equal,
    hash equal, and can be inserted into a ``set``.
    """
    a = _build()
    b = _build()

    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


# ---------------------------------------------------------------------------
# Case 9 — ``extra`` defaults to an empty read-only Mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extra_defaults_to_empty_mapping() -> None:
    """When ``extra`` is not supplied, it is a ``Mapping`` with zero keys
    and rejects writes (the frozen invariant must extend to ``extra``).
    """
    entry = _build()

    assert isinstance(entry.extra, Mapping)
    assert len(entry.extra) == 0
    with pytest.raises(TypeError):
        entry.extra["new"] = "value"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Case 10 — ``extra`` preserves supplied keys but rejects post-construction mutation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extra_preserves_keys_and_is_read_only() -> None:
    """A non-empty ``extra`` mapping survives construction unchanged but
    becomes write-locked. Mutating the *original* dict the caller passed
    must NOT change the entry's view.
    """
    payload = {"metadata": {"version": "0.7.1"}, "openclaw": {"category": "ads"}}

    entry = SkillEntry(
        name="extra-skill",
        description="Carries forward-compat metadata.",
        required_capabilities=frozenset(),
        advisory_mode_capabilities=frozenset(),
        source_path=Path("/tmp/skills/extra-skill/SKILL.md"),
        source_distribution=None,
        extra=payload,
    )

    # Round-trip: every key supplied is present.
    assert entry.extra["metadata"] == {"version": "0.7.1"}
    assert entry.extra["openclaw"] == {"category": "ads"}

    # The view is read-only.
    with pytest.raises(TypeError):
        entry.extra["pwn"] = "owned"  # type: ignore[index]

    # Caller mutation of the original dict must not leak into the entry.
    payload["pwn"] = "owned"
    assert "pwn" not in entry.extra


# ---------------------------------------------------------------------------
# Case 11 — non-Mapping ``extra`` rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extra_must_be_mapping() -> None:
    """Passing a non-``Mapping`` (e.g. a list) for ``extra`` raises
    :class:`TypeError`.
    """
    with pytest.raises(TypeError):
        SkillEntry(
            name="bad-extra",
            description="bad",
            required_capabilities=frozenset(),
            advisory_mode_capabilities=frozenset(),
            source_path=Path("/tmp/skills/bad-extra/SKILL.md"),
            source_distribution=None,
            extra=["not", "a", "mapping"],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Case 12 — non-str ``extra`` keys rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extra_keys_must_be_strings() -> None:
    """Frontmatter is YAML, but the parser hands the parser a dict that
    *should* be ``Mapping[str, Any]``. Defence in depth: a YAML mapping
    with non-string keys (e.g. integer keys) is rejected at construction.
    """
    with pytest.raises(TypeError):
        SkillEntry(
            name="bad-extra-keys",
            description="bad",
            required_capabilities=frozenset(),
            advisory_mode_capabilities=frozenset(),
            source_path=Path("/tmp/skills/bad-extra-keys/SKILL.md"),
            source_distribution=None,
            extra={1: "int key not allowed"},  # type: ignore[dict-item]
        )


# ---------------------------------------------------------------------------
# Case 13 — ``extra`` is excluded from equality + hashing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extra_does_not_affect_equality_or_hash() -> None:
    """Two ``SkillEntry`` instances that differ ONLY in ``extra`` (e.g.
    a bumped ``metadata.version``) compare equal and hash equal. This
    keeps the dedup behaviour in
    :func:`mureo.core.skills.discover_skills` stable across
    forward-compat metadata churn.
    """
    base_kwargs = {
        "name": "same-skill",
        "description": "same desc",
        "required_capabilities": frozenset(),
        "advisory_mode_capabilities": frozenset(),
        "source_path": Path("/tmp/skills/same-skill/SKILL.md"),
        "source_distribution": None,
    }
    a = SkillEntry(**base_kwargs, extra={"metadata": {"version": "0.1.0"}})
    b = SkillEntry(**base_kwargs, extra={"metadata": {"version": "0.2.0"}})

    assert a == b
    assert hash(a) == hash(b)
