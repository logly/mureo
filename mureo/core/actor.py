"""Who is writing, and why (#758, phase 2).

Two questions every audit trail has to answer and mureo previously could
not: **who** made this change, and **why**. The journal already knew the
first — it minted a session id per server process and recorded the
connected MCP client — but that knowledge lived in
:mod:`mureo.mcp.journal`, one layer ABOVE the module that actually writes
the ``action_log``. :func:`mureo.context.state.append_action_log` cannot
import :mod:`mureo.mcp` (``context`` sits below ``mcp`` in the layering,
and ``mcp`` imports ``context``), so the process identity moved down here
where both callers can reach it. ``journal`` re-exports the three names,
so every existing importer keeps working.

The rationale is the new half. An agent that pauses a campaign knows why
it is doing so at the moment it dispatches the call; nothing downstream
ever recovers that sentence. So the dispatcher binds it to the call and
the write choke point stamps it onto whatever ``action_log`` entry the
call produces — no recorder, tool schema or plugin ABI has to know.

``_call_reason`` is a :class:`~contextvars.ContextVar`, not a module
global, and that is load-bearing rather than stylistic: a ContextVar is
per asyncio task, so two tool calls running concurrently in one server
process each see their OWN rationale. A global would let the later call's
reason overwrite the earlier one and be stamped onto its entry — a
plausible-looking sentence attached to the wrong change, which is worse
than no sentence at all.
"""

from __future__ import annotations

import contextvars
import threading
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final

from mureo.core.scrub import scrub_text

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Hard cap on a call's rationale. One or two sentences naming the
#: evidence and the expected effect — the length a person reads off an
#: audit row, not a place to restate the analysis.
#:
#: Not the same budget as :data:`mureo.mcp.journal.MAX_REASON_CHARS`, and
#: deliberately so: this one is a write-boundary rule on a value a caller
#: supplies (over-long is REFUSED, see :func:`normalize_reason`), while
#: the journal's is a line-length cap on text mureo generates itself
#: (over-long is TRUNCATED, because dropping the record would be worse).
ACTION_REASON_MAX_CHARS: Final = 500

#: One id per process, minted on first use. Lets a reader group the calls
#: and the ``action_log`` entries of one MCP session without the client
#: having to supply anything.
_session: str | None = None

#: Guards the mint above. The stdio server is single-threaded, but this
#: module is also reached from library and CLI code, and two threads
#: racing here would hand out two ids for one process — splitting a
#: session's trail in half for whoever reads it back.
_session_lock = threading.Lock()

#: ``"<name>/<version>"`` of the connected MCP client, or ``None`` when the
#: SDK did not report one. Set once per process by the dispatcher.
_client: str | None = None

#: The rationale bound to the call running in THIS task, or ``None``.
_call_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mureo_call_reason", default=None
)


def session_id() -> str:
    """Return this process's session id (minted on first use)."""
    global _session
    with _session_lock:
        if _session is None:
            _session = uuid.uuid4().hex
        return _session


def set_client_info(name: str, version: str) -> None:
    """Record which MCP client is connected, for every later write.

    Called once per process by the dispatcher from inside the low-level
    SDK's request context. Ignored when the name is empty — an unnamed
    client is no more informative than ``null`` and would only make the
    field look populated.
    """
    global _client
    label = str(name).strip()
    if not label:
        return
    revision = str(version).strip()
    _client = f"{label}/{revision}" if revision else label


def client_info() -> str | None:
    """Return the connected client label, or ``None`` if unknown.

    ``None`` is the honest answer for a CLI run, a library call, or an MCP
    client that reported no ``clientInfo`` — not a defect to paper over.
    """
    return _client


def normalize_reason(value: Any) -> str | None:
    """Clean a caller-supplied rationale, or refuse it.

    ``None``, a non-string and a blank string all read as "no rationale
    was given" and collapse to ``None``. Anything longer than
    :data:`ACTION_REASON_MAX_CHARS` is **refused, never truncated** — the
    same write-boundary rule the #706 display fields follow: the caller is
    holding the sentence at the moment of refusal and can shorten it,
    while a half-sentence on an audit row reads as a bug in mureo and
    nobody downstream can tell what was cut.

    The survivor is scrubbed here, at the single boundary every rationale
    crosses, so STATE.json and JOURNAL.jsonl cannot disagree about what a
    secret is: a model that quotes the failing request into its reason
    ("retrying after api_key=… was rejected") must not leak the key into
    a file the operator commits.

    Raises:
        ValueError: ``value`` is longer than :data:`ACTION_REASON_MAX_CHARS`.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > ACTION_REASON_MAX_CHARS:
        raise ValueError(
            f"reason must be at most {ACTION_REASON_MAX_CHARS} characters; "
            f"got {len(cleaned)}"
        )
    return scrub_text(cleaned)


@contextmanager
def bind_call_reason(reason: str | None) -> Iterator[None]:
    """Bind ``reason`` to the current task for the duration of the block.

    Reset in ``finally`` so a raising call leaves nothing bound: the next
    call in the same task must never inherit a rationale that belonged to
    a change that failed.
    """
    token = _call_reason.set(reason)
    try:
        yield
    finally:
        _call_reason.reset(token)


def current_call_reason() -> str | None:
    """The rationale bound to the call running in this task, or ``None``."""
    return _call_reason.get()


__all__ = [
    "ACTION_REASON_MAX_CHARS",
    "bind_call_reason",
    "client_info",
    "current_call_reason",
    "normalize_reason",
    "session_id",
    "set_client_info",
]
