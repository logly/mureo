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
active :class:`StateStore` (``_resolve_path``), while the native and plugin
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
from typing import TYPE_CHECKING

from mureo.context.models import ActionLogEntry

if TYPE_CHECKING:
    from mureo.context.models import BatchRecord, StateDocument


class BatchError(Exception):
    """A batch lifecycle call that cannot be honoured.

    Raised for opening a batch while one is already open, and for closing one
    when none is. Both are refused rather than resolved silently: flattening a
    nested begin would merge two change sets an operator meant to keep apart,
    and a no-op end would report a batch that never collected anything.
    """


#: Number of random bytes in the id suffix. Ids are workspace-local names, not
#: secrets — this is collision avoidance across same-second batches, nothing
#: more.
_ID_ENTROPY_BYTES = 4


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


def stamp_batch(entry: ActionLogEntry, batch: BatchRecord | None) -> ActionLogEntry:
    """Return ``entry`` bound to ``batch``, or unchanged.

    An explicit ``batch_id`` already on the entry always wins: it is how an
    imported or backfilled record keeps the batch it actually belonged to,
    which must not be overwritten by whatever happens to be open now.
    """
    if batch is None or entry.batch_id is not None:
        return entry
    return ActionLogEntry(
        timestamp=entry.timestamp,
        action=entry.action,
        platform=entry.platform,
        campaign_id=entry.campaign_id,
        ad_id=entry.ad_id,
        summary=entry.summary,
        command=entry.command,
        metrics_at_action=entry.metrics_at_action,
        observation_due=entry.observation_due,
        reversible_params=entry.reversible_params,
        rollback_of=entry.rollback_of,
        evaluation_of=entry.evaluation_of,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        batch_id=batch.batch_id,
    )


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
    "BatchError",
    "active_batch",
    "batch_members",
    "batch_platforms",
    "find_batch",
    "new_batch_id",
    "stamp_batch",
]
