"""GAQL (Google Ads Query Language) input validators.

Centralizes every primitive that touches GAQL string assembly so every
caller routes potentially-untrusted input through the same whitelist-based
validation surface. All functions raise ``GAQLValidationError`` (a
``ValueError`` subclass) on bad input; existing ``except ValueError``
handlers remain compatible.

The functions here are intentionally pure — no I/O, no logging side
effects — so they can be reused by MCP handlers, CLI commands, and tests
alike.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Google Ads IDs are int64; 20 digits is comfortably above the real max
# while still capping attacker payloads at a trivial size.
_MAX_ID_LENGTH = 20
_ID_PATTERN = re.compile(r"\d+")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")

# Whitelist of Google Ads date range constants.
# Source: https://developers.google.com/google-ads/api/docs/query/date-ranges
# ``ALL_TIME`` is intentionally omitted — it produces unbounded reports
# that bypass the period-days guard. Callers needing longer windows must
# use an explicit ``BETWEEN`` clause.
VALID_DATE_RANGE_CONSTANTS: frozenset[str] = frozenset(
    {
        "TODAY",
        "YESTERDAY",
        "LAST_7_DAYS",
        "LAST_14_DAYS",
        "LAST_30_DAYS",
        "LAST_BUSINESS_WEEK",
        "LAST_WEEK_SUN_SAT",
        "LAST_WEEK_MON_SUN",
        "THIS_MONTH",
        "LAST_MONTH",
        "THIS_WEEK_SUN_TODAY",
        "THIS_WEEK_MON_TODAY",
    }
)

_DEFAULT_MAX_PERIOD_DAYS = 730  # ~2 years; Google Ads reporting hard cap


class GAQLValidationError(ValueError):
    """Raised when input fails GAQL validation.

    Subclasses ``ValueError`` so existing ``except ValueError`` code
    keeps working.
    """


def validate_id(value: str, field_name: str) -> str:
    """Return ``value`` if it is a bare numeric ID, else raise.

    Accepts only digit characters (``\\d+``). Dashes, spaces, quotes, and
    any other non-digit content are rejected — callers must normalize
    ``customer_id`` (e.g. ``"123-456-7890"``) to digits first.
    """
    if (
        not isinstance(value, str)
        or not _ID_PATTERN.fullmatch(value)
        or len(value) > _MAX_ID_LENGTH
    ):
        raise GAQLValidationError(f"Invalid {field_name}: {value!r}")
    return value


def validate_id_list(values: Iterable[str], field_name: str) -> list[str]:
    """Validate every ID in a list; reject if any element is invalid.

    Returns a new list preserving insertion order. An empty input is
    rejected because an empty ``IN ()`` clause is itself a syntax error.
    """
    items = list(values)
    if not items:
        raise GAQLValidationError(f"{field_name} list is empty")
    return [validate_id(item, field_name) for item in items]


def validate_date(value: str, field_name: str) -> str:
    """Return ``value`` if it matches ``YYYY-MM-DD``, else raise."""
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise GAQLValidationError(
            f"Invalid {field_name}: {value!r} (expected YYYY-MM-DD)"
        )
    return value


def validate_date_range_constant(value: str) -> str:
    """Return the upper-cased constant if it is a known GAQL date range.

    Rejects anything not in :data:`VALID_DATE_RANGE_CONSTANTS`.
    """
    if not isinstance(value, str):
        raise GAQLValidationError(f"Invalid date range constant: {value!r}")
    upper = value.upper()
    if upper not in VALID_DATE_RANGE_CONSTANTS:
        raise GAQLValidationError(f"Unknown date range constant: {value!r}")
    return upper


def escape_string_literal(value: str) -> str:
    """Escape a string for embedding inside a GAQL single-quoted literal.

    Backslashes are escaped first so that pre-existing escape sequences
    are not double-processed when single quotes are then escaped.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def validate_period_days(
    value: int, *, max_days: int = _DEFAULT_MAX_PERIOD_DAYS
) -> int:
    """Validate an integer day count used for reporting windows.

    Must be ``1 <= value <= max_days``. The upper bound guards against
    accidental API timeouts and absurd ranges.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise GAQLValidationError(
            f"period_days must be int, got {type(value).__name__}"
        )
    if value < 1:
        raise GAQLValidationError(f"period_days must be >= 1, got {value}")
    if value > max_days:
        raise GAQLValidationError(f"period_days must be <= {max_days}, got {value}")
    return value


def build_in_clause(values: Iterable[str], field_name: str) -> str:
    """Validate IDs and return a safe ``(1, 2, 3)`` GAQL ``IN`` clause."""
    safe = validate_id_list(values, field_name)
    return "(" + ", ".join(safe) + ")"
