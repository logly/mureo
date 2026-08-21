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
- ``MUREO_DISABLE_CREATIVE_STUDIO`` — skip the ``creative_studio_*`` tool
  family (image-generation providers + visual generation).
- ``MUREO_DISABLE_AMAZON_ADS`` — do not register the in-tree Amazon Ads
  bridge, so none of its manifest tools are exposed (see
  ``mureo.amazon_ads.provider.amazon_ads_disabled``).

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
    from collections.abc import Callable

    from mcp.types import Tool

    from mureo.core.policy import PolicyDecision, PolicyGate
    from mureo.mcp.tool_provider import MCPToolProvider

from mureo.core.control_flow import STOP_EXCEPTIONS
from mureo.core.strategy_reminder import is_mutating_builtin_tool
from mureo.mcp._helpers import is_error_result
from mureo.mcp.exclusion_preflight import (
    append_notice as append_exclusion_impact_notice,
)
from mureo.mcp.exclusion_preflight import (
    exclusion_impact_preflight,
)
from mureo.mcp.exclusion_preflight import (
    refusal_content as exclusion_refusal_content,
)
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
    plugin_provider_name,
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
from mureo.mcp.tools_batch import TOOLS as BATCH_TOOLS
from mureo.mcp.tools_batch import handle_tool as handle_batch_tool
from mureo.mcp.tools_change_import import TOOLS as CHANGE_IMPORT_TOOLS
from mureo.mcp.tools_change_import import handle_tool as handle_change_import_tool
from mureo.mcp.tools_creative_studio import TOOLS as CREATIVE_STUDIO_TOOLS
from mureo.mcp.tools_creative_studio import (
    handle_tool as handle_creative_studio_tool,
)
from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_ADS_TOOLS
from mureo.mcp.tools_google_ads import handle_tool as handle_google_ads_tool
from mureo.mcp.tools_learning import TOOLS as LEARNING_TOOLS
from mureo.mcp.tools_learning import handle_tool as handle_learning_tool
from mureo.mcp.tools_learning_preflight import TOOLS as LEARNING_PREFLIGHT_TOOLS
from mureo.mcp.tools_learning_preflight import (
    handle_tool as handle_learning_preflight_tool,
)
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
_CREATIVE_STUDIO_ENABLED = not _is_disabled("MUREO_DISABLE_CREATIVE_STUDIO")


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
    *BATCH_TOOLS,
    *CHANGE_IMPORT_TOOLS,
    *ANALYSIS_TOOLS,
    *MUREO_CONTEXT_TOOLS,
    *ANALYTICS_REGISTRY_TOOLS,
    *LEARNING_TOOLS,
    *LEARNING_PREFLIGHT_TOOLS,
    *(CREATIVE_STUDIO_TOOLS if _CREATIVE_STUDIO_ENABLED else []),
]
_GOOGLE_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in GOOGLE_ADS_TOOLS) if _GOOGLE_ADS_ENABLED else frozenset()
)
_META_ADS_NAMES: frozenset[str] = (
    frozenset(t.name for t in META_ADS_TOOLS) if _META_ADS_ENABLED else frozenset()
)
_SEARCH_CONSOLE_NAMES: frozenset[str] = frozenset(t.name for t in SEARCH_CONSOLE_TOOLS)
_ROLLBACK_NAMES: frozenset[str] = frozenset(t.name for t in ROLLBACK_TOOLS)
_BATCH_NAMES: frozenset[str] = frozenset(t.name for t in BATCH_TOOLS)
_CHANGE_IMPORT_NAMES: frozenset[str] = frozenset(t.name for t in CHANGE_IMPORT_TOOLS)
_ANALYSIS_NAMES: frozenset[str] = frozenset(t.name for t in ANALYSIS_TOOLS)
_MUREO_CONTEXT_NAMES: frozenset[str] = frozenset(t.name for t in MUREO_CONTEXT_TOOLS)
_ANALYTICS_REGISTRY_NAMES: frozenset[str] = frozenset(
    t.name for t in ANALYTICS_REGISTRY_TOOLS
)
_LEARNING_NAMES: frozenset[str] = frozenset(t.name for t in LEARNING_TOOLS)
_LEARNING_PREFLIGHT_NAMES: frozenset[str] = frozenset(
    t.name for t in LEARNING_PREFLIGHT_TOOLS
)
_CREATIVE_STUDIO_NAMES: frozenset[str] = (
    frozenset(t.name for t in CREATIVE_STUDIO_TOOLS)
    if _CREATIVE_STUDIO_ENABLED
    else frozenset()
)

