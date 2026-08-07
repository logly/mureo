"""Parse the opt-in ``## Tracking Convention`` section of STRATEGY.md.

The zero-config checks in :mod:`mureo.analysis.tracking.checks` work
from evidence already in the account. A convention adds the one thing
evidence cannot supply — what the operator *intended* — and it is
declared, never inferred:

```markdown
## Tracking Convention

- recognize: utm_*, argument
- require: utm_source, utm_medium, utm_campaign
- pattern utm_source: google, yahoo
- pattern utm_campaign: seg[ab]??
```

Patterns are ``fnmatch`` globs (``*``, ``?``, ``[seq]``), not regular
expressions: an operator-authored regex in an agent-writable file is
both harder to write and a denial-of-service surface, while a glob is
bounded and matches how these values are actually shaped.

The section is parsed by mureo, not interpreted by the agent — the
whole point of the feature is that the rule is applied deterministically.
"""

from __future__ import annotations

import re

from mureo.analysis.tracking.models import TrackingConvention

#: The STRATEGY.md heading this section is declared under.
SECTION_HEADING = "Tracking Convention"

_H2 = re.compile(r"^##\s+(.+?)\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_PATTERN_DIRECTIVE = re.compile(r"^pattern\s+(\S+)$", re.IGNORECASE)


def _split_list(raw: str) -> tuple[str, ...]:
    """Split a comma- or whitespace-separated directive value."""
    return tuple(item for item in re.split(r"[,\s]+", raw.strip()) if item)


def _section_lines(markdown: str) -> list[str] | None:
    """Return the lines under ``## Tracking Convention``, or None."""
    lines: list[str] | None = None
    for line in markdown.splitlines():
        heading = _H2.match(line)
        if heading is not None:
            if heading.group(1).strip().lower() == SECTION_HEADING.lower():
                lines = []
            elif lines is not None:
                break
            continue
        if lines is not None:
            lines.append(line)
    return lines


def parse_tracking_convention(markdown: str) -> TrackingConvention | None:
    """Parse a ``## Tracking Convention`` section out of ``markdown``.

    Accepts either the whole STRATEGY.md or just the section. Returns
    ``None`` when the section is absent — the caller then runs the
    zero-config checks only. Unrecognised bullets are ignored rather
    than guessed at, so a typo weakens the declaration instead of
    silently changing its meaning.
    """
    lines = _section_lines(markdown)
    if lines is None:
        return None

    recognize: list[str] = []
    require: list[str] = []
    patterns: dict[str, tuple[str, ...]] = {}

    for line in lines:
        bullet = _BULLET.match(line)
        if bullet is None or ":" not in bullet.group(1):
            continue
        directive, _, raw_value = bullet.group(1).partition(":")
        directive = directive.strip()
        values = _split_list(raw_value)
        if not values:
            continue
        pattern_for = _PATTERN_DIRECTIVE.match(directive)
        if pattern_for is not None:
            patterns[pattern_for.group(1)] = values
        elif directive.lower() == "recognize":
            recognize.extend(values)
        elif directive.lower() == "require":
            require.extend(values)

    return TrackingConvention(
        recognize=tuple(recognize),
        require=tuple(require),
        patterns=tuple(sorted(patterns.items())),
    )


__all__ = ["SECTION_HEADING", "parse_tracking_convention"]
