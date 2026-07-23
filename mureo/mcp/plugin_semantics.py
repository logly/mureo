"""Phase 2 of #114: derive safety semantics for plugin MCP tools and
promote *mutating* plugin calls into STATE.json's ``action_log``.

A plugin opts into richer treatment purely through **standard MCP**
metadata — no new mureo Protocol surface:

- ``Tool.annotations.readOnlyHint is True`` → the tool is a read; it
  stays in the dedicated plugin audit log only (no STATE.json write).
- Anything else (no annotations, ``readOnlyHint`` absent/false, or
  ``destructiveHint``) is treated as **mutating** (conservative
  default — undeclared ⇒ mutating, matching Phase 1).
- Optional ``Tool.meta["mureo"]``:
    - ``reversal``: a dict recorded verbatim into the action_log
      entry's ``reversible_params`` so ``rollback_plan_get`` can see
      the intent. NOTE: the rollback *planner* only builds an actual
      reversal when ``reversal["operation"]`` is in its built-in
      allow-list — arbitrary plugin operations are recorded for audit
      but not auto-reversible. Honest scope, documented.
    - ``throttle``: ``{"rate": float, "burst": int}`` → a dedicated
      Throttler for that tool; invalid/absent ⇒ shared default.

Mutations are promoted to the action_log **only when a STATE.json
already exists in cwd** — we never litter an arbitrary working
directory with a new STATE.json just because a plugin tool ran. The
plugin audit log (Phase 1) always captures the call regardless.
Promotion is best-effort and never raises (auditing/strategy
visibility must not break the tool call).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mureo.policy.strategy_gate import BidDeclaration, BudgetDeclaration
from mureo.throttle import ThrottleConfig

if TYPE_CHECKING:
    from mcp.types import Tool

logger = logging.getLogger(__name__)

# Phase 4 (#114): structural strategy parity. A built-in mutation gets
# an observation window (set contextually by its platform skill) so the
# daily-check evidence loop reviews the outcome. An arbitrary plugin has
# no per-platform skill to set one, so the mechanical promotion applies
# a conservative default window — long enough to avoid single-day-noise
# conclusions (daily-check requires ≥7 consecutive days) and matching
# the "keyword/creative changes 14 days" guidance in ActionLogEntry.
# A plugin may shorten/lengthen it via meta["mureo"]["observation_days"].
_DEFAULT_OBSERVATION_DAYS = 14


#: Accepted ``budget.unit`` spellings → whether the value is in micros.
_BUDGET_UNITS = {"currency": False, "micros": True}

#: Accepted ``bid.unit`` spellings → whether the value is in micros. Shares the
#: budget vocabulary: ``currency`` means "compare as-is" (minor units for the
#: ``bid_amount`` channel, currency units for ``cpc_bid``), ``micros`` divides
#: by 1e6 — exactly like the built-in ``cpc_bid_micros`` path.
_BID_UNITS = {"currency": False, "micros": True}


@dataclass(frozen=True)
class ToolSemantics:
    """Safety classification derived from a plugin tool's MCP metadata."""

    mutating: bool
    reversal: dict[str, Any] | None = None
    throttle: ThrottleConfig | None = None
    observation_days: int | None = None
    budget: BudgetDeclaration | None = None
    bid: BidDeclaration | None = None


def _parse_budget(raw: Any) -> BudgetDeclaration | None:
    """Parse ``meta["mureo"]["budget"]``, or ``None`` when unusable (#414).

    A malformed hint is rejected WHOLE rather than half-applied: a partial
    declaration would re-create the exact silent-underenforcement the seam
    exists to remove. Requires a dict carrying at least one of ``daily`` /
    ``lifetime`` as a non-blank string key name; ``current`` is optional;
    ``unit`` is ``currency`` (default) or ``micros``.
    """
    if not isinstance(raw, dict):
        return None
    unit = raw.get("unit", "currency")
    if not isinstance(unit, str) or unit not in _BUDGET_UNITS:
        return None

    def _key(name: str) -> str | None:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    daily = _key("daily")
    lifetime = _key("lifetime")
    if daily is None and lifetime is None:
        return None
    # A declared-but-unusable key name (non-str) is a mistake, not an
    # omission — refuse the whole declaration so it surfaces in testing
    # rather than silently dropping one cap.
    for name in ("daily", "lifetime", "current"):
        if name in raw and _key(name) is None:
            return None
    return BudgetDeclaration(
        daily_key=daily,
        lifetime_key=lifetime,
        current_key=_key("current"),
        micros=_BUDGET_UNITS[unit],
    )


