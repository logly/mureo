"""The ``mureo_learning_reset_preflight`` MCP tool (#548).

The read-only, before-the-change surface of the learning-period pre-flight:
given the tool the agent is *about* to call and the arguments it is about to
pass, it answers the two questions the operator's confirmation step needs —
is this change reset-triggering, and is the campaign already in a learning
period — plus whether the operator's STRATEGY.md would refuse it.

``would_block`` is computed by the exact function the gate uses
(:func:`mureo.policy.learning_reset.learning_reset_denial`), so the pre-flight
and the enforcement cannot drift into disagreeing.

Every answer is explicit about not knowing. ``reset_risk`` is ``unknown`` for
a platform mureo has no first-party trigger list for, and
``learning_state.state`` is ``unknown`` / ``unreportable`` rather than
``steady`` when nothing was observed — a false "safe" here would convert a
missing warning into implied approval.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.types import TextContent, Tool

from mureo.policy.learning_reset import learning_reset_denial, load_preflight
from mureo.policy.learning_rules import registered_platforms
from mureo.policy.strategy_gate import Guardrails, guardrails_from_strategy_text

TOOL_NAME = "mureo_learning_reset_preflight"

TOOLS: list[Tool] = [
    Tool(
        name=TOOL_NAME,
        description=(
            "Pre-flight a pending ad-platform change against the target "
            "campaign's learning period. Read-only — it changes nothing and "
            "calls no platform API. Returns (1) whether mureo classifies the "
            "change as restarting an automated bid strategy's learning "
            "period, with the first-party source that classification rests "
            "on; (2) the campaign's current learning state as recorded in "
            "STATE.json; (3) whether STRATEGY.md ## Guardrails "
            "(block_learning_resets / "
            "block_learning_resets_during_incident) would refuse it. Call "
            "this BEFORE a bid-strategy, budget, conversion-setting, keyword "
            "or re-enable change and show the operator the answer in your "
            "confirmation step. reset_risk='unknown' and "
            "learning_state.state='unknown'/'unreportable' mean mureo does "
            "not know — they never mean safe."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": (
                        "The tool you are about to call, e.g. "
                        "'google_ads_campaigns_update'."
                    ),
                },
                "arguments": {
                    "type": "object",
                    "description": (
                        "The arguments you are about to pass. Needed because "
                        "one tool can be both: "
                        "google_ads_campaigns_update resets learning when it "
                        "carries bidding_strategy and does not when it only "
                        "renames the campaign."
                    ),
                    "additionalProperties": True,
                },
                "campaign_id": {
                    "type": "string",
                    "description": (
                        "Campaign whose learning state to look up. Optional "
                        "when 'arguments' already carries campaign_id; supply "
                        "it for tools keyed on something else (e.g. "
                        "google_ads_budget_update takes a budget_id), "
                        "otherwise the learning state is reported unknown."
                    ),
                },
            },
            "required": ["tool_name"],
            "additionalProperties": False,
        },
    ),
]

_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in TOOLS)


def _guardrails() -> Guardrails:
    """The operator's guardrails, read fresh. Fail-open (empty) on any error."""
    from mureo.policy.strategy_gate import _resolve_strategy_path

    try:
        path = _resolve_strategy_path()
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return guardrails_from_strategy_text(text)
    except Exception:  # noqa: BLE001 — a read-only pre-flight never fails hard
        return Guardrails()


async def _handle_preflight(arguments: dict[str, Any]) -> list[TextContent]:
    tool_name = arguments.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name is required")
    pending = arguments.get("arguments") or {}
    if not isinstance(pending, dict):
        raise ValueError("arguments must be an object")
    campaign_id = arguments.get("campaign_id")

    pre = load_preflight(
        tool_name.strip(),
        pending,
        str(campaign_id) if isinstance(campaign_id, str) and campaign_id else None,
    )
    guardrails = _guardrails()
    denial = learning_reset_denial(
        pre,
        block_all=guardrails.block_learning_resets,
        block_during_incident=guardrails.block_learning_resets_during_incident,
    )
    payload: dict[str, Any] = pre.to_dict()
    payload["guardrails"] = {
        "block_learning_resets": guardrails.block_learning_resets,
        "block_learning_resets_during_incident": (
            guardrails.block_learning_resets_during_incident
        ),
    }
    payload["would_block"] = denial is not None
    payload["block_reason"] = denial
    payload["platforms_with_learning_rules"] = list(registered_platforms())
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


_HANDLERS: dict[str, Any] = {TOOL_NAME: _handle_preflight}


async def handle_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a learning-pre-flight tool call to its handler."""
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    handler = _HANDLERS.get(name)
    if handler is None:
        raise ValueError(f"Unknown tool: {name}")
    return await handler(arguments)  # type: ignore[no-any-return]


__all__ = ["TOOLS", "TOOL_NAME", "handle_tool"]
