"""How a ``## Guardrails`` bullet's numeric value is read (#843).

Split out of :mod:`mureo.policy.strategy_gate` to keep that module within
the project file-size budget; the gate imports both readers from here.

A value the readers cannot use comes back as ``None`` — the gate then
treats the rule as not declared — and that includes a non-finite number.
``nan > cap`` is always False, so a ``nan`` cap would silently allow every
amount while looking declared, and ``inf`` / ``1e999`` cap nothing at all.
"""

from __future__ import annotations

import math


def _to_float(value: str) -> float | None:
    """A finite bullet number (thousands separators tolerated), or ``None``."""
    try:
        number = float(value.replace(",", "").replace("_", "").strip())
    except (ValueError, AttributeError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value: str) -> int | None:
    """Whole-number bullet value, or ``None`` when it is not one.

    A fractional day count is dropped rather than truncated: silently
    turning ``30.5`` into ``30`` would report a window the operator did not
    write.
    """
    number = _to_float(value)
    if number is None:
        return None
    try:
        return int(number) if number == int(number) else None
    except (OverflowError, ValueError):
        # Unreachable while _to_float only returns finite numbers.
        return None
