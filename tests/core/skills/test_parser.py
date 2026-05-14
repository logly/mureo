"""Unit tests for ``mureo.core.skills.parser`` (RED phase, Issue #89 P1-08).

These tests pin the contract of :func:`parse_skill_md`:

- Reads the file as UTF-8 strict.
- Extracts YAML frontmatter delimited by ``^---\\n`` / ``\\n---\\n``.
- Uses ``yaml.safe_load`` (never ``yaml.load`` / ``yaml.unsafe_load``).
- Requires ``name`` (matching ``^_?[a-z][a-z0-9_-]*$``) and ``description``
  (non-empty).
- Optional ``capabilities`` block with ``required`` + ``advisory_mode``
  lists; ``advisory_mode`` must be a subset of ``required``.
- Unknown top-level keys are ignored for forward compatibility.
- File-size cap of 64 KiB enforced *before* YAML parse.
- Wraps any decode / YAML / validation failure in
  :class:`SkillParseError`.

Marks: every test is ``@pytest.mark.unit`` — pure file I/O against
``tmp_path``; no network, no entry points, no plugin discovery.

NOTE: these imports are expected to FAIL during the RED phase — the
module ``mureo.core.skills.parser`` does not exist yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mureo.core.providers.capabilities import Capability
from mureo.core.skills.parser import (  # noqa: E402 — RED-phase import
    SkillParseError,
    parse_skill_md,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill(tmp_path: Path, body: str, *, name: str = "skill.md") -> Path:
    """Write ``body`` to ``tmp_path/name`` and return the resolved path."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path.resolve()


_MIN_FRONTMATTER = (
    "---\n"
    "name: example-skill\n"
    'description: "An example skill for tests."\n'
    "---\n"
    "# Body\n"
    "Some markdown body content here.\n"
)


# ---------------------------------------------------------------------------
# Case 1 — well-formed minimal frontmatter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_well_formed_minimal(tmp_path: Path) -> None:
    """A SKILL.md with only ``name`` + ``description`` parses cleanly and
    returns empty capability frozensets (no ``capabilities`` block declared).
    """
    path = _write_skill(tmp_path, _MIN_FRONTMATTER)

    entry = parse_skill_md(path)

    assert entry.name == "example-skill"
    assert entry.description == "An example skill for tests."
    assert entry.required_capabilities == frozenset()
    assert entry.advisory_mode_capabilities == frozenset()
    assert entry.source_path == path
    assert entry.source_distribution is None


