"""The ``mureo_outcome_evaluate`` handler (#888, #889).

The answer carries the evaluation table automatic closure stores, under
``evaluation`` — the same field name as on the ``outcome_evaluated`` entry —
next to the legacy keys (``overall`` / ``summary`` / ``primary`` / ``basis``
/ ``reason`` / ``metrics``), which are read off that same table. The agent
appends the table unchanged with ``evaluation_of``, so a manual evaluation
leaves the record an automatic one does.

Two ways in:

- ``evaluation_of``: the action-log entry being evaluated. Its chained
  decision's ``expected`` effects, its campaign's ``bidding_details`` and its
  ``metrics_at_action`` are resolved from STATE.json and scored by
  :func:`mureo.context.auto_evaluation.evaluate_entry`, the scoring path of
  the automatic closure itself. An explicit ``expected`` beside it is
  refused (one source of truth), and so is an explicit ``before`` beside a
  recorded baseline; ``before`` is needed only when the entry recorded none.
  A result with no comparable metric is refused, so an empty table is never
  handed out to be stored.
- ``before`` / ``after`` / optional ``expected``: scored by
  :func:`mureo.analysis.expected_eval.build_evaluation`, with no window.

Split out of :mod:`mureo.mcp._handlers_mureo_context`, which is at the size
limit; that module keeps the append side and the shared index check.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from mureo.analysis.expected_eval import build_evaluation
from mureo.context.auto_evaluation import (
    SKIP_NO_COMPARABLE_METRIC,
    entry_snapshot,
    evaluate_entry,
)
from mureo.context.expected import parse_expected
from mureo.context.state import read_state_file
from mureo.mcp._handlers_mureo_context import validate_closure_index
from mureo.mcp._helpers import _json_result, _require, resolve_workspace_path
from mureo.mcp._outcome_thresholds import load_outcome_thresholds

if TYPE_CHECKING:
    from mcp.types import TextContent

    from mureo.analysis.expected_eval import EvaluationResult
    from mureo.analysis.outcome_eval import OutcomeThresholds
    from mureo.context.models import ActionLogEntry

#: Refusal code: ``evaluation_of`` and an explicit ``expected`` together. Led
#: into the message the way ``expected_primary_required`` is.
EVALUATION_OF_CONFLICTS_WITH_EXPECTED: Final = "evaluation_of_conflicts_with_expected"
#: Refusal code: ``evaluation_of`` on an entry with a baseline, and an
#: explicit ``before`` too. Same shape as the one above.
EVALUATION_OF_CONFLICTS_WITH_BEFORE: Final = "evaluation_of_conflicts_with_before"

_MAPS_HINT: Final = "before and after must be objects (metric name -> number)"


def _metric_maps(
    before: object, after: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError(_MAPS_HINT)
    return before, after


def _evaluate_maps(
    arguments: dict[str, Any], after: object, thresholds: OutcomeThresholds
) -> EvaluationResult:
    """Score the explicit ``before`` / ``after`` / ``expected``."""
    before, current = _metric_maps(_require(arguments, "before"), after)
    expected = parse_expected(arguments.get("expected"))
    return build_evaluation(
        before,
        current,
        expected,
        window_from=None,
        window_to=None,
        thresholds=thresholds,
    )


def _baseline(arguments: dict[str, Any], entry: ActionLogEntry) -> object:
    """The entry's ``metrics_at_action``, or ``before`` when it has none."""
    if not entry.metrics_at_action:
        return _require(arguments, "before")
    if arguments.get("before") is not None:
        raise ValueError(
            f"{EVALUATION_OF_CONFLICTS_WITH_BEFORE}: the evaluated entry "
            "recorded metrics_at_action, which is the baseline; omit before"
        )
    return entry.metrics_at_action


def _evaluate_entry_of(
    arguments: dict[str, Any], after: object, thresholds: OutcomeThresholds
) -> EvaluationResult:
    """Score the entry ``evaluation_of`` names, as automatic closure would."""
    if arguments.get("expected") is not None:
        raise ValueError(
            f"{EVALUATION_OF_CONFLICTS_WITH_EXPECTED}: with evaluation_of the "
            "expected effects are the ones the evaluated entry's decision "
            "declared; omit expected"
        )
    path = resolve_workspace_path(arguments, "STATE.json", store_attr="state_path")
    doc = read_state_file(path)
    validate_closure_index(arguments, "evaluation_of", len(doc.action_log))
    entry = doc.action_log[arguments["evaluation_of"]]
    before, current = _metric_maps(_baseline(arguments, entry), after)
    entry = replace(entry, metrics_at_action=before)
    snapshot = entry_snapshot(doc, entry)
    bidding = None if isinstance(snapshot, str) else snapshot.bidding_details
    result = evaluate_entry(
        doc,
        entry,
        current,
        bidding_details=bidding,
        thresholds=thresholds,
    )
    if isinstance(result, str):
        raise ValueError(
            f"{result}: before and after state different periods and the "
            "primary metric is a count; pass after over the same window as "
            "the baseline"
        )
    if result.scored == 0:
        raise ValueError(
            f"{SKIP_NO_COMPARABLE_METRIC}: the baseline and after share no "
            "numeric metric; pass after with the metric names the baseline uses"
        )
    return result


def _answer(result: EvaluationResult) -> dict[str, Any]:
    """The legacy keys, read off the table, and the table under ``evaluation``."""
    table = result.table
    payload: dict[str, Any] = {
        "overall": result.overall,
        "summary": result.summary,
        "primary": table["primary"],
        "basis": table["basis"],
    }
    if "reason" in table:
        payload["reason"] = table["reason"]
    payload["metrics"] = [
        {key: value for key, value in row.items() if key != "role"}
        for row in table["metrics"]
    ]
    payload["evaluation"] = table
    return payload


async def handle_outcome_evaluate(arguments: dict[str, Any]) -> list[TextContent]:
    """Deterministically evaluate a before→after metric change.

    Returns every metric's row and the primary metric's verdict (#888), on
    the workspace's ``## Guardrails`` thresholds unless ``noise_pct`` is set,
    and the table to store with the evaluation record (#889).
    """
    after = _require(arguments, "after")
    thresholds = load_outcome_thresholds(arguments.get("noise_pct"))
    if arguments.get("evaluation_of") is None:
        result = _evaluate_maps(arguments, after, thresholds)
    else:
        result = _evaluate_entry_of(arguments, after, thresholds)
    return _json_result(_answer(result))


__all__ = [
    "EVALUATION_OF_CONFLICTS_WITH_BEFORE",
    "EVALUATION_OF_CONFLICTS_WITH_EXPECTED",
    "handle_outcome_evaluate",
]
