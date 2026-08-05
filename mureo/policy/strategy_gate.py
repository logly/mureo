"""Built-in strategy policy gate — deterministic STRATEGY.md enforcement.

This is mureo OSS's first built-in :class:`~mureo.core.policy.PolicyGate`.
Strategy enforcement is core mureo value: the operator declares hard rules in a
``## Guardrails`` section of STRATEGY.md, and mureo blocks any ad-platform
mutation that violates them **before dispatch, regardless of what the LLM
decides**. This closes the gap where gating was only an instruction the model
could ignore (and was entirely absent for hosted connectors).

Two layers:

- Pure decision logic (:func:`parse_guardrails`, :func:`evaluate_guardrails`)
  — I/O-free and fully unit-testable. It asks
  :mod:`mureo.policy.declaration_resolution` what the call PROPOSES (that
  sibling holds ``_budget_inputs`` / ``_bid_inputs``, split out to keep this
  module within the project file-size budget) and compares the answer against
  the operator's caps.
- :class:`StrategyPolicyGate` — the ``PolicyGate`` implementation. It reads
  STRATEGY.md (TTL-cached, fail-open: any read/parse error ⇒ allow) and
  delegates the decision to the pure logic.

Fail-open by contract: when there is no ``## Guardrails`` section, or it is
empty, or STRATEGY.md is unreadable, the gate **allows** (abstains). It only
ever denies on an explicit, machine-readable rule the operator wrote. This
keeps mureo's default behaviour identical to "no enforcement".

Three ways a budget/bid reaches a cap
-------------------------------------

1. The **built-in key scan** — the Google/Meta argument spellings hard-coded
   below (``daily_budget``, ``amount_micros``, ``bid_amount``,
   ``cpc_bid_micros``, …).
2. An **exact declaration** (:mod:`mureo.policy.declarations`) — a plugin
   names the keys its tools carry, in standard MCP metadata; or, for a
   bridged surface that cannot carry metadata at all, mureo names the exact
   nested PATHS itself (:class:`~mureo.policy.declarations.ArgumentPaths`,
   #527). Authoritative: it REPLACES the built-in scan for the channels it
   covers.
3. The **pattern fallback** (:mod:`mureo.policy.pattern_scan`) — for a
   registered MUTATING plugin tool that declared nothing, budget-shaped and
   bid-shaped argument keys are read heuristically (recursively, micros-aware)
   and held to the same caps, with the same fail-closed handling of a
   non-finite figure and the same deny envelope.

The fallback is **best-effort by construction**: it matches on key *shape*, so
it can miss a budget spelled without the word (and it can over-block a
budget-named field that is not a proposal). It exists because a bridged tool
surface — someone else's tool definitions, forwarded verbatim — declares
nothing of its own, and "no declaration" must not mean "no cap" where real
money moves. A **flat-key declaration takes precedence**: for a channel that
has one, the scan is not consulted — the plugin owns the argument names of
tools it authors itself.

A **PATH declaration is different, and deliberately so** (#527): it raises the
FLOOR rather than replacing the scan. mureo writes those paths for a surface
it does not own, from a manifest snapshot, so whenever a family is declared by
path the scan runs too and the larger figure per channel wins — however much
the declaration resolved. The invariant is *never check less than the scan
alone would have checked*: several declared tools carry two independent money
fields in one channel, so a rule like "suppress the scan once the declaration
resolves something" let a drifted SIBLING field go completely unchecked. See
:func:`~mureo.policy.declarations.raise_to_scan_floor`. What a path
declaration buys — exactness in the deny message, a DENY on an unreadable
declared leaf, drift visibility — needs no suppression to work.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from mureo.core.policy import PolicyDecision

# The channel-resolution layer — "what does this call propose?" — lives in
# another sibling (:mod:`mureo.policy.declaration_resolution`), split out for
# the same file-size reason and re-exported here for the same import-path
# reason. This module is the decision layer: it asks that one for the resolved
# channels and compares them against the operator's caps.
from mureo.policy.declaration_resolution import (
    _BID_AMOUNT_KEYS,
    _BUDGET_KEYS,
    _CONVENTION_CURRENT_KEY,
    _CONVENTION_TOTAL_KEY,
    _CURRENT_BUDGET_KEYS,
    _bid_inputs,
    _BidInputs,
    _budget_inputs,
    _BudgetInputs,
    _current_budget,
    _projected_total,
    _proposed_bid_amount,
    _proposed_budget,
    _proposed_cpc_bid,
    _proposed_lifetime_budget,
)

# The plugin budget/bid declaration machinery lives in a sibling module
# (:mod:`mureo.policy.declarations`), split out to keep this module within the
# project file-size budget. It is re-imported here — and listed in ``__all__``
# below — so that ``mureo.policy.strategy_gate`` stays a stable import path:
# the sibling bridges, mureo-pro, and the test-suite import several of these
# names from here, so every symbol that used to live in this module must keep
# resolving from it.
from mureo.policy.declarations import (
    _BID_DECLARATIONS,
    _BUDGET_DECLARATIONS,
    _UNREADABLE,
    ArgumentPaths,
    BidDeclaration,
    BudgetDeclaration,
    bid_declaration_for,
    budget_declaration_for,
    register_bid_declaration,
    register_budget_declaration,
    reset_bid_declarations,
    reset_budget_declarations,
)
from mureo.policy.pattern_scan import (
    SCAN_EXHAUSTED_NODES,
    has_pattern_fallback,
    is_scan_exhausted,
    register_pattern_fallback_tool,
    reset_pattern_fallback_tools,
)

logger = logging.getLogger(__name__)

# Stable import surface of this module. Membership here marks the re-exported
# declaration names above as an explicit re-export (mypy ``--strict``'s
# ``no_implicit_reexport``) and documents the API the downstream bridges,
# mureo-pro, and the test-suite depend on. The three ``_``-prefixed registry
# names are included deliberately: the test-suite imports them from this path.
__all__ = [
    "GUARDRAILS_HEADING",
    "Guardrails",
    "StrategyPolicyGate",
    "evaluate_guardrails",
    "guardrails_from_strategy_text",
    "parse_guardrails",
    "ArgumentPaths",
    "BudgetDeclaration",
    "BidDeclaration",
    "budget_declaration_for",
    "bid_declaration_for",
    "register_budget_declaration",
    "register_bid_declaration",
    "reset_budget_declarations",
    "reset_bid_declarations",
    "_BUDGET_DECLARATIONS",
    "_BID_DECLARATIONS",
    "_UNREADABLE",
    "has_pattern_fallback",
    "is_scan_exhausted",
    "register_pattern_fallback_tool",
    "reset_pattern_fallback_tools",
    # Resolution layer, re-exported so every name that used to live in this
    # module keeps resolving from it.
    "_BUDGET_KEYS",
    "_CURRENT_BUDGET_KEYS",
    "_BID_AMOUNT_KEYS",
    "_CONVENTION_CURRENT_KEY",
    "_CONVENTION_TOTAL_KEY",
    "_BudgetInputs",
    "_BidInputs",
    "_budget_inputs",
    "_bid_inputs",
    "_projected_total",
    "_proposed_budget",
    "_proposed_lifetime_budget",
    "_current_budget",
    "_proposed_bid_amount",
    "_proposed_cpc_bid",
]

#: The two ways the best-effort scan can run out, in operator words. Keyed by
#: the sentinel :mod:`mureo.policy.pattern_scan` reports, so the reason names
#: the ACTUAL cause rather than a generic "too big".
_SCAN_EXHAUSTED_CAUSES = {
    SCAN_EXHAUSTED_NODES: (
        "are too large for mureo's best-effort {what} scan to read completely"
    ),
    # Anything else is the depth sentinel.
    None: (
        "nest a {what}-carrying section deeper than mureo's best-effort "
        "{what} scan descends"
    ),
}

#: Shared by the budget and bid deny paths so the two cannot drift.
#: ``{what}`` is "budget" / "bid"; ``{cause}`` comes from
#: :data:`_SCAN_EXHAUSTED_CAUSES`.
_SCAN_EXHAUSTED_REASON = (
    "This call's arguments {cause}, so the STRATEGY.md Guardrails {what} caps "
    "cannot be verified for it. Refusing it rather than letting an unchecked "
    "{what} through. Declare this tool's {what} argument keys in its MCP "
    "metadata (_meta['mureo']['{what}']) — a declaration is read directly and "
    "is affected by neither payload size nor nesting — or flatten the payload "
    "and split the call into smaller batches."
)


def _scan_exhausted_reason(unreadable_key: str, what: str) -> str:
    """Operator-facing text for an exhausted scan. One builder, two families."""
    cause = _SCAN_EXHAUSTED_CAUSES.get(
        unreadable_key, _SCAN_EXHAUSTED_CAUSES[None]
    ).format(what=what)
    return _SCAN_EXHAUSTED_REASON.format(cause=cause, what=what)


# The (case-insensitive) STRATEGY.md section that carries machine-readable
# hard rules. Unrecognized by strategy.py's section map, so it round-trips as
# a raw-heading entry titled "Guardrails".
GUARDRAILS_HEADING = "guardrails"


_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True)
class Guardrails:
    """Machine-readable hard rules parsed from STRATEGY.md ``## Guardrails``."""

    max_daily_budget_per_campaign: float | None = None
    max_daily_budget_increase_pct: float | None = None
    max_total_daily_budget: float | None = None
    max_lifetime_budget_per_campaign: float | None = None
    #: Bid caps. Distinct from budgets: a bid is a per-auction ceiling, not a
    #: spend budget, so it gets its own cap. ``max_bid_amount_per_ad_set`` is
    #: in account-currency MINOR units — identical to Meta's ``bid_amount``
    #: argument (yen for JPY, cents for USD). ``max_cpc_bid_per_ad_group`` is in
    #: account-currency units — Google's ``cpc_bid_micros`` is converted from
    #: micros before comparison, mirroring the budget-micros convention.
    max_bid_amount_per_ad_set: float | None = None
    max_cpc_bid_per_ad_group: float | None = None
    blocked_operations: frozenset[str] = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        return (
            self.max_daily_budget_per_campaign is None
            and self.max_daily_budget_increase_pct is None
            and self.max_total_daily_budget is None
            and self.max_lifetime_budget_per_campaign is None
            and self.max_bid_amount_per_ad_set is None
            and self.max_cpc_bid_per_ad_group is None
            and not self.blocked_operations
        )


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace("_", "").strip())
    except (ValueError, AttributeError):
        return None


