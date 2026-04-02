"""Read and write STATE.json."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from mureo.context.errors import ContextFileError
from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    PlatformState,
    StateDocument,
)

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

    return json.dumps(data, ensure_ascii=False, indent=2)


def _platform_state_to_dict(ps: PlatformState) -> dict[str, Any]:
    """Convert a PlatformState to a dictionary."""
    return {
        "account_id": ps.account_id,
        "campaigns": [_snapshot_to_dict(c) for c in ps.campaigns],
    }


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
    return result


def _snapshot_to_dict(c: CampaignSnapshot) -> dict[str, Any]:
    """Convert a CampaignSnapshot to a dictionary."""
    device_targeting: list[dict[str, Any]] | None = None
    if c.device_targeting is not None:
        device_targeting = list(c.device_targeting)
    return {
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


def upsert_campaign(path: Path, campaign: CampaignSnapshot) -> StateDocument:
    """Upsert a campaign (update if exists, add if not).

    Returns:
        Updated StateDocument
    """
    doc = read_state_file(path)
    found = False
    new_campaigns: list[CampaignSnapshot] = []
    for c in doc.campaigns:
        if c.campaign_id == campaign.campaign_id:
            new_campaigns.append(campaign)
            found = True
        else:
            new_campaigns.append(c)
    if not found:
        new_campaigns.append(campaign)

    new_doc = StateDocument(
        version=doc.version,
        last_synced_at=doc.last_synced_at,
        customer_id=doc.customer_id,
        campaigns=tuple(new_campaigns),
        platforms=doc.platforms,
        action_log=doc.action_log,
    )
    write_state_file(path, new_doc)
    return new_doc


def append_action_log(path: Path, entry: ActionLogEntry) -> StateDocument:
    """Append an action log entry to STATE.json.

    Reads the current state, appends the entry, and writes back atomically.

    Returns:
        Updated StateDocument
    """
    doc = read_state_file(path)
    new_log = (*doc.action_log, entry)
    new_doc = StateDocument(
        version=doc.version,
        last_synced_at=doc.last_synced_at,
        customer_id=doc.customer_id,
        campaigns=doc.campaigns,
        platforms=doc.platforms,
        action_log=new_log,
    )
    write_state_file(path, new_doc)
    return new_doc


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None
