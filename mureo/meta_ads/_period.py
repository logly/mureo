"""Period argument resolution for Meta Ads insights requests.

The Meta Graph API accepts either ``date_preset`` (a documented
named window like ``last_7d``) or ``time_range`` (an explicit
``{"since": …, "until": …}`` pair). The Meta Ads MCP tools expose a
single ``period`` string that may be either shape — this module
normalises it into one of those API shapes, and rejects unknown
values with :class:`ValueError` rather than silently degrading the
request to ``last_7d`` (Issue #134).

A companion :func:`previous_period` builds the corresponding prior
window so period-over-period analyses (``meta_ads_analysis_cost``,
``meta_ads_analysis_performance``) can return a previous block that
genuinely sits immediately before the current block — not the
last_30d superset of last_7d that the pre-fix code produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Final

# The Meta ``date_preset`` values advertised by the Meta Ads MCP tool
# descriptions. Keep aligned with ``_PERIOD_PARAM`` in
# ``mureo/mcp/_tools_meta_ads_insights.py`` so the surface and the
# implementation never drift apart again.
_DATE_PRESETS: Final[frozenset[str]] = frozenset(
    {
        "today",
        "yesterday",
        "last_7d",
        "last_14d",
        "last_30d",
        "last_90d",
        "this_month",
        "last_month",
    }
)

# Length-in-days for the presets that map to a fixed-length window.
# Calendar-relative presets (``this_month`` / ``last_month``) are
# absent on purpose — their length depends on the current month, so
# consumers must treat them separately.
_PRESET_DAYS: Final[dict[str, int]] = {
    # ``today`` and ``yesterday`` share length 1 but anchor at
    # different days — keep that in mind when reasoning about windows.
    "today": 1,
    "yesterday": 1,
    "last_7d": 7,
    "last_14d": 14,
    "last_30d": 30,
    "last_90d": 90,
}


@dataclass(frozen=True)
class ResolvedPeriod:
    """Result of resolving a ``period`` string.

    Exactly one of ``date_preset`` / ``time_range`` is populated.
    ``time_range`` is a ``(since, until)`` tuple of ``YYYY-MM-DD``
    strings, both endpoints inclusive (Meta's documented convention).
    """

    date_preset: str | None = None
    time_range: tuple[str, str] | None = None

    @property
    def is_preset(self) -> bool:
        return self.date_preset is not None

    @property
    def days(self) -> int:
        """Inclusive length of the window in days.

        For an explicit ``time_range`` this is ``until - since + 1``.
        For a fixed-length preset (``last_Nd`` / ``today`` /
        ``yesterday``) this is the documented length. For a
        calendar-relative preset (``this_month`` / ``last_month``)
        the value is ``0`` — there is no fixed length, and callers
        that need one must resolve to an explicit range first.
        """
        if self.time_range is not None:
            since, until = self.time_range
            return (date.fromisoformat(until) - date.fromisoformat(since)).days + 1
        return _PRESET_DAYS.get(self.date_preset or "", 0)

    def to_api_params(self) -> dict[str, Any]:
        """Build the Meta API request parameters for this resolved
        period.

        Returns a fresh dict with exactly one key — ``date_preset`` or
        ``time_range`` — depending on which form the resolver chose.
        The ``time_range`` value is the JSON-encoded
        ``{"since": …, "until": …}`` shape Meta expects.

        Raises:
            RuntimeError: The dataclass somehow has neither field
                populated. ``resolve_period`` cannot construct such
                an instance, so this only fires if an external caller
                ignored the API and built a ``ResolvedPeriod()`` by
                hand.
        """
        if self.date_preset is not None:
            return {"date_preset": self.date_preset}
        if self.time_range is not None:
            since, until = self.time_range
            return {"time_range": json.dumps({"since": since, "until": until})}
        raise RuntimeError(
            "ResolvedPeriod is empty: neither date_preset nor "
            "time_range is set. Build via resolve_period(...)."
        )


def resolve_period(period: str) -> ResolvedPeriod:
    """Resolve a ``period`` string to a Meta API request shape.

    Args:
        period: Either a documented Meta ``date_preset`` name
            (``today``, ``yesterday``, ``last_7d``, ``last_14d``,
            ``last_30d``, ``last_90d``, ``this_month``,
            ``last_month``) or an explicit ``YYYY-MM-DD..YYYY-MM-DD``
            range with both endpoints inclusive.

    Returns:
        A :class:`ResolvedPeriod` describing whether the caller should
        send ``date_preset`` or ``time_range`` to Meta.

    Raises:
        ValueError: ``period`` is empty, not a string, not a
            documented preset, contains the wrong number of ``..``
            separators, has a malformed ISO date, or has
            ``since`` > ``until``.
    """
    if not isinstance(period, str) or not period:
        raise ValueError(f"period must be a non-empty string, got {period!r}")
    if period in _DATE_PRESETS:
        return ResolvedPeriod(date_preset=period)
    if ".." in period:
        return _resolve_range(period)
    raise ValueError(
        f"period {period!r} is not a Meta date_preset and not a valid "
        f"YYYY-MM-DD..YYYY-MM-DD range. Accepted presets: "
        f"{sorted(_DATE_PRESETS)}"
    )


def _resolve_range(period: str) -> ResolvedPeriod:
    parts = period.split("..")
    if len(parts) != 2:
        raise ValueError(
            f"period {period!r} contains multiple '..' separators; "
            f"expected exactly one (YYYY-MM-DD..YYYY-MM-DD)"
        )
    since_str, until_str = parts[0], parts[1]
    try:
        since = date.fromisoformat(since_str)
        until = date.fromisoformat(until_str)
    except ValueError as exc:
        raise ValueError(
            f"period {period!r} contains a malformed date (expected "
            f"YYYY-MM-DD..YYYY-MM-DD): {exc}"
        ) from exc
    if since > until:
        raise ValueError(
            f"period {period!r}: 'since' ({since_str}) is after 'until' "
            f"({until_str})"
        )
    return ResolvedPeriod(time_range=(since_str, until_str))


def previous_period(period: str, *, today: date | None = None) -> str:
    """Return the previous-window for ``period`` in the same shape.

    For an explicit ``YYYY-MM-DD..YYYY-MM-DD`` range, the previous
    window is the same-length window immediately before ``since``.
    For ``this_month``, the natural previous is the matching preset
    name ``last_month``. For ``last_month``, return an explicit
    ``YYYY-MM-DD..YYYY-MM-DD`` for the calendar month before that.
    For fixed-length presets (``today`` / ``yesterday`` /
    ``last_Nd``) the previous is an explicit range that does NOT
    overlap the current window — this is the bug fix at the heart of
    Issue #134, where the pre-fix code mapped ``last_7d`` to
    ``last_30d`` (a superset, not a previous).

    Args:
        period: A value :func:`resolve_period` accepts.
        today: The anchor date for converting presets to explicit
            ranges. Defaults to :func:`date.today`. Injectable for
            deterministic testing.

    Returns:
        A string suitable for round-tripping through
        :func:`resolve_period` — either a preset name (``"yesterday"``
        for ``"today"``; ``"last_month"`` for ``"this_month"``) or a
        ``YYYY-MM-DD..YYYY-MM-DD`` range. The asymmetry is
        deliberate: when a documented preset cleanly names the prior
        window, we return the cheaper preset form so the Meta API
        call doesn't carry an explicit range.

        ``last_Nd`` is treated as "the N complete days ending
        yesterday" — the most conservative interpretation of Meta's
        own definition. The returned previous-window therefore ends
        at ``anchor - N`` and never overlaps the current window, but
        the operator should be aware that today's partial-day data
        is in neither window when comparing.

    Raises:
        ValueError: Propagated from :func:`resolve_period` for any
            invalid ``period``.
    """
    anchor = today if today is not None else date.today()

    # ``this_month`` has a natural preset previous; round-tripping
    # through preset names keeps the Meta API call cheap.
    if period == "this_month":
        return "last_month"

    if period == "last_month":
        first_of_this = anchor.replace(day=1)
        last_of_last = first_of_this - timedelta(days=1)
        first_of_last = last_of_last.replace(day=1)
        last_of_prev = first_of_last - timedelta(days=1)
        first_of_prev = last_of_prev.replace(day=1)
        return f"{first_of_prev.isoformat()}..{last_of_prev.isoformat()}"

    rp = resolve_period(period)

    if rp.time_range is not None:
        since = date.fromisoformat(rp.time_range[0])
        length = rp.days
        prev_until = since - timedelta(days=1)
        prev_since = prev_until - timedelta(days=length - 1)
        return f"{prev_since.isoformat()}..{prev_until.isoformat()}"

    # Fixed-length presets. ``last_Nd`` ends at the most recent
    # complete day (conventionally yesterday); ``today`` is itself;
    # ``yesterday`` is the single day before today.
    if rp.date_preset == "today":
        return "yesterday"
    if rp.date_preset == "yesterday":
        d = anchor - timedelta(days=2)
        return f"{d.isoformat()}..{d.isoformat()}"

    days = _PRESET_DAYS[rp.date_preset or ""]
    cur_until = anchor - timedelta(days=1)
    cur_since = cur_until - timedelta(days=days - 1)
    prev_until = cur_since - timedelta(days=1)
    prev_since = prev_until - timedelta(days=days - 1)
    return f"{prev_since.isoformat()}..{prev_until.isoformat()}"


__all__ = [
    "ResolvedPeriod",
    "previous_period",
    "resolve_period",
]
