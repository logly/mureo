"""Fit whole lines into a bounded block for the always-on ``instructions`` route.

The MCP server's ``instructions`` are read on every conversation, before any
tool call, so every contribution to them spends a budget shared with
everything else the model has to read. More than one contribution renders the
same shape — a heading, one line per entry, and a cap on the whole block — and
the rules for fitting that shape are the part that must not differ between
them:

* **Whole lines only.** Half a line still reads as a complete claim, so a line
  that does not fit is dropped, never cut.
* **Greedy, in the caller's order.** A long line that does not fit does not
  stop a later, shorter one from fitting.
* **Never over the budget**, counting the heading, the lines, the newlines
  joining them and the omission notice.
* **Visible omission.** A block that lost lines ends with a notice built by
  the caller, because the heading otherwise reads as a complete list and "not
  listed" would mean both "has nothing to say" and "did not fit".

* **Names are validated before they are rendered.** A line that quotes a
  plugin-supplied name (a tool name, a tool prefix) renders it only when
  :func:`is_renderable_name` accepts it: a name carrying a line break could
  forge a heading or another entry, and a long one would carry free text past
  the per-entry cap.

Pure functions: nothing is logged here, so each caller keeps its own log
message, and nothing passed in is modified.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Longest name an always-on line renders.
MAX_RENDERED_NAME_CHARS: Final = 128

#: The name shape an always-on line renders: nothing that can end a line, open
#: a ``name: text`` separator or hide in the rendered text.
_RENDERABLE_NAME_PATTERN: Final = re.compile(
    rf"[A-Za-z0-9_.-]{{1,{MAX_RENDERED_NAME_CHARS}}}"
)


def is_renderable_name(name: object) -> bool:
    """Whether ``name`` may be quoted on an always-on line.

    1 to :data:`MAX_RENDERED_NAME_CHARS` characters of ASCII letters, digits,
    ``_``, ``.`` and ``-``. Anything else, a non-``str`` included, is refused.
    """
    return isinstance(name, str) and bool(_RENDERABLE_NAME_PATTERN.fullmatch(name))


def is_single_line(text: str) -> bool:
    """Whether ``text`` holds no line boundary of any kind.

    An always-on entry is one line of a list. Any line boundary — not only CR
    and LF but every one :meth:`str.splitlines` honours (U+2028, U+2029,
    U+0085, vertical tab, form feed, the file/group/record separators), and a
    trailing one too — would let the entry pose as a second entry or as a
    heading.
    """
    return text.splitlines() == [text]


def _fit(
    heading: str,
    entries: Sequence[tuple[str, str]],
    budget: int,
    reserve: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Greedily fit lines into ``budget`` with ``reserve`` held back.

    Returns the kept lines and the labels of the dropped ones, both in input
    order.
    """
    lines: list[str] = []
    dropped: list[str] = []
    used = len(heading)
    for label, line in entries:
        # +1 for the newline that joins this line to the block.
        if used + 1 + len(line) + reserve > budget:
            dropped.append(label)
            continue
        used += 1 + len(line)
        lines.append(line)
    return tuple(lines), tuple(dropped)


def render_block(
    heading: str,
    entries: Sequence[tuple[str, str]],
    budget: int,
    omission_note: Callable[[int], str],
) -> tuple[str, tuple[str, ...]]:
    """Render ``heading`` and the ``(label, line)`` entries within ``budget``.

    Returns the rendered block and the labels of the entries that were
    dropped. The block is ``""`` when there are no entries or none fits; the
    dropped labels are still reported then, so the caller can log them.

    The first pass spends the whole budget on lines; only if something did not
    fit is a notice needed, and only then does it cost anything. The reserve
    for the second pass is computed for the largest count the notice could
    ever carry, so that pass cannot overshoot.
    """
    if not entries:
        return "", ()
    lines, dropped = _fit(heading, entries, budget, reserve=0)
    note = ""
    if dropped:
        reserve = 1 + len(omission_note(len(entries)))
        lines, dropped = _fit(heading, entries, budget, reserve=reserve)
        note = omission_note(len(dropped))
    if not lines:
        return "", dropped
    return "\n".join([heading, *lines, *([note] if note else [])]), dropped


__all__ = [
    "MAX_RENDERED_NAME_CHARS",
    "is_renderable_name",
    "is_single_line",
    "render_block",
]