def parse_guardrails(content: str) -> Guardrails:
    """Parse the body of a ``## Guardrails`` section into :class:`Guardrails`.

    Recognizes ``- key: value`` bullets. Unknown keys are ignored (forward
    compatibility). A malformed numeric value drops that one rule rather than
    failing the whole parse.
    """
    max_per_campaign: float | None = None
    max_increase_pct: float | None = None
    max_total: float | None = None
    max_lifetime: float | None = None
    max_bid_amount: float | None = None
    max_cpc_bid: float | None = None
    blocked: set[str] = set()

    for line in content.splitlines():
        m = _BULLET_RE.match(line)
        if m is None:
            continue
        key = m.group(1).lower()
        raw = m.group(2).strip()
        if key == "max_daily_budget_per_campaign":
            max_per_campaign = _to_float(raw)
        elif key == "max_daily_budget_increase_pct":
            max_increase_pct = _to_float(raw)
        elif key == "max_total_daily_budget":
            max_total = _to_float(raw)
        elif key == "max_lifetime_budget_per_campaign":
            max_lifetime = _to_float(raw)
        elif key == "max_bid_amount_per_ad_set":
            max_bid_amount = _to_float(raw)
        elif key == "max_cpc_bid_per_ad_group":
            max_cpc_bid = _to_float(raw)
        elif key == "blocked_operations":
            blocked = {op.strip() for op in raw.split(",") if op.strip()}

    return Guardrails(
        max_daily_budget_per_campaign=max_per_campaign,
        max_daily_budget_increase_pct=max_increase_pct,
        max_total_daily_budget=max_total,
        max_lifetime_budget_per_campaign=max_lifetime,
        max_bid_amount_per_ad_set=max_bid_amount,
        max_cpc_bid_per_ad_group=max_cpc_bid,
        blocked_operations=frozenset(blocked),
    )


