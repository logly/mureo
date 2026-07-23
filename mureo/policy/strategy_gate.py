"""Built-in strategy policy gate — deterministic STRATEGY.md enforcement.

This is mureo OSS's first built-in :class:`~mureo.core.policy.PolicyGate`.
Strategy enforcement is core mureo value: the operator declares hard rules in a
``## Guardrails`` section of STRATEGY.md, and mureo blocks any ad-platform
mutation that violates them **before dispatch, regardless of what the LLM
decides**. This closes the gap where gating was only an instruction the model
could ignore (and was entirely absent for hosted connectors).

Two layers:

- Pure decision logic (:func:`parse_guardrails`, :func:`evaluate_guardrails`)
  — I/O-free and fully unit-testable.
- :class:`StrategyPolicyGate` — the ``PolicyGate`` implementation. It reads
  STRATEGY.md (TTL-cached, fail-open: any read/parse error ⇒ allow) and
  delegates the decision to the pure logic.

Fail-open by contract: when there is no ``## Guardrails`` section, or it is
empty, or STRATEGY.md is unreadable, the gate **allows** (abstains). It only
ever denies on an explicit, machine-readable rule the operator wrote. This
keeps mureo's default behaviour identical to "no enforcement".
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any

from mureo.core.policy import PolicyDecision

# The plugin budget/bid declaration machinery lives in a sibling module
# (:mod:`mureo.policy.declarations`), split out to keep this module within the
# project file-size budget. It is re-imported here — and listed in ``__all__``
# below — so that ``mureo.policy.strategy_gate`` stays a stable import path:
# the sibling bridges, mureo-pro, and the test-suite import several of these
# names from here, so every symbol that used to live in this module must keep
# resolving from it. ``_saturate`` / ``_declared_amount`` / ``_Unreadable`` are
# also used directly by the decision logic below.
from mureo.policy.declarations import (
    _BID_DECLARATIONS,
    _BUDGET_DECLARATIONS,
    _UNREADABLE,
    BidDeclaration,
    BudgetDeclaration,
    _declared_amount,
    _saturate,
    _Unreadable,
    bid_declaration_for,
    budget_declaration_for,
    register_bid_declaration,
    register_budget_declaration,
    reset_bid_declarations,
    reset_budget_declarations,
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
]

# The (case-insensitive) STRATEGY.md section that carries machine-readable
# hard rules. Unrecognized by strategy.py's section map, so it round-trips as
# a raw-heading entry titled "Guardrails".
GUARDRAILS_HEADING = "guardrails"

# Argument keys that carry a proposed daily budget, in priority order.
# These are the BUILT-IN (Google/Meta) spellings; a plugin whose tools use a
# different vocabulary declares its own keys instead — see BudgetDeclaration.
_BUDGET_KEYS = ("daily_budget", "proposed_daily_budget", "amount")
_CURRENT_BUDGET_KEYS = ("current_daily_budget", "current")
#: Argument keys carrying a proposed *bid cap* (distinct from a spend budget).
#: ``bid_amount`` is Meta's ad-set bid cap in account-currency minor units
#: (meta_ads_ad_sets_create / _update). Deliberately scalar-only: the sibling
#: ``bid_constraints`` dict carries a ``roas_average_floor`` (a min-ROAS floor,
#: not a spend amount) and must NOT be read as a proposed bid.
_BID_AMOUNT_KEYS = ("bid_amount",)
#: The cross-provider convention keys for the two budget figures the CALLER
#: supplies rather than the tool: the *existing* daily budget and the
#: account-wide projected total (both in currency units), which the skills pass
#: on a budget mutation. A declaration cannot replace these — see
#: :func:`_budget_inputs`.
_CONVENTION_CURRENT_KEY = "current_daily_budget"
_CONVENTION_TOTAL_KEY = "projected_total_daily_budget"

_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


def _projected_total(arguments: dict[str, Any]) -> float | None:
    """The account-wide projected daily total a skill passes for the total cap.

    Convention key only, on the declared path as much as the built-in one:
    there is no declared equivalent because this figure is not a budget the
    TOOL proposes — like ``current_daily_budget`` it is context the CALLER
    computes. Routed through ``_saturate`` like every other budget channel so
    an oversized int denies instead of raising.
    """
    total = arguments.get(_CONVENTION_TOTAL_KEY)
    if isinstance(total, (int, float)) and not isinstance(total, bool):
        return _saturate(total)
    return None


@dataclass(frozen=True)
class _BudgetInputs:
    """The budget channels one evaluation needs, already resolved.

    Every value here is either ``None`` (no budget on that channel) or a
    FINITE float. A present-but-non-finite value (``inf``/``nan``, from an
    oversized int that saturated, a bare ``NaN`` on the wire, or garbage on a
    declared key) is collapsed into :attr:`unreadable_key` so the caller fails
    closed once — no downstream comparison ever sees ``inf``/``nan``. This is
    the single choke point that keeps ``nan > cap`` (always False) and
    ``finite/inf = nan`` from silently defeating a cap.
    """

    proposed: float | None = None
    current: float | None = None
    lifetime: float | None = None
    total: float | None = None
    #: The first budget key that was present but unreadable (⇒ deny).
    unreadable_key: str | None = None


def _budget_inputs(
    arguments: dict[str, Any], declaration: BudgetDeclaration | None
) -> _BudgetInputs:
    """Resolve the budget channels from declared keys, else the built-in scan.

    A non-finite value on ANY channel — declared or built-in — fails closed:
    the whole call is refused. The declared path already did this via
    ``_declared_amount`` returning ``_UNREADABLE``; the built-in scan is held to
    the same standard here so an oversized int (``inf``) or a bare ``NaN``
    cannot slip past a comparison.

    Deliberately BROAD, and fail-safe: a non-finite value on a budget channel
    denies even when the specific cap that reads that channel is not the one
    configured (e.g. garbage in ``current_daily_budget`` with only an absolute
    cap set). This is only reachable once the operator has written *some*
    guardrail (``evaluate_guardrails`` returns early on an empty ``Guardrails``),
    so the fail-open default is preserved; past that point a non-finite figure
    in any recognized budget argument is malformed input, and refusing it is the
    safe direction. It also keeps this the single choke point — scoping the
    check per-active-cap would re-introduce the "which comparison did we forget"
    surface that let the overflow/NaN bypass exist in the first place. Mirrors
    the already-shipped declared path (#414), which denies on any unreadable
    declared key regardless of which cap reads it.
    """
    if declaration is None:
        channels: list[tuple[str, float | None]] = [
            ("daily budget", _proposed_budget(arguments)),
            ("current budget", _current_budget(arguments)),
            ("lifetime budget", _proposed_lifetime_budget(arguments)),
            ("projected total daily budget", _projected_total(arguments)),
        ]
        for label, value in channels:
            if value is not None and not math.isfinite(value):
                return _BudgetInputs(unreadable_key=label)
        proposed, current, lifetime, total = (v for _, v in channels)
        return _BudgetInputs(
            proposed=proposed, current=current, lifetime=lifetime, total=total
        )
    resolved: list[float | None] = []
    for key in (
        declaration.daily_key,
        declaration.current_key,
        declaration.lifetime_key,
    ):
        declared = _declared_amount(arguments, key, micros=declaration.micros)
        if isinstance(declared, _Unreadable):
            return _BudgetInputs(unreadable_key=key)
        resolved.append(declared)
    proposed, current, lifetime = resolved
    # The two CALLER-supplied channels survive a declaration. Neither is part of
    # the plugin's argument vocabulary: the existing daily budget and the
    # account-wide projected total are context the skills compute and pass under
    # mureo's own cross-provider convention (currency units, on every budget
    # mutation). A declaration replaces the built-in scan for the budgets the
    # tool PROPOSES; replacing these too silently disabled
    # max_daily_budget_increase_pct and max_total_daily_budget for every plugin
    # that adopted the seam — the exact underenforcement it exists to remove,
    # and for the total cap not even opt-out-able, since a declaration has no
    # key to name it with. Both are read in currency units even when the DECLARED
    # keys are micros: ``micros`` describes what the tool carries, not these.
    #
    # They are budget channels like any other, so they fail closed on a
    # non-finite figure exactly as the built-in scan does (#419): a ``nan``
    # baseline makes ``current > 0`` False and takes the percentage cap dark,
    # while a bare oversized int raises out of ``float()`` into the gate's
    # blanket ``except`` — an abstain, i.e. an allow.
    if not declaration.current_key:
        # Only the namespaced convention key here, never the bare ``current``
        # alias the built-in scan also accepts: a declaring plugin owns its
        # argument vocabulary, and ``current`` is a plausible name for something
        # else entirely (an index, a status). Misreading one as the baseline
        # would compute a nonsense increase — and a LARGE stray value yields a
        # SMALL percentage, i.e. it would allow a raise that should be refused.
        raw = arguments.get(_CONVENTION_CURRENT_KEY)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            current = _saturate(raw)
            if not math.isfinite(current):
                return _BudgetInputs(unreadable_key=_CONVENTION_CURRENT_KEY)
    total = _projected_total(arguments)
    if total is not None and not math.isfinite(total):
        return _BudgetInputs(unreadable_key=_CONVENTION_TOTAL_KEY)
    return _BudgetInputs(
        proposed=proposed, current=current, lifetime=lifetime, total=total
    )


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


def _proposed_budget(arguments: dict[str, Any]) -> float | None:
    for key in _BUDGET_KEYS:
        if key in arguments:
            v = arguments[key]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return _saturate(v)
    # Google Ads budgets are sometimes expressed in micros —
    # budget_amount_micros on campaign tools, amount_micros on budget tools.
    for micros_key in ("budget_amount_micros", "amount_micros"):
        micros = arguments.get(micros_key)
        if isinstance(micros, (int, float)) and not isinstance(micros, bool):
            return _saturate(micros) / 1_000_000
    return None


def _proposed_lifetime_budget(arguments: dict[str, Any]) -> float | None:
    """Extract a proposed lifetime / period-total budget in currency units.

    Both spellings of a Google total budget are covered — ``total_amount``
    (currency units) and ``total_amount_micros`` — so the cap cannot be
    sidestepped by picking the other parameter form.
    """
    for key in ("lifetime_budget", "total_amount"):
        v = arguments.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return _saturate(v)
    micros = arguments.get("total_amount_micros")
    if isinstance(micros, (int, float)) and not isinstance(micros, bool):
        return _saturate(micros) / 1_000_000
    return None


def _current_budget(arguments: dict[str, Any]) -> float | None:
    for key in _CURRENT_BUDGET_KEYS:
        v = arguments.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return _saturate(v)
    return None


def _proposed_bid_amount(arguments: dict[str, Any]) -> float | None:
    """Extract a proposed ad-set bid cap in account-currency minor units.

    Mirrors :func:`_proposed_budget`: scans the built-in Meta spelling
    (``bid_amount``) and saturates an oversized int to ``inf`` so it exceeds any
    finite cap and denies rather than raising. Only the scalar ``bid_amount`` is
    a spend cap; the sibling ``bid_constraints`` dict carries a
    ``roas_average_floor`` (a min-ROAS floor, not a spend amount) and is
    deliberately not read here — see :data:`_BID_AMOUNT_KEYS`.
    """
    for key in _BID_AMOUNT_KEYS:
        v = arguments.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return _saturate(v)
    return None


def _proposed_cpc_bid(arguments: dict[str, Any]) -> float | None:
    """Extract a proposed Google ad-group CPC bid in account-currency units.

    ``cpc_bid_micros`` (google_ads_ad_groups_create / _update) is in micros, so
    it is divided by 1e6 to currency units before comparison — the same micros
    convention :func:`_proposed_budget` applies to Google budgets. A
    ``bid_modifier`` (google_ads_bid_adjustments_update) is a 0.1–10.0
    multiplier, not a spend amount, so it is deliberately not read here.
    """
    micros = arguments.get("cpc_bid_micros")
    if isinstance(micros, (int, float)) and not isinstance(micros, bool):
        return _saturate(micros) / 1_000_000
    return None


@dataclass(frozen=True)
class _BidInputs:
    """The bid channels one evaluation needs, already resolved.

    The bid analogue of :class:`_BudgetInputs` (#419). Every value here is
    either ``None`` (no bid proposed on that channel) or a FINITE float. A
    present-but-non-finite value — an oversized int that saturated to ``inf``, a
    bare ``NaN`` / ``Infinity`` token ``json.loads`` accepts off the wire, or a
    ``nan`` surviving the micros→currency division — collapses into
    :attr:`unreadable_key` so the caller fails closed once, before any
    ``bid > cap`` comparison (where ``nan > cap`` is always False and would
    silently defeat the cap). ``bid_amount`` is in account-currency minor units;
    ``cpc_bid`` is in currency units (post-division).
    """

    bid_amount: float | None = None
    cpc_bid: float | None = None
    #: The first bid key that was present but non-finite (⇒ deny).
    unreadable_key: str | None = None


def _bid_inputs(
    arguments: dict[str, Any], declaration: BidDeclaration | None = None
) -> _BidInputs:
    """Resolve the bid channels from declared keys, else the built-in scan.

    Mirrors :func:`_budget_inputs` (#419) at a single choke point rather than
    per-comparison: a proposed bid that is ``inf`` / ``nan`` is refused instead
    of silently sailing past the cap. Both channels are checked AFTER the
    micros→currency division, so a non-finite ``cpc_bid_micros`` cannot slip
    through post-division. Only reachable once the operator has written some
    guardrail (``evaluate_guardrails`` returns early on an empty ``Guardrails``),
    so the fail-open default is preserved.

    ``declaration`` (the bid twin of #414) names a plugin tool's bid argument
    keys. When given it REPLACES the built-in Meta/Google key scan for that
    tool — the plugin owns its argument vocabulary, so a stray ``bid_amount``
    field cannot false-trip a cap. Unlike budgets there are no caller-supplied
    convention keys, so a declaration replaces the whole bid scan. Declared keys
    feed the SAME fail-closed logic as the built-in scan via
    :func:`_declared_amount`: a present-but-unreadable declared key returns
    :data:`_UNREADABLE`, collapsing into :attr:`_BidInputs.unreadable_key` so
    the caller denies once — no second comparison path.
    """
    if declaration is None:
        channels: list[tuple[str, float | None]] = [
            ("bid_amount", _proposed_bid_amount(arguments)),
            ("cpc_bid_micros", _proposed_cpc_bid(arguments)),
        ]
        for label, value in channels:
            if value is not None and not math.isfinite(value):
                return _BidInputs(unreadable_key=label)
        bid_amount, cpc_bid = (v for _, v in channels)
        return _BidInputs(bid_amount=bid_amount, cpc_bid=cpc_bid)
    resolved: list[float | None] = []
    for key in (declaration.bid_amount_key, declaration.cpc_bid_key):
        declared = _declared_amount(arguments, key, micros=declaration.micros)
        if isinstance(declared, _Unreadable):
            return _BidInputs(unreadable_key=key)
        resolved.append(declared)
    bid_amount, cpc_bid = resolved
    return _BidInputs(bid_amount=bid_amount, cpc_bid=cpc_bid)


def evaluate_guardrails(
    tool_name: str,
    arguments: dict[str, Any],
    guardrails: Guardrails,
    *,
    budget_declaration: BudgetDeclaration | None = None,
    bid_declaration: BidDeclaration | None = None,
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

    inputs = _budget_inputs(arguments, budget_declaration)
    if inputs.unreadable_key is not None:
        # Fail CLOSED: the operator wrote a cap and the tool's declared
        # budget argument carries garbage, so the cap CANNOT be checked.
        # Allowing here would be the #414 silent bypass with extra steps.
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
    bids = _bid_inputs(arguments, bid_declaration)
    if bids.unreadable_key is not None:
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
            )
        except Exception:  # noqa: BLE001 — abstain on any unexpected error
            logger.debug("StrategyPolicyGate: abstaining on error", exc_info=True)
            return PolicyDecision(allowed=True)
