"""The stored evaluation table of an observed change (#848, rules 2 since #888).

:func:`mureo.analysis.outcome_eval.evaluate_outcome` judges ONE primary
metric by its inherent direction: CPA down is good, conversions up is good,
spend has no direction at all. That is the right default, and the wrong
verdict for a change made to MOVE spend. :func:`choose_primary` is the one
place the primary is picked, in this order:

1. the declared expected effect marked ``primary`` (a single effect is
   primary by itself; a legacy declaration of several with none marked
   uses the first) — judged against the declared direction and target.
   It stays the primary even without figures: the result is then
   ``inconclusive`` with ``no_primary_metric``, never a verdict on a
   metric the decision did not name;
2. only when nothing is declared, the campaign's bidding target:
   ``target_roas`` → ``roas``, ``target_cpa`` → ``cpa``;
3. nothing, and the evaluator's own default (``cpa`` when both sides have
   conversions) applies.

The table is what an ``outcome_evaluated`` entry stores, so a verdict read
months later can be checked against the figures that produced it::

    {"rules": 2, "overall": "improved", "basis": "expected",
     "primary": "spend", "noise_pct": 10.0,
     "window": {"from": "2026-09-01", "to": "2026-09-18"},
     "metrics": [{"metric": "spend", "before": 1000.0, "after": 1500.0,
                  "delta_pct": 50.0, "verdict": "improved",
                  "note": "expected up; +50% (noise band ±10%)",
                  "role": "primary"}, ...]}

``basis`` says who chose the primary (``expected`` / ``bidding_target`` /
``default``), ``reason`` (only when set) why the result is inconclusive.
A ``target`` on a count metric is the total over the evaluation window: it
is compared with the raw ``after`` figure, not the per-day row.
Declared metrics with no figures on both sides are listed in
``expected_missing``. A table without ``rules`` was written under the old
"any regression wins" aggregation; readers accept both.

Pure, I/O-free, platform-agnostic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from mureo.analysis.outcome_eval import (
    BASIS_BIDDING_TARGET,
    BASIS_DEFAULT,
    BASIS_EXPECTED,
    DEFAULT_THRESHOLDS,
    GATE_REASONS,
    OUTCOME_REASONS,
    PER_DAY_MARKER,
    REASON_NO_CHANGE,
    REASON_TARGET_NOT_REACHED,
    REASON_ZERO_BASELINE,
    PrimaryChoice,
    Verdict,
    canonical_metrics,
    evaluate_outcome,
    outcome_summary,
)
from mureo.context.expected import (
    DIRECTION_DOWN,
    DIRECTION_HOLD,
    DIRECTION_UP,
    canonical_metric,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mureo.analysis.outcome_eval import (
        MetricOutcome,
        OutcomeReport,
        OutcomeThresholds,
    )
    from mureo.context.expected import ExpectedEffect

#: Version of the verdict rules a table was built under. A table without
#: the key predates #888.
RULES_VERSION: Final = 2

#: ``role`` values of a metric row.
ROLE_PRIMARY: Final = "primary"
ROLE_REFERENCE: Final = "reference"

#: The keys :func:`evaluation_from_report` writes: the ones every table
#: carries, then the ones written only when they apply. A row carries
#: exactly the keys of :func:`_row`.
_TABLE_REQUIRED_KEYS: Final[tuple[str, ...]] = (
    "rules",
    "overall",
    "basis",
    "primary",
    "noise_pct",
    "window",
    "metrics",
)
_TABLE_OPTIONAL_KEYS: Final[tuple[str, ...]] = ("reason", "expected_missing")
_ROW_KEYS: Final[frozenset[str]] = frozenset(
    {"metric", "before", "after", "delta_pct", "verdict", "note", "role"}
)
_BASES: Final[tuple[str, ...]] = (BASIS_EXPECTED, BASIS_BIDDING_TARGET, BASIS_DEFAULT)

#: A declared primary row's note, as ``str.format`` templates, read back by
#: :mod:`mureo.analysis.outcome_note` from the same strings. A primary with
#: no percentage change (a zero baseline) carries the evaluator's own note
#: after the direction instead of the change and the band.
NOTE_EXPECTED: Final = (
    "expected {direction}; {delta_pct:+g}% (noise band ±{noise_pct:g}%)"
)
NOTE_EXPECTED_UNSCORED: Final = "expected {direction}; {note}"
NOTE_TARGET: Final = "; target {target:g} {state}"
NOTE_TARGET_REACHED: Final = "reached"
NOTE_TARGET_NOT_REACHED: Final = "not reached"
#: Follows the target on a per-day row: the raw figure it was compared with.
NOTE_WINDOW_TOTAL: Final = " (window total {total:g})"

#: ``bidding_details`` key -> the metric that target is set on, in order.
_BIDDING_TARGETS: Final[tuple[tuple[str, str], ...]] = (
    ("target_roas", "roas"),
    ("target_cpa", "cpa"),
)


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


def _declared_primary(expected: Sequence[ExpectedEffect]) -> ExpectedEffect | None:
    """The effect marked primary, else the first one declared."""
    marked = next((effect for effect in expected if effect.primary), None)
    if marked is not None:
        return marked
    return expected[0] if expected else None


def _positive_target(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


def choose_primary(
    expected: Sequence[ExpectedEffect],
    bidding_details: Mapping[str, Any] | None,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> PrimaryChoice | None:
    """Pick the primary metric: expected, then bidding target, then none.

    A declared primary is returned whether or not it has figures (the
    evaluator then says ``no_primary_metric``). A bidding target counts
    only when nothing is declared and its metric has figures on both
    sides. ``None`` leaves the choice to the evaluator's default.
    """
    effect = _declared_primary(expected)
    if effect is not None:
        return PrimaryChoice(
            metric=canonical_metric(effect.metric), basis=BASIS_EXPECTED, effect=effect
        )
    present = set(canonical_metrics(before)) & set(canonical_metrics(after))
    for key, metric in _BIDDING_TARGETS:
        target = (bidding_details or {}).get(key)
        if _positive_target(target) and metric in present:
            return PrimaryChoice(metric=metric, basis=BASIS_BIDDING_TARGET, effect=None)
    return None


def _target_reached(total: float, effect: ExpectedEffect, noise_pct: float) -> bool:
    target = float(effect.target or 0)
    if effect.direction == DIRECTION_UP:
        return total >= target
    if effect.direction == DIRECTION_DOWN:
        return total <= target
    return abs(total - target) <= abs(target) * noise_pct / 100


def _expected_verdict(
    outcome: MetricOutcome, effect: ExpectedEffect, noise_pct: float, total: float
) -> tuple[Verdict, str | None]:
    """Judge one metric against the declared direction and target.

    ``total`` is the raw ``after`` figure the target is compared with: the
    window total for a count metric, the row's ``after`` for a ratio.
    A reached target is ``improved`` even inside the band; a hold with a
    target is judged around the target. A move the right way that misses
    the target is ``target_not_reached``; the wrong way beyond the band is
    ``regressed``; inside the band is ``no_change`` (``held`` for a hold).
    """
    has_target = effect.target is not None
    if has_target and effect.direction == DIRECTION_HOLD:
        near = _target_reached(total, effect, noise_pct)
        return (Verdict.HELD if near else Verdict.REGRESSED), None
    if has_target and _target_reached(total, effect, noise_pct):
        return Verdict.IMPROVED, None
    if outcome.delta_pct is None:
        return Verdict.INCONCLUSIVE, REASON_ZERO_BASELINE
    if abs(outcome.delta_pct) < noise_pct:
        if effect.direction == DIRECTION_HOLD:
            return Verdict.HELD, None
        return Verdict.INCONCLUSIVE, REASON_NO_CHANGE
    if effect.direction == DIRECTION_HOLD:
        return Verdict.REGRESSED, None
    if (outcome.delta_pct > 0) != (effect.direction == DIRECTION_UP):
        return Verdict.REGRESSED, None
    if has_target:
        return Verdict.INCONCLUSIVE, REASON_TARGET_NOT_REACHED
    return Verdict.IMPROVED, None


def _expected_note(
    outcome: MetricOutcome, effect: ExpectedEffect, noise_pct: float, total: float
) -> str:
    per_day = outcome.note.find(PER_DAY_MARKER)
    if outcome.delta_pct is None:
        note = NOTE_EXPECTED_UNSCORED.format(
            direction=effect.direction, note=outcome.note
        )
    else:
        note = NOTE_EXPECTED.format(
            direction=effect.direction,
            delta_pct=outcome.delta_pct,
            noise_pct=noise_pct,
        ) + (outcome.note[per_day:] if per_day >= 0 else "")
    if effect.target is not None:
        reached = _target_reached(total, effect, noise_pct)
        state = NOTE_TARGET_REACHED if reached else NOTE_TARGET_NOT_REACHED
        note += NOTE_TARGET.format(target=effect.target, state=state)
        if per_day >= 0:
            note += NOTE_WINDOW_TOTAL.format(total=total)
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


def _rows(
    report: OutcomeReport,
    effect: ExpectedEffect | None,
    noise_pct: float,
    totals: Mapping[str, float],
    reason: str | None,
) -> list[dict[str, Any]]:
    """The primary row (re-judged when declared) and every reference row.

    A primary held back by a gate or a zero baseline (``reason``) keeps the
    report's row: ``inconclusive``, its note leading with the reason code.
    """
    held_back = reason in GATE_REASONS or reason == REASON_ZERO_BASELINE
    rows: list[dict[str, Any]] = []
    for outcome in report.metrics:
        if outcome.metric != report.primary:
            rows.append(_row(outcome, outcome.verdict, outcome.note, ROLE_REFERENCE))
        elif effect is None or held_back:
            rows.append(_row(outcome, outcome.verdict, outcome.note, ROLE_PRIMARY))
        else:
            total = totals.get(outcome.metric, outcome.after)
            verdict, _ = _expected_verdict(outcome, effect, noise_pct, total)
            note = _expected_note(outcome, effect, noise_pct, total)
            rows.append(_row(outcome, verdict, note, ROLE_PRIMARY))
    return rows


def _effect_of(
    report: OutcomeReport, expected: Sequence[ExpectedEffect]
) -> ExpectedEffect | None:
    """The declared effect the report's primary was chosen from, if any."""
    if report.basis != BASIS_EXPECTED or report.primary is None:
        return None
    return next(
        (e for e in expected if canonical_metric(e.metric) == report.primary), None
    )


