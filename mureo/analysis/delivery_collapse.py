"""Delivery-collapse detection — the inverse of a cost spike (#546).

``cost_increase_investigate`` answers "why did spend jump?". Nothing
answered its opposite: a campaign whose status still says ENABLED while
its impressions have gone to zero. That contradiction — *configured to
serve, serving nothing* — is the most detectable failure mode in ad
operations, and it is what separates a real fault from an intentional
pause.

Why this is not :mod:`mureo.analysis.anomaly_detector`
------------------------------------------------------
The generic anomaly path takes one campaign's current metrics by hand
and baselines them off ``action_log`` history. On an account operated
partly by hand that history is thin or empty, so the baseline is
``None`` and the detector goes quiet exactly where it is needed. This
module baselines off the **platform's own daily delivery series**
(:data:`BASELINE_SOURCE`) and never reads ``action_log`` at all.

Why the baseline is weekday-aware
---------------------------------
Delivery is seasonal within the week. A retail account can run 350k
impressions on a Tuesday and 15k on a Saturday — a 96% swing that a
flat median would report as a collapse every single weekend. A detector
that cries wolf on Saturdays gets muted, and a muted detector is worth
nothing, so the baseline for a given day is the median of the *same
weekday* inside the trailing window whenever there are enough samples
for it (falling back to the all-day median otherwise, which is recorded
on the signal as :class:`BaselineMethod`).

Why only complete days count
----------------------------
Budget pacing spreads a day's impressions unevenly, so a partially
elapsed day always looks like a cliff. Everything at or after
``as_of`` (the host's today, via :func:`mureo.core.clock.server_now`)
is dropped before any comparison happens.

This module is pure: no network, no filesystem, no clock except the
injectable ``as_of``. Detection is deliberately separable from
diagnosis (:mod:`mureo.analysis.collapse_diagnosis`) — knowing that a
campaign died is actionable on its own, hours before anyone knows why.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

#: Provenance stamped on every signal. Pinned by the test-suite: the
#: whole point of this detector is that its baseline does NOT come from
#: ``action_log``.
BASELINE_SOURCE = "platform_daily_delivery"

DEFAULT_DROP_PCT = 90.0
DEFAULT_MIN_BASELINE_IMPRESSIONS = 1_000
DEFAULT_BASELINE_DAYS = 28
DEFAULT_MIN_BASELINE_DAYS = 14
DEFAULT_CONSECUTIVE_DAYS = 1
DEFAULT_MIN_SAME_WEEKDAY_SAMPLES = 2

#: Status tokens that mean "this campaign is configured to serve", across
#: every platform vocabulary mureo touches: Google Ads (``ENABLED``),
#: Meta (``ACTIVE``), TikTok (``ENABLE``), and the serving-status spellings
#: bridges and plugins report. Compared case-insensitively.
SERVING_STATUSES: frozenset[str] = frozenset(
    {
        "ENABLED",
        "ENABLE",
        "ACTIVE",
        "RUNNING",
        "SERVING",
        "DELIVERING",
        "ELIGIBLE",
    }
)


class CollapseSeverity(str, Enum):
    """Two tiers only — same rationale as the anomaly detector's.

    ``CRITICAL`` is reserved for a total stop (zero impressions on every
    collapsed day); a severe-but-nonzero drop is ``HIGH``.
    """

    CRITICAL = "critical"
    HIGH = "high"


_SEVERITY_ORDER: dict[CollapseSeverity, int] = {
    CollapseSeverity.CRITICAL: 0,
    CollapseSeverity.HIGH: 1,
}


class BaselineMethod(str, Enum):
    """How the day's baseline was computed. Reported on every signal."""

    SAME_WEEKDAY_MEDIAN = "same_weekday_median"
    ALL_DAY_MEDIAN = "all_day_median"


@dataclass(frozen=True)
class DailyDelivery:
    """One complete day of delivery for one campaign."""

    date: date
    impressions: int
    clicks: int = 0
    cost: float = 0.0


@dataclass(frozen=True)
class DeliverySeries:
    """One campaign's day-grain delivery, normalised across platforms.

    ``status`` is the platform's own spelling (see
    :data:`SERVING_STATUSES`). ``end_date`` is the campaign's flight end
    when the platform reports one; a finished flight stops serving while
    its status stays ENABLED, which is not a fault.
    """

    platform: str
    campaign_id: str
    status: str
    daily: tuple[DailyDelivery, ...]
    campaign_name: str = ""
    end_date: date | None = None


