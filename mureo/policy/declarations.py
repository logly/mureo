"""Plugin budget/bid declaration machinery for the strategy policy gate.

Split out of :mod:`mureo.policy.strategy_gate` to keep that module within the
project file-size budget; the two form one logical unit (the gate imports
everything here). This is the *lower* half of the pair — it has no dependency
on ``strategy_gate`` — so it holds the pieces the gate's pure decision layer
builds on:

- :class:`BudgetDeclaration` / :class:`BidDeclaration` — how a plugin tool
  declares, in standard MCP metadata, where it carries its proposed budget
  (#414) or bid, so the built-in :class:`~mureo.policy.strategy_gate.StrategyPolicyGate`
  can enforce the operator's ``## Guardrails`` caps on a tool whose argument
  vocabulary differs from the built-in Google/Meta spellings.
- Their process-wide registries and register / lookup / reset helpers,
  populated by ``mureo.mcp.server`` from plugin tool metadata at import so the
  pure decision layer stays I/O-free and needs no plugin imports.
- :func:`_declared_amount` and its numeric helpers (:func:`_saturate`, the
  :data:`_UNREADABLE` sentinel) — the single reader that turns one declared
  argument key into currency units, distinguishing "absent" from
  "present-but-unreadable" so the gate can fail closed on garbage.

Every public name here is re-exported from
:mod:`mureo.policy.strategy_gate` for import-path compatibility — see the
re-export block in that module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetDeclaration:
    """Where one tool carries its budget arguments (#414).

    Built-in Google/Meta tools are covered by the hard-coded key scan in
    :mod:`mureo.policy.strategy_gate` (``_budget_inputs``).
    A plugin tool's arguments can be spelled anything, so the gate had no way
    to find its budget and silently treated every plugin mutation as
    "no budget proposed" — the operator's ``## Guardrails`` caps were
    unenforced for that platform, with no error or warning. A plugin closes
    that by declaring its keys in standard MCP metadata::

        Tool(
            name="acme_ads_update_budget",
            _meta={"mureo": {"budget": {"daily": "daily_budget_micros",
                                        "unit": "micros"}}},
            ...
        )

    ``unit`` is ``"currency"`` (default) or ``"micros"`` (value / 1e6).

    A declaration REPLACES the built-in key scan for the budgets the tool
    **proposes** — ``daily`` and ``lifetime`` — for every one of them, not just
    the ones it names. The plugin owns its argument vocabulary, so an unrelated
    field that happens to be spelled ``amount`` must not false-trip a cap. The
    corollary: declaring only ``daily`` also opts the tool out of the built-in
    ``lifetime_budget`` / ``total_amount`` scan, so a tool that carries a
    lifetime budget must declare ``lifetime`` too (a coincidental built-in
    spelling stops being honored the moment you declare anything).

    The two CALLER-supplied figures are the exception, and deliberately so.
    Neither is something the tool carries: the *existing* daily budget
    (``current_daily_budget``) and the account-wide *projected total*
    (``projected_total_daily_budget``) are context the skills compute and pass
    on a budget mutation, under mureo's own cross-provider convention, in
    currency units. A declaration does not replace them, so
    ``max_daily_budget_increase_pct`` and ``max_total_daily_budget`` go on
    working for a declaring tool. ``current`` may still be declared where a
    plugin really does carry the current budget itself, and that declaration
    wins; the projected total has no key at all, because it is never a tool
    argument.

    A declared key that is present but unreadable (``inf``, ``nan``, a
    bool, a non-numeric string) makes the gate DENY — see
    :func:`_declared_amount`. The convention keys are held to the same
    standard (#419).
    """

    daily_key: str | None = None
    lifetime_key: str | None = None
    current_key: str | None = None
    micros: bool = False


# Tool name → declaration. Populated by the MCP server from plugin tool
# metadata at import (see ``mureo.mcp.server``), so the pure decision layer
# stays I/O-free and the gate needs no plugin imports.
_BUDGET_DECLARATIONS: dict[str, BudgetDeclaration] = {}


def register_budget_declaration(tool_name: str, declaration: BudgetDeclaration) -> None:
    """Bind ``tool_name``'s budget argument keys (last registration wins)."""
    _BUDGET_DECLARATIONS[tool_name] = declaration


def budget_declaration_for(tool_name: str) -> BudgetDeclaration | None:
    """The declaration registered for ``tool_name``, or ``None``."""
    return _BUDGET_DECLARATIONS.get(tool_name)


def reset_budget_declarations() -> None:
    """Drop every registration (tests; a re-discovery re-registers)."""
    _BUDGET_DECLARATIONS.clear()


@dataclass(frozen=True)
class BidDeclaration:
    """Where one tool carries its *bid* arguments — the bid twin of #414.

    ``BudgetDeclaration`` closed the gap for budgets; bids had the same hole.
    The gate's bid extraction (:func:`_bid_inputs`) scans only the built-in
    Google/Meta spellings — Meta's ``bid_amount`` (minor units) and Google's
    ``cpc_bid_micros`` (micros) — so a plugin bid tool whose argument is spelled
    anything else was read as "no bid proposed" and sailed past
    ``max_bid_amount_per_ad_set`` / ``max_cpc_bid_per_ad_group``, silently: no
    startup error, no warning, on a surface where real money moves. A plugin
    closes that by declaring its keys in standard MCP metadata::

        Tool(
            name="acme_ads_update_bid",
            _meta={"mureo": {"bid": {"cpc_bid": "bid_cap_micros",
                                     "unit": "micros"}}},
            ...
        )

    A declaration names one or both of the two bid channels, mirroring how a
    ``BudgetDeclaration`` names its daily / lifetime / current channels:

    - ``bid_amount_key`` — capped by ``max_bid_amount_per_ad_set``, compared in
      account-currency MINOR units (like Meta's ``bid_amount``, direct).
    - ``cpc_bid_key`` — capped by ``max_cpc_bid_per_ad_group``, compared in
      account-currency units (like Google's ``cpc_bid_micros`` after ÷1e6).

    The channel a key names decides WHICH cap constrains it; ``micros`` decides
    the UNIT (``value / 1e6`` when set, direct otherwise) — the two are declared
    independently so a plugin states both "which guardrail caps this" and
    "is my value micros" explicitly. Like ``BudgetDeclaration``'s single
    ``micros`` flag, one declaration carries one unit for both channels: a bid
    tool proposes a single bid, so the common case names exactly one channel.

    A declaration REPLACES the built-in key scan for that tool (there are no
    caller-supplied convention keys for bids, so it replaces the whole bid
    scan): the plugin owns its argument vocabulary, so an unrelated field
    spelled ``bid_amount`` cannot false-trip a cap. A declared key that is
    present but unreadable (``inf``, ``nan``, a bool, a non-numeric string, a
    nested object) makes the gate DENY through the same :func:`_bid_inputs`
    choke point the built-in scan uses — see :func:`_declared_amount`.
    """

    bid_amount_key: str | None = None
    cpc_bid_key: str | None = None
    micros: bool = False


# Tool name → bid declaration. Populated by the MCP server from plugin tool
# metadata at import (see ``mureo.mcp.server``), exactly like the budget
# registry above, so the pure decision layer stays I/O-free.
_BID_DECLARATIONS: dict[str, BidDeclaration] = {}


def register_bid_declaration(tool_name: str, declaration: BidDeclaration) -> None:
    """Bind ``tool_name``'s bid argument keys (last registration wins)."""
    _BID_DECLARATIONS[tool_name] = declaration


def bid_declaration_for(tool_name: str) -> BidDeclaration | None:
    """The bid declaration registered for ``tool_name``, or ``None``."""
    return _BID_DECLARATIONS.get(tool_name)


def reset_bid_declarations() -> None:
    """Drop every bid registration (tests; a re-discovery re-registers)."""
    _BID_DECLARATIONS.clear()


class _Unreadable:
    """Sentinel: a declared budget key is PRESENT but not a usable number."""


_UNREADABLE = _Unreadable()


def _saturate(value: int | float) -> float:
    """``float(value)``, saturating an out-of-range ``int`` to infinity.

    Python ints are arbitrary precision but floats are not, so ``float(10**400)``
    raises ``OverflowError`` — and the downstream handler forwards the bare int
    happily. Every budget path here funnels through this helper so an oversized
    integer becomes ``inf`` (which exceeds any finite cap and denies) rather than
    an exception that bubbles up to ``StrategyPolicyGate.evaluate``'s blanket
    ``except`` and silently abstains — the exact bypass the guardrail exists to
    prevent. A string budget never reaches here (``float("9"*309)`` already
    saturates to ``inf`` without raising).
    """
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def _declared_amount(
    arguments: dict[str, Any], key: str | None, *, micros: bool
) -> float | _Unreadable | None:
    """Read one declared budget key as currency units.

    Three outcomes, and the distinction is the whole point of #414:

    - ``None`` — the key is absent (or ``null`` / blank, which mean the same
      thing): this call proposes no budget on that channel.
    - ``float`` — a usable amount (stringified numbers are accepted; plugins
      hit them in the wild when a JSON body round-trips through a form
      encoder).
    - :data:`_UNREADABLE` — the key IS present but carries garbage (a
      non-finite ``inf``/``nan``, a bool, a non-numeric string, a nested
      object). The caller must **deny**: silently treating it as "no
      proposal" would let ``{"spend_limit": "inf"}`` sail past every cap —
      re-opening the exact silent bypass this seam exists to close, and
      making the declared path weaker than the built-in scan (where a raw
      ``inf`` simply exceeds any finite cap and denies).
    """
    if not key or key not in arguments:
        return None
    raw = arguments[key]
    if raw is None:
        return None
    if isinstance(raw, bool):
        return _UNREADABLE
    if isinstance(raw, (int, float)):
        value = _saturate(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        try:
            value = float(stripped)
        except ValueError:
            return _UNREADABLE
    else:
        return _UNREADABLE
    if math.isnan(value) or math.isinf(value):
        return _UNREADABLE
    return value / 1_000_000 if micros else value
