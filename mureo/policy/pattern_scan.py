"""Best-effort budget/bid pattern scan for declaration-less plugin tools.

The third module of the policy trio (:mod:`mureo.policy.strategy_gate` is the
gate, :mod:`mureo.policy.declarations` is the exact-key seam). It exists for
one gap: a plugin whose tool surface arrives as a **manifest snapshot** — an
official-MCP bridge that forwards someone else's tool definitions verbatim —
cannot carry mureo ``_meta`` declarations, because mureo does not author those
tools. Such a provider can declare nothing, so every ``## Guardrails`` budget
and bid cap was silently unenforced for its mutations, on the one surface where
real money moves.

The fallback is deliberately **pattern-based and generic** — it encodes no
platform's argument vocabulary, only the shape of one:

- a key whose name contains ``budget`` or ``spend`` (case-insensitively)
  carries a proposed budget;
- a key whose name carries ``bid`` as a word fragment (``bid``, ``bid_amount``,
  ``bidAmount``, ``default_bid``, ``maxBid`` — but not ``forbidden``) carries a
  proposed bid;
- a *generically* named numeric leaf — exactly ``value`` or ``amount`` — carries
  the family of the nearest budget/bid-named ANCESTOR key, within a bounded
  window (:data:`_MAX_CONTEXT_SPAN`), so both
  ``{"monetaryBudget": {"value": 500}}`` and
  ``{"countryMonetaryBudgetSettings": {"US": {"value": 500}}}`` are budget
  proposals;
- a matching key that ALSO contains ``micros`` is divided by 1e6, mirroring the
  built-in Google micros convention.

Nested ``dict`` / ``list`` arguments are walked — deep enough to reach every
money leaf a real bridged manifest actually declares (:data:`_MAX_DEPTH`), with
the work bounded by a total node cap (:data:`_MAX_NODES`) rather than by
shallowness — because a bridged tool commonly buries its budget under six or
more wrapper objects. Apart from the two generic leaves above, only a key that
itself matches is read: crediting *every* value under a matching key would read
sibling identifiers as amounts and deny on a ten-digit resource id, so
``{"budget": {"value": 500, "campaignId": "1234567890"}}`` reads the amount and
not the id. Identifier-shaped keys (``*_id`` / ``*Id`` / ``*_ids``) are excluded
throughout, and mureo's own caller-supplied convention keys
(``current_daily_budget`` / ``projected_total_daily_budget``) are excluded from
the budget predicate — they are context the caller computes, not a proposal,
and reading one as a proposal would deny a *decrease*.

**Why the context window spans levels rather than one.** The levels between a
budget-named ancestor and its number are frequently *opaque map keys* that
carry no vocabulary of their own — country codes, marketplace ids, currency
codes — as in the real
``budgetCaps.countryMonetaryBudgetSettings.<CC>.value`` shape, where the only
semantic word sits two objects above the number. Requiring the family on the
immediate parent left 24 real daily budgets unguarded on that one tool. The
error direction is what makes the widening safe: because only ``value`` /
``amount`` are ever credited by context, a too-wide window *over*-detects (a
harmless number is checked against a cap it comfortably passes, or at worst
over-blocks a call the operator can re-issue with a declaration) while a
too-narrow one *under*-detects — silently letting real money past a cap. For a
guardrail check, over-detection is the documented safe side.

**Bounds, and what running out of them means.** The walk is bounded by depth
(:data:`_MAX_DEPTH`) and by total processed nodes (:data:`_MAX_NODES`, the DoS
guard). :attr:`PatternAmount.value` is contractually *the LARGEST amount
found*, and the gate compares exactly that against the cap — so any truncation
that could hide a larger amount must NOT be reported as a confident answer,
whether or not something was read first:

- **node cap** → :data:`SCAN_EXHAUSTED_NODES`, always, ``best`` or no ``best``.
  The walk was abandoned globally: neither "no money here" nor "this is the
  maximum" is a claim the scan can make about a payload it never finished.
- **depth cap, inside a money context** → :data:`SCAN_EXHAUSTED_DEPTH`,
  likewise regardless of ``best``. A budget/bid-named subtree the scan could
  not descend into is exactly where a larger unchecked amount hides.
- **depth cap, no money context** → silent (``value=None`` or the reading).
  Ordinary bounded-heuristic truncation on a subtree with nothing suggesting
  money in it; denying every deeply-nested honest call would cost availability
  for no safety. Documented honest limit.

Either sentinel makes :mod:`mureo.policy.strategy_gate` refuse the call, naming
the actual cause and pointing at declarations. Returning a small early reading
from a stopped walk is how a 99,000,000 proposal once passed a 10,000 cap.

Honest limits, since best-effort must not be mistaken for exhaustive: a scalar
inside a list has no key of its own and is not read; a generic leaf more than
:data:`_MAX_CONTEXT_SPAN` levels below its family name is not found; an
unrelated numeric field that happens to be budget-named reads as a proposal and
can over-block; when a bound is exhausted after one amount was already read, a
larger amount elsewhere in the payload may go unseen. All of these resolve the
same way — declare the exact keys (see :mod:`mureo.policy.declarations`), which
always take precedence over this scan.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.policy.declarations import _UNREADABLE, _saturate, _Unreadable

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "SCAN_EXHAUSTED_DEPTH",
    "SCAN_EXHAUSTED_NODES",
    "PatternAmount",
    "has_pattern_fallback",
    "is_bid_key",
    "is_budget_key",
    "is_scan_exhausted",
    "register_pattern_fallback_tool",
    "reset_pattern_fallback_tools",
    "scan_bid_amount",
    "scan_budget_amount",
]

#: Reported as :attr:`PatternAmount.unreadable_key` when the scan stopped
#: GLOBALLY on :data:`_MAX_NODES` without having read a single amount. The
#: walk was abandoned wherever it happened to be, so "no amount found" would
#: be a claim about a payload the scan never finished reading.
SCAN_EXHAUSTED_NODES = "<scan exhausted: payload too large>"

#: Reported as :attr:`PatternAmount.unreadable_key` when :data:`_MAX_DEPTH`
#: cut off a branch that was INSIDE an active money context — the key named
#: this family, or an enclosing one did and the context window was still open
#: — and no amount was read anywhere. A budget-named subtree that the scan
#: could not descend into is precisely where an unchecked amount would hide.
#:
#: A depth cut on a branch with NO money context is deliberately NOT reported:
#: that is ordinary bounded-heuristic truncation on a subtree with nothing
#: suggesting money in it, and denying every deeply-nested honest call would
#: cost availability for no safety.
SCAN_EXHAUSTED_DEPTH = "<scan exhausted: money nested deeper than the scan descends>"

_SCAN_EXHAUSTED_KEYS = frozenset({SCAN_EXHAUSTED_NODES, SCAN_EXHAUSTED_DEPTH})


def is_scan_exhausted(unreadable_key: str | None) -> bool:
    """Is ``unreadable_key`` one of the exhaustion sentinels?

    The seam :mod:`mureo.policy.strategy_gate` uses to tell "the scan could
    not finish" apart from "this tool's budget argument carries garbage" —
    both fail closed, but they need different words for the operator.
    """
    return unreadable_key in _SCAN_EXHAUSTED_KEYS


#: How deep the argument walk goes. NOT a DoS guard — :data:`_MAX_NODES` is
#: (see there); this bound only exists so a self-referential-looking tree
#: terminates, and it must therefore be set by what real schemas do, not by a
#: guess. Measured against a real 85-tool Amazon Ads manifest: every
#: budget/bid-carrying numeric leaf across those tools sits at walk depth ≤ 11
#: — the deepest being
#: ``body.campaigns[].flights[].budget.budgetValue.monetaryBudgetValue.marketplaceSettings[].monetaryBudget.value``
#: (each array costs two levels, the list then its item) — so 12 is that
#: measurement plus one level of headroom. The previous value of 8 silently
#: truncated 12 of those 38 money leaves, i.e. the global-campaign
#: (``marketplaceSettings``) and flight budgets sailed past every cap.
#: Guarded by ``tests/test_strategy_gate_pattern_fallback.py`` →
#: ``TestRealAmazonManifestReachability``.
_MAX_DEPTH = 12

#: The actual DoS guard: how many nodes one scan may *process* before it stops.
#: A depth bound alone never bounded the work — a single flat dict with a
#: million keys is depth 1 — so bounding nodes is what keeps a hostile payload
#: from turning a policy check into a long walk, and it lets
#: :data:`_MAX_DEPTH` follow real schemas instead of doubling as a budget for
#: total effort.
#:
#: Charged at the moment work is DONE, never when a branch is merely queued:
#: one unit per container popped off the queue, one per scalar entry actually
#: examined. Charging at enqueue time made the budget consumable by branches
#: that were never looked at — which, combined with LIFO order, let a large
#: unrelated sibling starve a money-bearing one (see :func:`_scan`).
#:
#: This is a DoS bound, NOT a coverage knob: reaching it makes the scan report
#: :data:`SCAN_EXHAUSTED_NODES` and the gate REFUSE the call, so the value
#: trades availability against bounded work — never against safety, since the
#: truly pathological payload still fails closed either way.
#:
#: Sized against the WORST realistic shape, not the cheapest one. Cost per
#: campaign varies ~10x across the real Amazon budget shapes, because a global
#: campaign repeats its budget per marketplace
#: (``…monetaryBudgetValue.marketplaceSettings[].monetaryBudget.value``, 23
#: marketplaces in the enum):
#:
#: ===============================  ===============  ====================
#: shape                            nodes/campaign   exhausts at (this cap)
#: ===============================  ===============  ====================
#: no ``marketplaceSettings``                    10              100,000
#: 2 marketplaces                                19               52,632
#: 5 marketplaces                                31               32,258
#: 23 marketplaces (full enum)                  103                9,709
#: ===============================  ===============  ====================
#:
#: The previous 100,000 exhausted at **971** full-marketplace campaigns — and
#: nothing schema-side prevents that call: the ``campaigns`` / ``budgets``
#: arrays of every money tool carry no ``maxItems``. A legitimate bulk update
#: of ~1,000 global campaigns would have been refused. At 1,000,000 the same
#: call costs 10.3% of the bound and 2,000 costs 20.6%, so an honest bulk call
#: cannot be denied at any plausible batch size.
#:
#: The cost of the extra headroom is bounded and linear (~0.85 µs/node): a
#: payload that burns the whole budget takes ~0.85 s per scan (~1.7 s for the
#: budget and bid channels together) — and it must itself be ~1,000,000 nodes,
#: i.e. tens of MB the host already parsed. Doubling again to 2,000,000 would
#: double that worst-case latency to buy headroom (19k full-marketplace
#: campaigns) nobody plausibly needs.
_MAX_NODES = 1_000_000

#: mureo's cross-provider caller-supplied budget context. Never a proposal —
#: see :data:`mureo.policy.strategy_gate._CONVENTION_CURRENT_KEY`.
_CONVENTION_KEYS = frozenset({"current_daily_budget", "projected_total_daily_budget"})

#: Leaf names that mean nothing on their own but everything in context. Kept to
#: exactly these two (case-insensitively): a real bridged surface wraps the
#: number in a named object — ``{"monetaryBudget": {"value": 500}}`` — so the
#: family is on an ANCESTOR and the leaf is generic. Widening this set would
#: start crediting ordinary fields to whatever object happens to enclose them.
_CONTEXTUAL_LEAF_KEYS = frozenset({"value", "amount"})

#: How far below a budget/bid-named ancestor key a generic
#: :data:`_CONTEXTUAL_LEAF_KEYS` leaf is still credited to that family.
#:
#: Counted in *named object* levels: ``0`` means the leaf's own enclosing
#: object is the one the matching key named
#: (``{"monetaryBudget": {"value": …}}``), ``1`` means one object further down
#: (``{"countryMonetaryBudgetSettings": {"US": {"value": …}}}`` — the real
#: shape this exists for). An array level costs nothing, because a list and
#: its items are the same named collection. Past the window the context
#: lapses; a nearer matching ancestor resets it to ``0``.
#:
#: ``3`` is the real requirement (``1``) plus headroom, chosen on the
#: over-detect-rather-than-under-detect reasoning in the module docstring.
#: Verified against a real 85-tool Amazon Ads manifest: with this window the
#: scan matches every money-carrying tool and no other tool at all.
_MAX_CONTEXT_SPAN = 3


@dataclass(frozen=True)
class PatternAmount:
    """One scan result: the largest match, or the key that made it unreadable.

    ``value`` is the LARGEST finite amount found under a matching key (the
    conservative choice: the cap must be checked against the biggest thing the
    call proposes). ``unreadable_key`` names the first matching key that was
    present but carried a non-finite number, so the gate can fail closed the
    same way it does for the built-in scan and the declared path.
    """

    value: float | None = None
    unreadable_key: str | None = None


def _is_identifier_key(key: str) -> bool:
    """Is ``key`` an identifier rather than an amount?

    ``budget_id`` contains ``budget`` and ``bid_id`` contains ``bid``, but both
    carry a resource id — typically a ten-digit integer that would exceed every
    cap and deny an otherwise fine call. The boundary is explicit (``_id`` /
    ``_ids`` / camelCase ``Id`` / ``Ids``) rather than a bare ``endswith("id")``
    because ``bid`` itself ends in ``id``.
    """
    lowered = key.lower()
    return (
        lowered in {"id", "ids"}
        or lowered.endswith(("_id", "_ids"))
        or key.endswith(("Id", "Ids"))
    )


def is_budget_key(key: str) -> bool:
    """Does ``key`` name a proposed budget?

    Case-insensitive ``budget`` or ``spend``. ``spend`` joins the vocabulary
    because a real bridged surface caps daily outlay under that word rather
    than "budget" (``dailyMinSpendValue``), and a spend figure is the same
    real money the daily-budget guardrail exists to bound.
    """
    if key in _CONVENTION_KEYS or _is_identifier_key(key):
        return False
    lowered = key.lower()
    return "budget" in lowered or "spend" in lowered


def is_bid_key(key: str) -> bool:
    """Does ``key`` carry ``bid`` as a word fragment (not ``forbidden``)?

    Accepts ``bid``, a ``bid``-prefixed name (``bid_amount``, ``bidAmount``), a
    ``bid``-suffixed one (``default_bid``, ``maxBid``), an underscore-delimited
    ``bid`` anywhere, and a camelCase ``Bid``. A bare substring test would drag
    in ``forbidden`` and ``morbidity``.
    """
    if _is_identifier_key(key):
        return False
    lowered = key.lower()
    if "bid" not in lowered:
        return False
    return (
        lowered.startswith("bid")
        or lowered.endswith("bid")
        or "bid_" in lowered
        or "_bid" in lowered
        or "Bid" in key
    )


def _is_micros_key(key: str) -> bool:
    return "micros" in key.lower()


#: A thousands-grouped decimal: ``1,000``, ``-1,234,567.89``. Strictly
#: grouped on purpose. The looser "digits and commas" reading would swallow
#: ``"1,5"`` — which is *one and a half* in most of Europe — and re-read it as
#: fifteen, a 10x over-read of a real-money figure. Anything that is not
#: unambiguous grouping stays ignored, which is this scan's documented default.
_GROUPED_NUMBER_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _degrouped(text: str) -> float | None:
    """``"1,000,000"`` → ``1000000.0``; anything else → ``None``.

    A JSON body that round-trips through a form encoder or a spreadsheet
    export commonly arrives with grouped numerals, and ``float()`` rejects
    them — so a real budget would read as "no proposal" and sail past the cap.
    """
    if _GROUPED_NUMBER_RE.match(text) is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:  # pragma: no cover — the regex already guarantees this
        return None


def _read_amount(key: str, raw: Any) -> float | _Unreadable | None:
    """Read one matching key's value as an amount in currency units.

    Three outcomes, mirroring :func:`mureo.policy.declarations._declared_amount`
    with ONE deliberate difference: a non-numeric value is *ignored* rather than
    treated as unreadable. The declared path knows the key really is a budget,
    so garbage there is a fault worth denying on; here the key was matched by a
    heuristic, and ``{"budget_type": "DAILY"}`` is an ordinary enum, not an
    attack. A present-but-non-finite NUMBER still denies — that is the overflow
    / ``NaN`` bypass this whole layer exists to close.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = _saturate(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError:
            grouped = _degrouped(stripped)
            if grouped is None:
                return None
            value = grouped
    else:
        return None
    if not math.isfinite(value):
        return _UNREADABLE
    return value / 1_000_000 if _is_micros_key(key) else value


def _matched_key(
    key: str, context: str | None, matches: Callable[[str], bool]
) -> str | None:
    """Which key makes ``key`` an amount of this family, or ``None``.

    Either the key itself, or — for a generic ``value`` / ``amount`` leaf —
    the nearest matching ANCESTOR key still inside the context window (the
    walk in :func:`_scan` decides what is in window; ``context`` here is
    already ``None`` when it has lapsed). The returned name is what decides
    micros scaling and what a deny message quotes, so a contextual match
    reports the ancestor: "countryMonetaryBudgetSettings" says something,
    "value" does not.

    ``context`` is only ever set from a key that satisfied THIS scan's
    ``matches``, so a bid ancestor can never credit a budget leaf or the
    reverse — the two families never blur.
    """
    if matches(key):
        return key
    if context is None or _is_identifier_key(key):
        return None
    if key.lower() not in _CONTEXTUAL_LEAF_KEYS:
        return None
    return context


def _child_context(
    key: Any,
    context: str | None,
    span: int,
    matches: Callable[[str], bool],
) -> tuple[str | None, int]:
    """The ``(context, span)`` a child object/array inherits under ``key``.

    Three outcomes, in order:

    - ``key`` matches this scan's family → *it* becomes the context, span
      reset to ``0``. A nearer name always wins over a further one.
    - an active context is still inside :data:`_MAX_CONTEXT_SPAN` → carried
      down one level further.
    - otherwise → no context. (A non-``str`` key names no family, so it can
      only carry an existing context, never establish one; its subtree is
      still walked.)
    """
    if isinstance(key, str) and matches(key):
        return key, 0
    if context is not None and span < _MAX_CONTEXT_SPAN:
        return context, span + 1
    return None, 0


def _scan(arguments: Any, matches: Callable[[str], bool]) -> PatternAmount:
    """Walk ``arguments``, returning the largest amount under a matching key.

    ``matches`` is the key predicate (:func:`is_budget_key` /
    :func:`is_bid_key`). Each node carries the nearest matching ancestor key
    and how far below it the node sits, so a generic leaf can be credited to
    that ancestor (see :func:`_matched_key` and :data:`_MAX_CONTEXT_SPAN`).
    A list passes its own context through to its items unchanged — a list and
    its items are the same named collection, so ``{"budgets": [{"value":
    500}]}`` costs no window. The first unreadable match short-circuits: the
    gate denies on it, so there is nothing to gain from scanning further.

    **Traversal order is deterministic and money-first.** The queue is a
    ``deque``. A child is *promising* when its key matches the family or it is
    still inside an active context window; promising children of one node are
    collected in document order and pushed to the FRONT as a block, everything
    else goes to the back. Two properties matter and both were bugs:

    - **priority** — without it a plain LIFO drained whichever branch happened
      to be queued last, so a large unrelated sibling could burn the node
      budget before a money-bearing branch was popped at all;
    - **document order within a group** — ``appendleft`` per child while
      iterating forward REVERSES a node's promising children, so one matching
      key's big collection was walked end→front and its first entries (where a
      real proposal usually sits) were the ones dropped under pressure.

    **Bounds and what hitting one means.** :data:`_MAX_DEPTH` bounds a branch,
    :data:`_MAX_NODES` bounds total processed nodes (charged on pop / on
    examining a scalar — never when a branch is merely queued, or the budget
    would again be consumed by work not done). Because ``value`` promises the
    LARGEST amount, exhaustion outranks whatever was read so far:

    - :data:`_MAX_NODES` → always :data:`SCAN_EXHAUSTED_NODES`.
    - :data:`_MAX_DEPTH` → :data:`SCAN_EXHAUSTED_DEPTH` when the cut branch was
      inside an active money context (its key named this family, or an
      enclosing one did and the window was still open) — a subtree the scan
      could not descend into is exactly where a larger amount hides. A depth
      cut with NO money context stays silent: nothing about that subtree
      suggested money, and denying every deeply-nested honest call would cost
      availability for no safety.

    Either sentinel makes the gate FAIL CLOSED. Neither "there is no money
    here" nor "this is the maximum" is sayable about a payload the scan did not
    finish reading.
    """
    best: float | None = None
    visited = 0
    nodes_exhausted = False
    depth_exhausted_in_context = False
    # (node, depth, nearest matching ancestor key, levels below that ancestor)
    queue: deque[tuple[Any, int, str | None, int]] = deque([(arguments, 0, None, 0)])
    while queue:
        if visited >= _MAX_NODES:
            nodes_exhausted = True
            break
        node, depth, context, span = queue.popleft()
        visited += 1
        if depth > _MAX_DEPTH:
            # ``context is not None`` is precisely "inside a money-named
            # subtree, or the cut key itself matched" — see _child_context.
            if context is not None:
                depth_exhausted_in_context = True
            continue
        # Promising children are collected in DOCUMENT order and pushed to the
        # front as a block (``extendleft(reversed(...))``). Calling
        # ``appendleft`` per child while iterating forward would reverse them,
        # so one matching key's big collection got walked end→front and its
        # first — usually real — entries were the ones dropped under pressure.
        promising: list[tuple[Any, int, str | None, int]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    child = _child_context(key, context, span, matches)
                    entry = (value, depth + 1, *child)
                    if child[0] is not None:
                        promising.append(entry)
                    else:
                        queue.append(entry)
                    continue
                visited += 1
                if visited > _MAX_NODES:
                    nodes_exhausted = True
                    break
                if not isinstance(key, str):
                    continue
                matched = _matched_key(key, context, matches)
                if matched is None:
                    continue
                amount = _read_amount(matched, value)
                if isinstance(amount, _Unreadable):
                    return PatternAmount(unreadable_key=matched)
                if amount is not None and (best is None or amount > best):
                    best = amount
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    entry = (item, depth + 1, context, span)
                    # Items of a list that is itself in a money context are
                    # promising too — ``{"budgets": [{"value": 500}]}``.
                    if context is not None:
                        promising.append(entry)
                    else:
                        queue.append(entry)
                else:
                    visited += 1
                    if visited > _MAX_NODES:
                        nodes_exhausted = True
                        break
        if promising:
            queue.extendleft(reversed(promising))
    # Any truncation that could hide a LARGER amount must not be reported as a
    # confident answer: ``PatternAmount.value`` means "the largest amount
    # found", and the gate compares exactly that against the cap. Returning a
    # small early reading from a walk that stopped mid-payload is how a
    # 99,000,000 proposal passed a 10,000 cap. So exhaustion wins over ``best``.
    # Node exhaustion is the stronger claim (the walk stopped globally) and so
    # wins when both fired.
    if nodes_exhausted:
        return PatternAmount(unreadable_key=SCAN_EXHAUSTED_NODES)
    if depth_exhausted_in_context:
        return PatternAmount(unreadable_key=SCAN_EXHAUSTED_DEPTH)
    return PatternAmount(value=best)


def scan_budget_amount(arguments: dict[str, Any]) -> PatternAmount:
    """Largest budget-shaped amount in ``arguments`` (best-effort)."""
    return _scan(arguments, is_budget_key)


def scan_bid_amount(arguments: dict[str, Any]) -> PatternAmount:
    """Largest bid-shaped amount in ``arguments`` (best-effort)."""
    return _scan(arguments, is_bid_key)


# Tool names eligible for the fallback: MUTATING plugin tools, registered by
# ``mureo.mcp.server`` from plugin tool metadata at import — the same shape as
# the declaration registries next door, so the pure decision layer stays
# I/O-free and needs no plugin imports. Membership alone does not enable the
# scan for a channel that HAS a declaration: the gate consults the declaration
# first and the scan only fills the gap it leaves.
_PATTERN_FALLBACK_TOOLS: set[str] = set()


def register_pattern_fallback_tool(tool_name: str) -> None:
    """Mark ``tool_name`` as eligible for the pattern fallback."""
    _PATTERN_FALLBACK_TOOLS.add(tool_name)


def has_pattern_fallback(tool_name: str) -> bool:
    """Is ``tool_name`` a registered declaration-less plugin mutation?"""
    return tool_name in _PATTERN_FALLBACK_TOOLS


def reset_pattern_fallback_tools() -> None:
    """Drop every registration (tests; a re-discovery re-registers)."""
    _PATTERN_FALLBACK_TOOLS.clear()
