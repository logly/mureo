"""SKILL.md frontmatter parser (Issue #89 P1-08).

Parses a single ``SKILL.md`` file from disk and returns a frozen
:class:`SkillEntry`. Every decode / YAML / validation failure is wrapped
in :class:`SkillParseError` so callers (notably
:func:`mureo.core.skills.discover_skills`) can isolate per-file faults
without catching :class:`Exception` directly.

Security posture
----------------
SKILL.md content is shipped by third-party pip plugins via the
``mureo.skills`` entry-points group — the same trust boundary as the
provider registry, extended to data-as-code. The parser mitigates the
risk by:

1. **YAML safety**: ``yaml.safe_load`` only — never ``yaml.load`` or
   ``yaml.unsafe_load``. A YAML tag such as
   ``!!python/object/apply:os.system [...]`` is rejected by
   ``safe_load`` and wrapped in :class:`SkillParseError`.
2. **Bounded input**: 64 KiB max file size enforced *before* the YAML
   parser runs. Guards against memory-exhaustion DoS.
3. **UTF-8 strict decode**: ``errors="strict"``; hostile non-UTF-8
   bytes are rejected, not silently mangled.
4. **No code execution**: the parser does not ``exec`` anything, does
   not import anything from the SKILL.md, does not follow external
   references. Frontmatter is pure data.
5. **Frontmatter must be at the start of the file**: a stray ``---`` on
   line 3 does NOT count as a delimiter.

Foundation rule
---------------
Imports are restricted to :mod:`mureo.core.providers.capabilities` and
:mod:`mureo.core.skills.models`. No registry imports, no domain
Protocol imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import yaml

from mureo.core.providers.capabilities import parse_capabilities
from mureo.core.skills.models import SkillEntry

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.core.providers.capabilities import Capability

# 64 KiB cap on raw on-disk file size, enforced before any YAML parse.
# Bumping this is a one-line change; documented in the planner HANDOFF.
MAX_SKILL_FILE_BYTES: Final[int] = 64 * 1024

# Frontmatter is delimited by lines containing exactly ``---``. The
# opening delimiter MUST be the first line of the file; the closing
# delimiter is the next line that is exactly ``---``.
_FRONTMATTER_DELIM: Final[str] = "---"

# Top-level frontmatter keys consumed by the parser. Anything not in
# this set is shovelled into :attr:`SkillEntry.extra` for forward
# compatibility (e.g. ``metadata`` blocks shipped by the 16 in-tree
# SKILL.md files).
_RESERVED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {"name", "description", "capabilities", "advisory_mode_capabilities"}
)


class SkillParseError(ValueError):
    """Raised when a SKILL.md file cannot be parsed.

    Subclasses :class:`ValueError` (not :class:`Exception` directly) so
    callers that already handle ``ValueError`` for capability parsing
    keep working without changes. The message includes the offending
    file path when available.
    """


def parse_skill_md(path: Path) -> SkillEntry:
    """Read ``path`` and return the parsed :class:`SkillEntry`.

    Args:
        path: Absolute path to a ``SKILL.md`` file on disk.

    Returns:
        A frozen :class:`SkillEntry` whose ``source_path`` is the
        resolved absolute form of ``path`` and ``source_distribution``
        is ``None`` (discovery sets the distribution name; the parser
        does not know it).

    Raises:
        SkillParseError: any of: file exceeds
            :data:`MAX_SKILL_FILE_BYTES`, invalid UTF-8 byte sequence,
            missing or malformed frontmatter delimiters, missing
            required ``name`` / ``description`` keys, ``name`` fails the
            regex, unknown capability token, ``advisory_mode`` not a
            subset of ``required``, or any YAML parser error.
    """
    resolved = path.resolve()
    raw = _read_bounded(resolved)
    body = _decode_utf8(resolved, raw)
    frontmatter_text = _extract_frontmatter(resolved, body)
    data = _parse_yaml(resolved, frontmatter_text)
    return _build_entry(resolved, data)


def _read_bounded(path: Path) -> bytes:
    """Read ``path`` as bytes, rejecting files larger than the cap.

    The size check uses :meth:`Path.stat` first (cheap, no read) so a
    multi-gigabyte hostile file does not even enter memory.
    """
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SkillParseError(f"cannot stat SKILL.md at {path!s}: {exc}") from exc
    if size > MAX_SKILL_FILE_BYTES:
        raise SkillParseError(
            f"SKILL.md at {path!s} exceeds maximum size of "
            f"{MAX_SKILL_FILE_BYTES} bytes (got {size} bytes); rejected "
            f"before YAML parse"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SkillParseError(f"cannot read SKILL.md at {path!s}: {exc}") from exc


def _decode_utf8(path: Path, raw: bytes) -> str:
    """Decode ``raw`` as UTF-8 with ``errors='strict'``.

    A leading UTF-8 BOM (``U+FEFF``) is stripped immediately after
    decode. Some Windows editors (Notepad, older VS Code with
    auto-detect) silently prepend a BOM when saving UTF-8 files; the
    BOM would otherwise push the ``---`` frontmatter delimiter past
    the start-of-file invariant in :func:`_extract_frontmatter` and
    surface as a confusing "missing frontmatter" error.
    """
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SkillParseError(
            f"SKILL.md at {path!s} is not valid UTF-8: {exc}"
        ) from exc
    return decoded.lstrip("﻿")


def _extract_frontmatter(path: Path, body: str) -> str:
    """Return the YAML frontmatter text between leading ``---`` lines.

    The opening delimiter must be the FIRST line of the file. A
    ``---`` appearing on any later line without a preceding opener at
    line 1 does NOT count as a delimiter — this rejects files that try
    to sneak frontmatter past a leading comment block.

    Coupling note: ``splitlines()`` runs on the full decoded body in
    memory. The cost is currently bounded by the 64 KiB upstream cap
    (:data:`MAX_SKILL_FILE_BYTES`). Raising ``MAX_SKILL_FILE_BYTES``
    requires an audit of both the decode and splitlines memory cost
    before merging.
    """
    lines = body.splitlines()
    if not lines or lines[0].rstrip() != _FRONTMATTER_DELIM:
        raise SkillParseError(
            f"SKILL.md at {path!s} is missing a leading {_FRONTMATTER_DELIM!r} "
            f"frontmatter delimiter on line 1"
        )
    # Find the closing delimiter starting from line 2 (index 1).
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == _FRONTMATTER_DELIM:
            return "\n".join(lines[1:idx])
    raise SkillParseError(
        f"SKILL.md at {path!s} has an opening {_FRONTMATTER_DELIM!r} but no "
        f"closing frontmatter delimiter"
    )


def _parse_yaml(path: Path, text: str) -> dict[str, Any]:
    """Run ``yaml.safe_load`` on the frontmatter text.

    Returns a mapping; rejects non-mapping / non-dict YAML documents.
    Wraps every ``yaml.YAMLError`` (including the ``ConstructorError``
    raised on rejected ``!!python/object`` tags) in
    :class:`SkillParseError`.
    """
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SkillParseError(
            f"SKILL.md at {path!s} has malformed YAML frontmatter: {exc}"
        ) from exc
    if loaded is None:
        # Empty frontmatter block — treat as an empty mapping so we hit
        # the "missing required key 'name'" branch with a clearer error.
        return {}
    if not isinstance(loaded, dict):
        raise SkillParseError(
            f"SKILL.md at {path!s} frontmatter must be a YAML mapping, "
            f"got {type(loaded).__name__}"
        )
    return loaded


def _build_entry(path: Path, data: dict[str, Any]) -> SkillEntry:
    """Validate required fields, parse capabilities, and construct."""
    name = _require_str(path, data, key="name")
    description = _require_str(path, data, key="description")
    if description == "":
        raise SkillParseError(
            f"SKILL.md at {path!s}: 'description' must be a non-empty string"
        )

    required_caps, advisory_caps = _parse_capabilities_block(path, data)
    extra = {k: v for k, v in data.items() if k not in _RESERVED_TOP_LEVEL_KEYS}

    try:
        return SkillEntry(
            name=name,
            description=description,
            required_capabilities=required_caps,
            advisory_mode_capabilities=advisory_caps,
            source_path=path,
            source_distribution=None,
            extra=extra,
        )
    except (TypeError, ValueError) as exc:
        # Re-wrap dataclass invariant failures (bad name regex, advisory
        # not subset, etc.) as SkillParseError so callers see one
        # exception class.
        raise SkillParseError(f"SKILL.md at {path!s} failed validation: {exc}") from exc


def _require_str(path: Path, data: dict[str, Any], *, key: str) -> str:
    """Return ``data[key]`` as ``str`` or raise :class:`SkillParseError`."""
    if key not in data:
        raise SkillParseError(
            f"SKILL.md at {path!s} is missing required frontmatter key {key!r}"
        )
    value = data[key]
    if not isinstance(value, str):
        raise SkillParseError(
            f"SKILL.md at {path!s} key {key!r} must be a string, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_capabilities_block(
    path: Path, data: dict[str, Any]
) -> tuple[frozenset[Capability], frozenset[Capability]]:
    """Parse the optional ``capabilities`` block.

    Returns ``(required, advisory_mode)`` as two frozensets of
    :class:`Capability` members. Absent or empty block yields two
    empty frozensets — the matcher treats these skills as executable
    against any provider (regression contract for the 16 shipped
    SKILL.md files).
    """
    caps = data.get("capabilities")
    if caps is None:
        return frozenset(), frozenset()
    if not isinstance(caps, dict):
        raise SkillParseError(
            f"SKILL.md at {path!s} 'capabilities' must be a mapping, "
            f"got {type(caps).__name__}"
        )

    required_raw = caps.get("required", [])
    advisory_raw = caps.get("advisory_mode", [])

    required = _parse_capability_list(path, required_raw, field="required")
    advisory = _parse_capability_list(path, advisory_raw, field="advisory_mode")
    return required, advisory


def _parse_capability_list(
    path: Path, raw: object, *, field: str
) -> frozenset[Capability]:
    """Parse a list of capability tokens into a frozenset."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise SkillParseError(
            f"SKILL.md at {path!s} capabilities.{field} must be a list, "
            f"got {type(raw).__name__}"
        )
    tokens: list[str] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, str):
            raise SkillParseError(
                f"SKILL.md at {path!s} capabilities.{field}[{idx}] must be "
                f"a string, got {type(item).__name__}"
            )
        tokens.append(item)
    try:
        return parse_capabilities(tokens)
    except ValueError as exc:
        raise SkillParseError(
            f"SKILL.md at {path!s} capabilities.{field}: {exc}"
        ) from exc


__all__ = ["MAX_SKILL_FILE_BYTES", "SkillParseError", "parse_skill_md"]
