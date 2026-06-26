"""Canonical Meta conversion counting from an Insights ``actions`` array.

Single source of truth for "how many conversions does this Meta row
report", shared by every live counter so they cannot drift (#340).

Why an exact-match allow-list, not a substring scan
---------------------------------------------------
A naive ``"lead" in action_type or "purchase" in action_type`` sum
over-counts for two reasons:

1. **Alias double-count.** Meta's Insights ``actions`` array returns a
   conversion under several overlapping ``action_type`` rows. The generic
   ``lead`` action_type is, by Meta's own definition, the *aggregate*
   ("All offsite leads plus all On-Facebook leads") of its components
   ``offsite_conversion.fb_pixel_lead`` + ``onsite_conversion.lead_grouped``;
   ``purchase`` / ``omni_purchase`` is the analogous roll-up. Because mureo
   fetches ``actions`` unfiltered, the aggregate row and its component rows
   co-occur — summing every ``*lead*`` / ``*purchase*`` row counts the same
   conversions two or three times.
2. **Substring false positives.** Operator-named custom conversions
   (``offsite_conversion.custom.<slug>``) carry free-text slugs that may
   contain ``"lead"`` / ``"purchase"`` and would be swept in uncontrolled.

Counting only the **deduped generic** action_types
(:data:`CONVERSION_ACTION_TYPES`) takes each conversion family once — the
aggregate already includes its components, so the components must NOT be
added on top.

Known limitation (deliberately out of scope here)
-------------------------------------------------
This counts a fixed default set of generic conversion events. An operator
whose objective reports only a component row (no generic aggregate), or who
wants a specific custom event, is not yet served — that needs an
operator-specified canonical-event selection (a separate, larger change).
This module fixes the over-count; it does not add per-account event config.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Deduped generic conversion ``action_type`` values. Each already rolls up
# its offsite/onsite component aliases, so counting these — and ONLY these —
# takes every conversion exactly once. Kept identical to the value the live
# MCP analysis path uses (``mureo.meta_ads._analysis._extract_cv``) so the
# two live counters agree byte-for-byte.
CONVERSION_ACTION_TYPES: frozenset[str] = frozenset(
    {"lead", "purchase", "complete_registration"}
)


def _safe_float(value: Any) -> float:
    """Coerce a Meta numeric-string value to float; 0.0 on junk/None."""
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def count_conversions_from_actions(actions: Any) -> float:
    """Sum the values of the canonical conversion ``action_type`` rows.

    ``actions`` is the Insights ``actions`` array — a list of
    ``{"action_type": str, "value": str|number}`` mappings. A non-list
    (``None`` / BYOD shape / malformed) yields ``0.0`` so callers can pass
    ``row.get("actions")`` directly. Non-mapping entries are skipped.
    """
    if not isinstance(actions, list):
        return 0.0
    return sum(
        _safe_float(entry.get("value"))
        for entry in actions
        if isinstance(entry, Mapping)
        and entry.get("action_type") in CONVERSION_ACTION_TYPES
    )
