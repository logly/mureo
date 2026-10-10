"""Common constants and helper functions for analysis modules."""

from __future__ import annotations

import logging
from typing import Any

# The comparison-window helpers are pure date arithmetic and live in an
# SDK-free module, so a caller that needs only them does not import the SDK
# through ``mappers`` below (#809). Re-exported here for existing importers.
from mureo.google_ads._date_ranges import _PERIOD_DAYS as _PERIOD_DAYS  # noqa: F401
from mureo.google_ads._date_ranges import (  # noqa: F401
    _get_comparison_date_ranges as _get_comparison_date_ranges,
)
from mureo.google_ads._date_ranges import (  # noqa: F401
    _resolve_current_window as _resolve_current_window,
)
from mureo.google_ads._enum_names import KEYWORD_MATCH_TYPE_MAP
from mureo.google_ads.mappers import AD_GROUP_CRITERION_STATUS_MAP

logger = logging.getLogger(__name__)

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
# (non-commercial) search intent — e.g. the Japanese for "what is",
# "compare" and "reviews" (the first, second and seventh entries below).
# Kept in Japanese because mureo is designed to classify Japanese
# ad-platform search terms.
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
