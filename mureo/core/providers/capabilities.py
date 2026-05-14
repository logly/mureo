"""Capability enum and parsers for the provider abstraction layer.

This module is the foundation of the provider ABI. Provider Protocols,
adapters, the entry-points registry, the skill matcher, and third-party
plugins all import ``Capability`` from here.

Stability promise
-----------------
Adding values is non-breaking; renaming/removing values is a breaking
change for installed plugins. Treat the string values as a public ABI.

Members may be added at any position; do not rely on iteration order or
the total member count.

Delete convention
-----------------
Deletion operations are folded into write capabilities (e.g., pausing or
archiving a campaign requires ``WRITE_CAMPAIGN_STATUS``). There are no
dedicated ``DELETE_*`` capabilities; this is intentional to keep the
ABI minimal.

Foundation rule
---------------
This module must not import from any other ``mureo.*`` module. Everything
else may depend on it; it depends on nothing internal.
"""

from __future__ import annotations

import difflib
import sys
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):
        """Backport shim for Python 3.10.

        Python 3.11+ provides ``enum.StrEnum`` natively. This shim mirrors
        the essentials: each member is both a ``str`` and an ``Enum``,
        ``str(member)`` returns the member's value, and ``auto()`` yields
        ``name.lower()`` (matching 3.11+ stdlib behaviour).
        """

        def __new__(cls, value: str) -> StrEnum:
            if not isinstance(value, str):
                raise TypeError(
                    f"StrEnum values must be strings: got {type(value).__name__}"
                )
            member = str.__new__(cls, value)
            member._value_ = value
            return member

        def __str__(self) -> str:
            return str(self._value_)

        @staticmethod
        def _generate_next_value_(  # noqa: ARG004
            name: str,
            start: int,
            count: int,
            last_values: list[str],
        ) -> str:
            return name.lower()


class Capability(StrEnum):
    """Stable identifiers for provider capabilities.

    Values are snake_case strings forming the public ABI consumed by
    plugins and skill frontmatter.
    """

    READ_CAMPAIGNS = "read_campaigns"
    READ_PERFORMANCE = "read_performance"
    READ_KEYWORDS = "read_keywords"
    READ_SEARCH_TERMS = "read_search_terms"
    READ_AUDIENCES = "read_audiences"
    READ_EXTENSIONS = "read_extensions"
    WRITE_BUDGET = "write_budget"
    WRITE_BID = "write_bid"
    WRITE_CREATIVE = "write_creative"
    WRITE_KEYWORDS = "write_keywords"
    WRITE_AUDIENCES = "write_audiences"
    WRITE_EXTENSIONS = "write_extensions"
    WRITE_CAMPAIGN_STATUS = "write_campaign_status"


# Load-time invariant: every Capability value is snake_case (lowercase
# ASCII letters plus underscores). Catches accidental ABI drift on import.
assert all(
    c.value.replace("_", "").isalpha() and c.value.islower() for c in Capability
), "All Capability values must be snake_case (lowercase letters + underscores)"


CAPABILITY_NAMES: frozenset[str] = frozenset(str(c) for c in Capability)


def parse_capability(value: str) -> Capability:
    """Return the ``Capability`` member matching ``value``.

    Raises ``ValueError`` (including the offending input, close-match
    suggestions when available, and the full set of valid tokens) if no
    member matches.
    """
    try:
        return Capability(value)
    except ValueError as exc:
        suggestions = difflib.get_close_matches(value, sorted(CAPABILITY_NAMES), n=3)
        suggestion_hint = (
            f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        )
        raise ValueError(
            f"unknown capability: {value!r}.{suggestion_hint} "
            f"Valid: {sorted(CAPABILITY_NAMES)}"
        ) from exc


def parse_capabilities(values: Iterable[str]) -> frozenset[Capability]:
    """Return a ``frozenset`` of parsed capabilities.

    Duplicates are silently deduped. Raises ``ValueError`` (mentioning the
    offending token and its index in the input) on the first unknown value.
    """
    parsed: set[Capability] = set()
    for idx, value in enumerate(values):
        try:
            parsed.add(parse_capability(value))
        except ValueError as exc:
            raise ValueError(f"capability at index {idx}: {exc}") from exc
    return frozenset(parsed)


__all__ = [
    "CAPABILITY_NAMES",
    "Capability",
    "parse_capabilities",
    "parse_capability",
]
