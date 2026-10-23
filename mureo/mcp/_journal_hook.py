"""Dispatcher-side classification for the journal (#758, phase 1).

Everything :func:`mureo.mcp.server.handle_call_tool` needs in order to
leave exactly one :mod:`mureo.mcp.journal` record per call, kept out of
``server.py`` because that module is already over the 800-line limit.

Three jobs:

- :func:`tool_family` — which dispatcher branch a name belongs to,
  answered from the dispatcher's OWN name sets rather than from a second
  hand-maintained table. A family that stops serving a name (an env gate
  switched it off) stops claiming it here too, by construction.
- :func:`tool_mutating` — the same classification the dispatcher already
  applies: :func:`mureo.core.strategy_reminder.is_mutating_builtin_tool`
  for built-ins, the derived ``_PLUGIN_SEMANTICS`` entry for plugins, and
  the conservative "undeclared ⇒ mutating" default of
  :mod:`mureo.mcp.plugin_semantics`.
- :func:`journal_call` — the context manager that times the dispatch,
  classifies the outcome, and writes the one record on the way out,
  including the exits that raise.
- :func:`take_rationale` — the one step that has to happen before any of
  the dispatcher's exits, splitting the injected ``reason`` off the
  arguments and filing it under its own key (#758 phase 2).

The plugin maps (``_PLUGIN_SEMANTICS`` / ``_PLUGIN_DISPATCH``) are
imported at top level from :mod:`mureo.mcp._plugin_tables`, which sits below
``server``; ``server`` refills those same objects in place at load, so a
test that reloads ``server`` (the plugin fixtures do) is answered from the
reloaded run (#879). A test that wants this hook to see a fake plugin must
change those dicts in place (``monkeypatch.setitem`` on the
:mod:`mureo.mcp._plugin_tables` objects) or reload ``server``; rebinding
``server._PLUGIN_DISPATCH`` with ``monkeypatch.setattr`` is not seen here.
The family name sets are built in ``server`` from the env gates and the tool
modules, and ``server`` imports this module at load time, so a top-level
import back would close a cycle. Instead :func:`tool_family` asks the view
``server`` publishes in :mod:`mureo.mcp._server_slots` at the end of its load
(#879 stage 2); the view reads ``server``'s name sets at call time, so a
reload or a ``monkeypatch.setattr`` on one of them is seen here.
"""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.mcp import _server_slots, journal
from mureo.mcp._helpers import API_ERROR_CODE, exception_text, failure_of
from mureo.mcp._plugin_tables import _PLUGIN_DISPATCH, _PLUGIN_SEMANTICS
from mureo.mcp._reason_param import split_call_reason
from mureo.mcp.tool_provider import plugin_source
from mureo.rollback.executor import is_rollback_dispatch_active

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator

logger = logging.getLogger(__name__)

#: Every ``outcome`` a record can carry — the verdicts :class:`JournalledCall`
#: sets below, in the order the dispatcher can reach them. Stated as a
#: constant since #758 phase 4b because ``mureo_history_query`` offers the
#: vocabulary as a schema ``enum``: an agent filtering on ``"failed"`` (a
#: word that appears in no record) would otherwise be told, truthfully and
#: uselessly, that nothing matched.
JOURNAL_OUTCOMES: tuple[str, ...] = (
    "ok",
    "platform_error",
    "exception",
    "denied",
    "refused",
    "invalid_args",
)

#: The family of a name no branch claims — an unknown tool, which the
#: dispatcher answers with ``ValueError``. Recorded rather than dropped:
#: an agent calling a tool that does not exist is worth seeing.
UNKNOWN_FAMILY = "unknown"

_PLUGIN_FAMILY = "plugin"

#: Random bytes in a journal ``call_id``.
_CALL_ID_BYTES = 8


def new_call_id() -> str:
    """Mint the id one tool call's journal record is named by (#848)."""
    return f"call-{secrets.token_hex(_CALL_ID_BYTES)}"


