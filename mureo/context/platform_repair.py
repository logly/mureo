"""The way out of a ``platforms`` entry mureo cannot resolve (Issue #610).

:mod:`mureo.context.platform_guards` stops a **new** bad key being written
(#609). This module is the other half: what an operator does about state that
already carries one. Before it, the only move was to open STATE.json and edit
it by hand — on a non-engineer's machine the more dangerous option, not the
safer one.

What counts as "unresolvable" is **not decided here**
-----------------------------------------------------
:func:`is_unresolvable_platform_key` asks
:func:`~mureo.context.platform_guards.reject_unknown_platform_key` and reports
what it said. A second answer to "is this key real?" that can drift from the
first is the defect #609/#610 are about, so this module owns no vocabulary of
its own — not the built-in list, not the installed-provider enumeration, not
the ``plugin:<distribution>:<provider>`` form. It inherits that function's
fail-open behaviour too: when the environment cannot be enumerated at all,
every key is treated as resolvable and this module proposes nothing. A broken
install is not evidence that an entry should be deleted.

Unresolvable is not enough to propose removal (#616)
----------------------------------------------------
"mureo cannot resolve this key" is a fact about the **machine running the
repair** — which plugins are importable at this moment — not about the entry.
The same document is judged differently on two machines, and on the machine
lacking a bridge a *legitimate* solitary entry, holding a real account's real
figures and duplicating nothing, looked exactly like the invented key the
command exists to remove.

So the plan asks the **document** whether the entry is wrong, and offers
removal only on one of two answers:

- :data:`DROP_DUPLICATE` — another key in the same ``platforms`` map holds the
  same ad account and mureo CAN resolve it. The record survives under the key
  the account is really stored under, so this one is a second copy.
- :data:`DROP_EMPTY_STUB` — the entry stores nothing at all: no campaigns, no
  ``totals``, no ``periods`` and no operator-declared setting. There is
  nothing in it to lose, whoever the key turns out to belong to.

Everything else unresolvable is reported as a :class:`PlatformKeyFinding` and
handed back, the way an undecidable duplicate already is. Note what does NOT
make a stub: an empty ``account_id``. The shape reported from the field
carries one, and treating "did not say which account" as "holds nothing"
would delete precisely the solitary entry #616 is about.

The one field a sync does not bring back (#617)
------------------------------------------------
``conversion_action_types`` (:class:`~mureo.context.models.PlatformState`) is
an allow-list a **person** declared so a custom-event advertiser is counted
correctly (#342). Nothing on the platform side knows it, so no sync restores
it — unlike every figure in the entry. An entry carrying one is therefore
never dropped, even when it is otherwise removable; it is reported as
:data:`KEEP_CONVERSION_OVERRIDE` instead.

Refusing rather than asking a second time is deliberate. The confirmation this
command already asks is skippable with ``--yes``, which is exactly how the
sweep this feature leads with (``--all --apply --yes``) is run, so a second
prompt would protect nobody on the path that matters. A setting only an
operator can supply is also, by definition, not mureo's to decide.

Drop, never merge
-----------------
Two repairs were plausible: **move** the unresolvable entry's figures under
the key the account is really stored under, or **drop** the unresolvable
entry and let the next sync refill the canonical one. This module does the
second, only.

Moving requires deciding that the canonical entry is "empty or older" — a
judgement about which of two sets of partial figures is true, which is
precisely what ``mureo/web/reports.py`` refuses to make and is right to
refuse. It is also undefined in the shape actually reported from the field: an
unresolvable entry whose ``account_id`` is ``""`` joins with nothing, so there
is no canonical entry to move it to. Dropping needs no such judgement. The
figures are not lost — they are re-fetchable from the platform, and the
pre-repair document is backed up first. That argument covers figures and
nothing else, which is why the one operator-declared field is excluded from
dropping altogether (see above).

Nothing else in the document is touched. In particular ``last_synced_at`` is
**not** re-stamped: a repair is not a sync, and re-stamping it would make
every other platform's stale figures read as just-synced (the #535 trap). The
legacy v1 flat ``campaigns`` list is left alone too — it is platform-blind, so
nothing in it says which entries came from the key being removed, and guessing
would delete another platform's campaigns.

Not an ``action_log`` entry
---------------------------
Deliberately. ``action_log`` records changes made to an **ad platform**: every
entry names a ``platform`` and is fed to
:func:`mureo.rollback.planner.plan_rollback`, whose allow-list is MCP tool
operations. A local-file repair has no platform operation to name and none to
reverse, so the planner would file it as irreversible — which reads as "mureo
cannot undo this" when in fact it can. The entry would also have to carry the
very key just removed, putting it back onto the dashboard's activity feed and
into every ``--platform`` filter. Reversibility here is the **timestamped
backup**, which restores the exact prior document — strictly more than a
rollback plan could offer for a whole-document edit.

The write path
--------------
:func:`apply_state_file_repairs` writes through ``write_state_file``, the
whole-document funnel #609 deliberately left permissive precisely so a bad key
can be rewritten. It never calls the targeted writers, so
:func:`~mureo.context.platform_guards.guard_platform_entry_write` never sees
it and cannot refuse the repair of a document that is already duplicated. A
test pins that against a document the create guard does reject.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from mureo.context.platform_accounts import platform_keys_for_account
from mureo.context.platform_guards import reject_unknown_platform_key

# ``_state_lock_path`` is imported rather than recomputed: the repair has to
# contend on the SAME sidecar lock every other STATE.json mutator uses, and a
# local copy of "STATE.json" -> "STATE.json.lock" is a second answer that can
# drift from the one in ``state.py``.
from mureo.context.state import (
    _state_lock_path,
    read_state_file,
    write_state_file,
)
from mureo.fsutil import backup_file, file_lock

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from mureo.context.models import PlatformState, StateDocument

DROP_DUPLICATE = "duplicate"
"""Offered: a key mureo CAN resolve holds the same ad account."""

DROP_EMPTY_STUB = "empty_stub"
"""Offered: the entry stores nothing — no figures, no declared settings."""

KEEP_CARRIES_FIGURES = "carries_figures"
"""Kept: nothing in the document says this entry is wrong (#616)."""

KEEP_CONVERSION_OVERRIDE = "conversion_override"
"""Kept: it carries ``conversion_action_types``, which no sync restores."""


@dataclass(frozen=True)
class RollupFacts:
    """One stored metric window, and when its figures were fetched.

    ``fetched_at`` is relayed verbatim (it is writer-stamped and optional) and
    is ``None`` when the window carries none — the same treatment the Reports
    view gives it.
    """

    period: str
    fetched_at: str | None


@dataclass(frozen=True)
class PlatformEntryFacts:
    """What one ``platforms`` entry holds, in terms an operator can check.

    Everything the person deciding needs without opening the file: which key,
    whether mureo can resolve it, which ad account it claims, how many
    campaigns it carries, whether it has a ``totals`` rollup and which windows
    it covers. No figures — the decision this supports is about identity, not
    about whose spend is larger, and putting the numbers side by side would
    invite exactly the comparison this module refuses to make.

    ``conversion_action_types`` is the exception that proves the contract:
    it is not a figure but a setting an operator declared, and it is the one
    thing in the entry no sync restores (#617). A preview can only print what
    this dataclass carries, so leaving it out was what made the loss silent.
    """

    key: str
    resolvable: bool
    account_id: str
    campaign_count: int
    has_totals: bool
    metrics_period: str | None
    totals_fetched_at: str | None
    rollups: tuple[RollupFacts, ...]
    conversion_action_types: tuple[str, ...] = ()

    @property
    def is_empty_stub(self) -> bool:
        """Does this entry store nothing a removal could lose?

        No campaigns, no ``totals``, no per-period rollups and no declared
        conversion allow-list. An empty ``account_id`` deliberately does NOT
        count towards this: the shape reported from the field carries one, and
        an entry that declined to name its account can still hold every figure
        a platform has (#616).
        """
        return not (
            self.campaign_count
            or self.has_totals
            or self.rollups
            or self.conversion_action_types
        )


@dataclass(frozen=True)
class PlatformKeyRepair:
    """One unresolvable entry mureo offers to drop, plus its context.

    ``same_account`` is every OTHER key that describes the same ad account, in
    document order. It is empty when the entry names no account mureo can join
    on, which is the shape reported from the field (``account_id: ""``); an
    empty tuple therefore means "mureo found nothing this could be a duplicate
    of", never "there is nothing else". Its members are not all survivors —
    another one may be in the same plan — so a caller previewing this has to
    compare against the plan's own keys before promising anything about them
    (#618).

    ``reason`` is :data:`DROP_DUPLICATE` or :data:`DROP_EMPTY_STUB`: what in
    the DOCUMENT says this entry is wrong. Unresolvability alone is not one of
    them.
    """

    entry: PlatformEntryFacts
    same_account: tuple[PlatformEntryFacts, ...]
    reason: str


@dataclass(frozen=True)
class PlatformKeyFinding:
    """One unresolvable entry mureo will NOT remove, and why.

    Reported rather than repaired, the way an undecidable duplicate already
    is. ``reason`` is :data:`KEEP_CARRIES_FIGURES` (nothing in the document
    says the entry is wrong — the key may belong to a plugin that is simply
    not installed on this machine) or :data:`KEEP_CONVERSION_OVERRIDE` (the
    entry could otherwise go, but carries a setting no sync restores).
    """

    entry: PlatformEntryFacts
    same_account: tuple[PlatformEntryFacts, ...]
    reason: str


@dataclass(frozen=True)
class PlatformKeyPlan:
    """Every unresolvable entry, split by whether mureo will act on it.

    ``repairs`` is what an ``--apply`` would remove; ``kept`` is what it would
    leave and report. A caller reporting "nothing to repair" has to consult
    both: a document whose only finding is in ``kept`` is not clean, it is
    waiting on the operator.
    """

    repairs: tuple[PlatformKeyRepair, ...]
    kept: tuple[PlatformKeyFinding, ...]


@dataclass(frozen=True)
class RepairOutcome:
    """What :func:`apply_state_file_repairs` did.

    ``changed`` is ``False`` — with ``backup`` ``None`` and ``repairs`` empty
    — whenever there was nothing to repair, and in that case the file was not
    rewritten at all, not even re-rendered.
    """

    path: Path
    repairs: tuple[PlatformKeyRepair, ...]
    changed: bool
    backup: Path | None


def is_unresolvable_platform_key(platform: str) -> bool:
    """Can mureo resolve ``platform`` to a platform? (#609's answer, reused.)

    Delegates to :func:`~mureo.context.platform_guards.
    reject_unknown_platform_key` and reports whether it objected, so the two
    surfaces can never disagree about which keys are real. That includes its
    fail-open behaviour: an environment whose installed plugins cannot be
    enumerated makes every key resolvable, and therefore proposes nothing for
    removal.
    """
    try:
        reject_unknown_platform_key(platform)
    except ValueError:
        return True
    return False


def _rollup_fetched_at(rollup: object) -> str | None:
    """The ``fetched_at`` a totals-shaped dict carries, or ``None``.

    Tolerant on purpose: this reads a document that is already known to be
    wrong in at least one way, and a non-dict rollup or a non-string
    ``fetched_at`` must degrade to "not stated" rather than raise out of a
    preview the operator is relying on.
    """
    if not isinstance(rollup, dict):
        return None
    value = rollup.get("fetched_at")
    return value if isinstance(value, str) and value.strip() else None


def _describe(key: str, entry: PlatformState) -> PlatformEntryFacts:
    """Shape one ``platforms`` entry into :class:`PlatformEntryFacts`."""
    periods: Mapping[str, Any] = (
        entry.periods if isinstance(entry.periods, dict) else {}
    )
    return PlatformEntryFacts(
        key=key,
        resolvable=not is_unresolvable_platform_key(key),
        account_id=entry.account_id,
        campaign_count=len(entry.campaigns),
        has_totals=bool(entry.totals),
        metrics_period=entry.metrics_period,
        totals_fetched_at=_rollup_fetched_at(entry.totals),
        rollups=tuple(
            RollupFacts(period=str(period), fetched_at=_rollup_fetched_at(rollup))
            for period, rollup in periods.items()
        ),
        conversion_action_types=tuple(entry.conversion_action_types or ()),
    )


def _drop_reason(
    entry: PlatformEntryFacts, same_account: tuple[PlatformEntryFacts, ...]
) -> str | None:
    """What in the DOCUMENT says this entry is wrong, or ``None`` (#616).

    Two answers only, and neither of them is "the key does not resolve on this
    machine". A sibling that is itself unresolvable does not count as a
    duplicate: two entries mureo cannot vouch for are not evidence against
    each other, and dropping either still loses figures nothing refills.
    """
    if any(other.resolvable for other in same_account):
        return DROP_DUPLICATE
    if entry.is_empty_stub:
        return DROP_EMPTY_STUB
    return None


def plan_platform_keys(
    doc: StateDocument, *, keys: Iterable[str] | None = None
) -> PlatformKeyPlan:
    """Every unresolvable entry, split into what mureo will and will not touch.

    Pure — it reads ``doc`` and returns a description. This is what a dry run
    shows, and :func:`apply_state_file_repairs` re-derives it under the lock
    before writing anything.

    ``keys`` narrows the plan to the named keys. A named key that resolves
    fine, or that the document does not carry, simply produces nothing;
    telling the operator which of the two happened needs the document itself
    and is the caller's job.
    """
    platforms = doc.platforms or {}
    wanted = frozenset(keys) if keys is not None else None
    repairs: list[PlatformKeyRepair] = []
    kept: list[PlatformKeyFinding] = []
    for key, entry in platforms.items():
        if wanted is not None and key not in wanted:
            continue
        if not is_unresolvable_platform_key(key):
            continue
        facts = _describe(key, entry)
        same_account = tuple(
            _describe(other, platforms[other])
            for other in platform_keys_for_account(platforms, entry.account_id)
            if other != key
        )
        reason = _drop_reason(facts, same_account)
        if reason is None:
            kept.append(PlatformKeyFinding(facts, same_account, KEEP_CARRIES_FIGURES))
        elif facts.conversion_action_types:
            # Removable by the document, but it carries the one field a sync
            # does not bring back (#617). Reported, never dropped.
            kept.append(
                PlatformKeyFinding(facts, same_account, KEEP_CONVERSION_OVERRIDE)
            )
        else:
            repairs.append(PlatformKeyRepair(facts, same_account, reason))
    return PlatformKeyPlan(repairs=tuple(repairs), kept=tuple(kept))


def plan_platform_key_repairs(
    doc: StateDocument, *, keys: Iterable[str] | None = None
) -> tuple[PlatformKeyRepair, ...]:
    """Only the entries :func:`plan_platform_keys` offers to remove.

    The narrow view, for callers with nothing to say about the entries mureo
    hands back. Anything that reports to an operator wants
    :func:`plan_platform_keys`: an empty result here does NOT mean the
    document is clean.
    """
    return plan_platform_keys(doc, keys=keys).repairs


def drop_platform_entries(doc: StateDocument, keys: Iterable[str]) -> StateDocument:
    """Return ``doc`` without the ``platforms`` entries named by ``keys``.

    Removes the WHOLE entry, ``conversion_action_types`` included — which is
    why :func:`plan_platform_keys` never names a key carrying one (#617).
    This function takes the caller's word for it and does not re-check.

    Pure, and deliberately narrow: only the ``platforms`` map changes.
    ``last_synced_at`` is not re-stamped (a repair is not a sync), the legacy
    flat ``campaigns`` list is left alone (it is platform-blind, so nothing in
    it says which entries came from the removed key), and ``action_log`` /
    ``reports`` / ``batches`` are carried across by ``replace``.
    """
    if not doc.platforms:
        return doc
    removing = frozenset(keys)
    return replace(
        doc,
        platforms={k: v for k, v in doc.platforms.items() if k not in removing},
    )


def apply_state_file_repairs(
    path: Path, *, keys: Iterable[str] | None = None
) -> RepairOutcome:
    """Drop every ``platforms`` entry the document shows to be wrong, safely.

    "Unresolvable" is the filter, not the criterion: an entry is removed only
    when it duplicates a resolvable key holding the same ad account or is an
    empty stub, and never when it carries an operator-declared conversion
    allow-list. See :func:`plan_platform_keys`.


    The whole cycle — read, plan, back up, write — runs inside the STATE.json
    sidecar lock every other mutator contends on, so a concurrent sync cannot
    slip a write in between the backup and the repair (which would make the
    backup a copy of a document that never existed). The plan is re-derived
    from the freshly-read document rather than trusted from a caller's earlier
    preview, so a key that stopped being unresolvable in the meantime — a
    bridge installed since — is not deleted on stale information.

    Writes nothing at all when there is nothing to repair: no backup, no
    re-render, no change of mtime.

    Args:
        path: STATE.json location.
        keys: Narrow the repair to these ``platforms`` keys. ``None`` (the
            default) repairs every unresolvable entry in the document.

    Returns:
        A :class:`RepairOutcome` naming what was dropped and where the
        pre-repair document was backed up to.

    Raises:
        ContextFileError: ``path`` exists but cannot be read or parsed. The
            repair refuses to proceed on a document it cannot parse strictly,
            because writing back a tolerantly-parsed one would silently drop
            the entries the tolerant parse skipped.
        OSError: The backup could not be written. Nothing is overwritten in
            that case — :func:`mureo.fsutil.backup_file` fails closed.
    """
    with file_lock(_state_lock_path(path)):
        doc = read_state_file(path)
        repairs = plan_platform_key_repairs(doc, keys=keys)
        if not repairs:
            return RepairOutcome(path=path, repairs=(), changed=False, backup=None)
        # Timestamped rather than a single rolling ``.bak``: a second repair
        # run would otherwise overwrite the only copy of the pre-repair
        # document with the already-repaired one.
        backup = backup_file(path, timestamped=True)
        write_state_file(
            path, drop_platform_entries(doc, [r.entry.key for r in repairs])
        )
        return RepairOutcome(path=path, repairs=repairs, changed=True, backup=backup)


__all__ = [
    "DROP_DUPLICATE",
    "DROP_EMPTY_STUB",
    "KEEP_CARRIES_FIGURES",
    "KEEP_CONVERSION_OVERRIDE",
    "PlatformEntryFacts",
    "PlatformKeyFinding",
    "PlatformKeyPlan",
    "PlatformKeyRepair",
    "RepairOutcome",
    "RollupFacts",
    "apply_state_file_repairs",
    "drop_platform_entries",
    "is_unresolvable_platform_key",
    "plan_platform_key_repairs",
    "plan_platform_keys",
]
