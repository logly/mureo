"""Deterministic outcome evaluation for logged actions.

Pure, I/O-free. Given the ``metrics_at_action`` baseline recorded on an
``action_log`` entry and the current metrics for the same campaign, decide
whether the change **improved**, **regressed**, **held** or is
**inconclusive**. This turns the observation-window review daily-check
performs from an LLM judgement call into a reproducible verdict, and gives
``/learn`` a trustworthy signal.

Platform-agnostic: it only compares numbers, so it works for any platform
(google_ads / meta_ads / tiktok_ads / plugins) as long as the caller feeds
comparable before/after metric names.

The rules (#888):

- **One primary metric decides.** The caller's choice (a declared expected
  effect, the campaign's bidding target), else ``cpa`` when both sides have
  conversions, else nothing — ``inconclusive`` with ``no_primary_metric``.
  Every other metric is a reference row: scored, never deciding.
- **Synonyms merge first.** Names go through
  :func:`mureo.context.expected.canonical_metric`, so ``cost_per_conversion``
  is ``cpa`` and ``cost`` is ``spend``; one value per metric is kept.
- **Volume floor.** Both sides must reach the floor for the primary's count
  (:data:`VOLUME_GATE`), on the raw counts — else ``insufficient_volume``,
  or ``volume_unknown`` when a count is missing.
- **Counts per day.** Count metrics (:data:`COUNT_METRICS`) are compared per
  day when both sides' day counts are known (:func:`period_days`); a count
  primary without them is ``period_unknown``, and a count reference row
  without them is compared raw and says so. Ratios compare as they are.
- **A held-back primary row says so.** When a gate or a zero baseline
  holds the verdict back, the primary's own row is ``inconclusive`` too and
  its note leads with the reason code, so the row never contradicts the
  verdict.
- **Noise band.** A primary that moved less than ``noise_pct`` is
  ``inconclusive`` with ``no_change`` — the same sample-size / noise
  discipline the ``_mureo-learning`` skill states.
- A zero (or negative) baseline is ``inconclusive`` with ``zero_baseline``
  (no ratio is computable) rather than a fabricated 100% swing; a metric
  missing on either side is not a row at all.

``held`` is never produced here: it is the verdict for an expected ``hold``,
which :mod:`mureo.analysis.expected_eval` judges.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Final

from mureo.context.expected import canonical_metric
from mureo.core.metrics_windows import CANONICAL_METRICS_WINDOWS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.expected import ExpectedEffect

# A swing smaller than this (percent) is treated as day-to-day variance, not a
# real outcome. Matches the anomaly detector's "a single bad day is noise".
DEFAULT_NOISE_PCT = 10.0

#: Per-side floors of the volume gate: the sample sizes the
#: ``_mureo-learning`` skill states, enforced here.
DEFAULT_MIN_CONVERSIONS: Final = 30
DEFAULT_MIN_IMPRESSIONS: Final = 1000
DEFAULT_MIN_CLICKS: Final = 200

#: ``basis`` values: who chose the primary metric.
BASIS_EXPECTED: Final = "expected"
BASIS_BIDDING_TARGET: Final = "bidding_target"
BASIS_DEFAULT: Final = "default"

#: The metric the evaluator falls back to when nothing chose one.
DEFAULT_PRIMARY_METRIC: Final = "cpa"

#: Why a result is ``inconclusive``. A closed set, in the order the rules
#: apply; :data:`GATE_REASONS` are the ones decided before any judging.
REASON_NO_PRIMARY_METRIC: Final = "no_primary_metric"
REASON_INSUFFICIENT_VOLUME: Final = "insufficient_volume"
REASON_VOLUME_UNKNOWN: Final = "volume_unknown"
REASON_PERIOD_UNKNOWN: Final = "period_unknown"
REASON_ZERO_BASELINE: Final = "zero_baseline"
REASON_TARGET_NOT_REACHED: Final = "target_not_reached"
REASON_NO_CHANGE: Final = "no_change"
OUTCOME_REASONS: Final[tuple[str, ...]] = (
    REASON_NO_PRIMARY_METRIC,
    REASON_INSUFFICIENT_VOLUME,
    REASON_VOLUME_UNKNOWN,
    REASON_PERIOD_UNKNOWN,
    REASON_ZERO_BASELINE,
    REASON_TARGET_NOT_REACHED,
    REASON_NO_CHANGE,
)
# ``zero_baseline`` is not a gate: a declared target can still be judged
# against a zero baseline (the expected evaluation does so).
GATE_REASONS: Final[tuple[str, ...]] = (
    REASON_NO_PRIMARY_METRIC,
    REASON_INSUFFICIENT_VOLUME,
    REASON_VOLUME_UNKNOWN,
    REASON_PERIOD_UNKNOWN,
)

#: Directional metric -> the raw count its volume gate reads.
VOLUME_GATE: Final[dict[str, str]] = {
    "cpa": "conversions",
    "cpl": "conversions",
    "roas": "conversions",
    "conversions": "conversions",
    "cvr": "clicks",
    "ctr": "impressions",
    "cpm": "impressions",
    "cpc": "clicks",
}

#: Metrics that grow with the window's length, so are compared per day.
COUNT_METRICS: Final[frozenset[str]] = frozenset(
    {"conversions", "clicks", "impressions", "spend"}
)

#: Keys that say which window the figures cover. Read, never scored.
PERIOD_KEYS: Final[tuple[str, ...]] = ("period", "days")

#: Leads the part of a row note that says the row is per day. The expected
#: evaluation re-writes a primary row's note and carries this part over.
PER_DAY_MARKER: Final = "; per day over "


class Verdict(str, Enum):
    """Outcome of a single metric (``str`` mixin → trivial JSON)."""

    IMPROVED = "improved"
    REGRESSED = "regressed"
    HELD = "held"
    INCONCLUSIVE = "inconclusive"


class _Direction(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"
    NEUTRAL = "neutral"


# Known metric directions, matched case-insensitively against metric names.
_METRIC_DIRECTION: dict[str, _Direction] = {
    "cpa": _Direction.LOWER_IS_BETTER,
    "cost_per_conversion": _Direction.LOWER_IS_BETTER,
    "cpc": _Direction.LOWER_IS_BETTER,
    "cpl": _Direction.LOWER_IS_BETTER,
    "cpm": _Direction.LOWER_IS_BETTER,
    "conversions": _Direction.HIGHER_IS_BETTER,
    "conversion_rate": _Direction.HIGHER_IS_BETTER,
    "cvr": _Direction.HIGHER_IS_BETTER,
    "ctr": _Direction.HIGHER_IS_BETTER,
    "roas": _Direction.HIGHER_IS_BETTER,
    # Volume metrics: report the delta but never call it good or bad — more
    # spend or more clicks is only "good" relative to a goal, not on its own.
    "cost": _Direction.NEUTRAL,
    "spend": _Direction.NEUTRAL,
    "clicks": _Direction.NEUTRAL,
    "impressions": _Direction.NEUTRAL,
}


@dataclass(frozen=True)
class OutcomeThresholds:
    """The noise band and the per-side volume floors one evaluation uses."""

    noise_pct: float
    min_conversions: int
    min_impressions: int
    min_clicks: int

    def __post_init__(self) -> None:
        """Refuse a band outside (0, 100] and a floor that is not a count."""
        noise = self.noise_pct
        if isinstance(noise, bool) or not isinstance(noise, (int, float)):
            raise ValueError(f"noise_pct must be a number; got {noise!r}")
        if not 0 < noise <= 100:
            raise ValueError(
                f"noise_pct must be above 0 and at most 100; got {noise!r}"
            )
        object.__setattr__(self, "noise_pct", float(noise))
        for name in ("min_conversions", "min_impressions", "min_clicks"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a whole number of at least 1")


DEFAULT_THRESHOLDS: Final = OutcomeThresholds(
    noise_pct=DEFAULT_NOISE_PCT,
    min_conversions=DEFAULT_MIN_CONVERSIONS,
    min_impressions=DEFAULT_MIN_IMPRESSIONS,
    min_clicks=DEFAULT_MIN_CLICKS,
)


@dataclass(frozen=True)
class PrimaryChoice:
    """The metric the verdict is read off, and who chose it.

    effect: The declared expected effect when ``basis`` is ``expected``;
        ``None`` otherwise. Typed under ``TYPE_CHECKING`` only, so this
        module needs nothing from :mod:`mureo.analysis.expected_eval`.
    """

    metric: str
    basis: str
    effect: ExpectedEffect | None


@dataclass(frozen=True)
class MetricOutcome:
    """Verdict for one metric between the baseline and the current value."""

    metric: str
    before: float
    after: float
    delta_pct: float | None
    verdict: Verdict
    note: str


@dataclass(frozen=True)
class OutcomeReport:
    """Every comparable metric's row, and the primary metric's verdict.

    primary: The canonical name of the primary metric, or ``None`` when
        nothing chose one (``reason`` is then ``no_primary_metric``). A
        chosen primary without figures keeps its name, with that reason.
    basis: Who chose the primary (one of the ``BASIS_*`` values).
    reason: Why the result is inconclusive, from :data:`OUTCOME_REASONS`;
        ``None`` when it is not, or when no listed reason applies.
    """

    metrics: tuple[MetricOutcome, ...]
    overall: Verdict
    summary: str
    primary: str | None = None
    basis: str = BASIS_DEFAULT
    reason: str | None = None


def _direction(metric: str) -> _Direction:
    return _METRIC_DIRECTION.get(metric.strip().lower(), _Direction.NEUTRAL)


def is_directional(metric: str) -> bool:
    """Whether ``metric`` has an inherent good/bad direction (CPA, CTR, ...).

    Volume metrics (cost, clicks, ...) and unknown names do not.
    """
    return _direction(metric) is not _Direction.NEUTRAL


def _coerce_float(value: object) -> float | None:
    """Best-effort float coercion; ``bool`` is rejected (it is an ``int``)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def period_days(metrics: Mapping[str, object]) -> int | None:
    """How many days ``metrics`` cover, or ``None`` when that is not stated.

    An explicit positive whole ``days`` wins; else a ``period`` token from
    :data:`mureo.core.metrics_windows.CANONICAL_METRICS_WINDOWS`.
    """
    days = metrics.get("days")
    if isinstance(days, int) and not isinstance(days, bool) and days > 0:
        return days
    period = metrics.get("period")
    if isinstance(period, str):
        return CANONICAL_METRICS_WINDOWS.get(period.strip().upper())
    return None


