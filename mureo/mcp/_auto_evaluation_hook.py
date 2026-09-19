"""The ``mureo_state_get`` half of the automatic observation closure (#758).

:mod:`mureo.context.auto_evaluation` decides and writes; this module is the
thin layer that joins it to the MCP read path. Three things live here and
nothing else:

- **When** it runs — ``auto_evaluate`` on ``mureo_state_get``, default true.
  Before the read, so the response an agent gets already reflects the
  closures: a ``pending`` scope in the same call no longer lists the entry
  mureo just closed.
- **Whether it may write** — the closure appends an ``action_log`` entry, so
  it asks the SAME policy gates a ``mureo_state_action_log_append`` call
  would face. A read-only deployment (mureo-agency's gate) therefore skips
  the write with the gate's own sentence, instead of a read tool quietly
  doing what the host forbids a write tool to do.
- **What a failure costs** — nothing. Any exception is caught, logged with
  its traceback and reported as ``auto_evaluation_error``. ``mureo_state_get``
  is the call every skill starts from; a closure that cannot be computed must
  not take the document with it.

Journal (#758 phase 1): the call stays ``mutating: false``. That is the
honest classification — the agent asked to read — and the trail is complete
without reclassifying it: each closure entry carries the writing session's
id and a machine-built ``reason``, so the record says what was appended, by
which session, and why.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from mureo.context.auto_evaluation import close_due_observations

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

#: The tool whose permission a closure borrows. It appends an ``action_log``
#: entry, so this is the name the gates are asked about — not the read tool
#: the agent actually called.
APPEND_TOOL_NAME: Final = "mureo_state_action_log_append"

#: What a denial reads as when the gate stated none. ``PolicyDecision.reason``
#: is documented as required-when-denying, but a third-party gate can still
#: leave it empty and "write_denied: " with nothing after it is unreadable.
UNSTATED_DENIAL: Final = "refused by a policy gate"

#: The ``auto_evaluate`` switch on ``mureo_state_get``. Defined here rather
#: than in ``tools_mureo_context.py``, which is already far over the repo's
#: file-length limit — the same placement the ``decisions`` scope uses.
AUTO_EVALUATE_PROPERTY: dict[str, Any] = {
    "type": "boolean",
    "description": (
        "Close past-due observations automatically (default true). Before "
        "reading, mureo evaluates every open ``action_log`` entry whose "
        "``observation_due`` has passed and whose outcome its own document "
        "determines — a campaign-level action with a numeric "
        "``metrics_at_action``, on a platform whose campaign metrics were "
        "collected on or after the due date — and WRITES an "
        "``evaluation_of`` record for each, so it leaves the pending set. "
        "The response then carries ``auto_evaluations`` (what was closed, "
        "with the verdict) and ``auto_evaluation_skipped`` (what still "
        "needs the manual ``mureo_outcome_evaluate`` + ``evaluation_of`` "
        "append, each with a reason). Pass false for a strictly read-only "
        "call — an inspection, a dry run, or a host that must not have its "
        "STATE.json touched by a read; the two keys are then omitted "
        "entirely and you owe every past-due entry a manual evaluation."
    ),
}


def _policy_denial(tool_name: str) -> str | None:
    """The reason the host's policy gates give for refusing ``tool_name``.

    ``None`` means every gate allowed or abstained. The gates are consulted
    with an EMPTY argument map: there is no tool call to describe — the
    closure is mureo's own write — and the question being asked is the
    coarse one a read-only gate answers on the tool name alone. A gate that
    inspects arguments (the built-in ``## Guardrails`` one does) therefore
    sees nothing to object to, which is the correct answer for a record
    that changes no ad account.
    """
    # Lazy: ``mureo.mcp.server`` imports the tool modules, one of which
    # imports this one for the schema property above.
    from mureo.mcp.server import _evaluate_policy_gates

    decision = _evaluate_policy_gates(tool_name, {})
    if decision is None:
        return None
    return decision.reason.strip() or UNSTATED_DENIAL


def _auto_evaluate(path: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run the closure pass and return the response fragment for it.

    Empty when ``auto_evaluate`` is false — the caller opted out, so the
    response says nothing about a pass that did not happen. Otherwise both
    list keys are always present, empty included: "mureo closed nothing" and
    "mureo did not look" are different answers, and an agent deciding
    whether it still owes an evaluation has to be able to tell them apart.
    """
    if not arguments.get("auto_evaluate", True):
        return {}
    # Reached through the module so a test that freezes the clock is seen
    # here too (see ``mureo.core.clock``).
    from mureo.core import clock

    fragment: dict[str, Any] = {"auto_evaluations": [], "auto_evaluation_skipped": []}
    try:
        result = close_due_observations(
            path,
            today=clock.server_now().date(),
            may_write=lambda: _policy_denial(APPEND_TOOL_NAME),
        )
    except Exception as exc:  # noqa: BLE001 — a read must not fail on this
        logger.warning(
            "automatic observation closure failed for %s; returning the "
            "document unchanged",
            path,
            exc_info=True,
        )
        fragment["auto_evaluation_error"] = f"{type(exc).__name__}: {exc}"
        return fragment
    fragment["auto_evaluations"] = [
        {
            "index": c.index,
            "evaluation_index": c.evaluation_index,
            "overall": c.overall,
            "summary": c.summary,
        }
        for c in result.closed
    ]
    fragment["auto_evaluation_skipped"] = [
        {"index": s.index, "reason": s.reason} for s in result.skipped
    ]
    return fragment


__all__ = ["APPEND_TOOL_NAME", "AUTO_EVALUATE_PROPERTY", "_auto_evaluate"]
