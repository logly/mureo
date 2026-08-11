"""Before-state recording for reversible native mutations (#274, #544).

Built-in Meta/Google **status-toggle** mutations are the native operations
the rollback planner can actually dispatch. Unlike plugin tools — whose
mutations are promoted to STATE.json's ``action_log`` by
:func:`mureo.mcp.plugin_semantics.record_mutation_action_log` — native
mutations recorded nothing, so ``rollback_apply`` had no before-state to
undo even though their tool descriptions promised reversibility.

This module closes that gap for two families:

1. **Status toggles** (#274) — the entity's prior status is captured
   **before** the mutation and the ``action_log`` entry's
   ``reversible_params`` restores that exact status.
2. **Delivery-surface exclusions** (#544) — excluding a placement / app /
   app category is a delivery-affecting bulk write with an exact inverse.
   The two platforms need different before-states, so each gets its own
   builder:

   - Google: the reversal is "remove exactly the criteria this call
     created", and the created ids are only knowable from the call's
     RESULT — so no pre-mutation read is issued at all.
   - Meta: the exclusion lists live in the ad set's targeting spec, so
     the prior lists ARE readable beforehand and the reversal restores
     them.

   Either way one call — however many exclusions it carried — becomes one
   ``action_log`` entry with one reversal, so a bad batch is undone as a
   single unit.

Budget and general collection/spec mutations remain out of scope — their
before-state cannot be captured safely from the tool arguments alone
(e.g. ``budget_update`` takes a ``budget_id`` but the only getter keys on
``campaign_id``), and recording a wrong reversal value would be worse than
recording none.

Best-effort contract (mirrors ``plugin_semantics``): never raises, and
no-ops when there is no STATE.json in the current working directory.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from mureo.core import clock

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

# --- Delivery-surface exclusions (#544) ------------------------------------

#: The exclusion WRITES this module records, mapped to their platform key.
#: Reads (``*_list`` / ``*_get``) are deliberately absent — a read has
#: nothing to undo and must never reach ``action_log``.
_GOOGLE_PLACEMENTS_ADD = "google_ads_negative_placements_add"
_GOOGLE_PLACEMENTS_REMOVE = "google_ads_negative_placements_remove"
_META_EXCLUSIONS_SET = "meta_ads_excluded_placements_set"

_EXCLUSION_TOOLS: dict[str, str] = {
    _GOOGLE_PLACEMENTS_ADD: "google_ads",
    _META_EXCLUSIONS_SET: "meta_ads",
}

#: The ad-set targeting keys ``meta_ads_excluded_placements_set`` can write.
#: Kept in lockstep with ``mureo.meta_ads._placement_exclusions.EXCLUSION_KEYS``
#: and with the param set the rollback allow-list bounds that operation to.
_META_EXCLUSION_KEYS: tuple[str, ...] = (
    "excluded_publisher_categories",
    "excluded_publisher_list_ids",
    "excluded_brand_safety_content_types",
)

#: What the action_log summary calls the change, keyed by "is an exclusion
#: write". Two words, so ``/daily-check`` can tell a delivery-surface change
#: from a status flip without re-reading the tool name.
_SUMMARY_KIND = {False: "status change", True: "delivery-surface exclusion"}


def is_reversible_native_tool(name: str) -> bool:
    """True if ``name`` is a native mutation this module can reverse."""
    return name in _STATUS_TOOLS or name in _EXCLUSION_TOOLS


def _platform_of(name: str) -> str | None:
    """Platform key for a recordable native mutation (``None`` if not one)."""
    spec = _STATUS_TOOLS.get(name)
    if spec is not None:
        return spec[0]
    return _EXCLUSION_TOOLS.get(name)


def _result_payload(result: list[Any] | None) -> Any:
    """Decode a handler result's single JSON TextContent, or ``None``.

    The created criterion ids only exist in the tool's RESULT, so the
    Google reversal has to read them back out of the envelope the handler
    produced. Any deviation from that envelope degrades to "not reversible"
    rather than to a wrong reversal.
    """
    if not result:
        return None
    text = getattr(result[0], "text", None)
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _google_placements_reversal(
    args: dict[str, Any], result: list[Any] | None
) -> dict[str, Any] | None:
    """Reverse an exclusion batch by removing exactly what it created."""
    payload = _result_payload(result)
    if not isinstance(payload, dict):
        return None
    created = payload.get("created")
    if not isinstance(created, list):
        return None
    criterion_ids = [
        str(item["criterion_id"])
        for item in created
        if isinstance(item, dict) and item.get("criterion_id")
    ]
    if not criterion_ids:
        return None
    # The level key the forward call used is the level the reversal targets.
    for key in ("campaign_id", "ad_group_id"):
        value = args.get(key)
        if value:
            return {
                "operation": _GOOGLE_PLACEMENTS_REMOVE,
                "params": {key: str(value), "criterion_ids": criterion_ids},
            }
    return None


def _meta_exclusions_reversal(
    args: dict[str, Any], prior_state: Any
) -> dict[str, Any] | None:
    """Restore the exclusion lists the call replaced.

    Only the facets the forward call actually wrote are restored. A facet
    that had no prior value is restored to the empty list — the forward
    call created it, so reversing it means clearing it, not leaving the new
    exclusion in place.
    """
    if not isinstance(prior_state, dict):
        return None
    ad_set_id = args.get("ad_set_id")
    if not ad_set_id:
        return None
    params: dict[str, Any] = {"ad_set_id": str(ad_set_id)}
    for key in _META_EXCLUSION_KEYS:
        if args.get(key) is None:
            continue
        previous = prior_state.get(key)
        params[key] = list(previous) if isinstance(previous, list) else []
    if len(params) == 1:  # no facet was written ⇒ nothing to restore
        return None
    return {"operation": _META_EXCLUSIONS_SET, "params": params}


def build_reversal(
    name: str,
    args: dict[str, Any],
    prior_status: Any,
    result: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Build ``reversible_params`` for a recordable native mutation.

    ``prior_status`` is the before-state :func:`capture_before_state`
    produced: a status string for a status toggle, the prior exclusion
    lists for a Meta exclusion write, and ``None`` for a Google exclusion
    write (whose reversal comes from ``result`` instead).

    Returns ``None`` when the tool is unknown, an id arg is missing, or the
    before-state cannot be safely restored (e.g. ARCHIVED/REMOVED) — in
    which case the action is recorded as audit-only, not reversible.
    """
    if name == _GOOGLE_PLACEMENTS_ADD:
        return _google_placements_reversal(args, result)
    if name == _META_EXCLUSIONS_SET:
        return _meta_exclusions_reversal(args, prior_status)
    spec = _STATUS_TOOLS.get(name)
    if spec is None or not prior_status or not isinstance(prior_status, str):
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