def canonical_metrics(metrics: Mapping[str, object]) -> dict[str, float]:
    """The numeric figures of ``metrics`` under their canonical names.

    When several keys map to one metric, the canonical-named key wins,
    otherwise the first in sorted order. ``period`` / ``days`` and values
    that are not numbers are left out.
    """
    merged: dict[str, float] = {}
    exact: set[str] = set()
    for key in sorted(metrics, key=str):
        name = canonical_metric(str(key))
        value = _coerce_float(metrics[key])
        if name in PERIOD_KEYS or value is None or name in exact:
            continue
        if str(key).strip().lower() == name:
            exact.add(name)
        elif name in merged:
            continue
        merged[name] = value
    return merged


def evaluate_metric(
    metric: str,
    before: float,
    after: float,
    *,
    noise_pct: float = DEFAULT_NOISE_PCT,
) -> MetricOutcome:
    """Evaluate a single metric's before→after change deterministically."""
    direction = _direction(metric)

    if before <= 0:
        return MetricOutcome(
            metric=metric,
            before=before,
            after=after,
            delta_pct=None,
            verdict=Verdict.INCONCLUSIVE,
            note="baseline is zero/absent; change is not comparable",
        )

    delta_pct = round((after - before) / before * 100, 1)

    if abs(delta_pct) < noise_pct:
        return MetricOutcome(
            metric=metric,
            before=before,
            after=after,
            delta_pct=delta_pct,
            verdict=Verdict.INCONCLUSIVE,
            note=f"within ±{noise_pct:g}% noise band",
        )

    if direction is _Direction.NEUTRAL:
        return MetricOutcome(
            metric=metric,
            before=before,
            after=after,
            delta_pct=delta_pct,
            verdict=Verdict.INCONCLUSIVE,
            note="volume metric has no inherent good/bad direction",
        )

    improved = (
        (delta_pct < 0) if direction is _Direction.LOWER_IS_BETTER else (delta_pct > 0)
    )
    verdict = Verdict.IMPROVED if improved else Verdict.REGRESSED
    return MetricOutcome(
        metric=metric,
        before=before,
        after=after,
        delta_pct=delta_pct,
        verdict=verdict,
        note=f"{direction.value}; {delta_pct:+g}%",
    )


