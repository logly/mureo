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

Pure: no I/O. The one shared helper is imported lazily, because
:mod:`mureo.context.models` imports this module and the helper's module
imports the models.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Final

#: Longest ``reference``. Ticket and request ids are far shorter; the bound
#: is what STATE.json and one dashboard line can carry.
APPROVAL_REFERENCE_MAX_CHARS: Final = 128

#: Longest ``approved_by``, in code points after stripping.
APPROVAL_BY_MAX_CHARS: Final = 80

#: Longest ``approved_at``. Any ISO 8601 timestamp fits with room to spare;
#: the bound only stops a parser that accepts long forms from storing one.
APPROVAL_AT_MAX_CHARS: Final = 64

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
    if any(unicodedata.category(char) == "Cc" for char in cleaned):
        raise ValueError("approval.approved_by must not contain control characters")
    return cleaned


def _approved_at(value: Any) -> str:
    # Lazy: ``ops_history_query`` imports the models, which import this module.
    from mureo.context.ops_history_query import iso_date

    if not isinstance(value, str) or len(value) > APPROVAL_AT_MAX_CHARS:
        raise ValueError("approval.approved_at must be an ISO 8601 timestamp")
    if iso_date(value) is None:
        raise ValueError(
            f"approval.approved_at must be an ISO 8601 timestamp; got {value!r}"
        )
    return value


@dataclass(frozen=True)
class ApprovalRef:
    """One external approval, as the change stated it.

    reference: The approval's identifier in the system that holds it,
        1 to :data:`APPROVAL_REFERENCE_MAX_CHARS` characters of
        ``[A-Za-z0-9._-]``.
    approved_by: Who approved, as that system names them; stripped,
        1 to :data:`APPROVAL_BY_MAX_CHARS` characters, no control
        characters.
    approved_at: When, as an ISO 8601 timestamp. Kept exactly as given.
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