@dataclass(frozen=True)
class CollapseThresholds:
    """Operator-tunable detection thresholds.

    Every field is settable from STRATEGY.md's ``## Guardrails`` section
    as ``- delivery_collapse_<field>: <value>`` — see
    :func:`collapse_thresholds_from_strategy_text`. The defaults are
    deliberately conservative: a 90% drop against a campaign's own
    same-weekday baseline is not ad-ops variance, it is a fault.
    """

    drop_pct: float = DEFAULT_DROP_PCT
    min_baseline_impressions: int = DEFAULT_MIN_BASELINE_IMPRESSIONS
    baseline_days: int = DEFAULT_BASELINE_DAYS
    min_baseline_days: int = DEFAULT_MIN_BASELINE_DAYS
    consecutive_days: int = DEFAULT_CONSECUTIVE_DAYS
    min_same_weekday_samples: int = DEFAULT_MIN_SAME_WEEKDAY_SAMPLES


@dataclass(frozen=True)
class CollapseSignal:
    """One campaign whose delivery fell off a cliff while set to serve."""

    platform: str
    campaign_id: str
    campaign_name: str
    status: str
    severity: CollapseSeverity
    collapse_start_date: str
    days_at_collapse: int
    current_impressions: int
    baseline_impressions: float
    drop_pct: float
    current_cost: float
    baseline_cost: float
    baseline_method: BaselineMethod
    baseline_days_used: int
    baseline_samples: int
    evaluated_through: str
    message: str
    recommended_action: str
    baseline_source: str = BASELINE_SOURCE


@dataclass(frozen=True)
class _Baseline:
    """Internal: the reference level one day is compared against."""

    impressions: float
    cost: float
    method: BaselineMethod
    days_used: int
    samples: int


def is_serving_status(status: str) -> bool:
    """Return ``True`` when ``status`` says the campaign should serve."""
    return status.strip().upper() in SERVING_STATUSES


def detect_delivery_collapse(
    series: DeliverySeries,
    *,
    thresholds: CollapseThresholds | None = None,
    as_of: date | None = None,
) -> CollapseSignal | None:
    """Return a signal when ``series`` has collapsed, else ``None``.

    Note the signature: a delivery series and thresholds, nothing else.
    There is deliberately no ``action_log`` parameter — reintroducing one
    would reinstate the empty-history blind spot this detector exists to
    close.
    """
    resolved = thresholds or CollapseThresholds()
    if not is_serving_status(series.status):
        # Not a fault: somebody meant to stop this campaign.
        return None

    complete = _complete_days(series.daily, as_of=as_of)
    found = _walk_back_collapse(complete, resolved)
    if found is None:
        return None
    start_index, baseline = found

    if len(complete) - start_index < resolved.consecutive_days:
        return None
    cliff = complete[start_index].date
    if series.end_date is not None and cliff > series.end_date:
        # The flight ended; zero delivery afterwards is expected.
        return None
    return _build_signal(series, complete, start_index, baseline)


def detect_delivery_collapses(
    all_series: Iterable[DeliverySeries],
    *,
    thresholds: CollapseThresholds | None = None,
    as_of: date | None = None,
) -> tuple[CollapseSignal, ...]:
    """Run :func:`detect_delivery_collapse` over many campaigns.

    Ordered CRITICAL first, then by campaign id, so the caller can render
    the list verbatim.
    """
    signals = [
        signal
        for series in all_series
        if (
            signal := detect_delivery_collapse(
                series, thresholds=thresholds, as_of=as_of
            )
        )
        is not None
    ]
    signals.sort(key=lambda s: (_SEVERITY_ORDER[s.severity], s.campaign_id))
    return tuple(signals)


def _complete_days(
    daily: Sequence[DailyDelivery], *, as_of: date | None
) -> tuple[DailyDelivery, ...]:
    """Chronological days strictly before ``as_of`` (today by default).

    The current day is always partial — budget pacing makes it look like
    a cliff every morning — so it never takes part in a comparison.
    """
    if as_of is None:
        from mureo.core import clock

        as_of = clock.server_now().date()
    return tuple(sorted((d for d in daily if d.date < as_of), key=lambda d: d.date))


def _walk_back_collapse(
    complete: Sequence[DailyDelivery],
    thresholds: CollapseThresholds,
) -> tuple[int, _Baseline] | None:
    """Find the earliest day from which delivery has stayed collapsed.

    The baseline window always sits STRICTLY BEFORE the candidate cliff,
    and every later day is judged against that same pre-cliff window.
    Judging each day against the window immediately preceding *it* would
    let a long outage redefine "normal": once the collapse outlives half
    the window the median falls to zero, nothing looks like a drop any
    more, and the detector goes quiet on the worst possible account —
    exactly the week-long incident this was built for.

    Returns ``(collapse_start_index, baseline_at_the_cliff)`` or ``None``.
    """
    start: int | None = None
    baseline_at_start: _Baseline | None = None
    candidate = len(complete) - 1
    while candidate >= 0:
        window = complete[max(0, candidate - thresholds.baseline_days) : candidate]
        if len(window) < thresholds.min_baseline_days:
            break
        baseline = _baseline_for(complete[candidate], window, thresholds)
        if not all(
            _is_collapsed(day, window, thresholds) for day in complete[candidate:]
        ):
            break
        start, baseline_at_start = candidate, baseline
        candidate -= 1
    if start is None or baseline_at_start is None:
        return None
    return start, baseline_at_start