# ---------------------------------------------------------------------------
# Case 2 — well-formed with capabilities block
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_well_formed_with_capabilities(tmp_path: Path) -> None:
    """``capabilities.required`` and ``capabilities.advisory_mode`` are
    parsed into frozensets of :class:`Capability` members.
    """
    body = (
        "---\n"
        "name: cap-skill\n"
        'description: "Skill that declares capabilities."\n'
        "capabilities:\n"
        "  required:\n"
        "    - read_campaigns\n"
        "    - read_performance\n"
        "  advisory_mode:\n"
        "    - read_campaigns\n"
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    entry = parse_skill_md(path)

    assert entry.required_capabilities == frozenset(
        {Capability.READ_CAMPAIGNS, Capability.READ_PERFORMANCE}
    )
    assert entry.advisory_mode_capabilities == frozenset({Capability.READ_CAMPAIGNS})


# ---------------------------------------------------------------------------
# Case 3 — missing frontmatter delimiters
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_missing_frontmatter_delimiters(tmp_path: Path) -> None:
    """A SKILL.md that does NOT start with ``---\\n`` raises
    :class:`SkillParseError` mentioning ``frontmatter``.
    """
    body = "# A skill without frontmatter\n\nNo YAML header at all.\n"
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="frontmatter"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 4 — missing required key 'name'
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_missing_name_key(tmp_path: Path) -> None:
    """The parser raises :class:`SkillParseError` mentioning ``'name'`` if
    the frontmatter omits the required ``name`` key.
    """
    body = "---\n" 'description: "Missing name."\n' "---\n" "body\n"
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="name"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 5 — missing required key 'description'
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_missing_description_key(tmp_path: Path) -> None:
    """Missing ``description`` raises :class:`SkillParseError` mentioning
    ``'description'``.
    """
    body = "---\n" "name: ok-name\n" "---\n" "body\n"
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="description"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 6 — invalid name regex
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_invalid_name_regex(tmp_path: Path) -> None:
    """A name that does not match ``^_?[a-z][a-z0-9_-]*$`` raises
    :class:`SkillParseError`.
    """
    body = (
        "---\n"
        'name: "BadName!"\n'
        'description: "Has invalid name."\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 7 — unknown capability token
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_unknown_capability_token(tmp_path: Path) -> None:
    """An unknown token under ``capabilities.required`` raises
    :class:`SkillParseError` mentioning the offending token.
    """
    body = (
        "---\n"
        "name: bad-cap\n"
        'description: "Declares an unknown capability."\n'
        "capabilities:\n"
        "  required:\n"
        "    - read_unicorns\n"
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="read_unicorns"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 8 — advisory_mode not a subset of required
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_advisory_not_subset_of_required(tmp_path: Path) -> None:
    """If ``advisory_mode`` contains a capability not in ``required`` the
    parser raises :class:`SkillParseError`.
    """
    body = (
        "---\n"
        "name: bad-advisory\n"
        'description: "Advisory not in required."\n'
        "capabilities:\n"
        "  required:\n"
        "    - read_campaigns\n"
        "  advisory_mode:\n"
        "    - read_performance\n"
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 9 — unknown top-level keys are ignored (forward compat)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_ignores_unknown_top_level_keys(tmp_path: Path) -> None:
    """``metadata`` / ``openclaw`` / arbitrary unknown keys are tolerated
    (matches the 16 in-tree SKILL.md files which already carry
    ``metadata.version`` and ``metadata.openclaw``).
    """
    body = (
        "---\n"
        "name: fwd-compat\n"
        'description: "Forward-compatible parse."\n'
        "metadata:\n"
        '  version: "0.7.1"\n'
        "  openclaw:\n"
        '    category: "marketing"\n'
        "future_field:\n"
        '  hello: "world"\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    entry = parse_skill_md(path)

    assert entry.name == "fwd-compat"
    assert entry.required_capabilities == frozenset()
    assert entry.advisory_mode_capabilities == frozenset()


# ---------------------------------------------------------------------------
# Case 10 — oversized file rejected before YAML parse
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_oversized_file_rejected(tmp_path: Path) -> None:
    """A SKILL.md exceeding 64 KiB raises :class:`SkillParseError`
    mentioning size and is rejected without invoking the YAML parser.
    """
    # 65 KiB of padding inside a markdown body — still well-formed
    # frontmatter, but total file size pushes past the 64 KiB cap.
    padding = "x" * (65 * 1024)
    body = (
        "---\n" "name: too-big\n" 'description: "Oversized."\n' "---\n" f"{padding}\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="(?i)size|large|64"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 11 — malicious YAML tag rejected, no code execution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_rejects_malicious_yaml_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A YAML tag that would trigger code execution under unsafe loaders
    (e.g. ``!!python/object/apply:os.system``) must be rejected by
    ``yaml.safe_load``. The parser wraps the underlying YAML error in
    :class:`SkillParseError`.

    Defense in depth: we additionally monkeypatch ``os.system`` to a
    failing sentinel — if the parser is ever switched to an unsafe loader
    this assertion will fire and surface the regression.
    """
    import os as _os  # noqa: PLC0415 — local import for monkeypatch target

    sentinel: dict[str, bool] = {"called": False}

    def _explode(_cmd: str) -> int:
        sentinel["called"] = True
        return 0

    monkeypatch.setattr(_os, "system", _explode)

    body = (
        "---\n"
        "name: malicious\n"
        'description: "Tries to execute code via YAML tag."\n'
        'pwn: !!python/object/apply:os.system ["echo pwned"]\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError):
        parse_skill_md(path)

    assert (
        sentinel["called"] is False
    ), "os.system was called during parse — parser must use yaml.safe_load"


# ---------------------------------------------------------------------------
# Case 12 — non-UTF-8 bytes rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_rejects_non_utf8_bytes(tmp_path: Path) -> None:
    """A file containing invalid UTF-8 raises :class:`SkillParseError`
    (the parser reads with ``errors="strict"``).
    """
    path = tmp_path / "bad-utf8.md"
    # Latin-1 byte 0xff is invalid in UTF-8.
    path.write_bytes(b"---\nname: ok\ndescription: \xff bad\n---\nbody\n")

    with pytest.raises(SkillParseError):
        parse_skill_md(path.resolve())


# ---------------------------------------------------------------------------
# Case 13 — frontmatter delimiters must be at start of file
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_rejects_delimiters_not_at_start(tmp_path: Path) -> None:
    """``---`` appearing on line 3 (after a blank line and a comment) is
    NOT a valid frontmatter delimiter; the parser must reject it.
    """
    body = (
        "<!-- pre-comment -->\n"
        "\n"
        "---\n"
        "name: late-frontmatter\n"
        'description: "Frontmatter not at top."\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    with pytest.raises(SkillParseError, match="frontmatter"):
        parse_skill_md(path)


# ---------------------------------------------------------------------------
# Case 14 — unknown top-level keys are surfaced in ``extra``
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_populates_extra_with_unknown_keys(tmp_path: Path) -> None:
    """The parser collects every top-level frontmatter key that is NOT
    ``name`` / ``description`` / ``capabilities`` into
    :attr:`SkillEntry.extra` for forward compatibility.
    """
    body = (
        "---\n"
        "name: fwd-compat\n"
        'description: "Forward-compatible parse."\n'
        "metadata:\n"
        '  version: "0.7.1"\n'
        "  openclaw:\n"
        '    category: "marketing"\n'
        "future_field:\n"
        '  hello: "world"\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    entry = parse_skill_md(path)

    # Reserved keys are NOT in extra.
    assert "name" not in entry.extra
    assert "description" not in entry.extra
    assert "capabilities" not in entry.extra
    # Unknown keys ARE in extra, unchanged.
    assert entry.extra["metadata"] == {
        "version": "0.7.1",
        "openclaw": {"category": "marketing"},
    }
    assert entry.extra["future_field"] == {"hello": "world"}


# ---------------------------------------------------------------------------
# Case 15 — ``extra`` is empty when no unknown keys are present
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_extra_empty_when_no_unknown_keys(tmp_path: Path) -> None:
    """A SKILL.md whose frontmatter contains only reserved keys yields
    an ``extra`` mapping with zero entries.
    """
    path = _write_skill(tmp_path, _MIN_FRONTMATTER)

    entry = parse_skill_md(path)

    assert len(entry.extra) == 0


# ---------------------------------------------------------------------------
# Case 16 — capabilities key is consumed, not leaked into ``extra``
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_capabilities_not_leaked_into_extra(tmp_path: Path) -> None:
    """``capabilities`` is a reserved key — even when present, it does
    not appear in ``extra``.
    """
    body = (
        "---\n"
        "name: cap-skill\n"
        'description: "Cap skill."\n'
        "capabilities:\n"
        "  required:\n"
        "    - read_campaigns\n"
        "metadata:\n"
        '  version: "0.1.0"\n'
        "---\n"
        "body\n"
    )
    path = _write_skill(tmp_path, body)

    entry = parse_skill_md(path)

    assert "capabilities" not in entry.extra
    assert entry.extra["metadata"] == {"version": "0.1.0"}


# ---------------------------------------------------------------------------
# Case 17 — UTF-8 BOM is tolerated
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_accepts_utf8_bom(tmp_path: Path) -> None:
    """Some Windows editors prepend a UTF-8 BOM (``\\ufeff``) when
    saving. The parser strips it after decode so the ``---`` frontmatter
    delimiter on line 1 is still recognised.
    """
    path = tmp_path / "bom.md"
    # ``utf-8-sig`` writes a leading BOM and then the body as UTF-8.
    path.write_text(_MIN_FRONTMATTER, encoding="utf-8-sig")

    entry = parse_skill_md(path.resolve())

    assert entry.name == "example-skill"
    assert entry.description == "An example skill for tests."