def _outcome_row(
    metric: str,
    before: float,
    after: float,
    days: tuple[int, int] | None,
    noise_pct: float,
) -> MetricOutcome:
    """One row; a count metric per day when both day counts are known."""
    if metric not in COUNT_METRICS:
        return evaluate_metric(metric, before, after, noise_pct=noise_pct)
    if days is None:
        outcome = evaluate_metric(metric, before, after, noise_pct=noise_pct)
        return replace(outcome, note=f"{outcome.note}; raw totals, periods unknown")
    outcome = evaluate_metric(
        metric, before / days[0], after / days[1], noise_pct=noise_pct
    )
    return replace(
        outcome, note=f"{outcome.note}{PER_DAY_MARKER}{days[0]}d / {days[1]}d"
    )


def _count_floor(count_key: str, thresholds: OutcomeThresholds) -> int:
    if count_key == "impressions":
        return thresholds.min_impressions
    if count_key == "clicks":
        return thresholds.min_clicks
    return thresholds.min_conversions


def _gate_reason(
    metric: str | None,
    before: Mapping[str, float],
    after: Mapping[str, float],
    days: tuple[int, int] | None,
    thresholds: OutcomeThresholds,
) -> str | None:
    """The reason the primary cannot be judged, or ``None`` when it can."""
    if metric is None or metric not in before or metric not in after:
        return REASON_NO_PRIMARY_METRIC
    count_key = VOLUME_GATE.get(metric)
    if count_key is not None:
        floor = _count_floor(count_key, thresholds)
        counts = (before.get(count_key), after.get(count_key))
        if counts[0] is None or counts[1] is None:
            return REASON_VOLUME_UNKNOWN
        if counts[0] < floor or counts[1] < floor:
            return REASON_INSUFFICIENT_VOLUME
    if metric in COUNT_METRICS and days is None:
        return REASON_PERIOD_UNKNOWN
    return None


