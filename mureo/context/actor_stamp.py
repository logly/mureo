"""WHO wrote a record, and WHY — stamped in one place (#758).

:func:`mureo.context.state.append_action_log` has stamped the rationale and
the writing process's identity onto every entry since phase 2. Phase 5 added
a SECOND writer of ``action_log`` entries — the automatic observation closure
in :mod:`mureo.context.auto_evaluation`, which appends its records inside its
own locked document write rather than one call at a time — and two copies of
"if it is unset, fill it in from :mod:`mureo.core.actor`" is how a mureo-made
entry ends up without a session id on one path and with one on the other.
:func:`mureo.context.decisions.append_decision` is the third writer: a
decision and the actions it produced must carry the same session id.

So the stamp lives here, and every writer calls it. The identity rule is
:func:`stamp_identity`: an explicit value is KEPT, because an imported or
replayed record names the session that made the change rather than the one
replaying it, and only an absent field is filled in.

The rationale is passed IN rather than read here. Deciding what an entry's
reason is — the caller's own, the dispatcher's call-level one, or nothing at
all for an observed external change — is a policy the writers own and they
do not agree on it: ``append_action_log`` inherits the call's reason,
``auto_evaluation`` builds its own sentence from the verdict it just
computed. What both need is one place that puts it on the entry. A decision
carries its own ``rationale`` field instead, so it takes only the identity.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeVar

from mureo.core import actor

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry

__all__ = ["stamp_actor", "stamp_identity"]


class _IdentityCarrier(Protocol):
    """A frozen dataclass record carrying the writer's identity fields."""

    __dataclass_fields__: ClassVar[dict[str, Any]]

    @property
    def session_id(self) -> str | None: ...

    @property
    def client(self) -> str | None: ...


_R = TypeVar("_R", bound=_IdentityCarrier)


def stamp_identity(record: _R) -> _R:
    """``record`` with ``session_id`` / ``client`` filled in where unset.

    Both come from :mod:`mureo.core.actor`; an explicit value is kept, since
    a replayed or imported record names the session that wrote it, not the
    one writing it down now.
    """
    return replace(
        record,
        session_id=(
            record.session_id if record.session_id is not None else actor.session_id()
        ),
        client=record.client if record.client is not None else actor.client_info(),
    )


def stamp_actor(entry: ActionLogEntry, reason: str | None) -> ActionLogEntry:
    """Return ``entry`` with ``reason`` set and its identity filled in.

    ``session_id`` and ``client`` are filled in by :func:`stamp_identity`,
    only where the entry carries none. ``reason`` is set to what the caller
    passed, whatever the entry held: the writers above establish it before
    the lock (bounded, and scrubbed where it is caller-supplied), so this is
    the value that has crossed the write boundary.
    """
    return replace(stamp_identity(entry), reason=reason)
