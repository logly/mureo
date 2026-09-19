"""WHO wrote an ``action_log`` entry, and WHY — stamped in one place (#758).

:func:`mureo.context.state.append_action_log` has stamped the rationale and
the writing process's identity onto every entry since phase 2. Phase 5 added
a SECOND writer of ``action_log`` entries — the automatic observation closure
in :mod:`mureo.context.auto_evaluation`, which appends its records inside its
own locked document write rather than one call at a time — and two copies of
"if it is unset, fill it in from :mod:`mureo.core.actor`" is how a mureo-made
entry ends up without a session id on one path and with one on the other.

So the stamp lives here, and both writers call it. The rule is unchanged:
an explicit value is KEPT, because an imported or replayed entry names the
session that made the change rather than the one replaying it, and only an
absent field is filled in.

The rationale is passed IN rather than read here. Deciding what an entry's
reason is — the caller's own, the dispatcher's call-level one, or nothing at
all for an observed external change — is a policy the writers own and they
do not agree on it: ``append_action_log`` inherits the call's reason,
``auto_evaluation`` builds its own sentence from the verdict it just
computed. What both need is one place that puts it on the entry.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry

__all__ = ["stamp_actor"]


def stamp_actor(entry: ActionLogEntry, reason: str | None) -> ActionLogEntry:
    """Return ``entry`` with ``reason`` set and its identity filled in.

    ``session_id`` and ``client`` are taken from :mod:`mureo.core.actor`
    only where the entry carries none. ``reason`` is set to what the caller
    passed, whatever the entry held: the writers above establish it before
    the lock (bounded, and scrubbed where it is caller-supplied), so this is
    the value that has crossed the write boundary.
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context`` ->
    # ``state_store`` -> ``mureo.context.state``, which imports this module, so
    # a module-level import would be a cycle. Same reason as the lazy import
    # this function was extracted from.
    from mureo.core.actor import client_info, session_id

    return replace(
        entry,
        reason=reason,
        session_id=entry.session_id if entry.session_id is not None else session_id(),
        client=entry.client if entry.client is not None else client_info(),
    )
