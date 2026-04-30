"""Execute a :class:`RollbackPlan` by re-dispatching through an MCP handler.

The executor is the active half of the rollback feature: given an
index into ``STATE.json``'s ``action_log``, it re-runs
:func:`plan_rollback` on that entry, dispatches the reversal through
the same MCP handler used for forward actions, and appends a new
:class:`ActionLogEntry` tagged with ``rollback_of=<index>`` so the
history remains append-only.

Safety contract:
- ``confirm=True`` is required. Automated agents cannot apply a
  rollback by omission.
- The planner is re-invoked at execution time. A stale allow-list
  decision can never be smuggled in.
- Dispatch target cannot be a ``rollback.*`` tool. Even if a future
  allow-list entry accidentally included one, the executor refuses
  to recurse into itself.
- A later ``action_log`` entry with ``rollback_of == index`` marks
  the source as already reversed; a second call is refused.
- Dispatch failures never write to ``action_log``. The caller sees
  the underlying exception and STATE.json stays consistent.
- The appended rollback entry carries ``reversible_params=None`` so
  rollbacks of rollbacks do not chain by default.

Concurrency: STATE.json is assumed to be written by a single mureo
process at a time. The read-check-append sequence here is not
protected by a file lock; concurrent ``rollback_apply`` invocations
against the same file can race each other.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from mureo.context.models import ActionLogEntry
from mureo.context.state import append_action_log, read_state_file
from mureo.rollback.models import RollbackStatus
from mureo.rollback.planner import plan_rollback

if TYPE_CHECKING:
    from pathlib import Path


Dispatcher = Callable[[str, dict[str, Any]], Awaitable[list[Any]]]


class RollbackExecutionError(Exception):
    """Raised for any pre-dispatch refusal (missing file, out-of-range
    index, read-only entry, unsupported plan, already-rolled-back,
    missing confirm).

    Dispatch-time API failures propagate as the dispatcher's own
    exception type instead — callers can tell the two cases apart.
    """


async def execute_rollback(
    *,
    state_file: Path,
    index: int,
    confirm: bool,
    dispatcher: Dispatcher,
) -> dict[str, Any]:
    """Apply the rollback plan for ``action_log[index]``.

    Args:
        state_file: Path to STATE.json.
        index: Index into ``doc.action_log`` of the entry to reverse.
        confirm: Must be ``True`` — a second-factor against accidental
            or injected apply calls.
        dispatcher: Async callable ``(tool_name, arguments) -> result``.
            In production this is the MCP server's ``handle_call_tool``;
            tests pass a fake so the executor contract can be exercised
            without touching ad-platform APIs.

    Returns:
        A dict with ``status``, ``dispatched_tool``, ``result``, and
        ``caveats`` (possibly empty).

    Raises:
        RollbackExecutionError: Pre-dispatch refusal. STATE.json
            untouched.
        Exception: Anything the dispatcher raises. STATE.json
            untouched.
    """
    if not confirm:
        raise RollbackExecutionError(
            "Refusing to apply rollback: confirm=True is required."
        )
    if not state_file.exists():
        raise RollbackExecutionError(f"STATE.json not found: {state_file}")

    doc = read_state_file(state_file)
    if index < 0 or index >= len(doc.action_log):
        raise RollbackExecutionError(
            f"Index {index} is out of range "
            f"(action_log has {len(doc.action_log)} entries)."
        )

    entry = doc.action_log[index]
    plan = plan_rollback(entry)
    if plan is None:
        raise RollbackExecutionError(
            f"Entry #{index} ({entry.action}) is read-only — " "nothing to roll back."
        )
    if plan.status is RollbackStatus.NOT_SUPPORTED:
        raise RollbackExecutionError(
            f"Rollback not supported for entry #{index}: {plan.notes}"
        )
    # Planner guarantees these are populated when status != NOT_SUPPORTED.
    # Use explicit raises (not `assert`) so the contract holds under `python -O`.
    if plan.operation is None or plan.params is None:
        raise RollbackExecutionError(
            "Planner returned a non-NOT_SUPPORTED plan without operation/params; "
            "this is a programming error in the rollback allow-list."
        )

    # Defense-in-depth: refuse to dispatch back into the rollback surface
    # itself. If a future entry in ``_ALLOWED_OPERATIONS`` (or a badly-wired
    # test scaffold) ever names a ``rollback_*`` tool, this prevents the
    # executor from recursing into itself.
    if plan.operation.startswith("rollback_"):
        raise RollbackExecutionError(
            f"Refusing to dispatch rollback into rollback surface: " f"{plan.operation}"
        )

    for later in doc.action_log[index + 1 :]:
        if later.rollback_of == index:
            raise RollbackExecutionError(
                f"Entry #{index} was already rolled back "
                f"(see later log entry at {later.timestamp})."
            )

    # Planner already deep-copies params into the RollbackPlan, so dispatching
    # plan.params directly is safe — the stored plan cannot be mutated by the
    # dispatcher since it's a fresh copy, and subsequent executor runs always
    # call plan_rollback again from the log entry's hint.
    result = await dispatcher(plan.operation, plan.params)

    new_entry = ActionLogEntry(
        timestamp=_utc_now_iso(),
        action=plan.operation,
        platform=plan.platform,
        campaign_id=entry.campaign_id,
        summary=f"Rolled back #{index}: {entry.action}",
        rollback_of=index,
        reversible_params=None,
    )
    append_action_log(state_file, new_entry)

    return {
        "status": "applied",
        "dispatched_tool": plan.operation,
        "result": result,
        "caveats": list(plan.caveats),
        "rollback_of": index,
    }


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
