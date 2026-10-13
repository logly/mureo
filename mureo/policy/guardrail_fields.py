"""The catalog of ``## Guardrails`` fields — one row per rule (#843).

:class:`~mureo.policy.strategy_gate.Guardrails` defines WHAT the gate
enforces; this table describes each field for everything that has to show
or edit it: its kind (which decides how a value is validated and written),
its unit, its allowed range and the i18n key its human-readable name lives
under. The configure dashboard and its ``/api/strategy/guardrails`` route
read it, and so can any web extension that wants to render the same names.

It is the single source of truth for that description. A test enumerates
the dataclass against it, so a new field cannot ship without a row — and
another enumerates the rows against ``i18n.json``, so a row cannot ship
without a label and a one-line description in every locale.

Pure data, no I/O and no imports beyond the standard library, so the
policy package stays import-light.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "GUARDRAIL_FIELDS",
    "GUARDRAIL_KINDS",
    "GuardrailField",
    "GuardrailKind",
    "guardrail_field",
]

GuardrailKind = Literal[
    "money",
    "percent",
    "integer_days",
    "bool",
    "currency",
    "string_set",
    "metric_set",
]

#: Every kind a row may carry, for validation and for clients that switch on it.
GUARDRAIL_KINDS: Final[tuple[str, ...]] = (
    "money",
    "percent",
    "integer_days",
    "bool",
    "currency",
    "string_set",
    "metric_set",
)

#: Unit tags. ``currency`` means "the account's currency units" — the code
#: itself is the ``currency`` field, so a client renders it from there.
_MONEY_UNIT: Final = "currency"
_PERCENT_UNIT: Final = "%"
_DAYS_UNIT: Final = "days"

#: The longest look-back the exclusion-impact rules accept. Mirrors
#: ``mureo.analysis.exclusion_impact.rules.MAX_WINDOW_DAYS`` (a test pins the
#: two together); spelled here so this module needs no analysis import.
_MAX_WINDOW_DAYS: Final = 365

_I18N_PREFIX: Final = "guardrails.field"


@dataclass(frozen=True)
class GuardrailField:
    """How one ``## Guardrails`` bullet is described, validated and labelled.

    ``minimum`` / ``maximum`` are inclusive bounds on a numeric value
    (``None`` = unbounded on that side) and are ``None`` for every
    non-numeric kind. ``label_key`` is the ``i18n.json`` key of the field's
    display name; :attr:`desc_key` is its one-line description.
    """

    key: str
    kind: GuardrailKind
    unit: str | None
    minimum: float | None
    maximum: float | None
    label_key: str

    @property
    def desc_key(self) -> str:
        """The ``i18n.json`` key of the field's one-line description."""
        return f"{_I18N_PREFIX}.{self.key}.desc"


def _row(
    key: str,
    kind: GuardrailKind,
    unit: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> GuardrailField:
    return GuardrailField(
        key=key,
        kind=kind,
        unit=unit,
        minimum=minimum,
        maximum=maximum,
        label_key=f"{_I18N_PREFIX}.{key}.label",
    )


def _money(key: str) -> GuardrailField:
    # A cap of 0 is a legitimate "refuse any positive amount"; a negative
    # cap is a typo the gate would read as "refuse everything" silently.
    return _row(key, "money", _MONEY_UNIT, 0, None)


#: In :class:`~mureo.policy.strategy_gate.Guardrails` field order.
GUARDRAIL_FIELDS: Final[tuple[GuardrailField, ...]] = (
    _money("max_daily_budget_per_campaign"),
    # A raise can legitimately exceed 100% (doubling a small budget).
    _row("max_daily_budget_increase_pct", "percent", _PERCENT_UNIT, 0, None),
    _money("max_total_daily_budget"),
    _money("max_lifetime_budget_per_campaign"),
    _money("max_bid_amount_per_ad_set"),
    _money("max_cpc_bid_per_ad_group"),
    _row("currency", "currency"),
    _row("blocked_operations", "string_set"),
    _row("block_learning_resets", "bool"),
    _row("block_learning_resets_during_incident", "bool"),
    # A share of the account's own delivery: a whole is 100%.
    _row("max_delivery_share_removed_pct", "percent", _PERCENT_UNIT, 0, 100),
    _row(
        "max_cumulative_delivery_share_removed_pct",
        "percent",
        _PERCENT_UNIT,
        0,
        100,
    ),
    _row(
        "exclusion_impact_window_days", "integer_days", _DAYS_UNIT, 1, _MAX_WINDOW_DAYS
    ),
    _row("exclusion_impact_metrics", "metric_set"),
    _row("block_exclusions_without_impact_data", "bool"),
)

_BY_KEY: Final[dict[str, GuardrailField]] = {row.key: row for row in GUARDRAIL_FIELDS}


def guardrail_field(key: str) -> GuardrailField | None:
    """The catalog row for ``key``, or ``None`` when no such field exists."""
    return _BY_KEY.get(key)
