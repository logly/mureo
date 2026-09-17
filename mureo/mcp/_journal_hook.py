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

The name-set lookups import ``mureo.mcp.server`` **lazily, inside the
functions**: ``server`` imports this module at load time, so a top-level
import back would close the cycle. Resolving through the module object
also means a test that reloads ``server`` (the plugin fixtures do) is
answered from the reloaded module, not from a stale snapshot.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.mcp import journal
from mureo.mcp._helpers import exception_text, is_error_result
from mureo.rollback.executor import is_rollback_dispatch_active

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

#: ``server`` name-set attribute → journal ``family`` label, in the order
#: :func:`mureo.mcp.server._dispatch_tool` tests them, so the journal can
#: never name a different branch than the one that ran.
_FAMILIES: tuple[tuple[str, str], ...] = (
    ("_GOOGLE_ADS_NAMES", "google_ads"),
    ("_META_ADS_NAMES", "meta_ads"),
    ("_SEARCH_CONSOLE_NAMES", "search_console"),
    ("_ROLLBACK_NAMES", "rollback"),
    ("_BATCH_NAMES", "batch"),
    ("_CHANGE_IMPORT_NAMES", "change_import"),
    ("_ANALYSIS_NAMES", "analysis"),
    ("_MUREO_CONTEXT_NAMES", "mureo_context"),
    ("_ANALYTICS_REGISTRY_NAMES", "analytics"),
    ("_LEARNING_NAMES", "learning"),
    ("_LEARNING_PREFLIGHT_NAMES", "learning_preflight"),
    ("_CREATIVE_STUDIO_NAMES", "creative_studio"),
    ("_PLUGIN_NAMES", "plugin"),
)

#: The family of a name no branch claims — an unknown tool, which the
#: dispatcher answers with ``ValueError``. Recorded rather than dropped:
#: an agent calling a tool that does not exist is worth seeing.
UNKNOWN_FAMILY = "unknown"

_PLUGIN_FAMILY = "plugin"


def tool_family(name: str) -> str:
    """Return the journal ``family`` label for tool ``name``."""
    from mureo.mcp import server

    for attribute, family in _FAMILIES:
        if name in getattr(server, attribute, frozenset()):
            return family
    return UNKNOWN_FAMILY


def tool_mutating(name: str, family: str) -> bool:
    """Whether ``name`` is a mutation, by the dispatcher's own rules."""
    if family != _PLUGIN_FAMILY:
        return is_mutating_builtin_tool(name)
    from mureo.mcp import server

    semantics = server._PLUGIN_SEMANTICS.get(name)
    return True if semantics is None else bool(semantics.mutating)


def plugin_source_of(name: str) -> str | None:
    """The distribution that supplied plugin tool ``name``, else ``None``."""
    from mureo.mcp import server
    from mureo.mcp.tool_provider import plugin_source

    provider = server._PLUGIN_DISPATCH.get(name)
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

    __slots__ = ("arguments", "outcome", "reason", "tool", "_started")

    def __init__(self, tool: str, arguments: dict[str, Any]) -> None:
        self.tool = tool
        # Snapshot at entry: the journal records what was REQUESTED. A
        # handler that normalises, defaults or pops its arguments in place
        # would otherwise rewrite the trail an operator reads to find out
        # what the agent actually asked for.
        self.arguments = dict(arguments) if isinstance(arguments, dict) else {}
        self.outcome = "ok"
        self.reason: str | None = None
        self._started = time.monotonic()

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

        A platform refusal arrives as ordinary content in the canonical
        ``API error:`` envelope — the same signal that stops
        ``action_log`` promotion — so the journal must not read it as a
        success for a call that changed nothing. The result BODY is never
        stored; only this verdict and the envelope's own text.
        """
        if is_error_result(result):
            self.outcome = "platform_error"
            self.reason = getattr(result[0], "text", "")
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
                duration_ms=int((time.monotonic() - self._started) * 1000),
                source=(
                    plugin_source_of(self.tool) if family == _PLUGIN_FAMILY else None
                ),
                rollback=is_rollback_dispatch_active(),
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
    "UNKNOWN_FAMILY",
    "JournalledCall",
    "capture_client_info",
    "journal_call",
    "plugin_source_of",
    "tool_family",
    "tool_mutating",
]