#: Every tool name mureo itself serves, derived from ``_ALL_TOOLS`` while it
#: still holds only built-ins — plugin tools are appended further down. This
#: is what a plugin may not claim (``reserved_names`` below).
#:
#: Derived, not hand-written (#680): the previous hand-maintained union of the
#: per-family name sets was a second answer to "which names are built-in" and
#: had silently fallen one family behind ``_ALL_TOOLS``, leaving
#: ``mureo_learning_reset_preflight`` claimable by a plugin. Anything added to
#: ``_ALL_TOOLS`` above is now reserved the moment it is served.
_BUILTIN_NAMES: frozenset[str] = frozenset(t.name for t in _ALL_TOOLS)


# ---------------------------------------------------------------------------
# Third-party plugin tools (entry-point–discovered providers implementing
# MCPToolProvider). Purely additive: built-in platforms keep their static
# TOOLS and are NOT routed here, so there is no double-exposure. If no
# plugins are installed this is a no-op and behaviour is byte-identical to
# before. Built-in tool names are reserved so a plugin can never shadow a
# core tool. Discovery faults are contained (PluginToolWarning), never fatal.
# ---------------------------------------------------------------------------
def _discover_with_amazon() -> tuple[Any, ...]:
    """Registry-discovered entry-point providers PLUS the internal
    Amazon Ads bridge (#113).

    The Amazon bridge is in-tree (not an entry point), but it satisfies
    the same ``MCPToolProvider`` shape, so feeding it through the
    SAME collection makes it inherit the #114 safety layer (audit /
    throttle / Phase 2/4 strategy promotion) with zero dispatch
    changes. ``registry.discover_providers`` is resolved live here so a
    monkeypatched registry / module reload is still honoured. When the
    Amazon manifest is absent, ``AmazonAdsBridge.mcp_tools()`` returns
    ``()`` → no tools added → behaviour is byte-identical to before.

    #121: the entry is now built AND registered by
    ``mureo.amazon_ads.provider`` — one definition shared with the
    ``mureo configure`` UI, which needs it in ``default_registry`` to
    render the Amazon credentials card. ``discover_providers`` returns
    only what the entry-point pass registered, so the registration does
    not by itself put Amazon in ``entries``; the explicit append below
    is still what exposes the tools, guarded so an ``amazon_ads`` entry
    point (were one ever installed) cannot double-expose them.

    ORDER MATTERS: the built-in is registered BEFORE entry-point
    discovery, matching ``ConfigureWizard._discover_providers_safely``.
    The registry is first-wins, so registering first is what makes the
    in-tree bridge deterministically beat a third-party plugin that
    claims the ``amazon_ads`` name — in both processes, not just
    whichever happened to run its registration earlier. A genuinely
    pre-registered foreign ``amazon_ads`` (registered before this
    function runs at all) still wins, which is the documented
    first-wins contract.
    """
    from mureo.amazon_ads.provider import amazon_ads_disabled, register_amazon_provider
    from mureo.core.providers import registry as _registry

    if amazon_ads_disabled():
        # ``MUREO_DISABLE_AMAZON_ADS=1`` — the bridge is neither registered nor
        # appended, so no Amazon tools are exposed AND the configure UI does
        # not render a card for a bridge this server will not serve. A
        # third-party ``amazon_ads`` entry point (were one installed) is left
        # to discovery, exactly as the other MUREO_DISABLE_* gates leave the
        # official MCP they step aside for.
        return tuple(_registry.discover_providers())

    amazon = register_amazon_provider()
    entries = list(_registry.discover_providers())
    if not any(entry.name == amazon.name for entry in entries):
        entries.append(amazon)
    return tuple(entries)


