"""Read and write STATE.json."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
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

logger = logging.getLogger(__name__)

# Required campaign fields
_CAMPAIGN_REQUIRED_FIELDS: tuple[str, ...] = (
    "campaign_id",
    "campaign_name",
    "status",
)


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
        return tuple(_parse_campaign(c) for c in raw)
    parsed: list[CampaignSnapshot] = []
    for c in raw:
        try:
            parsed.append(_parse_campaign(c))
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


def parse_state(text: str, *, strict: bool = True) -> StateDocument:
    """Parse a JSON string and return a StateDocument.

    ``strict`` controls campaign-list, action_log AND platform validation:
    ``True`` (default) preserves the strict writer contract (raises on a missing
    required field, including a platform ``account_id``); ``False`` tolerantly
    skips nonconforming campaign / action_log entries and defaults a missing
    platform ``account_id`` to ``""`` for the read-only Reports view. Invalid
    JSON always raises regardless of ``strict``.
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
    # Per-period rollups: emit only when non-empty so legacy files (and
    # entries with no per-period data) stay byte-stable on round-trip.
    if ps.periods:
        result["periods"] = copy.deepcopy(ps.periods)
    # #342 — operator conversion override: emit only when set, as a JSON list,
    # so legacy entries stay byte-stable.
    if ps.conversion_action_types:
        result["conversion_action_types"] = list(ps.conversion_action_types)
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
    """Atomically and durably write a file (temp file -> fsync -> rename).

    fsync the data before the rename so a crash/power loss just after
    ``os.replace`` cannot leave STATE.json as a zero-length/partial file (which
    would lose campaign history / action_log). Best-effort directory fsync makes
    the rename itself durable on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _fsync_dir(parent: Path) -> None:
    """Best-effort fsync of ``parent`` so a rename is durable (POSIX-only)."""
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def read_state_file(path: Path, *, strict: bool = True) -> StateDocument:
    """Read a STATE.json file and return a StateDocument.

    Returns a default StateDocument if the file does not exist. ``strict`` is
    forwarded to :func:`parse_state`: pass ``strict=False`` from the read-only
    Reports view so a nonconforming campaign entry is skipped instead of
    raising and blanking the whole document.
    """
    if not path.exists():
        return StateDocument()
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STATE.json: {path}") from exc
    try:
        return parse_state(text, strict=strict)
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
            # (otherwise every upsert silently wipes the dashboard KPIs). The
            # same applies to the per-period rollups.
            totals=existing.totals if existing is not None else None,
            metrics_period=existing.metrics_period if existing is not None else None,
            periods=existing.periods if existing is not None else None,
            # #342 — the operator conversion override has no upsert input;
            # inherit it so a campaign upsert never wipes the account setting.
            conversion_action_types=(
                existing.conversion_action_types if existing is not None else None
            ),
        )

        return StateDocument(
            version=doc.version,
            last_synced_at=_now_iso(),
            customer_id=doc.customer_id,
            campaigns=flat_campaigns,
            platforms=platforms,
            action_log=doc.action_log,
            # Preserve the analysis summaries: a campaign upsert has no reports
            # input, so dropping this would silently wipe the daily/weekly/goal
            # summaries the dashboard renders (every upsert after a report write
            # erased it).
            reports=doc.reports,
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
            # Preserve the analysis summaries — appending an action must not
            # wipe the daily/weekly/goal reports the dashboard renders.
            reports=doc.reports,
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


def set_platform_metrics(
    path: Path,
    platform: str,
    account_id: str,
    *,
    totals: dict[str, Any] | None = None,
    metrics_period: str | None = None,
    periods: dict[str, dict[str, Any]] | None = None,
) -> StateDocument:
    """Set a platform's metric rollups in STATE.json's v2 ``platforms`` section.

    Writes the platform-level KPI rollup the reporting dashboard reads — the
    single ``totals`` + ``metrics_period`` (the most recent window) and/or the
    per-period ``periods`` map (``{"YESTERDAY": {...}, "LAST_30_DAYS": {...}}``).
    The platform's campaigns and every OTHER platform are preserved; only the
    targeted platform's rollup fields are touched. The platform entry is
    created (carrying ``account_id``) when absent.

    Merge semantics — a partial write never clobbers an unrelated window:

    - ``totals`` / ``metrics_period``: replaced when provided (non-``None``),
      otherwise the existing value is preserved.
    - ``periods``: merged PER WINDOW KEY into the existing map, so a
      daily-check ``YESTERDAY`` write keeps the ``LAST_30_DAYS`` bucket a prior
      sync wrote (and vice versa). A given window key is replaced wholesale.
      ``None`` preserves the existing map untouched.

    Re-stamps ``last_synced_at`` and writes back atomically under the state
    lock. Other document sections (root campaigns, action_log, reports) are
    preserved.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
        totals: The single-rollup totals to set (or ``None`` to preserve).
        metrics_period: The window ``totals`` covers (or ``None`` to preserve).
        periods: Per-window rollups to merge in (or ``None`` to preserve).

    Returns:
        The updated :class:`StateDocument`.
    """

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        existing = platforms.get(platform)

        merged_periods: dict[str, dict[str, Any]] | None
        if periods is not None:
            base = dict(existing.periods) if existing and existing.periods else {}
            base.update(periods)
            merged_periods = base
        else:
            merged_periods = existing.periods if existing is not None else None

        platforms[platform] = PlatformState(
            account_id=account_id,
            # Rollups have no campaign input — inherit the campaigns a prior
            # sync/upsert wrote rather than reset them.
            campaigns=existing.campaigns if existing is not None else (),
            totals=(
                totals
                if totals is not None
                else (existing.totals if existing is not None else None)
            ),
            metrics_period=(
                metrics_period
                if metrics_period is not None
                else (existing.metrics_period if existing is not None else None)
            ),
            periods=merged_periods,
            # #342 — preserve the operator conversion override across a
            # metrics write (it has no input here, same rationale as totals).
            conversion_action_types=(
                existing.conversion_action_types if existing is not None else None
            ),
        )

        return StateDocument(
            version=doc.version,
            last_synced_at=_now_iso(),
            customer_id=doc.customer_id,
            campaigns=doc.campaigns,
            platforms=platforms,
            action_log=doc.action_log,
            reports=doc.reports,
        )

    return _locked_state_mutation(path, _build)


def set_conversion_action_types(
    path: Path,
    platform: str,
    account_id: str,
    conversion_action_types: list[str] | None,
) -> StateDocument:
    """Set a platform's operator conversion ``action_type`` override (#342).

    Declares EXACTLY which Meta ``action_type`` rows count as this account's
    conversions — overriding the built-in deduped generic set
    (``{lead, purchase, complete_registration}``) so a custom-event advertiser
    (``offsite_conversion.custom.<id>``) or a component-only account is counted
    correctly. Pass ``None`` (or an empty list) to clear the override and
    restore the default.

    Replacement semantics: the override is the *complete* conversion set for
    the account — the counters use these and only these, never summed on top of
    the generic set (so two overlapping alias rows can't double-count).

    The platform's campaigns / rollups and every OTHER platform are preserved;
    the entry is created (carrying ``account_id``) when absent. Re-stamps
    ``last_synced_at`` and writes back atomically under the state lock.

    Args:
        path: STATE.json location.
        platform: Platform key (e.g. ``"meta_ads"``).
        account_id: The platform account id, always written onto the entry.
        conversion_action_types: The exact action_types to count, or ``None`` /
            ``[]`` to clear.

    Returns:
        The updated :class:`StateDocument`.
    """
    cleaned: tuple[str, ...] | None = None
    if conversion_action_types:
        cleaned = tuple(
            str(x).strip()
            for x in conversion_action_types
            if isinstance(x, str) and x.strip()
        )
        cleaned = cleaned or None

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        existing = platforms.get(platform)
        platforms[platform] = PlatformState(
            account_id=account_id,
            campaigns=existing.campaigns if existing is not None else (),
            totals=existing.totals if existing is not None else None,
            metrics_period=existing.metrics_period if existing is not None else None,
            periods=existing.periods if existing is not None else None,
            conversion_action_types=cleaned,
        )
        return StateDocument(
            version=doc.version,
            last_synced_at=_now_iso(),
            customer_id=doc.customer_id,
            campaigns=doc.campaigns,
            platforms=platforms,
            action_log=doc.action_log,
            reports=doc.reports,
        )

    return _locked_state_mutation(path, _build)


def _workspace_state_path() -> Path:
    """Resolve the ACTIVE workspace's STATE.json — the same file the MCP state
    tools write to (#342).

    Mirrors ``_handlers_mureo_context._resolve_path``'s default resolution
    (``store.state_path`` → ``store.workspace / STATE.json``) via the runtime
    context, so the conversion override is read from the same file it is
    written to — even under an agency / alternate ``StateStore`` where the
    workspace diverges from the process cwd. ``get_runtime_context`` is
    imported lazily to avoid an import cycle (``runtime_context`` builds on
    ``context``). Any failure falls back to the cwd convention.
    """
    from pathlib import Path as _Path

    try:
        from mureo.core.runtime_context import get_runtime_context

        store = get_runtime_context().state_store
        attr = getattr(store, "state_path", None)
        if attr is not None:
            return _Path(attr)
        workspace = getattr(store, "workspace", None)
        if workspace is not None:
            return _Path(workspace) / "STATE.json"
    except Exception:  # noqa: BLE001 — best-effort; never break a live read.
        pass
    return _Path("STATE.json")


def _account_id_eq(a: str, b: str) -> bool:
    """Compare Meta account ids tolerant of the optional ``act_`` prefix (#342).

    The MCP setter stores whatever id the operator/agent passed; the live
    counters resolve with the ``act_*`` form the client enforces. Comparing
    after stripping a leading ``act_`` keeps a bare-numeric override from
    silently never matching.
    """
    return a.removeprefix("act_") == b.removeprefix("act_")


def load_conversion_action_types(
    account_id: str,
    *,
    path: Path | None = None,
    platform: str = "meta_ads",
) -> tuple[str, ...] | None:
    """Read an account's operator conversion override from STATE.json (#342).

    Returns the ``platforms[platform].conversion_action_types`` override when
    it is set AND the entry's ``account_id`` matches ``account_id`` (tolerant
    of the ``act_`` prefix); otherwise ``None`` so the conversion counters fall
    back to the built-in generic set.

    Reads the ACTIVE workspace ``STATE.json`` (resolved via the runtime context
    — the same file the MCP state tools write to). **Never raises**: a missing
    / unreadable / malformed file, or an absent platform entry, all yield
    ``None`` so a live analysis is never broken by a state-read failure.
    """
    state_path = path if path is not None else _workspace_state_path()
    try:
        if not state_path.exists():
            return None
        doc = parse_state(state_path.read_text(encoding="utf-8"), strict=False)
    except Exception:  # noqa: BLE001 — never break a live analysis on a bad file.
        # parse_state can raise OSError / ContextFileError / ValueError
        # (JSONDecodeError) AND AttributeError/TypeError on non-object JSON;
        # a best-effort override read must swallow all of them.
        return None
    if doc.platforms is None:
        return None
    entry = doc.platforms.get(platform)
    if entry is None or not entry.conversion_action_types:
        return None
    if (
        entry.account_id
        and account_id
        and not _account_id_eq(entry.account_id, account_id)
    ):
        return None
    return entry.conversion_action_types


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None
