"""Read and write STRATEGY.md."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from mureo.context.errors import ContextFileError
from mureo.context.models import StrategyEntry
from mureo.context.state import _atomic_write
from mureo.fsutil import file_lock

logger = logging.getLogger(__name__)

# Section heading -> context_type mapping
_SECTION_MAP: dict[str, str] = {
    "Persona": "persona",
    "USP": "usp",
    "Target Audience": "target_audience",
    "Brand Voice": "brand_voice",
    "Market Context": "market_context",
    "Operation Mode": "operation_mode",
}

# Reverse mapping from context_type to heading (except Custom/Deep Research/Sales Material)
_TYPE_TO_HEADING: dict[str, str] = {v: k for k, v in _SECTION_MAP.items()}

# Colon-prefixed prefix -> context_type
_PREFIX_TYPES: dict[str, str] = {
    "Custom": "custom",
    "Deep Research": "deep_research",
    "Sales Material": "sales_material",
    "Goal": "goal",
}

# context_type -> prefix name (SUGGESTION-1: module-level constants)
_TYPE_TO_PREFIX: dict[str, str] = {v: k for k, v in _PREFIX_TYPES.items()}

# Sentinel context_type for headings we don't recognise. Rather than dropping
# their content on a round-trip (silent data loss on a partial update or a
# misspelled custom heading — issue #276), we keep the section verbatim: the
# full heading is stored in ``title`` and rendered back unchanged.
RAW_HEADING_TYPE = "raw_heading"

# h2 heading pattern
_H2_PATTERN = re.compile(r"^##\s+(.+)$")


def parse_strategy(text: str) -> list[StrategyEntry]:
    """Parse a Markdown string and return a list of StrategyEntry."""
    if not text.strip():
        return []

    entries: list[StrategyEntry] = []
    current_type: str | None = None
    current_title: str = ""
    content_lines: list[str] = []

    def _flush() -> None:
        if current_type is not None:
            content = "\n".join(content_lines).strip()
            entries.append(
                StrategyEntry(
                    context_type=current_type,
                    title=current_title,
                    content=content,
                )
            )

    for line in text.split("\n"):
        m = _H2_PATTERN.match(line)
        if m:
            _flush()
            heading = m.group(1).strip()
            current_type, current_title = _resolve_heading(heading)
            content_lines = []
        elif current_type is not None:
            content_lines.append(line)

    _flush()
    return entries


def _resolve_heading(heading: str) -> tuple[str, str]:
    """Resolve (context_type, title) from a heading string.

    Unknown headings are preserved as raw passthrough — returns
    ``(RAW_HEADING_TYPE, heading)`` (the full heading kept as the title so it
    renders back verbatim) and logs a warning so a likely misspelling is
    still visible.
    """
    # Exact match check
    if heading in _SECTION_MAP:
        return _SECTION_MAP[heading], heading

    # Prefix-type check (e.g. "Custom: title")
    for prefix, ctx_type in _PREFIX_TYPES.items():
        if heading.startswith(f"{prefix}:"):
            title = heading[len(prefix) + 1 :].strip()
            return ctx_type, title

    # Unrecognised: keep it rather than drop it (issue #276), but warn.
    logger.warning("Preserving unrecognized section heading as-is: '%s'", heading)
    return RAW_HEADING_TYPE, heading


def render_strategy(entries: list[StrategyEntry]) -> str:
    """Generate a Markdown string from a list of StrategyEntry."""
    lines: list[str] = ["# Strategy", ""]

    for entry in entries:
        heading = _make_heading(entry)
        lines.append(f"## {heading}")
        lines.append(entry.content)
        lines.append("")

    return "\n".join(lines)


def _make_heading(entry: StrategyEntry) -> str:
    """Generate a heading string from a StrategyEntry."""
    if entry.context_type in _TYPE_TO_HEADING:
        return _TYPE_TO_HEADING[entry.context_type]

    # SUGGESTION-1: Use module-level constants
    if entry.context_type in _TYPE_TO_PREFIX:
        return f"{_TYPE_TO_PREFIX[entry.context_type]}: {entry.title}"

    # RAW_HEADING_TYPE and any other unknown type: the original heading was
    # stored verbatim in ``title``, so render it back unchanged.
    return entry.title


def read_strategy_file(path: Path) -> list[StrategyEntry]:
    """Read a STRATEGY.md file and return a list of StrategyEntry.

    Returns an empty list if the file does not exist.
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STRATEGY.md: {path}") from exc
    return parse_strategy(text)


def write_strategy_file(path: Path, entries: list[StrategyEntry]) -> None:
    """Atomically write a list of StrategyEntry to a STRATEGY.md file."""
    text = render_strategy(entries)
    _atomic_write(path, text)


def _strategy_lock_path(path: Path) -> Path:
    """Sidecar lock file for ``path`` (``STRATEGY.md`` -> ``STRATEGY.md.lock``).

    Mirrors ``mureo.context.state._state_lock_path`` so both context files
    serialise their read-modify-write mutations the same way.
    """
    return path.with_name(path.name + ".lock")


def add_strategy_entry(path: Path, entry: StrategyEntry) -> list[StrategyEntry]:
    """Append an entry to the existing file.

    The read -> append -> write cycle runs inside the cross-process
    ``file_lock`` so two concurrent callers cannot last-writer-wins away each
    other's append (a lost update). This mirrors
    ``mureo.context.state._locked_state_mutation`` — STATE.json was already
    protected (issue #115) while STRATEGY.md was not; the write itself stays
    atomic via ``write_strategy_file``.

    Returns:
        Updated list of entries.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_strategy_lock_path(path)):
        entries = [*read_strategy_file(path), entry]
        write_strategy_file(path, entries)
    return entries


def remove_strategy_entry(
    path: Path,
    context_type: str,
    *,
    title: str | None = None,
) -> list[StrategyEntry]:
    """Remove entries matching a specific context_type (and optionally title).

    If title is specified, only entries matching both context_type and title are removed.
    If title is not specified, all entries matching context_type are removed.

    The read -> filter -> write cycle runs inside the same cross-process
    ``file_lock`` as :func:`add_strategy_entry` so a concurrent add/remove
    pair cannot clobber each other's change.

    Returns:
        Updated list of entries.
    """

    def _should_keep(e: StrategyEntry) -> bool:
        if e.context_type != context_type:
            return True
        return bool(title is not None and e.title != title)

    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_strategy_lock_path(path)):
        entries = read_strategy_file(path)
        filtered = [e for e in entries if _should_keep(e)]
        write_strategy_file(path, filtered)
    return filtered
