"""Frozen data model for a parsed mureo skill (Issue #89 P1-08).

Public surface
--------------
- :class:`SkillEntry` — immutable record describing one parsed
  ``SKILL.md`` file. Construct via :func:`mureo.core.skills.parse_skill_md`
  or manually in tests; both paths enforce the same invariants.

Name regex divergence
---------------------
Skill names obey ``^_?[a-z][a-z0-9_-]*$`` (leading underscore + hyphens
allowed). Provider names obey ``^[a-z][a-z0-9_]*$`` (snake_case only).
The divergence is deliberate: the 16 shipped in-tree skills already use
``daily-check`` and ``_mureo-shared`` style names, while provider names
are exposed as Python identifiers in tool prefixes.

Untrusted ``source_distribution``
---------------------------------
``source_distribution`` is the PEP 503 normalized pip package name that
supplied the skill via the ``mureo.skills`` entry-points group. Treat it
as **untrusted display data** — never interpolate it into shell commands,
SQL, log-injection-sensitive sinks, or paths.

Foundation rule
---------------
Only imports :class:`Capability` from
:mod:`mureo.core.providers.capabilities`. No imports from registry,
domain Protocols, or anything outside the providers foundation.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from mureo.core.providers.capabilities import Capability

# Empty read-only Mapping used as the default value for ``SkillEntry.extra``.
# A module-level constant guarantees every default-constructed instance shares
# the same identity-stable, write-locked mapping (no per-instance allocation
# and no risk of leaking a mutable default across instances).
_EMPTY_EXTRA: Final[Mapping[str, Any]] = MappingProxyType({})

# ``^_?[a-z][a-z0-9_-]*$``: optional single leading underscore, then a
# lowercase letter, then any mix of lowercase letters, digits, underscores,
# and hyphens. Double leading underscore is intentionally rejected.
_SKILL_NAME_REGEX: Final[re.Pattern[str]] = re.compile(r"^_?[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class SkillEntry:
    """Frozen record describing one parsed ``SKILL.md`` file.

    Attributes:
        name: Skill identifier matching ``^_?[a-z][a-z0-9_-]*$``. The
            optional leading underscore and embedded hyphens are
            permitted to match the 16 shipped in-tree skills.
        description: Non-empty human-readable description from the
            ``description`` frontmatter key.
        required_capabilities: :class:`frozenset` of
            :class:`Capability` members the skill needs to execute fully.
            Empty when the skill declares no ``capabilities`` block.
        advisory_mode_capabilities: Subset of ``required_capabilities``
            sufficient to produce useful advisory output when a provider
            cannot satisfy the full ``required`` set. Empty when no
            advisory mode is declared.
        source_path: Absolute :class:`Path` to the originating
            ``SKILL.md`` file. Parser resolves this before construction.
        source_distribution: Pip distribution name when the skill came
            from a ``mureo.skills`` entry point, ``None`` for built-ins
            and tests. Treat as untrusted display data.
        extra: Read-only :class:`Mapping` of forward-compatible
            top-level frontmatter keys that the parser did not consume
            (i.e. anything other than ``name``, ``description``,
            ``capabilities``, ``advisory_mode_capabilities``). Used to
            preserve metadata such as the ``metadata.version`` /
            ``metadata.openclaw`` blocks already present in the 16
            shipped in-tree SKILL.md files. ``__post_init__`` wraps the
            incoming mapping in a :class:`types.MappingProxyType` so
            the frozen invariant extends to this field too — callers
            cannot mutate it post-construction. Treat as untrusted
            data: it comes from third-party SKILL.md content.
    """

    name: str
    description: str
    required_capabilities: frozenset[Capability]
    advisory_mode_capabilities: frozenset[Capability]
    source_path: Path
    source_distribution: str | None
    # ``extra`` carries forward-compatible frontmatter (e.g. ``metadata``
    # blocks) and intentionally does NOT participate in equality or
    # hashing — two skills with the same identity/capabilities but a
    # bumped ``metadata.version`` must still be considered the same
    # SkillEntry for deduplication purposes. ``compare=False`` excludes
    # it from both ``__eq__`` and the dataclass-generated ``__hash__``,
    # which is also necessary because :class:`types.MappingProxyType`
    # is not hashable.
    extra: Mapping[str, Any] = field(
        default_factory=lambda: _EMPTY_EXTRA, compare=False
    )

    def __post_init__(self) -> None:
        """Validate every field at construction.

        Raises:
            TypeError: a field has the wrong type (e.g. a plain ``set``
                instead of ``frozenset`` for capabilities).
            ValueError: ``name`` fails the regex, ``description`` is
                empty, ``source_path`` is not absolute, or
                ``advisory_mode_capabilities`` is not a subset of
                ``required_capabilities``.
        """
        self._validate_name()
        self._validate_description()
        self._validate_capabilities()
        self._validate_source_path()
        self._validate_source_distribution()
        self._wrap_extra()

    def _validate_name(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError(
                f"SkillEntry.name must be str, got {type(self.name).__name__}"
            )
        if not _SKILL_NAME_REGEX.match(self.name):
            raise ValueError(
                f"SkillEntry.name {self.name!r} does not match "
                f"{_SKILL_NAME_REGEX.pattern!r}"
            )

    def _validate_description(self) -> None:
        if not isinstance(self.description, str):
            raise TypeError(
                f"SkillEntry.description must be str, "
                f"got {type(self.description).__name__}"
            )
        if self.description == "":
            raise ValueError("SkillEntry.description must be a non-empty string")

    def _validate_capabilities(self) -> None:
        if not isinstance(self.required_capabilities, frozenset):
            raise TypeError(
                f"SkillEntry.required_capabilities must be a frozenset, "
                f"got {type(self.required_capabilities).__name__}"
            )
        if not isinstance(self.advisory_mode_capabilities, frozenset):
            raise TypeError(
                f"SkillEntry.advisory_mode_capabilities must be a frozenset, "
                f"got {type(self.advisory_mode_capabilities).__name__}"
            )
        bad_req = [
            c for c in self.required_capabilities if not isinstance(c, Capability)
        ]
        bad_adv = [
            c for c in self.advisory_mode_capabilities if not isinstance(c, Capability)
        ]
        if bad_req or bad_adv:
            bad = bad_req + bad_adv
            raise TypeError(
                f"SkillEntry capabilities must contain only Capability "
                f"members; got non-Capability element(s): "
                f"{', '.join(repr(m) for m in bad)}"
            )
        if not self.advisory_mode_capabilities <= self.required_capabilities:
            extra = self.advisory_mode_capabilities - self.required_capabilities
            raise ValueError(
                f"SkillEntry.advisory_mode_capabilities must be a subset of "
                f"required_capabilities; extra: "
                f"{sorted(str(c) for c in extra)}"
            )

    def _validate_source_path(self) -> None:
        if not isinstance(self.source_path, Path):
            raise TypeError(
                f"SkillEntry.source_path must be a pathlib.Path, "
                f"got {type(self.source_path).__name__}"
            )
        if not self.source_path.is_absolute():
            raise ValueError(
                f"SkillEntry.source_path must be absolute, got {self.source_path!s}"
            )

    def _validate_source_distribution(self) -> None:
        if self.source_distribution is not None and not isinstance(
            self.source_distribution, str
        ):
            raise TypeError(
                f"SkillEntry.source_distribution must be str | None, "
                f"got {type(self.source_distribution).__name__}"
            )

    def _wrap_extra(self) -> None:
        """Type-check ``extra`` and wrap it in a :class:`MappingProxyType`.

        The wrap is what extends the frozen-dataclass invariant to this
        field: even though :class:`Mapping` itself is read-only by
        protocol, callers may have passed a plain ``dict`` (which is
        mutable). After wrapping, attempts to assign to keys via
        ``entry.extra["foo"] = ...`` raise :class:`TypeError`.

        We use ``object.__setattr__`` because the dataclass is frozen —
        ordinary attribute assignment is rejected by
        ``__setattr__`` even from inside ``__post_init__``.
        """
        if not isinstance(self.extra, Mapping):
            raise TypeError(
                f"SkillEntry.extra must be a Mapping, "
                f"got {type(self.extra).__name__}"
            )
        # Re-wrap regardless of input type. ``MappingProxyType`` over an
        # existing ``MappingProxyType`` is idempotent in behaviour (still
        # read-only over the same underlying dict).
        bad_keys = [k for k in self.extra if not isinstance(k, str)]
        if bad_keys:
            raise TypeError(
                f"SkillEntry.extra keys must be str; got non-str key(s): "
                f"{', '.join(repr(k) for k in bad_keys)}"
            )
        # Snapshot into a fresh dict so callers cannot mutate the original
        # ``extra`` argument and see the change reflected inside the entry.
        snapshot: dict[str, Any] = dict(self.extra)
        object.__setattr__(self, "extra", MappingProxyType(snapshot))


__all__ = ["SkillEntry"]
