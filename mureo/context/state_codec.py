"""STATE.json <-> :class:`~mureo.context.models.StateDocument` codec (#538).

Both directions of one contract. :func:`parse_state` and :func:`render_state`
are inverses, and every field of the schema appears exactly twice — once in
each — so the optionality rules that keep a round-trip byte-stable (emit
``metrics`` / ``ads`` / ``periods`` / ``conversion_action_types`` only when
they are actually present) can only be checked with both halves in front of
you. Keeping them apart would let the two sides drift, and drift here silently
rewrites an operator's STATE.json.

Extracted verbatim from :mod:`mureo.context.state`, which keeps the file /
lock / merge layer its name promises. Every public name here is re-exported
from that module, so no caller had to move.

The read side has two modes and the distinction is load-bearing:

- ``strict=True`` is the **writer contract** — a nonconforming entry raises,
  exactly as it always has.
- ``strict=False`` is the **read-only Reports view** — a nonconforming entry
  is skipped and logged at DEBUG (never WARNING: the dashboard re-parses on
  every poll, so a per-entry warning would flood the daemon log), so one
  hand-authored campaign cannot blank out a whole document.

Each tolerant branch documents its own reasoning below.

Dependency-free beyond stdlib and the frozen ``mureo.context.models``
dataclasses — the same discipline :mod:`mureo.context.platform_accounts`
keeps, and for the same reason: ``mureo.core.__init__`` ->
``runtime_context`` -> ``state_store`` -> ``mureo.context.state`` is a real
import chain, so a module inside it that reached back into ``mureo.core``
would close the cycle.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import fields as dataclass_fields
from typing import Any

from mureo.context.models import (
    NOT_COLLECTED_REASON_MAX_CHARS,
    ActionLogEntry,
    AdState,
    BatchRecord,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Codec field coverage — checked at import, not only under pytest
# ---------------------------------------------------------------------------
#
# Everywhere else in the tree, a field is carried across a rebuild by
# ``dataclasses.replace`` and cannot be forgotten. This module is the one place
# that CANNOT use it: it maps to an external JSON schema, so both halves list
# every field by hand. A field added to a model but not to this file is
# silently lost the moment a document is written and read back — the same
# omission-shaped failure, in the one file where the structural fix does not
# apply.
#
# So the omission is made loud instead. Each model below declares the fields
# this codec handles, and the check runs at MODULE IMPORT: any `import mureo`,
# a REPL, a `pytest -k` that never collects the round-trip test. Adding a field
# without visiting this file raises immediately with the two functions to edit,
# rather than costing an operator their data.
#
# This verifies DECLARATION, not behaviour — that the field is known here, not
# that it survives. Behaviour is the round-trip test's job
# (tests/test_dataclass_field_preservation.py::TestCodecRoundTrip).

_CODEC_COVERAGE: tuple[tuple[type, frozenset[str], str], ...] = (
    (
        StateDocument,
        frozenset(
            {
                "version",
                "last_synced_at",
                "customer_id",
                "campaigns",
                "platforms",
                "action_log",
                "reports",
                "batches",
            }
        ),
        "parse_state / render_state",
    ),
    (
        PlatformState,
        frozenset(
            {
                "account_id",
                "campaigns",
                "totals",
                "metrics_period",
                "periods",
                "conversion_action_types",
                "not_collected",
            }
        ),
        "parse_state / _platform_state_to_dict",
    ),
    (
        ActionLogEntry,
        frozenset(
            {
                "timestamp",
                "action",
                "platform",
                "campaign_id",
                "ad_id",
                "entity_type",
                "entity_id",
                "summary",
                "command",
                "metrics_at_action",
                "observation_due",
                "reversible_params",
                "rollback_of",
                "evaluation_of",
                "batch_id",
                "origin",
                "external_id",
                "occurred_at",
            }
        ),
        "_parse_action_log_entry / _action_log_entry_to_dict",
    ),
    (
        CampaignSnapshot,
        frozenset(
            {
                "campaign_id",
                "campaign_name",
                "status",
                "bidding_strategy_type",
                "bidding_details",
                "daily_budget",
                "device_targeting",
                "campaign_goal",
                "notes",
                "metrics",
                "ads",
            }
        ),
        "_parse_campaign / _snapshot_to_dict",
    ),
    (
        AdState,
        frozenset({"ad_id", "name", "status", "effective_status", "as_of"}),
        "_parse_ad / _ad_state_to_dict",
    ),
    (
        BatchRecord,
        frozenset({"batch_id", "label", "started_at", "ended_at"}),
        "_parse_batches / _batch_record_to_dict",
    ),
)


def _assert_codec_coverage() -> None:
    """Fail loudly if a model has a field this codec does not name."""
    for model, handled, functions in _CODEC_COVERAGE:
        declared = {f.name for f in dataclass_fields(model)}
        missing = declared - handled
        if missing:
            raise RuntimeError(
                f"{model.__name__} has field(s) {sorted(missing)} that "
                f"mureo.context.state_codec does not handle. Add them to BOTH "
                f"halves of {functions} and to _CODEC_COVERAGE — otherwise the "
                "field is silently dropped on every STATE.json write."
            )
        stale = handled - declared
        if stale:
            raise RuntimeError(
                f"_CODEC_COVERAGE lists field(s) {sorted(stale)} that "
                f"{model.__name__} no longer declares; remove them here and "
                f"from {functions}."
            )


_assert_codec_coverage()


# Required campaign fields
_CAMPAIGN_REQUIRED_FIELDS: tuple[str, ...] = (
    "campaign_id",
    "campaign_name",
    "status",
)


def _parse_ad(a: dict[str, Any]) -> AdState:
    """Create an :class:`AdState` from a dict (``ad_id`` required).

    ``ad_id`` is type-checked, not merely present-checked: it is the key every
    later run matches on to diff statuses, so a hand-edited numeric id would
    silently never match the string ids the platforms return.
    """
    if not isinstance(a, dict) or "ad_id" not in a:
        raise ValueError(f"Ad is missing required field 'ad_id': {a}")
    if not isinstance(a["ad_id"], str) or not a["ad_id"]:
        raise ValueError(f"Ad 'ad_id' must be a non-empty string: {a}")
    return AdState(
        ad_id=a["ad_id"],
        name=a.get("name"),
        status=a.get("status"),
        effective_status=a.get("effective_status"),
        as_of=a.get("as_of"),
    )


def _parse_ads(raw: Any, *, strict: bool) -> tuple[AdState, ...] | None:
    """Parse a campaign's ``ads`` list (#468).

    Returns ``None`` when the key is absent — "ad-level status was never
    fetched", which must stay distinguishable from ``()`` ("fetched, no ads").
    ``strict=True`` raises on a nonconforming entry (the writer contract);
    ``strict=False`` skips it, so one hand-authored ad cannot blank out a
    whole document for the read-only Reports view.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        if strict:
            raise ValueError(f"Campaign 'ads' must be a list: {raw!r}")
        logger.debug("skipping non-list campaign 'ads' value: %r", raw)
        return None
    if strict:
        return tuple(_parse_ad(a) for a in raw)
    parsed: list[AdState] = []
    for a in raw:
        try:
            parsed.append(_parse_ad(a))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING — see _parse_campaigns.
            logger.debug("skipping unparseable ad entry: %s", exc)
    return tuple(parsed)


