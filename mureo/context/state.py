"""Read, mutate and durably write STATE.json.

The document layer: the atomic write (temp file -> fsync -> rename), the
cross-process lock that makes a read -> modify -> write cycle one critical
section, and the targeted mutators that own STATE.json's merge semantics —
what a partial write inherits rather than resets.

Two halves that used to live here were split out in #538 to bring this file
back under the repo's size limits, both verbatim:

- the JSON codec (:func:`parse_state` / :func:`render_state` and their
  per-field helpers) is now :mod:`mureo.context.state_codec`;
- the account conversion-override lookup
  (:func:`load_conversion_action_types`) is now
  :mod:`mureo.context.conversion_overrides`.

Both are **re-exported from this module**, because ``mureo.context.state`` has
always been the single import site for the whole STATE.json surface and
callers inside and outside this tree import it from here.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mureo.context.models import ActionLogEntry, CampaignSnapshot

from mureo.context.conversion_overrides import load_conversion_action_types
from mureo.context.errors import ContextFileError
from mureo.context.models import PlatformState, StateDocument
from mureo.context.platform_guards import (
    guard_platform_entry_write,
    warn_on_duplicate_accounts,
)
from mureo.context.state_codec import parse_state, render_state
from mureo.fsutil import file_lock


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
    """Atomically write a StateDocument to a STATE.json file.

    Also emits the advisory duplicate-account warning (#534) — see
    :func:`mureo.context.platform_guards.warn_on_duplicate_accounts`. The write
    proceeds regardless.
    """
    warn_on_duplicate_accounts(path, doc)
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


def _merge_ads(
    existing: CampaignSnapshot, incoming: CampaignSnapshot
) -> CampaignSnapshot:
    """Inherit ``ads`` from ``existing`` when ``incoming`` did not supply it.

    An upsert replaces the whole snapshot, but ad-level state has no input on
    most calls: the standard flows fetch ads only for ACTIVE campaigns (an
    API-cost guard), so the first upsert after a campaign is paused — exactly
    when "what were its ads doing?" matters most — would otherwise reset
    ``ads`` from the last known statuses back to ``None`` ("never fetched"),
    silently destroying the audit trail #468 exists to create.

    Only ``None`` ("not supplied") inherits. An empty tuple is a real
    observation ("fetched, this campaign has no ads") and overwrites, as does
    any non-empty list. Each :class:`AdState` carries its own ``as_of``, so an
    inherited entry stays honestly dated rather than passing for fresh.
    """
    if incoming.ads is not None or existing.ads is None:
        return incoming
    return replace(incoming, ads=existing.ads)


def _upsert_into(
    campaigns: tuple[CampaignSnapshot, ...],
    campaign: CampaignSnapshot,
    *,
    inherit_ads: bool = False,
) -> tuple[CampaignSnapshot, ...]:
    """Return ``campaigns`` with ``campaign`` replacing any same-id entry
    (or appended when new), preserving order.

    ``inherit_ads`` enables the :func:`_merge_ads` carry-over and is safe ONLY
    for a platform-scoped list. The legacy v1 flat list matches on
    ``campaign_id`` alone — Google and Meta ids are independent namespaces, so
    a collision there matches two unrelated campaigns — and inheriting across
    that blind match would attach one account's ads to another's campaign.
    The flat list therefore keeps plain full-replace semantics.
    """
    result: list[CampaignSnapshot] = []
    found = False
    for c in campaigns:
        if c.campaign_id == campaign.campaign_id:
            result.append(_merge_ads(c, campaign) if inherit_ads else campaign)
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
    for backward compatibility — see :class:`StateDocument`). That list
    is platform-blind, so it takes the snapshot as given; ad-level state
    is inherited only in the platform-scoped v2 section (see
    :func:`_upsert_into`).

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

    Raises:
        ValueError: ``platform`` is not a usable platform key, or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """

    def _build(doc: StateDocument) -> StateDocument:
        # v1 flat list — preserved for backward compatibility.
        flat_campaigns = _upsert_into(doc.campaigns, campaign)

        # v2 per-platform — the shape the dashboard reads. Ensure the platform
        # entry exists, carries the (required) account_id, and holds the
        # campaign.
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)
        existing = platforms.get(platform)
        platforms[platform] = PlatformState(
            account_id=account_id,
            campaigns=_upsert_into(
                existing.campaigns if existing is not None else (),
                campaign,
                # Platform-scoped: a same-id match here IS the same campaign,
                # so carrying its ad-level state over is safe (#468).
                inherit_ads=True,
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

    Raises:
        ValueError: ``platform`` is not a usable platform key, or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)
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

    Raises:
        ValueError: ``platform`` is not a usable platform key, or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
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
        guard_platform_entry_write(platforms, platform, account_id)
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


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None


__all__ = [
    # Re-exported from mureo.context.state_codec / .conversion_overrides so
    # every existing ``from mureo.context.state import ...`` keeps working
    # (#538). Listed here, not merely imported, so the re-export is explicit
    # under mypy's ``no_implicit_reexport``.
    "load_conversion_action_types",
    "parse_state",
    "render_state",
    # Defined here.
    "append_action_log",
    "get_campaign",
    "read_state_file",
    "set_conversion_action_types",
    "set_platform_metrics",
    "set_report",
    "upsert_campaign",
    "write_state_file",
]
