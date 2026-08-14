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
- :class:`ArgumentPaths` — the same declaration, for money that does not sit
  at a top-level argument key but NESTED, through objects, arrays and dynamic
  maps (#527). A bridged tool surface (someone else's tool definitions,
  forwarded verbatim) cannot carry ``_meta`` at all, so mureo declares those
  paths itself; a channel field accepts either a flat key (unchanged) or this.
- Their process-wide registries and register / lookup / reset helpers,
  populated by ``mureo.mcp.server`` from plugin tool metadata at import so the
  pure decision layer stays I/O-free and needs no plugin imports. They are
  keyed by BARE tool name, deliberately: every lookup here is reached with a
  tool name and nothing else — ``StrategyPolicyGate.evaluate`` sits behind the
  public two-argument :class:`~mureo.core.policy.PolicyGate` Protocol that
  third parties implement, and :mod:`mureo.policy.learning_reset` is a pure
  layer with no provider handle — so an identity-keyed registry would have
  nothing to resolve an identity from. It does not need one: mureo exposes at
  most one plugin tool per name (see :func:`~mureo.mcp.tool_provider.
  collect_plugin_tools`), so the declaration held under a name always belongs
  to the tool that name dispatches to. A *conflicting* re-registration is
  still announced rather than applied in silence — see
  :func:`_log_conflicting_registration` (#589).
- The same for one tool's ``annotations.readOnlyHint``
  (:func:`register_read_only_hint` / :func:`declared_read_only_hint` /
  :func:`reset_read_only_hints`) — so a pure decision that has to ask "is this
  a read?" can prefer the tool's own DECLARATION over the shape of its name.
- :func:`_declared_amount` and its numeric helpers (:func:`_saturate`, the
  :data:`_UNREADABLE` sentinel) — the single reader that turns one declared
  argument key or path into currency units, distinguishing "absent" from
  "present-but-unreadable" so the gate can fail closed on garbage.

Every public name here is re-exported from
:mod:`mureo.policy.strategy_gate` for import-path compatibility — see the
re-export block in that module.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

#: A path segment suffix meaning "descend every item of this array".
ARRAY_SUFFIX = "[]"

#: A whole path segment meaning "descend every value of this object".
#: Required to be EXPLICIT: a level whose keys are data rather than vocabulary
#: (a country code, a marketplace id, a currency) cannot be guessed at, and
#: guessing would be the one thing a declaration exists to avoid — silently
#: matching something adjacent to the money instead of the money.
WILDCARD = "*"


class _Descent(Enum):
    """A structural resolution step — descend into every child at this level."""

    ITEMS = ARRAY_SUFFIX
    VALUES = WILDCARD


#: One resolution step: a ``str`` indexes an object by EXACT key, a
#: :class:`_Descent` fans out over an array's items / an object's values.
_Step = str | _Descent


def _parse_path(spec: str) -> tuple[_Step, ...]:
    """Compile one dotted path spec into resolution steps.

    ``body.campaigns[].budgetCaps.countryMonetaryBudgetSettings.*.value`` →
    ``("body", "campaigns", ITEMS, "budgetCaps",
    "countryMonetaryBudgetSettings", VALUES, "value")``.

    Raises ``ValueError`` on a malformed spec (an empty segment, a stray
    bracket, a ``*`` glued to a name). The table that uses this is in-tree and
    compiled at import, so a typo must fail loudly in testing rather than
    quietly resolve to nothing — a path that silently never matches is an
    unenforced cap.
    """
    steps: list[_Step] = []
    for raw in spec.split("."):
        if raw == WILDCARD:
            steps.append(_Descent.VALUES)
            continue
        name = raw[: -len(ARRAY_SUFFIX)] if raw.endswith(ARRAY_SUFFIX) else raw
        if not name or any(c in name for c in "[]*"):
            raise ValueError(f"malformed declared argument path segment: {raw!r}")
        steps.append(name)
        if raw.endswith(ARRAY_SUFFIX):
            steps.append(_Descent.ITEMS)
    if not steps:
        raise ValueError("empty declared argument path")
    return tuple(steps)


def _resolve_path(arguments: dict[str, Any], steps: tuple[_Step, ...]) -> list[Any]:
    """Every value ``steps`` reaches in ``arguments`` (possibly none).

    Resolution is STRICT at every level, because the whole point of declaring a
    path is that it cannot drift onto a neighbour: a key step matches only an
    object carrying that exact key, an array step only an actual list, a
    wildcard step only an actual object. The first level that matches nothing
    ends the walk with "not found" — never with a value from somewhere else.

    Arrays (and wildcards) fan out element-wise, so a batch call resolves to
    one value per element; the caller takes the MAXIMUM across them, which is
    the same contract the best-effort scan reports (:attr:`PatternAmount.value`
    is the largest amount found) and the only safe one — a cap must be checked
    against the biggest amount the call proposes.

    Work is linear in the payload the host already parsed: each step keeps at
    most the nodes at one level of it, and only along the declared path.
    """
    nodes: list[Any] = [arguments]
    for step in steps:
        reached: list[Any] = []
        for node in nodes:
            if isinstance(step, str):
                if isinstance(node, dict) and step in node:
                    reached.append(node[step])
            elif step is _Descent.ITEMS:
                if isinstance(node, list):
                    reached.extend(node)
            elif isinstance(node, dict):
                reached.extend(node.values())
        if not reached:
            return []
        nodes = reached
    return nodes


@dataclass(frozen=True)
class ArgumentPaths:
    """One money channel's declared NESTED argument paths (#527).

    A :class:`BudgetDeclaration` / :class:`BidDeclaration` channel normally
    names a flat argument key. That is all a plugin authoring its own tools
    needs, but it cannot express where a BRIDGED surface carries money: the
    tools are someone else's, forwarded verbatim, and their amounts sit under
    arrays and dynamic maps, e.g.::

        body.campaigns[].budgets[].budgetValue.monetaryBudgetValue.monetaryBudget.value
        body.campaigns[].budgetCaps.countryMonetaryBudgetSettings.*.value
        body.targets[].bid.bid

    So a channel accepts either a flat key (``str``, behaviour unchanged) or
    this — one or more dotted path specs, all read as the SAME channel, the
    largest resolved amount winning. Several specs per channel is the normal
    case: one tool commonly declares alternative budget shapes and a call fills
    in whichever it uses.

    Written as strings rather than nested tuples because the table that holds
    them is meant to be read against a real tool schema by a human, and the
    dotted form is the shape those schemas are quoted in everywhere else in
    mureo. They are compiled once, at import (:func:`_parse_path`).
    """

    specs: tuple[str, ...]
    steps: tuple[tuple[_Step, ...], ...]

    @classmethod
    def parse(cls, *specs: str) -> ArgumentPaths:
        """Compile ``specs`` into a channel declaration (see :func:`_parse_path`)."""
        if not specs:
            raise ValueError("an ArgumentPaths declaration needs at least one path")
        return cls(specs=tuple(specs), steps=tuple(_parse_path(s) for s in specs))

    @property
    def label(self) -> str:
        """The declared paths, for an operator-facing message."""
        return " / ".join(self.specs)


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

    Either PROPOSAL channel may instead name :class:`ArgumentPaths` — nested
    paths, for a bridged surface whose money is not at a top-level key (#527).
    Everything above holds unchanged for a path; the two differences are in
    :func:`_declared_amount` (a path fans out over arrays and takes the
    largest match) and in the gate, where a path declaration is joined by the
    best-effort scan acting as a FLOOR (see :func:`raise_to_scan_floor`) — a
    flat key cannot drift, a bridged schema can.

    ``current_key`` is deliberately NOT path-capable. It names the *existing*
    budget, which is caller-supplied context rather than something the call
    proposes, so it is outside both the drift story and the floor: the scan
    never contributes to it (a baseline is not a proposal) and
    :func:`declares_paths` therefore never inspects it. Allowing a path there
    would create the one channel resolved with no floor under it.
    """

    daily_key: str | ArgumentPaths | None = None
    lifetime_key: str | ArgumentPaths | None = None
    current_key: str | None = None
    micros: bool = False


def _log_conflicting_registration(
    channel: str, tool_name: str, existing: object, incoming: object
) -> None:
    """Announce a second, DIFFERENT registration under the same tool name (#589).

    All three registries below are keyed by BARE tool name — no plugin, no
    distribution — and every one is last-write-wins, so a second registration
    replaces a guardrail rather than adding one. That is the right default and
    stays: reversing it to first-wins would silently break the deliberate
    override an out-of-tree caller makes (these registrars are public API,
    re-exported from :mod:`mureo.policy.strategy_gate` for the sibling
    bridges). What must not stay is the *silence* — a replaced budget key
    points the gate at an argument the called tool does not have, and a
    replaced ``readOnlyHint`` can turn a real mutation into a "read" that
    loses both its pattern-fallback money scan and its
    ``block_learning_resets`` refusal.

    Re-registering the SAME value is not a collision and says nothing: server
    startup and a test's ``reset_*`` + re-discovery both replay identical
    registrations, and a warning there would be noise that trains an operator
    to ignore the real one.

    This layer is pure and holds no plugin identity, so the message names the
    tool and both values but cannot name the distributions. The one collision
    where identity IS known — two installed plugins shipping the same tool
    name — is reported at collection time by
    :func:`mureo.mcp.tool_provider.collect_plugin_tools`, which names both.
    """
    if existing == incoming:
        return
    logger.warning(
        "conflicting %s declaration for tool '%s': %r was already registered "
        "and is being replaced by %r (last registration wins). These "
        "registries are keyed by tool name alone, so the usual cause is two "
        "installed distributions claiming the same name; check which one "
        "supplies '%s' before trusting the guardrail on it.",
        channel,
        tool_name,
        existing,
        incoming,
        tool_name,
    )


# Tool name → declaration. Populated by the MCP server from plugin tool
# metadata at import (see ``mureo.mcp.server``), so the pure decision layer
# stays I/O-free and the gate needs no plugin imports.
_BUDGET_DECLARATIONS: dict[str, BudgetDeclaration] = {}


def register_budget_declaration(tool_name: str, declaration: BudgetDeclaration) -> None:
    """Bind ``tool_name``'s budget argument keys (last registration wins).

    A conflicting re-registration is logged rather than refused — see
    :func:`_log_conflicting_registration`.
    """
    existing = _BUDGET_DECLARATIONS.get(tool_name)
    if existing is not None:
        _log_conflicting_registration("budget", tool_name, existing, declaration)
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

    Like its budget twin, a channel may instead name :class:`ArgumentPaths`
    for a bridged tool whose bid is nested (``body.targets[].bid.bid``) —
    see :class:`BudgetDeclaration` for what that changes (#527).
    """

    bid_amount_key: str | ArgumentPaths | None = None
    cpc_bid_key: str | ArgumentPaths | None = None
    micros: bool = False


# Tool name → bid declaration. Populated by the MCP server from plugin tool
# metadata at import (see ``mureo.mcp.server``), exactly like the budget
# registry above, so the pure decision layer stays I/O-free.
_BID_DECLARATIONS: dict[str, BidDeclaration] = {}


def register_bid_declaration(tool_name: str, declaration: BidDeclaration) -> None:
    """Bind ``tool_name``'s bid argument keys (last registration wins).

    A conflicting re-registration is logged rather than refused — see
    :func:`_log_conflicting_registration`.
    """
    existing = _BID_DECLARATIONS.get(tool_name)
    if existing is not None:
        _log_conflicting_registration("bid", tool_name, existing, declaration)
    _BID_DECLARATIONS[tool_name] = declaration


def bid_declaration_for(tool_name: str) -> BidDeclaration | None:
    """The bid declaration registered for ``tool_name``, or ``None``."""
    return _BID_DECLARATIONS.get(tool_name)


def reset_bid_declarations() -> None:
    """Drop every bid registration (tests; a re-discovery re-registers)."""
    _BID_DECLARATIONS.clear()


# Tool name → the tool's OWN ``annotations.readOnlyHint``. Populated by the
# MCP server from plugin tool metadata at import, exactly like the two money
# registries above, so the pure decision layer stays I/O-free. It holds only
# what a tool DECLARED: absence means "undeclared", never "read".
_READ_ONLY_HINTS: dict[str, bool] = {}


def register_read_only_hint(tool_name: str, read_only: bool) -> None:
    """Bind ``tool_name``'s declared ``readOnlyHint`` (last registration wins).

    Only ever called for a tool that actually declared one. A pure decision
    layer otherwise has nothing but the tool's NAME to go on, and a name shape
    is a guess where a declaration is evidence — registering the declaration
    lets the guess be demoted to a fallback.

    A conflicting re-registration is logged rather than refused — see
    :func:`_log_conflicting_registration`. The membership test is deliberate:
    a stored ``False`` is a DECLARED value, and ``.get()`` would read it as
    "nothing was registered" and skip the check on the one flip that matters.
    """
    if tool_name in _READ_ONLY_HINTS:
        _log_conflicting_registration(
            "readOnlyHint", tool_name, _READ_ONLY_HINTS[tool_name], read_only
        )
    _READ_ONLY_HINTS[tool_name] = read_only


def declared_read_only_hint(tool_name: str) -> bool | None:
    """``tool_name``'s DECLARED ``readOnlyHint``, or ``None`` when undeclared.

    ``None`` is "the tool said nothing" and must not be read as "read": the
    caller falls back to the name vocabulary for that case, which is the only
    signal left.
    """
    return _READ_ONLY_HINTS.get(tool_name)


def reset_read_only_hints() -> None:
    """Drop every hint registration (tests; a re-discovery re-registers)."""
    _READ_ONLY_HINTS.clear()


class _Unreadable:
    """Sentinel: a declared budget key is PRESENT but not a usable number.

    ``key`` names the exact declared key or path that carried the garbage. It
    is ``None`` on the shared :data:`_UNREADABLE` singleton, where the caller
    already knows which key it asked for; a multi-path channel sets it, so the
    deny message can quote the ONE path that failed rather than all of them.
    """

    __slots__ = ("key",)

    def __init__(self, key: str | None = None) -> None:
        self.key = key


_UNREADABLE = _Unreadable()


def declares_paths(*keys: str | ArgumentPaths | None) -> bool:
    """Is any of ``keys`` a nested-path declaration rather than a flat key?

    The gate's seam for the one behaviour that differs (#527): a path
    declaration that resolves nothing may fall back to the best-effort scan,
    because a bridged schema can move under mureo's feet. A flat key names an
    argument of a tool the declaring plugin owns, so its absence means "this
    call proposes nothing on that channel" — never drift — and that path stays
    byte-identical to what it has always done.
    """
    return any(isinstance(key, ArgumentPaths) for key in keys)


def unreadable_key_label(
    sentinel: _Unreadable, declared: str | ArgumentPaths | None
) -> str:
    """Name the declared key/path a :class:`_Unreadable` came from.

    Never empty for a real declaration, because the gate treats "no name" as
    "nothing was unreadable" and would then skip the deny it just decided on.
    """
    if sentinel.key is not None:
        return sentinel.key
    if isinstance(declared, ArgumentPaths):
        return declared.label
    return declared or ""


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
    arguments: dict[str, Any], key: str | ArgumentPaths | None, *, micros: bool
) -> float | _Unreadable | None:
    """Read one declared budget key — or path (#527) — as currency units.

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

    An :class:`ArgumentPaths` channel takes the same three outcomes through
    :func:`_path_amount`, with the array/wildcard fan-out resolved to its
    largest match first.
    """
    if isinstance(key, ArgumentPaths):
        return _path_amount(arguments, key, micros=micros)
    if not key or key not in arguments:
        return None
    return _scalar_amount(arguments[key], micros=micros)


def _scalar_amount(raw: Any, *, micros: bool) -> float | _Unreadable | None:
    """Read ONE present value as currency units (the reader both channels share).

    Split out of :func:`_declared_amount` unchanged so a declared flat key and
    a declared path judge the same value identically — a path must not become
    the lenient way to spell a declaration.
    """
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


def _path_amount(
    arguments: dict[str, Any], declared: ArgumentPaths, *, micros: bool
) -> float | _Unreadable | None:
    """The LARGEST amount ``declared``'s paths reach in ``arguments`` (#527).

    Same three outcomes as :func:`_declared_amount`, resolved across every
    path and every array/wildcard element:

    - ``None`` — no path resolved to a readable amount. Either the call
      carries no money on this channel, or the tool's schema has drifted
      since the table was written; the two are indistinguishable from here,
      which is one reason the gate never lets a path declaration stand alone
      — see :func:`raise_to_scan_floor`.
    - ``float`` — the maximum across every match, because a cap must be
      checked against the biggest amount the call proposes (the same contract
      the pattern scan reports).
    - :class:`_Unreadable` — a path reached a SCALAR that is garbage, naming
      that path. Content garbage is a fault worth denying on, exactly as on a
      flat declared key.

    One deliberate difference from a flat key: a path that lands on a nested
    object or array is treated as NOT FOUND rather than unreadable. On a flat
    key that shape is a plugin mis-declaring its own argument; here it is the
    schema having moved the number deeper, and re-scanning the payload
    best-effort enforces the cap on the amount actually being proposed, where
    denying would refuse a call whose money nobody ever looked at.
    """
    best: float | None = None
    for spec, steps in zip(declared.specs, declared.steps, strict=True):
        for leaf in _resolve_path(arguments, steps):
            if isinstance(leaf, (dict, list)):
                continue
            amount = _scalar_amount(leaf, micros=micros)
            if isinstance(amount, _Unreadable):
                return _Unreadable(spec)
            if amount is not None and (best is None or amount > best):
                best = amount
    return best


def _merge_pattern(channel: float | None, pattern: float | None) -> float | None:
    """Fold a pattern-scanned amount into a resolved channel (larger wins).

    Additive, never subtractive: whatever was resolved is kept, and the scan
    can only raise the figure a cap is checked against. Taking the larger of
    the two is the conservative direction — the check must see the biggest
    amount the call proposes.
    """
    if pattern is None:
        return channel
    if channel is None:
        return pattern
    return max(channel, pattern)


def raise_to_scan_floor(
    channels: tuple[float | None, float | None], scanned: float | None
) -> tuple[float | None, float | None]:
    """Raise both proposal channels of one family to the scanned amount (#527).

    **A path declaration raises the FLOOR; it does not replace the scan.**
    Whenever a family is declared by PATH, the best-effort scan runs too and
    the larger figure per channel wins — unconditionally, whether or not the
    declaration resolved anything.

    The invariant that matters where real money moves is *never check less
    than the scan alone would have checked*. Only an additive merge guarantees
    that structurally. The earlier design suppressed the scan whenever the
    declaration resolved any amount, and that boundary condition was wrong:
    several declared tools carry two physically independent money fields in
    one channel (an ad group's ``budgets[]…`` and its
    ``optimization.budgetSettings.dailyMinSpendValue``; a campaign's
    ``budgets[]…`` and its ``flights[].budget…``), so one trivially-resolving
    leaf silenced the scan for the whole tool and a SIBLING field whose shape
    had drifted went unchecked — a call the pattern scan had been catching
    since #517.

    Suppressing the scan was never buying safety, either: it was justified as
    stopping a stray budget-named field from false-tripping a cap, but those
    same tools were scanned unconditionally before they were declared, and
    #517 measured zero false positives across all 62 money leaves of the real
    manifest. What a declaration still buys is real and needs no suppression:
    exactness in the deny message (the resolved path is quoted), a DENY on an
    unreadable declared leaf, and visibility when a path stops resolving.

    Both channels take the same scanned figure because a heuristically matched
    key does not announce which cap it belongs to, so it is held to every cap
    the operator configured — the same reasoning as the undeclared path.
    """
    return _merge_pattern(channels[0], scanned), _merge_pattern(channels[1], scanned)
