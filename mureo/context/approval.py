"""The external approval a change carries out (#854).

Some changes are signed off by a person outside mureo before an agent makes
them: a ticket, a change request, an approval queue. ``approval`` is the
reference to that sign-off, stated on the change itself — WHICH approval
(``reference``), WHO gave it (``approved_by``) and WHEN (``approved_at``) —
so the operator reading the history later can find it again.

**Recorded and shown, never verified.** mureo looks nothing up and assigns
the value no meaning: it does not know the system the reference points
into, cannot tell whether the person exists, and does not compare the time
with anything. It only bounds the shape, so the value is safe to store in
STATE.json and to put on a dashboard line.

Pure: no I/O. Imported by :mod:`mureo.context.models`, so it imports
only leaf modules.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

from mureo.context.iso_time import iso_date

#: Longest ``reference``. Ticket and request ids are far shorter; the bound
#: is what STATE.json and one dashboard line can carry.
APPROVAL_REFERENCE_MAX_CHARS: Final = 128

#: Longest ``approved_by``, in code points after stripping.
APPROVAL_BY_MAX_CHARS: Final = 80

#: Longest ``approved_at``. Every value the profile below accepts fits with
#: room to spare; the bound is checked first, before any pattern runs.
APPROVAL_AT_MAX_CHARS: Final = 64

#: The ``approved_at`` profile: a date, optionally a time to the minute,
#: second or microsecond, optionally ``Z`` or a ``+HH:MM`` offset. Checked
#: before ``fromisoformat``, whose accepted forms differ between Python
#: versions (3.11 added basic and week dates), so every supported version
#: accepts the same values. ``[0-9]``, not ``\d``, which matches any digit.
_APPROVED_AT_PATTERN: Final = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})?)?"
)

#: A fraction of a second, padded to six digits before the calendar check:
#: ``fromisoformat`` on 3.10 reads only three or six.
_FRACTION_PATTERN: Final = re.compile(r"\.([0-9]{1,6})")

#: Unicode categories ``approved_by`` refuses: control (Cc), format (Cf,
#: e.g. bidi overrides and zero-width spaces), line and paragraph
#: separators (Zl, Zp), surrogates (Cs) and private use (Co). Each can hide
#: or reorder text on the dashboard line, or is not text at all.
_REFUSED_NAME_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs", "Co"})

#: The keys an approval carries, all required, nothing else accepted.
APPROVAL_KEYS: Final[tuple[str, ...]] = ("reference", "approved_by", "approved_at")

#: What a ``reference`` may be made of: an identifier, not a sentence.
_REFERENCE_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]+")

_SHAPE_HINT: Final = (
    "approval must be an object with reference, approved_by and approved_at"
)


def _reference(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("approval.reference must be a string")
    if not 1 <= len(value) <= APPROVAL_REFERENCE_MAX_CHARS:
        raise ValueError(
            f"approval.reference must be 1 to {APPROVAL_REFERENCE_MAX_CHARS} "
            f"characters; got {len(value)}"
        )
    if _REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError(
            "approval.reference may contain only A-Z, a-z, 0-9, '.', '_' and '-'"
        )
    return value


def _approved_by(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("approval.approved_by must be a string")
    cleaned = value.strip()
    if not 1 <= len(cleaned) <= APPROVAL_BY_MAX_CHARS:
        raise ValueError(
            f"approval.approved_by must be 1 to {APPROVAL_BY_MAX_CHARS} "
            f"characters; got {len(cleaned)}"
        )
    if any(unicodedata.category(char) in _REFUSED_NAME_CATEGORIES for char in cleaned):
        raise ValueError(
            "approval.approved_by must not contain control, format or "
            "separator characters"
        )
    return cleaned


def _approved_at(value: Any) -> str:
    # Refusals name the shape, never the value: they reach logs as well as
    # the agent.
    hint = (
        "approval.approved_at must be an ISO 8601 date or timestamp "
        "(YYYY-MM-DD, optionally THH:MM[:SS[.ffffff]] and Z or +HH:MM)"
    )
    if not isinstance(value, str) or len(value) > APPROVAL_AT_MAX_CHARS:
        raise ValueError(hint)
    if _APPROVED_AT_PATTERN.fullmatch(value) is None:
        raise ValueError(hint)
    padded = _FRACTION_PATTERN.sub(lambda m: "." + m.group(1).ljust(6, "0"), value)
    if iso_date(padded) is None:
        raise ValueError(hint)
    return value


@dataclass(frozen=True)
class ApprovalRef:
    """One external approval, as the change stated it.

    reference: The approval's identifier in the system that holds it,
        1 to :data:`APPROVAL_REFERENCE_MAX_CHARS` characters of
        ``[A-Za-z0-9._-]``.
    approved_by: Who approved, as that system names them; stripped,
        1 to :data:`APPROVAL_BY_MAX_CHARS` characters, no control, format
        or separator characters.
    approved_at: When, as an ISO 8601 date or timestamp in the profile of
        :data:`_APPROVED_AT_PATTERN`. Kept exactly as given.
    """

    reference: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        """Refuse anything out of bounds, naming the field."""
        object.__setattr__(self, "reference", _reference(self.reference))
        object.__setattr__(self, "approved_by", _approved_by(self.approved_by))
        object.__setattr__(self, "approved_at", _approved_at(self.approved_at))


def parse_approval(value: Any) -> ApprovalRef | None:
    """Validate ``value`` into an :class:`ApprovalRef`, or refuse it.

    ``None`` means no approval was stated. Every refusal names the field,
    because these messages are what an agent sees as ``invalid_args``.

    Raises:
        ValueError: ``value`` is not an object, has an unknown or missing
            key, or a field is out of bounds.
    """
    if value is None or isinstance(value, ApprovalRef):
        return value
    if not isinstance(value, dict):
        raise ValueError(_SHAPE_HINT)
    unknown = sorted(str(key) for key in value if key not in APPROVAL_KEYS)
    if unknown:
        raise ValueError(f"approval has unknown key(s) {unknown}")
    for key in APPROVAL_KEYS:
        if key not in value:
            raise ValueError(f"approval is missing {key!r}")
    return ApprovalRef(
        reference=value["reference"],
        approved_by=value["approved_by"],
        approved_at=value["approved_at"],
    )


def approval_to_dict(ref: ApprovalRef) -> dict[str, str]:
    """Serialise an approval: the three keys, as stored."""
    return {
        "reference": ref.reference,
        "approved_by": ref.approved_by,
        "approved_at": ref.approved_at,
    }


__all__ = [
    "APPROVAL_AT_MAX_CHARS",
    "APPROVAL_BY_MAX_CHARS",
    "APPROVAL_KEYS",
    "APPROVAL_REFERENCE_MAX_CHARS",
    "ApprovalRef",
    "approval_to_dict",
    "parse_approval",
]
