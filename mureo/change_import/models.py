"""The shapes a change feed produces and the importer reports (#545).

One normalised change record, one feed response, and one per-platform
outcome. Everything here is a frozen dataclass or an enum: the per-platform
adapters map their vendor payload onto :class:`ExternalChange` and the rest
of mureo never sees a vendor shape.

Why the outcome carries so many counters. "How many changes were imported"
is not the question an operator has. The question is *what did mureo look
at, and what is it still blind to* — so the outcome distinguishes a feed
that ran and found nothing (:data:`ChangeImportStatus.IMPORTED` with an
empty ``imported``) from a platform that has no feed at all
(:data:`ChangeImportStatus.UNAVAILABLE`) from a feed that failed
(:data:`ChangeImportStatus.ERROR`), and reports ``truncated`` when the
window was wider than the feed could answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChangeImportStatus(str, Enum):
    """What happened for one platform on one import pass.

    ``IMPORTED`` with an empty ``imported`` tuple is a real answer: the feed
    ran and the window was quiet. It is deliberately a DIFFERENT value from
    ``UNAVAILABLE`` — conflating the two is the exact failure #545 exists to
    remove, because it lets "nothing happened" and "something happened that I
    cannot see" render identically.
    """

    #: A feed ran. ``imported`` may still be empty.
    IMPORTED = "imported"
    #: No change feed is registered for this platform. Nothing was checked.
    UNAVAILABLE = "unavailable"
    #: A feed is registered but the fetch failed. Nothing was checked.
    ERROR = "error"


class ImportVerdict(Enum):
    """What the deduper decided about one candidate change."""

    #: Not seen before and not attributable to mureo — record it.
    IMPORT = "import"
    #: This exact change is already in ``action_log`` from an earlier pass.
    ALREADY_IMPORTED = "already_imported"
    #: The feed is echoing a change mureo itself made. Do not double-count.
    ATTRIBUTED_TO_MUREO = "attributed_to_mureo"


@dataclass(frozen=True)
class ExternalChange:
    """One change observed on a platform, normalised across platforms.

    ``occurred_at`` is when the PLATFORM says the change happened, which is
    routinely hours or days before mureo sees it. It is what the observation
    window anchors on: a change made a week ago has been live for a week, and
    dating it from the import would push its review a week too late.

    ``change_id`` is the feed's own stable identifier when it has one (Google
    Ads supplies ``change_event.resource_name``). A feed with none leaves it
    blank and :func:`mureo.change_import.dedupe.external_change_id` derives a
    content fingerprint instead — see there for what that costs.

    Identity (``campaign_id`` / ``ad_id`` / ``entity_type`` + ``entity_id``)
    is what lets mureo tell its own change apart from an operator's. A feed
    that supplies none is still imported, but nothing can be attributed to
    mureo, so mureo's own change would be recorded twice. Adapters should
    populate whatever the feed exposes.

    ``actor`` and ``client_type`` are context for the reader, never evidence
    of origin: mureo's API calls carry the same OAuth user's email as that
    user's own UI session.
    """

    platform: str
    occurred_at: str
    resource_type: str
    operation: str
    change_id: str = ""
    changed_fields: tuple[str, ...] = ()
    actor: str = ""
    client_type: str = ""
    campaign_id: str | None = None
    ad_id: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None

    def __post_init__(self) -> None:
        """Normalise ``changed_fields`` to a tuple (defensive copy)."""
        if not isinstance(self.changed_fields, tuple):
            object.__setattr__(self, "changed_fields", tuple(self.changed_fields))


@dataclass(frozen=True)
class ChangeFeedResult:
    """One feed's answer for one window.

    ``truncated`` is the field that matters most. Google Ads' ``change_event``
    returns at most 100 rows with no paging, so a single bulk edit can consume
    the whole window and make everything before it permanently unreachable.
    A feed that hit its cap MUST say so: reporting a capped page as a complete
    answer turns a known blind spot into an invisible one.

    ``unavailable_reason`` is how a feed says "I did not look" as distinct
    from "I looked and the window was quiet". A feed that is registered but
    cannot answer for this account or mode — BYOD, an unsupported account
    type, a plan without change history — MUST set it rather than return an
    empty ``changes`` tuple. The two render identically to an operator
    otherwise, and the whole point of #545 is that they must not: the
    importer maps a non-empty value to
    :data:`ChangeImportStatus.UNAVAILABLE`, which is what puts the platform
    in ``blind_spots``.

    ``notes`` carries anything else the operator needs to read the result
    honestly (retention limits, kinds of change the feed omits).
    """

    changes: tuple[ExternalChange, ...] = ()
    truncated: bool = False
    notes: tuple[str, ...] = ()
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        """Normalise the sequence fields to tuples (defensive copies)."""
        if not isinstance(self.changes, tuple):
            object.__setattr__(self, "changes", tuple(self.changes))
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(self.notes))


@dataclass(frozen=True)
class ChangeImportOutcome:
    """What one import pass did for one platform.

    ``imported`` holds ``action_log`` indices, not a count, so a caller can
    address each new entry — the same index ``rollback_plan_get`` and
    ``evaluation_of`` use.
    """

    platform: str
    status: ChangeImportStatus
    imported: tuple[int, ...] = ()
    already_imported: int = 0
    attributed_to_mureo: int = 0
    since: str = ""
    until: str = ""
    truncated: bool = False
    reason: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Normalise the sequence fields to tuples (defensive copies)."""
        if not isinstance(self.imported, tuple):
            object.__setattr__(self, "imported", tuple(self.imported))
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(self.notes))


__all__ = [
    "ChangeFeedResult",
    "ChangeImportOutcome",
    "ChangeImportStatus",
    "ExternalChange",
    "ImportVerdict",
]