def guardrails_from_strategy_text(text: str) -> Guardrails:
    """Extract guardrails from full STRATEGY.md text (empty if no section)."""
    # Imported here to keep the pure decision logic above import-light.
    from mureo.context.strategy import parse_strategy

    for entry in parse_strategy(text):
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            return parse_guardrails(entry.content)
    return Guardrails()


def evaluate_guardrails(
    tool_name: str,
    arguments: dict[str, Any],
    guardrails: Guardrails,
    *,
    budget_declaration: BudgetDeclaration | None = None,
    bid_declaration: BidDeclaration | None = None,
    pattern_fallback: bool = False,
) -> PolicyDecision:
    """Pure decision: does ``tool_name(arguments)`` violate ``guardrails``?

    Returns ``PolicyDecision(allowed=False, reason=...)`` on the first hard
    violation, else ``allowed=True``. No I/O.

    ``budget_declaration`` (#414) names the argument keys carrying this
    tool's budget. When given it REPLACES the built-in Google/Meta key scan
    for the budgets the tool *proposes* — the tool's own vocabulary is
    authoritative there. The exceptions are the two figures the CALLER supplies
    rather than the tool: the current daily budget (undeclared, it still comes
    from the ``current_daily_budget`` convention) and the projected account
    total (always ``projected_total_daily_budget``). So declaring a budget
    cannot switch ``max_daily_budget_increase_pct`` or ``max_total_daily_budget``
    off (see :class:`BudgetDeclaration`). Omitted (every built-in tool, and any
    plugin that has not declared) ⇒ unchanged behavior.

    ``bid_declaration`` is the bid twin of the above: it names the keys carrying
    this tool's proposed bid and REPLACES the built-in Meta/Google bid scan for
    that tool, so a plugin bid tool is enforced by ``max_bid_amount_per_ad_set``
    / ``max_cpc_bid_per_ad_group`` (see :class:`BidDeclaration`). Omitted ⇒
    unchanged behavior.

    ``pattern_fallback`` turns on the best-effort key-shape scan
    (:mod:`mureo.policy.pattern_scan`) for the channels that have NO
    declaration — the only enforcement available to a tool surface that cannot
    carry declarations at all — and, since #527, for every family declared by
    PATH, where it acts as a FLOOR under the declaration (the larger figure
    wins; see the module docstring). It is additive: the built-in scan still
    runs and the larger figure wins. Per-family, so declaring a budget does not
    switch the bid fallback off (or vice versa). Default ``False`` ⇒ every
    existing caller is byte-identical.
    """
    if guardrails.is_empty():
        return PolicyDecision(allowed=True)

    if tool_name in guardrails.blocked_operations:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Operation '{tool_name}' is blocked by the STRATEGY.md "
                f"Guardrails (blocked_operations)."
            ),
        )

    inputs = _budget_inputs(
        arguments, budget_declaration, pattern_fallback=pattern_fallback
    )
    if inputs.unreadable_key is not None:
        # Fail CLOSED: the operator wrote a cap and the tool's declared
        # budget argument carries garbage, so the cap CANNOT be checked.
        # Allowing here would be the #414 silent bypass with extra steps.
        # An exhausted scan is the same failure for a different reason — it
        # ran out of budget before reading anything — and gets a reason the
        # operator can act on rather than "'<sentinel>' is not a number".
        if is_scan_exhausted(inputs.unreadable_key):
            return PolicyDecision(
                allowed=False,
                reason=_scan_exhausted_reason(inputs.unreadable_key, "budget"),
            )
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Budget argument '{inputs.unreadable_key}' is not a usable "
                f"number, so the STRATEGY.md Guardrails caps cannot be "
                f"verified for this call. Refusing it."
            ),
        )

    proposed = inputs.proposed
    if proposed is not None:
        cap = guardrails.max_daily_budget_per_campaign
        if cap is not None and proposed > cap:
            return PolicyDecision(
                allowed=False,
                reason=(
                    f"Proposed daily budget {proposed:,.0f} exceeds the "
                    f"STRATEGY.md Guardrails cap of {cap:,.0f} "
                    f"(max_daily_budget_per_campaign)."
                ),
            )

        current = inputs.current
        pct_cap = guardrails.max_daily_budget_increase_pct
        if pct_cap is not None and current is not None:
            if current > 0:
                increase_pct = (proposed - current) / current * 100
                if increase_pct > pct_cap:
                    return PolicyDecision(
                        allowed=False,
                        reason=(
                            f"Proposed daily budget raises spend {increase_pct:.0f}% "
                            f"({current:,.0f} → {proposed:,.0f}), over the STRATEGY.md "
                            f"Guardrails limit of {pct_cap:.0f}% "
                            f"(max_daily_budget_increase_pct)."
                        ),
                    )
            elif proposed > 0:
                # current == 0 (a paused / zero-budget campaign). A percentage
                # increase from a zero baseline is unbounded — NO finite raise
                # can satisfy a percentage cap — so the old ``current > 0`` guard
                # let a 0 → any-amount jump skip max_daily_budget_increase_pct
                # entirely. When a percentage cap is the only budget rule the
                # operator wrote, that raise then hit no cap at all. Fail CLOSED,
                # consistent with the rest of this gate: refuse it and let the
                # operator resume from zero via an explicit
                # max_daily_budget_per_campaign, or without passing a zero
                # ``current_daily_budget`` baseline. (``proposed == 0`` is a
                # decrease-to-zero, not an increase, so it is left to pass.)
                return PolicyDecision(
                    allowed=False,
                    reason=(
                        f"Proposed daily budget raises spend from 0 to "
                        f"{proposed:,.0f}, an unbounded increase from a zero "
                        f"baseline that the {pct_cap:.0f}% STRATEGY.md Guardrails "
                        f"limit (max_daily_budget_increase_pct) cannot bound. "
                        f"Refusing it."
                    ),
                )

    # Lifetime (period-total) budgets have distinct semantics from daily
    # budgets, so they get their own cap rather than reusing the daily one.
    # Without this, a lifetime-budget mutation would sidestep every budget
    # guardrail the operator wrote (#367). Covers Meta's ``lifetime_budget``
    # (minor units) and Google's CUSTOM_PERIOD ``total_amount_micros``
    # (micros → currency units), mirroring the daily micros handling (#366).
    lifetime = inputs.lifetime
    lifetime_cap = guardrails.max_lifetime_budget_per_campaign
    if lifetime_cap is not None and lifetime is not None and lifetime > lifetime_cap:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Proposed lifetime budget {lifetime:,.0f} exceeds the "
                f"STRATEGY.md Guardrails cap of {lifetime_cap:,.0f} "
                f"(max_lifetime_budget_per_campaign)."
            ),
        )

    total = inputs.total
    total_cap = guardrails.max_total_daily_budget
    if total_cap is not None and total is not None and total > total_cap:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Projected total daily budget {total:,.0f} exceeds the "
                f"STRATEGY.md Guardrails cap of {total_cap:,.0f} "
                f"(max_total_daily_budget)."
            ),
        )

    # Bid caps have distinct semantics from budgets — a bid is a per-auction
    # ceiling, not a spend budget — so they get their own caps rather than
    # reusing the budget ones. Resolved through the same single-choke-point
    # discipline as budgets (#419): a non-finite proposed bid (oversized int
    # saturated to inf, or a bare NaN/Infinity the wire allows) fails CLOSED
    # here, before any ``bid > cap`` comparison where ``nan > cap`` (False)
    # would silently defeat the cap.
    bids = _bid_inputs(arguments, bid_declaration, pattern_fallback=pattern_fallback)
    if bids.unreadable_key is not None:
        if is_scan_exhausted(bids.unreadable_key):
            return PolicyDecision(
                allowed=False,
                reason=_scan_exhausted_reason(bids.unreadable_key, "bid"),
            )
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Bid argument '{bids.unreadable_key}' is not a usable "
                f"number, so the STRATEGY.md Guardrails bid caps cannot be "
                f"verified for this call. Refusing it."
            ),
        )

    bid = bids.bid_amount
    bid_cap = guardrails.max_bid_amount_per_ad_set
    if bid_cap is not None and bid is not None and bid > bid_cap:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Proposed bid amount {bid:,.0f} exceeds the "
                f"STRATEGY.md Guardrails cap of {bid_cap:,.0f} "
                f"(max_bid_amount_per_ad_set)."
            ),
        )

    cpc_bid = bids.cpc_bid
    cpc_cap = guardrails.max_cpc_bid_per_ad_group
    if cpc_cap is not None and cpc_bid is not None and cpc_bid > cpc_cap:
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Proposed CPC bid {cpc_bid:,.0f} exceeds the "
                f"STRATEGY.md Guardrails cap of {cpc_cap:,.0f} "
                f"(max_cpc_bid_per_ad_group)."
            ),
        )

    return PolicyDecision(allowed=True)