def _parse_campaigns(
    raw: list[dict[str, Any]], *, strict: bool
) -> tuple[CampaignSnapshot, ...]:
    """Parse a campaign list.

    ``strict=True`` (the canonical contract relied on by every writer) raises
    on the first nonconforming entry. ``strict=False`` skips entries that fail
    validation, logging each one — used only by the read-only Reports view so a
    single variant/hand-authored campaign cannot blank out a whole document
    (whose platforms/periods/reports the dashboard actually renders).
    """
    if strict:
        return tuple(_parse_campaign(c, strict=True) for c in raw)
    parsed: list[CampaignSnapshot] = []
    for c in raw:
        try:
            parsed.append(_parse_campaign(c, strict=False))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING: the read-only Reports view re-parses on every
            # poll, so a per-entry WARNING would flood the log for a STATE.json
            # with many nonconforming (e.g. legacy / hand-authored) campaigns.
            logger.debug("skipping unparseable campaign entry: %s", exc)
    return tuple(parsed)


def _parse_action_log(
    raw: list[dict[str, Any]], *, strict: bool
) -> tuple[ActionLogEntry, ...]:
    """Parse the action_log list.

    ``strict=True`` (the writer contract) raises on the first entry missing a
    required field (``timestamp`` / ``action`` / ``platform``). ``strict=False``
    skips such entries, logging each — used only by the read-only Reports view
    so a single old / hand-authored entry (e.g. one written before those fields
    were required) cannot blank out a whole document.
    """
    if strict:
        return tuple(_parse_action_log_entry(e) for e in raw)
    parsed: list[ActionLogEntry] = []
    for e in raw:
        try:
            parsed.append(_parse_action_log_entry(e))
        except (ValueError, KeyError, TypeError) as exc:
            # DEBUG, not WARNING — see _parse_campaigns: avoid per-render log
            # flood from a STATE.json with many nonconforming action_log entries.
            logger.debug("skipping unparseable action_log entry: %s", exc)
    return tuple(parsed)


