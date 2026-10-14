"""Read and write STRATEGY.md."""

from __future__ import annotations

import enum
import logging
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable
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

# Title written when a file has no preamble of its own (new file, or one
# that starts directly at a ``## `` section).
_DEFAULT_PREAMBLE_LINES: tuple[str, ...] = ("# Strategy", "")


class _Keep(enum.Enum):
    KEEP = "keep"


# Default for ``write_strategy_file(preamble=...)``: keep whatever precedes
# the first section in the file being replaced (issue #845).
KEEP: Final = _Keep.KEEP


def strategy_preamble(text: str) -> str:
    """Return the text before the first ``## `` heading, verbatim.

    That is the title and any prose above the first section, including its
    trailing newlines. A text that starts with a section, or is empty, has
    no preamble (``""``); a text with no section at all is all preamble.
    """
    offset = 0
    for line in text.split("\n"):
        if _H2_PATTERN.match(line):
            return text[:offset]
        offset += len(line) + 1
    return text


def _kept_preamble(text: str) -> str | None:
    """The preamble of ``text`` to write back, or ``None`` for the default.

    A missing, empty or whitespace-only preamble gets the default title.
    """
    preamble = strategy_preamble(text)
    return preamble if preamble.strip() else None


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


def render_strategy(entries: list[StrategyEntry], preamble: str | None = None) -> str:
    """Generate a Markdown string from a list of StrategyEntry.

    ``preamble`` is written verbatim before the first section (a newline is
    added if it does not end with one); ``""`` writes nothing there. ``None``
    writes the default ``# Strategy`` title.
    """
    section_lines: list[str] = []
    for entry in entries:
        section_lines.append(f"## {_make_heading(entry)}")
        section_lines.append(entry.content)
        section_lines.append("")

    if preamble is None:
        return "\n".join([*_DEFAULT_PREAMBLE_LINES, *section_lines])
    if preamble and not preamble.endswith("\n"):
        preamble += "\n"
    return preamble + "\n".join(section_lines)


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
    return parse_strategy(_read_strategy_text(path))


def _read_strategy_text(path: Path) -> str:
    """The raw text of ``path``; ``""`` if the file does not exist."""
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STRATEGY.md: {path}") from exc


def write_strategy_file(
    path: Path,
    entries: list[StrategyEntry],
    preamble: str | None | _Keep = KEEP,
) -> None:
    """Atomically write a list of StrategyEntry to a STRATEGY.md file.

    With the default ``KEEP`` the existing file's title and preamble (the
    text before its first ``## `` section) are kept byte-for-byte; a missing
    file, or one with no preamble, gets the default ``# Strategy`` title.
    ``None`` forces the default title; a string is written as given (see
    :func:`render_strategy`).
    """
    if preamble is KEEP:
        preamble = _kept_preamble(_read_strategy_text(path))
    _atomic_write(path, render_strategy(entries, preamble=preamble))


def _strategy_lock_path(path: Path) -> Path:
    """Sidecar lock file for ``path`` (``STRATEGY.md`` -> ``STRATEGY.md.lock``).

    Mirrors ``mureo.context.state._state_lock_path`` so both context files
    serialise their read-modify-write mutations the same way.
    """
    return path.with_name(path.name + ".lock")


def mutate_strategy_file(
    path: Path,
    mutate: Callable[[list[StrategyEntry]], list[StrategyEntry]],
) -> list[StrategyEntry]:
    """Run ``mutate`` over the file's entries inside the cross-process lock.

    mkdir -> lock -> read (a missing file reads as ``[]``) -> ``mutate`` ->
    atomic write, which is the one read-modify-write shape every STRATEGY.md
    writer needs: without the lock two concurrent callers last-writer-wins
    away each other's change (a lost update). This mirrors
    ``mureo.context.state._locked_state_mutation`` — STATE.json was already
    protected (issue #115) while STRATEGY.md was not.

    The file is read once under the lock: its entries go to ``mutate`` and
    its title and preamble are written back unchanged (issue #845).

    ``mutate`` must be PURE with respect to its argument: it returns the new
    list rather than editing the one it was handed. It runs while the lock is
    held, so anything it does besides deciding the new entries (taking a
    backup, say) also happens before the write and under the same lock.

    Returns:
        The entries that were written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_strategy_lock_path(path)):
        text = _read_strategy_text(path)
        entries = mutate(parse_strategy(text))
        write_strategy_file(path, entries, preamble=_kept_preamble(text))
    return entries


def add_strategy_entry(path: Path, entry: StrategyEntry) -> list[StrategyEntry]:
    """Append an entry to the existing file.

    The read -> append -> write cycle runs inside the cross-process
    ``file_lock`` (see :func:`mutate_strategy_file`) so two concurrent
    callers cannot last-writer-wins away each other's append; the write
    itself stays atomic via ``write_strategy_file``.

    Returns:
        Updated list of entries.
    """
    return mutate_strategy_file(path, lambda entries: [*entries, entry])


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
    ``file_lock`` as :func:`add_strategy_entry` (see
    :func:`mutate_strategy_file`) so a concurrent add/remove pair cannot
    clobber each other's change.

    Returns:
        Updated list of entries.
    """

    def _should_keep(e: StrategyEntry) -> bool:
        if e.context_type != context_type:
            return True
        return bool(title is not None and e.title != title)

    return mutate_strategy_file(
        path, lambda entries: [e for e in entries if _should_keep(e)]
    )
