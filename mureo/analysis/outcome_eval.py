"""Deterministic outcome evaluation for logged actions.

Pure, I/O-free. Given the ``metrics_at_action`` baseline recorded on an
``action_log`` entry and the current metrics for the same campaign, decide
whether each key metric **improved**, **regressed**, or is **inconclusive**
(the change is within day-to-day noise). This turns the observation-window
review daily-check performs from an LLM judgement call into a reproducible
verdict, and gives ``/learn`` a trustworthy signal.

Platform-agnostic: it only compares numbers, so it works for any platform
(google_ads / meta_ads / tiktok_ads / plugins) as long as the caller feeds
comparable before/after metric names.

Design notes:
- A change smaller than ``noise_pct`` (default ±10%) is INCONCLUSIVE — the
  same sample-size / noise discipline the anomaly detector and the
  ``_mureo-learning`` skill use, so a single-day wobble is never a win or loss.
- Metric direction is explicit: CPA is lower-is-better, conversions/CTR are
  higher-is-better. Volume metrics with no inherent good/bad direction (cost,
  clicks, impressions) are reported with their delta but no verdict.
- A missing or zero baseline is INCONCLUSIVE (no ratio is computable) rather
  than a fabricated 100% swing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# A swing smaller than this (percent) is treated as day-to-day variance, not a
# real outcome. Matches the anomaly detector's "a single bad day is noise".
DEFAULT_NOISE_PCT = 10.0


class Verdict(str, Enum):
    """Outcome of a single metric (``str`` mixin → trivial JSON)."""

    IMPROVED = "improved"
    REGRESSED = "regressed"
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
    """Aggregate outcome across every comparable metric."""

    metrics: tuple[MetricOutcome, ...]
    overall: Verdict
    summary: str


def _direction(metric: str) -> _Direction:
    return _METRIC_DIRECTION.get(metric.strip().lower(), _Direction.NEUTRAL)


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


def evaluate_outcome(
    before: dict[str, object],
    after: dict[str, object],
    *,
    noise_pct: float = DEFAULT_NOISE_PCT,
) -> OutcomeReport:
    """Compare two metric snapshots and return per-metric + overall verdicts.

    Only metrics present (and numeric) in BOTH snapshots are compared. The
    overall verdict weighs only directional metrics (CPA / conversions / …):
    any regression → REGRESSED; else any improvement → IMPROVED; else
    INCONCLUSIVE. Neutral/volume metrics never decide the overall verdict.
    """
    outcomes: list[MetricOutcome] = []
    for metric in sorted(before):
        b = _coerce_float(before.get(metric))
        a = _coerce_float(after.get(metric))
        if b is None or a is None:
            continue
        outcomes.append(evaluate_metric(metric, b, a, noise_pct=noise_pct))

    directional = [
        o for o in outcomes if _direction(o.metric) is not _Direction.NEUTRAL
    ]
    if any(o.verdict is Verdict.REGRESSED for o in directional):
        overall = Verdict.REGRESSED
    elif any(o.verdict is Verdict.IMPROVED for o in directional):
        overall = Verdict.IMPROVED
    else:
        overall = Verdict.INCONCLUSIVE

    improved = [o.metric for o in directional if o.verdict is Verdict.IMPROVED]
    regressed = [o.metric for o in directional if o.verdict is Verdict.REGRESSED]
    if overall is Verdict.REGRESSED:
        summary = f"Regressed on {', '.join(regressed)}."
    elif overall is Verdict.IMPROVED:
        summary = f"Improved on {', '.join(improved)}."
    else:
        summary = "No change beyond the noise band on any directional metric."

    return OutcomeReport(metrics=tuple(outcomes), overall=overall, summary=summary)
