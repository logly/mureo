"""Publishing plugin/bridge tool semantics to the policy registries (#678).

Lifted verbatim out of :mod:`mureo.mcp.server`, which had grown past the point
where one reader could hold it. Nothing here changed in the move — same
functions, same bodies, same order.

What lives here is the *startup* half of the guardrail wiring: five best-effort
registrars that take a plugin semantics map (and, for the bridged table, the
dispatch map) and publish what they declare to the pure policy layer, so the
ONE built-in :class:`~mureo.policy.strategy_gate.StrategyPolicyGate` enforces a
plugin's ``## Guardrails`` caps without a per-plugin hand-rolled gate.

Every function takes what it needs as an argument and holds no module state of
its own. That is what made the extraction safe and is what keeps it safe: the
maps themselves — ``_PLUGIN_SEMANTICS`` / ``_PLUGIN_DISPATCH`` — and the calls
that feed them in stay in ``server.py``'s module body, because the env-gating
suite re-triggers the whole registration by ``importlib.reload``-ing that one
module and a registrar that had captured a map at import would go stale.

Best-effort throughout: a registry failure logs and moves on. A guardrail hint
that cannot be published must never take the server down at startup.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mureo.mcp.tool_provider import plugin_source

if TYPE_CHECKING:
    from mureo.mcp.plugin_semantics import ToolSemantics
    from mureo.mcp.tool_provider import MCPToolProvider

logger = logging.getLogger(__name__)


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