def _parse_bid(raw: Any) -> BidDeclaration | None:
    """Parse ``meta["mureo"]["bid"]``, or ``None`` when unusable.

    The bid twin of :func:`_parse_budget`, held to the identical whole-or-
    nothing discipline: a partial declaration would re-create the exact silent
    underenforcement this seam exists to remove. Requires a dict carrying at
    least one of ``bid_amount`` / ``cpc_bid`` as a non-blank string key name;
    ``unit`` is ``currency`` (default) or ``micros``.
    """
    if not isinstance(raw, dict):
        return None
    unit = raw.get("unit", "currency")
    if not isinstance(unit, str) or unit not in _BID_UNITS:
        return None

    def _key(name: str) -> str | None:
        value = raw.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    bid_amount = _key("bid_amount")
    cpc_bid = _key("cpc_bid")
    if bid_amount is None and cpc_bid is None:
        return None
    # A declared-but-unusable key name (non-str) is a mistake, not an
    # omission — refuse the whole declaration so it surfaces in testing
    # rather than silently dropping one cap.
    for name in ("bid_amount", "cpc_bid"):
        if name in raw and _key(name) is None:
            return None
    return BidDeclaration(
        bid_amount_key=bid_amount,
        cpc_bid_key=cpc_bid,
        micros=_BID_UNITS[unit],
    )


def _meta_mureo(tool: Tool) -> dict[str, Any]:
    """Return ``meta["mureo"]`` if present, else ``{}``.

    MCP's ``Tool.meta`` field is aliased ``_meta``; a plugin author who
    builds ``Tool(meta=...)`` (the intuitive spelling) does NOT populate
    the real field — pydantic ``extra="allow"`` stashes it in
    ``__pydantic_extra__`` instead. Accept both so the documented and
    the intuitive spelling behave identically.
    """
    meta = getattr(tool, "meta", None)
    if not isinstance(meta, dict):
        extra = getattr(tool, "__pydantic_extra__", None)
        meta = extra.get("meta") if isinstance(extra, dict) else None
    if isinstance(meta, dict):
        section = meta.get("mureo")
        if isinstance(section, dict):
            return section
    return {}


def derive_semantics(tool: Tool) -> ToolSemantics:
    """Classify one plugin tool from standard MCP annotations + meta."""
    ann = getattr(tool, "annotations", None)
    read_only = bool(getattr(ann, "readOnlyHint", False) is True)
    mutating = not read_only

    section = _meta_mureo(tool)
    reversal = section.get("reversal")
    reversal = reversal if isinstance(reversal, dict) else None

    throttle: ThrottleConfig | None = None
    raw = section.get("throttle")
    if isinstance(raw, dict):
        try:
            throttle = ThrottleConfig(
                rate=float(raw["rate"]),
                burst=int(raw["burst"]),
                hourly_limit=(
                    int(raw["hourly_limit"])
                    if raw.get("hourly_limit") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError):
            throttle = None  # malformed hint → fall back to shared default

    observation_days: int | None = None
    raw_days = section.get("observation_days")
    # bool is an int subclass — exclude it; require a positive int.
    if isinstance(raw_days, int) and not isinstance(raw_days, bool) and raw_days > 0:
        observation_days = raw_days

    return ToolSemantics(
        mutating=mutating,
        reversal=reversal,
        throttle=throttle,
        observation_days=observation_days,
        budget=_parse_budget(section.get("budget")),
        bid=_parse_bid(section.get("bid")),
    )


def record_mutation_action_log(
    *,
    tool: str,
    source: str,
    reversal: dict[str, Any] | None,
    observation_days: int | None = None,
) -> None:
    """Append a plugin mutation to STATE.json's action_log. Never raises.

    No-op (jsonl audit still has it) when there is no STATE.json in cwd.
    Called only after a *successful* call; a failed mutation did not
    change platform state, so it is intentionally NOT promoted here —
    failed attempts live in the Phase 1 jsonl audit only (by design).

    Phase 4 (#114): an ``observation_due`` window is always set so the
    entry enters the same evidence/outcome-review loop a built-in
    mutation does (daily-check step 9 / ``_mureo-learning``). It is
    ``observation_days`` (when the plugin declared one) or the
    conservative default. ``metrics_at_action`` is intentionally left
    unset — capturing baseline metrics is platform-specific analytics
    that does not exist for an arbitrary plugin; the outcome review
    falls back to a qualitative read, by design.
    """
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        now = datetime.now(timezone.utc)
        days = observation_days or _DEFAULT_OBSERVATION_DAYS
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action=tool,
            platform=f"plugin:{source or 'unknown'}",
            summary=f"plugin tool {tool} (mutating)",
            command=tool,
            observation_due=(now + timedelta(days=days)).date().isoformat(),
            reversible_params=reversal,
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "plugin action_log promotion failed for tool %r", tool, exc_info=True
        )