def take_rationale(
    call: JournalledCall,
    name: str,
    arguments: dict[str, Any],
    injected: Collection[str],
) -> tuple[str | None, dict[str, Any]]:
    """Split the injected ``reason`` off ``arguments`` and file it on ``call``.

    Lives here, and runs before every gate, because a rationale is only
    worth asking for if the records that need it most have it: a DENIED
    mutation is exactly the call an operator asks "why did it try that?"
    about. Returning the handler's arguments separately also keeps the
    policy gates reading the same set the handler will — ``reason`` is
    mureo's parameter, and a gate has no business seeing it.

    An over-long rationale is classified as ``invalid_args``, like the
    schema violation it is, and re-raised for the caller to surface.

    Returns:
        The rationale (``None`` when none was given, or when this tool
        owns its own ``reason``) and the arguments to dispatch with.

    Raises:
        ValueError: the rationale is over its bound.
    """
    try:
        reason, handler_args = split_call_reason(name, arguments, injected)
    except ValueError as exc:
        call.invalid_args(exc)
        raise
    if name in injected:  # a tool owning its ``reason`` keeps it in ``args``
        call.set_rationale(reason)
    return reason, handler_args


def tool_family(name: str) -> str:
    """Return the journal ``family`` label for tool ``name``.

    Raises:
        RuntimeError: ``mureo.mcp.server`` has not published its family view
            (see :mod:`mureo.mcp._server_slots`).
    """
    for names, family in _server_slots.require_tool_families()():
        if name in names:
            return family
    return UNKNOWN_FAMILY


def tool_mutating(name: str, family: str) -> bool:
    """Whether ``name`` is a mutation, by the dispatcher's own rules."""
    if family != _PLUGIN_FAMILY:
        return is_mutating_builtin_tool(name)
    semantics = _PLUGIN_SEMANTICS.get(name)
    return True if semantics is None else bool(semantics.mutating)


def plugin_source_of(name: str) -> str | None:
    """The distribution that supplied plugin tool ``name``, else ``None``."""
    provider = _PLUGIN_DISPATCH.get(name)
    return None if provider is None else plugin_source(provider)


def capture_client_info(server: Any) -> None:
    """Name the connected MCP client for every later journal record.

    Called from inside the low-level SDK's ``call_tool`` handler, where a
    request context exists: ``Server.request_context.session.client_params``
    holds the ``clientInfo`` (name + version) the client sent at
    ``initialize``. Once per process — the session's client cannot change
    mid-connection — and entirely best-effort: an SDK version that does
    not expose it, or a call made outside a request context (every direct
    unit-test call of ``handle_call_tool``), simply leaves ``client``
    ``null`` in the record.
    """
    if journal.client_info() is not None:
        return
    try:
        info = server.request_context.session.client_params.clientInfo
        journal.set_client_info(info.name, info.version)
    except Exception:  # noqa: BLE001 — a missing client name costs nothing
        logger.debug("journal: MCP client info unavailable", exc_info=True)


