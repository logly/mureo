"""The dispatcher hook that sizes an exclusion batch before it is applied.

Why here and not in :class:`~mureo.policy.strategy_gate.StrategyPolicyGate`
------------------------------------------------------------------------

The gate is the natural home for a ``## Guardrails`` rule, and this one is
not in it, deliberately. ``PolicyGate``'s v1 ABI is *synchronous by
design* — "gates that need to await network I/O are out of scope for
``mureo.policy_gates`` in 0.9.x" — and it "MUST be pure and fast" because
it runs on **every** tool call. Sizing an exclusion needs one awaited read
of the account's own recent delivery, which is neither. So the rule is
parsed by the gate's parser (one ``## Guardrails`` vocabulary, one parser)
and enforced here, at the first point in dispatch that has both an
``await`` and the call's arguments — before ``_dispatch_tool``, so no
mutation has reached the platform when the refusal is returned.

There is also no confirmation step to put this in. MCP gives mureo two
outcomes: run the call, or refuse it. So "surface it in the confirmation
step" from the issue becomes three surfaces of deliberately different
strength:

===============================================  ==========  ================
Surface                                          When        Strength
===============================================  ==========  ================
``## Guardrails`` ``max_delivery_share_removed_pct``,
``max_cumulative_delivery_share_removed_pct``,
``block_exclusions_without_impact_data``         before      **hard** — the
                                                 dispatch    call is refused
``analysis_exclusion_impact_preview``            whenever    advisory — as
                                                 the agent   strong as the
                                                 asks        agent's
                                                             compliance
Notice appended to the exclusion call's own      after       records what was
result                                           that call   removed, so the
                                                             NEXT pass in an
                                                             incremental
                                                             sequence is not
                                                             made blind
===============================================  ==========  ================

The third one is what the motivating incident actually needed: the damage
was done by two weeks of individually-small passes, and no single one of
them was ever measured.

Fail-open, and cheap when off
-----------------------------

With none of the three rules written the pre-flight returns before it
builds a client, so no report request is issued and behaviour is
byte-identical to today. A tool that is not a registered exclusion surface
returns even earlier, without touching STRATEGY.md.

Any error — an unreadable report, a client that cannot be built, a plugin
surface that raises — becomes ``coverage: unknown`` with the reason
attached. That never blocks unless the operator wrote
``block_exclusions_without_impact_data``, and it is never rendered as
"0% impact".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.analysis.exclusion_impact import (
    COVERAGE_MEASURED,
    DeliverySample,
    ExclusionImpact,
    ExclusionImpactRules,
    estimate_exclusion_impact,
    evaluate_exclusion_impact,
    exclusion_impact_rules,
    exclusion_surface_for,
)
from mureo.core.control_flow import STOP_EXCEPTIONS

# Importing the sources module registers the built-in surfaces.
from mureo.mcp import exclusion_sources as _sources  # noqa: F401

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.analysis.exclusion_impact import ExclusionSurface

logger = logging.getLogger(__name__)

#: Env kill-switch, matching the other pre-dispatch checks. Set to ``1`` to
#: skip the check entirely (the guardrail then enforces nothing).
DISABLE_ENV_VAR = "MUREO_DISABLE_EXCLUSION_PREFLIGHT"


@dataclass(frozen=True)
class ExclusionPreflight:
    """Outcome of the pre-dispatch sizing of one exclusion batch."""

    tool: str
    impact: ExclusionImpact | None = None
    refusal_reason: str | None = None

    @property
    def checked(self) -> bool:
        return self.impact is not None


_NOT_A_SURFACE = ExclusionPreflight(tool="")


async def _sample(
    surface: ExclusionSurface, arguments: Mapping[str, Any], window_days: int
) -> DeliverySample:
    """Ask the surface for its delivery; any failure is 'unknown', not zero."""
    try:
        return await surface.delivery(arguments, window_days)
    except STOP_EXCEPTIONS:
        raise
    except BaseException as exc:  # noqa: BLE001 — a read failure is not a refusal
        logger.warning(
            "exclusion delivery read failed for %r", surface.tool, exc_info=True
        )
        return DeliverySample(
            records=None,
            basis=f"{surface.platform}_unavailable",
            reason=(
                f"mureo could not read this account's recent delivery "
                f"({type(exc).__name__}), so the size of this exclusion is "
                f"unknown."
            ),
        )


def _impact_for(
    surface: ExclusionSurface,
    arguments: Mapping[str, Any],
    sample: DeliverySample,
    window_days: int,
) -> ExclusionImpact:
    return estimate_exclusion_impact(
        targets=surface.targets(arguments),
        records=sample.records,
        attributable_types=sample.attributable_types,
        basis=sample.basis,
        window_days=window_days,
        standing=sample.standing,
        coverage_reason=sample.reason,
        cumulative_reason=sample.standing_reason,
    )


async def measure_exclusion_impact(
    surface: ExclusionSurface,
    arguments: Mapping[str, Any],
    rules: ExclusionImpactRules,
) -> ExclusionImpact:
    """Size one exclusion batch against the account's own recent delivery."""
    sample = await _sample(surface, arguments, rules.window_days)
    return _impact_for(surface, arguments, sample, rules.window_days)


