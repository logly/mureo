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

- a key whose name contains ``budget`` (case-insensitively) carries a proposed
  budget;
- a key whose name carries ``bid`` as a word fragment (``bid``, ``bid_amount``,
  ``bidAmount``, ``default_bid``, ``maxBid`` — but not ``forbidden``) carries a
  proposed bid;
- a matching key that ALSO contains ``micros`` is divided by 1e6, mirroring the
  built-in Google micros convention.

Nested ``dict`` / ``list`` arguments are walked (bounded by
:data:`_MAX_DEPTH`), because a bridged tool commonly nests its payload under a
resource object. Only a key that itself matches is read: crediting every value
*underneath* a matching key would read sibling identifiers as amounts and deny
on a ten-digit resource id. For the same reason identifier-shaped keys
(``*_id`` / ``*Id`` / ``*_ids``) are excluded, and mureo's own caller-supplied
convention keys (``current_daily_budget`` / ``projected_total_daily_budget``)
are excluded from the budget predicate — they are context the caller computes,
not a proposal, and reading one as a proposal would deny a *decrease*.

Honest limits, since best-effort must not be mistaken for exhaustive: a scalar
inside a list has no key of its own and is not read; a budget spelled without
the word ``budget`` (a bare ``amount`` outside the built-in scan's reach) is
not found; an unrelated numeric field that happens to be budget-named reads as
a proposal and can over-block. All of these resolve the same way — declare the
exact keys (see :mod:`mureo.policy.declarations`), which always take
precedence over this scan.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mureo.policy.declarations import _UNREADABLE, _saturate, _Unreadable

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "PatternAmount",
    "has_pattern_fallback",
    "is_bid_key",
    "is_budget_key",
    "register_pattern_fallback_tool",
    "reset_pattern_fallback_tools",
    "scan_bid_amount",
    "scan_budget_amount",
]

#: How deep the argument walk goes. Real tool payloads nest two or three
#: levels; the bound keeps a pathological (or hostile) argument tree from
#: turning a policy check into a stack walk.
_MAX_DEPTH = 8

#: mureo's cross-provider caller-supplied budget context. Never a proposal —
#: see :data:`mureo.policy.strategy_gate._CONVENTION_CURRENT_KEY`.
_CONVENTION_KEYS = frozenset({"current_daily_budget", "projected_total_daily_budget"})


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
    """Does ``key`` name a proposed budget? (case-insensitive ``budget``)"""
    if key in _CONVENTION_KEYS or _is_identifier_key(key):
        return False
    return "budget" in key.lower()


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


def _scan(arguments: Any, matches: Callable[[str], bool]) -> PatternAmount:
    """Walk ``arguments``, returning the largest amount under a matching key.

    ``matches`` is the key predicate (:func:`is_budget_key` /
    :func:`is_bid_key`). The first unreadable match short-circuits: the gate
    denies on it, so there is nothing to gain from scanning further.
    """
    best: float | None = None
    stack: list[tuple[Any, int]] = [(arguments, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > _MAX_DEPTH:
            continue
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
                    continue
                if not isinstance(key, str) or not matches(key):
                    continue
                amount = _read_amount(key, value)
                if isinstance(amount, _Unreadable):
                    return PatternAmount(unreadable_key=key)
                if amount is not None and (best is None or amount > best):
                    best = amount
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
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
