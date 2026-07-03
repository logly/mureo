"""Before-state recording for reversible native mutations (#274).

Built-in Meta/Google **status-toggle** mutations are the native operations
the rollback planner can actually dispatch. Unlike plugin tools — whose
mutations are promoted to STATE.json's ``action_log`` by
:func:`mureo.mcp.plugin_semantics.record_mutation_action_log` — native
mutations recorded nothing, so ``rollback_apply`` had no before-state to
undo even though their tool descriptions promised reversibility.

This module closes that gap for status toggles: it captures the entity's
prior status **before** the mutation and appends an ``action_log`` entry
whose ``reversible_params`` restores that exact status. Budget and
collection/spec mutations are intentionally out of scope — their
before-state cannot be captured safely from the tool arguments alone
(e.g. ``budget_update`` takes a ``budget_id`` but the only getter keys on
``campaign_id``), and recording a wrong reversal value would be worse than
recording none.

Best-effort contract (mirrors ``plugin_semantics``): never raises, and
no-ops when there is no STATE.json in the current working directory.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Matches mureo.mcp.plugin_semantics so native and plugin mutations enter
# the same evidence/outcome-review window.
_DEFAULT_OBSERVATION_DAYS = 14

# Meta exposes status changes as dedicated pause/enable tools, so a reversal
# is "set the opposite verb" keyed by the *prior* status.
_META_STATUS_TO_VERB: dict[str, str] = {"ACTIVE": "enable", "PAUSED": "pause"}
# Google uses a single update_status tool; only these prior statuses can be
# restored (REMOVED/UNKNOWN are not safely re-settable).
_GOOGLE_RESTORABLE: frozenset[str] = frozenset({"ENABLED", "PAUSED"})

# tool name -> (platform, entity, id_keys). The id_keys both identify the
# entity for the before-state GET and become the reversal params.
_STATUS_TOOLS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "meta_ads_campaigns_pause": ("meta_ads", "campaigns", ("campaign_id",)),
    "meta_ads_campaigns_enable": ("meta_ads", "campaigns", ("campaign_id",)),
    "meta_ads_ad_sets_pause": ("meta_ads", "ad_sets", ("ad_set_id",)),
    "meta_ads_ad_sets_enable": ("meta_ads", "ad_sets", ("ad_set_id",)),
    "meta_ads_ads_pause": ("meta_ads", "ads", ("ad_id",)),
    "meta_ads_ads_enable": ("meta_ads", "ads", ("ad_id",)),
    "google_ads_campaigns_update_status": (
        "google_ads",
        "campaigns",
        ("campaign_id",),
    ),
    "google_ads_ads_update_status": (
        "google_ads",
        "ads",
        ("ad_group_id", "ad_id"),
    ),
}


def is_reversible_native_tool(name: str) -> bool:
    """True if ``name`` is a native status toggle this module can reverse."""
    return name in _STATUS_TOOLS


def build_reversal(
    name: str, args: dict[str, Any], prior_status: str | None
) -> dict[str, Any] | None:
    """Build ``reversible_params`` that restore ``prior_status``.

    Returns ``None`` when the tool is unknown, an id arg is missing, or
    ``prior_status`` cannot be safely restored (e.g. ARCHIVED/REMOVED) — in
    which case the action is recorded as audit-only, not reversible.
    """
    spec = _STATUS_TOOLS.get(name)
    if spec is None or not prior_status:
        return None
    platform, entity, id_keys = spec
    params: dict[str, Any] = {}
    for key in id_keys:
        value = args.get(key)
        if value is None:
            return None
        params[key] = value

    if platform == "meta_ads":
        verb = _META_STATUS_TO_VERB.get(prior_status)
        if verb is None:
            return None
        return {"operation": f"meta_ads_{entity}_{verb}", "params": params}

    # google_ads: generic update_status restores the prior status directly.
    if prior_status not in _GOOGLE_RESTORABLE:
        return None
    return {
        "operation": f"google_ads_{entity}_update_status",
        "params": {**params, "status": prior_status},
    }


async def capture_before_state(name: str, args: dict[str, Any]) -> str | None:
    """Read the entity's current status *before* a status-toggle mutation.

    Best-effort: returns ``None`` (skipping the network GET entirely) when
    the tool is not a reversible status toggle or no STATE.json exists, and
    swallows any error from the GET so it never blocks the mutation.
    """
    spec = _STATUS_TOOLS.get(name)
    if spec is None:
        return None
    if not (Path.cwd() / "STATE.json").is_file():
        return None
    try:
        return await _read_status(spec, args)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "before-state capture failed for native tool %r", name, exc_info=True
        )
        return None


async def _read_status(
    spec: tuple[str, str, tuple[str, ...]], args: dict[str, Any]
) -> str | None:
    platform, entity, _ = spec
    if platform == "meta_ads":
        from mureo.mcp._handlers_meta_ads import _get_client
        from mureo.mcp._helpers import _close_clients

        client = await _get_client(args)
        if client is None:
            return None
        # before-state capture runs outside any handler's cleanup scope, so
        # close the client's httpx pool here rather than leaking it.
        try:
            if entity == "campaigns":
                record = await client.get_campaign(args["campaign_id"])
            elif entity == "ad_sets":
                record = await client.get_ad_set(args["ad_set_id"])
            else:
                record = await client.get_ad(args["ad_id"])
            return _status_of(record)
        finally:
            await _close_clients([client])

    from mureo.mcp._handlers_google_ads import _get_client as _get_google_client

    client = _get_google_client(args)
    if client is None:
        return None
    if entity == "campaigns":
        return _status_of(await client.get_campaign(args["campaign_id"]))
    # ads: no single-ad getter, find the row in the ad group listing.
    ads = await client.list_ads(ad_group_id=args["ad_group_id"])
    target = str(args["ad_id"])
    for ad in ads if isinstance(ads, list) else []:
        if isinstance(ad, dict) and str(ad.get("id")) == target:
            return _status_of(ad)
    return None


def _status_of(record: Any) -> str | None:
    if isinstance(record, dict):
        status = record.get("status")
        if isinstance(status, str) and status:
            return status
    return None


def _is_error_result(result: list[Any] | None) -> bool:
    """True if ``result`` is an ``api_error_handler`` error envelope.

    Thin module-local alias for :func:`mureo.mcp._helpers.is_error_result`
    (the one source of truth, kept next to the producer). Retained so the
    in-module call site and its history stay stable.
    """
    from mureo.mcp._helpers import is_error_result

    return is_error_result(result)


def record_native_mutation(
    name: str,
    args: dict[str, Any],
    prior_status: str | None,
    result: list[Any] | None = None,
) -> None:
    """Append a reversible status toggle to STATE.json's action_log.

    Records ``reversible_params`` that restore ``prior_status`` when one was
    captured; otherwise records an audit-only entry (``reversible_params``
    ``None``) so the change is still visible. Skips recording when ``result``
    is an ``api_error_handler`` error envelope, so a failed mutation does not
    pollute the log. (A missing-credentials failure is not that envelope, so
    it still produces an audit-only entry — harmless, since its reversal is
    ``None``.) Best-effort: never raises, and no-ops without a STATE.json in
    cwd.
    """
    spec = _STATUS_TOOLS.get(name)
    if spec is None or _is_error_result(result):
        return
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log

        now = datetime.now(timezone.utc)
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action=name,
            platform=spec[0],
            summary=f"{name} (status change)",
            command=name,
            observation_due=(now + timedelta(days=_DEFAULT_OBSERVATION_DAYS))
            .date()
            .isoformat(),
            reversible_params=build_reversal(name, args, prior_status),
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "native action_log promotion failed for tool %r", name, exc_info=True
        )
