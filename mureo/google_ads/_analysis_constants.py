"""Common constants and helper functions for analysis modules."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Period name -> days mapping (for non-overlapping period-over-period comparison)
# ---------------------------------------------------------------------------

_PERIOD_DAYS: dict[str, int] = {
    "LAST_7_DAYS": 7,
    "LAST_14_DAYS": 14,
    "LAST_30_DAYS": 30,
}

# ---------------------------------------------------------------------------
# Common mapping constants (eliminate duplicate definitions)
# ---------------------------------------------------------------------------

_MATCH_TYPE_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "EXACT",
    3: "PHRASE",
    4: "BROAD",
}

_STATUS_MAP: dict[int, str] = {
    0: "UNSPECIFIED",
    1: "UNKNOWN",
    2: "ENABLED",
    3: "PAUSED",
    4: "REMOVED",
}

# ---------------------------------------------------------------------------
# Informational query patterns
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


def _get_comparison_date_ranges(period: str) -> tuple[str, str]:
    """Return non-overlapping current and previous periods in BETWEEN format for a given period.

    Example: LAST_7_DAYS ->
      Current: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (last 7 days)
      Previous: BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD' (prior 7 days)
    """
    days = _PERIOD_DAYS.get(period.upper(), 7)
    today = date.today()
    current_end = today - timedelta(days=1)
    current_start = today - timedelta(days=days)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    fmt = "%Y-%m-%d"
    current = (
        f"BETWEEN '{current_start.strftime(fmt)}' AND '{current_end.strftime(fmt)}'"
    )
    previous = f"BETWEEN '{prev_start.strftime(fmt)}' AND '{prev_end.strftime(fmt)}'"
    return current, previous


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
