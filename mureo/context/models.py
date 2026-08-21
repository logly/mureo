"""Data model definitions for file-based context."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

#: ``ActionLogEntry.origin`` value for a change mureo OBSERVED rather than
#: performed (#545). ``origin is None`` — every entry written before this
#: field existed, and every entry mureo writes for its own dispatch — means
#: mureo-originated. The two must never collapse into one another: mureo can
#: vouch for the arguments of its own change and can often reverse it, and can
#: do neither for a change made in a platform's UI.
EXTERNAL_ORIGIN = "external"

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
#: :func:`mureo.web.reports._workspace_not_collected`) — because a document can
#: also be written wholesale by a digest that goes near neither.
NOT_COLLECTED_REASON_MAX_CHARS = 500


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
    """

    ad_id: str
    name: str | None = None
    status: str | None = None
    effective_status: str | None = None
    as_of: str | None = None


@dataclass(frozen=True)
class CampaignSnapshot:
    """Campaign state snapshot.

    frozen=True prevents field reassignment, but dict/list contents are still mutable,
    so __post_init__ takes defensive copies.
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

    def __post_init__(self) -> None:
        """Take defensive copies of mutable fields."""
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
class ActionLogEntry:
    """Immutable record of a single action performed on a campaign.

    metrics_at_action: Key metrics at the time of action (e.g., {"cpa": 5200, "conversions": 45}).
        Used by the agent to evaluate the outcome of the action after the observation window.
    observation_due: ISO 8601 date when the agent should evaluate the outcome (e.g., "2026-04-15").
        Typical windows: budget changes 7 days, keyword/creative changes 14 days.
    reversible_params: Structured hint describing how to reverse this action. Shape:
        ``{"operation": "<tool_name>", "params": {...}, "caveats": [...]}``.
        Agents set this when making reversible changes (budget update, status toggle,
        etc.) so ``mureo.rollback.plan_rollback()`` can build a concrete reversal plan.
        ``None`` means the action was not marked reversible (read-only query, create,
        delete, or simply not annotated). The ``operation`` value must be in the
        rollback planner's allow-list (see ``mureo.rollback.planner._ALLOWED_OPERATIONS``);
        values outside it — including destructive verbs like ``.delete`` — are refused
        so a prompt-injected or buggy agent cannot smuggle a privileged call through
        the rollback path.
    ad_id: The ad this action targeted, when it was ad-level (#468). Without it an
        ad-level pause could only be recorded as free text, so a later run could not
        match what mureo did against the ad statuses it observes — and would have to
        guess whether a stopped ad was its own doing or an operator's manual change.
    entity_type / entity_id: Generic sub-campaign identity for targets that are not
        ads, such as Google ad groups, Meta ad sets, or placements (#524). The pair
        lets a later run suppress a repeated recommendation for the same entity
        without suppressing unrelated changes across the whole campaign.
    evaluation_of: Positional index (into the full, append-only action_log) of the
        action whose ``observation_due`` this entry evaluates and closes. Same
        index semantics as ``rollback_of``: the log is append-only, so an entry's
        index never shifts. ``mureo_outcome_evaluate`` is pure and writes nothing,
        so without this marker a past-due observation would stay "pending" forever
        (re-evaluated every daily-check, the set growing unbounded). Appending an
        entry with ``evaluation_of=<index>`` records that the outcome was reviewed
        and takes the source out of the pending set. ``None`` means this entry is
        not an evaluation record.
    batch_id: The logical batch this action was dispatched as part of (#549), or
        ``None`` for a standalone action — which every entry written before this
        field existed is, so old STATE.json files parse unchanged and gain no new
        key on the next write. Membership is what makes "undo what I did on
        Monday" expressible: ``rollback_plan_get`` takes the id and reports the
        reversibility of EVERY member before anything is applied, so the operator
        never has to reconstruct a change set from memory. Stamped automatically
        by :func:`mureo.context.state.append_action_log` from the workspace's open
        batch, so a native, hosted-connector and bridged/plugin mutation all join
        the same unit without any per-platform code.
    origin: Who made this change (#545). ``None`` — the default, and what every
        entry written before this field existed carries — means mureo did:
        mureo dispatched it, a policy gate saw it, and its ``reversible_params``
        are mureo's own. :data:`EXTERNAL_ORIGIN` means mureo only OBSERVED it,
        having read it out of a platform's change feed after the fact. The
        distinction is load-bearing rather than cosmetic: mureo cannot vouch for
        an external change's arguments, did not record the prior value, and
        therefore refuses to plan a rollback for it (see
        :func:`mureo.rollback.planner.plan_rollback`). Collapsing the two would
        let mureo claim it can undo work it never did.
    external_id: The change feed's identity for an external change, namespaced by
        platform (``"google_ads|customers/…/changeEvents/…"``). It is what makes
        importing idempotent — the same change polled twice must not be recorded
        twice — so it is only meaningful together with ``origin``, and setting it
        without :data:`EXTERNAL_ORIGIN` is refused rather than ignored.
    occurred_at: When the PLATFORM says an external change happened, which is
        routinely hours or days before mureo saw it. ``timestamp`` stays what it
        has always been — when mureo wrote this entry, stamped server-side (#460)
        — so nothing here reintroduces a model-supplied "now"; ``occurred_at`` is
        history reported by the platform and must never be read as the current
        date. The observation window anchors on it, because a change that has
        been live for a week is already due for review, not due in a fortnight.
        ``None`` for a mureo-originated entry, where the two coincide.
    """

    timestamp: str
    action: str
    platform: str
    campaign_id: str | None = None
    ad_id: str | None = None
    summary: str | None = None
    command: str | None = None
    metrics_at_action: dict[str, Any] | None = None
    observation_due: str | None = None
    reversible_params: dict[str, Any] | None = None
    rollback_of: int | None = None
    evaluation_of: int | None = None
    # Appended after every pre-#524 field to preserve positional-constructor
    # compatibility for third-party callers of this public dataclass.
    entity_type: str | None = None
    entity_id: str | None = None
    # Appended after every pre-#549 field, same positional-compatibility rule.
    batch_id: str | None = None
    # Appended after every pre-#545 field, same positional-compatibility rule.
    origin: str | None = None
    external_id: str | None = None
    occurred_at: str | None = None

    def __post_init__(self) -> None:
        """Take defensive copies of mutable dict fields."""
        self._validate_origin()
        if self.batch_id is not None:
            if not isinstance(self.batch_id, str) or not self.batch_id.strip():
                raise ValueError("batch_id must be a non-empty string")
            object.__setattr__(self, "batch_id", self.batch_id.strip())
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together")
        if self.entity_type is not None and self.entity_id is not None:
            if not isinstance(self.entity_type, str) or not self.entity_type.strip():
                raise ValueError("entity_type must be a non-empty string")
            if not isinstance(self.entity_id, str) or not self.entity_id.strip():
                raise ValueError("entity_id must be a non-empty string")
            object.__setattr__(self, "entity_type", self.entity_type.strip())
            object.__setattr__(self, "entity_id", self.entity_id.strip())
        if self.metrics_at_action is not None:
            object.__setattr__(
                self, "metrics_at_action", copy.deepcopy(self.metrics_at_action)
            )
        if self.reversible_params is not None:
            object.__setattr__(
                self, "reversible_params", copy.deepcopy(self.reversible_params)
            )

    def _validate_origin(self) -> None:
        """Enforce the #545 provenance invariants.

        Three refusals, all of the same kind: a half-declared provenance is
        worse than none, because every downstream surface (rollback, dedup,
        daily-check) reads one of these fields and would draw a confident
        conclusion from a value the others contradict.
        """
        if self.origin is not None:
            if not isinstance(self.origin, str) or not self.origin.strip():
                raise ValueError("origin must be a non-empty string")
            object.__setattr__(self, "origin", self.origin.strip())
        if self.external_id is not None:
            if not isinstance(self.external_id, str) or not self.external_id.strip():
                raise ValueError("external_id must be a non-empty string")
            object.__setattr__(self, "external_id", self.external_id.strip())
            # An external_id on a mureo-originated entry has no meaning and
            # would poison dedup: the next import would treat mureo's own
            # action as a change it had already imported.
            if self.origin != EXTERNAL_ORIGIN:
                raise ValueError(
                    f"external_id requires origin={EXTERNAL_ORIGIN!r}; got "
                    f"origin={self.origin!r}"
                )
        if self.occurred_at is not None and (
            not isinstance(self.occurred_at, str) or not self.occurred_at.strip()
        ):
            raise ValueError("occurred_at must be a non-empty string")
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", self.occurred_at.strip())

    @property
    def is_external(self) -> bool:
        """Did mureo merely observe this change rather than perform it?

        A property, not a field: it derives from ``origin`` so the two can
        never disagree, and it keeps the dataclass field set — which IS the
        plugin ABI — unchanged by its addition.
        """
        return self.origin == EXTERNAL_ORIGIN


@dataclass(frozen=True)
class PlatformState:
    """Per-platform state snapshot (Google Ads, Meta Ads, etc.).

    frozen=True prevents field reassignment; __post_init__ takes defensive
    copies of mutable inner contents.
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
    # collection has already answered (:func:`mureo.web.reports.
    # _platform_not_collected`). A document holding a fresh ``fetched_at``
    # and an older failure states two contradictory answers to one question;
    # the contract stops that being written, and the read rule stops it being
    # shown when the contract was not honoured.
    not_collected: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Ensure campaigns is a tuple (defensive copy)."""
        if not isinstance(self.campaigns, tuple):
            object.__setattr__(self, "campaigns", tuple(self.campaigns))
        if self.totals is not None:
            object.__setattr__(self, "totals", copy.deepcopy(self.totals))
        if self.periods is not None:
            object.__setattr__(self, "periods", copy.deepcopy(self.periods))
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
    # (:func:`mureo.web.reports._workspace_not_collected`) drops the note once
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

    def __post_init__(self) -> None:
        """Defensive copies for mutable fields."""
        if self.platforms is not None:
            object.__setattr__(self, "platforms", dict(self.platforms))
        if not isinstance(self.action_log, tuple):
            object.__setattr__(self, "action_log", tuple(self.action_log))
        if not isinstance(self.batches, tuple):
            object.__setattr__(self, "batches", tuple(self.batches))
        if self.reports is not None:
            object.__setattr__(self, "reports", copy.deepcopy(self.reports))
        if self.workspace_not_collected is not None:
            object.__setattr__(
                self,
                "workspace_not_collected",
                copy.deepcopy(self.workspace_not_collected),
            )
