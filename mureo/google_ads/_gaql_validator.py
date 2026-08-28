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
from datetime import date, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Google Ads IDs are int64; 20 digits is comfortably above the real max
# while still capping attacker payloads at a trivial size.
_MAX_ID_LENGTH = 20
# Use explicit ASCII ``[0-9]`` (not ``\d``) so Unicode digits — full-width
# ``１２３`` or Arabic-Indic ``٣٤٥`` — are rejected, not silently accepted as
# "numeric" and interpolated into a GAQL clause.
_ID_PATTERN = re.compile(r"[0-9]+")
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

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

# Constants mureo offers that Google Ads has no date-range constant for, and
# the trailing window each one stands for. ``LAST_90_DAYS`` is recommended by
# the tool descriptions as the trend baseline but is absent from the API's
# constant list, so every call using it used to die in
# :func:`validate_date_range_constant` (#717). It is resolved into an explicit
# ``BETWEEN`` window instead of being dropped.
#
# Boundary: the derived window ends **yesterday**, matching the trailing
# constants it sits beside — Google's ``LAST_N_DAYS`` covers the N days before
# today and never includes the partial current day, so a 90-day baseline lines
# up with a 30-day one instead of being one day longer at the near end.
# Source: https://developers.google.com/google-ads/api/docs/query/date-ranges
#
# One asymmetry the callers must document: a real constant is resolved by
# Google against the ACCOUNT's reporting time zone, while anything resolved
# here is resolved against whatever date the caller passes in — in practice
# ``mureo.core.clock.server_now``, the HOST's zone. Where the two zones differ
# the derived window's edges can sit a day away from a native constant's. This
# is the same clock ``_get_comparison_date_ranges`` has always used, so the
# behaviour is not new; the disclosure in the tool descriptions is.
DERIVED_DATE_RANGE_DAYS: Mapping[str, int] = MappingProxyType({"LAST_90_DAYS": 90})

# Every period value the MCP surface may offer: the API's own constants plus
# the ones resolved above. ``mureo.mcp._period_param.PERIOD_CONSTANTS`` is
# built from this set (it only chooses a display order), so "offered by a
# schema" and "honoured downstream" are the same list by construction (#717).
SUPPORTED_PERIOD_CONSTANTS: frozenset[str] = VALID_DATE_RANGE_CONSTANTS | frozenset(
    DERIVED_DATE_RANGE_DAYS
)

# The explicit-range form, in one place. Published verbatim as the JSON Schema
# ``pattern`` of the MCP ``period`` parameter (#716). It is deliberately the
# STRICT spelling — exactly what the tools document — while
# :data:`BETWEEN_CLAUSE_RE` below is what the parser tolerates. The asymmetry
# runs one way only: the schema must never admit a string the parser would
# refuse. The reverse (a lower-cased or double-spaced clause that the parser
# would have taken) is simply turned away at the edge.
#
# Two deliberate deviations from the obvious spelling, both because
# ``jsonschema`` compiles this with Python's ``re`` and evaluates it with
# ``re.search``:
#   * ``[0-9]`` rather than ``\d`` — same reason as :data:`_ID_PATTERN`: Python's
#     ``\d`` also matches full-width and Arabic-Indic digits.
#   * ``\A``/``\Z`` rather than ``^``/``$`` — Python's ``$`` also matches just
#     before a single trailing newline, so ``"...31'\n"`` would pass the schema.
#     It is harmless downstream (the parser strips), but a schema that accepts
#     what the parser would not is exactly the drift this module exists to
#     prevent. Note this makes the pattern Python-flavoured: an ECMA-262
#     validator reads ``\A`` as a literal ``A``. Enforcement is server-side only
#     (``mureo.mcp.server._build_tool_validators``), so that costs nothing today.
PERIOD_BETWEEN_PATTERN = (
    r"\ABETWEEN '([0-9]{4}-[0-9]{2}-[0-9]{2})' AND '([0-9]{4}-[0-9]{2}-[0-9]{2})'\Z"
)

# The tolerant form accepted at the parsing boundary (any case, any run of
# whitespace). Callers re-emit the clause from the validated endpoints, so a
# tolerant read never widens what is spliced into GAQL.
BETWEEN_CLAUSE_RE = re.compile(
    r"BETWEEN\s+'([0-9]{4}-[0-9]{2}-[0-9]{2})'\s+AND\s+'([0-9]{4}-[0-9]{2}-[0-9]{2})'",
    re.IGNORECASE,
)


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