_PLUGIN_TOOLS: list[Tool]
_PLUGIN_DISPATCH: dict[str, MCPToolProvider]
_PLUGIN_TOOLS, _PLUGIN_DISPATCH = collect_plugin_tools(
    reserved_names=_BUILTIN_NAMES,
    discover=_discover_with_amazon,
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
#
# Keyed by BARE tool name, and that is safe rather than lucky (#589):
# ``collect_plugin_tools`` already dedupes tool names first-wins, dropping the
# duplicate from BOTH ``_PLUGIN_TOOLS`` and ``_PLUGIN_DISPATCH`` and naming the
# two distributions involved. So this map — and the three declaration
# registries fed from it below — holds the semantics of the ONE tool that is
# actually dispatchable under that name. A second distribution's declaration
# can never be paired with a first distribution's tool, which is what re-keying
# by ``(distribution, name)`` would have bought; what identity is needed for is
# the *message*, and that is emitted where identity lives, at collection.
_PLUGIN_SEMANTICS: dict[str, ToolSemantics] = {
    t.name: derive_semantics(t) for t in _PLUGIN_TOOLS
}
_PLUGIN_TOOL_THROTTLERS: dict[str, Throttler] = {
    name: Throttler(sem.throttle)
    for name, sem in _PLUGIN_SEMANTICS.items()
    if sem.throttle is not None
}


def _register_plugin_budget_declarations(
    semantics: dict[str, ToolSemantics],
) -> None:
    """Publish plugin budget declarations to the StrategyPolicyGate (#414).

    The gate's built-in key scan only knows the Google/Meta argument
    spellings, so a plugin tool's budget was invisible to it — every
    ``## Guardrails`` cap was silently unenforced on that platform. A
    plugin now declares its keys in standard MCP metadata and this wires
    them into the gate's registry, so the ONE built-in gate enforces them
    (no per-plugin hand-rolled gate). Best-effort: a registry failure must
    not take the server down.
    """
    from mureo.policy.declarations import register_budget_declaration

    for name, sem in semantics.items():
        if sem.budget is None:
            continue
        try:
            register_budget_declaration(name, sem.budget)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register budget declaration for plugin tool '%s'",
                name,
                exc_info=True,
            )


def _register_plugin_bid_declarations(
    semantics: dict[str, ToolSemantics],
) -> None:
    """Publish plugin bid declarations to the StrategyPolicyGate.

    The bid twin of :func:`_register_plugin_budget_declarations`: the gate's
    built-in bid scan only knows the Meta/Google spellings, so a plugin bid
    tool's ``bid_amount`` / ``cpc_bid`` cap was silently unenforced. A plugin
    declares its keys in standard MCP metadata and this wires them into the
    gate's registry, so the ONE built-in gate enforces them. Best-effort: a
    registry failure must not take the server down.
    """
    from mureo.policy.declarations import register_bid_declaration

    for name, sem in semantics.items():
        if sem.bid is None:
            continue
        try:
            register_bid_declaration(name, sem.bid)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register bid declaration for plugin tool '%s'",
                name,
                exc_info=True,
            )


def _register_plugin_read_only_hints(
    semantics: dict[str, ToolSemantics],
) -> None:
    """Publish plugin ``readOnlyHint`` declarations to the pure policy layer.

    The learning-period pre-flight (:mod:`mureo.policy.learning_reset`) has to
    answer "is this call a mutation?" for a plugin/bridged tool too — a plugin
    or bridge can register its own learning rules under a ``tool_prefix``, so
    those names really do reach it. Without the declaration it had only the
    NAME to go on and was wrong in both directions: a read-shaped name that
    declares ``readOnlyHint=False`` got no learning-period notice and no
    ``block_learning_resets`` refusal, and a mutation-shaped name that
    declares ``readOnlyHint=True`` risked a spurious one. Only tools that
    actually declared a hint are registered — absence must stay "undeclared",
    never "read". Best-effort: a registry failure must not take the server
    down.
    """
    from mureo.policy.declarations import register_read_only_hint

    for name, sem in semantics.items():
        if sem.read_only_hint is None:
            continue
        try:
            register_read_only_hint(name, sem.read_only_hint)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register the readOnlyHint for plugin tool '%s'",
                name,
                exc_info=True,
            )


