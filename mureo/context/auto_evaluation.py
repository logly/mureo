"""Close a past-due observation mureo can decide on its own (#758 phase 5).

An ``action_log`` entry with an ``observation_due`` stays open until somebody
appends an ``evaluation_of`` record for it. ``mureo_outcome_evaluate`` is pure
and writes nothing, so that somebody is the agent — and when it forgets, the
entry is re-evaluated on every run and the pending set grows without bound.

For the common case the answer is already in STATE.json. A campaign-level
action that recorded ``metrics_at_action``, on a platform whose campaign
metrics have been collected since the window closed, has a **determined**
outcome: the same ``evaluate_outcome`` the agent would call, over two maps
mureo already holds. So mureo closes it itself, on the next
``mureo_state_get``.

What it will NOT decide
-----------------------
Every rule below exists because the alternative is a confident verdict on
the wrong numbers, and a wrong verdict in the audit trail is worse than an
open observation:

- an **external** change is not mureo's to evaluate (mureo did not make it,
  did not record the prior value, and its baseline is not mureo's baseline);
- no baseline, no campaign id, or a campaign/platform that is not in the
  document, means there is nothing to compare;
- current metrics whose ``fetched_at`` is missing, unreadable, or EARLIER
  than the due date would score the wrong period. There is deliberately no
  fallback to ``platform.last_synced_at``: a platform-level sync stamp says
  nothing about when this campaign's figures were read;
- a baseline and a snapshot that state DIFFERENT ``period`` windows are not
  a before and an after of the same thing — every volume metric would move
  simply because the window changed.

``fetched_at`` is taken as the collector wrote it: mureo cannot verify when
a platform's figures were actually read, so a collector that stamps a wrong
date produces a wrong closure. That is the trust the dashboard already
places in the same snapshot.

Each refusal is reported as a skip with a reason from a fixed vocabulary, so
the agent knows exactly which entries it still owes a manual evaluation —
and so the reason an operator reads is the same string every time.

Pure decision plus ONE locked write. Nothing here imports the MCP layer; the
handler hook (:mod:`mureo.mcp._auto_evaluation_hook`) supplies "today" and
the write permission, exactly as the skills supply ``server_now``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final

from mureo.analysis.outcome_eval import evaluate_outcome
from mureo.context.actor_stamp import stamp_actor
from mureo.context.models import ActionLogEntry
from mureo.context.observations import closed_observation_indices, parse_due_date

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from pathlib import Path

    from mureo.analysis.outcome_eval import OutcomeReport
    from mureo.context.models import StateDocument

#: The ``action`` of the entry an automatic closure appends. One string, so a
#: reader can tell mureo's own closure from an agent-written evaluation record
#: without parsing prose.
AUTO_EVALUATION_ACTION: Final = "outcome_evaluated"

#: Keys a collector stores alongside the figures that are not figures. They
#: are dropped from both maps for the SCORING call only — the closure entry
#: records the snapshot whole, because a stored verdict that does not say
#: which window and which collection produced it cannot be checked.
BOOKKEEPING_METRIC_KEYS: Final[tuple[str, ...]] = (
    "period",
    "fetched_at",
    "result_indicator",
)

SKIP_EXTERNAL_ORIGIN: Final = "external_origin"
SKIP_NO_BASELINE: Final = "no_baseline"
SKIP_NO_CAMPAIGN_ID: Final = "no_campaign_id"
SKIP_PLATFORM_NOT_IN_STATE: Final = "platform_not_in_state"
SKIP_CAMPAIGN_NOT_IN_STATE: Final = "campaign_not_in_state"
SKIP_NO_CURRENT_METRICS: Final = "no_current_metrics"
SKIP_UNPARSEABLE_DUE_DATE: Final = "unparseable_due_date"
SKIP_CURRENT_METRICS_UNDATED: Final = "current_metrics_undated"
SKIP_CURRENT_METRICS_PREDATE_WINDOW: Final = "current_metrics_predate_window"
SKIP_PERIOD_MISMATCH: Final = "period_mismatch"
SKIP_NO_COMPARABLE_METRIC: Final = "no_comparable_metric"

#: Prefix of the skip reported when the host refuses the write. The denial
#: text follows it verbatim, so an operator reading "why was nothing closed?"
#: gets the gate's own sentence rather than mureo's paraphrase.
WRITE_DENIED_PREFIX: Final = "write_denied: "

#: The closed vocabulary, in the order the rules are applied. Exported so the
#: docs and the tests name the same strings this module does.
SKIP_REASONS: Final[tuple[str, ...]] = (
    SKIP_EXTERNAL_ORIGIN,
    SKIP_NO_BASELINE,
    SKIP_NO_CAMPAIGN_ID,
    SKIP_PLATFORM_NOT_IN_STATE,
    SKIP_CAMPAIGN_NOT_IN_STATE,
    SKIP_NO_CURRENT_METRICS,
    SKIP_UNPARSEABLE_DUE_DATE,
    SKIP_CURRENT_METRICS_UNDATED,
    SKIP_CURRENT_METRICS_PREDATE_WINDOW,
    SKIP_PERIOD_MISMATCH,
    SKIP_NO_COMPARABLE_METRIC,
)


@dataclass(frozen=True)
class AutoClosure:
    """One observation mureo closed, and the record it appended for it."""

    index: int
    evaluation_index: int
    overall: str
    summary: str


@dataclass(frozen=True)
class AutoSkip:
    """One due observation mureo would not decide, and why."""

    index: int
    reason: str


@dataclass(frozen=True)
class ClosurePlan:
    """A closure that has been decided but not yet written.

    Separate from :class:`AutoClosure` because the position the record will
    occupy is not known until the append happens, inside the lock.
    """

    index: int
    entry: ActionLogEntry
    overall: str
    summary: str


@dataclass(frozen=True)
class AutoEvaluationResult:
    """What one pass over the due observations did."""

    closed: tuple[AutoClosure, ...]
    skipped: tuple[AutoSkip, ...]


def due_candidates(doc: StateDocument, today: date) -> list[int]:
    """Indices of the OPEN observations whose window has closed, in order.

    Same two questions :mod:`mureo.context.observations` answers for the
    pending filter and the Reports triage — not closed by a later
    ``rollback_of`` / ``evaluation_of``, and due on or before ``today`` — so
    an entry mureo closes here is exactly one the daily-check would have
    been shown.
    """
    closed = closed_observation_indices(doc.action_log)
    candidates: list[int] = []
    for index, entry in enumerate(doc.action_log):
        if index in closed:
            continue
        due = parse_due_date(entry.observation_due)
        if due is not None and due <= today:
            candidates.append(index)
    return candidates


def _baseline_skip(entry: ActionLogEntry) -> str | None:
    """The refusals that need only the entry itself, in rule order."""
    if entry.origin is not None:
        return SKIP_EXTERNAL_ORIGIN
    if not entry.metrics_at_action:
        return SKIP_NO_BASELINE
    if not entry.campaign_id:
        return SKIP_NO_CAMPAIGN_ID
    return None


def _scored_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """``metrics`` without the keys that are bookkeeping, not figures."""
    return {k: v for k, v in metrics.items() if k not in BOOKKEEPING_METRIC_KEYS}


def _period_label(value: Any) -> str | None:
    """A ``metrics`` window token, normalised, or ``None`` when unstated."""
    if not isinstance(value, str):
        return None
    return value.strip().upper() or None


def _period_mismatch(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Do the two snapshots state DIFFERENT windows?

    Only when both state one. "Unstated" is not "mismatched": most baselines
    carry no ``period`` at all, and refusing those would leave every one of
    them open forever — while the manual path an agent would fall back to has
    exactly the same limit, since it too compares whatever two maps it is
    handed. What this rule catches is the case mureo can actually see: a
    7-day baseline scored against a 30-day snapshot, which reads as a real
    movement in every volume metric and is nothing but the window changing.
    """
    stated_before = _period_label(before.get("period"))
    stated_after = _period_label(after.get("period"))
    if stated_before is None or stated_after is None:
        return False
    return stated_before != stated_after


