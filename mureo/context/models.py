"""Data model definitions for file-based context."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mureo.context._preserve import copied_raw

# Re-exported: ``ActionLogEntry`` and ``EXTERNAL_ORIGIN`` live in their own
# module (size limit) and are still imported from here. A runtime import, not
# a TYPE_CHECKING one, because callers import them from this module.
from mureo.context.action_log_entry import (
    EXTERNAL_ORIGIN as EXTERNAL_ORIGIN,
)
from mureo.context.action_log_entry import (
    ActionLogEntry as ActionLogEntry,  # noqa: TC001
)

# Re-exported: the display contract models live in their own module (size
# limit) and are still imported from here. A runtime import, not a
# TYPE_CHECKING one, because callers import the classes from this module.
from mureo.context.display_models import (
    DisplayBreakdown as DisplayBreakdown,
)
from mureo.context.display_models import (
    DisplayBreakdownRow as DisplayBreakdownRow,
)
from mureo.context.display_models import (
    DisplayContract as DisplayContract,  # noqa: TC001
)
from mureo.context.display_models import (
    DisplayHighlight as DisplayHighlight,
)
from mureo.context.display_models import (
    DisplayProposal as DisplayProposal,
)
from mureo.context.display_models import (
    DisplayStatedValue as DisplayStatedValue,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mureo.context.decisions import DecisionRecord
    from mureo.context.settings import WorkspaceSettings

#: Longest ``reason`` mureo stores or renders in EITHER collection-failure
#: note — ``PlatformState.not_collected`` (#638) and
#: ``StateDocument.workspace_not_collected`` (#661). One bound, because the
#: two are the same shape shown in the same place.
#: A collector's raw error can be a page of API JSON, while the card that has
#: to show it has one line and STATE.json is read whole on every write. The
#: cap is applied at BOTH boundaries — the write helpers
#: (:func:`mureo.context.state.set_platform_not_collected` /
#: :func:`mureo.context.state.set_workspace_not_collected`) and the dashboard's
#: read (:func:`mureo.web.reports._platform_row` /
#: :func:`mureo.web.report_document._workspace_not_collected`) — because a document can
#: also be written wholesale by a digest that goes near neither.
NOT_COLLECTED_REASON_MAX_CHARS = 500

#: The shape of a ``PlatformState.daily`` key — one complete calendar day,
#: ``YYYY-MM-DD`` (#690). Written down once, because three surfaces have to
#: agree on it and a second copy is how they would drift: the writer refuses
#: anything else (:func:`mureo.context.state.set_platform_daily`), the MCP
#: tool states it as the ``propertyNames`` pattern of its ``days`` object
#: (date keys cannot be enumerated the way window tokens can), and the
#: dashboard uses it to decide which stored keys can be placed on a timeline
#: at all (:func:`mureo.web.report_document._daily_series`).
#:
#: A shape, not a vocabulary. It says nothing about whether the date exists
#: or is in the past — the writer parses it and checks both, because
#: ``2026-02-30`` matches this perfectly.
DAILY_DATE_KEY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


@dataclass(frozen=True)
class StrategyEntry:
    """Immutable data model representing a single section in STRATEGY.md."""

    context_type: str
    title: str
    content: str


@dataclass(frozen=True)
class AdState:
    """Ad-level (creative-level) delivery state under a campaign (#468).

    Platform-agnostic by design: ``status`` is what the ad is configured as
    and ``effective_status`` is whether it is actually delivering, which is
    the pair every platform expresses in some form (Meta
    ``status``/``effective_status``, Google Ads ``ad_group_ad.status`` plus
    its policy review status). Only ``ad_id`` is required — a platform that
    exposes no delivery status simply omits the field rather than having one
    invented for it.

    ``as_of`` is the ISO 8601 timestamp at which this status was observed,
    stamped SERVER-side by the MCP handler (the #460 pattern). It is what
    makes a stored status auditable: an agent comparing today's fetch against
    the stored one needs to know when the stored one was true, and a
    model-supplied date would reintroduce exactly the drift #460 fixed.

    ``raw`` is the ad's on-disk dict, kept only when the codec could not
    represent it fully (#881): ``ad_id`` absent, null or not a string (it
    then reads as ``""``), or a key the codec does not know. ``None`` on every
    ad mureo constructs. :func:`mureo.context.state_codec.render_state` uses
    it to write the ad back in its on-disk shape — see
    :mod:`mureo.context._platform_codec`.
    """

    ad_id: str
    name: str | None = None
    status: str | None = None
    effective_status: str | None = None
    as_of: str | None = None
    # Appended after every pre-#881 field, same positional-compatibility rule
    # as ``ActionLogEntry``.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Take a defensive copy of ``raw``."""
        object.__setattr__(self, "raw", copied_raw(self.raw))


@dataclass(frozen=True)
class CampaignSnapshot:
    """Campaign state snapshot.

    frozen=True prevents field reassignment, but dict/list contents are still mutable,
    so __post_init__ takes defensive copies.

    ``raw`` is what the codec needs of the campaign's on-disk dict to write
    it back — its key order and the values it cannot hold, the rest stored as
    placeholders — kept only when the codec could not represent it fully
    (#881): ``campaign_id`` / ``campaign_name`` /
    ``status`` absent, null or not a string (each then reads as ``""``), a key
    the codec does not know, or an ``ads`` / ``device_targeting`` value the
    model cannot hold (not a list, or ``ads`` holding a non-object). ``None``
    on every campaign mureo constructs. :func:`mureo.context.state_codec.
    render_state` uses it to write the campaign back in its on-disk shape —
    see :mod:`mureo.context._platform_codec`.
    """

    campaign_id: str
    campaign_name: str
    status: str
    bidding_strategy_type: str | None = None
    bidding_details: dict[str, Any] | None = None
    daily_budget: float | None = None
    # The campaign's own MONTHLY budget, where the platform has that concept
    # (#656) — a figure some platforms accept alongside the daily one. It sits
    # here, beside ``daily_budget``, because it is part of what the campaign is
    # configured with, and a campaign's configuration has one home.
    #
    # ``None`` is "this platform has no such field, or mureo has not read it",
    # which is why the platform-configured monthly total
    # (:func:`mureo.context.platform_monthly_budget.
    # platform_configured_monthly_budget`) is computed on READ and stored
    # nowhere: a cached sum is stale the moment one campaign's budget changes.
    # Whether an absent value is a gap is not decidable from this field alone —
    # only a platform that declared the concept can be missing one.
    #
    # Optional with a None default so old STATE.json files parse unchanged and
    # gain no new key on the next write.
    monthly_budget: float | None = None
    device_targeting: tuple[dict[str, Any], ...] | None = None
    campaign_goal: str | None = None
    notes: str | None = None
    # Optional performance metrics for the read-only reporting dashboard.
    # Validation stays loose (free-form dict); intended keys are:
    #   spend, impressions, clicks, conversions, cpa, ctr,
    #   result_indicator (Meta: whether "results" are clicks vs leads),
    #   period (e.g. "LAST_30_DAYS"), fetched_at (ISO 8601).
    # Optional with a None default so old STATE.json files parse unchanged.
    metrics: dict[str, Any] | None = None
    # Ad-level delivery state (#468). ``None`` means "never fetched" and is
    # deliberately distinct from ``()`` ("fetched, this campaign has no ads")
    # — the two lead to different advice, and only ``None`` should be silent.
    # Optional with a None default so old STATE.json files parse unchanged and
    # gain no new key on the next write.
    ads: tuple[AdState, ...] | None = None
    # Appended after every pre-#881 field, same positional-compatibility rule
    # as ``ActionLogEntry``.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Take defensive copies of mutable fields."""
        object.__setattr__(self, "raw", copied_raw(self.raw))
        if self.ads is not None and not isinstance(self.ads, tuple):
            object.__setattr__(self, "ads", tuple(self.ads))
        if self.bidding_details is not None:
            object.__setattr__(
                self, "bidding_details", copy.deepcopy(self.bidding_details)
            )
        if self.device_targeting is not None:
            # Convert lists to tuples and deepcopy contents
            copied = tuple(copy.deepcopy(item) for item in self.device_targeting)
            object.__setattr__(self, "device_targeting", copied)
        if self.metrics is not None:
            object.__setattr__(self, "metrics", copy.deepcopy(self.metrics))


@dataclass(frozen=True)
class BatchRecord:
    """One declared bulk change set (#549).

    A bulk change is normally many tool calls, and nothing in a single call
    tells mureo which other calls belong with it. So the boundary is
    **declared**: ``mureo_batch_begin`` opens a record, every ``action_log``
    write until ``mureo_batch_end`` is stamped with its ``batch_id``, and the
    rollback plan for that id covers exactly those entries.

    Stored in STATE.json rather than in process memory because the MCP server
    can be restarted by its host between two calls of the same operator
    session, and a batch that silently stopped collecting members is the
    failure mode this whole feature exists to prevent.

    The record outlives the batch: ``ended_at`` is set on close rather than the
    record being deleted, so ``label`` is still there weeks later when the
    operator asks what a batch id actually was. ``ended_at is None`` means the
    batch is open, and at most one record may be open at a time.

    Both timestamps are stamped SERVER-side (the #460 rule).
    """

    batch_id: str
    label: str
    started_at: str
    ended_at: str | None = None


@dataclass(frozen=True)
class PlatformState:
    """Per-platform state snapshot (Google Ads, Meta Ads, etc.).

    frozen=True prevents field reassignment; __post_init__ takes defensive
    copies of mutable inner contents.

    ``raw`` is what the codec needs of the entry's on-disk dict to write it
    back — its key order and the values it cannot hold, the rest stored as
    placeholders — kept only when the codec could not represent it fully
    (#881): ``account_id`` absent (it then reads as ``""``,
    i.e. unknown — see :mod:`mureo.context.platform_accounts`), a key the
    codec does not know, or a ``campaigns`` value the model cannot hold (not a
    list, or holding a non-object). ``None`` on every entry mureo constructs.
    :func:`mureo.context.state_codec.render_state` uses it to write the entry
    back in its on-disk shape — see :mod:`mureo.context._platform_codec`.
    """

    account_id: str
    campaigns: tuple[CampaignSnapshot, ...] = field(default_factory=tuple)
    # Optional platform-level metric rollup (e.g. {"spend": ..., "clicks": ...})
    # and the period those totals cover (e.g. "LAST_30_DAYS"). Both default to
    # None so legacy platform entries parse unchanged and emit no extra keys.
    # ``totals`` / ``metrics_period`` carry a SINGLE rollup (the most recent
    # window a sync wrote); ``periods`` carries one rollup PER window so the
    # dashboard can offer a period toggle.
    totals: dict[str, Any] | None = None
    metrics_period: str | None = None
    # Optional per-period rollups keyed by canonical period token
    # ({"YESTERDAY": {<totals>}, "LAST_30_DAYS": {<totals>}}). Each value is a
    # totals-shaped dict (same canonical keys as ``totals``). None by default so
    # legacy entries parse unchanged and emit no extra key. sync-state writes
    # LAST_30_DAYS; daily-check writes YESTERDAY.
    periods: dict[str, dict[str, Any]] | None = None
    # Optional day-grain history keyed by calendar date (#690):
    # ``{"2026-08-20": {<totals>}, "2026-08-19": {<totals>}}``. Same shape and
    # merge rules as ``periods``, with :data:`DAILY_DATE_KEY_PATTERN` keys
    # instead of window tokens, and None by default so legacy entries parse
    # unchanged and emit no extra key.
    #
    # ``periods`` holds ONE rollup per window and every collection overwrites
    # it, so the value it replaces is gone — nothing could answer "was
    # yesterday better than the day before?". This map is what accumulates,
    # and the day-grain rows every platform family already fetches are what
    # fills it.
    #
    # **A missing day stays missing.** Nothing zero-fills a day that was not
    # collected: "not collected" and "collected, and the answer was zero" are
    # different facts (the same distinction ``not_collected`` exists for), so
    # readers render a gap as a gap rather than as a day of no spend.
    daily: dict[str, dict[str, Any]] | None = None
    # Optional operator-declared conversion ``action_type`` allow-list (#342).
    # When set (non-None), the Meta conversion counters treat EXACTLY these
    # action_types as this account's conversions — overriding the default
    # deduped generic set — so a custom-event advertiser
    # (``offsite_conversion.custom.<id>``) or a component-only account is
    # counted correctly. None (the default) keeps the built-in generic set, so
    # legacy entries parse unchanged and emit no extra key.
    conversion_action_types: tuple[str, ...] | None = None
    # Why this platform's figures were NOT refreshed by the last collection
    # (#638), as ``{"attempted_at": <ISO 8601>, "reason": <human-readable>}``.
    # None (the default) is what every entry written before this field existed
    # carries, so legacy entries parse unchanged and emit no extra key.
    #
    # A note about the COLLECTION, never a verdict on the figures. The numbers
    # in ``totals`` / ``periods`` are still the last ones that were truly
    # collected: they are not wrong, they are older than they should be. A
    # surface that renders this as "these figures are wrong" says something
    # mureo did not.
    #
    # It exists because "not collected" and "collected, and the answer was
    # zero" were the same document. ``merge_metrics_into_state`` leaves an
    # uncollected platform entirely alone — correct, since writing 0 for a
    # timed-out request would be a lie — so an operator seeing figures that
    # had not moved for eleven days had no way to tell a stopped account from
    # a stopped collector, and left it alone.
    #
    # **Whoever collects clears it.** A successful collection MUST clear this
    # note in the same pass, by calling
    # :func:`mureo.context.state.set_platform_not_collected` with
    # ``reason=None``. mureo does not clear it as a side effect of any other
    # write: every targeted mutator here treats an omitted field as "leave it
    # alone", and a platform-level note cannot be inferred from one window's
    # rollup landing. A note that outlived its failure would be the very
    # defect this field is here to remove — permanently stale information,
    # stated with confidence.
    #
    # That contract is a duty, not a guarantee, so nothing an operator SEES
    # is allowed to depend on it: the read side drops a note that any later
    # collection has already answered (:func:`mureo.web.report_document.
    # _platform_not_collected`). A document holding a fresh ``fetched_at``
    # and an older failure states two contradictory answers to one question;
    # the contract stops that being written, and the read rule stops it being
    # shown when the contract was not honoured.
    not_collected: dict[str, Any] | None = None
    # Appended after every pre-#881 field, same positional-compatibility rule
    # as ``ActionLogEntry``.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Ensure campaigns is a tuple (defensive copy)."""
        object.__setattr__(self, "raw", copied_raw(self.raw))
        if not isinstance(self.campaigns, tuple):
            object.__setattr__(self, "campaigns", tuple(self.campaigns))
        if self.totals is not None:
            object.__setattr__(self, "totals", copy.deepcopy(self.totals))
        if self.periods is not None:
            object.__setattr__(self, "periods", copy.deepcopy(self.periods))
        if self.daily is not None:
            object.__setattr__(self, "daily", copy.deepcopy(self.daily))
        if self.not_collected is not None:
            object.__setattr__(self, "not_collected", copy.deepcopy(self.not_collected))
        if self.conversion_action_types is not None and not isinstance(
            self.conversion_action_types, tuple
        ):
            # A bare str must NOT be char-split into a tuple of letters; wrap
            # it as a single action_type. Other iterables tuple-ify normally.
            normalized = (
                (self.conversion_action_types,)
                if isinstance(self.conversion_action_types, str)
                else tuple(self.conversion_action_types)
            )
            object.__setattr__(self, "conversion_action_types", normalized)


@dataclass(frozen=True)
class StateDocument:
    """Root document of STATE.json."""

    version: str = "1"
    last_synced_at: str | None = None
    customer_id: str | None = None  # Kept for backward compatibility (v1)
    campaigns: tuple[CampaignSnapshot, ...] = field(
        default_factory=tuple
    )  # Kept for v1
    platforms: dict[str, PlatformState] | None = None  # v2: per-platform state
    action_log: tuple[ActionLogEntry, ...] = field(
        default_factory=tuple
    )  # v2: action log
    # Stage-c analysis summaries, keyed by report kind
    # (mureo.core.report_kinds.REPORT_KINDS — one kind per skill that writes
    # a report). Round-tripped as found: a key outside the vocabulary is
    # preserved rather than dropped. Optional with a None default so old
    # STATE.json files parse unchanged and emit no extra key.
    reports: dict[str, Any] | None = None
    # Why THIS WORKSPACE could not be collected at all (#661), as
    # ``{"attempted_at": <ISO 8601>, "reason": <human-readable>}`` — the same
    # two fields as ``PlatformState.not_collected``, one level up. None (the
    # default) is what every document written before this field existed
    # carries, so a legacy STATE.json parses unchanged and emits no new key.
    #
    # The document-level counterpart exists because the per-platform field
    # cannot carry a failure that happened BEFORE any platform was reached:
    # ``set_platform_not_collected`` requires a platform key and an
    # ``account_id``, and those are exactly what the dead process would have
    # resolved. Writing the note onto every existing entry would say
    # something else ("Meta failed, and Google failed, and…"), and a
    # workspace that has never been collected — the case where the record
    # matters most — has no entry to write onto at all.
    #
    # It is NOT a per-platform note repeated, and must never be rendered as
    # one: "this workspace could not be collected" and "this workspace's Meta
    # failed" call for different actions. The two are separate fields, set by
    # separate writers, and retired on separate evidence.
    #
    # Retirement follows #638's rule one level up: the read side
    # (:func:`mureo.web.report_document._workspace_not_collected`) drops the note once
    # ANY rollup anywhere in the document carries a ``fetched_at`` later than
    # ``attempted_at`` — a collection that succeeded after the failure has
    # already answered it. Clearing it is still the collector's duty
    # (:func:`mureo.context.state.set_workspace_not_collected` with
    # ``reason=None``), but nothing an operator SEES depends on that duty
    # being honoured.
    workspace_not_collected: dict[str, Any] | None = None
    # Declared bulk change sets (#549), open and closed. Empty by default and
    # emitted only when non-empty, so a STATE.json written before this field
    # existed parses unchanged and gains no new key.
    batches: tuple[BatchRecord, ...] = field(default_factory=tuple)
    # What the DASHBOARD reads for this client (#706) — see
    # :class:`DisplayContract`. ``None`` (the default) is what every document
    # written before this section existed carries, so a legacy STATE.json
    # parses unchanged and emits no new key.
    #
    # A section of its own, beside ``reports`` rather than inside one, because
    # it answers a different question. ``reports`` holds one stage-c analysis
    # summary PER KIND, written for whoever reads that report; this is the
    # whole client's screen as of one moment, and it is written under bounds
    # that refuse prose. Folding it into a report kind would make the
    # dashboard pick a kind to render, which is the "latest report wins"
    # problem one level up — and would put a guarded surface inside an
    # unguarded one.
    display: DisplayContract | None = None
    # The reasoning trail (#758 phase 3) — see
    # :class:`mureo.context.decisions.DecisionRecord`. Append-only like
    # ``action_log``, and separate from ``display.proposals`` because that
    # section is REPLACED WHOLE on every write and so cannot be a history.
    # Empty by default and emitted only when non-empty, so a STATE.json
    # written before this section existed parses unchanged and gains no key.
    decisions: tuple[DecisionRecord, ...] = field(default_factory=tuple)
    # #848, see :mod:`mureo.context.settings`; ``None`` reads as the defaults.
    settings: WorkspaceSettings | None = None
    # The on-disk value of each top-level section the model cannot hold,
    # keyed by section name (#882). This is the one place its shape is
    # defined:
    #
    # - ``{"campaigns": <value>}`` — a top-level ``campaigns`` that is not a
    #   list of objects (``campaigns`` then reads as ``()`` in the writers'
    #   strict parse; the read-only parse still reads the object entries of
    #   a list);
    # - ``{"platforms": <value>}`` — a ``platforms`` that is not an object
    #   (``platforms`` then reads as ``None``); ``<value>`` is never a dict;
    # - ``{"platforms": {"<key>": <value>, ...}}`` — the whole ``platforms``
    #   object as found, when one or more of its values is not an object;
    #   each such value is omitted from ``platforms``, and the whole object
    #   is kept so it is written back at its original position. Told apart
    #   from the line above by being a dict;
    # - ``{"decisions": <value>}`` — a ``decisions`` that is not a list
    #   (``decisions`` then reads as ``()``);
    # - ``{"action_log": <value>}`` — an ``action_log`` that is not a list
    #   and not ``null`` (``action_log`` then reads as ``()``; ``null`` reads
    #   as empty and is not kept, like a ``null`` ``decisions``).
    #
    # :func:`mureo.context.state_codec.render_state` writes a kept section
    # back verbatim while the model's section is still what the parser left
    # (``()`` / ``None``) and drops a kept ``campaigns`` / ``platforms`` once
    # a writer has filled that section; a kept platform value is merged back
    # under its key, at its original position, unless ``platforms`` now
    # holds that key. A kept ``decisions`` / ``action_log`` is history and is
    # never replaced: no writer records into it, and
    # ``render_state`` refuses a document holding both a kept value and new
    # records. A read-only (``strict=False``) parse is never written back.
    # ``None`` on every document mureo constructs. Appended after every
    # pre-#882 field, same positional-compatibility rule as
    # ``ActionLogEntry``.
    raw: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Defensive copies for mutable fields."""
        object.__setattr__(self, "raw", copied_raw(self.raw))
        if self.platforms is not None:
            object.__setattr__(self, "platforms", dict(self.platforms))
        if not isinstance(self.action_log, tuple):
            object.__setattr__(self, "action_log", tuple(self.action_log))
        if not isinstance(self.batches, tuple):
            object.__setattr__(self, "batches", tuple(self.batches))
        if not isinstance(self.decisions, tuple):
            object.__setattr__(self, "decisions", tuple(self.decisions))
        if self.reports is not None:
            object.__setattr__(self, "reports", copy.deepcopy(self.reports))
        if self.workspace_not_collected is not None:
            object.__setattr__(
                self,
                "workspace_not_collected",
                copy.deepcopy(self.workspace_not_collected),
            )