def _register_plugin_pattern_fallbacks(
    semantics: dict[str, ToolSemantics],
) -> None:
    """Mark MUTATING plugin tools for the gate's pattern fallback.

    The two registrations above only help a plugin that CAN declare. A bridged
    tool surface — someone else's tool definitions forwarded verbatim, e.g. from
    a manifest snapshot — carries no mureo ``_meta`` at all, so it declares
    nothing and every ``## Guardrails`` budget/bid cap was silently unenforced
    for its mutations. Registering the mutating tools here lets the gate fall
    back to the best-effort key-shape scan
    (:mod:`mureo.policy.pattern_scan`) for the channels no declaration covers.

    Reads are deliberately excluded — they move no money, so scanning their
    arguments could only produce false denials — and "read" is decided by
    DECLARATION first, NAME second: the same precedence
    :func:`~mureo.mcp.plugin_semantics.derive_semantics` itself uses, so the
    two surfaces cannot answer "is this a read?" differently.

    - ``annotations.readOnlyHint``, when the tool declares it. An explicit
      ``False`` is a plugin author saying "this moves money"; overturning it
      with a name guess silently dropped that tool's budget/bid cap, which is
      the one failure this ordering exists to prevent. A declaration is
      evidence, a name shape is a guess.
    - the tool NAME, via the shared read vocabulary in
      :mod:`mureo.core.tool_names`, single-sourced so the surfaces that use it
      cannot drift — consulted ONLY for a tool that declared nothing, which is
      the case the fallback was introduced for: a manifest snapshot carries no
      annotations at all, so a bridged read whose arguments carry a numeric
      budget-shaped FILTER would otherwise be refused outright. The error
      costs are asymmetric there: platform mutations are consistently
      verb-named (``create_`` / ``update_`` / ``delete_`` / ``set_``), so a
      read-shaped name is almost never a mutation, whereas a mutation-shaped
      name that is really a read costs only a wasted scan of arguments that
      carry no budget.

    The matcher here is the STRICT one, :func:`~mureo.core.tool_names.
    is_read_only_tool_name`, and that is deliberate. The rollback planner uses
    a looser sibling that also reads a verb at the END of a name, because
    mureo's own tools are named that way; this gate does not, because it
    decides about PLUGIN tools whose names mureo does not choose, and a
    mutation admitted here silently loses its ``## Guardrails`` cap. Do not
    "unify" the two — see that sibling's docstring for the argument.

    For semantics produced by ``derive_semantics`` the undeclared read-shaped
    case already arrives as ``mutating=False``, so the name check below is a
    belt-and-braces guard for any semantics map NOT built by that function
    rather than a load-bearing step on the normal path.

    Annotation coverage on a real bridged surface is known rather than assumed
    (#517): of 85 tools on one Amazon manifest, 83 declare ``readOnlyHint``
    and 2 omit it — good enough to lead with the declaration, not good enough
    to drop the name fallback.

    Best-effort: a registry failure must not take the server down.
    """
    from mureo.core.tool_names import is_read_only_tool_name
    from mureo.policy.pattern_scan import register_pattern_fallback_tool

    for name, sem in semantics.items():
        if not sem.mutating:
            continue
        # The name is a fallback, not an override: it decides only for a tool
        # that declared no readOnlyHint at all.
        if sem.read_only_hint is None and is_read_only_tool_name(name):
            continue
        try:
            register_pattern_fallback_tool(name)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register the guardrail pattern fallback for "
                "plugin tool '%s'",
                name,
                exc_info=True,
            )


def _declares_from_bridged_table(
    name: str,
    semantics: dict[str, ToolSemantics],
    dispatch: dict[str, MCPToolProvider],
) -> ToolSemantics | None:
    """``name``'s semantics when mureo's bridged table may declare it, else None.

    Three conditions, and the third is the one that matters. Tool names are
    keyed WITHOUT plugin identity everywhere in this module, and the Amazon
    manifest's names (``campaign_management-update_campaign``, …) are generic
    enough that another provider could plausibly ship the same string. Hanging
    exact money paths off a bare name would then point Amazon's schema at a
    different platform's arguments, so the owning distribution is checked
    against the tool's actual provider instance — the same breadcrumb the
    audit trail attributes calls with.
    """
    from mureo.amazon_ads.provider import AMAZON_SOURCE_DISTRIBUTION

    sem = semantics.get(name)
    if sem is None or not sem.mutating:
        return None
    if plugin_source(dispatch.get(name)) != AMAZON_SOURCE_DISTRIBUTION:
        return None
    return sem


