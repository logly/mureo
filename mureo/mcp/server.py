"""mureo MCP server

Exposes Google Ads / Meta Ads / Search Console tools via the MCP protocol.
Invoked over stdio by MCP clients such as Claude Code or Cursor.

Tool definitions and handlers are separated into per-service modules
(tools_google_ads.py, tools_meta_ads.py, tools_search_console.py).

Per-platform tool families can be disabled at server-startup time by
setting one of the following process env vars to the exact string ``"1"``
before launching the server (typically written by ``mureo providers add
<official-id>`` into ``mcpServers.mureo.env``):

- ``MUREO_DISABLE_GOOGLE_ADS`` — skip the ``google_ads_*`` tool family.
- ``MUREO_DISABLE_META_ADS`` — skip the ``meta_ads_*`` tool family.
- ``MUREO_DISABLE_GA4`` — wired in for forward-compat (no-op today; mureo
  ships no native GA4 tools yet).

The env vars are read **once at module import time**; the server starts
once per process and the gate is a startup decision. Search Console is
*always* registered regardless of env-var combinations — mureo is
canonical for SC because no official MCP exists.

The comparison is exact-string ``== "1"`` — any other value (``"0"``,
``""``, ``"true"``, ``"  1  "``) leaves tools enabled. Do not loosen this
comparison; multiple tests pin the contract.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema
from jsonschema import Draft202012Validator
from mcp.server import Server
from mcp.server.stdio import stdio_server

if TYPE_CHECKING:
    from mcp.types import Tool

    from mureo.core.policy import PolicyDecision, PolicyGate
    from mureo.mcp.tool_provider import MCPToolProvider

from mureo.mcp._helpers import is_error_result
from mureo.mcp.native_reversal import capture_before_state, record_native_mutation
from mureo.mcp.plugin_audit import record_plugin_call
from mureo.mcp.plugin_semantics import (
    ToolSemantics,
    derive_semantics,
    record_mutation_action_log,
)
from mureo.mcp.tool_provider import (
    MCPReversibleToolProvider,
    collect_plugin_tools,
    plugin_source,
)
from mureo.mcp.tools_analysis import TOOLS as ANALYSIS_TOOLS
from mureo.mcp.tools_analysis import handle_tool as handle_analysis_tool
from mureo.mcp.tools_analytics_registry import (
    TOOLS as ANALYTICS_REGISTRY_TOOLS,
)
from mureo.mcp.tools_analytics_registry import (
    handle_tool as handle_analytics_registry_tool,
)
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_google_ads import handle_tool as handle_google_ads_tool
from mureo.mcp.tools_learning import TOOLS as LEARNING_TOOLS
from mureo.mcp.tools_learning import handle_tool as handle_learning_tool
from mureo.mcp.tools_meta_ads import TOOLS as META_ADS_TOOLS
from mureo.mcp.tools_meta_ads import handle_tool as handle_meta_ads_tool
from mureo.mcp.tools_mureo_context import TOOLS as MUREO_CONTEXT_TOOLS
from mureo.mcp.tools_mureo_context import handle_tool as handle_mureo_context_tool
from mureo.mcp.tools_rollback import TOOLS as ROLLBACK_TOOLS
from mureo.mcp.tools_rollback import handle_tool as handle_rollback_tool
from mureo.mcp.tools_search_console import TOOLS as SEARCH_CONSOLE_TOOLS
from mureo.mcp.tools_search_console import handle_tool as handle_search_console_tool
from mureo.rollback.executor import is_rollback_dispatch_active
from mureo.throttle import PLUGIN_THROTTLE, Throttler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Env-var gating (read once at module import time — see module docstring)
# ---------------------------------------------------------------------------


def _is_disabled(env_var: str) -> bool:
    """Return True iff the env var equals the exact string ``"1"``.

    Exact-string comparison is intentional — see module docstring. Do NOT
    loosen this to ``bool(...)`` or ``strip().lower() == "1"``; the
    contract is locked in by ``test_truthy_coercion_does_not_disable``.
    """
    return os.environ.get(env_var) == "1"


_GOOGLE_ADS_ENABLED = not _is_disabled("MUREO_DISABLE_GOOGLE_ADS")
_META_ADS_ENABLED = not _is_disabled("MUREO_DISABLE_META_ADS")
# GA4 flag is wired in for forward-compat symmetry; mureo ships no native
# GA4 tools today, so the flag does not currently gate anything. Once GA4
# tools land in mureo, add a ``GA4_TOOLS`` import + ``_GA4_NAMES`` block
# below and the gate becomes operational automatically.
_GA4_ENABLED = not _is_disabled("MUREO_DISABLE_GA4")  # noqa: F841


# ---------------------------------------------------------------------------
# Combined tool list — built conditionally based on env-var gates above.
# ``MUREO_DISABLE_SEARCH_CONSOLE`` is deliberately NOT honored — mureo is
# canonical for Search Console (no official MCP equivalent exists).
# ---------------------------------------------------------------------------

_ALL_TOOLS: list[Tool] = [
    *(GOOGLE_ADS_TOOLS if _GOOGLE_ADS_ENABLED else []),
    *(META_ADS_TOOLS if _META_ADS_ENABLED else []),
    *SEARCH_CONSOLE_TOOLS,
    *ROLLBACK_TOOLS,
    *ANALYSIS_TOOLS,
    *MUREO_CONTEXT_TOOLS,
    *ANALYTICS_REGISTRY_TOOLS,
    *LEARNING_TOOLS,
]
_GOOGLE_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in GOOGLE_ADS_TOOLS) if _GOOGLE_ADS_ENABLED else frozenset()
)
_META_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in META_ADS_TOOLS) if _META_ADS_ENABLED else frozenset()
)
_SEARCH_CONSOLE_NAMES: frozenset[str] = frozenset(t.name for t in SEARCH_CONSOLE_TOOLS)
_ROLLBACK_NAMES: frozenset[str] = frozenset(t.name for t in ROLLBACK_TOOLS)
_ANALYSIS_NAMES: frozenset[str] = frozenset(t.name for t in ANALYSIS_TOOLS)
_MUREO_CONTEXT_NAMES: frozenset[str] = frozenset(t.name for t in MUREO_CONTEXT_TOOLS)
_ANALYTICS_REGISTRY_NAMES: frozenset[str] = frozenset(
    t.name for t in ANALYTICS_REGISTRY_TOOLS
)
_LEARNING_NAMES: frozenset[str] = frozenset(t.name for t in LEARNING_TOOLS)

# ---------------------------------------------------------------------------
# Third-party plugin tools (entry-point–discovered providers implementing
# MCPToolProvider). Purely additive: built-in platforms keep their static
# TOOLS and are NOT routed here, so there is no double-exposure. If no
# plugins are installed this is a no-op and behaviour is byte-identical to
# before. Built-in tool names are reserved so a plugin can never shadow a
# core tool. Discovery faults are contained (PluginToolWarning), never fatal.
# ---------------------------------------------------------------------------
_PLUGIN_TOOLS: list[Tool]
_PLUGIN_DISPATCH: dict[str, MCPToolProvider]
_PLUGIN_TOOLS, _PLUGIN_DISPATCH = collect_plugin_tools(
    reserved_names=(
        _GOOGLE_ADS_NAMES
        | _META_ADS_NAMES
        | _SEARCH_CONSOLE_NAMES
        | _ROLLBACK_NAMES
        | _ANALYSIS_NAMES
        | _MUREO_CONTEXT_NAMES
        | _ANALYTICS_REGISTRY_NAMES
        | _LEARNING_NAMES
    ),
)
_ALL_TOOLS.extend(_PLUGIN_TOOLS)
_PLUGIN_NAMES: frozenset[str] = frozenset(_PLUGIN_DISPATCH)


# Pre-compiled JSON Schema validators for every tool, keyed by tool name.
# The MCP framework does not enforce ``inputSchema``, so declared bounds
# (``minimum``, ``required``, ``type``, ``enum``) are advisory until checked
# server-side. Validating here is the single guard that makes them real for
# every mutation — most importantly the real-spend boundary values
# (budget / bid ``minimum: 1``) flagged in issue #277.
#
# Plugin tools are validated here too (guardrail parity, #114 follow-up): a
# plugin that declares ``minimum``/``required``/``enum`` on a real-spend
# parameter now has those bounds enforced server-side, exactly like a
# built-in, instead of relying on the (unverifiable) assumption that every
# provider validates its own inputs. A plugin whose schema is permissive
# (no constraints, ``additionalProperties`` open) is unaffected — the
# validator simply finds nothing to reject. A malformed plugin schema is
# skipped per-tool below, same as a malformed built-in schema.
def _build_tool_validators() -> dict[str, Draft202012Validator]:
    validators: dict[str, Draft202012Validator] = {}
    for tool in _ALL_TOOLS:
        schema = getattr(tool, "inputSchema", None)
        if not isinstance(schema, dict):
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as exc:
            # A malformed built-in schema must not take the whole server
            # offline — skip validation for that one tool and log it.
            logger.warning(
                "tool %s: inputSchema is not a valid JSON Schema (%s); "
                "input validation skipped for it",
                tool.name,
                exc,
            )
            continue
        validators[tool.name] = Draft202012Validator(schema)
    return validators


_TOOL_VALIDATORS: dict[str, Draft202012Validator] = _build_tool_validators()


def _validate_tool_input(name: str, arguments: dict[str, Any]) -> None:
    """Validate ``arguments`` against the tool's declared ``inputSchema``.

    Raises ``ValueError`` (the dispatcher's standard caller-error channel)
    on the first violation, before the tool handler runs — so an invalid
    budget/bid never reaches a real-spend API call. Applies to both built-in
    and plugin tools. No-op for a tool without a registered validator (no
    schema, or a schema that failed ``check_schema`` at build time).
    """
    validator = _TOOL_VALIDATORS.get(name)
    if validator is None:
        return
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    if not errors:
        return
    first = errors[0]
    location = "/".join(str(p) for p in first.path) or "(root)"
    raise ValueError(f"Invalid arguments for {name}: at '{location}': {first.message}")


# One conservative shared bucket for all plugin tool calls. Built-in
# platforms keep their own per-platform throttlers; this only gates the
# plugin dispatch branch.
#
# Kept as a module-level attribute because (a) existing tests
# monkey-patch it directly to inject a spy throttler and (b) the lazy
# seeding helper below copies its instance into the resolved
# :class:`ProcessLocalThrottleStore` so the same bucket is observed
# regardless of which path enters the dispatcher.
_PLUGIN_THROTTLER = Throttler(PLUGIN_THROTTLE)

# Phase 2 (#114): per-tool safety semantics derived from STANDARD MCP
# metadata (annotations.readOnlyHint + optional meta["mureo"]). No new
# ABI surface. A declared throttle hint gets its own bucket; everything
# else shares _PLUGIN_THROTTLER. Undeclared ⇒ mutating (conservative).
_PLUGIN_SEMANTICS: dict[str, ToolSemantics] = {
    t.name: derive_semantics(t) for t in _PLUGIN_TOOLS
}
_PLUGIN_TOOL_THROTTLERS: dict[str, Throttler] = {
    name: Throttler(sem.throttle)
    for name, sem in _PLUGIN_SEMANTICS.items()
    if sem.throttle is not None
}


# Guardrail parity (#114 follow-up): top-level ``inputSchema`` property names
# per plugin tool. The rollback planner uses these to bound the params a
# plugin-declared reversal may carry — the plugin counterpart of the static
# ``_ALLOWED_OPERATIONS`` key-sets the planner enforces for built-in reversals.
def _plugin_schema_property_keys(tool: Tool) -> frozenset[str] | None:
    """Return the declared top-level object property names of ``tool``'s
    ``inputSchema``, or ``None`` when the schema is absent or declares no
    usable ``properties`` map (so the planner applies no key restriction
    and leaves the bound to execution-time validation)."""
    schema = getattr(tool, "inputSchema", None)
    if not isinstance(schema, dict):
        return None
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return None
    return frozenset(props)


_PLUGIN_REVERSAL_KEYS: dict[str, frozenset[str] | None] = {
    t.name: _plugin_schema_property_keys(t) for t in _PLUGIN_TOOLS
}


def plugin_reversal_param_keys(operation: str) -> tuple[bool, frozenset[str] | None]:
    """Resolve a plugin reversal operation for the rollback planner (GAP C).

    The planner calls this (lazily, to avoid an import cycle) when a reversal
    ``operation`` is not in its static built-in allow-list, to decide whether
    a plugin-declared reversal is executable.

    Returns:
        ``(False, None)`` when ``operation`` is not a registered plugin tool
        — the planner then refuses it exactly as before (an arbitrary,
        unregistered operation is never auto-reversible).

        ``(True, frozenset(keys))`` when ``operation`` is a registered plugin
        tool that declares an object ``inputSchema`` — the planner bounds the
        reversal params to ``keys`` (defense-in-depth against an injected
        agent smuggling extra params), mirroring the built-in key-set check.

        ``(True, None)`` when ``operation`` is a registered plugin tool with
        no usable schema — the planner applies no plan-time key restriction.
        The reversal is still gated by the planner's destructive-verb refusal,
        and at execution the dispatcher re-runs policy gates + ``inputSchema``
        validation against the live tool, so an unbounded plan cannot bypass
        the forward-action guardrails.
    """
    if operation not in _PLUGIN_NAMES:
        return (False, None)
    return (True, _PLUGIN_REVERSAL_KEYS.get(operation))


# ---------------------------------------------------------------------------
# Throttle dispatch — bridge legacy module state to the RuntimeContext
# throttle_store so an alternate backend (registered via
# ``mureo.runtime_context_factory``) can take over without each handler
# having to know about it.
# ---------------------------------------------------------------------------


# Sentinel key for the "everything else" bucket installed alongside the
# per-tool buckets when seeding a default ``ProcessLocalThrottleStore``.
# Kept as a module-level constant so the seeding helper and the
# unknown-name fallback both reference the same string.
_PLUGIN_DEFAULT_BUCKET = "__plugin_default__"

# Set of ``id()``s of ``ProcessLocalThrottleStore`` instances we have
# already seeded with the legacy ``_PLUGIN_TOOL_THROTTLERS`` configs.
# Idempotent: re-entry against a previously-seeded store is a no-op.
# Tests that monkey-patch ``_PLUGIN_THROTTLER`` or
# ``_PLUGIN_TOOL_THROTTLERS`` directly must clear this set AND call
# ``reset_runtime_context()`` so the next handler call re-seeds a
# freshly-resolved store with the patched throttlers.
_throttle_store_seeded: set[int] = set()


async def _acquire_plugin_throttle(name: str) -> None:
    """Acquire one throttle slot for plugin tool ``name``.

    Routes through ``get_runtime_context().throttle_store`` so an
    alternate backend can intercept the call. For the default
    file-backed runtime the throttle_store is a
    :class:`ProcessLocalThrottleStore`; this function lazily seeds it
    with the per-tool ``Throttler`` instances built at module load,
    preserving today's per-name bucket semantics. The fallback bucket
    for unknown names is the store's ``default_config`` (=
    ``PLUGIN_THROTTLE`` for the default runtime).

    The legacy ``_PLUGIN_THROTTLER`` / ``_PLUGIN_TOOL_THROTTLERS``
    module attributes are still consulted: tests that monkey-patch
    them continue to observe their spy being invoked, because the
    seeded ``ProcessLocalThrottleStore`` uses those exact instances.

    Alternate backends (non-``ProcessLocalThrottleStore`` returned by a
    ``mureo.runtime_context_factory`` entry-point) receive a single
    ``acquire(name)`` call and own the full per-key + unknown-name
    fallback semantics themselves. The seeding step above is
    deliberately skipped for them: this Protocol exposes only
    ``acquire``, so a backend that wants the "unknown name → shared
    default bucket" behaviour must implement it internally.
    """
    # Lazy import to avoid an import cycle: ``mureo.core.runtime_context``
    # is free to reference MCP types in future without circling back to
    # this module via the top-level import graph.
    from mureo.core.runtime_context import get_runtime_context
    from mureo.core.throttle_store import ProcessLocalThrottleStore

    store = get_runtime_context().throttle_store
    if isinstance(store, ProcessLocalThrottleStore):
        ident = id(store)
        if ident not in _throttle_store_seeded:
            # Install per-tool buckets first.
            for tname, throttler in _PLUGIN_TOOL_THROTTLERS.items():
                store.throttlers.setdefault(tname, throttler)
            # And the conservative fallback bucket for unknown names.
            # We DO NOT call store.register() here because that would
            # rebuild a fresh Throttler from default_config; reusing
            # ``_PLUGIN_THROTTLER`` keeps the singleton state (token
            # bucket) coherent across the legacy and RuntimeContext
            # paths.
            store.throttlers.setdefault(_PLUGIN_DEFAULT_BUCKET, _PLUGIN_THROTTLER)
            _throttle_store_seeded.add(ident)
        # Unknown names go through the default bucket. Resolve here
        # because the Protocol does not expose "give me the throttler
        # for this key" — only acquire(key) — and we want the named
        # bucket for known names but the SHARED bucket for unknown.
        if name not in _PLUGIN_TOOL_THROTTLERS:
            await store.throttlers[_PLUGIN_DEFAULT_BUCKET].acquire()
            return
    await store.acquire(name)


# ---------------------------------------------------------------------------
# Handlers (defined as module-level functions so tests can call them directly)
# ---------------------------------------------------------------------------


async def handle_list_tools() -> list[Any]:
    """Return the list of registered tools."""
    return list(_ALL_TOOLS)


def _policy_gate_entry_points() -> tuple[Any, ...]:
    """Return the entry points registered under
    ``mureo.policy_gates``. Isolated so the unit tests can patch this
    without monkeypatching ``importlib.metadata``."""
    from importlib.metadata import entry_points

    from mureo.core.policy import POLICY_GATES_ENTRY_POINT_GROUP

    try:
        eps = entry_points(group=POLICY_GATES_ENTRY_POINT_GROUP)
    except Exception as exc:  # noqa: BLE001
        # importlib.metadata blowing up is rare but possible on weird
        # environments (unusual install layout, corrupted metadata).
        # Log so operators have a signal rather than silently treating
        # the situation as "no gates registered".
        logger.warning(
            "policy gates: importlib.metadata.entry_points failed (%s); "
            "treating as zero gates registered",
            exc,
        )
        return ()
    return tuple(eps)


def _load_policy_gates() -> tuple[PolicyGate, ...]:
    """Load and instantiate every gate declared under the
    ``mureo.policy_gates`` entry-point group.

    Per-entry-point exception isolation: a broken third-party
    package (partial install, import error) MUST NOT take mureo
    offline. The failing entry is dropped with a WARNING and the
    rest still load.
    """
    gates: list[PolicyGate] = []
    for ep in _policy_gate_entry_points():
        try:
            cls = ep.load()
            instance = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "policy gate '%s' failed to load (%s); skipping",
                getattr(ep, "name", "?"),
                exc,
            )
            continue
        gates.append(instance)
    return tuple(gates)


def _builtin_policy_gates() -> tuple[PolicyGate, ...]:
    """mureo's own gates, shipped in OSS and active by default.

    Unlike :func:`_load_policy_gates` (third-party gates via the
    ``mureo.policy_gates`` entry-point group), these are built in —
    strategy enforcement is core mureo value, not a plugin add-on. Kept
    separate from ``_load_policy_gates`` so that function's "entry-point
    gates only" contract (and its tests) stay unchanged. Each built-in gate
    is fail-open: it abstains (allows) whenever no rule applies.
    """
    from mureo.policy.strategy_gate import StrategyPolicyGate

    return (StrategyPolicyGate(),)


def _evaluate_policy_gates(
    name: str, arguments: dict[str, Any]
) -> PolicyDecision | None:
    """Run every gate — built-in then third-party. Returns the first deny
    decision, or ``None`` if every gate allowed (or abstained on exception).

    Calls :func:`_load_policy_gates` on every dispatch rather than
    caching at module-import time so a (rare) at-runtime
    install/uninstall of a third-party gate is picked up without a
    server restart. ``importlib.metadata.entry_points`` is itself
    cached internally, so the per-call cost is microseconds.
    """
    # Lazy-imported so the type is available for the isinstance guard
    # without re-introducing the runtime import at module top (it lives
    # under TYPE_CHECKING for the rest of this module).
    from mureo.core.policy import PolicyDecision as _PolicyDecision

    for gate in (*_builtin_policy_gates(), *_load_policy_gates()):
        try:
            decision = gate.evaluate(name, arguments)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "policy gate %r raised on '%s' (%s); abstain",
                type(gate).__name__,
                name,
                exc,
            )
            continue
        # Protocol violation guard: a buggy gate that returns None /
        # True / a tuple / dict / etc. would crash the dispatcher
        # downstream (AttributeError on `.allowed` or `.reason`).
        # Treat any non-PolicyDecision return as a buggy abstain so
        # one broken gate cannot take mureo offline — the exact same
        # discipline as the per-call exception isolation above.
        if not isinstance(decision, _PolicyDecision):
            logger.warning(
                "policy gate %r returned %r (not PolicyDecision) on '%s'; " "abstain",
                type(gate).__name__,
                type(decision).__name__,
                name,
            )
            continue
        if not decision.allowed:
            return decision
    return None


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
    cwd to record into (so we skip the read entirely), when the call raises, or
    when the returned value is not a well-formed ``{operation: str, params:
    dict}``. Never raises — a capture failure must not block the mutation.
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
    except KeyboardInterrupt:
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


# Once-per-process latch: the stale-version banner is appended to the first
# tool result that detects the mismatch, not every call (avoid spamming a
# read-heavy daily-check). A fresh process after restart starts False again.
_staleness_warned = False


def _maybe_append_staleness_warning(result: list[Any]) -> list[Any]:
    """Append a one-time restart warning when this MCP process is older than
    the mureo installed on disk.

    Push, not pull: the agent receives the warning in normal tool output and
    never has to ask for a version. No-op once warned this process, or when the
    running version is current. Best-effort — never raises, never replaces the
    tool's own content. See :mod:`mureo.core.version_staleness`.
    """
    global _staleness_warned
    if _staleness_warned:
        return result
    try:
        from mureo.core.version_staleness import staleness_warning

        warning = staleness_warning()
        if warning is None:
            return result
        _staleness_warned = True
        logger.warning("%s", warning)
        from mcp.types import TextContent

        return [*result, TextContent(type="text", text=warning)]
    except Exception:  # noqa: BLE001 - a version check must never break a tool call
        logger.debug("staleness warning check failed", exc_info=True)
        return result


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Execute a tool and return the result.

    Before dispatch, every policy gate is consulted — mureo's built-in
    gate(s) (:func:`_builtin_policy_gates`, e.g. the STRATEGY.md
    guardrail gate) first, then any gate registered under the
    ``mureo.policy_gates`` entry-point group. If any gate denies the
    call, a TextContent refusal is returned and the handler is never
    invoked. See :mod:`mureo.core.policy`.

    After successful dispatch of a built-in *mutating* tool, a
    STRATEGY.md reminder TextContent block is appended to the result
    so the agent re-surfaces the operator's declared strategy after
    every mutation. Soft enforcement only — never refuses. See
    :mod:`mureo.core.strategy_reminder`.

    Raises:
        ValueError: Unknown tool name, schema-invalid arguments, or a
            missing required parameter.
    """
    decision = _evaluate_policy_gates(name, arguments)
    if decision is not None:
        return _refuse_text_content(name, decision)
    # Schema-validate AFTER the gate decision (a policy denial is absolute and
    # need not depend on arg validity) but BEFORE any handler, before-state
    # capture, or real-spend API call — so an out-of-bounds budget/bid is
    # rejected before it can reach a live campaign.
    _validate_tool_input(name, arguments)
    result = await _dispatch_tool(name, arguments)
    # Push, not pull: if this MCP process is older than the mureo installed on
    # disk (operator upgraded but did not fully restart Claude), append a
    # one-time restart warning so the agent surfaces it WITHOUT having to ask
    # for a version. See :mod:`mureo.core.version_staleness`.
    return _maybe_append_staleness_warning(result)


