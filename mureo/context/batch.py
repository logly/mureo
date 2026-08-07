"""A bulk change as one named unit in ``action_log`` (#549).

The pure half of the batch feature: id minting, the stamping rule, and the
membership queries. The mutators that open and close a batch live in
:mod:`mureo.context.state` with the rest of STATE.json's targeted mutators —
they need its file lock, and putting them here would close an import cycle.

**Where the boundary comes from.** A bulk pass is many tool calls, and no
single call carries a signal about which other calls belong with it. Inferring
one (same minute, same campaign, same tool) would be a heuristic, and a
heuristic that silently omits a member re-creates the exact failure this module
exists to prevent — an operator reconstructing a change set from memory. So the
boundary is **declared**: ``mureo_batch_begin`` opens a batch, every
``action_log`` write until ``mureo_batch_end`` belongs to it.

**Why the stamp is applied at the append choke point.** Every platform mureo
drives — native Google/Meta, hosted connectors recorded through
``mureo_state_action_log_append``, and bridged / plugin tools promoted by
:func:`mureo.mcp.plugin_semantics.record_mutation_action_log` — reaches
``action_log`` through :func:`mureo.context.state.append_action_log`. Stamping
there is what makes batch membership platform-agnostic with no per-platform
code and no ABI change: a bridged tool's arguments belong to the bridged
platform, not to mureo, so threading a ``batch_id`` through tool schemas would
work for native tools only.

**Known limit.** The batch lifecycle tools resolve STATE.json through the
active :class:`StateStore` (via
:func:`mureo.mcp._helpers.resolve_workspace_path`), while the native and plugin
recorders write to ``Path.cwd() / "STATE.json"`` directly — a pre-existing
asymmetry, not one introduced here. They coincide in the default file-backed
configuration, which is every OSS install; under an alternate
``mureo.runtime_context_factory`` backend that points elsewhere, the two would
address different files and automatic membership would not apply. Anything
recorded through ``mureo_state_action_log_append`` uses the store path and is
unaffected.

Not to be confused with :class:`mureo.amazon_ads.batch.SessionBatch`, which is
a transport concern (one Amazon session for a sequence of calls) and has
nothing to do with ``action_log`` membership.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mureo.context.models import ActionLogEntry, BatchRecord, StateDocument


class BatchError(Exception):
    """A batch lifecycle call that cannot be honoured.

    Raised for opening a batch while one is already open, for closing one when
    none is, and for naming a batch that does not exist or has already closed.
    All are refused rather than resolved silently: flattening a nested begin
    would merge two change sets an operator meant to keep apart, a no-op end
    would report a batch that never collected anything, and an unchecked id
    would let membership be invented or grown after the fact.
    """


#: Number of random bytes in the id suffix. Ids are workspace-local names, not
#: secrets — this is collision avoidance across same-second batches, nothing
#: more.
_ID_ENTROPY_BYTES = 4

#: How long a batch may stay open before it is reported as stale. A bulk pass
#: is one working session; a batch still open a day later has almost certainly
#: been forgotten rather than deliberately kept. The threshold only controls
#: when mureo *says something* — nothing closes a batch automatically, because
#: an auto-close would trade a visible wrong answer for an invisible one: the
#: entries after it would silently stop joining and no one would be told.
STALE_AFTER_HOURS = 24


def new_batch_id(started_at: str = "") -> str:
    """Mint a batch id.

    Prefixed with the start timestamp's date-time when one is supplied, because
    an operator reads these ids in tool output and types them back into
    ``rollback_plan_get`` — ``batch-20260807T101500-1f4c9a02`` says which pass
    it was; a bare UUID does not. Uniqueness comes from the random suffix, not
    from the timestamp, so two batches opened in the same second are still
    distinct.
    """
    suffix = secrets.token_hex(_ID_ENTROPY_BYTES)
    stamp = "".join(ch for ch in started_at[:19] if ch.isdigit() or ch == "T")
    return f"batch-{stamp}-{suffix}" if stamp else f"batch-{suffix}"


def active_batch(doc: StateDocument) -> BatchRecord | None:
    """Return the workspace's open batch, or ``None``.

    "Open" is ``ended_at is None``. :func:`mureo.context.state.begin_batch`
    refuses to open a second one, so there is at most one; if a hand-edited
    file somehow holds several, the most recently declared wins — the same
    one a fresh ``begin_batch`` would have refused to displace.
    """
    for record in reversed(doc.batches):
        if record.ended_at is None:
            return record
    return None


def find_batch(doc: StateDocument, batch_id: str) -> BatchRecord | None:
    """Return the record for ``batch_id``, open or closed, or ``None``."""
    wanted = batch_id.strip()
    for record in doc.batches:
        if record.batch_id == wanted:
            return record
    return None


def ensure_joinable(doc: StateDocument, batch_id: str) -> BatchRecord:
    """Return the record ``batch_id`` names, or raise if it cannot be joined.

    A batch id supplied by a caller is untrusted, and membership is the one
    thing this whole feature asks the operator to trust. Two refusals:

    - **Unknown id.** An id that names no declared batch is a typo or a
      fabrication, not a batch. Accepting it would let an entry manufacture a
      change set out of nothing, which ``rollback_plan_get`` would then report
      as a legitimate — and, having no record, unlabelled — unit.
    - **Closed batch.** ``mureo_batch_end`` reports a ``member_count`` the
      operator keeps. If a later append could still join, that number silently
      stops being true, and a change set whose membership drifts after it was
      reported is exactly the "confidently wrong" state this feature exists to
      remove. Closing is final.

    Backfill and import (#545) therefore do not reattach to a closed batch:
    they declare their own with ``begin_batch``, which gives the imported set
    an honest label and start time instead of retrofitting someone else's.
    """
    record = find_batch(doc, batch_id)
    if record is None:
        raise BatchError(
            f"Unknown batch_id {batch_id.strip()!r}. Open a batch with "
            "mureo_batch_begin; an id that names no declared batch cannot be "
            "joined."
        )
    if record.ended_at is not None:
        raise BatchError(
            f"Batch {record.batch_id!r} closed at {record.ended_at}; its "
            "membership is final and was already reported. Open a new batch "
            "for further changes."
        )
    return record


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO 8601 timestamp, or ``None`` when it is unusable.

    Naive values are read as UTC so a hand-edited or legacy record still
    compares against ``now`` instead of raising.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def batch_open_hours(record: BatchRecord, now: datetime | None = None) -> float | None:
    """How long ``record`` has been open, or ``None`` if that is unknowable.

    ``None`` for a closed batch and for one whose ``started_at`` cannot be
    parsed — an unknown age must not be reported as a small one.

    ``now`` defaults to :func:`mureo.core.clock.server_now`, the one clock seam
    (#460): reaching for ``datetime.now`` directly would leave the production
    path outside the seam every test freezes, so a drift there would go
    unnoticed. Resolved through the MODULE (``clock.server_now()``) rather than
    a bound name, which is what keeps
    ``monkeypatch.setattr(mureo.core.clock, "server_now", …)`` effective.

    The import is deliberately lazy: ``mureo.core.__init__`` → ``runtime_context``
    → ``state_store`` → ``mureo.context.state`` → this module is a real import
    chain, so reaching ``mureo.core`` at module load would close the cycle.
    """
    if record.ended_at is not None:
        return None
    started = _parse_iso(record.started_at)
    if started is None:
        return None
    if now is None:
        from mureo.core import clock

        now = clock.server_now()
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return (current - started).total_seconds() / 3600.0


def stale_batch_warning(
    record: BatchRecord | None, now: datetime | None = None
) -> str | None:
    """Warn that a batch has been open too long, or ``None``.

    The asymmetry this exists for: a missed ``begin`` yields no batch, which is
    obvious and harmless. A missed ``end`` yields a batch that keeps swallowing
    unrelated changes for days and then reports them, confidently, as one
    reviewable unit — a wrong answer that looks like a right one. So the open
    batch has to announce itself; it is never closed on the operator's behalf.
    """
    if record is None:
        return None
    hours = batch_open_hours(record, now)
    if hours is None or hours < STALE_AFTER_HOURS:
        return None
    return (
        f"Batch {record.batch_id!r} ({record.label!r}) has been open for "
        f"{hours:.0f}h. Every action_log entry recorded since it opened has "
        "joined it, including any unrelated to that change set. If the bulk "
        "pass is finished, close it with mureo_batch_end; mureo will not close "
        "it for you."
    )


def stamp_batch(entry: ActionLogEntry, batch: BatchRecord | None) -> ActionLogEntry:
    """Return ``entry`` bound to ``batch``, or unchanged.

    An explicit ``batch_id`` already on the entry always wins: it is how an
    imported or backfilled record keeps the batch it actually belonged to,
    which must not be overwritten by whatever happens to be open now.

    **Never rebuild the entry field-by-field here.** ``dataclasses.replace``
    changes ``batch_id`` and carries everything else across by construction; an
    enumerated constructor silently drops any field added to
    :class:`ActionLogEntry` after this function was written, and joining a
    batch is the DEFAULT path (``join_active_batch=True``), so the loss would
    hit ordinary appends. The failure is silent — a dropped field reads as
    "the caller did not set it" — so nothing downstream would flag it.

    That is not hypothetical: an enumerated version of this function dropped
    the provenance fields (``origin`` / ``external_id``), and because
    ``is_external`` is derived from ``origin``, an externally-imported entry
    lost the very marker that stops a forged ``reversible_params`` from being
    planned as a reversal.
    """
    if batch is None or entry.batch_id is not None:
        return entry
    return replace(entry, batch_id=batch.batch_id)


def batch_members(
    doc: StateDocument, batch_id: str
) -> tuple[tuple[int, ActionLogEntry], ...]:
    """Return ``(index, entry)`` for every member of ``batch_id``, in log order.

    The index is the position in the FULL append-only log — the same index
    ``rollback_apply`` and ``rollback_of`` use — so a caller holding only the
    batch can still address each member individually.
    """
    wanted = batch_id.strip()
    if not wanted:
        return ()
    return tuple(
        (index, entry)
        for index, entry in enumerate(doc.action_log)
        if entry.batch_id == wanted
    )


def batch_platforms(doc: StateDocument, batch_id: str) -> tuple[str, ...]:
    """Distinct platform keys represented in ``batch_id``, sorted."""
    return tuple(sorted({entry.platform for _, entry in batch_members(doc, batch_id)}))


__all__ = [
    "STALE_AFTER_HOURS",
    "BatchError",
    "active_batch",
    "batch_members",
    "batch_open_hours",
    "batch_platforms",
    "ensure_joinable",
    "find_batch",
    "new_batch_id",
    "stale_batch_warning",
    "stamp_batch",
]
