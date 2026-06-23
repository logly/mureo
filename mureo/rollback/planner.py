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
listed in :data:`_ALLOWED_OPERATIONS` — or, via
:func:`_plugin_reversal_keys`, naming a *registered* plugin tool —
are planned, that no operation naming a destructive verb is ever
planned, and that each plan carries only the param keys that operation
declares (built-in: the static key-set; plugin: its ``inputSchema``
property names). Executors (Task #26) must still re-authorize against
the same policy gate used for forward actions; for a plugin reversal
the dispatcher additionally re-validates the params against the live
tool's ``inputSchema`` before the call runs.
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
# Every operation here must name a *registered* MCP tool with these exact
# param keys — native status toggles are recorded automatically by
# :mod:`mureo.mcp.native_reversal`, which builds reversals against these
# operations. Keep the two in lockstep.
_ALLOWED_OPERATIONS: dict[str, frozenset[str]] = {
    # Google budget: restores the prior daily amount. Key is ``amount`` to
    # match the real google_ads_budget_update tool (currency units, not
    # micros). Captured manually — see native_reversal for why budget is not
    # auto-recorded.
    "google_ads_budget_update": frozenset({"budget_id", "amount"}),
    # Google status toggles: one update_status tool restores the prior status.
    "google_ads_campaigns_update_status": frozenset({"campaign_id", "status"}),
    "google_ads_ads_update_status": frozenset({"ad_group_id", "ad_id", "status"}),
    # Meta status toggles are dedicated pause/enable tools; the reversal
    # invokes the opposite verb to restore the prior status.
    "meta_ads_campaigns_pause": frozenset({"campaign_id"}),
    "meta_ads_campaigns_enable": frozenset({"campaign_id"}),
    "meta_ads_ad_sets_pause": frozenset({"ad_set_id"}),
    "meta_ads_ad_sets_enable": frozenset({"ad_set_id"}),
    "meta_ads_ads_pause": frozenset({"ad_id"}),
    "meta_ads_ads_enable": frozenset({"ad_id"}),
}

# Underscore-prefixed verbs match the spec-compliant tool naming
# (e.g. ``google_ads_campaigns_delete``). The pre-rename forms with
# leading dot (".delete" etc.) no longer match anything in the new
# tool registry — leaving them dotted would silently disable the
# destructive-verb safety net.
_DESTRUCTIVE_VERBS: tuple[str, ...] = (
    "_delete",
    "_remove",
    "_destroy",
    "_purge",
    "_transfer",
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


def _plugin_reversal_keys(operation: str) -> tuple[bool, frozenset[str] | None]:
    """Plugin escape hatch for :func:`plan_rollback` (guardrail parity).

    A plugin tool may declare ``meta["mureo"]["reversal"]`` pointing at one of
    its own operations. Such an operation can never appear in the static
    :data:`_ALLOWED_OPERATIONS` (mureo cannot enumerate third-party tools at
    author time), so before #114-follow-up it was always recorded-but-not-
    executable. This hook lets the planner accept it when it names a
    *registered* plugin tool, bounding params by that tool's declared schema.

    Returns ``(is_registered_plugin_tool, allowed_keys_or_None)``. Resolved
    lazily against the live MCP server to avoid the import cycle
    ``server → tools_rollback → _handlers_rollback → rollback.planner``. A
    server-import failure (e.g. this module imported in isolation in a test)
    degrades safely to ``(False, None)`` — no plugin operation is planned.
    Tests monkeypatch this function directly.
    """
    try:
        from mureo.mcp.server import plugin_reversal_param_keys
    except Exception:  # noqa: BLE001 — degrade to "not a plugin op"
        return (False, None)
    return plugin_reversal_param_keys(operation)


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
    # Built-in allow-list first; fall back to the plugin escape hatch so a
    # plugin-declared reversal naming a registered plugin tool is executable
    # too (guardrail parity). ``allowed_keys is None`` means "no plan-time key
    # restriction" — used both for an unrecognised built-in (rejected below)
    # and for a registered schema-less plugin tool (accepted, bounded at
    # execution by the dispatcher's re-validation + policy gates).
    allowed_keys = _ALLOWED_OPERATIONS.get(operation)
    if allowed_keys is None:
        is_plugin_tool, allowed_keys = _plugin_reversal_keys(operation)
        if not is_plugin_tool:
            return _not_supported(
                entry,
                notes=(f"Operation {operation!r} is not in the rollback allow-list."),
            )
    if allowed_keys is not None:
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
