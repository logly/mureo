"""Outcome thresholds from the operator's STRATEGY.md ``## Guardrails`` (#888).

The noise band and the volume floors the outcome verdict uses can be set
per workspace with four bullets (``outcome_noise_pct``,
``outcome_min_conversions``, ``outcome_min_impressions``,
``outcome_min_clicks``). They are read and parsed HERE, at the MCP layer,
and passed down as an :class:`~mureo.analysis.outcome_eval.OutcomeThresholds`:
this layer already imports both the evaluator and ``mureo.policy``, so
neither ``mureo.analysis`` nor ``mureo.context`` gains an edge onto
``mureo.policy`` (the delivery-collapse thresholds reach it through a kept
cycle, #879).

Fail-open, as :func:`mureo.analysis.delivery_collapse_config.
load_collapse_thresholds` is: an absent or unreadable STRATEGY.md yields the
defaults, and a bad bullet keeps its one default with a logged warning.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from mureo.analysis.delivery_collapse_config import resolve_strategy_path
from mureo.analysis.outcome_eval import DEFAULT_THRESHOLDS, OutcomeThresholds
from mureo.context.strategy import parse_strategy
from mureo.policy.guardrail_numbers import to_float, to_int
from mureo.policy.strategy_gate import GUARDRAILS_HEADING, guardrail_bullets

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

#: ``## Guardrails`` bullet key -> :class:`OutcomeThresholds` field. The
#: same registration pattern as ``delivery_collapse.GUARDRAIL_KEYS``.
GUARDRAIL_KEYS: Final[dict[str, str]] = {
    "outcome_noise_pct": "noise_pct",
    "outcome_min_conversions": "min_conversions",
    "outcome_min_impressions": "min_impressions",
    "outcome_min_clicks": "min_clicks",
}


def _guardrail_value(field: str, raw: str) -> float | int | None:
    """One bullet value, read and range-checked; ``None`` rejects it."""
    if field == "noise_pct":
        number = to_float(raw)
        return number if number is not None and 0 < number <= 100 else None
    count = to_int(raw)
    return count if count is not None and count >= 1 else None


def outcome_thresholds_from_guardrails(
    bullets: Mapping[str, str],
) -> OutcomeThresholds:
    """Thresholds from ``## Guardrails`` bullets (``key -> raw value``).

    Unknown keys are ignored. A value that cannot be used keeps that one
    default and logs a warning naming the key, so a typo in one bullet
    neither fails the read nor goes unnoticed.
    """
    values: dict[str, float | int] = {}
    for key, field in GUARDRAIL_KEYS.items():
        raw = bullets.get(key)
        if raw is None:
            continue
        value = _guardrail_value(field, raw)
        if value is None:
            logger.warning(
                "STRATEGY.md Guardrails %s: %r is not a usable value; "
                "keeping the default",
                key,
                raw,
            )
            continue
        values[field] = value
    # ``replace`` is typed per field; every field name comes from
    # GUARDRAIL_KEYS and every value passed its range check above.
    return replace(DEFAULT_THRESHOLDS, **values)  # type: ignore[arg-type]


def _guardrail_thresholds() -> OutcomeThresholds:
    """The workspace's thresholds, or the defaults when none are readable."""
    path = resolve_strategy_path()
    try:
        if not path.exists():
            return DEFAULT_THRESHOLDS
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning(
            "outcome thresholds: STRATEGY.md unreadable; using the defaults",
            exc_info=True,
        )
        return DEFAULT_THRESHOLDS
    for entry in parse_strategy(text):
        if entry.title.strip().lower() == GUARDRAILS_HEADING:
            bullets = guardrail_bullets(entry.content)
            return outcome_thresholds_from_guardrails(bullets)
    return DEFAULT_THRESHOLDS


def load_outcome_thresholds(noise_pct: object = None) -> OutcomeThresholds:
    """The thresholds one evaluation uses.

    Args:
        noise_pct: ``mureo_outcome_evaluate``'s explicit ``noise_pct``
            argument, which overrides the Guardrails / default band for
            that one call. ``None`` when the caller gave none.

    Raises:
        ValueError: ``noise_pct`` is not a number, or is outside (0, 100].
            The message names ``noise_pct``; the dispatcher reports it as
            ``invalid_args``.
    """
    thresholds = _guardrail_thresholds()
    if noise_pct is None:
        return thresholds
    if isinstance(noise_pct, bool) or not isinstance(noise_pct, (int, float, str)):
        raise ValueError("noise_pct must be a number")
    try:
        number = float(noise_pct)
    except ValueError as exc:
        raise ValueError("noise_pct must be a number") from exc
    return replace(thresholds, noise_pct=number)


__all__ = [
    "GUARDRAIL_KEYS",
    "load_outcome_thresholds",
    "outcome_thresholds_from_guardrails",
]
