"""Declaration resolution — turn one call's arguments into budget/bid channels.

The middle layer of the policy trio's decision path, split out of
:mod:`mureo.policy.strategy_gate` to keep that module within the project
file-size budget. The two form one logical unit: everything here answers
"what does this call PROPOSE?", and the gate next door answers "does that
violate the operator's caps?".

One function per family — :func:`_budget_inputs` and :func:`_bid_inputs` —
and each is the SINGLE choke point where the three ways an amount reaches a
cap are resolved and reconciled:

1. the built-in Google/Meta key scan (the module-level spellings below);
2. an exact declaration (:mod:`mureo.policy.declarations`) — a plugin's
   ``_meta`` keys, or mureo's own nested PATHS for a bridged surface;
3. the best-effort pattern scan (:mod:`mureo.policy.pattern_scan`).

Both functions return a frozen ``*Inputs`` record whose every channel is
either ``None`` or a FINITE float, with anything present-but-unreadable
collapsed into ``unreadable_key`` so the gate fails closed exactly once — no
downstream comparison ever sees ``inf``/``nan``. Keeping that reconciliation
in one place per family is deliberate: scoping it per-comparison is what let
the overflow/NaN bypass exist in the first place.

Every name here is re-exported from :mod:`mureo.policy.strategy_gate` for
import-path compatibility — see the re-export block in that module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mureo.policy.declarations import (
    BidDeclaration,
    BudgetDeclaration,
    _declared_amount,
    _saturate,
    _Unreadable,
    declares_paths,
    raise_to_scan_floor,
    unreadable_key_label,
)
from mureo.policy.pattern_scan import scan_bid_amount, scan_budget_amount

__all__ = [
    "_BID_AMOUNT_KEYS",
    "_BUDGET_KEYS",
    "_CONVENTION_CURRENT_KEY",
    "_CONVENTION_TOTAL_KEY",
    "_CURRENT_BUDGET_KEYS",
    "_BidInputs",
    "_BudgetInputs",
    "_bid_inputs",
    "_budget_inputs",
    "_current_budget",
    "_projected_total",
    "_proposed_bid_amount",
    "_proposed_budget",
    "_proposed_cpc_bid",
    "_proposed_lifetime_budget",
]

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
    arguments: dict[str, Any],
    declaration: BudgetDeclaration | None,
    *,
    pattern_fallback: bool = False,
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
        if pattern_fallback:
            # Best-effort key-shape scan for a declaration-less plugin
            # mutation. Folded into BOTH proposal channels because a matched
            # key's channel is exactly what the scan cannot know: the amount is
            # held to every budget cap the operator configured rather than
            # slipping past the one it happens not to be named for. The two
            # CALLER-supplied channels (current / projected total) are
            # deliberately untouched — they are mureo's own convention keys,
            # already read above, and are never a proposal.
            scanned = scan_budget_amount(arguments)
            if scanned.unreadable_key is not None:
                return _BudgetInputs(unreadable_key=scanned.unreadable_key)
            proposed, lifetime = raise_to_scan_floor(
                (proposed, lifetime), scanned.value
            )
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
            return _BudgetInputs(unreadable_key=unreadable_key_label(declared, key))
        resolved.append(declared)
    proposed, current, lifetime = resolved
    if pattern_fallback and declares_paths(
        declaration.daily_key, declaration.lifetime_key
    ):
        # A PATH declaration raises the floor, it does not replace the scan
        # (#527) — unconditionally, whatever it resolved. See
        # :func:`raise_to_scan_floor` for why the earlier "only when nothing
        # resolved" boundary under-enforced. Flat KEY declarations are
        # untouched: they keep replacing the scan exactly as they always have.
        scanned = scan_budget_amount(arguments)
        if scanned.unreadable_key is not None:
            # An exhausted scan still fails closed even though the declaration
            # resolved something: what it could not finish reading may hold a
            # LARGER amount than the declared paths found.
            return _BudgetInputs(unreadable_key=scanned.unreadable_key)
        proposed, lifetime = raise_to_scan_floor((proposed, lifetime), scanned.value)
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
    arguments: dict[str, Any],
    declaration: BidDeclaration | None = None,
    *,
    pattern_fallback: bool = False,
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
        if pattern_fallback:
            # The bid twin of the budget fallback above, folded into both bid
            # channels for the same reason: a heuristically matched key does
            # not announce whether it is an ad-set bid cap or a CPC bid, so it
            # is held to whichever caps the operator configured.
            scanned = scan_bid_amount(arguments)
            if scanned.unreadable_key is not None:
                return _BidInputs(unreadable_key=scanned.unreadable_key)
            bid_amount, cpc_bid = raise_to_scan_floor(
                (bid_amount, cpc_bid), scanned.value
            )
        return _BidInputs(bid_amount=bid_amount, cpc_bid=cpc_bid)
    resolved: list[float | None] = []
    for key in (declaration.bid_amount_key, declaration.cpc_bid_key):
        declared = _declared_amount(arguments, key, micros=declaration.micros)
        if isinstance(declared, _Unreadable):
            return _BidInputs(unreadable_key=unreadable_key_label(declared, key))
        resolved.append(declared)
    bid_amount, cpc_bid = resolved
    if pattern_fallback and declares_paths(
        declaration.bid_amount_key, declaration.cpc_bid_key
    ):
        # The bid twin of the floor merge in :func:`_budget_inputs` (#527): a
        # mureo-declared PATH into a bridged schema never checks less than the
        # best-effort scan alone would have.
        scanned = scan_bid_amount(arguments)
        if scanned.unreadable_key is not None:
            return _BidInputs(unreadable_key=scanned.unreadable_key)
        bid_amount, cpc_bid = raise_to_scan_floor((bid_amount, cpc_bid), scanned.value)
    return _BidInputs(bid_amount=bid_amount, cpc_bid=cpc_bid)