class JournalledCall:
    """One in-flight tool call, and the outcome it will be recorded with.

    Starts out ``ok``; the dispatcher narrows that at whichever exit it
    takes. Nothing is written until :meth:`flush`, so a call that is
    denied, refused, invalid, failed or successful leaves exactly one
    record either way.
    """

    __slots__ = (
        "arguments",
        "call_id",
        "decision_id",
        "outcome",
        "rationale",
        "reason",
        "tool",
        "_started",
    )

    def __init__(self, tool: str, arguments: dict[str, Any]) -> None:
        self.tool = tool
        # #848: the id a decision record carried out by this call names it
        # by, and that decision's id once known. Written to the record only
        # when both are set.
        self.call_id = new_call_id()
        self.decision_id: str | None = None
        # Snapshot at entry: the journal records what was REQUESTED. A
        # handler that normalises, defaults or pops its arguments in place
        # would otherwise rewrite the trail an operator reads to find out
        # what the agent actually asked for.
        self.arguments = dict(arguments) if isinstance(arguments, dict) else {}
        self.outcome = "ok"
        self.reason: str | None = None
        self.rationale: str | None = None
        self._started = time.monotonic()

    def set_rationale(self, reason: str | None) -> None:
        """Record WHY the agent made this call (#758 phase 2).

        ``reason`` is the dispatcher-injected parameter, already split off
        the arguments the handler will receive. It is removed from the
        snapshot here too: ``args`` is what the agent asked the TOOL to do,
        and an operator filtering the journal on arguments must not find a
        sentence sitting where a parameter belongs. The rationale gets its
        own key instead.

        **Call this only for a tool ``reason`` was INJECTED into.** On the
        two tools that declare a ``reason`` of their own it is a persisted
        value — the operator-facing "why was this account not collected"
        note — which the handler receives and which therefore belongs in
        ``args``; lifting it out would both lose it from the record of what
        was asked and file it under a key that means something else.
        """
        self.rationale = reason
        self.arguments.pop("reason", None)

    def denied(self, reason: str) -> None:
        """A policy gate refused the call before any handler ran."""
        self.outcome, self.reason = "denied", reason

    def refused(self, reason: str) -> None:
        """The exclusion preflight refused the call before dispatch."""
        self.outcome, self.reason = "refused", reason

    def invalid_args(self, exc: BaseException) -> None:
        """``inputSchema`` validation rejected the arguments."""
        self.outcome, self.reason = "invalid_args", str(exc)

    def failed(self, exc: BaseException) -> None:
        """The dispatch raised.

        Through :func:`mureo.mcp._helpers.exception_text`, not ``repr`` —
        the repr of a ``GoogleAdsException`` is the gRPC call repr, request
        metadata and developer token included (#603). The type name is
        prefixed here, for the journal only: a reader grouping failures
        needs it, while the operator-facing envelope keeps its wording.
        """
        name, detail = type(exc).__name__, exception_text(exc)
        self.outcome = "exception"
        self.reason = detail if detail == name else f"{name}: {detail}"

    def completed(self, result: list[Any]) -> list[Any]:
        """Classify a returned result and pass it straight through.

        A failure can arrive as ordinary content — the ``API error:`` text,
        the ``auth_error`` JSON, or the ``refused`` / ``error`` JSON of
        :func:`mureo.mcp._helpers._failure_result` — the same signal that
        stops ``action_log`` promotion, so the journal must not read it as
        a success for a call that changed nothing (#862). A ``refused``
        envelope is recorded as ``refused``, every other one as
        ``platform_error``. The result BODY is never stored: the ``API
        error:`` text keeps its own text as the reason, and a JSON
        envelope is reduced to ``"<code>: <detail>"``.
        """
        failure = failure_of(result)
        if failure is not None:
            self.outcome = (
                "refused" if failure.status == "refused" else "platform_error"
            )
            api_text = failure.status == "error" and failure.code == API_ERROR_CODE
            self.reason = (
                failure.detail if api_text else f"{failure.code}: {failure.detail}"
            )
        return result

    def flush(self) -> None:
        """Write the one record for this call. Never raises."""
        try:
            family = tool_family(self.tool)
            journal.record_call(
                tool=self.tool,
                family=family,
                mutating=tool_mutating(self.tool, family),
                arguments=self.arguments,
                outcome=self.outcome,
                reason=self.reason,
                rationale=self.rationale,
                duration_ms=int((time.monotonic() - self._started) * 1000),
                source=(
                    plugin_source_of(self.tool) if family == _PLUGIN_FAMILY else None
                ),
                rollback=is_rollback_dispatch_active(),
                call_id=self.call_id,
                decision_id=self.decision_id,
            )
        except Exception:  # noqa: BLE001 — journaling never breaks a call
            logger.warning("journal hook failed for tool %r", self.tool, exc_info=True)


@contextmanager
def journal_call(tool: str, arguments: dict[str, Any]) -> Iterator[JournalledCall]:
    """Time one dispatch and record it, on every way out.

    ``KeyboardInterrupt`` is re-raised WITHOUT a record, mirroring the
    plugin dispatch branch: it is the operator stopping the process, not
    an outcome of the tool call.
    """
    call = JournalledCall(tool, arguments)
    try:
        yield call
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        if call.outcome == "ok":  # not already classified (e.g. invalid_args)
            call.failed(exc)
        call.flush()
        raise
    else:
        call.flush()


__all__ = [
    "JOURNAL_OUTCOMES",
    "UNKNOWN_FAMILY",
    "JournalledCall",
    "capture_client_info",
    "journal_call",
    "new_call_id",
    "plugin_source_of",
    "take_rationale",
    "tool_family",
    "tool_mutating",
]