async def exclusion_impact_preflight(
    name: str, arguments: Mapping[str, Any]
) -> ExclusionPreflight:
    """Size ``name(arguments)`` if it is an exclusion, else do nothing.

    Never raises: an unexpected failure degrades to "not checked", because
    a broken pre-flight must not take the exclusion tools offline.
    """
    import os

    surface = exclusion_surface_for(name)
    if surface is None or os.environ.get(DISABLE_ENV_VAR) == "1":
        return _NOT_A_SURFACE
    try:
        from mureo.policy.strategy_gate import load_guardrails

        rules = exclusion_impact_rules(load_guardrails())
        if not rules.enabled():
            # No rule written ⇒ no platform read, no refusal, no notice.
            return _NOT_A_SURFACE
        impact = await measure_exclusion_impact(surface, arguments, rules)
        return ExclusionPreflight(
            tool=name,
            impact=impact,
            refusal_reason=evaluate_exclusion_impact(impact, rules),
        )
    except STOP_EXCEPTIONS:
        raise
    except BaseException:  # noqa: BLE001 — must never break a tool call
        logger.warning("exclusion impact pre-flight failed for %r", name, exc_info=True)
        return _NOT_A_SURFACE


def refusal_content(preflight: ExclusionPreflight) -> list[Any]:
    """The TextContent payload returned in place of a refused exclusion."""
    from mcp.types import TextContent

    reason = preflight.refusal_reason or ""
    impact = preflight.impact
    body = "Tool call refused by the exclusion delivery-impact guardrail.\n"
    body += f"  Tool: {preflight.tool}\n  Reason: {reason}\n"
    if impact is not None:
        body += f"  Coverage: {impact.coverage} (basis: {impact.basis})\n"
        body += _share_lines(impact)
    return [TextContent(type="text", text=body)]


def _share_lines(impact: ExclusionImpact) -> str:
    lines: list[str] = []
    for label, shares in (
        ("this batch", impact.incremental),
        ("all standing exclusions after this batch", impact.cumulative),
    ):
        if shares is None:
            continue
        rendered = ", ".join(
            f"{share.metric} {share.share_pct:.1f}%"
            for share in shares
            if share.share_pct is not None
        )
        if rendered:
            lines.append(
                f"  Share of the last {impact.window_days} days removed by "
                f"{label}: {rendered}\n"
            )
    if impact.cumulative is None and impact.cumulative_reason:
        lines.append(f"  Cumulative share: not computed — {impact.cumulative_reason}\n")
    return "".join(lines)


def notice_text(preflight: ExclusionPreflight) -> str | None:
    """The advisory block appended to an allowed exclusion's own result."""
    impact = preflight.impact
    if impact is None:
        return None
    header = (
        f"[mureo] Delivery impact of {preflight.tool} "
        f"(last {impact.window_days} days, basis {impact.basis}):\n"
    )
    if impact.coverage != COVERAGE_MEASURED:
        header += (
            f"  Coverage: {impact.coverage} — {impact.coverage_reason}\n"
            f"  This exclusion was applied WITHOUT a measured size. Set "
            f"block_exclusions_without_impact_data in STRATEGY.md "
            f"## Guardrails to refuse this case instead.\n"
        )
    body = _share_lines(impact)
    if not body and impact.coverage == COVERAGE_MEASURED:
        body = (
            "  The window served nothing on this basis, so no share could "
            "be computed — this is not the same as 'removes nothing'.\n"
        )
    return header + body


def append_notice(result: list[Any], preflight: ExclusionPreflight) -> list[Any]:
    """Append the impact notice to an exclusion call's result. Never raises."""
    try:
        from mureo.mcp._helpers import is_error_result

        if preflight.impact is None or is_error_result(result):
            return result
        text = notice_text(preflight)
        if not text:
            return result
        from mcp.types import TextContent

        return [*result, TextContent(type="text", text=text)]
    except Exception:  # noqa: BLE001 — a notice must never break a tool call
        logger.debug("exclusion impact notice failed", exc_info=True)
        return result


__all__ = [
    "DISABLE_ENV_VAR",
    "ExclusionPreflight",
    "append_notice",
    "exclusion_impact_preflight",
    "measure_exclusion_impact",
    "notice_text",
    "refusal_content",
]