def _comparable_metrics(
    doc: StateDocument, entry: ActionLogEntry
) -> dict[str, Any] | str:
    """The current campaign snapshot's metrics to score against, or a skip.

    Returned WHOLE, bookkeeping keys included — the caller strips them for
    the scoring call and keeps them on the record, where they are what makes
    a stored verdict diagnosable months later.

    The freshness rule is the load-bearing one: the snapshot must say WHEN it
    was collected (``fetched_at``), and that date must be on or after the
    observation's due date. Anything else scores a period that overlaps the
    window rather than follows it.
    """
    platform = (doc.platforms or {}).get(entry.platform)
    if platform is None:
        return SKIP_PLATFORM_NOT_IN_STATE
    snapshot = next(
        (c for c in platform.campaigns if c.campaign_id == entry.campaign_id), None
    )
    if snapshot is None:
        return SKIP_CAMPAIGN_NOT_IN_STATE
    metrics = snapshot.metrics or {}
    if not metrics:
        return SKIP_NO_CURRENT_METRICS
    due = parse_due_date(entry.observation_due)
    if due is None:
        return SKIP_UNPARSEABLE_DUE_DATE
    fetched = parse_due_date(metrics.get("fetched_at"))
    if fetched is None:
        return SKIP_CURRENT_METRICS_UNDATED
    if fetched < due:
        return SKIP_CURRENT_METRICS_PREDATE_WINDOW
    if _period_mismatch(entry.metrics_at_action or {}, metrics):
        return SKIP_PERIOD_MISMATCH
    return dict(metrics)