def _register_bridged_money_declarations(
    semantics: dict[str, ToolSemantics],
    dispatch: dict[str, MCPToolProvider],
) -> None:
    """Publish mureo's OWN money declarations for a bridged surface (#527).

    The two registrations above only reach a plugin that CAN declare, and the
    pattern fallback below is best-effort by construction. A bridged surface
    is neither: its tools are someone else's, so it declares nothing, yet its
    money paths are *known* — enumerated from a real manifest and held in
    :mod:`mureo.amazon_ads.money_paths`. Registering them here makes the known
    part of that surface enforced EXACTLY, through the very registry a
    declaring plugin uses, while the best-effort scan keeps running underneath
    as a floor (see ``mureo.policy.declarations.raise_to_scan_floor``).

    Only for a tool that is present, MUTATING and supplied by the Amazon
    bridge (:func:`_declares_from_bridged_table`), and only when it declared
    nothing itself: a plugin's own ``_meta`` always wins over mureo's table —
    the tool author knows their vocabulary better than a snapshot does.
    Best-effort: a registry failure must not take the server down, and neither
    must a table that fails to import.
    """
    try:
        from mureo.amazon_ads.money_paths import BID_DECLARATIONS, BUDGET_DECLARATIONS
    except Exception:  # noqa: BLE001 — never break startup on a table
        logger.warning("could not load the bridged money declarations", exc_info=True)
        return
    from mureo.policy.declarations import (
        register_bid_declaration,
        register_budget_declaration,
    )

    for name, budget in BUDGET_DECLARATIONS.items():
        sem = _declares_from_bridged_table(name, semantics, dispatch)
        if sem is None or sem.budget is not None:
            continue
        try:
            register_budget_declaration(name, budget)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register the bridged budget declaration for '%s'",
                name,
                exc_info=True,
            )
    for name, bid in BID_DECLARATIONS.items():
        sem = _declares_from_bridged_table(name, semantics, dispatch)
        if sem is None or sem.bid is not None:
            continue
        try:
            register_bid_declaration(name, bid)
        except Exception:  # noqa: BLE001 — never break startup on a hint
            logger.warning(
                "could not register the bridged bid declaration for '%s'",
                name,
                exc_info=True,
            )


_register_plugin_budget_declarations(_PLUGIN_SEMANTICS)
_register_plugin_bid_declarations(_PLUGIN_SEMANTICS)
_register_bridged_money_declarations(_PLUGIN_SEMANTICS, _PLUGIN_DISPATCH)
_register_plugin_read_only_hints(_PLUGIN_SEMANTICS)
_register_plugin_pattern_fallbacks(_PLUGIN_SEMANTICS)


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


def _policy_gate_entry_points() -> tuple[Any, ...] | None:
    """Return the entry points registered under ``mureo.policy_gates``.

    ``None`` — distinct from an empty tuple — means the environment could not
    be enumerated at all. The two must not collapse into one value, because
    :func:`_load_policy_gates` memoizes its answer (#633) and memoizing a
    failure as "zero gates registered" would run the rest of the process with
    every third-party guardrail silently missing. An empty tuple is a machine
    with no gates installed; ``None`` is a moment.

    Isolated as its own function so the unit tests can patch this without
    monkeypatching ``importlib.metadata`` — and, since the memo is keyed by
    this function object, so that patching it is what misses the memo.
    """
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
            "treating as zero gates for this call",
            exc,
        )
        return None
    return tuple(eps)


_POLICY_GATE_CLASS_CACHE: (
    tuple[
        Callable[[], tuple[Any, ...] | None],
        tuple[Any, ...],
        list[type[PolicyGate] | None],
    ]
    | None
) = None
"""Memoized gate discovery for :func:`_load_policy_gates` (#633).

Three parts: the enumerator that produced it, the entry points it returned,
and the class each of those entry points loaded to — ``None`` in that last
list where the load has not succeeded (yet).

**Keyed by the enumerator itself**, the pattern
:func:`mureo.context.platform_guards.installed_platform_names` uses: the tests
install fake gates by replacing :func:`_policy_gate_entry_points`, and a
different function object structurally misses the memo. So no test's gates can
leak into the next test, whatever order the suite runs in, and nothing has to
remember to clear anything.

**Absence is never cached.** A failed enumeration is not stored at all, and an
entry point whose ``load()`` raised keeps its slot at ``None`` and is retried
on the next dispatch. A dropped gate is a missing guardrail; a memo that
remembered one would turn a transient import error into an enforcement hole
for the life of the process, which is the opposite of what this module exists
to do. Retrying costs an ``ep.load()`` (microseconds once the module is in
``sys.modules``, and this path is only reached at all when something is
broken), not a re-enumeration.

What is cached is the *class*, never the instance — see
:func:`_load_policy_gates`.

Written as one assignment, and the per-entry slot as one item store, so a
concurrent reader sees either the old answer or the new one, never half.
"""


