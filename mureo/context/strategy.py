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
}

# context_type -> prefix name (SUGGESTION-1: module-level constants)
_TYPE_TO_PREFIX: dict[str, str] = {v: k for k, v in _PREFIX_TYPES.items()}

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


def _resolve_heading(heading: str) -> tuple[str | None, str]:
    """Resolve (context_type, title) from a heading string.

    Returns (None, heading) for unknown headings and logs a warning.
    """
    # Exact match check
    if heading in _SECTION_MAP:
        return _SECTION_MAP[heading], heading

    # Prefix-type check (e.g. "Custom: title")
    for prefix, ctx_type in _PREFIX_TYPES.items():
        if heading.startswith(f"{prefix}:"):
            title = heading[len(prefix) + 1 :].strip()
            return ctx_type, title

    # WARNING-3: logging.warning for unknown sections
    logger.warning("Skipping unknown section heading: '%s'", heading)
    return None, heading


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


def add_strategy_entry(path: Path, entry: StrategyEntry) -> list[StrategyEntry]:
    """Append an entry to the existing file.

    Returns:
        Updated list of entries.
    """
    entries = read_strategy_file(path)
    entries = [*entries, entry]
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

    Returns:
        Updated list of entries.
    """
    entries = read_strategy_file(path)

    def _should_keep(e: StrategyEntry) -> bool:
        if e.context_type != context_type:
            return True
        return bool(title is not None and e.title != title)

    filtered = [e for e in entries if _should_keep(e)]
    write_strategy_file(path, filtered)
    return filtered