async def capture_before_state(name: str, args: dict[str, Any]) -> Any:
    """Read the entity's state *before* a recordable native mutation.

    Returns a status string for a status toggle and the prior exclusion
    lists (a dict) for a Meta exclusion write. Returns ``None`` — skipping
    the network GET entirely — for anything else, including the Google
    exclusion add, whose reversal is derived from the call's result rather
    than from a pre-mutation read.

    Best-effort: no-ops without a STATE.json in cwd, and swallows any error
    from the GET so it never blocks the mutation.
    """
    spec = _STATUS_TOOLS.get(name)
    if spec is None and name != _META_EXCLUSIONS_SET:
        return None
    if not (Path.cwd() / "STATE.json").is_file():
        return None
    try:
        if spec is None:
            return await _read_meta_exclusions(args)
        return await _read_status(spec, args)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "before-state capture failed for native tool %r", name, exc_info=True
        )
        return None


async def _read_meta_exclusions(args: dict[str, Any]) -> dict[str, Any] | None:
    """Read an ad set's current exclusion lists before they are replaced."""
    from mureo.mcp._handlers_meta_ads import _get_client
    from mureo.mcp._helpers import _close_clients

    ad_set_id = args.get("ad_set_id")
    if not ad_set_id:
        return None
    client = await _get_client(args)
    if client is None:
        return None
    # Runs outside any handler's cleanup scope, so close the httpx pool here.
    try:
        record = await client.get_excluded_placements(str(ad_set_id))
    finally:
        await _close_clients([client])
    return record if isinstance(record, dict) else None


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
    prior_status: Any,
    result: list[Any] | None = None,
) -> None:
    """Append a recordable native mutation to STATE.json's action_log.

    Records ``reversible_params`` when a reversal could be built (from the
    captured before-state, or from ``result`` for the Google exclusion add);
    otherwise records an audit-only entry (``reversible_params`` ``None``)
    so the change is still visible. Skips recording when ``result`` is an
    ``api_error_handler`` error envelope, so a failed mutation does not
    pollute the log. (A missing-credentials failure is not that envelope, so
    it still produces an audit-only entry — harmless, since its reversal is
    ``None``.) Best-effort: never raises, and no-ops without a STATE.json in
    cwd.
    """
    platform = _platform_of(name)
    if platform is None or _is_error_result(result):
        return
    try:
        state_path = Path.cwd() / "STATE.json"
        if not state_path.is_file():
            return
        from mureo.context.models import ActionLogEntry
        from mureo.context.state import append_action_log
        from mureo.mcp.plugin_semantics import extract_mutation_identity

        # Server clock (#460): the same offset-bearing local timestamp
        # ``mureo_state_action_log_append`` stamps, so entries from both
        # promotion paths are directly comparable — and ``observation_due``
        # lands on the operator's local calendar day.
        now = clock.server_now()
        campaign_id, ad_id, entity_type, entity_id = extract_mutation_identity(args)
        entry = ActionLogEntry(
            timestamp=now.isoformat(timespec="seconds"),
            action=name,
            platform=platform,
            campaign_id=campaign_id,
            ad_id=ad_id,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=f"{name} ({_SUMMARY_KIND[name in _EXCLUSION_TOOLS]})",
            command=name,
            observation_due=(now + timedelta(days=_DEFAULT_OBSERVATION_DAYS))
            .date()
            .isoformat(),
            reversible_params=build_reversal(name, args, prior_status, result),
        )
        append_action_log(state_path, entry)
    except Exception:  # noqa: BLE001 — must never break the tool call
        logger.warning(
            "native action_log promotion failed for tool %r", name, exc_info=True
        )