def _platform_account_id(
    platform_key: str, platform_data: dict[str, Any], *, strict: bool
) -> str:
    """Resolve a platform's ``account_id``.

    ``strict=True`` (the writer contract) requires the key — a missing
    ``account_id`` raises ``KeyError`` exactly as before. ``strict=False``
    (the read-only Reports view) defaults a missing ``account_id`` to ``""``
    so an agent-/hand-authored STATE.json that omitted it still renders its
    platforms/totals/periods instead of blanking the whole dashboard. Logged
    at DEBUG (expected for non-canonical files; never per-poll WARNING noise).
    """
    if strict or "account_id" in platform_data:
        # KeyError in strict if absent — unchanged writer contract. Annotated
        # local so mypy treats the dict[str, Any] value as the declared str.
        account_id: str = platform_data["account_id"]
        return account_id
    logger.debug(
        "platform %r missing 'account_id'; defaulting to '' for the tolerant "
        "read-only view",
        platform_key,
    )
    return ""


def _parse_conversion_action_types(raw: Any) -> tuple[str, ...] | None:
    """Parse a platform's ``conversion_action_types`` override (#342).

    Returns a tuple of non-empty string action_types, or ``None`` when the
    field is absent / not a list / has no usable entries (so the counters
    fall back to the built-in generic set). Tolerant by design — a malformed
    value degrades to "no override" rather than raising.
    """
    if not isinstance(raw, list):
        return None
    cleaned = tuple(str(x).strip() for x in raw if isinstance(x, str) and x.strip())
    return cleaned or None


def _parse_not_collected(raw: Any) -> dict[str, Any] | None:
    """Parse a platform's "why the figures did not move" note (#638).

    Returns ``{"attempted_at": ..., "reason": ...}`` (``attempted_at`` only
    when it is a usable string), or ``None`` when there is no usable note.

    **No reason means no note.** The reason IS the payload: a note carrying
    only a timestamp tells an operator that something happened and refuses to
    say what, which is the exact non-answer this field exists to end.

    Tolerant like the other optional platform fields — a hand-edited value
    costs the note, never the document — and normalising to the two known keys
    here keeps every reader (dashboard, CLI, a plugin) working from one shape.

    ``reason`` is capped at
    :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS`, the same
    bound the write helper and the dashboard apply. Doing it on READ too is
    what stops a page of API JSON from a hand edit or an outside writer being
    re-serialised in full on every subsequent write.
    """
    if not isinstance(raw, dict):
        return None
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    note: dict[str, Any] = {}
    attempted_at = raw.get("attempted_at")
    if isinstance(attempted_at, str) and attempted_at.strip():
        note["attempted_at"] = attempted_at.strip()
    note["reason"] = reason.strip()[:NOT_COLLECTED_REASON_MAX_CHARS]
    return note


