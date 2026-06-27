"""Budget efficiency scoring for the built-in analytics adapters.

Pure scorer: takes per-campaign performance rows in either Google's
``{metrics: {...}}`` shape or the flat BYOD / Meta shape, normalises
the conversion-per-cost ratio across campaigns, and returns the
:class:`BudgetEfficiency` payload the workflow skills consume.

Scoring model (deliberately simple — see the budget-rebalance skill
for the deeper analysis):

- For each campaign with spend > 0, compute ``conversions / cost``.
- Normalise to [0.0, 1.0] by dividing by the best campaign's rate
  (so the top performer scores 1.0, others scale relative to it).
- Flag campaigns with score < 0.3 as inefficient if there is at least
  one campaign with score >= 0.7 — that's the "reallocation
  opportunity" signal.

Pure: no I/O, no platform-specific calls. The adapter feeds it the
data and renders the response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analytics.models import BudgetEfficiency
from mureo.context.state import load_conversion_action_types

if TYPE_CHECKING:
    from collections.abc import Collection

INEFFICIENT_THRESHOLD = 0.3
EFFICIENT_THRESHOLD = 0.7


def _extract_cost_and_conversions(
    row: dict[str, Any],
    *,
    spend_key: str,
    nested_metrics: bool,
    conversion_action_types: Collection[str] | None = None,
) -> tuple[str, float, float] | None:
    """Return ``(campaign_id, cost, conversions)`` for one row, or
    ``None`` when the row is unusable (missing id / non-positive cost).

    The two shape selectors mirror the live-clients module's
    BYOD-tolerance helpers — kept here as small inline branches rather
    than importing the helpers to avoid a circular dep on adapters.
    """
    campaign_id = str(row.get("campaign_id") or "").strip()
    if not campaign_id:
        return None

    if nested_metrics:
        metrics = row.get("metrics")
        if isinstance(metrics, dict) and metrics:
            cost = float(metrics.get("cost") or 0)
            conversions = float(metrics.get("conversions") or 0)
        else:
            # Live mapper produced no nested metrics — fall through to
            # flat lookup. Matches the BYOD path.
            cost = float(row.get("cost") or 0)
            conversions = float(row.get("conversions") or 0)
    else:
        cost = float(row.get(spend_key) or 0)
        conversions = float(row.get("conversions") or 0)
        # Meta Live shape: conversions live inside ``actions``. Count via the
        # canonical exact-match counter (#340) — the old substring scan here
        # double-counted aggregate+component aliases and swept in custom
        # slugs, skewing the budget-efficiency CPA. Lazy import keeps adapter
        # registration free of the mureo.meta_ads client weight.
        if conversions == 0:
            from mureo.meta_ads._conversion_count import (
                count_conversions_from_actions,
            )

            conversions = count_conversions_from_actions(
                row.get("actions"), conversion_action_types=conversion_action_types
            )

    if cost <= 0:
        return None
    return campaign_id, cost, conversions


def score_budget_efficiency(
    rows: list[dict[str, Any]],
    *,
    platform: str,
    account_id: str,
    spend_key: str = "cost",
    nested_metrics: bool = True,
) -> BudgetEfficiency:
    """Score per-campaign efficiency and propose a reallocation move.

    Args:
        rows: Per-campaign performance rows.
        platform: Stamped onto the returned :class:`BudgetEfficiency`.
        account_id: Same.
        spend_key: ``"cost"`` for Google, ``"spend"`` for Meta.
        nested_metrics: ``True`` when the row may wrap metrics under
            ``row["metrics"]`` (Google live). The function still
            tolerates either shape when this flag is set; the explicit
            flag exists for callers that want to assert the shape they
            expect (and catch upstream bugs that drop the wrapper).
    """
    rates: dict[str, tuple[float, float]] = {}  # campaign_id -> (rate, cost)
    total_unused = 0.0
    # #342 — the operator conversion override is Meta-specific; resolve once
    # for the account (None for non-Meta platforms / unset accounts).
    cv_types = (
        load_conversion_action_types(account_id) if platform == "meta_ads" else None
    )
    for row in rows:
        extracted = _extract_cost_and_conversions(
            row,
            spend_key=spend_key,
            nested_metrics=nested_metrics,
            conversion_action_types=cv_types,
        )
        if extracted is None:
            continue
        campaign_id, cost, conversions = extracted
        rate = conversions / cost  # cost > 0 enforced by extractor
        rates[campaign_id] = (rate, cost)
        if conversions == 0:
            total_unused += cost

    if not rates:
        return BudgetEfficiency(
            platform=platform,
            account_id=account_id,
            per_campaign_score=(),
            rebalance_suggestion="no campaigns with spend",
            unused_budget_amount=0.0,
        )

    best_rate = max(rate for rate, _ in rates.values())
    if best_rate <= 0:
        # All campaigns have zero conversions — every campaign is "as
        # efficient as the best", which is meaningless. Return zeros
        # and let the workflow flag the absence of conversions.
        scores = [(cid, 0.0) for cid in sorted(rates)]
        return BudgetEfficiency(
            platform=platform,
            account_id=account_id,
            per_campaign_score=tuple(scores),
            rebalance_suggestion=(
                "no campaign converted this window — check tracking before "
                "reallocating budget"
            ),
            unused_budget_amount=total_unused,
        )

    scored: list[tuple[str, float]] = []
    for cid in sorted(rates):
        rate, _ = rates[cid]
        scored.append((cid, round(rate / best_rate, 3)))

    inefficient = [cid for cid, score in scored if score < INEFFICIENT_THRESHOLD]
    # The top campaign by definition scores 1.0 (best_rate > 0 here), so
    # at least one campaign satisfies the EFFICIENT_THRESHOLD bound —
    # the previous ``elif inefficient and not efficient`` branch was
    # unreachable. Kept the suggestion text scoped to the inefficient/
    # efficient split that actually occurs.
    efficient = [cid for cid, score in scored if score >= EFFICIENT_THRESHOLD]

    if inefficient:
        suggestion = (
            f"reallocate spend from {len(inefficient)} inefficient campaign(s) "
            f"({', '.join(inefficient[:3])}) toward {len(efficient)} efficient "
            f"campaign(s) ({', '.join(efficient[:3])})"
        )
    else:
        suggestion = "budget mix is balanced — no reallocation suggested"

    return BudgetEfficiency(
        platform=platform,
        account_id=account_id,
        per_campaign_score=tuple(scored),
        rebalance_suggestion=suggestion,
        unused_budget_amount=total_unused,
    )


__all__ = [
    "EFFICIENT_THRESHOLD",
    "INEFFICIENT_THRESHOLD",
    "score_budget_efficiency",
]
