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
   same platform, **same kind of change**, same target, close in time.

Case 2 cannot be caught exactly, and it is worth being precise about why.
The feed's own attribution fields do not separate the two: Google reports
``user_email`` (mureo's API calls carry the same operator's OAuth identity as
that operator's UI session) and ``client_type`` (``GOOGLE_ADS_API`` covers
mureo and every other API tool the account has). So the discriminator is
mureo's own log.

**Identity and time alone are not enough**, and the gap is not theoretical:
mureo pauses campaign 111, four minutes later the operator edits that same
campaign's budget by hand, and an identity-only match swallows the budget
edit as mureo's own status toggle. Manual and mureo-driven operation
overlapping on the same campaign is normal for a while after onboarding (see
``/daily-check`` → *Mixed operation*), so this is the common case, not the
corner. A match therefore also requires the two to be the **same kind of
change** — see :func:`change_kind` / :func:`action_kind` for the vocabulary
and :func:`_kinds_match` for the rule.

**Which way it fails matters.** Wherever the comparison cannot be made —
identity missing on either side, kind underivable on either side — the change
is imported as external. That direction is deliberate: an over-import shows
the operator a change they may have made through mureo (visible, annoying,
correctable), while an over-attribution silently swallows a real UI edit —
which is precisely the blindness #545 exists to remove. Never trade a visible
wrong answer for an invisible one.

**One case still fails the expensive way, and it cannot be fixed here.** A
hand edit to the SAME setting on the SAME entity within the window of a mureo
change is indistinguishable from mureo's own — the two rows agree in every
field the feed exposes — so it is attributed to mureo and lost. That is the
mixed-operation pattern from the incident behind #545, not an exotic shape.
It is bounded (a different entity, or a different setting on the same entity,
imports normally), so it is documented as an operator-facing limitation with
concrete advice in ``docs/change-import.md`` and in the ``_mureo-shared``
skill rather than papered over here. Anyone tempted to close it by loosening
the comparison should read that section first: every loosening moves MORE
changes into this bucket.
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
#: not the same clock. Ten minutes absorbs that skew and a slow API call.
#:
#: **The trade-off is asymmetric, so this number should not be raised
#: casually.** Widening it can only ever cause MORE attribution, and the
#: attributions it adds are the least certain ones — a hand edit further from
#: mureo's action, hiding behind it. That failure is silent: the operator's
#: change is discarded and nothing says so. Narrowing it can only cause more
#: over-import, which the operator sees and can dismiss. When in doubt, keep
#: it small: the kind + identity requirements below carry most of the
#: precision, and the window is only there to absorb clock skew.
ATTRIBUTION_WINDOW_MINUTES = 10

#: Coarse "what kind of thing changed" vocabulary, shared by both sides of the
#: attribution comparison. Deliberately small: it only has to be fine enough
#: to separate the changes an operator would describe differently, and every
#: extra distinction is another way for a legitimate match to be missed (which
#: costs an over-import) OR for two unlike changes to land in one bucket
#: (which costs a silent swallow — the expensive direction).
KIND_STATUS = "status"
KIND_BUDGET = "budget"
KIND_BID = "bid"
KIND_CRITERION = "criterion"
KIND_AD = "ad"
KIND_AD_GROUP = "ad_group"
KIND_CAMPAIGN = "campaign"

#: ``changed_fields`` substrings that override the resource type. A Google
#: budget edit can arrive as ``CAMPAIGN`` + ``changed_fields=["campaign_budget"]``
#: as easily as ``CAMPAIGN_BUDGET``; reading only the resource type would call
#: the first one a generic campaign edit and let it match a status toggle.
#: Ordered — first hit wins.
_FIELD_KINDS: tuple[tuple[str, str], ...] = (
    ("budget", KIND_BUDGET),
    ("bid", KIND_BID),
    ("status", KIND_STATUS),
)

#: Feed ``resource_type`` -> kind. Types absent here yield ``""`` ("unknown"),
#: which blocks attribution rather than falling back to a permissive default.
_RESOURCE_KINDS: dict[str, str] = {
    "CAMPAIGN_BUDGET": KIND_BUDGET,
    "AD_GROUP_BID_MODIFIER": KIND_BID,
    "CAMPAIGN_CRITERION": KIND_CRITERION,
    "AD_GROUP_CRITERION": KIND_CRITERION,
    "AD": KIND_AD,
    "AD_GROUP_AD": KIND_AD,
    "AD_GROUP": KIND_AD_GROUP,
    "CAMPAIGN": KIND_CAMPAIGN,
}

