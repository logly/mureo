"""What the running mutating call declared, for the action-log choke point (#848).

The dispatcher splits ``expected`` and ``decision_id`` off a mutating
call's arguments, exactly as it splits ``reason``, and binds them to the
running task here. :func:`mureo.context.state.append_action_log` reads them
back when the call records its change, which is what lets a decision record
be created — or an earlier proposal adopted — without any recorder, tool
schema or plugin knowing ops history exists.

A ``ContextVar`` rather than a parameter, for the reason
:func:`mureo.core.actor.bind_call_reason` gives: the recorders that append
the entry sit several calls below the dispatcher and are shared with paths
that have no call at all. ``asyncio.to_thread`` copies the context, so a
recorder running on a worker thread sees the same intent.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from mureo.context.expected import ExpectedEffect


class CallDecisionSlot:
    """The decision the running call has linked its entries to, once known.

    Deliberately mutable — the one exception to this package's frozen
    models. A call that records two entries (a bulk toggle) must put both
    under ONE decision, and the second append cannot learn the first one's
    id any other way: a ``ContextVar`` set on a worker thread does not
    propagate back. The slot lives exactly as long as the call's binding.
    """

    __slots__ = ("decision_id",)

    def __init__(self) -> None:
        self.decision_id: str | None = None


@dataclass(frozen=True)
class OpsIntent:
    """The ops-history parameters of one mutating call.

    expected: The call's declared effects; empty when none were given.
    decision_id: An explicit earlier decision to link to (a proposal to
        adopt), validated by the dispatcher before the call ran.
    arguments: A copy of the call's own arguments, so a derived title can
        say what the change set a value TO.
    applied_params: The same arguments as they may be STORED — masked and
        bounded by the dispatcher — or ``None`` when they cannot be.
    call_id: The id of the call's journal record, for the decision record.
    slot: See :class:`CallDecisionSlot`.
    """

    expected: tuple[ExpectedEffect, ...] = ()
    decision_id: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    applied_params: Mapping[str, Any] | None = None
    call_id: str | None = None
    slot: CallDecisionSlot = field(default_factory=CallDecisionSlot)


_intent: ContextVar[OpsIntent | None] = ContextVar("mureo_ops_intent", default=None)


@contextmanager
def bind_ops_intent(
    *,
    expected: tuple[ExpectedEffect, ...] = (),
    decision_id: str | None = None,
    arguments: Mapping[str, Any] | None = None,
    applied_params: Mapping[str, Any] | None = None,
    call_id: str | None = None,
) -> Iterator[OpsIntent]:
    """Bind an intent to the current task for the duration of the block.

    Reset in ``finally``, so a call that raised leaves nothing behind for
    the next call in the same task.
    """
    intent = OpsIntent(
        expected=tuple(expected),
        decision_id=decision_id,
        arguments=copy.deepcopy(dict(arguments or {})),
        applied_params=(
            None if applied_params is None else copy.deepcopy(dict(applied_params))
        ),
        call_id=call_id,
    )
    token = _intent.set(intent)
    try:
        yield intent
    finally:
        _intent.reset(token)


def current_ops_intent() -> OpsIntent | None:
    """The intent bound to the call running in this task, or ``None``."""
    return _intent.get()


__all__ = [
    "CallDecisionSlot",
    "OpsIntent",
    "bind_ops_intent",
    "current_ops_intent",
]