def _verdict_of(
    report: OutcomeReport,
    effect: ExpectedEffect | None,
    noise_pct: float,
    totals: Mapping[str, float],
) -> tuple[str, str | None, str]:
    """``(overall, reason, summary)``: a gate result stands as it is."""
    if effect is None or report.reason in GATE_REASONS:
        return report.overall.value, report.reason, report.summary
    outcome = next(o for o in report.metrics if o.metric == report.primary)
    total = totals.get(outcome.metric, outcome.after)
    verdict, reason = _expected_verdict(outcome, effect, noise_pct, total)
    summary = outcome_summary(verdict.value, report.primary, reason)
    return verdict.value, reason, summary


def build_evaluation(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    expected: Sequence[ExpectedEffect],
    *,
    window_from: str | None,
    window_to: str | None,
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
    bidding_details: Mapping[str, Any] | None = None,
) -> EvaluationResult:
    """Score ``before`` against ``after`` and build the stored table.

    Args:
        before / after: Metric snapshots, bookkeeping keys already removed
            (``period`` / ``days`` stay: they decide the per-day split).
        expected: The decision's declared effects; empty for none.
        window_from / window_to: ISO dates of the observed period.
        thresholds: The noise band and the volume floors.
        bidding_details: The campaign's bidding settings, for the
            bidding-target rule of :func:`choose_primary`.
    """
    choice = choose_primary(expected, bidding_details, before, after)
    report = evaluate_outcome(before, after, thresholds=thresholds, primary=choice)
    return evaluation_from_report(
        report,
        expected,
        after=after,
        window_from=window_from,
        window_to=window_to,
        thresholds=thresholds,
    )