# --- Gate implementation (thin I/O layer over the pure logic) --------------

# Module-level TTL cache. The dispatcher constructs the gate fresh per call
# (instance state is ephemeral by contract), so the cache lives at module
# scope. STRATEGY.md changes are picked up within _CACHE_TTL_SECONDS.
_CACHE_TTL_SECONDS = 5.0
_cache: dict[str, tuple[float, Guardrails]] = {}


def _resolve_strategy_path() -> Any:
    """Best-effort STRATEGY.md path for the active workspace (or None)."""
    from pathlib import Path

    try:
        from mureo.core.runtime_context import get_runtime_context

        store = get_runtime_context().state_store
        strategy_path = getattr(store, "strategy_path", None)
        if strategy_path is not None:
            return Path(strategy_path)
    except Exception:  # noqa: BLE001 — never let resolution break dispatch
        pass
    return Path.cwd() / "STRATEGY.md"


def _load_guardrails() -> Guardrails:
    """Read + parse STRATEGY.md guardrails, TTL-cached. Fail-open (empty)."""
    path = _resolve_strategy_path()
    key = str(path)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        guardrails = guardrails_from_strategy_text(text)
    except Exception:  # noqa: BLE001 — a gate must never take mureo offline
        logger.debug("StrategyPolicyGate: could not load guardrails", exc_info=True)
        guardrails = Guardrails()
    _cache[key] = (now, guardrails)
    return guardrails


class StrategyPolicyGate:
    """Built-in gate enforcing STRATEGY.md ``## Guardrails`` hard rules.

    Conforms to :class:`mureo.core.policy.PolicyGate`. Ships and runs in OSS
    by default; abstains (allows) whenever no guardrail applies.
    """

    def evaluate(self, tool_name: str, arguments: dict[str, Any]) -> PolicyDecision:
        try:
            return evaluate_guardrails(
                tool_name,
                arguments,
                _load_guardrails(),
                # #414: a plugin tool that declared its budget keys is now
                # enforced by THIS gate — no hand-rolled per-plugin gate.
                budget_declaration=budget_declaration_for(tool_name),
                # The bid twin of #414: a plugin tool that declared its bid keys
                # is enforced by the same gate through the same choke point.
                bid_declaration=bid_declaration_for(tool_name),
                # A MUTATING plugin tool that declared NOTHING (a bridged tool
                # surface cannot) falls back to the best-effort key-shape scan
                # rather than to no enforcement at all.
                pattern_fallback=has_pattern_fallback(tool_name),
            )
        except Exception:  # noqa: BLE001 — abstain on any unexpected error
            logger.debug("StrategyPolicyGate: abstaining on error", exc_info=True)
            return PolicyDecision(allowed=True)
