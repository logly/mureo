"""Turning ``## Guardrails`` into a refusal — the one enforcement decision.

:func:`evaluate_exclusion_impact` is the single place that decides whether
an exclusion batch is refused. The dispatcher pre-flight calls it to
actually refuse, and ``analysis_exclusion_impact_preview`` calls the same
function to report ``would_block``, so the advertised verdict and the
enforced one cannot drift.

Fail-open by the same contract as every other guardrail: with none of the
five keys written, :meth:`ExclusionImpactRules.enabled` is ``False``, the
pre-flight does no platform I/O at all, and behaviour is unchanged.

Unknown coverage is NOT a refusal by default. A platform mureo cannot
attribute delivery on (Meta's publisher-category exclusions, an
un-declared plugin surface) would otherwise become unusable the moment an
operator wrote a share cap for Google. ``block_exclusions_without_impact_data``
is the opt-in for operators who would rather refuse than proceed blind —
and the batch is never *silently* allowed either way: the measured (or
unmeasurable) verdict is appended to the call's own result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mureo.analysis.exclusion_impact.models import (
    COVERAGE_MEASURED,
    METRICS,
    ExclusionImpact,
)

if TYPE_CHECKING:
    from mureo.policy.strategy_gate import Guardrails

#: Recent-window length used when the operator did not name one.
DEFAULT_WINDOW_DAYS = 30

#: Metric the share cap applies to when the operator did not name any.
#: Impressions, not cost: an exclusion removes *inventory*, and impressions
#: are the first thing to collapse when too much of it is removed.
DEFAULT_METRICS: tuple[str, ...] = ("impressions",)

#: Upper bound on ``exclusion_impact_window_days``. Beyond this the report
#: request stops being a "recent window" and starts being a slow scan.
MAX_WINDOW_DAYS = 365


@dataclass(frozen=True)
class ExclusionImpactRules:
    """The operator's exclusion-impact rules, resolved with defaults."""

    max_share_pct: float | None = None
    max_cumulative_share_pct: float | None = None
    window_days: int = DEFAULT_WINDOW_DAYS
    metrics: tuple[str, ...] = DEFAULT_METRICS
    block_without_data: bool = False

    def enabled(self) -> bool:
        """True when the operator wrote at least one exclusion-impact rule.

        False ⇒ the pre-flight makes no platform call and never refuses.
        """
        return (
            self.max_share_pct is not None
            or self.max_cumulative_share_pct is not None
            or self.block_without_data
        )


def _clamp_window(days: int | None) -> int:
    if days is None:
        return DEFAULT_WINDOW_DAYS
    return max(1, min(int(days), MAX_WINDOW_DAYS))


def exclusion_impact_rules(guardrails: Guardrails) -> ExclusionImpactRules:
    """Resolve the ``## Guardrails`` exclusion keys against the defaults."""
    metrics = tuple(m for m in guardrails.exclusion_impact_metrics if m in METRICS)
    return ExclusionImpactRules(
        max_share_pct=guardrails.max_delivery_share_removed_pct,
        max_cumulative_share_pct=(guardrails.max_cumulative_delivery_share_removed_pct),
        window_days=_clamp_window(guardrails.exclusion_impact_window_days),
        metrics=metrics or DEFAULT_METRICS,
        block_without_data=guardrails.block_exclusions_without_impact_data,
    )


def _over_cap(
    impact: ExclusionImpact,
    cap: float | None,
    metrics: tuple[str, ...],
    *,
    cumulative: bool,
) -> str | None:
    if cap is None:
        return None
    key = (
        "max_cumulative_delivery_share_removed_pct"
        if cumulative
        else "max_delivery_share_removed_pct"
    )
    what = "already-excluded inventory plus this batch" if cumulative else "this batch"
    for metric in metrics:
        share = (
            impact.cumulative_share_pct(metric)
            if cumulative
            else impact.share_pct(metric)
        )
        if share is None or share <= cap:
            continue
        return (
            f"Refusing this exclusion batch: {what} accounted for "
            f"{share:.1f}% of the last {impact.window_days} days of "
            f"{metric} ({impact.basis}), over the STRATEGY.md Guardrails "
            f"limit of {cap:g}% ({key}). Narrow the batch, raise the "
            f"limit, or apply it in smaller passes and observe delivery "
            f"between them."
        )
    return None


@dataclass(frozen=True)
class UnevaluatedRule:
    """A rule the operator WROTE that could not be evaluated for this call."""

    key: str
    reason: str

    def as_text(self) -> str:
        return f"{self.key} could not be evaluated here — {self.reason}"


def unevaluated_rules(
    impact: ExclusionImpact, rules: ExclusionImpactRules
) -> tuple[UnevaluatedRule, ...]:
    """Rules that are silently inert for this particular call.

    A rule that cannot fire has to say so **at the moment it cannot fire**,
    not only in a document. The case that matters:
    ``max_cumulative_delivery_share_removed_pct`` is the rule that catches
    incremental tightening, and it is exactly the rule an operator writes
    after reading an incident report — but mureo cannot list the standing
    exclusion set for an ad-group-scoped write, so on those calls the rule
    enforces nothing at all. An operator who wrote ONLY that rule would
    have no enforcement on the very scope the incident happened at. Saying
    so lets them add ``max_delivery_share_removed_pct`` as the backstop.
    """
    inert: list[UnevaluatedRule] = []
    if rules.max_share_pct is not None and impact.incremental is None:
        inert.append(
            UnevaluatedRule(
                key="max_delivery_share_removed_pct",
                reason=(
                    impact.coverage_reason
                    or f"delivery coverage for this call is '{impact.coverage}'"
                ),
            )
        )
    if rules.max_cumulative_share_pct is not None and impact.cumulative is None:
        inert.append(
            UnevaluatedRule(
                key="max_cumulative_delivery_share_removed_pct",
                reason=(
                    impact.cumulative_reason
                    or "the standing exclusion set could not be read for this scope"
                ),
            )
        )
    return tuple(inert)


def evaluate_exclusion_impact(
    impact: ExclusionImpact, rules: ExclusionImpactRules
) -> str | None:
    """Return the refusal reason for ``impact``, or ``None`` to allow.

    Order matters only for which reason surfaces first; any one of them is
    a refusal.
    """
    if not rules.enabled():
        return None
    if rules.block_without_data and impact.coverage != COVERAGE_MEASURED:
        detail = impact.coverage_reason or "no attributable delivery data"
        return (
            f"Refusing this exclusion batch: mureo could not measure how much "
            f"of the last {impact.window_days} days of delivery it removes "
            f"(coverage: {impact.coverage} — {detail}). STRATEGY.md Guardrails "
            f"has block_exclusions_without_impact_data set, which refuses an "
            f"exclusion mureo cannot size rather than applying it blind."
        )
    return _over_cap(
        impact, rules.max_share_pct, rules.metrics, cumulative=False
    ) or _over_cap(
        impact, rules.max_cumulative_share_pct, rules.metrics, cumulative=True
    )


__all__ = [
    "DEFAULT_METRICS",
    "DEFAULT_WINDOW_DAYS",
    "MAX_WINDOW_DAYS",
    "ExclusionImpactRules",
    "UnevaluatedRule",
    "evaluate_exclusion_impact",
    "exclusion_impact_rules",
    "unevaluated_rules",
]