def parse_between_clause(
    value: str, *, max_days: int = _DEFAULT_MAX_PERIOD_DAYS
) -> tuple[date, date]:
    """Return the inclusive endpoints of ``BETWEEN 'x' AND 'y'``.

    Both endpoints are re-validated individually, so callers can rebuild the
    clause from the returned dates rather than echoing attacker-supplied text.

    The span is bounded by ``max_days`` — the same bound
    :func:`validate_period_days` applies to a day count. ``ALL_TIME`` is left
    out of :data:`VALID_DATE_RANGE_CONSTANTS` precisely because an unbounded
    window bypasses that guard; a ``BETWEEN`` clause that may name any two
    dates is the same unbounded report by another spelling, and
    ``BETWEEN '1900-01-01' AND '2100-01-01'`` would have been the ``ALL_TIME``
    the whitelist refuses to offer. Bounding here also keeps callers that do
    date arithmetic on the result away from ``date.min`` / ``date.max``.
    """
    if not isinstance(value, str):
        raise GAQLValidationError(f"Invalid period: {value!r}")
    match = BETWEEN_CLAUSE_RE.fullmatch(value.strip())
    if match is None:
        raise GAQLValidationError(
            f"Invalid BETWEEN clause: {value!r} "
            "(expected: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD')"
        )
    endpoints: list[date] = []
    for raw, field in (
        (match.group(1), "period.start"),
        (match.group(2), "period.end"),
    ):
        validate_date(raw, field)
        try:
            endpoints.append(date.fromisoformat(raw))
        except ValueError as exc:  # e.g. 2026-13-01 — shaped right, not a date
            raise GAQLValidationError(f"Invalid {field}: {raw!r}") from exc
    start, end = endpoints[0], endpoints[1]
    if end < start:
        raise GAQLValidationError(
            f"Invalid BETWEEN clause: {value!r} (end date precedes start date)"
        )
    span = (end - start).days + 1
    if span > max_days:
        raise GAQLValidationError(
            f"Date range too long: {value!r} spans {span} days, "
            f"maximum {max_days}. Narrow the window."
        )
    return start, end


def format_between_clause(start: date, end: date) -> str:
    """Render an inclusive date pair as a GAQL ``BETWEEN`` clause."""
    if end < start:
        raise GAQLValidationError(
            f"Invalid date range: {start.isoformat()} precedes {end.isoformat()}"
        )
    return f"BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'"


def trailing_window(days: int, today: date) -> tuple[date, date]:
    """Return the inclusive ``days``-long window ending the day before ``today``.

    ``today`` is passed in rather than read from a clock so this module stays
    pure; callers supply :func:`mureo.core.clock.server_now`.
    """
    validate_period_days(days)
    end = today - timedelta(days=1)
    return end - timedelta(days=days - 1), end


def resolve_derived_date_range(period: str, today: date) -> str | None:
    """Return the ``BETWEEN`` clause a derived constant stands for.

    ``None`` when ``period`` is not one of :data:`DERIVED_DATE_RANGE_DAYS`, so
    callers fall through to their normal constant handling.
    """
    if not isinstance(period, str):
        return None
    days = DERIVED_DATE_RANGE_DAYS.get(period.strip().upper())
    if days is None:
        return None
    return format_between_clause(*trailing_window(days, today))


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


# ---------------------------------------------------------------------------
# Static-query marker (v0.9.24)
# ---------------------------------------------------------------------------

# Patterns that indicate a query is NOT a pure static string literal. Any
# of these means the caller is doing some kind of interpolation, which
# means the validator (not this marker) should be used.
_INTERPOLATION_PATTERNS = (
    "{",  # f-string / str.format placeholder
    "}",  # closing brace from same
    "%s",  # %-formatting positional
    "%d",  # %-formatting positional
    "%(",  # %-formatting named
    "$",  # string.Template ($name / ${name}). GAQL never legitimately
    # contains $ (verified across all current call sites), so flagging
    # any future Template-style interpolation is a free defensive line.
)


def validate_static_query(query: str) -> str:
    """Marker for GAQL queries that are 100% static string literals.

    Returns ``query`` unchanged so call sites can wrap their static
    queries with this marker as a signal to readers and reviewers:
    *"this query takes no external input — already audited."*

    The marker is **not** a security boundary on its own (a static
    string needs no validation), but it does enforce one invariant: the
    string must contain no formatting placeholders. If a future edit
    introduces ``f"... {var}"`` interpolation or ``"... %s"`` %-format,
    this marker will refuse to pass through. The contributor must then
    either (a) prove the inputs come from a trusted source and re-mark,
    or (b) route the dynamic part through :func:`validate_id`,
    :func:`escape_string_literal`, :func:`build_in_clause`, etc. — the
    actual validators.

    This satisfies the v0.9.23 audit gap: ``accounts.py`` had two raw
    GAQL queries bypassing the validator. They are static today, but
    nothing in the codebase signalled the intent or trapped future
    drift. Wrapping them in :func:`validate_static_query` does both.
    """
    if not isinstance(query, str):
        raise GAQLValidationError(
            f"validate_static_query expected str, got {type(query).__name__}"
        )
    if not query.strip():
        raise GAQLValidationError("validate_static_query: query is empty")
    for marker in _INTERPOLATION_PATTERNS:
        if marker in query:
            raise GAQLValidationError(
                f"validate_static_query: query is not static (contains "
                f"interpolation marker {marker!r}). Route the dynamic "
                f"part through the validator instead."
            )
    return query