def _closure_entry(
    entry: ActionLogEntry, index: int, report: OutcomeReport, after: dict[str, Any]
) -> ActionLogEntry:
    """Build the ``evaluation_of`` record for a decided closure.

    ``after`` is the WHOLE snapshot, ``period`` and ``fetched_at`` included:
    the record has to say which days it scored, or a reader coming back to it
    cannot check the verdict against anything.

    ``batch_id`` stays ``None`` and the entry is written outside
    ``append_action_log``'s batch stamping: an automatic record joining
    whatever batch happens to be open would grow that change set with
    something nobody dispatched.

    The rationale is the one place in mureo where an over-long reason is
    SLICED rather than refused. It is machine-built from a bounded verdict
    and a generated summary, so there is no caller holding a sentence it
    could shorten — and dropping the record to protect a cap would leave the
    observation open forever, which is the bug this feature closes. It is
    scrubbed all the same: it is built from metric names a writer supplied,
    and every other ``reason`` that reaches STATE.json crosses this boundary
    (:func:`mureo.core.actor.normalize_reason`), so this one does too.
    """
    # Lazy, for the cycle ``mureo.context.state`` documents: importing
    # anything from ``mureo.core`` at module level runs its ``__init__``,
    # which reaches back into this package through ``state_store``.
    from mureo.core.actor import ACTION_REASON_MAX_CHARS
    from mureo.core.clock import server_now_iso
    from mureo.core.scrub import scrub_text

    reason = scrub_text(
        f"Automatic observation closure ({report.overall.value}): {report.summary}"
    )
    return ActionLogEntry(
        timestamp=server_now_iso(),
        action=AUTO_EVALUATION_ACTION,
        platform=entry.platform,
        campaign_id=entry.campaign_id,
        ad_id=entry.ad_id,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        summary=report.summary,
        metrics_at_action=dict(after),
        evaluation_of=index,
        reason=reason[:ACTION_REASON_MAX_CHARS],
    )


def plan_closure(doc: StateDocument, index: int, today: date) -> ClosurePlan | AutoSkip:
    """Decide what to do with the due observation at ``index``.

    The rules run in the order they are listed in :data:`SKIP_REASONS` and
    the FIRST failing one wins, so an entry that offends several (external
    AND baseline-less, say) always reports the same reason.

    ``today`` is accepted so a plan is a function of the same
    ``(doc, index, today)`` triple that selected the candidate; the freshness
    rule itself anchors on the entry's ``observation_due``, never on today —
    a window that closed a fortnight ago is still the period to score.
    """
    entry = doc.action_log[index]
    refusal = _baseline_skip(entry)
    if refusal is not None:
        return AutoSkip(index=index, reason=refusal)
    after = _comparable_metrics(doc, entry)
    if isinstance(after, str):
        return AutoSkip(index=index, reason=after)
    # Stripped for the SCORING only. The record keeps the whole snapshot.
    report = evaluate_outcome(
        before=_scored_metrics(entry.metrics_at_action or {}),
        after=_scored_metrics(after),
    )
    # No scored metric at all — the baseline and the current snapshot share no
    # numeric key. ``Verdict`` has no "unknown" member: INCONCLUSIVE is a real
    # verdict ("moved less than the noise band") and is closed like any other.
    if not report.metrics:
        return AutoSkip(index=index, reason=SKIP_NO_COMPARABLE_METRIC)
    return ClosurePlan(
        index=index,
        entry=_closure_entry(entry, index, report, after),
        overall=report.overall.value,
        summary=report.summary,
    )


def _plan_due(doc: StateDocument, today: date) -> list[ClosurePlan | AutoSkip]:
    """Plan every due candidate in ``doc``, in document order."""
    return [plan_closure(doc, index, today) for index in due_candidates(doc, today)]


class _NothingToCloseError(Exception):
    """Raised inside the locked build when the re-plan closes nothing.

    Private, and never seen by a caller. It exists to leave the ``file_lock``
    block BEFORE ``write_state_file`` runs: two readers can both pass the
    un-locked pre-check, and the loser must not rewrite an identical document
    — a superfluous write bumps the mtime of a file whose freshness other
    surfaces read, on a call the operator issued as a READ.
    """