#: ``action_log`` action-name substrings -> kind. ORDER IS THE CONTRACT: the
#: first hit wins, so the more specific verbs must precede the entity nouns.
#: ``google_ads_campaigns_update_status`` has to read as a status change, not
#: as a generic campaign edit, or the very case this exists to block would
#: still match.
_ACTION_KINDS: tuple[tuple[str, str], ...] = (
    ("budget", KIND_BUDGET),
    ("bid", KIND_BID),
    ("keyword", KIND_CRITERION),
    ("criteri", KIND_CRITERION),
    ("negative", KIND_CRITERION),
    ("placement", KIND_CRITERION),
    ("exclusion", KIND_CRITERION),
    ("targeting", KIND_CRITERION),
    ("audience", KIND_CRITERION),
    ("_status", KIND_STATUS),
    ("pause", KIND_STATUS),
    ("enable", KIND_STATUS),
    ("resume", KIND_STATUS),
    ("creative", KIND_AD),
    ("ads_create", KIND_AD),
    ("ads_update", KIND_AD),
    ("ad_group", KIND_AD_GROUP),
    ("ad_set", KIND_AD_GROUP),
    ("campaign", KIND_CAMPAIGN),
)

#: Feed operation -> canonical verb, and the same for an action name. Used
#: only to REFUTE a match (see :func:`_operations_conflict`), never to require
#: one: a tool called ``*_update`` may well be an upsert, so demanding
#: agreement here would block far more true matches than it protects.
_OPERATION_ALIASES: dict[str, str] = {
    "CREATE": "create",
    "ADD": "create",
    "REMOVE": "remove",
    "DELETE": "remove",
    "UPDATE": "update",
}
_ACTION_OPERATIONS: tuple[tuple[str, str], ...] = (
    ("_remove", "remove"),
    ("_delete", "remove"),
    ("_add", "create"),
    ("_create", "create"),
)

#: Identity slots in order of INCREASING specificity. The order is mureo's
#: existing canonical-target precedence (#524): an explicitly declared
#: ``entity_id`` outranks an ``ad_id``, which outranks the campaign.
_IDENTITY_SLOTS: tuple[str, ...] = ("campaign_id", "ad_id", "entity_id")


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


def _identities(
    *,
    campaign_id: str | None,
    ad_id: str | None,
    entity_type: str | None,
    entity_id: str | None,
) -> dict[str, str]:
    """The populated ``{slot: value}`` identities of a change or an entry.

    Slot-keyed so a campaign id can never be compared against an ad id that
    happens to be the same string — Google and Meta both mint numeric ids from
    separate namespaces, and an unqualified comparison would match across them.

    The generic slot folds ``entity_type`` into its value for the same reason.
    ``entity_id`` is only unique within a kind: an ``ad_group`` numbered 999
    and a ``keyword`` numbered 999 are different things, and comparing the
    bare id would call them the same target. Google and Meta happen to make
    that collision unlikely, but a plugin declaring its own ``entity_type``
    (:class:`mureo.mcp.plugin_semantics.IdentityDeclaration`) gives no such
    guarantee — and ``ExternalChange`` has always documented ``entity_type``
    as part of identity, so it has to actually be part of it.
    """
    generic = f"{entity_type or ''}:{entity_id}" if entity_id else None
    return {
        slot: value
        for slot, value in (
            ("campaign_id", campaign_id),
            ("ad_id", ad_id),
            ("entity_id", generic),
        )
        if value
    }


def _finest_slot(identities: dict[str, str]) -> str:
    """The most specific slot ``identities`` can answer at, or ``""``.

    The precedence is mureo's existing canonical-target rule (#524, and
    ``/daily-check`` step 9): an explicitly declared ``entity_id`` outranks an
    ``ad_id``, which outranks the campaign. Reusing it here means "how
    specifically can this side name its target" has one answer across mureo
    rather than a second, private one in the deduper.
    """
    for slot in reversed(_IDENTITY_SLOTS):
        if slot in identities:
            return slot
    return ""


def _identities_agree(own: dict[str, str], other: dict[str, str]) -> bool:
    """Do two sides name the SAME target — not merely an overlapping one?

    This used to intersect the two identity sets and accept a non-empty
    result, which is "some slot agrees" and not "nothing disagrees". Two
    failures came out of that, and both discarded a real operator edit:

    - mureo updates keyword ``kw-A``'s bid; four minutes later the operator
      edits ``kw-B``'s bid in the same campaign. ``entity_id`` disagrees
      outright, but the shared ``campaign_id`` alone satisfied the
      intersection, so it never got consulted.
    - mureo pauses one ad; the operator pauses the whole campaign. ``ad_id``
      is simply absent on a campaign-level feed row, so the match fell back
      to the coarser shared field and a small mureo action swallowed a much
      larger operator action.

    Two conditions now, and both are the module's stated bias applied at this
    layer rather than only at the kind layer:

    1. **No populated-both-sides slot may disagree.** Rejecting on any
       disagreement, rather than accepting on any agreement, is the whole fix
       for the first case.
    2. **Both sides must be able to answer at the same specificity.** If one
       side names an ad and the other can only name a campaign, they are not
       known to be the same target — they are a target and a container. That
       is *unresolved*, and unresolved must mean import, because attributing
       it is how the second case swallowed a campaign-wide pause.
    """
    for slot in own.keys() & other.keys():
        if own[slot] != other[slot]:
            return False
    own_finest = _finest_slot(own)
    other_finest = _finest_slot(other)
    # No identity at all on a side: nothing to compare, so nothing is the
    # same. (Condition 1 is vacuously true for an empty set, which is exactly
    # why it cannot be the only condition.)
    if not own_finest or not other_finest:
        return False
    return own_finest == other_finest


