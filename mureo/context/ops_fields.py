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

#: The suffix that marks a parameter as naming its target.
ID_SUFFIX: Final = "_id"

#: The suffix that marks a parameter as naming several targets.
IDS_SUFFIX: Final = "_ids"


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
    return key in _ID_KEYS or key.endswith(ID_SUFFIX)


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


def _is_scalar(value: Any) -> bool:
    return value is not None and not isinstance(value, (dict, list, tuple))


def derive_call_title(tool: str, arguments: Mapping[str, Any]) -> str:
    """A title for a change that left no ``action_log`` entry to describe it.

    The operation, the target its ``*_id`` parameters name, and the values
    it set: ``google_ads_budget_update budget b1: amount 12,000``. The value
    before the change is not known here, so none is shown.
    """
    target: list[str] = []
    values: list[str] = []
    for key, value in arguments.items():
        if not isinstance(key, str) or not _is_scalar(value):
            continue
        if key in _ID_KEYS:
            continue
        if key.endswith(ID_SUFFIX):
            target.append(f"{key[: -len(ID_SUFFIX)].replace('_', ' ')} {value}")
        else:
            values.append(f"{key} {_format_value(value)}")
    head = " ".join([tool, *target])
    detail = "; ".join(values)
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


def target_ids(params: Any) -> dict[str, Any]:
    """The ids a parameter map names its target by, not its account.

    ``budget_id``, ``campaign_id``, ``ad_group_id``, ``keyword_ids`` …;
    never ``id`` / ``customer_id`` / ``account_id``, which name the
    account the call ran against rather than what it changed.
    """
    if not isinstance(params, dict):
        return {}
    return {
        key: value
        for key, value in params.items()
        if isinstance(key, str)
        and key not in _ID_KEYS
        and (key.endswith(ID_SUFFIX) or key.endswith(IDS_SUFFIX))
    }


def entry_target_ids(entry: ActionLogEntry) -> dict[str, Any]:
    """Every target id an ``action_log`` entry records.

    From its ``reversible_params`` and ``applied_params``, then its own
    ``campaign_id`` / ``ad_id`` and ``entity_type`` + ``entity_id`` (a
    ``budget`` entity is ``budget_id``), which win where they overlap.
    """
    reversible = entry.reversible_params or {}
    found = {
        **target_ids(reversible.get("params")),
        **target_ids(entry.applied_params),
    }
    for key, value in (("campaign_id", entry.campaign_id), ("ad_id", entry.ad_id)):
        if value is not None:
            found[key] = value
    if entry.entity_type is not None and entry.entity_id is not None:
        found[f"{entry.entity_type}{ID_SUFFIX}"] = entry.entity_id
    return found


def _id_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return str(value)


def _all_named(ids: dict[str, Any], by: dict[str, Any]) -> bool:
    """Every id in ``ids`` appears in ``by`` with the same value."""
    return all(
        key in by and _id_value(by[key]) == _id_value(value)
        for key, value in ids.items()
    )


def _own_target(entry: ActionLogEntry, have: dict[str, Any]) -> dict[str, Any]:
    """The ids naming what ``entry`` itself changed.

    Its ``entity_type`` + ``entity_id`` when declared; otherwise every
    target id it records, so an entry naming more than the call did (an
    ad group inside the call's campaign) is never read as the call's.
    """
    if entry.entity_type is not None and entry.entity_id is not None:
        key = f"{entry.entity_type}{ID_SUFFIX}"
        return {key: have[key]}
    return have


def names_same_target(sent: Any, entry: ActionLogEntry) -> bool:
    """``sent`` and ``entry`` name the same target, exactly.

    Every target id ``sent`` names appears with the same value in
    ``entry``, and the entry's own target is among the ids ``sent`` names.
    ``False`` when ``sent`` names none: an untargeted call cannot be
    matched to an entry, only guessed at.
    """
    wanted = target_ids(sent)
    have = entry_target_ids(entry)
    return (
        bool(wanted)
        and _all_named(wanted, have)
        and _all_named(_own_target(entry, have), wanted)
    )


__all__ = [
    "ARROW",
    "ELLIPSIS",
    "IDS_SUFFIX",
    "ID_SUFFIX",
    "derive_call_title",
    "derive_title",
    "entry_target_ids",
    "fit_title",
    "names_same_target",
    "project_metrics",
    "target_ids",
]
