"""The fields of an automatically created decision record (#848).

A decision mureo writes on the agent's behalf still has to pass every bound
:class:`~mureo.context.decisions.DecisionRecord` enforces — and those bounds
REFUSE rather than truncate, because a human caller can shorten a sentence.
Nobody is holding this one, and refusing it would drop the action-log entry
it rides with. So the two machine-built fields are fitted here, before the
record is built: the title is cut with an ellipsis, and the figures keep only
what a decision's ``metrics`` may hold.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Final

from mureo.context.decisions import (
    DECISION_METRIC_VALUE_MAX_CHARS,
    DECISION_METRICS_MAX_KEYS,
    DECISION_TITLE_MAX_CHARS,
    _clean_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.models import ActionLogEntry

#: Marks a title that was cut to fit.
ELLIPSIS: Final = "…"

#: Separator between a value before and after the change.
ARROW: Final = " → "

#: Parameter names that identify the target rather than describe the change.
_ID_KEYS: Final[frozenset[str]] = frozenset({"id", "customer_id", "account_id"})
_ID_SUFFIX: Final = "_id"


def _format_value(value: Any) -> str:
    """A figure as an operator reads it: ``10000`` is ``10,000``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:,}"


def _target(entry: ActionLogEntry) -> str:
    parts: list[str] = []
    if entry.campaign_id:
        parts.append(f"campaign {entry.campaign_id}")
    if entry.ad_id:
        parts.append(f"ad {entry.ad_id}")
    if entry.entity_type and entry.entity_id:
        parts.append(f"{entry.entity_type} {entry.entity_id}")
    return " / ".join(parts)


def _is_identity(key: str) -> bool:
    return key in _ID_KEYS or key.endswith(_ID_SUFFIX)


def _changes(entry: ActionLogEntry, arguments: Mapping[str, Any]) -> list[str]:
    """``key before → after`` for every restorable value the call changed.

    The before-values are the ones ``reversible_params`` would restore; the
    after-values are the call's own arguments.
    """
    reversal = entry.reversible_params or {}
    params = reversal.get("params")
    if not isinstance(params, dict):
        return []
    changes: list[str] = []
    for key, before in params.items():
        if not isinstance(key, str) or _is_identity(key):
            continue
        after = arguments.get(key)
        if after is None or isinstance(after, (dict, list)) or after == before:
            continue
        changes.append(f"{key} {_format_value(before)}{ARROW}{_format_value(after)}")
    return changes


def fit_title(title: str) -> str:
    cleaned = _clean_text(title)
    if len(cleaned) <= DECISION_TITLE_MAX_CHARS:
        return cleaned
    return cleaned[: DECISION_TITLE_MAX_CHARS - len(ELLIPSIS)].rstrip() + ELLIPSIS


def derive_title(entry: ActionLogEntry, arguments: Mapping[str, Any]) -> str:
    """A one-line title from the operation, its target and what it changed.

    ``google_ads_budget_update campaign 123: amount 10,000 → 12,000``. When
    the values are not known, the entry's own one-line description is used
    instead; bounded to :data:`DECISION_TITLE_MAX_CHARS` with an ellipsis.
    """
    head = " ".join(part for part in (entry.action, _target(entry)) if part)
    detail = "; ".join(_changes(entry, arguments))
    if not detail:
        detail = entry.display_title or entry.summary or ""
    if detail.startswith(entry.action):
        # A recorder's summary that only repeats the operation adds nothing.
        detail = ""
    return fit_title(f"{head}: {detail}" if detail else head)


def _storable(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return len(_clean_text(value)) <= DECISION_METRIC_VALUE_MAX_CHARS
    return False


def project_metrics(raw: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The part of ``metrics_at_action`` a decision's ``metrics`` may hold.

    Flat, finite, short scalars only, at most
    :data:`DECISION_METRICS_MAX_KEYS` of them, in the entry's own order.
    The full map stays on the action-log entry; this is the decision's
    copy of the figures it was made on.
    """
    if not raw:
        return None
    kept: dict[str, Any] = {}
    for key, value in raw.items():
        if len(kept) >= DECISION_METRICS_MAX_KEYS:
            break
        if isinstance(key, str) and key.strip() and _storable(value):
            kept[key] = value
    return kept or None


__all__ = ["ARROW", "ELLIPSIS", "derive_title", "fit_title", "project_metrics"]