def change_kind(change: ExternalChange) -> str:
    """The coarse kind of thing ``change`` touched, or ``""`` when unknown.

    ``changed_fields`` is consulted BEFORE ``resource_type`` because it is the
    more specific signal: a budget edit reaches the feed as ``CAMPAIGN`` +
    ``changed_fields=["campaign_budget"]`` at least as often as it reaches it
    as ``CAMPAIGN_BUDGET``, and reading only the resource type would classify
    that as a generic campaign edit — which is exactly the bucket a status
    toggle falls into.

    ``""`` is returned rather than a permissive default. A kind mureo cannot
    derive must not be allowed to match anything; see :func:`_kinds_match`.
    """
    for field in change.changed_fields:
        lowered = field.lower()
        for token, kind in _FIELD_KINDS:
            if token in lowered:
                return kind
    return _RESOURCE_KINDS.get(change.resource_type.strip().upper(), "")


def action_kind(action: str) -> str:
    """The coarse kind of thing an ``action_log`` action touched, or ``""``.

    Matched against the tool name because that is all a recorded action
    reliably carries — an agent-supplied ``summary`` is free text. The rules
    are ordered verb-before-noun (see :data:`_ACTION_KINDS`), so
    ``google_ads_campaigns_update_status`` is a status change and not a
    campaign edit.

    A free-text or unrecognised action yields ``""``. That costs an
    over-import for platforms whose mutations mureo records by hand, and that
    is the correct side to be wrong on.
    """
    normalized = action.strip().lower().replace("-", "_")
    for token, kind in _ACTION_KINDS:
        if token in normalized:
            return kind
    return ""


def _kinds_match(entry: ActionLogEntry, change: ExternalChange) -> bool:
    """Do the two describe the same kind of change?

    Both sides must yield a kind AND the two must be equal. "Unknown matches
    anything" would restore the identity-only behaviour for every action mureo
    cannot classify, which is the permissive direction — and permissive here
    means silently discarding an operator's edit.
    """
    feed_kind = change_kind(change)
    own_kind = action_kind(entry.action)
    return bool(feed_kind) and feed_kind == own_kind


def _operations_conflict(entry: ActionLogEntry, change: ExternalChange) -> bool:
    """Do the two definitely disagree about create-vs-remove?

    Only a definite disagreement refutes; an unknown verb on either side
    imposes no constraint. This catches the case kind matching cannot — mureo
    removing a negative keyword while the operator adds one on the same ad
    group in the same minute — without demanding a verb mapping that is
    genuinely ambiguous for the ``*_update`` upsert family.
    """
    feed_op = _OPERATION_ALIASES.get(change.operation.strip().upper(), "")
    if not feed_op:
        return False
    normalized = entry.action.strip().lower().replace("-", "_")
    for token, own_op in _ACTION_OPERATIONS:
        if token in normalized:
            return own_op != feed_op
    return False


def _entry_matches(
    entry: ActionLogEntry,
    change: ExternalChange,
    change_time: datetime,
    window: timedelta,
) -> bool:
    """Is ``entry`` mureo's own record of ``change``?

    Four conditions, all required: same platform, same kind of change, the
    SAME target (see :func:`_identities_agree` — not merely an overlapping
    one), and within the attribution window. Dropping any one of them makes
    mureo swallow an operator's edit that merely happened near one of its own.
    """
    # Only mureo-originated entries can absorb a change. An already-imported
    # external entry must never attribute a later one, or a single UI edit
    # would suppress every subsequent edit on the same target.
    if entry.origin is not None or entry.platform != change.platform:
        return False
    if not _kinds_match(entry, change) or _operations_conflict(entry, change):
        return False
    if not _identities_agree(
        _identities(
            campaign_id=entry.campaign_id,
            ad_id=entry.ad_id,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
        ),
        _identities(
            campaign_id=change.campaign_id,
            ad_id=change.ad_id,
            entity_type=change.entity_type,
            entity_id=change.entity_id,
        ),
    ):
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
    "KIND_AD",
    "KIND_AD_GROUP",
    "KIND_BID",
    "KIND_BUDGET",
    "KIND_CAMPAIGN",
    "KIND_CRITERION",
    "KIND_STATUS",
    "action_kind",
    "change_kind",
    "classify_change",
    "external_change_id",
    "imported_change_ids",
]
