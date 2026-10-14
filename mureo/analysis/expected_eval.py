"""The stored evaluation table of an observed change (#848).

:func:`mureo.analysis.outcome_eval.evaluate_outcome` judges every metric by
its inherent direction: CPA down is good, conversions up is good, spend has
no direction at all. That is the right default, and the wrong verdict for a
change made to MOVE spend. When the decision behind a change declared what
it expected (:mod:`mureo.context.expected`), the declared metrics are judged
against the declared direction and decide the verdict; every other metric
is kept in the table as reference.

The table is what an ``outcome_evaluated`` entry stores, so a verdict read
months later can be checked against the figures that produced it::

    {"overall": "improved", "basis": "expected", "noise_pct": 10.0,
     "window": {"from": "2026-09-01", "to": "2026-09-18"},
     "metrics": [{"metric": "cost", "before": 1000.0, "after": 1500.0,
                  "delta_pct": 50.0, "verdict": "improved",
                  "note": "expected up; +50%", "role": "primary"}, ...]}

``basis`` is ``"expected"`` when the declared metrics decided the verdict,
``"default"`` when the evaluator's own rule did (nothing declared, or none
of the declared metrics had figures on both sides — those are then listed
in ``expected_missing``). The schema also reserves ``control`` (a
comparison group) and ``skipped_reason``; neither is written here.

Pure, I/O-free, platform-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from mureo.analysis.outcome_eval import (
    DEFAULT_NOISE_PCT,
    MetricOutcome,
    Verdict,
    evaluate_outcome,
    is_directional,
)
from mureo.context.expected import (
    DIRECTION_DOWN,
    DIRECTION_HOLD,
    DIRECTION_UP,
    canonical_metric,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mureo.analysis.outcome_eval import OutcomeReport
    from mureo.context.expected import ExpectedEffect

#: ``basis`` values: who decided the overall verdict.
BASIS_EXPECTED: Final = "expected"
BASIS_DEFAULT: Final = "default"

#: ``role`` values of a metric row.
ROLE_PRIMARY: Final = "primary"
ROLE_REFERENCE: Final = "reference"


@dataclass(frozen=True)
class EvaluationResult:
    """The verdict, its one-line summary, and the table that backs it.

    scored: How many metrics had figures on both sides. Zero means there
        was nothing to judge — the caller's cue to skip rather than store a
        verdict on nothing.
    """

    overall: str
    summary: str
    table: dict[str, Any]
    scored: int


def _hold_verdict(delta_pct: float, noise_pct: float) -> Verdict:
    return Verdict.IMPROVED if abs(delta_pct) < noise_pct else Verdict.REGRESSED


def _directed_verdict(delta_pct: float, noise_pct: float, sign: int) -> Verdict:
    signed = delta_pct * sign
    if signed >= noise_pct:
        return Verdict.IMPROVED
    if signed <= -noise_pct:
        return Verdict.REGRESSED
    return Verdict.INCONCLUSIVE


def _expected_verdict(
    outcome: MetricOutcome, effect: ExpectedEffect, noise_pct: float
) -> Verdict:
    """Judge one metric against the direction the decision declared."""
    if outcome.delta_pct is None:
        return Verdict.INCONCLUSIVE
    if effect.direction == DIRECTION_HOLD:
        return _hold_verdict(outcome.delta_pct, noise_pct)
    sign = 1 if effect.direction == DIRECTION_UP else -1
    return _directed_verdict(outcome.delta_pct, noise_pct, sign)


def _target_reached(after: float, effect: ExpectedEffect, noise_pct: float) -> bool:
    target = float(effect.target or 0)
    if effect.direction == DIRECTION_UP:
        return after >= target
    if effect.direction == DIRECTION_DOWN:
        return after <= target
    return abs(after - target) <= abs(target) * noise_pct / 100


def _expected_note(
    outcome: MetricOutcome, effect: ExpectedEffect, noise_pct: float
) -> str:
    if outcome.delta_pct is None:
        note = f"expected {effect.direction}; {outcome.note}"
    else:
        note = (
            f"expected {effect.direction}; {outcome.delta_pct:+g}% "
            f"(noise band ±{noise_pct:g}%)"
        )
    if effect.target is not None:
        reached = _target_reached(outcome.after, effect, noise_pct)
        state = "reached" if reached else "not reached"
        note += f"; target {effect.target:g} {state}"
    return note


def _row(
    outcome: MetricOutcome, verdict: Verdict, note: str, role: str
) -> dict[str, Any]:
    return {
        "metric": outcome.metric,
        "before": outcome.before,
        "after": outcome.after,
        "delta_pct": outcome.delta_pct,
        "verdict": verdict.value,
        "note": note,
        "role": role,
    }


def _default_rows(outcomes: Sequence[MetricOutcome]) -> list[dict[str, Any]]:
    """Directional metrics primary, volume metrics reference."""
    return [
        _row(
            o,
            o.verdict,
            o.note,
            ROLE_PRIMARY if is_directional(o.metric) else ROLE_REFERENCE,
        )
        for o in outcomes
    ]


def _expected_rows(
    outcomes: Sequence[MetricOutcome],
    by_metric: dict[str, ExpectedEffect],
    noise_pct: float,
) -> list[dict[str, Any]]:
    """Declared metrics primary and re-judged; the rest reference."""
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        effect = by_metric.get(canonical_metric(outcome.metric))
        if effect is None:
            rows.append(_row(outcome, outcome.verdict, outcome.note, ROLE_REFERENCE))
            continue
        verdict = _expected_verdict(outcome, effect, noise_pct)
        note = _expected_note(outcome, effect, noise_pct)
        rows.append(_row(outcome, verdict, note, ROLE_PRIMARY))
    return rows


def _overall_of(verdicts: Sequence[str]) -> str:
    """Same aggregation rule as the evaluator: any regression wins."""
    if Verdict.REGRESSED.value in verdicts:
        return Verdict.REGRESSED.value
    if Verdict.IMPROVED.value in verdicts:
        return Verdict.IMPROVED.value
    return Verdict.INCONCLUSIVE.value


def _expected_summary(overall: str, primary: Sequence[dict[str, Any]]) -> str:
    names = ", ".join(r["metric"] for r in primary if r["verdict"] == overall)
    if overall == Verdict.REGRESSED.value:
        return f"Moved against the expected effect on {names}."
    if overall == Verdict.IMPROVED.value:
        return f"Met the expected effect on {names}."
    return "No change beyond the noise band on the expected metrics."


def build_evaluation(
    before: dict[str, Any],
    after: dict[str, Any],
    expected: Sequence[ExpectedEffect],
    *,
    window_from: str | None,
    window_to: str | None,
    noise_pct: float = DEFAULT_NOISE_PCT,
) -> EvaluationResult:
    """Score ``before`` against ``after`` and build the stored table.

    Args:
        before / after: Metric snapshots, bookkeeping keys already removed.
        expected: The decision's declared effects; empty for none.
        window_from / window_to: ISO dates of the observed period.
        noise_pct: The band within which a move is noise.
    """
    report = evaluate_outcome(before, after, noise_pct=noise_pct)
    return evaluation_from_report(
        report,
        expected,
        window_from=window_from,
        window_to=window_to,
        noise_pct=noise_pct,
    )


def evaluation_from_report(
    report: OutcomeReport,
    expected: Sequence[ExpectedEffect],
    *,
    window_from: str | None,
    window_to: str | None,
    noise_pct: float = DEFAULT_NOISE_PCT,
) -> EvaluationResult:
    """Build the table from an evaluator report already in hand.

    ``noise_pct`` must be the band the report was scored with.
    """
    by_metric = {canonical_metric(e.metric): e for e in expected}
    present = {canonical_metric(o.metric) for o in report.metrics}
    missing = [e.metric for e in expected if canonical_metric(e.metric) not in present]
    table: dict[str, Any] = {
        "noise_pct": float(noise_pct),
        "window": {"from": window_from, "to": window_to},
    }
    if by_metric and len(missing) < len(by_metric):
        rows = _expected_rows(report.metrics, by_metric, noise_pct)
        primary = [r for r in rows if r["role"] == ROLE_PRIMARY]
        overall = _overall_of([r["verdict"] for r in primary])
        summary = _expected_summary(overall, primary)
        table["basis"] = BASIS_EXPECTED
    else:
        rows = _default_rows(report.metrics)
        overall = report.overall.value
        summary = report.summary
        table["basis"] = BASIS_DEFAULT
    table["overall"] = overall
    table["metrics"] = rows
    if missing:
        table["expected_missing"] = missing
    return EvaluationResult(
        overall=overall, summary=summary, table=table, scored=len(report.metrics)
    )


__all__ = [
    "BASIS_DEFAULT",
    "BASIS_EXPECTED",
    "ROLE_PRIMARY",
    "ROLE_REFERENCE",
    "EvaluationResult",
    "build_evaluation",
    "evaluation_from_report",
]
