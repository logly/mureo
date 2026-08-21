"""What mureo adds to a tool result, and the one thing it returns instead (#678).

Lifted verbatim out of :mod:`mureo.mcp.server`, which had grown past the point
where one reader could hold it. Nothing here changed in the move — same
functions, same bodies, same order.

Six helpers the dispatcher wraps around a tool call, and they share a contract
worth stating once rather than six times: **none of them may break the call**.
Each takes the result list and returns a new one, appending at most one
``TextContent`` block; each swallows its own failures; none raises. A reminder
that took a mutation down would be worse than the reminder never existing.

The exception is :func:`_refuse_text_content`, which is not an addition but a
replacement: it is what the agent receives *instead of* the tool's output when
a policy gate denies the call.

:func:`_capture_plugin_reversal` is the odd one out in a second way — it runs
BEFORE the mutation rather than after, and it is here because it belongs to the
same "best-effort, never blocks the call" family as its neighbours. It has one
genuine escape hatch: a stop (cancellation / ``KeyboardInterrupt`` /
``SystemExit``) is re-raised rather than degraded, because a caller that has
gone away must not have the dispatch carry on into a real-spend mutation on its
behalf.

Everything here is a function of its arguments — no module state, so nothing a
test monkey-patches on ``server`` is read from here. The dispatcher's own
latched state (``_staleness_warned``) deliberately stayed behind in
``server.py`` for exactly that reason.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.core.control_flow import STOP_EXCEPTIONS
from mureo.mcp.tool_provider import MCPReversibleToolProvider

if TYPE_CHECKING:
    from mureo.core.policy import PolicyDecision
    from mureo.mcp.tool_provider import MCPToolProvider

logger = logging.getLogger(__name__)


def _refuse_text_content(name: str, decision: PolicyDecision) -> list[Any]:
    """Build the TextContent payload returned to the agent when a
    policy gate refuses a tool call. Kept here so the message format
    has one source of truth.
    """
    from mcp.types import TextContent

    reason = decision.reason.strip() or "(no reason provided by the policy gate)"
    body = (
        f"Tool call refused by policy gate.\n"
        f"  Tool: {name}\n"
        f"  Reason: {reason}\n"
    )
    return [TextContent(type="text", text=body)]


def _maybe_append_batch_reminder(result: list[Any], *, is_mutation: bool) -> list[Any]:
    """Warn, on a mutation, that a batch has been open too long (#549).

    Push, not pull. ``mureo_batch_status`` reports the same staleness, but a
    caller who FORGOT the batch is open is by definition not asking — and every
    mutation dispatched meanwhile is another entry silently joining a change
    set it does not belong to. So the warning rides out on the mutation itself,
    the same soft-enforcement shape as the STRATEGY.md reminder.

    Re-emitted per mutation rather than latched once per process: each one adds
    a member, so each one is a new instance of the problem, not a repeat of the
    old one. Never refuses, never replaces the tool's content, never raises;
    suppress with ``MUREO_DISABLE_BATCH_REMINDER=1``.
    """
    if not is_mutation:
        # Reads add no members, so a read is not another instance of the
        # problem — warning on one would only cost context.
        return result

    from mcp.types import TextContent

    from mureo.mcp._handlers_batch import maybe_build_batch_reminder

    warning = maybe_build_batch_reminder()
    if warning is None:
        return result
    return [*result, TextContent(type="text", text=warning)]


def _maybe_append_strategy_reminder(name: str, result: list[Any]) -> list[Any]:
    """Best-effort soft-enforcement of the "strategy-driven" claim.

    For built-in mutating tools, append a short TextContent reminder
    listing STRATEGY.md section titles so the agent re-surfaces the
    operator's declared strategy after every mutation. Never refuses,
    never replaces the tool's content. Skipped when:

    - ``MUREO_DISABLE_STRATEGY_REMINDER=1`` env var is set
    - the tool is not a built-in mutating tool (read-only, discover,
      plugin tools all skip)
    - STRATEGY.md is empty / missing / unreadable

    See :mod:`mureo.core.strategy_reminder` for the classification and
    builder logic.
    """
    # Imported at the dispatcher's hot-path top rather than lazily on
    # every call — review round 2 perf nit. TextContent is already in
    # the module via TYPE_CHECKING; maybe_build_reminder is cheap.
    from mcp.types import TextContent

    from mureo.core.strategy_reminder import maybe_build_reminder

    reminder = maybe_build_reminder(name)
    if reminder is None:
        return result
    return [*result, TextContent(type="text", text=reminder)]


def _maybe_append_plugin_strategy_reminder(name: str, result: list[Any]) -> list[Any]:
    """Plugin counterpart of :func:`_maybe_append_strategy_reminder`.

    Called only for a successful *mutating* plugin tool (the dispatch branch
    has already consulted ``derive_semantics``), so the reminder fires for a
    plugin mutation exactly as it does for a built-in one — closing the
    strategy-reminder guardrail gap. Same soft-enforcement contract: never
    refuses, never replaces the tool's content, best-effort.
    """
    from mcp.types import TextContent

    from mureo.core.strategy_reminder import maybe_build_reminder_for_plugin

    reminder = maybe_build_reminder_for_plugin(name)
    if reminder is None:
        return result
    return [*result, TextContent(type="text", text=reminder)]


async def _capture_plugin_reversal(
    provider: MCPToolProvider, name: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Best-effort runtime-correct reversal capture for a plugin mutation (#327).

    Mirrors :func:`mureo.mcp.native_reversal.capture_before_state`: when the
    provider opts into :class:`MCPReversibleToolProvider`, call its
    ``capture_reversal`` **before** the mutation so it can read prior state and
    return a reversal carrying the actual entity id + prior value — something a
    static tool-definition ``meta`` reversal can never express.

    Returns ``None`` (and the caller falls back to the static ``meta``
    reversal) when the provider does not opt in, when there is no STATE.json in
    cwd to record into (so we skip the read entirely), when the call fails, or
    when the returned value is not a well-formed ``{operation: str, params:
    dict}``. A capture *failure* must not block the mutation, so it never
    raises one.

    A **stop is not a failure** — :data:`mureo.core.control_flow
    .STOP_EXCEPTIONS` (cancellation, KeyboardInterrupt, SystemExit) is
    re-raised. mureo's MCP server
    runs each tool call in a task and cancels it when the client goes away, so
    degrading that to "no reversal" would swallow the caller's own cancellation
    and let the dispatch carry straight on into the mutation, for a caller that
    is no longer waiting for the result — and would do so while the provider's
    capture was still unwinding (:mod:`mureo.amazon_ads.batch` gives a capture
    a session of its own). Same rule as
    :func:`mureo.mcp.tools_analytics_registry._handle_analytics_run` and
    :meth:`mureo.amazon_ads.bridge.AmazonAdsBridge.capture_reversal`.
    """
    if not isinstance(provider, MCPReversibleToolProvider):
        return None
    capture = getattr(provider, "capture_reversal", None)
    if not inspect.iscoroutinefunction(capture):
        return None
    # No STATE.json ⇒ nothing will be recorded; skip the (network) read.
    if not (Path.cwd() / "STATE.json").is_file():
        return None
    try:
        reversal = await capture(name, dict(arguments))
    except STOP_EXCEPTIONS:
        raise
    except BaseException:  # noqa: BLE001 — capture must never block the mutation
        logger.warning(
            "plugin capture_reversal failed for %r; falling back to static "
            "meta reversal",
            name,
            exc_info=True,
        )
        return None
    if (
        isinstance(reversal, dict)
        and isinstance(reversal.get("operation"), str)
        and isinstance(reversal.get("params"), dict)
    ):
        return reversal
    return None


def _maybe_append_learning_reset_notice(
    name: str, arguments: dict[str, Any], result: list[Any]
) -> list[Any]:
    """Append the #548 learning-period notice to a reset-triggering call.

    Fires ONLY when :func:`mureo.policy.learning_reset.classify_change` says
    the call restarts an automated bid strategy's learning period — a small,
    evidence-backed set — so an ordinary read or a rename appends nothing. An
    UNKNOWN verdict appends nothing either: it would fire on every mutation of
    every platform mureo has no trigger list for, and a notice that always
    fires is a notice nobody reads (the pre-flight tool still reports UNKNOWN
    honestly when asked).

    This runs AFTER the call, so for the call it rides on it is a record, not
    a veto — MCP gives mureo no interposed confirmation step. What it buys is
    the NEXT change in a troubleshooting sequence: the agent now knows the
    campaign has just re-entered learning. The before-the-change surfaces are
    ``mureo_learning_reset_preflight`` and the ``## Guardrails`` refusal.

    Best-effort and never raises: a notice must not break a tool call.
    """
    try:
        from mcp.types import TextContent

        from mureo.policy.learning_reset import load_preflight, preflight_notice

        notice = preflight_notice(load_preflight(name, arguments))
        if notice is None:
            return result
        return [*result, TextContent(type="text", text=notice)]
    except Exception:  # noqa: BLE001 — never let a notice break a tool call
        logger.debug("learning-reset notice failed for %r", name, exc_info=True)
        return result