def _load_policy_gates() -> tuple[PolicyGate, ...]:
    """Load and instantiate every gate declared under the
    ``mureo.policy_gates`` entry-point group.

    Per-entry-point exception isolation: a broken third-party
    package (partial install, import error) MUST NOT take mureo
    offline. The failing entry is dropped with a WARNING and the
    rest still load — and it is retried on the next call, never
    remembered as absent (:data:`_POLICY_GATE_CLASS_CACHE`).

    Discovery is memoized; **instantiation is not**. ``cls()`` is a few
    microseconds even with every bridge installed, and
    :class:`mureo.core.policy.PolicyGate` promises third-party authors that
    the dispatcher constructs their gate fresh per tool call, so instance
    attributes do not persist and cross-call state belongs on a class
    attribute. Reusing one instance would quietly break every gate written to
    that published contract to save nothing, so what the cache holds is the
    loaded class.
    """
    global _POLICY_GATE_CLASS_CACHE

    enumerate_entry_points = _policy_gate_entry_points
    cached = _POLICY_GATE_CLASS_CACHE
    if cached is not None and cached[0] is enumerate_entry_points:
        entries, classes = cached[1], cached[2]
    else:
        found = enumerate_entry_points()
        if found is None:  # could not enumerate; not an answer worth keeping
            return ()
        entries, classes = found, [None] * len(found)
        _POLICY_GATE_CLASS_CACHE = (enumerate_entry_points, entries, classes)

    gates: list[PolicyGate] = []
    for index, ep in enumerate(entries):
        try:
            cls = classes[index]
            if cls is None:
                cls = ep.load()
                classes[index] = cls
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

    The gate set is discovered once per process (#633)
    ---------------------------------------------------

    This used to call :func:`_load_policy_gates` uncached on every dispatch,
    to pick up an at-runtime install/uninstall of a third-party gate without a
    server restart, on the claim that ``importlib.metadata.entry_points`` is
    "itself cached internally, so the per-call cost is microseconds". That
    claim was wrong by four orders of magnitude. Measured on Python 3.10 with
    four gates installed: 11.76 ms per ``_load_policy_gates()`` call, of which
    **11.43 ms is the enumeration**, which re-stats and re-parses the
    environment every time — that re-check is precisely the freshness being
    paid for, so it never converges toward free. Every MCP tool call paid it
    before any gate logic ran.

    And the freshness bought a state nobody wants. A distribution installed
    into a running server contributes **no tools**: ``_PLUGIN_TOOLS`` /
    ``_PLUGIN_DISPATCH`` are built by ``collect_plugin_tools`` at module
    import, ``_PLUGIN_SEMANTICS`` and the throttler/declaration registries are
    module-level comprehensions over them, and
    :func:`mureo.core.runtime_context.get_runtime_context` caches the first
    context it resolves. Every gate-registering distribution observed in the
    wild also registers ``mureo.providers``, so "the gate arrives alone" is not
    the scenario — the scenario is a bridge whose gate goes live while its
    tools and its analytics module stay unregistered, so its own budget gate
    guards tool names that cannot be dispatched. A distribution shipping a
    *global* gate is worse rather than better: mureo-agency's read-only gate
    would start refusing mutations while the runtime-context factory deciding
    *whose* account is being refused — which it registers in the same
    ``pyproject.toml`` — is still the OSS default, because that one is
    resolved once. Uninstall is the worse direction again: a guardrail
    disappearing mid-process, silently.

    So the gate set is fixed at the first dispatch and changing it costs a
    restart — which is what changing the tool set already cost. This is the
    same trade #631 made for the platform-name enumeration, for the same
    reason: one consistent answer beats a fresher one that disagrees with the
    rest of the process. What is **not** cached is any failure; see
    :data:`_POLICY_GATE_CLASS_CACHE`.
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
    # #547: size a bulk exclusion / block / negative-keyword batch against the
    # account's own recent delivery before it is applied. Runs here rather than
    # in a PolicyGate because it needs one AWAITED platform read and the gate
    # ABI is synchronous by design; runs before _dispatch_tool so a refusal
    # lands before any mutation. No-ops (and issues no read) for every tool
    # that is not a registered exclusion surface, and for an operator who wrote
    # no exclusion rule in STRATEGY.md ## Guardrails.
    preflight = await exclusion_impact_preflight(name, arguments)
    if preflight.refusal_reason is not None:
        return exclusion_refusal_content(preflight)
    result = append_exclusion_impact_notice(
        await _dispatch_tool(name, arguments), preflight
    )
    # #548: a change that restarts an automated bid strategy's learning period
    # says so in its own result, so the next change in a troubleshooting
    # sequence is not made blind. No-op for everything else.
    result = _maybe_append_learning_reset_notice(name, arguments, result)
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
        return _maybe_append_batch_reminder(
            _maybe_append_strategy_reminder(name, result),
            is_mutation=is_mutating_builtin_tool(name),
        )
    if name in _META_ADS_NAMES:
        before = await capture_before_state(name, arguments)
        result = await handle_meta_ads_tool(name, arguments)
        if record_mutations:
            record_native_mutation(name, arguments, before, result)
        return _maybe_append_batch_reminder(
            _maybe_append_strategy_reminder(name, result),
            is_mutation=is_mutating_builtin_tool(name),
        )
    if name in _SEARCH_CONSOLE_NAMES:
        return _maybe_append_strategy_reminder(
            name, await handle_search_console_tool(name, arguments)
        )
    if name in _ROLLBACK_NAMES:
        return _maybe_append_strategy_reminder(
            name, await handle_rollback_tool(name, arguments)
        )
    if name in _BATCH_NAMES:
        return await handle_batch_tool(name, arguments)
    if name in _CHANGE_IMPORT_NAMES:
        return await handle_change_import_tool(name, arguments)
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
    if name in _LEARNING_PREFLIGHT_NAMES:
        return await handle_learning_preflight_tool(name, arguments)
    if name in _CREATIVE_STUDIO_NAMES:
        return await handle_creative_studio_tool(name, arguments)
    if name in _PLUGIN_NAMES:
        provider = _PLUGIN_DISPATCH[name]
        source = plugin_source(provider)
        # The entry-point name this provider registered under. Dispatch
        # itself is keyed by TOOL name, not by platform key — the platform
        # key appears here only as the action_log attribution below, and
        # since one distribution can ship several providers (#537) that
        # attribution needs both halves to name the right platform.
        provider_name = plugin_provider_name(provider)
        sem = _PLUGIN_SEMANTICS.get(name)
        await _acquire_plugin_throttle(name)
        # Capture a runtime-correct reversal BEFORE the mutation (#327),
        # mirroring the native before-state capture: an opted-in provider reads
        # the entity's prior state and returns a reversal carrying the actual
        # id + prior value. Only for mutating tools; best-effort, never blocks.
        #
        # Deliberately AFTER the throttle acquisition: the capture issues real
        # platform reads, so running it first would let a burst of mutations
        # push out unthrottled traffic. Holding the mutation's slot means the
        # capture + write are rate-limited as one group. The capture's own
        # reads are bounded independently too — a per-read timeout, a probe
        # cap of one call per ad product, and a learned id → ad-product cache
        # that usually collapses the probe to a single read
        # (:mod:`mureo.amazon_ads.reversal`).
        captured_reversal: dict[str, Any] | None = None
        if sem is None or sem.mutating:
            captured_reversal = await _capture_plugin_reversal(
                provider, name, arguments
            )
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
        # The call returned, so ``ok`` (= "did not raise") stays True. But a
        # provider can report a PLATFORM refusal as ordinary content in the
        # canonical error envelope — the same signal that skips the
        # action_log promotion below — and the operator-facing trail must not
        # read as a success for a call that changed nothing (#528).
        platform_failed = is_error_result(result)
        record_plugin_call(
            tool=name,
            arguments=arguments,
            source=source,
            ok=True,
            platform_ok=not platform_failed,
            error=result[0].text if platform_failed else None,
        )
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
                    provider=provider_name,
                    reversal=reversal,
                    arguments=arguments,
                    identity=None if sem is None else sem.identity,
                    observation_days=None if sem is None else sem.observation_days,
                )
            # Guardrail parity: a mutating plugin call re-surfaces the
            # operator's STRATEGY.md sections, exactly like a built-in
            # mutation — appended regardless of the result envelope, matching
            # the built-in dispatch. Read-only plugin tools skip it.
            result = _maybe_append_plugin_strategy_reminder(name, result)
            # This branch runs only for a mutating plugin tool, so the call
            # just added a member to any open batch — same reason the built-in
            # mutating branches warn (#549).
            result = _maybe_append_batch_reminder(result, is_mutation=True)
        return result
    raise ValueError(f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# MCP server setup & entry point
# ---------------------------------------------------------------------------


def _workspace_instruction() -> str:
    """Server-level instructions that name the workspace this server is bound to.

    Some hosts expose *every* configured MCP server to *every* conversation at
    once, with no way to scope a conversation to one of them. When more than one
    mureo server is configured (one per workspace), the model has no signal about
    which workspace a given server is bound to and can route a tool call to the
    wrong one. Single-process, cwd-scoped hosts (e.g. Claude Code) are unaffected.

    Naming the bound workspace in the server's ``instructions`` (part of the MCP
    ``InitializeResult`` the client shows the model) gives the model the signal it
    needs to pick the right server and to notice a mismatch instead of proceeding.

    Returns ``""`` for the default single-workspace install — see
    :func:`_server_instructions` for why that matters.
    """
    # Lazy import mirrors the throttle path above (``_acquire_plugin_throttle``):
    # keeping it inside the function pre-empts a cycle should
    # ``mureo.core.runtime_context`` ever reference MCP types.
    from mureo.core.runtime_context import (
        DEFAULT_WORKSPACE_ID,
        RuntimeContextFactoryError,
        get_runtime_context,
    )

    try:
        workspace_id = get_runtime_context().workspace_id
    except RuntimeContextFactoryError:
        # A misconfigured factory is a real error, but it must surface where it
        # already does (first tool call), not by refusing to start the server.
        # Omit instructions and let startup proceed unchanged.
        return ""
    if workspace_id == DEFAULT_WORKSPACE_ID:
        return ""
    return (
        f"This mureo server is bound to workspace {workspace_id!r}. Every tool "
        f"here reads and writes ONLY that workspace's data. If the user is "
        f"working on a different client/workspace, do NOT use this server — use "
        f"the mureo server bound to that workspace instead. Never assume a tool "
        f"call here acts on any workspace other than {workspace_id!r}."
    )


def _platform_model_instruction() -> str:
    """The registered platform delivery models this server actually serves (#648).

    ``instructions`` is the only always-on prose slot an MCP server has: the
    client receives it inside the ``initialize`` response, before any tool
    call, and it does not depend on a description matching. That is precisely
    what a contributed ``SKILL.md`` cannot offer — it is description-matched
    and read on demand, so a plugin's account of how its platform really works
    was never read on the routine reporting paths where a borrowed mental
    model does its damage.

    Scoped to what this server serves and to who contributed it, so a platform
    this server does not serve (uninstalled, or switched off by
    ``MUREO_DISABLE_*``) contributes nothing, and no plugin can publish text
    under another platform's name. Returns ``""`` when no in-scope platform has
    registered a model — which is every install with no such plugin, mureo core
    shipping none of its own.
    """
    # Lazy import for the same reason as the runtime-context import above:
    # nothing in the policy package is needed to define the tool list, and
    # keeping it out of module import order pre-empts a cycle.
    from mureo.policy.platform_model import platform_model_instructions

    return platform_model_instructions(_plugin_tool_owners())


def _plugin_tool_owners() -> dict[str, str]:
    """Which provider contributed each plugin tool this server exposes (#648).

    The ownership map ``platform_model_instructions`` decides scope from. Only
    plugin tools appear: mureo's own built-in tools are deliberately absent, so
    a third-party model claiming ``google_ads_`` or ``meta_ads_`` matches
    nothing and renders nothing. Core registers no models, so leaving its tools
    unowned costs nothing and removes a whole class of impersonation.

    The owner is the breadcrumb ``collect_plugin_tools`` stamps from
    ``ProviderEntry.name`` — the registry key, which is itself first-wins
    protected — rather than an attribute the instance could restyle later. The
    fallback to ``name`` covers the ``__slots__`` provider whose stamp the
    collector had to skip.

    Intersected with ``_ALL_TOOLS``: a dispatch entry with no exposed tool is
    not a served tool, and only a served tool puts a platform in scope.
    """
    exposed = frozenset(tool.name for tool in _ALL_TOOLS)
    owners: dict[str, str] = {}
    for name, provider in _PLUGIN_DISPATCH.items():
        if name not in exposed:
            continue
        owner = getattr(provider, "_mureo_provider_name", None) or getattr(
            provider, "name", None
        )
        if isinstance(owner, str) and owner:
            owners[name] = owner
    return owners


def _server_instructions() -> str | None:
    """Compose the server's MCP ``instructions``, or ``None`` if there is none.

    Two contributions today — the bound-workspace notice and the per-platform
    delivery models (#648) — joined only when non-empty.

    Returns ``None`` when both are empty, which is the default single-workspace
    install with no platform model registered: its ``InitializeResult`` stays
    byte-identical, so standalone OSS users see no change. A multi-workspace
    install with no models gets exactly the workspace string it got before.
    """
    sections = [
        section
        for section in (_workspace_instruction(), _platform_model_instruction())
        if section
    ]
    if not sections:
        return None
    return "\n\n".join(sections)


def _create_server() -> Server:
    """Create an MCP Server instance and register handlers."""
    server = Server("mureo", instructions=_server_instructions())

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
