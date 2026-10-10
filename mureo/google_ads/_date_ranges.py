"""Period-over-period comparison windows for the Google Ads analysis layer.

Pure date arithmetic on top of :mod:`mureo.google_ads._gaql_validator`; it
imports nothing from the Google Ads SDK, so a caller that needs only the
windows (the built-in analytics modules, also in BYOD mode) does not pay the
SDK import for them, and never on the event loop (#809).
:mod:`mureo.google_ads._analysis_constants` re-exports these names.
"""

from __future__ import annotations

from datetime import date, timedelta

from mureo.core import clock
from mureo.google_ads._gaql_validator import (
    DERIVED_DATE_RANGE_DAYS,
    GAQLValidationError,
    format_between_clause,
    parse_between_clause,
    trailing_window,
)

# ---------------------------------------------------------------------------
# Period name -> days mapping (for non-overlapping period-over-period comparison)
#
# Only fixed-length trailing windows belong here: a period-over-period pair
# needs a length to build the *previous* window from. Calendar constants
# (THIS_MONTH, the week ranges) have no fixed length and are rejected rather
# than silently rounded to something else — see _get_comparison_date_ranges.
# ---------------------------------------------------------------------------

_PERIOD_DAYS: dict[str, int] = {
    "LAST_7_DAYS": 7,
    "LAST_14_DAYS": 14,
    "LAST_30_DAYS": 30,
    **DERIVED_DATE_RANGE_DAYS,
}


def _resolve_current_window(period: str) -> tuple[date, date]:
    """Return the inclusive (start, end) this comparison path will report on.

    Accepts a fixed-length trailing constant or an explicit
    ``BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`` range (#716/#718). Anything else
    raises: quietly substituting a 7-day window for a period the caller asked
    for is the #134 failure mode — the answer looks fine and describes the
    wrong dates.
    """
    if not isinstance(period, str):
        raise GAQLValidationError(f"Invalid period: {period!r}")
    text = period.strip()
    if text.upper().startswith("BETWEEN"):
        return parse_between_clause(text)
    days = _PERIOD_DAYS.get(text.upper())
    if days is None:
        raise GAQLValidationError(
            f"Period {period!r} cannot be compared period-over-period. Use one "
            f"of {', '.join(sorted(_PERIOD_DAYS))} or an explicit "
            "BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' range."
        )
    return trailing_window(days, clock.server_now().date())


def _get_comparison_date_ranges(period: str) -> tuple[str, str]:
    """Return non-overlapping current and previous periods in BETWEEN format for a given period.

    Example: LAST_7_DAYS ->
      Current: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (last 7 days)
      Previous: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (prior 7 days)

    For an explicit range the previous period is the equal-length window
    immediately before it, so the two never overlap.
    """
    current_start, current_end = _resolve_current_window(period)
    span = (current_end - current_start).days + 1
    try:
        prev_end = current_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
    except OverflowError as exc:
        # A window anchored within `span` days of date.min has no equal-length
        # predecessor. The span guard in parse_between_clause rules out the
        # 0001..9999 case; this catches the short-range-at-year-1 remainder so
        # the caller gets a GAQLValidationError like every other bad period,
        # not a bare OverflowError down the generic exception path.
        raise GAQLValidationError(
            f"Period {period!r} starts too early to have a comparable "
            f"preceding {span}-day window."
        ) from exc
    return (
        format_between_clause(current_start, current_end),
        format_between_clause(prev_start, prev_end),
    )