async def _dispatch_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    """Route an already-gated, already-validated tool call to its handler.

    Built-in tool families append their STRATEGY.md reminder per-branch; the
    process-level staleness warning is applied once by the caller around the
    whole result.
    """
    # When this dispatch is the reversal leg of a rollback, executor.py appends
    # the single authoritative rollback_of entry; skip the native recording so
    # the reversal is not double-logged as a fresh reversible mutation.
    record_mutations = not is_rollback_dispatch_active()
    if name in _GOOGLE_ADS_NAMES:
        before = await capture_before_state(name, arguments)
        result = await handle_google_ads_tool(name, arguments)
        if record_mutations:
            record_native_mutation(name, arguments, before, result)
        return _maybe_append_strategy_reminder(name, result)
    if name in _META_ADS_NAMES:
        before = await capture_before_state(name, arguments)
        result = await handle_meta_ads_tool(name, arguments)
        if record_mutations:
            record_native_mutation(name, arguments, before, result)
        return _maybe_append_strategy_reminder(name, result)
    if name in _SEARCH_CONSOLE_NAMES:
        return _maybe_append_strategy_reminder(
            name, await handle_search_console_tool(name, arguments)
        )
    if name in _ROLLBACK_NAMES:
        return _maybe_append_strategy_reminder(
            name, await handle_rollback_tool(name, arguments)
        )
    if name in _ANALYSIS_NAMES:
        return await handle_analysis_tool(name, arguments)
    if name in _MUREO_CONTEXT_NAMES:
        return _maybe_append_strategy_reminder(
            name, await handle_mureo_context_tool(name, arguments)
        )
    if name in _ANALYTICS_REGISTRY_NAMES:
        return await handle_analytics_registry_tool(name, arguments)
    if name in _LEARNING_NAMES:
        return await handle_learning_tool(name, arguments)
    if name in _PLUGIN_NAMES:
        provider = _PLUGIN_DISPATCH[name]
        source = plugin_source(provider)
        sem = _PLUGIN_SEMANTICS.get(name)
        # Capture a runtime-correct reversal BEFORE the mutation (#327),
        # mirroring the native before-state capture: an opted-in provider reads
        # the entity's prior state and returns a reversal carrying the actual
        # id + prior value. Only for mutating tools; best-effort, never blocks.
        captured_reversal: dict[str, Any] | None = None
        if sem is None or sem.mutating:
            captured_reversal = await _capture_plugin_reversal(
                provider, name, arguments
            )
        await _acquire_plugin_throttle(name)
        try:
            result = await provider.handle_mcp_tool(name, arguments)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # noqa: BLE001
            # Record the failed call, then re-raise unchanged so the MCP
            # framework surfaces a clean tool error exactly as before
            # (no server crash, no silently-swallowed error).
            record_plugin_call(
                tool=name,
                arguments=arguments,
                source=source,
                ok=False,
                error=repr(exc),
            )
            raise
        record_plugin_call(tool=name, arguments=arguments, source=source, ok=True)
        # Phase 2: promote a *successful mutating* call into STATE.json's
        # action_log (only when a STATE.json exists in cwd) so the agent
        # / strategy review / rollback can see it like a built-in op.
        # Read-only tools stay in the jsonl audit only (no STATE bloat).
        if sem is None or sem.mutating:
            # Skip the action_log promotion when the plugin returned an
            # api_error_handler-style error envelope WITHOUT raising — the
            # mutation did not change platform state, so promoting it would
            # log a phantom action (and, via a declared reversal, leave a
            # phantom executable rollback). Mirrors native_reversal's
            # _is_error_result skip for built-in mutations. The jsonl audit
            # (above) still captures the attempt regardless.
            if record_mutations and not is_error_result(result):
                # Prefer the runtime-correct reversal captured before the
                # mutation; fall back to the provider's static meta reversal
                # when it did not opt into capture_reversal (#327).
                reversal = (
                    captured_reversal
                    if captured_reversal is not None
                    else (None if sem is None else sem.reversal)
                )
                record_mutation_action_log(
                    tool=name,
                    source=source,
                    reversal=reversal,
                    observation_days=None if sem is None else sem.observation_days,
                )
            # Guardrail parity: a mutating plugin call re-surfaces the
            # operator's STRATEGY.md sections, exactly like a built-in
            # mutation — appended regardless of the result envelope, matching
            # the built-in dispatch. Read-only plugin tools skip it.
            result = _maybe_append_plugin_strategy_reminder(name, result)
        return result
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# MCP server setup & entry point
# ---------------------------------------------------------------------------


def _create_server() -> Server:
    """Create an MCP Server instance and register handlers."""
    server = Server("mureo")

    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator, unused-ignore]
    async def list_tools() -> list[Any]:
        return await handle_list_tools()

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
        return await handle_call_tool(name, arguments)

    return server


async def main() -> None:
    """Start the MCP server over stdio."""
    server = _create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
