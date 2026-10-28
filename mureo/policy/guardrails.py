"""The ``## Guardrails`` section of STRATEGY.md, parsed (#879).

Split out of :mod:`mureo.policy.strategy_gate`, verbatim. The gate reads
STRATEGY.md through :mod:`mureo.context.strategy`, and loading that loads the
``mureo.context`` package — including
:mod:`mureo.context.monthly_budget`, which reads the same section for its
implied-daily-ceiling rung. Kept here, the parser imports nothing from
``mureo.context`` at runtime, so the monthly-budget reader and the gate both
import it at top level and share one reading of the section.
:mod:`mureo.policy.strategy_gate` re-exports every public name here, so
``from mureo.policy.strategy_gate import Guardrails`` keeps working.

Callers hand :func:`guardrails_from_entries` the entries
:func:`mureo.context.strategy.parse_strategy` returns; parsing the full text
is the caller's half, because that parser lives in ``mureo.context``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mureo.policy.currency_units import parse_currency_code

# How a bullet's number is read (#843) — split out for the file-size budget.
from mureo.policy.guardrail_numbers import to_float, to_int

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mureo.context.models import StrategyEntry

# The (case-insensitive) STRATEGY.md section that carries machine-readable
# hard rules. Unrecognized by strategy.py's section map, so it round-trips as
# a raw-heading entry titled "Guardrails".
GUARDRAILS_HEADING = "guardrails"


_BULLET_RE = re.compile(r"^\s*[-*]\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+?)\s*$")

#: Public alias of the bullet pattern above (#786). The configure dashboard
#: edits one bullet of this section in place, so it has to recognise a line
#: by exactly the rule that parses it — a second spelling would let the two
#: halves disagree about which line carries the value.
GUARDRAILS_BULLET_RE = _BULLET_RE


@dataclass(frozen=True)
class Guardrails:
    """Machine-readable hard rules parsed from STRATEGY.md ``## Guardrails``."""

    max_daily_budget_per_campaign: float | None = None
    max_daily_budget_increase_pct: float | None = None
    max_total_daily_budget: float | None = None
    max_lifetime_budget_per_campaign: float | None = None
    #: Bid caps. Distinct from budgets: a bid is a per-auction ceiling, not a
    #: spend budget, so it gets its own cap. ``max_cpc_bid_per_ad_group`` is in
    #: account-currency units — Google's ``cpc_bid_micros`` is converted from
    #: micros before comparison, mirroring the budget-micros convention.
    #: ``max_bid_amount_per_ad_set`` is in the SAME currency units once
    #: :attr:`currency` is declared, since Meta's ``bid_amount`` is then
    #: converted out of minor units like the budgets (#783); with no
    #: ``currency`` it stays minor units, as it always was.
    max_bid_amount_per_ad_set: float | None = None
    max_cpc_bid_per_ad_group: float | None = None
    #: The ad account's ISO 4217 currency, upper-cased (#783). Enforces
    #: nothing by itself — it is the UNIT the caps above are written in, and
    #: the only way this pure, I/O-free gate can know that Meta's
    #: minor-unit ``daily_budget`` / ``lifetime_budget`` / ``bid_amount``
    #: need dividing before they are compared with them. Absent ⇒ Meta
    #: amounts are compared as minor units (correct only for zero-decimal
    #: currencies such as JPY), which is why :meth:`is_empty` ignores it.
    currency: str | None = None
    blocked_operations: frozenset[str] = field(default_factory=frozenset)
    #: Learning-period reset refusals (#548). ``block_learning_resets``
    #: refuses every change mureo classifies as restarting an automated bid
    #: strategy's learning period. ``block_learning_resets_during_incident``
    #: refuses one only when the campaign is not positively known to be out
    #: of a learning period — the "stop stacking resets on an unstable
    #: campaign" rule, which therefore also fires when the state is unknown.
    #: Both default off, so the gate stays fail-open.
    block_learning_resets: bool = False
    block_learning_resets_during_incident: bool = False
    #: Delivery-impact rules for bulk exclusions / blocks / negative
    #: keywords (#547). Enforced by the dispatcher pre-flight
    #: (:mod:`mureo.mcp.exclusion_preflight`) rather than by this gate: the
    #: check needs one AWAITED platform read of the account's own recent
    #: delivery, and the ``PolicyGate`` v1 contract is synchronous and
    #: must stay pure and fast. They are parsed here so ``## Guardrails``
    #: stays one vocabulary with one parser. Resolved against their
    #: defaults by
    #: :func:`mureo.analysis.exclusion_impact.exclusion_impact_rules`.
    max_delivery_share_removed_pct: float | None = None
    max_cumulative_delivery_share_removed_pct: float | None = None
    exclusion_impact_window_days: int | None = None
    exclusion_impact_metrics: tuple[str, ...] = ()
    block_exclusions_without_impact_data: bool = False

    def is_empty(self) -> bool:
        """True when THIS gate has nothing to enforce.

        Blind to ``currency`` for the same reason it is blind to the
        ``exclusion_impact_*`` fields below: it declares a UNIT, not a rule,
        so an operator who wrote only a currency has asked for no
        enforcement at all.

        Deliberately blind to the ``exclusion_impact_*`` fields: they are
        enforced by the dispatcher pre-flight, not here, and counting them
        would switch on this gate's budget/bid scan — including the
        best-effort pattern fallback and its fail-closed deny on an
        exhausted scan — for an operator who wrote only an exclusion rule
        and no money cap at all.
        """
        return (
            self.max_daily_budget_per_campaign is None
            and self.max_daily_budget_increase_pct is None
            and self.max_total_daily_budget is None
            and self.max_lifetime_budget_per_campaign is None
            and self.max_bid_amount_per_ad_set is None
            and self.max_cpc_bid_per_ad_group is None
            and not self.blocked_operations
            and not self.block_learning_resets
            and not self.block_learning_resets_during_incident
        )