def evaluation_from_report(
    report: OutcomeReport,
    expected: Sequence[ExpectedEffect],
    *,
    after: Mapping[str, Any],
    window_from: str | None,
    window_to: str | None,
    thresholds: OutcomeThresholds = DEFAULT_THRESHOLDS,
) -> EvaluationResult:
    """Build the table from an evaluator report already in hand.

    ``after`` and ``thresholds`` must be the snapshot and the thresholds
    the report was scored with: a declared target is compared with the
    raw ``after`` figure (the window total for a count metric).
    """
    noise_pct = thresholds.noise_pct
    totals = canonical_metrics(after)
    effect = _effect_of(report, expected)
    overall, reason, summary = _verdict_of(report, effect, noise_pct, totals)
    present = {o.metric for o in report.metrics}
    missing = [e.metric for e in expected if canonical_metric(e.metric) not in present]
    table: dict[str, Any] = {
        "rules": RULES_VERSION,
        "overall": overall,
        "basis": report.basis,
        "primary": report.primary,
    }
    if reason is not None:
        table["reason"] = reason
    table["noise_pct"] = float(noise_pct)
    table["window"] = {"from": window_from, "to": window_to}
    table["metrics"] = _rows(report, effect, noise_pct, totals, reason)
    if missing:
        table["expected_missing"] = missing
    return EvaluationResult(
        overall=overall, summary=summary, table=table, scored=len(report.metrics)
    )