def _is_collapsed(
    day: DailyDelivery,
    window: Sequence[DailyDelivery],
    thresholds: CollapseThresholds,
) -> bool:
    """Is ``day`` collapsed against a baseline drawn from ``window``?"""
    baseline = _baseline_for(day, window, thresholds)
    if baseline.impressions < thresholds.min_baseline_impressions:
        return False
    return _drop_pct(day.impressions, baseline.impressions) >= thresholds.drop_pct


def _baseline_for(
    day: DailyDelivery,
    window: Sequence[DailyDelivery],
    thresholds: CollapseThresholds,
) -> _Baseline:
    """Median baseline for ``day``, same-weekday when there is enough of it.

    Median rather than mean: one promotional spike in the window must not
    inflate the bar and turn every ordinary day that follows into an
    alert.
    """
    same_weekday = [d for d in window if d.date.weekday() == day.date.weekday()]
    if len(same_weekday) >= thresholds.min_same_weekday_samples:
        sample, method = same_weekday, BaselineMethod.SAME_WEEKDAY_MEDIAN
    else:
        sample, method = list(window), BaselineMethod.ALL_DAY_MEDIAN
    return _Baseline(
        impressions=float(statistics.median(d.impressions for d in sample)),
        cost=float(statistics.median(d.cost for d in sample)),
        method=method,
        days_used=len(window),
        samples=len(sample),
    )


def _drop_pct(current: float, baseline: float) -> float:
    """Percentage ``current`` sits below ``baseline`` (0 when unusable)."""
    if baseline <= 0:
        return 0.0
    return 100.0 * (1.0 - (current / baseline))


def _build_signal(
    series: DeliverySeries,
    complete: Sequence[DailyDelivery],
    start_index: int,
    baseline: _Baseline,
) -> CollapseSignal:
    """Render the detected run of collapsed days as a signal."""
    collapsed = complete[start_index:]
    latest = collapsed[-1]
    severity = (
        CollapseSeverity.CRITICAL
        if all(d.impressions == 0 for d in collapsed)
        else CollapseSeverity.HIGH
    )
    drop = _drop_pct(latest.impressions, baseline.impressions)
    days = len(collapsed)
    return CollapseSignal(
        platform=series.platform,
        campaign_id=series.campaign_id,
        campaign_name=series.campaign_name,
        status=series.status,
        severity=severity,
        collapse_start_date=collapsed[0].date.isoformat(),
        days_at_collapse=days,
        current_impressions=latest.impressions,
        baseline_impressions=baseline.impressions,
        drop_pct=drop,
        current_cost=latest.cost,
        baseline_cost=baseline.cost,
        baseline_method=baseline.method,
        baseline_days_used=baseline.days_used,
        baseline_samples=baseline.samples,
        evaluated_through=latest.date.isoformat(),
        message=(
            f"Impressions are {drop:.1f}% below this campaign's own "
            f"{baseline.method.value} baseline of {baseline.impressions:,.0f}/day, "
            f"starting {collapsed[0].date.isoformat()} ({days} day(s) so far), "
            f"while its status is still {series.status}."
        ),
        recommended_action=(
            "Run analysis_delivery_collapse_diagnose for this campaign: overlay "
            "the change feed on the daily series and walk the elimination "
            "ladder (ad approval/policy, billing, budget, bid competitiveness, "
            "targeting and exclusions, learning state, flight dates)."
        ),
    )


# ---------------------------------------------------------------------------
# Normalisation — the shared entry point for every platform
# ---------------------------------------------------------------------------


