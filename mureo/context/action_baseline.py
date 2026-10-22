"""Fill an action's baseline from the campaign snapshot STATE.json holds (#890).

The automatic observation closure (:mod:`mureo.context.auto_evaluation`)
scores an ``action_log`` entry's ``metrics_at_action`` against the campaign's
snapshot once the window has closed. That baseline used to exist only when
the agent remembered to pass it, and when it did, it usually carried no
``period`` — so the closure skipped the entry with ``no_baseline``, or could
not compare a count per day.

The campaign's snapshot already holds the answer: its ``metrics`` are the
figures the agent would have copied, with the ``period`` they cover and the
``fetched_at`` they were read at. So when a campaign-level entry mureo made
is appended without a baseline, the snapshot is copied in WHOLE, plus the
day count the evaluator reads (``days``). The closure then scores it like
any baseline a caller passed — nothing downstream can tell the two apart.

What it will NOT fill
---------------------
- an entry whose caller passed a baseline: that value is kept as given,
  never merged — a skill may pass figures the snapshot does not hold
  (month-to-date spend, a segment's numbers);
- an entry with no ``campaign_id``, an external change (``origin`` set —
  mureo's baseline is not the one in place when somebody else changed the
  account, the rule :mod:`mureo.context.auto_evaluation` follows) and an
  evaluation record (``evaluation_of``), which closes an observation rather
  than opening one;
- a snapshot that is missing, has no metrics, does not say when it was
  read, or was read more than :data:`BASELINE_MAX_AGE_DAYS` days ago
  (or is dated more than :data:`BASELINE_MAX_LEAD_DAYS` ahead). A
  partial or stale baseline would be scored as if it were the state at the
  time of the change; no baseline leaves the entry to a manual evaluation,
  which is the honest answer.

The refusal reasons reuse the closure's vocabulary; :data:`BASELINE_STALE`
is the one word added. Pure: ``today`` is passed in, as everywhere else in
this package.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from mureo.analysis.outcome_eval import period_days
from mureo.context.auto_evaluation import (
    SKIP_CURRENT_METRICS_UNDATED,
    SKIP_NO_CURRENT_METRICS,
    entry_snapshot,
)
from mureo.context.observations import parse_due_date

if TYPE_CHECKING:
    from datetime import date

    from mureo.context.models import ActionLogEntry, StateDocument

#: How many days old a snapshot may be and still serve as a baseline.
#: Campaign metrics are collected once a day, so the newest snapshot on a
#: normal day was read today or covers through yesterday; two days allows
#: for a collection that ran late. Anything older describes the account as
#: it was before changes the snapshot never saw.
BASELINE_MAX_AGE_DAYS: Final = 2

#: How many days AHEAD of today a ``fetched_at`` may be: one is a collector
#: in a timezone ahead of the server; more is a mistyped date or a broken clock.
BASELINE_MAX_LEAD_DAYS: Final = 1

#: Why a baseline was not filled: the snapshot is outside the limits above.
BASELINE_STALE: Final = "baseline_stale"

#: Where an appended entry's baseline came from (the response's ``baseline``).
BASELINE_SOURCE_CALLER: Final = "caller"
BASELINE_SOURCE_STATE: Final = "state_snapshot"
BASELINE_SOURCE_NONE: Final = "none"


def _fillable(entry: ActionLogEntry) -> bool:
    """Is ``entry`` one whose missing baseline mureo fills?"""
    return (
        bool(entry.campaign_id) and entry.origin is None and entry.evaluation_of is None
    )


def baseline_from_state(
    doc: StateDocument, entry: ActionLogEntry, today: date
) -> dict[str, Any] | str:
    """The entry's campaign snapshot as a baseline, or why there is none.

    The snapshot's ``metrics`` are copied whole into a new dict — figures,
    ``period``, ``fetched_at``, ``result_indicator`` — and ``days`` is added
    when absent and :func:`~mureo.analysis.outcome_eval.period_days` can
    read it from ``period``. The snapshot itself is not modified.

    Returns:
        The baseline, or a reason code: ``platform_not_in_state`` /
        ``campaign_not_in_state`` (from
        :func:`~mureo.context.auto_evaluation.entry_snapshot`),
        ``no_current_metrics``, ``current_metrics_undated`` or
        :data:`BASELINE_STALE`.
    """
    snapshot = entry_snapshot(doc, entry)
    if isinstance(snapshot, str):
        return snapshot
    metrics = snapshot.metrics or {}
    if not metrics:
        return SKIP_NO_CURRENT_METRICS
    fetched = parse_due_date(metrics.get("fetched_at"))
    if fetched is None:
        return SKIP_CURRENT_METRICS_UNDATED
    # Local dates, as _auto_evaluation_hook; up to a day ahead is a timezone gap.
    age = (today - fetched).days
    if age > BASELINE_MAX_AGE_DAYS or -age > BASELINE_MAX_LEAD_DAYS:
        return BASELINE_STALE
    baseline = dict(metrics)
    days = period_days(metrics)
    if "days" not in baseline and days is not None:
        baseline["days"] = days
    return baseline


def with_baseline(
    doc: StateDocument, entry: ActionLogEntry, today: date
) -> tuple[ActionLogEntry, dict[str, str]]:
    """``entry`` with its baseline filled when it may be, and where it came from.

    The second value is the append response's ``baseline``:
    ``{"source": "caller" | "state_snapshot" | "none"}``, plus ``reason``
    when an entry that could have been filled was not. An entry out of scope
    (no campaign, external, an evaluation record) is ``none`` without a
    reason. ``entry`` is never modified; a filled entry is a new one.
    """
    if entry.metrics_at_action:
        return entry, {"source": BASELINE_SOURCE_CALLER}
    if not _fillable(entry):
        return entry, {"source": BASELINE_SOURCE_NONE}
    baseline = baseline_from_state(doc, entry, today)
    if isinstance(baseline, str):
        return entry, {"source": BASELINE_SOURCE_NONE, "reason": baseline}
    filled = replace(entry, metrics_at_action=baseline)
    return filled, {"source": BASELINE_SOURCE_STATE}


__all__ = [
    "BASELINE_MAX_AGE_DAYS",
    "BASELINE_MAX_LEAD_DAYS",
    "BASELINE_SOURCE_CALLER",
    "BASELINE_SOURCE_NONE",
    "BASELINE_SOURCE_STATE",
    "BASELINE_STALE",
    "baseline_from_state",
    "with_baseline",
]
