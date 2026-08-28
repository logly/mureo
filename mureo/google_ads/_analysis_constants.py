"""Common constants and helper functions for analysis modules."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from mureo.core import clock
from mureo.google_ads._enum_names import KEYWORD_MATCH_TYPE_MAP
from mureo.google_ads._gaql_validator import (
    DERIVED_DATE_RANGE_DAYS,
    GAQLValidationError,
    format_between_clause,
    parse_between_clause,
    trailing_window,
)
from mureo.google_ads.mappers import AD_GROUP_CRITERION_STATUS_MAP

logger = logging.getLogger(__name__)

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

# ---------------------------------------------------------------------------
# Common mapping constants (eliminate duplicate definitions)
#
# Both were transcribed by hand and both happened to be right; they are now
# aliases of the SDK-derived maps so they cannot drift from the API version
# (#588). The names are kept because the analysis modules read them.
# ---------------------------------------------------------------------------

_MATCH_TYPE_MAP: dict[int, str] = KEYWORD_MATCH_TYPE_MAP

_STATUS_MAP: dict[int, str] = AD_GROUP_CRITERION_STATUS_MAP

# ---------------------------------------------------------------------------
# Informational query patterns. Japanese tokens that signal informational
# (non-commercial) search intent — e.g. "とは" (what is), "比較" (compare),
# "口コミ" (reviews). Kept in Japanese because mureo is designed to
# classify Japanese ad-platform search terms.
# ---------------------------------------------------------------------------

_INFORMATIONAL_PATTERNS: tuple[str, ...] = (
    "とは",
    "比較",
    "方法",
    "無料",
    "やり方",
    "仕組み",
    "口コミ",
    "評判",
    "ランキング",
    "おすすめ",
    "違い",
)


# ---------------------------------------------------------------------------
# Common helper functions
# ---------------------------------------------------------------------------


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


def _calc_change_rate(current: float, previous: float) -> float | None:
    """Calculate change rate (%). Returns None if previous value is 0."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def _safe_metrics(perf: list[dict[str, Any]]) -> dict[str, Any]:
    """Safely extract the first metrics entry from a performance report."""
    if perf:
        return perf[0].get("metrics", {})  # type: ignore[no-any-return]
    return {"impressions": 0, "clicks": 0, "cost": 0}


def _extract_ngrams(text: str, n: int) -> list[str]:
    """Extract N-grams from text (space-delimited)."""
    words = text.strip().split()
    if len(words) < n:
        return [text.strip()] if text.strip() else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def _resolve_enum(raw_value: int | Any, mapping: dict[int, str]) -> str:
    """Convert protobuf enum int to string. Uses .name for enum types."""
    if isinstance(raw_value, int):
        return mapping.get(raw_value, str(raw_value))
    return raw_value.name if hasattr(raw_value, "name") else str(raw_value)
