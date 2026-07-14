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

logger = logging.getLogger(__name__)

# The (case-insensitive) STRATEGY.md section that carries machine-readable
# hard rules. Unrecognized by strategy.py's section map, so it round-trips as
# a raw-heading entry titled "Guardrails".
GUARDRAILS_HEADING = "guardrails"

# Argument keys that carry a proposed daily budget, in priority order.
# These are the BUILT-IN (Google/Meta) spellings; a plugin whose tools use a
# different vocabulary declares its own keys instead — see BudgetDeclaration.
_BUDGET_KEYS = ("daily_budget", "proposed_daily_budget", "amount")
_CURRENT_BUDGET_KEYS = ("current_daily_budget", "current")

_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True)
class BudgetDeclaration:
    """Where one tool carries its budget arguments (#414).

    Built-in Google/Meta tools are covered by the hard-coded key scan above.
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

    A declaration REPLACES the built-in key scan for that tool — **for every
    channel, not just the ones it names**. The plugin owns its argument
    vocabulary, so an unrelated field that happens to be spelled ``amount``
    must not false-trip a cap. The corollary: declaring only ``daily`` also
    opts the tool out of the built-in ``lifetime_budget`` / ``total_amount``
    scan, so a tool that carries a lifetime budget must declare
    ``lifetime`` too (a coincidental built-in spelling stops being honored
    the moment you declare anything).

    A declared key that is present but unreadable (``inf``, ``nan``, a
    bool, a non-numeric string) makes the gate DENY — see
    :func:`_declared_amount`.
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


class _Unreadable:
    """Sentinel: a declared budget key is PRESENT but not a usable number."""


_UNREADABLE = _Unreadable()


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
        value = float(raw)
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


@dataclass(frozen=True)
class _BudgetInputs:
    """The three budget channels one evaluation needs, already resolved."""

    proposed: float | None = None
    current: float | None = None
    lifetime: float | None = None
    #: The first declared key that was present but unreadable (⇒ deny).
    unreadable_key: str | None = None


def _budget_inputs(
    arguments: dict[str, Any], declaration: BudgetDeclaration | None
) -> _BudgetInputs:
    """Resolve the budget channels from declared keys, else the built-in scan."""
    if declaration is None:
        return _BudgetInputs(
            proposed=_proposed_budget(arguments),
            current=_current_budget(arguments),
            lifetime=_proposed_lifetime_budget(arguments),
        )
    resolved: list[float | None] = []
    for key in (
        declaration.daily_key,
        declaration.current_key,
        declaration.lifetime_key,
    ):
        value = _declared_amount(arguments, key, micros=declaration.micros)
        if isinstance(value, _Unreadable):
            return _BudgetInputs(unreadable_key=key)
        resolved.append(value)
    proposed, current, lifetime = resolved
    return _BudgetInputs(proposed=proposed, current=current, lifetime=lifetime)


@dataclass(frozen=True)
class Guardrails:
    """Machine-readable hard rules parsed from STRATEGY.md ``## Guardrails``."""

    max_daily_budget_per_campaign: float | None = None
    max_daily_budget_increase_pct: float | None = None
    max_total_daily_budget: float | None = None
    max_lifetime_budget_per_campaign: float | None = None
    blocked_operations: frozenset[str] = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        return (
            self.max_daily_budget_per_campaign is None
            and self.max_daily_budget_increase_pct is None
            and self.max_total_daily_budget is None
            and self.max_lifetime_budget_per_campaign is None
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
        elif key == "blocked_operations":
            blocked = {op.strip() for op in raw.split(",") if op.strip()}

    return Guardrails(
        max_daily_budget_per_campaign=max_per_campaign,
        max_daily_budget_increase_pct=max_increase_pct,
        max_total_daily_budget=max_total,
        max_lifetime_budget_per_campaign=max_lifetime,
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
                return float(v)
    # Google Ads budgets are sometimes expressed in micros —
    # budget_amount_micros on campaign tools, amount_micros on budget tools.
    for micros_key in ("budget_amount_micros", "amount_micros"):
        micros = arguments.get(micros_key)
        if isinstance(micros, (int, float)) and not isinstance(micros, bool):
            return float(micros) / 1_000_000
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
            return float(v)
    micros = arguments.get("total_amount_micros")
    if isinstance(micros, (int, float)) and not isinstance(micros, bool):
        return float(micros) / 1_000_000
    return None


def _current_budget(arguments: dict[str, Any]) -> float | None:
    for key in _CURRENT_BUDGET_KEYS:
        v = arguments.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def evaluate_guardrails(
    tool_name: str,
    arguments: dict[str, Any],
    guardrails: Guardrails,
    *,
    budget_declaration: BudgetDeclaration | None = None,
) -> PolicyDecision:
    """Pure decision: does ``tool_name(arguments)`` violate ``guardrails``?

    Returns ``PolicyDecision(allowed=False, reason=...)`` on the first hard
    violation, else ``allowed=True``. No I/O.

    ``budget_declaration`` (#414) names the argument keys carrying this
    tool's budget. When given it REPLACES the built-in Google/Meta key scan
    — the tool's own vocabulary is authoritative. Omitted (every built-in
    tool, and any plugin that has not declared) ⇒ unchanged behavior.
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
        if pct_cap is not None and current is not None and current > 0:
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

    total = arguments.get("projected_total_daily_budget")
    total_cap = guardrails.max_total_daily_budget
    if (
        total_cap is not None
        and isinstance(total, (int, float))
        and not isinstance(total, bool)
        and float(total) > total_cap
    ):
        return PolicyDecision(
            allowed=False,
            reason=(
                f"Projected total daily budget {float(total):,.0f} exceeds the "
                f"STRATEGY.md Guardrails cap of {total_cap:,.0f} "
                f"(max_total_daily_budget)."
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
            )
        except Exception:  # noqa: BLE001 — abstain on any unexpected error
            logger.debug("StrategyPolicyGate: abstaining on error", exc_info=True)
            return PolicyDecision(allowed=True)
