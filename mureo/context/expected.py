"""The structured expected effect of a change (#848, ops history phase 1).

``rationale`` and ``reason`` say WHY in prose. Neither says what the change
should be measured on, so the later evaluation had to guess which of the
dozen figures it compared was the one that mattered. ``expected`` is that
declaration, made up front: "this should move CPA down", "this should
raise spend to 12,000 within a week".

The metric vocabulary is the outcome evaluator's own
(:mod:`mureo.analysis.outcome_eval`), so every declared metric is one the
evaluation can actually score, and a name it would silently treat as
neutral (``cpa_7d``, a plugin's own column) is refused at the boundary
instead of producing a verdict on nothing.

Pure: no I/O, no imports from the MCP layer. Shared by the decision record,
the mutating-tool parameter and the evaluation table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

#: Metrics an ``expected`` entry may name. A subset of the outcome
#: evaluator's vocabulary (pinned by a test), deliberately without its
#: long-form aliases so one metric has one spelling here.
EXPECTED_METRICS: Final[tuple[str, ...]] = (
    "cpa",
    "cpc",
    "cpl",
    "cpm",
    "conversions",
    "cvr",
    "ctr",
    "roas",
    "cost",
    "spend",
    "clicks",
    "impressions",
)

#: Which way the metric should move. ``hold`` is a real expectation — "the
#: budget shift must not cost conversions" — and is judged as such.
DIRECTION_UP: Final = "up"
DIRECTION_DOWN: Final = "down"
DIRECTION_HOLD: Final = "hold"
EXPECTED_DIRECTIONS: Final[tuple[str, ...]] = (
    DIRECTION_UP,
    DIRECTION_DOWN,
    DIRECTION_HOLD,
)

#: Long-form metric names a snapshot may use, mapped to the one spelling
#: above. Applied when a declared metric is matched against measured ones,
#: so ``cost_per_conversion`` in the figures meets ``cpa`` in ``expected``.
METRIC_ALIASES: Final[dict[str, str]] = {
    "cost_per_conversion": "cpa",
    "cost_per_acquisition": "cpa",
    "cost_per_click": "cpc",
    "cost_per_lead": "cpl",
    "cost_per_mille": "cpm",
    "conversion_rate": "cvr",
    "click_through_rate": "ctr",
    "return_on_ad_spend": "roas",
    # A baseline's ``cost`` and a snapshot's ``spend`` are the same money
    # (#888); ``spend`` is the STATE.json word, so it is the one kept.
    "cost": "spend",
}

#: One entry per metric at most, so the vocabulary size is the bound.
EXPECTED_MAX_ITEMS: Final[int] = len(EXPECTED_METRICS)

#: Longest observation horizon an entry may declare. A year is already far
#: past any window the automatic evaluation scores.
EXPECTED_HORIZON_MAX_DAYS: Final[int] = 365

#: Keys an entry may carry. Anything else is refused rather than dropped:
#: a misspelled ``horizon`` silently ignored would read as "no horizon".
_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {"metric", "direction", "target", "horizon_days", "primary"}
)

_SHAPE_HINT: Final = (
    "expected must be an array of "
    "{metric, direction, target?, horizon_days?, primary?} objects"
)

#: The code a declaration of several effects without exactly one
#: ``primary: true`` is refused with (#888). It leads the ``ValueError``
#: message, as ``write_denied: `` leads an automatic-closure skip, so a
#: caller can match on it while the rest of the sentence says how to fix it.
EXPECTED_PRIMARY_REQUIRED: Final = "expected_primary_required"


@dataclass(frozen=True)
class ExpectedEffect:
    """One declared expectation: ``metric`` should move ``direction``.

    metric: One of :data:`EXPECTED_METRICS`.
    direction: One of :data:`EXPECTED_DIRECTIONS`.
    target: The figure the change aims for, in the metric's own unit.
    horizon_days: How many days after the change it should be judged.
    primary: Whether this is the effect the verdict is read off (#888). One
        declared effect is primary by itself; of several, exactly one is.
    """

    metric: str
    direction: str
    target: float | int | None = None
    horizon_days: int | None = None
    primary: bool = False

    def __post_init__(self) -> None:
        """Normalise the two labels and refuse anything out of vocabulary."""
        object.__setattr__(self, "metric", _label(self.metric, "metric"))
        object.__setattr__(self, "direction", _label(self.direction, "direction"))
        if self.metric not in EXPECTED_METRICS:
            raise ValueError(
                f"expected metric {self.metric!r} is not one of "
                f"{list(EXPECTED_METRICS)}"
            )
        if self.direction not in EXPECTED_DIRECTIONS:
            raise ValueError(
                f"expected direction {self.direction!r} is not one of "
                f"{list(EXPECTED_DIRECTIONS)}"
            )
        _check_target(self.target)
        _check_horizon(self.horizon_days)
        if not isinstance(self.primary, bool):
            raise ValueError(
                f"expected primary must be true or false; got {self.primary!r}"
            )


def _label(value: Any, name: str) -> str:
    """A required vocabulary label, trimmed and lower-cased."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"expected {name} must be a non-empty string")
    return value.strip().lower()


def _check_target(value: Any) -> None:
    """``target`` is an optional finite number; ``bool`` is not a number."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expected target must be a number; got {value!r}")
    if not math.isfinite(value):
        raise ValueError("expected target must be a finite number")


def _check_horizon(value: Any) -> None:
    """``horizon_days`` is an optional whole number of days in range."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"expected horizon_days must be an integer; got {value!r}")
    if not 1 <= value <= EXPECTED_HORIZON_MAX_DAYS:
        raise ValueError(
            f"expected horizon_days must be between 1 and "
            f"{EXPECTED_HORIZON_MAX_DAYS}; got {value}"
        )


def _parse_item(item: Any) -> ExpectedEffect:
    """One entry, from its dict (or an already-built effect)."""
    if isinstance(item, ExpectedEffect):
        return item
    if not isinstance(item, dict):
        raise ValueError(f"{_SHAPE_HINT}; an item is not an object")
    unknown = sorted(str(key) for key in item if key not in _ALLOWED_KEYS)
    if unknown:
        raise ValueError(f"expected item has unknown key(s) {unknown}")
    for required in ("metric", "direction"):
        if required not in item:
            raise ValueError(f"expected item is missing {required!r}")
    return ExpectedEffect(
        metric=item["metric"],
        direction=item["direction"],
        target=item.get("target"),
        horizon_days=item.get("horizon_days"),
        primary=item.get("primary", False),
    )


def _check_primary(effects: tuple[ExpectedEffect, ...]) -> None:
    """Several effects need exactly one ``primary: true`` (#888)."""
    if len(effects) < 2:
        return
    marked = sum(1 for effect in effects if effect.primary)
    if marked != 1:
        raise ValueError(
            f"{EXPECTED_PRIMARY_REQUIRED}: expected declares {len(effects)} "
            f"effects and marks {marked} primary; mark exactly one with "
            '"primary": true, the metric the verdict is read off'
        )


def parse_expected(
    raw: Any, *, require_primary: bool = True
) -> tuple[ExpectedEffect, ...]:
    """Validate ``raw`` into effects, or raise ``ValueError`` naming why.

    ``None`` reads as "nothing declared" and returns ``()``. Every refusal
    names the offending part, because these messages are what an agent sees
    as ``invalid_args`` and has to correct from.

    ``require_primary`` is the rule for a NEW declaration: several effects
    need exactly one ``primary: true``, and a metric may not be named twice
    under two synonyms (``cost`` and ``spend``). A stored declaration is
    read with it off: one written before the rules existed may list several
    effects and mark none (the evaluation then takes the first), or name
    both synonyms; only the same name twice is refused there, as before.
    """
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError(_SHAPE_HINT)
    if len(raw) > EXPECTED_MAX_ITEMS:
        raise ValueError(
            f"expected may hold at most {EXPECTED_MAX_ITEMS} items; got {len(raw)}"
        )
    effects = tuple(_parse_item(item) for item in raw)
    seen: set[str] = set()
    for effect in effects:
        # Canonical for a new declaration, so ``cost`` and ``spend`` are one
        # metric; a stored one keeps the raw-name rule it was written under.
        name = canonical_metric(effect.metric) if require_primary else effect.metric
        if name in seen:
            raise ValueError(f"expected names metric {effect.metric!r} more than once")
        seen.add(name)
    if require_primary:
        _check_primary(effects)
    return effects


def expected_to_list(effects: tuple[ExpectedEffect, ...]) -> list[dict[str, Any]]:
    """Serialise effects; an unset optional key is omitted, not ``null``."""
    rendered: list[dict[str, Any]] = []
    for effect in effects:
        item: dict[str, Any] = {"metric": effect.metric, "direction": effect.direction}
        if effect.target is not None:
            item["target"] = effect.target
        if effect.horizon_days is not None:
            item["horizon_days"] = effect.horizon_days
        if effect.primary:
            item["primary"] = True
        rendered.append(item)
    return rendered


def canonical_metric(name: str) -> str:
    """``name`` trimmed, lower-cased and mapped through :data:`METRIC_ALIASES`."""
    key = name.strip().lower()
    return METRIC_ALIASES.get(key, key)


__all__ = [
    "DIRECTION_DOWN",
    "DIRECTION_HOLD",
    "DIRECTION_UP",
    "EXPECTED_DIRECTIONS",
    "EXPECTED_HORIZON_MAX_DAYS",
    "EXPECTED_MAX_ITEMS",
    "EXPECTED_METRICS",
    "EXPECTED_PRIMARY_REQUIRED",
    "METRIC_ALIASES",
    "ExpectedEffect",
    "canonical_metric",
    "expected_to_list",
    "parse_expected",
]
