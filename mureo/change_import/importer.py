"""Poll each platform's change feed and record what mureo did not do (#545).

The orchestration: work out the window, ask the feed, drop what is already
accounted for, and append the rest to ``action_log`` marked as observed
rather than performed.

**The watermark is derived, not stored.** Where the next poll starts is the
newest ``occurred_at`` mureo has already imported for that platform, read
straight out of ``action_log``; the first pass falls back to
:data:`DEFAULT_LOOKBACK_DAYS`. No new STATE.json section, nothing to keep in
sync with the log, and a hand-deleted entry re-imports instead of being
skipped forever by a watermark that outlived it.

**What this cannot recover.** History cannot be reconstructed after the fact
— Google Ads' ``change_event`` caps at 100 rows with no paging and retains
about 30 days, so a single bulk edit can consume the whole window and hide
everything before it permanently. That is why the first import's default
lookback is short: asking for 30 days invites a silent truncation. A capped
response comes back with ``truncated=True`` and is reported as such rather
than passed off as a complete answer.

**Per-platform fault isolation.** One platform's expired token must not stop
the others, and must not be reported as quiet. Each platform gets its own
:class:`~mureo.change_import.models.ChangeImportOutcome` with one of three
statuses, and "a feed ran and found nothing" is a different value from "there
is no feed" and from "the feed failed".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from mureo.change_import.dedupe import (
    ATTRIBUTION_WINDOW_MINUTES,
    classify_change,
    external_change_id,
    imported_change_ids,
)
from mureo.change_import.models import (
    ChangeImportOutcome,
    ChangeImportStatus,
    ImportVerdict,
)
from mureo.change_import.registry import get_change_feed
from mureo.context.models import EXTERNAL_ORIGIN, ActionLogEntry
from mureo.context.state import append_action_log, read_state_file
from mureo.core import clock

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from mureo.change_import.models import ChangeFeedResult, ExternalChange
    from mureo.context.models import StateDocument

#: Observation window applied to an imported change. mureo has no idea what
#: an operator's UI edit was meant to achieve, so it uses the conservative
#: default the rest of mureo already uses for a change it cannot characterise
#: (the plugin-promotion window, and the "keyword/creative changes 14 days"
#: guidance on :class:`~mureo.context.models.ActionLogEntry`) — long enough
#: that daily-check's >=7-consecutive-day evidence rule can actually be met.
EXTERNAL_OBSERVATION_DAYS = 14

#: How far back the FIRST import for a platform looks. Deliberately short.
#: A wider first window does not recover more history — it just makes a
#: row-capped feed likelier to truncate, which loses the newest changes too.
#: Continuous polling is the only thing that captures history; a one-off deep
#: backfill is not available and pretending otherwise would be the same
#: mistake the incident post-mortem hit.
DEFAULT_LOOKBACK_DAYS = 7


def to_action_log_entry(
    change: ExternalChange, *, recorded_at: datetime
) -> ActionLogEntry:
    """Build the ``action_log`` entry for one imported change.

    ``timestamp`` is when mureo recorded it (server clock, #460) and
    ``occurred_at`` is when the platform says it happened. The observation
    window anchors on the latter, so a change that has been live for three
    weeks lands already past due and daily-check reviews it on the next run
    instead of a fortnight from now.

    ``metrics_at_action`` is left unset on purpose. mureo was not present
    when the change was made and has no baseline for it; synthesising one
    from today's numbers would invent a "before" that never existed, and
    ``mureo_outcome_evaluate`` would then score a fabricated delta. The
    outcome review falls back to a qualitative read, exactly as it does for
    a plugin mutation.

    ``reversible_params`` is likewise unset, and would be ignored anyway:
    :func:`mureo.rollback.planner.plan_rollback` refuses every external entry
    (see there).
    """
    occurred = _parse_iso(change.occurred_at) or recorded_at
    due = (occurred + timedelta(days=EXTERNAL_OBSERVATION_DAYS)).date().isoformat()
    return ActionLogEntry(
        timestamp=recorded_at.isoformat(timespec="seconds"),
        action=f"external_change:{change.resource_type or 'UNKNOWN'}",
        platform=change.platform,
        campaign_id=change.campaign_id,
        ad_id=change.ad_id,
        entity_type=change.entity_type,
        entity_id=change.entity_id,
        summary=_summary(change),
        observation_due=due,
        origin=EXTERNAL_ORIGIN,
        external_id=external_change_id(change),
        occurred_at=change.occurred_at,
    )


def _summary(change: ExternalChange) -> str:
    """One line an operator can read without opening the platform.

    ``actor`` and ``client_type`` are included as CONTEXT, never as proof of
    origin: mureo's own API calls carry the same operator's OAuth email, and
    ``GOOGLE_ADS_API`` covers every API tool the account uses. The provenance
    claim lives in ``origin``; this string only says what the feed reported.
    """
    parts = [f"{change.operation or 'CHANGE'} on {change.resource_type or 'UNKNOWN'}"]
    if change.changed_fields:
        parts.append("fields: " + ", ".join(change.changed_fields))
    if change.actor:
        parts.append(f"by {change.actor}")
    if change.client_type:
        parts.append(f"via {change.client_type}")
    return "observed outside mureo — " + "; ".join(parts)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp as timezone-aware UTC, or ``None``."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def latest_imported_at(doc: StateDocument, platform: str) -> datetime | None:
    """Newest ``occurred_at`` already imported for ``platform``, or ``None``.

    The derived watermark. Reads only entries mureo imported (``origin`` is
    external): a mureo-originated entry's ``timestamp`` says when mureo acted,
    which is no evidence about how far the change FEED has been read.
    """
    newest: datetime | None = None
    for entry in doc.action_log:
        if not entry.is_external or entry.platform != platform:
            continue
        moment = _parse_iso(entry.occurred_at or entry.timestamp)
        if moment is not None and (newest is None or moment > newest):
            newest = moment
    return newest


def _platform_keys(
    doc: StateDocument, platforms: Sequence[str] | None
) -> tuple[str, ...]:
    """Which platforms this pass covers, in a stable order.

    Defaults to every key in STATE.json's ``platforms`` section — including
    the ones with no feed, which is the point: they have to be REPORTED as
    unavailable, not quietly left out of the answer.
    """
    if platforms is not None:
        return tuple(dict.fromkeys(p for p in platforms if p))
    return tuple(sorted(doc.platforms or {}))


def _account_id(
    doc: StateDocument, platform: str, overrides: Mapping[str, str] | None
) -> str:
    """The account id to poll for ``platform``."""
    if overrides and platform in overrides:
        return overrides[platform]
    entry = (doc.platforms or {}).get(platform)
    return entry.account_id if entry is not None else ""


async def _fetch(
    platform: str, account_id: str, *, since: datetime, until: datetime
) -> ChangeFeedResult:
    """Ask ``platform``'s registered feed for the window. Raises on failure."""
    feed = get_change_feed(platform)
    if feed is None:  # pragma: no cover — caller checks first
        raise LookupError(platform)
    return await feed.fetch_change_events(account_id, since=since, until=until)


async def _import_one_platform(
    path: Path,
    platform: str,
    *,
    doc: StateDocument,
    account_ids: Mapping[str, str] | None,
    since: datetime | None,
    now: datetime,
    window_minutes: int,
) -> ChangeImportOutcome:
    """Run one platform's import. Never raises."""
    if get_change_feed(platform) is None:
        # Honest degradation, the same contract as
        # ``analytics_not_available_for_<platform>``. Absence of a feed is
        # NOT evidence that nothing happened on that platform.
        return ChangeImportOutcome(
            platform=platform,
            status=ChangeImportStatus.UNAVAILABLE,
            reason=f"change_import_unavailable_for_{platform}",
            until=now.isoformat(),
            notes=(
                f"mureo has no change feed for {platform}, so manual work there "
                "is invisible to mureo. This is not evidence that none happened.",
            ),
        )

    start = (
        since
        or latest_imported_at(doc, platform)
        or (now - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    )
    try:
        result = await _fetch(
            platform, _account_id(doc, platform, account_ids), since=start, until=now
        )
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # noqa: BLE001 — one platform must not stop the rest
        return ChangeImportOutcome(
            platform=platform,
            status=ChangeImportStatus.ERROR,
            since=start.isoformat(),
            until=now.isoformat(),
            reason=f"{type(exc).__name__}: {exc}",
            notes=(
                f"The {platform} change feed could not be read, so this window "
                "was NOT checked. Treat it as unreviewed, not as quiet.",
            ),
        )

    if result.unavailable_reason:
        # A registered feed that could not answer for THIS account or mode
        # (BYOD, an unsupported account type). It did not look, so it must not
        # land in the same bucket as a feed that looked and found nothing —
        # only UNAVAILABLE and ERROR reach ``blind_spots``, and a platform
        # missing from ``blind_spots`` is one the agent is told was checked.
        return ChangeImportOutcome(
            platform=platform,
            status=ChangeImportStatus.UNAVAILABLE,
            since=start.isoformat(),
            until=now.isoformat(),
            reason=f"change_import_unavailable_for_{platform}",
            notes=(*result.notes, result.unavailable_reason),
        )

    own, foreign = _split_by_platform(result.changes, platform)
    imported: list[int] = []
    already = 0
    attributed = 0
    seen = set(imported_change_ids(doc))
    for change in own:
        verdict = classify_change(
            change, doc, window_minutes=window_minutes, seen_ids=seen
        )
        if verdict is ImportVerdict.ALREADY_IMPORTED:
            already += 1
            continue
        if verdict is ImportVerdict.ATTRIBUTED_TO_MUREO:
            attributed += 1
            continue
        # Append through the normal choke point for the state lock and the
        # atomic write, but explicitly OUT of any open batch (#549).
        #
        # A batch is the operator's declared change set — "what I did on
        # Monday". A change mureo merely observed is by definition not
        # something they did through mureo, and letting it join would make
        # that set mean something else: an unrelated UI edit imported while
        # the batch happened to be open would drop the whole batch's rollback
        # coverage to ``partial`` and be listed as a member the operator
        # cannot reverse. The same reasoning as the rollback executor's own
        # ``rollback_of`` record, which is excluded for the same reason.
        doc = append_action_log(
            path,
            to_action_log_entry(change, recorded_at=now),
            join_active_batch=False,
        )
        imported.append(len(doc.action_log) - 1)
        seen.add(external_change_id(change))

    notes = result.notes
    if foreign:
        notes = (*notes, _foreign_platform_note(platform, foreign))
    return ChangeImportOutcome(
        platform=platform,
        status=ChangeImportStatus.IMPORTED,
        imported=tuple(imported),
        already_imported=already,
        attributed_to_mureo=attributed,
        since=start.isoformat(),
        until=now.isoformat(),
        truncated=result.truncated,
        notes=notes,
    )


def _split_by_platform(
    changes: tuple[ExternalChange, ...], platform: str
) -> tuple[tuple[ExternalChange, ...], tuple[ExternalChange, ...]]:
    """Partition ``changes`` into this platform's and everything else's.

    A feed answers for the platform it registered under and no other. Writing
    a change it labelled with a different key would let one distribution's feed
    file entries against another platform's account — silently, since every
    downstream surface joins on that key. Cheap to enforce, so enforce it: the
    strays are dropped and reported rather than trusted or discarded quietly.
    """
    own = tuple(c for c in changes if c.platform == platform)
    foreign = tuple(c for c in changes if c.platform != platform)
    return own, foreign


def _foreign_platform_note(platform: str, foreign: tuple[ExternalChange, ...]) -> str:
    """Say which platform keys a feed tried to write outside its own."""
    keys = sorted({c.platform for c in foreign})
    return (
        f"The {platform} change feed returned {len(foreign)} change(s) labelled "
        f"for other platforms ({', '.join(repr(k) for k in keys)}); they were "
        "dropped. A feed answers only for the platform it registered under."
    )


async def import_external_changes(
    path: Path,
    *,
    platforms: Sequence[str] | None = None,
    account_ids: Mapping[str, str] | None = None,
    since: datetime | None = None,
    now: datetime | None = None,
    window_minutes: int = ATTRIBUTION_WINDOW_MINUTES,
) -> tuple[ChangeImportOutcome, ...]:
    """Import each platform's unseen changes into ``path``'s ``action_log``.

    Args:
        path: STATE.json location.
        platforms: Platform keys to cover. Defaults to every key in
            STATE.json's ``platforms`` section, so a platform with no feed is
            still reported as unavailable rather than omitted.
        account_ids: Per-platform account id override. Defaults to the
            ``account_id`` on each platform's STATE.json entry.
        since: Explicit window start for every platform, overriding the
            derived watermark. Use it to re-check a period, not to backfill:
            a capped feed cannot answer a wide window.
        now: Window end and record time. Defaults to the server clock (#460).
        window_minutes: Attribution window — see
            :data:`~mureo.change_import.dedupe.ATTRIBUTION_WINDOW_MINUTES`.

    Returns:
        One :class:`~mureo.change_import.models.ChangeImportOutcome` per
        platform, in the order the platforms were resolved. Never raises for
        a platform-level failure; that is reported as ``ERROR``.
    """
    resolved_now = now or clock.server_now()
    doc = read_state_file(path)
    outcomes = []
    for platform in _platform_keys(doc, platforms):
        outcome = await _import_one_platform(
            path,
            platform,
            doc=read_state_file(path),
            account_ids=account_ids,
            since=since,
            now=resolved_now,
            window_minutes=window_minutes,
        )
        outcomes.append(outcome)
    return tuple(outcomes)


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "EXTERNAL_OBSERVATION_DAYS",
    "import_external_changes",
    "latest_imported_at",
    "to_action_log_entry",
]
