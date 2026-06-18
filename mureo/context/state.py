"""Read and write STATE.json."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)
from mureo.fsutil import file_lock

# Required campaign fields
_CAMPAIGN_REQUIRED_FIELDS: tuple[str, ...] = (
    "campaign_id",
    "campaign_name",
    "status",
)


def parse_state(text: str) -> StateDocument:
    """Parse a JSON string and return a StateDocument."""
    data = json.loads(text)
    campaigns_raw = data.get("campaigns", [])
    campaigns = tuple(_parse_campaign(c) for c in campaigns_raw)

    # v2: platforms
    platforms: dict[str, PlatformState] | None = None
    platforms_raw = data.get("platforms")
    if platforms_raw is not None:
        platforms = {}
        for platform_key, platform_data in platforms_raw.items():
            platform_campaigns = tuple(
                _parse_campaign(c) for c in platform_data.get("campaigns", [])
            )
            platforms[platform_key] = PlatformState(
                account_id=platform_data["account_id"],
                campaigns=platform_campaigns,
                totals=platform_data.get("totals"),
                metrics_period=platform_data.get("metrics_period"),
            )

    # v2: action_log
    action_log_raw = data.get("action_log", [])
    action_log = tuple(_parse_action_log_entry(e) for e in action_log_raw)

    return StateDocument(
        version=data.get("version", "1"),
        last_synced_at=data.get("last_synced_at"),
        customer_id=data.get("customer_id"),
        campaigns=campaigns,
        platforms=platforms,
        action_log=action_log,
        reports=data.get("reports"),
    )


def _parse_action_log_entry(e: dict[str, Any]) -> ActionLogEntry:
    """Create an ActionLogEntry from a dict."""
    return ActionLogEntry(
        timestamp=e["timestamp"],
        action=e["action"],
        platform=e["platform"],
        campaign_id=e.get("campaign_id"),
        summary=e.get("summary"),
        command=e.get("command"),
        metrics_at_action=e.get("metrics_at_action"),
        observation_due=e.get("observation_due"),
        reversible_params=e.get("reversible_params"),
        rollback_of=e.get("rollback_of"),
    )


def _parse_campaign(c: dict[str, Any]) -> CampaignSnapshot:
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
    return result


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write a file (temp file -> rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def read_state_file(path: Path) -> StateDocument:
    """Read a STATE.json file and return a StateDocument.

    Returns a default StateDocument if the file does not exist.
    """
    if not path.exists():
        return StateDocument()
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STATE.json: {path}") from exc
    try:
        return parse_state(text)
    except json.JSONDecodeError as exc:
        raise ContextFileError(f"Failed to parse JSON in STATE.json: {path}") from exc


def write_state_file(path: Path, doc: StateDocument) -> None:
    """Atomically write a StateDocument to a STATE.json file."""
    text = render_state(doc)
    _atomic_write(path, text)


def _state_lock_path(path: Path) -> Path:
    """Sidecar lock file for ``path`` (e.g. ``STATE.json`` -> ``STATE.json.lock``)."""
    return path.with_name(path.name + ".lock")


def _locked_state_mutation(
    path: Path, build: Callable[[StateDocument], StateDocument]
) -> StateDocument:
    """Run a read -> ``build`` -> write cycle as one critical section.

    ``_atomic_write`` only makes the file *replace* atomic; the surrounding
    read-modify-write is not. Holding the cross-process ``file_lock`` across
    read + write serialises every STATE.json mutator, so two concurrent calls
    (built-in <-> built-in, or built-in <-> plugin dispatch) can no longer
    last-writer-wins away each other's changes — e.g. drop an action_log
    entry (issue #115). ``build(doc)`` returns the new document to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_state_lock_path(path)):
        doc = read_state_file(path)
        new_doc = build(doc)
        write_state_file(path, new_doc)
    return new_doc


def _now_iso() -> str:
    """Current time as a timezone-aware ISO 8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


def _upsert_into(
    campaigns: tuple[CampaignSnapshot, ...], campaign: CampaignSnapshot
) -> tuple[CampaignSnapshot, ...]:
    """Return ``campaigns`` with ``campaign`` replacing any same-id entry
    (or appended when new), preserving order."""
    result: list[CampaignSnapshot] = []
    found = False
    for c in campaigns:
        if c.campaign_id == campaign.campaign_id:
            result.append(campaign)
            found = True
        else:
            result.append(c)
    if not found:
        result.append(campaign)
    return tuple(result)


def upsert_campaign(
    path: Path,
    campaign: CampaignSnapshot,
    *,
    platform: str,
    account_id: str,
) -> StateDocument:
    """Upsert a campaign into STATE.json under its platform.

    Writes the v2 ``platforms[platform]`` section — the schema the
    dashboard reads — with the **required** ``account_id`` and the
    campaign, and stamps ``last_synced_at`` to now. Without these the
    document is schema-incomplete and the client renders as "not yet
    bootstrapped" / inactive even though campaigns exist.

    The legacy v1 flat ``campaigns`` list is updated in lockstep so
    readers still on the v1 shape keep working (the field is retained
    for backward compatibility — see :class:`StateDocument`).

    Args:
        path: STATE.json location.
        campaign: The campaign snapshot to insert or update.
        platform: Platform key the campaign belongs to (e.g.
            ``"google_ads"``, ``"meta_ads"``) — the ``platforms`` dict key.
        account_id: The platform account id (Google ``customer_id`` /
            Meta ``act_*``). Always written onto the platform entry so a
            per-account override is never silently dropped.

    Returns:
        The updated :class:`StateDocument`.
    """

    def _build(doc: StateDocument) -> StateDocument:
        # v1 flat list — preserved for backward compatibility.
        flat_campaigns = _upsert_into(doc.campaigns, campaign)

        # v2 per-platform — the shape the dashboard reads. Ensure the platform
        # entry exists, carries the (required) account_id, and holds the
        # campaign.
        platforms = dict(doc.platforms) if doc.platforms else {}
        existing = platforms.get(platform)
        platforms[platform] = PlatformState(
            account_id=account_id,
            campaigns=_upsert_into(
                existing.campaigns if existing is not None else (), campaign
            ),
            # Preserve the platform-level rollup: it has no upsert input, so
            # a campaign upsert must inherit it rather than reset it to None
            # (otherwise every upsert silently wipes the dashboard KPIs).
            totals=existing.totals if existing is not None else None,
            metrics_period=existing.metrics_period if existing is not None else None,
        )

        return StateDocument(
            version=doc.version,
            last_synced_at=_now_iso(),
            customer_id=doc.customer_id,
            campaigns=flat_campaigns,
            platforms=platforms,
            action_log=doc.action_log,
        )

    return _locked_state_mutation(path, _build)


def append_action_log(path: Path, entry: ActionLogEntry) -> StateDocument:
    """Append an action log entry to STATE.json.

    Reads the current state, appends the entry, and writes back atomically.

    Returns:
        Updated StateDocument
    """

    def _build(doc: StateDocument) -> StateDocument:
        return StateDocument(
            version=doc.version,
            last_synced_at=doc.last_synced_at,
            customer_id=doc.customer_id,
            campaigns=doc.campaigns,
            platforms=doc.platforms,
            action_log=(*doc.action_log, entry),
        )

    return _locked_state_mutation(path, _build)


def set_report(path: Path, report: str, summary: dict[str, Any]) -> StateDocument:
    """Persist a structured analysis ``summary`` into STATE.json ``reports``.

    Merges ``reports[report] = summary`` into the document's ``reports``
    section (a free-form ``{"daily": ..., "weekly": ..., "goal": ...}`` map
    the read-only dashboard renders), re-stamps ``last_synced_at``, and writes
    back atomically. Other report keys and the rest of the document
    (campaigns, platforms, action_log) are preserved. When ``reports`` is
    ``None`` (old STATE.json), it starts from ``{}`` — so the call is
    backward compatible.

    Args:
        path: STATE.json location.
        report: Report kind key (``"daily"`` / ``"weekly"`` / ``"goal"``).
        summary: The free-form summary object to store under that key.

    Returns:
        The updated :class:`StateDocument`.
    """

    def _build(doc: StateDocument) -> StateDocument:
        # Start from a shallow copy of the existing reports (or {} when the
        # document predates the reports section) so sibling report kinds are
        # preserved rather than wiped.
        reports = dict(doc.reports) if doc.reports else {}
        reports[report] = summary
        return StateDocument(
            version=doc.version,
            last_synced_at=_now_iso(),
            customer_id=doc.customer_id,
            campaigns=doc.campaigns,
            platforms=doc.platforms,
            action_log=doc.action_log,
            reports=reports,
        )

    return _locked_state_mutation(path, _build)


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None