#: Accepted spellings of "on" for a boolean guardrail. Anything else — including
#: a typo — reads as OFF, matching the numeric rules' "a malformed value drops
#: that one rule" behaviour rather than silently enabling a refusal.
_TRUE_WORDS = frozenset({"true", "yes", "on", "1"})


def _to_bool(value: str) -> bool:
    return value.strip().lower() in _TRUE_WORDS


def _to_metrics(value: str) -> tuple[str, ...]:
    """``impressions, cost`` → ``("impressions", "cost")``, order preserved.

    Unknown names are dropped by
    :func:`~mureo.analysis.exclusion_impact.exclusion_impact_rules`, which
    owns the metric vocabulary; parsing stays a pure split so this module
    keeps no import on the analysis package.
    """
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def guardrail_bullets(content: str) -> dict[str, str]:
    """``- key: value`` bullets of a section body, last occurrence winning.

    Lines end at ``\\n`` only, as the section split in ``parse_strategy``
    does: a ``\\u2028`` or ``\\x85`` inside a line does not start a new one.
    """
    found: dict[str, str] = {}
    for line in content.split("\n"):
        match = _BULLET_RE.match(line)
        if match is not None:
            found[match.group(1).lower()] = match.group(2).strip()
    return found


def parse_guardrails(content: str) -> Guardrails:
    """Parse the body of a ``## Guardrails`` section into :class:`Guardrails`.

    Recognizes ``- key: value`` bullets. Unknown keys are ignored (forward
    compatibility). A malformed numeric value drops that one rule rather than
    failing the whole parse — and so does an unrecognized ``currency`` code,
    with one warning (see :func:`~mureo.policy.currency_units.
    parse_currency_code`).
    """
    bullets = guardrail_bullets(content)

    def number(key: str) -> float | None:
        raw = bullets.get(key)
        return None if raw is None else to_float(raw)

    window_raw = bullets.get("exclusion_impact_window_days")
    return Guardrails(
        max_daily_budget_per_campaign=number("max_daily_budget_per_campaign"),
        max_daily_budget_increase_pct=number("max_daily_budget_increase_pct"),
        max_total_daily_budget=number("max_total_daily_budget"),
        max_lifetime_budget_per_campaign=number("max_lifetime_budget_per_campaign"),
        max_bid_amount_per_ad_set=number("max_bid_amount_per_ad_set"),
        max_cpc_bid_per_ad_group=number("max_cpc_bid_per_ad_group"),
        currency=parse_currency_code(bullets.get("currency")),
        blocked_operations=frozenset(
            op.strip()
            for op in bullets.get("blocked_operations", "").split(",")
            if op.strip()
        ),
        max_delivery_share_removed_pct=number("max_delivery_share_removed_pct"),
        max_cumulative_delivery_share_removed_pct=number(
            "max_cumulative_delivery_share_removed_pct"
        ),
        exclusion_impact_window_days=(
            None if window_raw is None else to_int(window_raw)
        ),
        exclusion_impact_metrics=_to_metrics(
            bullets.get("exclusion_impact_metrics", "")
        ),
        block_exclusions_without_impact_data=_to_bool(
            bullets.get("block_exclusions_without_impact_data", "")
        ),
        block_learning_resets=_to_bool(bullets.get("block_learning_resets", "")),
        block_learning_resets_during_incident=_to_bool(
            bullets.get("block_learning_resets_during_incident", "")
        ),
    )


def guardrails_from_entries(entries: Sequence[StrategyEntry]) -> Guardrails:
    """The guardrails of parsed STRATEGY.md entries (empty if no section).

    The first entry titled ``Guardrails`` (case-insensitive) wins.
    """
    for entry in entries:
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            return parse_guardrails(entry.content)
    return Guardrails()


__all__ = [
    "GUARDRAILS_BULLET_RE",
    "GUARDRAILS_HEADING",
    "Guardrails",
    "guardrail_bullets",
    "guardrails_from_entries",
    "parse_guardrails",
]