def _check_table_keys(raw: Mapping[str, Any]) -> None:
    unknown = sorted(set(raw) - {*_TABLE_REQUIRED_KEYS, *_TABLE_OPTIONAL_KEYS})
    if unknown:
        raise ValueError(f"evaluation has unknown keys: {', '.join(unknown)}")
    missing = [key for key in _TABLE_REQUIRED_KEYS if key not in raw]
    if missing:
        raise ValueError(f"evaluation is missing keys: {', '.join(missing)}")


def _check_noise_pct(value: object) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 < value <= 100
    ):
        raise ValueError(
            f"evaluation.noise_pct must be a number above 0 and at most 100; "
            f"got {value!r}"
        )


def _check_rows(rows: object) -> None:
    if not isinstance(rows, list):
        raise ValueError("evaluation.metrics must be a list of metric rows")
    if not rows:
        # The automatic closure's skip word (auto_evaluation's
        # SKIP_NO_COMPARABLE_METRIC), spelled out: that module imports this
        # one, so importing it back would be a cycle.
        raise ValueError(
            "no_comparable_metric: evaluation.metrics is empty; the automatic "
            "closure never stores a table without rows"
        )
    keys = ", ".join(sorted(_ROW_KEYS))
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise ValueError(
                f"evaluation.metrics[{position}] must be an object with "
                f"exactly the keys {keys}"
            )


def validate_evaluation_table(raw: object) -> Mapping[str, Any]:
    """Check that ``raw`` has the shape :func:`evaluation_from_report` writes.

    For a table handed back by a caller (the manual evaluation record,
    #889). The values are not re-derived — only the shape is checked, so a
    record carries a table every reader of the automatic one can read.
    Reading a STORED table never calls this: a malformed one on disk reads
    as no verdict, it does not block a load.

    Raises:
        ValueError: naming the first offending part, as
            :func:`mureo.context.expected.parse_expected` does.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            "evaluation must be an object: the table mureo_outcome_evaluate returns"
        )
    _check_table_keys(raw)
    rules = raw["rules"]
    if isinstance(rules, bool) or rules != RULES_VERSION:
        raise ValueError(f"evaluation.rules must be {RULES_VERSION}; got {rules!r}")
    # Tuples, not sets: ``in`` on a set raises TypeError for a list or a dict.
    if raw["overall"] not in tuple(verdict.value for verdict in Verdict):
        raise ValueError(f"evaluation.overall is not a verdict: {raw['overall']!r}")
    if raw["basis"] not in _BASES:
        raise ValueError(f"evaluation.basis is not a basis: {raw['basis']!r}")
    if raw["primary"] is not None and not isinstance(raw["primary"], str):
        raise ValueError("evaluation.primary must be a metric name or null")
    if "reason" in raw and raw["reason"] not in OUTCOME_REASONS:
        raise ValueError(f"evaluation.reason is not a reason: {raw['reason']!r}")
    _check_noise_pct(raw["noise_pct"])
    _check_rows(raw["metrics"])
    return raw


__all__ = [
    "BASIS_BIDDING_TARGET",
    "BASIS_DEFAULT",
    "BASIS_EXPECTED",
    "NOTE_EXPECTED",
    "NOTE_EXPECTED_UNSCORED",
    "NOTE_TARGET",
    "NOTE_TARGET_NOT_REACHED",
    "NOTE_TARGET_REACHED",
    "NOTE_WINDOW_TOTAL",
    "ROLE_PRIMARY",
    "ROLE_REFERENCE",
    "RULES_VERSION",
    "EvaluationResult",
    "build_evaluation",
    "choose_primary",
    "evaluation_from_report",
    "validate_evaluation_table",
]
