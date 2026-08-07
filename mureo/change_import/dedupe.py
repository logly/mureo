"""Decide what to do with one candidate change (#545).

Two ways the same real-world change can already be accounted for, and both
have to be caught or ``action_log`` stops being a record and becomes a tally:

1. **mureo imported it on an earlier pass.** Feeds are polled with an
   overlapping window on purpose (a feed's boundary handling is its own
   business), so re-seeing a change is the normal case, not the exception.
   Caught exactly, by :func:`external_change_id`.

2. **mureo made it.** Every change mureo dispatches also appears in the
   platform's own change feed. Importing that back as "external" would
   double-count mureo's own work and — far worse — would file a change mureo
   CAN reverse under a provenance that says it cannot. Caught by matching
   target identity within a bounded time window.

Case 2 cannot be caught exactly, and it is worth being precise about why.
The feed's own attribution fields do not separate the two: Google reports
``user_email`` (mureo's API calls carry the same operator's OAuth identity as
that operator's UI session) and ``client_type`` (``GOOGLE_ADS_API`` covers
mureo and every other API tool the account has). So the discriminator is
mureo's own log: same platform, same target, close in time.

**Which way it fails matters.** When identity is missing on either side the
match cannot be made, and the change is imported as external. That direction
is deliberate: an over-import shows the operator a change they may have made
through mureo (visible, annoying, correctable), while an over-attribution
silently swallows a real UI edit — which is precisely the blindness #545
exists to remove. Never trade a visible wrong answer for an invisible one.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from mureo.change_import.models import ImportVerdict

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from mureo.change_import.models import ExternalChange
    from mureo.context.models import ActionLogEntry, StateDocument

#: How far apart a mureo ``action_log`` entry and a feed row may be and still
#: be read as the same event. mureo stamps its entry when the call returns;
#: a platform stamps the change when it commits it, and the two clocks are
#: not the same clock. Ten minutes absorbs that skew and a slow API call
#: without being wide enough to let an unrelated hand edit on the same target
#: hide behind a mureo action from earlier in the session.
ATTRIBUTION_WINDOW_MINUTES = 10


def external_change_id(change: ExternalChange) -> str:
    """The dedup identity for ``change``, namespaced by platform.

    ``"<platform>|<id>"``. The id half is the feed's own stable identifier
    when it has one (Google Ads' ``change_event.resource_name``) — that is
    exact, and exactness is what makes a repeated poll a no-op.

    A feed with no native id falls back to a content fingerprint over
    everything that identifies the change. The cost is explicit: two changes
    that are identical in every recorded field, including the timestamp, are
    indistinguishable and collapse to one entry. For a review log that is the
    right answer — the operator would read them as one change anyway — but a
    feed that CAN supply an id should, because the fingerprint also shifts if
    the adapter ever normalises a field differently.

    The platform prefix is not decoration: two platforms' internal ids share
    no namespace, and ``action_log`` holds every platform in one list.
    """
    native = change.change_id.strip()
    if native:
        return f"{change.platform}|{native}"
    material = "\x1f".join(
        (
            change.platform,
            change.occurred_at,
            change.resource_type,
            change.operation,
            ",".join(change.changed_fields),
            change.actor,
            change.campaign_id or "",
            change.ad_id or "",
            change.entity_type or "",
            change.entity_id or "",
        )
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"{change.platform}|sha256:{digest}"


def imported_change_ids(doc: StateDocument) -> frozenset[str]:
    """Every ``external_id`` already recorded in ``doc``'s ``action_log``."""
    return frozenset(
        entry.external_id for entry in doc.action_log if entry.external_id is not None
    )


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp as timezone-aware UTC, or ``None``.

    A naive value is read as UTC so a hand-edited or legacy entry still
    compares rather than raising. Unparseable input yields ``None``, which
    every caller treats as "cannot compare" — never as "close enough".
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _identity_pairs(
    *, campaign_id: str | None, ad_id: str | None, entity_id: str | None
) -> frozenset[tuple[str, str]]:
    """The ``(slot, value)`` identities carried by a change or an entry.

    Slot-qualified so a campaign id can never match an ad id that happens to
    be the same string — Google and Meta both mint numeric ids from separate
    namespaces, and an unqualified match would attribute across them.
    """
    pairs = {
        ("campaign_id", campaign_id),
        ("ad_id", ad_id),
        ("entity_id", entity_id),
    }
    return frozenset((slot, value) for slot, value in pairs if value)


def _entry_matches(
    entry: ActionLogEntry,
    change: ExternalChange,
    change_time: datetime,
    window: timedelta,
) -> bool:
    """Is ``entry`` mureo's own record of ``change``?"""
    # Only mureo-originated entries can absorb a change. An already-imported
    # external entry must never attribute a later one, or a single UI edit
    # would suppress every subsequent edit on the same target.
    if entry.origin is not None or entry.platform != change.platform:
        return False
    shared = _identity_pairs(
        campaign_id=change.campaign_id,
        ad_id=change.ad_id,
        entity_id=change.entity_id,
    ) & _identity_pairs(
        campaign_id=entry.campaign_id,
        ad_id=entry.ad_id,
        entity_id=entry.entity_id,
    )
    if not shared:
        return False
    entry_time = _parse_iso(entry.timestamp)
    if entry_time is None:
        return False
    return abs(entry_time - change_time) <= window


def classify_change(
    change: ExternalChange,
    doc: StateDocument,
    *,
    window_minutes: int = ATTRIBUTION_WINDOW_MINUTES,
    seen_ids: AbstractSet[str] | None = None,
) -> ImportVerdict:
    """Decide whether ``change`` should be recorded, and if not, why not.

    Args:
        change: The candidate from a platform's change feed.
        doc: The parsed STATE.json to compare against. Not mutated.
        window_minutes: Attribution window — see
            :data:`ATTRIBUTION_WINDOW_MINUTES`.
        seen_ids: Precomputed :func:`imported_change_ids` for ``doc``, so a
            caller classifying a whole page walks the log once instead of
            once per change. Read-only here; a caller importing as it goes
            passes its own growing set so the second copy of one change in the
            same page is still caught.

    Returns:
        The :class:`~mureo.change_import.models.ImportVerdict`.
    """
    already = imported_change_ids(doc) if seen_ids is None else seen_ids
    if external_change_id(change) in already:
        return ImportVerdict.ALREADY_IMPORTED

    change_time = _parse_iso(change.occurred_at)
    if change_time is None:
        # An unusable timestamp cannot be compared, so nothing can be
        # attributed to mureo — record it rather than guess.
        return ImportVerdict.IMPORT

    window = timedelta(minutes=window_minutes)
    for entry in doc.action_log:
        if _entry_matches(entry, change, change_time, window):
            return ImportVerdict.ATTRIBUTED_TO_MUREO
    return ImportVerdict.IMPORT


__all__ = [
    "ATTRIBUTION_WINDOW_MINUTES",
    "classify_change",
    "external_change_id",
    "imported_change_ids",
]
