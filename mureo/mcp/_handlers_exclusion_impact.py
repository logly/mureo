"""MCP handler for ``analysis_exclusion_impact_preview`` (#547).

Read-only. Two ways to call it, and the second is why it exists for
platforms mureo does not own:

1. ``tool`` + ``arguments`` — "this is the call I am about to make".
   mureo resolves the entities from the tool's own arguments and fetches
   the account's own recent delivery for that scope. Available for every
   registered exclusion surface (mureo's own, plus whatever a plugin
   registered).
2. ``excluded_entities`` + ``delivery_records`` — the caller supplies both
   sides. Reaches no platform API at all, so a Yahoo placement URL list, a
   LOGLY adspot block or an Amazon negative-targeting batch is auditable
   whenever the agent can pull that platform's own report itself.

``delivery_records`` may also be combined with ``tool``, which then reads
the entities from the arguments and issues no platform request.

``would_block`` is computed by the same
:func:`~mureo.analysis.exclusion_impact.evaluate_exclusion_impact` the
dispatcher pre-flight calls, against the same STRATEGY.md, so what this
tool advertises and what the guardrail enforces cannot drift.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.analysis.exclusion_impact import (
    DeliveryRecord,
    DeliverySample,
    ExclusionTarget,
    estimate_exclusion_impact,
    evaluate_exclusion_impact,
    exclusion_impact_rules,
    exclusion_surface_for,
    registered_exclusion_tools,
)
from mureo.mcp._helpers import _json_result, _opt

if TYPE_CHECKING:
    from mcp.types import TextContent

logger = logging.getLogger(__name__)

_SUPPLIED_BASIS = "caller_supplied_delivery_records"


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _records(raw: Any) -> tuple[DeliveryRecord, ...] | None:
    """Caller-supplied delivery rows, or ``None`` when none were supplied.

    An explicitly supplied EMPTY list is a measured "nothing served", so it
    is kept distinct from the key being absent.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("delivery_records must be a list of objects")
    return tuple(
        DeliveryRecord(
            entity=str(row.get("entity") or ""),
            entity_type=str(row.get("entity_type") or ""),
            impressions=_number(row.get("impressions")),
            clicks=_number(row.get("clicks")),
            cost=_number(row.get("cost")),
            conversions=_number(row.get("conversions")),
        )
        for row in raw
        if isinstance(row, dict)
    )


def _targets(raw: Any) -> tuple[ExclusionTarget, ...]:
    if not isinstance(raw, list):
        raise ValueError("excluded_entities must be a list of objects")
    return tuple(
        ExclusionTarget(
            value=str(row.get("value") or ""),
            entity_type=str(row.get("entity_type") or ""),
            match_type=(
                str(row["match_type"]) if row.get("match_type") is not None else None
            ),
        )
        for row in raw
        if isinstance(row, dict) and row.get("value")
    )


def _supplied_sample(
    records: tuple[DeliveryRecord, ...],
    targets: tuple[ExclusionTarget, ...],
    standing: tuple[ExclusionTarget, ...] | None,
) -> DeliverySample:
    """Every kind present in supplied rows is attributable by construction."""
    return DeliverySample(
        records=records,
        basis=_SUPPLIED_BASIS,
        attributable_types=frozenset(
            {record.entity_type for record in records}
            | {target.entity_type for target in targets}
        ),
        standing=standing,
        standing_reason=(
            "" if standing is not None else "No standing_exclusions were supplied."
        ),
    )


async def _resolve(
    arguments: dict[str, Any], window_days: int
) -> tuple[tuple[ExclusionTarget, ...], DeliverySample, str]:
    """Return (targets, sample, note) for either calling convention."""
    tool = _opt(arguments, "tool")
    supplied = _records(arguments.get("delivery_records"))
    standing = (
        _targets(arguments["standing_exclusions"])
        if isinstance(arguments.get("standing_exclusions"), list)
        else None
    )
    if tool:
        surface = exclusion_surface_for(str(tool))
        if surface is None:
            raise ValueError(
                f"'{tool}' is not a registered exclusion surface. Known "
                f"surfaces: {', '.join(sorted(registered_exclusion_tools()))}. "
                f"Pass excluded_entities + delivery_records instead to size an "
                f"exclusion on a platform mureo does not model."
            )
        call_args = arguments.get("arguments") or {}
        if not isinstance(call_args, dict):
            raise ValueError("arguments must be an object")
        targets = tuple(surface.targets(call_args))
        if supplied is not None:
            return targets, _supplied_sample(supplied, targets, standing), surface.note
        return targets, await surface.delivery(call_args, window_days), surface.note
    targets = _targets(arguments.get("excluded_entities") or [])
    if not targets:
        raise ValueError(
            "Provide either 'tool' (+ 'arguments') or a non-empty "
            "'excluded_entities' list."
        )
    if supplied is None:
        return (
            targets,
            DeliverySample(
                records=None,
                basis=_SUPPLIED_BASIS,
                reason=(
                    "No delivery_records were supplied and no tool was named, "
                    "so mureo has nothing to size this exclusion against."
                ),
            ),
            "",
        )
    return targets, _supplied_sample(supplied, targets, standing), ""


async def handle_exclusion_impact_preview(
    arguments: dict[str, Any],
) -> list[TextContent]:
    """Size an exclusion batch without applying it."""
    from mureo.policy.strategy_gate import load_guardrails

    rules = exclusion_impact_rules(load_guardrails())
    window_days = int(_opt(arguments, "window_days", rules.window_days))
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    targets, sample, note = await _resolve(arguments, window_days)
    impact = estimate_exclusion_impact(
        targets=targets,
        records=sample.records,
        attributable_types=sample.attributable_types,
        basis=sample.basis,
        window_days=window_days,
        standing=sample.standing,
        coverage_reason=sample.reason,
        cumulative_reason=sample.standing_reason,
    )
    block_reason = evaluate_exclusion_impact(impact, rules)
    payload: dict[str, Any] = {
        "tool": _opt(arguments, "tool"),
        "excluded_entity_count": len(targets),
        "impact": impact.as_dict(),
        "guardrails": {
            "enabled": rules.enabled(),
            "max_delivery_share_removed_pct": rules.max_share_pct,
            "max_cumulative_delivery_share_removed_pct": (
                rules.max_cumulative_share_pct
            ),
            "exclusion_impact_window_days": rules.window_days,
            "exclusion_impact_metrics": list(rules.metrics),
            "block_exclusions_without_impact_data": rules.block_without_data,
        },
        "would_block": block_reason is not None,
        "block_reason": block_reason,
    }
    if note:
        payload["note"] = note
    return _json_result(payload)


__all__ = ["handle_exclusion_impact_preview"]