def _parse_batches(raw: Any) -> tuple[BatchRecord, ...]:
    """Parse the declared bulk change sets (#549).

    Tolerant in both modes, unlike the campaign / action_log lists: a batch
    record is bookkeeping ABOUT history, not history itself — the members are
    in ``action_log`` and their ``batch_id`` stands on its own. A malformed
    record therefore costs a label, and dropping it is a far better trade than
    letting a hand-edited entry blank a whole document.
    """
    if not isinstance(raw, list):
        return ()
    records: list[BatchRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            logger.debug("skipping non-object batch record: %r", item)
            continue
        batch_id = item.get("batch_id")
        if not isinstance(batch_id, str) or not batch_id.strip():
            logger.debug("skipping batch record without a usable batch_id: %r", item)
            continue
        label = item.get("label")
        started_at = item.get("started_at")
        ended_at = item.get("ended_at")
        records.append(
            BatchRecord(
                batch_id=batch_id.strip(),
                label=label if isinstance(label, str) else "",
                started_at=started_at if isinstance(started_at, str) else "",
                ended_at=ended_at if isinstance(ended_at, str) else None,
            )
        )
    return tuple(records)


def parse_state(text: str, *, strict: bool = True) -> StateDocument:
    """Parse a JSON string and return a StateDocument.

    ``strict`` controls campaign-list, action_log AND platform validation:
    ``True`` (default) preserves the strict writer contract (raises on a missing
    required field, including a platform ``account_id``); ``False`` tolerantly
    skips nonconforming campaign / action_log entries and defaults a missing
    platform ``account_id`` to ``""`` for the read-only Reports view. Invalid
    JSON always raises regardless of ``strict``.

    Unknown top-level keys are ignored (and :func:`render_state` emits only
    the known ones), which is what keeps the ``mureo_state_get`` response
    field ``server_now`` from ever being persisted: a document echoed back
    into STATE.json with that key loses it on the next write instead of
    fossilising a stale "today" (#460).
    """
    data = json.loads(text)
    campaigns_raw = data.get("campaigns", [])
    campaigns = _parse_campaigns(campaigns_raw, strict=strict)

    # v2: platforms
    platforms: dict[str, PlatformState] | None = None
    platforms_raw = data.get("platforms")
    if platforms_raw is not None:
        platforms = {}
        for platform_key, platform_data in platforms_raw.items():
            platform_campaigns = _parse_campaigns(
                platform_data.get("campaigns", []), strict=strict
            )
            platforms[platform_key] = PlatformState(
                account_id=_platform_account_id(
                    platform_key, platform_data, strict=strict
                ),
                campaigns=platform_campaigns,
                totals=platform_data.get("totals"),
                metrics_period=platform_data.get("metrics_period"),
                periods=platform_data.get("periods"),
                conversion_action_types=_parse_conversion_action_types(
                    platform_data.get("conversion_action_types")
                ),
                not_collected=_parse_not_collected(platform_data.get("not_collected")),
            )

    # v2: action_log
    action_log_raw = data.get("action_log", [])
    action_log = _parse_action_log(action_log_raw, strict=strict)

    return StateDocument(
        version=data.get("version", "1"),
        last_synced_at=data.get("last_synced_at"),
        customer_id=data.get("customer_id"),
        campaigns=campaigns,
        platforms=platforms,
        action_log=action_log,
        reports=data.get("reports"),
        batches=_parse_batches(data.get("batches")),
    )


def _parse_action_log_entry(e: dict[str, Any]) -> ActionLogEntry:
    """Create an ActionLogEntry from a dict."""
    return ActionLogEntry(
        timestamp=e["timestamp"],
        action=e["action"],
        platform=e["platform"],
        campaign_id=e.get("campaign_id"),
        ad_id=e.get("ad_id"),
        entity_type=e.get("entity_type"),
        entity_id=e.get("entity_id"),
        batch_id=e.get("batch_id"),
        summary=e.get("summary"),
        command=e.get("command"),
        metrics_at_action=e.get("metrics_at_action"),
        observation_due=e.get("observation_due"),
        reversible_params=e.get("reversible_params"),
        rollback_of=e.get("rollback_of"),
        evaluation_of=e.get("evaluation_of"),
        # #545 provenance. Absent on every entry written before it existed,
        # which is exactly what "mureo made this change" looks like.
        origin=e.get("origin"),
        external_id=e.get("external_id"),
        occurred_at=e.get("occurred_at"),
    )


def _parse_campaign(c: dict[str, Any], *, strict: bool = True) -> CampaignSnapshot:
    """Create a CampaignSnapshot from a dict (with required field validation)."""
    for field_name in _CAMPAIGN_REQUIRED_FIELDS:
        if field_name not in c:
            raise ValueError(f"Campaign is missing required field '{field_name}': {c}")
    device_targeting_raw = c.get("device_targeting")
    device_targeting: tuple[dict[str, Any], ...] | None = None
    if device_targeting_raw is not None:
        device_targeting = tuple(device_targeting_raw)
    return CampaignSnapshot(
        campaign_id=c["campaign_id"],
        campaign_name=c["campaign_name"],
        status=c["status"],
        bidding_strategy_type=c.get("bidding_strategy_type"),
        bidding_details=c.get("bidding_details"),
        daily_budget=c.get("daily_budget"),
        device_targeting=device_targeting,
        campaign_goal=c.get("campaign_goal"),
        notes=c.get("notes"),
        metrics=c.get("metrics"),
        ads=_parse_ads(c.get("ads"), strict=strict),
    )


def render_state(doc: StateDocument) -> str:
    """Generate a JSON string from a StateDocument."""
    data: dict[str, Any] = {
        "version": doc.version,
        "last_synced_at": doc.last_synced_at,
        "customer_id": doc.customer_id,
        "campaigns": [_snapshot_to_dict(c) for c in doc.campaigns],
    }

    # v2: platforms
    if doc.platforms is not None:
        data["platforms"] = {
            key: _platform_state_to_dict(ps) for key, ps in doc.platforms.items()
        }
    else:
        data["platforms"] = None

    # v2: action_log
    data["action_log"] = [_action_log_entry_to_dict(e) for e in doc.action_log]

    # Optional reports section (stage-c forward-ready): emit only when present
    # so old STATE.json files don't gain a new key.
    if doc.reports is not None:
        data["reports"] = copy.deepcopy(doc.reports)

    # Declared batches (#549): emit only when the workspace has any, so a
    # document written before this field existed stays byte-stable on
    # round-trip. ``ended_at`` is omitted while a batch is open.
    if doc.batches:
        data["batches"] = [_batch_record_to_dict(b) for b in doc.batches]

    return json.dumps(data, ensure_ascii=False, indent=2)


def _platform_state_to_dict(ps: PlatformState) -> dict[str, Any]:
    """Convert a PlatformState to a dictionary."""
    result: dict[str, Any] = {
        "account_id": ps.account_id,
        "campaigns": [_snapshot_to_dict(c) for c in ps.campaigns],
    }
    # Optional platform-level rollup: emit only when present.
    if ps.totals is not None:
        result["totals"] = copy.deepcopy(ps.totals)
    if ps.metrics_period is not None:
        result["metrics_period"] = ps.metrics_period
    # Per-period rollups: emit only when non-empty so legacy files (and
    # entries with no per-period data) stay byte-stable on round-trip.
    if ps.periods:
        result["periods"] = copy.deepcopy(ps.periods)
    # #342 — operator conversion override: emit only when set, as a JSON list,
    # so legacy entries stay byte-stable.
    if ps.conversion_action_types:
        result["conversion_action_types"] = list(ps.conversion_action_types)
    # #638 — why the figures did not move: emit only when there is a note, so
    # a document that has never had a failed collection stays byte-stable, and
    # a cleared note leaves no key behind to be read as a live one.
    if ps.not_collected:
        result["not_collected"] = copy.deepcopy(ps.not_collected)
    return result


def _action_log_entry_to_dict(e: ActionLogEntry) -> dict[str, Any]:
    """Convert an ActionLogEntry to a dictionary."""
    result: dict[str, Any] = {
        "timestamp": e.timestamp,
        "action": e.action,
        "platform": e.platform,
    }
    if e.campaign_id is not None:
        result["campaign_id"] = e.campaign_id
    if e.ad_id is not None:
        result["ad_id"] = e.ad_id
    if e.entity_type is not None:
        result["entity_type"] = e.entity_type
    if e.entity_id is not None:
        result["entity_id"] = e.entity_id
    if e.batch_id is not None:
        result["batch_id"] = e.batch_id
    if e.summary is not None:
        result["summary"] = e.summary
    if e.command is not None:
        result["command"] = e.command
    if e.metrics_at_action is not None:
        result["metrics_at_action"] = copy.deepcopy(e.metrics_at_action)
    if e.observation_due is not None:
        result["observation_due"] = e.observation_due
    if e.reversible_params is not None:
        result["reversible_params"] = copy.deepcopy(e.reversible_params)
    if e.rollback_of is not None:
        result["rollback_of"] = e.rollback_of
    if e.evaluation_of is not None:
        result["evaluation_of"] = e.evaluation_of
    # #545: emitted only when set, so a STATE.json written by a mureo-driven
    # run round-trips byte-identically and gains no new key.
    if e.origin is not None:
        result["origin"] = e.origin
    if e.external_id is not None:
        result["external_id"] = e.external_id
    if e.occurred_at is not None:
        result["occurred_at"] = e.occurred_at
    return result


def _batch_record_to_dict(b: BatchRecord) -> dict[str, Any]:
    """Convert a :class:`BatchRecord` to a dictionary.

    ``ended_at`` is emitted only once the batch is closed, so "open" is the
    absence of the key rather than a null a reader could misparse as a time.
    """
    result: dict[str, Any] = {
        "batch_id": b.batch_id,
        "label": b.label,
        "started_at": b.started_at,
    }
    if b.ended_at is not None:
        result["ended_at"] = b.ended_at
    return result


def _snapshot_to_dict(c: CampaignSnapshot) -> dict[str, Any]:
    """Convert a CampaignSnapshot to a dictionary."""
    device_targeting: list[dict[str, Any]] | None = None
    if c.device_targeting is not None:
        device_targeting = list(c.device_targeting)
    result: dict[str, Any] = {
        "campaign_id": c.campaign_id,
        "campaign_name": c.campaign_name,
        "status": c.status,
        "bidding_strategy_type": c.bidding_strategy_type,
        "bidding_details": c.bidding_details,
        "daily_budget": c.daily_budget,
        "device_targeting": device_targeting,
        "campaign_goal": c.campaign_goal,
        "notes": c.notes,
    }
    # Optional metrics: emit only when present so old STATE.json files don't
    # gain a new key (no diff churn / bloat).
    if c.metrics is not None:
        result["metrics"] = copy.deepcopy(c.metrics)
    # Ad-level state (#468): emit only when it was actually fetched, so a
    # campaign that predates this field stays byte-stable on round-trip.
    if c.ads is not None:
        result["ads"] = [_ad_state_to_dict(a) for a in c.ads]
    return result


def _ad_state_to_dict(a: AdState) -> dict[str, Any]:
    """Convert an :class:`AdState` to a dictionary.

    Optional fields are emitted only when set: an absent ``effective_status``
    must stay absent rather than becoming an empty string a later run could
    read as an observed value.
    """
    result: dict[str, Any] = {"ad_id": a.ad_id}
    for key, value in (
        ("name", a.name),
        ("status", a.status),
        ("effective_status", a.effective_status),
        ("as_of", a.as_of),
    ):
        if value is not None:
            result[key] = value
    return result


__all__ = [
    "parse_state",
    "render_state",
]