def delivery_series_from_rows(
    rows: Iterable[dict[str, Any]],
    *,
    platform: str,
) -> tuple[DeliverySeries, ...]:
    """Group day-grain platform rows into per-campaign series.

    This is what makes the detector genuinely cross-platform: a hosted
    connector, an official-MCP bridge, or a plugin only has to produce
    rows of ``{campaign_id, status, date, impressions, clicks, cost}``
    (plus optional ``campaign_name`` / ``end_date``) to get the same
    detection the native platforms get.

    Rows without a usable ``campaign_id`` are dropped — folding them into
    a synthetic ``""`` campaign would silently mix several campaigns'
    delivery. A malformed ``date`` raises :class:`ValueError`: guessing
    at it would misplace the cliff.
    """
    grouped: dict[str, list[DailyDelivery]] = {}
    attributes: dict[str, tuple[str, str, date | None]] = {}
    for row in rows:
        campaign_id = str(row.get("campaign_id") or "").strip()
        if not campaign_id:
            continue
        grouped.setdefault(campaign_id, []).append(
            DailyDelivery(
                date=_parse_date(row.get("date")),
                impressions=_to_int(row.get("impressions")),
                clicks=_to_int(row.get("clicks")),
                cost=_to_float(row.get("cost")),
            )
        )
        if campaign_id not in attributes:
            attributes[campaign_id] = (
                str(row.get("campaign_name") or ""),
                str(row.get("status") or ""),
                _parse_optional_date(row.get("end_date")),
            )
    return tuple(
        DeliverySeries(
            platform=platform,
            campaign_id=campaign_id,
            campaign_name=attributes[campaign_id][0],
            status=attributes[campaign_id][1],
            end_date=attributes[campaign_id][2],
            daily=tuple(sorted(days, key=lambda d: d.date)),
        )
        for campaign_id, days in sorted(grouped.items())
    )


def _parse_date(value: Any) -> date:
    """Parse a ``YYYY-MM-DD`` date; raise :class:`ValueError` otherwise."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError as exc:
            raise ValueError(f"unparseable delivery date: {value!r}") from exc
    raise ValueError(f"unparseable delivery date: {value!r}")


def _parse_optional_date(value: Any) -> date | None:
    """Same as :func:`_parse_date` but tolerates an absent value."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_date(value)


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Thresholds from STRATEGY.md ## Guardrails
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")

#: ``## Guardrails`` bullet key -> :class:`CollapseThresholds` field.
GUARDRAIL_KEYS: dict[str, str] = {
    "delivery_collapse_drop_pct": "drop_pct",
    "delivery_collapse_min_baseline_impressions": "min_baseline_impressions",
    "delivery_collapse_baseline_days": "baseline_days",
    "delivery_collapse_min_baseline_days": "min_baseline_days",
    "delivery_collapse_consecutive_days": "consecutive_days",
    "delivery_collapse_min_same_weekday_samples": "min_same_weekday_samples",
}

_INTEGER_FIELDS = frozenset(GUARDRAIL_KEYS.values()) - {"drop_pct"}


def collapse_thresholds_from_guardrails_text(content: str) -> CollapseThresholds:
    """Parse a ``## Guardrails`` body into :class:`CollapseThresholds`.

    Mirrors :func:`mureo.policy.strategy_gate.parse_guardrails`: unknown
    keys are ignored (forward compatibility) and a malformed or
    out-of-range value drops that one rule rather than failing the parse
    — a typo in one bullet must not silently disable detection.
    """
    thresholds = CollapseThresholds()
    for line in content.splitlines():
        match = _BULLET_RE.match(line)
        if match is None:
            continue
        field = GUARDRAIL_KEYS.get(match.group(1).lower())
        if field is None:
            continue
        value = _valid_threshold(field, match.group(2))
        if value is not None:
            # ``replace`` is typed per-field; the key is validated against
            # GUARDRAIL_KEYS above, so the dynamic field name is sound.
            thresholds = replace(thresholds, **{field: value})  # type: ignore[arg-type]
    return thresholds


def _valid_threshold(field: str, raw: str) -> float | int | None:
    """Coerce + range-check one bullet value; ``None`` rejects it."""
    try:
        number = float(raw.replace(",", "").replace("_", "").strip())
    except (AttributeError, ValueError):
        return None
    if field == "drop_pct":
        return number if 0.0 < number <= 100.0 else None
    if field in _INTEGER_FIELDS:
        return int(number) if number >= 1 else None
    return None  # pragma: no cover — defensive: every key maps to a branch


def collapse_thresholds_from_strategy_text(text: str) -> CollapseThresholds:
    """Extract thresholds from full STRATEGY.md text (defaults if absent)."""
    # Local imports: this module stays import-light for the pure path, and
    # ``strategy_gate`` owns the canonical heading name so the two cannot
    # drift onto different sections.
    from mureo.context.strategy import parse_strategy
    from mureo.policy.strategy_gate import GUARDRAILS_HEADING

    for entry in parse_strategy(text):
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            return collapse_thresholds_from_guardrails_text(entry.content)
    return CollapseThresholds()


__all__ = [
    "BASELINE_SOURCE",
    "GUARDRAIL_KEYS",
    "SERVING_STATUSES",
    "BaselineMethod",
    "CollapseSeverity",
    "CollapseSignal",
    "CollapseThresholds",
    "DailyDelivery",
    "DeliverySeries",
    "collapse_thresholds_from_guardrails_text",
    "collapse_thresholds_from_strategy_text",
    "delivery_series_from_rows",
    "detect_delivery_collapse",
    "detect_delivery_collapses",
    "is_serving_status",
]