def _write_closures(
    path: Path, today: date
) -> tuple[list[AutoClosure], list[AutoSkip]]:
    """Re-plan under the state lock and append every closure in ONE write.

    The candidates are recomputed against the LOCKED document rather than
    reusing the plans made outside it: two ``mureo_state_get`` calls racing
    each other must not both close the same index, and inside the lock the
    second one sees the first one's record and finds nothing due — in which
    case nothing is written at all (see :class:`_NothingToCloseError`).
    """
    from mureo.context.state import _locked_state_mutation

    closed: list[AutoClosure] = []
    skipped: list[AutoSkip] = []

    def _build(doc: StateDocument) -> StateDocument:
        closed.clear()
        skipped.clear()
        entries = list(doc.action_log)
        for plan in _plan_due(doc, today):
            if isinstance(plan, AutoSkip):
                skipped.append(plan)
                continue
            closed.append(
                AutoClosure(
                    index=plan.index,
                    evaluation_index=len(entries),
                    overall=plan.overall,
                    summary=plan.summary,
                )
            )
            entries.append(stamp_actor(plan.entry, plan.entry.reason))
        if not closed:
            # Another writer got here first. Leave the lock without writing.
            raise _NothingToCloseError
        # ``last_synced_at`` is deliberately not re-stamped, for the reason
        # ``append_action_log`` gives: appending an action is not a sync.
        return replace(doc, action_log=tuple(entries))

    try:
        _locked_state_mutation(path, _build)
    except _NothingToCloseError:
        return [], skipped
    return closed, skipped


def close_due_observations(
    path: Path, *, today: date, may_write: Callable[[], str | None]
) -> AutoEvaluationResult:
    """Close every past-due observation whose outcome is determined.

    Args:
        path: STATE.json location.
        today: The server's date. Passed in, never read from a clock here —
            the same discipline every other date-sensitive rule in this
            package follows.
        may_write: Consulted ONCE, before the lock, and only when there is
            something to close. A denial reason means the host forbids the
            ``action_log`` append (a read-only deployment's policy gate);
            nothing is written and every candidate is reported as skipped
            with that reason. This is what keeps the feature inside the
            host's guardrails instead of around them.

    Returns:
        What was closed and what was not. Both may be empty: an untouched
        document is the normal answer.

    Raises:
        Exception: whatever the read, the scoring or the write raised. The
            caller decides — the MCP hook degrades to an error field rather
            than failing the read it is attached to.
    """
    from mureo.context.state import read_state_file

    plans = _plan_due(read_state_file(path), today)
    if not plans:
        return AutoEvaluationResult(closed=(), skipped=())
    denial = may_write()
    if denial is not None:
        reason = f"{WRITE_DENIED_PREFIX}{denial}"
        denied = tuple(AutoSkip(index=p.index, reason=reason) for p in plans)
        return AutoEvaluationResult(closed=(), skipped=denied)
    skips = tuple(p for p in plans if isinstance(p, AutoSkip))
    if len(skips) == len(plans):
        # Nothing to append. Taking the lock to rewrite an identical document
        # would churn STATE.json on every read for as long as an unclosable
        # candidate sits in the log.
        return AutoEvaluationResult(closed=(), skipped=skips)
    closed, skipped = _write_closures(path, today)
    return AutoEvaluationResult(closed=tuple(closed), skipped=tuple(skipped))


__all__ = [
    "AUTO_EVALUATION_ACTION",
    "BOOKKEEPING_METRIC_KEYS",
    "SKIP_CAMPAIGN_NOT_IN_STATE",
    "SKIP_CURRENT_METRICS_PREDATE_WINDOW",
    "SKIP_CURRENT_METRICS_UNDATED",
    "SKIP_EXTERNAL_ORIGIN",
    "SKIP_NO_BASELINE",
    "SKIP_NO_CAMPAIGN_ID",
    "SKIP_NO_COMPARABLE_METRIC",
    "SKIP_NO_CURRENT_METRICS",
    "SKIP_PERIOD_MISMATCH",
    "SKIP_PLATFORM_NOT_IN_STATE",
    "SKIP_REASONS",
    "SKIP_UNPARSEABLE_DUE_DATE",
    "WRITE_DENIED_PREFIX",
    "AutoClosure",
    "AutoEvaluationResult",
    "AutoSkip",
    "ClosurePlan",
    "close_due_observations",
    "due_candidates",
    "plan_closure",
]
