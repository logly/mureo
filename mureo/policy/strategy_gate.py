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
_BUDGET_KEYS = ("daily_budget", "proposed_daily_budget", "amount")
_CURRENT_BUDGET_KEYS = ("current_daily_budget", "current")

_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")


@dataclass(frozen=True)
class Guardrails:
    """Machine-readable hard rules parsed from STRATEGY.md ``## Guardrails``."""

    max_daily_budget_per_campaign: float | None = None
    max_daily_budget_increase_pct: float | None = None
    max_total_daily_budget: float | None = None
    blocked_operations: frozenset[str] = field(default_factory=frozenset)

    def is_empty(self) -> bool:
        return (
            self.max_daily_budget_per_campaign is None
            and self.max_daily_budget_increase_pct is None
            and self.max_total_daily_budget is None
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
        elif key == "blocked_operations":
            blocked = {op.strip() for op in raw.split(",") if op.strip()}

    return Guardrails(
        max_daily_budget_per_campaign=max_per_campaign,
        max_daily_budget_increase_pct=max_increase_pct,
        max_total_daily_budget=max_total,
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
    # Google Ads budgets are sometimes expressed in micros.
    micros = arguments.get("budget_amount_micros")
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
) -> PolicyDecision:
    """Pure decision: does ``tool_name(arguments)`` violate ``guardrails``?

    Returns ``PolicyDecision(allowed=False, reason=...)`` on the first hard
    violation, else ``allowed=True``. No I/O.
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

    proposed = _proposed_budget(arguments)
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

        current = _current_budget(arguments)
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
            return evaluate_guardrails(tool_name, arguments, _load_guardrails())
        except Exception:  # noqa: BLE001 — abstain on any unexpected error
            logger.debug("StrategyPolicyGate: abstaining on error", exc_info=True)
            return PolicyDecision(allowed=True)
