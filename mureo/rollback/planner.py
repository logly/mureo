"""Plan a rollback from an :class:`ActionLogEntry`.

Contract:
- Read-only actions (``list_*``, ``get_*``, ``analyze_*``, etc.)
  return ``None``. Nothing to reverse.
- Write actions without a ``reversible_params`` hint return a plan
  with :data:`RollbackStatus.NOT_SUPPORTED`, so the caller can surface
  *why* no rollback is possible.
- Write actions with a well-formed hint return a plan the caller can
  execute by invoking ``plan.operation`` with ``plan.params``.
- Hints carrying ``caveats`` are treated as :data:`RollbackStatus.PARTIAL`
  — the configuration change can be undone but its side effects (spend,
  impressions served) cannot.

**Trust model.** ``reversible_params`` is authored by the same agent
that performed the original action, and is therefore untrusted input
for the rollback executor: a compromised or prompt-injected agent
could otherwise log a "reversal" that points to a destructive
operation. This module enforces that only operations explicitly
listed in :data:`_ALLOWED_OPERATIONS` are planned, and that each plan
carries only the keys that operation declares. Executors (Task #26)
must still re-authorize against the same policy gate used for forward
actions.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from mureo.rollback.models import RollbackPlan, RollbackStatus

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry

# Operation name → frozenset of allowed parameter keys. Only non-destructive,
# idempotent reversals are listed. Deletion/removal operations are
# deliberately absent so an agent cannot log a "reversal" that drops a
# campaign, keyword, or asset. Add entries as new reversible flows land.
_ALLOWED_OPERATIONS: dict[str, frozenset[str]] = {
    "google_ads.budgets.update": frozenset({"budget_id", "amount_micros"}),
    "google_ads_campaigns_update_status": frozenset({"campaign_id", "status"}),
    "google_ads.ad_groups.update_status": frozenset({"ad_group_id", "status"}),
    "google_ads_ads_update_status": frozenset({"ad_group_id", "ad_id", "status"}),
    "meta_ads.campaigns.update_status": frozenset({"campaign_id", "status"}),
    "meta_ads.ad_sets.update_status": frozenset({"ad_set_id", "status"}),
    "meta_ads.ads.update_status": frozenset({"ad_id", "status"}),
}

_DESTRUCTIVE_VERBS: tuple[str, ...] = (
    ".delete",
    ".remove",
    ".destroy",
    ".purge",
    ".transfer",
)

_READ_ONLY_PREFIXES: tuple[str, ...] = (
    "list_",
    "get_",
    "analyze_",
    "diagnose_",
    "inspect_",
    "report_",
    "check_",
    "search_",
)


def plan_rollback(entry: ActionLogEntry) -> RollbackPlan | None:
    """Build a :class:`RollbackPlan` for one action log entry.

    Returns ``None`` for read-only actions (no state change to undo).
    Returns a plan with :data:`RollbackStatus.NOT_SUPPORTED` when the
    entry is a write but carries no usable ``reversible_params`` hint.
    """
    if _is_read_only(entry.action):
        if entry.reversible_params is not None:
            # Read-only action should never carry a reversible hint; this is
            # almost certainly an agent bug worth surfacing.
            return _not_supported(
                entry,
                notes=(
                    "Read-only action carried a reversible_params hint; "
                    "this is likely an agent bug."
                ),
            )
        return None

    hint = entry.reversible_params
    if hint is None:
        return _not_supported(
            entry,
            notes=(
                "Source action has no reversible_params hint. "
                "Agents must set reversible_params at write time to enable rollback."
            ),
        )

    operation = hint.get("operation")
    params = hint.get("params")
    if not isinstance(operation, str) or not operation:
        return _not_supported(
            entry,
            notes="reversible_params is missing a string 'operation' key.",
        )
    if not isinstance(params, dict):
        return _not_supported(
            entry,
            notes="reversible_params is missing a dict 'params' key.",
        )

    if any(verb in operation for verb in _DESTRUCTIVE_VERBS):
        return _not_supported(
            entry,
            notes=(
                f"Operation {operation!r} names a destructive verb "
                "and cannot be planned as a rollback."
            ),
        )
    allowed_keys = _ALLOWED_OPERATIONS.get(operation)
    if allowed_keys is None:
        return _not_supported(
            entry,
            notes=(f"Operation {operation!r} is not in the rollback allow-list."),
        )
    extra = set(params) - allowed_keys
    if extra:
        return _not_supported(
            entry,
            notes=(
                f"Operation {operation!r} received unexpected params: "
                f"{sorted(extra)}."
            ),
        )

    raw_caveats = hint.get("caveats")
    if raw_caveats is not None and not isinstance(raw_caveats, list):
        return _not_supported(
            entry,
            notes="reversible_params.caveats must be a list of strings.",
        )
    caveats = _extract_caveats(raw_caveats)
    status = RollbackStatus.PARTIAL if caveats else RollbackStatus.SUPPORTED

    return RollbackPlan(
        source_timestamp=entry.timestamp,
        source_action=entry.action,
        platform=entry.platform,
        status=status,
        operation=operation,
        params=copy.deepcopy(params),
        description=f"Reverse {entry.action} on {entry.platform}",
        caveats=caveats,
        notes="",
    )


def _is_read_only(action: str) -> bool:
    lowered = action.lower()
    return any(lowered.startswith(prefix) for prefix in _READ_ONLY_PREFIXES)


def _not_supported(entry: ActionLogEntry, *, notes: str) -> RollbackPlan:
    return RollbackPlan(
        source_timestamp=entry.timestamp,
        source_action=entry.action,
        platform=entry.platform,
        status=RollbackStatus.NOT_SUPPORTED,
        operation=None,
        params=None,
        description=f"Cannot roll back {entry.action} on {entry.platform}",
        caveats=(),
        notes=notes,
    )


def _extract_caveats(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)