def _default_primary(
    before: Mapping[str, float], after: Mapping[str, float]
) -> PrimaryChoice | None:
    """``cpa`` when both sides have conversions, else nothing."""
    if before.get("conversions", 0) > 0 and after.get("conversions", 0) > 0:
        return PrimaryChoice(
            metric=DEFAULT_PRIMARY_METRIC, basis=BASIS_DEFAULT, effect=None
        )
    return None


def outcome_summary(overall: str, primary: str | None, reason: str | None) -> str:
    """The one-line summary of a verdict on ``primary``."""
    if primary is None:
        return f"Inconclusive: {reason or REASON_NO_PRIMARY_METRIC}."
    if reason is not None:
        return f"Inconclusive: {reason} on {primary}."
    if overall == Verdict.HELD.value:
        return f"Held {primary} within the noise band."
    return f"{overall.capitalize()} on {primary} (primary)."


def evaluate_outcome(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
    primary: PrimaryChoice | None = None,
) -> OutcomeReport:
    """Judge the primary metric of two snapshots (gates: module docstring).

    Rows are the metrics numeric in BOTH snapshots; the primary is
    ``primary`` when given, else ``cpa`` when both sides have conversions.
    """
    figures = (canonical_metrics(before), canonical_metrics(after))
    stated = (period_days(before), period_days(after))
    days = None if stated[0] is None or stated[1] is None else (stated[0], stated[1])
    outcomes = tuple(
        _outcome_row(m, figures[0][m], figures[1][m], days, thresholds.noise_pct)
        for m in sorted(figures[0])
        if m in figures[1]
    )
    choice = primary or _default_primary(*figures)
    basis = choice.basis if choice is not None else BASIS_DEFAULT
    metric = canonical_metric(choice.metric) if choice is not None else None
    reason = _gate_reason(metric, *figures, days, thresholds)
    overall = Verdict.INCONCLUSIVE
    if reason is None:
        row = next(o for o in outcomes if o.metric == metric)
        overall = row.verdict
        if row.delta_pct is None:
            reason = REASON_ZERO_BASELINE
        elif abs(row.delta_pct) < thresholds.noise_pct:
            reason = REASON_NO_CHANGE
    if reason is not None and reason != REASON_NO_CHANGE:
        # Held back: the primary's row must not show the verdict withheld.
        outcomes = tuple(
            (
                replace(o, verdict=Verdict.INCONCLUSIVE, note=f"{reason}; {o.note}")
                if o.metric == metric
                else o
            )
            for o in outcomes
        )
    return OutcomeReport(
        metrics=outcomes,
        overall=overall,
        summary=outcome_summary(overall.value, metric, reason),
        primary=metric,
        basis=basis,
        reason=reason,
    )


__all__ = [
    "BASIS_BIDDING_TARGET",
    "BASIS_DEFAULT",
    "BASIS_EXPECTED",
    "COUNT_METRICS",
    "DEFAULT_MIN_CLICKS",
    "DEFAULT_MIN_CONVERSIONS",
    "DEFAULT_MIN_IMPRESSIONS",
    "DEFAULT_NOISE_PCT",
    "DEFAULT_PRIMARY_METRIC",
    "DEFAULT_THRESHOLDS",
    "GATE_REASONS",
    "OUTCOME_REASONS",
    "PERIOD_KEYS",
    "PER_DAY_MARKER",
    "REASON_INSUFFICIENT_VOLUME",
    "REASON_NO_CHANGE",
    "REASON_NO_PRIMARY_METRIC",
    "REASON_PERIOD_UNKNOWN",
    "REASON_TARGET_NOT_REACHED",
    "REASON_VOLUME_UNKNOWN",
    "REASON_ZERO_BASELINE",
    "VOLUME_GATE",
    "MetricOutcome",
    "OutcomeReport",
    "OutcomeThresholds",
    "PrimaryChoice",
    "Verdict",
    "canonical_metrics",
    "evaluate_metric",
    "evaluate_outcome",
    "is_directional",
    "outcome_summary",
    "period_days",
]
