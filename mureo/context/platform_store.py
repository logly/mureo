"""Targeted writes to a platform entry's rollups, notes and settings.

Split out of :mod:`mureo.context.state` in #917, verbatim apart from the long
functions being broken into named steps and the longest rationale moving from
their docstrings into the sections below; :mod:`mureo.context.state`
re-exports every public name here, so existing imports keep working.

Every writer here builds on :func:`mureo.context.campaign_store._platform_base`
and changes ONLY the fields it has input for, under
:func:`mureo.context.state_io._locked_state_mutation`.

``set_platform_daily``: the path half of the day-grain write (#690, #710)
-------------------------------------------------------------------------

``periods`` carries one rollup per WINDOW and every collection overwrites
it, so the figure it replaces is gone and nothing in the document can
answer "was yesterday better than the day before?". The ``daily`` map is the
half that accumulates: one totals-shaped bucket per ``YYYY-MM-DD``, the same
canonical metric vocabulary, merged PER DATE KEY.

The merge itself is :func:`~mureo.context.daily.with_platform_daily`
(#710) — :func:`set_platform_daily` is the PATH half: the lock, the read, and
the atomic write back around it. A writer that must land ``daily`` together
with other fields in one document write calls that one directly, and gets
the identical semantics rather than a second implementation of them:

- a date this call supplies REPLACES that day's bucket wholesale, so
  re-writing a day is idempotent rather than additive;
- every OTHER date already stored is preserved — that is the whole point;
- the platform's campaigns, rollups, conversion override and
  ``not_collected`` note, and every other platform, are untouched;
- **a day nobody collected is not written** — no zero-filling.

**Only complete past days are accepted.** Each key must be ``YYYY-MM-DD``,
must be a date that exists, and must be before ``as_of_date`` (or, without
one, before the host's today) — see
:func:`~mureo.context.daily._reject_unusable_daily_keys`, which runs before
the file is opened and before the lock is taken: a rejected write must leave
the document exactly as it was, including its ``last_synced_at``.
``with_platform_daily`` guards again — this call moves WHEN the refusal
happens, not whether it does.

``fetched_at`` is stamped with the write time on every bucket the call
supplies without one, and a day it merely preserves is never re-stamped —
the same contract :func:`set_platform_metrics` keeps (#637).

The stored history is capped at
:data:`~mureo.context.daily.DAILY_RETENTION_DAYS` days on every write (see
:func:`~mureo.context.daily.capped_platform_daily`); the days that trim
drops are archived under ``history/daily/<YYYY-MM>.json`` on this lock
first, so nothing is lost to the cap (#758 phase 4a).

What a ``not_collected`` note says (#638, #661)
-----------------------------------------------

**It says the numbers were not UPDATED. It does not say they are wrong.**
``totals`` / ``periods`` are left exactly as they were — they are still the
last figures that were truly collected — because writing 0 for a collection
that failed would be the lie :func:`set_platform_metrics`' merge semantics
deliberately avoid. What was missing was the other half: with the failure
unrecorded, "not collected" and "collected, and the answer was zero" are the
same document, and an operator watching a card whose figures had not moved
for eleven days could not tell a stopped account from a stopped collector.

**A clear must be said, and whoever collects says it.** Every other targeted
mutator here treats an omitted argument as "leave it alone", so nothing else
in this module can retire the note: a successful collection writes a rollup,
and one window's rollup landing does not prove the platform-level collection
recovered. The collector therefore calls :func:`set_platform_not_collected`
with ``reason=None`` on success, in the same pass — and
:func:`set_workspace_not_collected` with ``reason=None`` on the next
successful collection, likewise. A note that outlives its failure is
permanently stale information stated with confidence — exactly what this
field exists to remove.

The dashboard does not TRUST that contract, and should not have to: it drops
a platform note any later collection has already answered (see
:func:`mureo.web.report_document._platform_not_collected`), and a workspace
note that any later collection anywhere in the document has already answered
(see :func:`mureo.web.report_document._workspace_not_collected`), the same
evidence-based retirement #638 gave the per-platform note. Clearing it here
is still what keeps the document itself honest — the read rule only decides
what is shown.

``last_synced_at`` is deliberately NOT re-stamped by either writer, for the
same reason :func:`~mureo.context.action_log_store.append_action_log` does
not: a collection that FAILED is not a sync, and re-stamping it would make the
card report itself just-synced on the strength of nothing having been
collected.

**The workspace note is the counterpart of the platform note, one level up —
and :func:`set_workspace_not_collected` deliberately takes neither a platform
key nor an ``account_id``.** Those two are exactly what a collection that
died before reaching any platform failed to resolve, so requiring them to
record "resolving them failed" is circular. Writing the note onto every
existing platform entry would state a different fact ("Meta failed, and
Google failed, and…"), and a workspace that has NEVER been collected — the
case this exists for — has no entry to write onto: inventing one with a blank
``account_id`` creates the poisoned entry #533/#536 removed.

**Nothing else in the document is touched by the workspace note.**
``platforms`` is left exactly as it was, including any per-platform note: the
two record different failures and neither implies the other. The stored
figures are still the last ones truly collected — this says they were not
UPDATED, never that they are wrong.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from pathlib import Path

    from mureo.context.models import PlatformState, StateDocument

from mureo.context.campaign_store import _platform_base, _stamp_fetched_at
from mureo.context.daily import _reject_unusable_daily_keys, with_platform_daily
from mureo.context.history import archive_platform_daily
from mureo.context.models import NOT_COLLECTED_REASON_MAX_CHARS
from mureo.context.platform_accounts import UNKNOWN_ACCOUNT_ID, normalize_account_id
from mureo.context.platform_guards import guard_platform_entry_write
from mureo.context.state_io import _locked_state_mutation, _now_iso
from mureo.core.metrics_windows import reject_non_canonical_metrics_window


def _reject_non_canonical_windows(
    metrics_period: str | None, periods: dict[str, dict[str, Any]] | None
) -> None:
    """Refuse a window outside the closed vocabulary, before the file is touched.

    **The window vocabulary is closed (#659).** ``metrics_period`` and every
    ``periods`` key must be one of
    :data:`~mureo.core.metrics_windows.CANONICAL_METRICS_WINDOWS`; anything
    else is REFUSED before the file is touched, and refused as spelled — a
    ``LAST_8_DAYS`` rollup is never re-filed under ``LAST_7_DAYS``, because
    that would present eight days of figures as a seven-day answer. A window
    outside the set lands where no default view looks, so accepting it
    produces a write that reports success while the dashboard truthfully
    keeps reading stale, with nothing naming the contradiction. Refusing here
    is the one moment the caller still holds the figures and can re-file
    them. This is the WRITE half of a deliberate asymmetry: the read side
    stays tolerant of labels already on disk (see
    :func:`~mureo.web.report_document._available_periods`), which are real figures
    under an unexpected name.
    """
    # Outside the lock and before the file is opened: a rejected write must
    # leave the document exactly as it was, including its ``last_synced_at``.
    if metrics_period is not None:
        reject_non_canonical_metrics_window(metrics_period, field="metrics_period")
    for window in periods or {}:
        reject_non_canonical_metrics_window(window, field="periods key")


def _merged_periods(
    base: PlatformState,
    periods: dict[str, dict[str, Any]] | None,
    written_at: str,
) -> dict[str, dict[str, Any]] | None:
    """``base.periods`` with ``periods`` merged in PER WINDOW KEY.

    ``None`` preserves the existing map untouched.
    """
    if periods is None:
        return base.periods
    merged = dict(base.periods) if base.periods else {}
    # Only the buckets THIS write supplies are stamped; the ones it
    # merely preserves keep the age they were collected at.
    merged.update(
        {
            window: _stamp_fetched_at(bucket, written_at)
            for window, bucket in periods.items()
        }
    )
    return merged


def _rollup_entry(
    base: PlatformState,
    *,
    account_id: str,
    written_at: str,
    totals: dict[str, Any] | None,
    metrics_period: str | None,
    periods: dict[str, dict[str, Any]] | None,
) -> PlatformState:
    """``base`` carrying the rollups this write supplies.

    ``fetched_at`` — the freshness the dashboard reads — is stamped with the
    write time on every rollup this call SUPPLIES without one (``totals`` and
    each ``periods`` bucket), and a rollup this call merely preserves is never
    re-stamped. A value the caller did supply is relayed verbatim. See
    :func:`~mureo.context.campaign_store._stamp_fetched_at` (#637).
    """
    # ``campaigns`` and the #342 conversion override have no input on a
    # metrics write and are carried over by ``replace``; a ``None``
    # argument means "leave as it was", not "clear it".
    return replace(
        base,
        account_id=account_id,
        totals=(
            _stamp_fetched_at(totals, written_at) if totals is not None else base.totals
        ),
        metrics_period=(
            metrics_period if metrics_period is not None else base.metrics_period
        ),
        periods=_merged_periods(base, periods, written_at),
    )


def _with_platform_metrics(
    doc: StateDocument,
    *,
    platform: str,
    account_id: str,
    totals: dict[str, Any] | None,
    metrics_period: str | None,
    periods: dict[str, dict[str, Any]] | None,
) -> StateDocument:
    """``doc`` with the platform's rollups merged — the locked step.

    The platform's campaigns and every OTHER platform are preserved; only the
    targeted platform's rollup fields are touched. The platform entry is
    created (carrying ``account_id``) when absent.

    Merge semantics — a partial write never clobbers an unrelated window:

    - ``totals`` / ``metrics_period``: replaced when provided (non-``None``),
      otherwise the existing value is preserved.
    - ``periods``: merged PER WINDOW KEY into the existing map, so a
      daily-check ``YESTERDAY`` write keeps the ``LAST_30_DAYS`` bucket a prior
      sync wrote (and vice versa). A given window key is replaced wholesale.
      ``None`` preserves the existing map untouched.

    Re-stamps ``last_synced_at`` and writes back atomically under the state
    lock. Other document sections (root campaigns, action_log, reports) are
    preserved.
    """
    platforms = dict(doc.platforms) if doc.platforms else {}
    guard_platform_entry_write(platforms, platform, account_id)

    base = _platform_base(platforms, platform, account_id)
    # One clock read for the whole write, so a rollup's age and the
    # document's cannot disagree by a hair and read as two events.
    written_at = _now_iso()
    platforms[platform] = _rollup_entry(
        base,
        account_id=account_id,
        written_at=written_at,
        totals=totals,
        metrics_period=metrics_period,
        periods=periods,
    )
    return replace(doc, last_synced_at=written_at, platforms=platforms)


def set_platform_metrics(
    path: Path,
    platform: str,
    account_id: str,
    *,
    totals: dict[str, Any] | None = None,
    metrics_period: str | None = None,
    periods: dict[str, dict[str, Any]] | None = None,
) -> StateDocument:
    """Set a platform's metric rollups in STATE.json's v2 ``platforms`` section.

    Writes the platform-level KPI rollup the reporting dashboard reads — the
    single ``totals`` + ``metrics_period`` (the most recent window) and/or the
    per-period ``periods`` map (``{"YESTERDAY": {...}, "LAST_30_DAYS": {...}}``).
    Merge semantics and what is preserved: :func:`_with_platform_metrics`;
    ``fetched_at`` stamping (#637): :func:`_rollup_entry`; the closed window
    vocabulary (#659): :func:`_reject_non_canonical_windows`.

    Args:
        path: STATE.json location.
        platform: The ``platforms`` key (``"google_ads"``, ``"plugin:<dist>"``, …).
        account_id: The platform account id, always written onto the entry.
        totals: The single-rollup totals to set; ``None`` preserves.
        metrics_period: The canonical window ``totals`` covers; ``None`` preserves.
        periods: Canonical-window-keyed rollups to merge in; ``None`` preserves.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: ``metrics_period`` or a ``periods`` key is not a canonical
            metrics window (#659), or ``platform`` is unusable or names no
            platform mureo can resolve (a built-in, an installed plugin's, or a
            ``plugin:<dist>:<provider>`` key — checked on CREATE only), or the
            write would create a SECOND key for an account another key holds
            (:func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """
    _reject_non_canonical_windows(metrics_period, periods)

    def _build(doc: StateDocument) -> StateDocument:
        return _with_platform_metrics(
            doc,
            platform=platform,
            account_id=account_id,
            totals=totals,
            metrics_period=metrics_period,
            periods=periods,
        )

    return _locked_state_mutation(path, _build)


def _daily_archiver(
    path: Path,
) -> Callable[[str, str, dict[str, dict[str, Any]]], None]:
    """The ``archive`` hook for :func:`~mureo.context.daily.with_platform_daily`.

    Keeps the days the retention trim drops under ``path``'s
    ``history/daily/`` (#758 phase 4a) — see
    :func:`~mureo.context.history.archive_platform_daily`.
    """

    def _archive(p: str, a: str, d: dict[str, dict[str, Any]]) -> None:
        archive_platform_daily(path, p, a, d)

    return _archive


def set_platform_daily(
    path: Path,
    platform: str,
    account_id: str,
    *,
    days: dict[str, dict[str, Any]],
    as_of_date: date | None = None,
) -> StateDocument:
    """Merge day-grain rollups into a platform's ``daily`` history (#690).

    The PATH half of :func:`~mureo.context.daily.with_platform_daily`; the
    merge, completeness, ``fetched_at`` and retention rules are in the module
    docstring. Re-stamps ``last_synced_at`` and writes back atomically.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>:<provider>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
        days: Day-grain rollups keyed ``YYYY-MM-DD``. An empty map writes no
            day and leaves the stored history alone.
        as_of_date: The account's own today, resolved in the ACCOUNT's
            timezone, for the "is this day over?" check (#710). Omit to judge
            against the host's clock, which is what every caller did before it
            existed. It is a self-report and is bounded as one: an anchor more
            than :data:`~mureo.context.daily._MAX_ANCHOR_DAYS_AHEAD` days
            ahead of the server's date is refused, so stating a far-future
            today cannot switch the completeness rule off.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: a key is not a complete past calendar day (#690), or
            ``platform`` is not a usable platform key, names no platform
            mureo can resolve (checked on CREATE only, so an existing entry
            stays writable), or the write would create a SECOND key for an
            account another key already holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """
    # Outside the lock and before the file is opened (see the module docstring).
    _reject_unusable_daily_keys(days, as_of_date=as_of_date)
    archive = _daily_archiver(path)

    def _build(doc: StateDocument) -> StateDocument:
        return with_platform_daily(
            doc, platform, account_id, days, as_of_date=as_of_date, archive=archive
        )

    return _locked_state_mutation(path, _build)


def _account_id_for_not_collected(
    platforms: dict[str, PlatformState], platform: str, account_id: str | None
) -> str:
    """The ``account_id`` a ``not_collected`` write should land on (#794).

    A collection can fail BECAUSE no account could be resolved — Google Ads
    authenticated with zero accessible accounts, no customer id configured —
    and the caller then has no legal value to pass. ``None``, ``""``, a
    whitespace-only string and a placeholder spelling
    (:data:`~mureo.context.platform_accounts.PLACEHOLDER_ACCOUNT_IDS`, #793)
    all state that same absence, and all fold to — and are stored as —
    :data:`~mureo.context.platform_accounts.UNKNOWN_ACCOUNT_ID` (``""``), the one
    spelling the join understands: it matches nothing, including another
    unknown id, so two platforms that both failed this way stay two entries.
    Inventing a placeholder instead — the observed ``"unknown"`` on both
    Google Ads and Meta Ads — is what made the reports view read them as one
    duplicated ad account (#793).

    **An unknown id never overwrites a KNOWN stored one.** The entry for a
    platform that failed today still describes the ad account it described
    yesterday; blanking it would break the per-account conversion override
    and the duplicate join for an entry that was fine. A known id is written
    verbatim — the caller's own spelling — exactly as before.
    """
    if account_id is not None and normalize_account_id(account_id):
        return account_id
    existing = platforms.get(platform)
    if existing is not None and normalize_account_id(existing.account_id):
        return existing.account_id
    return UNKNOWN_ACCOUNT_ID


def _not_collected_note(reason: str | None) -> dict[str, str] | None:
    """The ``{"attempted_at", "reason"}`` note for ``reason``, or ``None``.

    ``None`` or a blank ``reason`` CLEARS the note. ``attempted_at`` is
    stamped SERVER-side (the #460 rule): the caller states what happened,
    never when. The reason is truncated to
    :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS` characters.
    """
    cleaned = reason.strip() if isinstance(reason, str) else ""
    if not cleaned:
        return None
    return {
        "attempted_at": _now_iso(),
        "reason": cleaned[:NOT_COLLECTED_REASON_MAX_CHARS],
    }


def _with_platform_not_collected(
    doc: StateDocument, platform: str, account_id: str | None, reason: str | None
) -> StateDocument:
    """``doc`` with ``platforms[platform].not_collected`` set — the locked step.

    The platform's campaigns, rollups and conversion override — and every
    OTHER platform — are preserved; the entry is created (carrying
    ``account_id``) when absent, because a platform that failed on its very
    first collection is precisely the one an operator cannot otherwise
    diagnose.

    **The account id may itself be what the collection could not resolve.**
    ``None`` / ``""`` / whitespace / a placeholder spelling
    (:data:`~mureo.context.platform_accounts.PLACEHOLDER_ACCOUNT_IDS`, #793)
    say so, and are stored as
    :data:`~mureo.context.platform_accounts.UNKNOWN_ACCOUNT_ID` (``""``) rather
    than refused — see :func:`_account_id_for_not_collected`, which also explains
    why an unknown id is never written over a known stored one (#794).
    """
    platforms = dict(doc.platforms) if doc.platforms else {}
    # Resolved BEFORE the guard, because what the guard has to judge is
    # the id this call will actually store — not the absence a caller who
    # could not resolve one sent in its place.
    resolved = _account_id_for_not_collected(platforms, platform, account_id)
    guard_platform_entry_write(platforms, platform, resolved)
    note = _not_collected_note(reason)
    # Campaigns, rollups and the conversion override have no input on this
    # call and are carried over by ``replace``: it declares one fact.
    platforms[platform] = replace(
        _platform_base(platforms, platform, resolved),
        account_id=resolved,
        not_collected=note,
    )
    return replace(doc, platforms=platforms)


def set_platform_not_collected(
    path: Path,
    platform: str,
    account_id: str | None,
    *,
    reason: str | None,
) -> StateDocument:
    """Record — or clear — why a platform's figures were not refreshed (#638).

    Writes ``platforms[platform].not_collected`` as
    ``{"attempted_at": <now>, "reason": <reason>}``, or removes it when
    ``reason`` is ``None`` / blank — see :func:`_not_collected_note`. What the
    note says and does not say, who clears it, and why ``last_synced_at`` is
    NOT re-stamped: see the module docstring. The write is atomic, under the
    state lock; what it preserves: see :func:`_with_platform_not_collected`.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>:<provider>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, written onto the entry. ``None``
            / ``""`` / whitespace / a ``PLACEHOLDER_ACCOUNT_IDS`` spelling
            state that the collection could not resolve one, and are stored
            as ``""``; a known id already stored on the entry then stays.
        reason: What happened, in words an operator can act on (an expired
            token, a permissions error, a collector that did not run).
            Truncated to :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS`
            characters. ``None`` or blank CLEARS the note.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: ``platform`` is not a usable platform key, names no
            platform mureo can resolve (checked on CREATE only, so an existing
            entry stays writable — an operator holding a bad key is exactly
            the operator whose figures stopped moving), or the write would
            create a SECOND key for an account another key already holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """

    def _build(doc: StateDocument) -> StateDocument:
        return _with_platform_not_collected(doc, platform, account_id, reason)

    return _locked_state_mutation(path, _build)


def set_workspace_not_collected(
    path: Path,
    *,
    reason: str | None,
) -> StateDocument:
    """Record — or clear — why this WORKSPACE could not be collected (#661).

    Writes the document-level ``workspace_not_collected`` as
    ``{"attempted_at": <now>, "reason": <reason>}``, or removes it when
    ``reason`` is ``None`` / blank. ``attempted_at`` is stamped SERVER-side
    (the #460 rule): the caller states what happened, never when.

    The counterpart of :func:`set_platform_not_collected`, one level up, and
    it deliberately takes neither a platform key nor an ``account_id``; why,
    what it leaves untouched, who clears it and why ``last_synced_at`` is NOT
    re-stamped: see the module docstring.

    Args:
        path: STATE.json location. Created (with an otherwise empty document)
            when it does not exist — the absence of figures is the thing
            being reported, so this write cannot be conditional on having any.
        reason: What happened, in words an operator can act on (credentials
            that could not be read, a run that never started, a client whose
            workspace is missing). Truncated to
            :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS`
            characters. ``None`` or blank CLEARS the note.

    Returns:
        The updated :class:`StateDocument`.
    """

    def _build(doc: StateDocument) -> StateDocument:
        # One field, by ``replace``: everything else — platforms and their own
        # notes, campaigns, action_log, reports, batches — is carried over.
        return replace(doc, workspace_not_collected=_not_collected_note(reason))

    return _locked_state_mutation(path, _build)


def _cleaned_action_types(
    conversion_action_types: list[str] | None,
) -> tuple[str, ...] | None:
    """The non-blank, stripped action_types, or ``None`` to clear the override."""
    cleaned: tuple[str, ...] | None = None
    if conversion_action_types:
        cleaned = tuple(
            str(x).strip()
            for x in conversion_action_types
            if isinstance(x, str) and x.strip()
        )
        cleaned = cleaned or None
    return cleaned


def _with_conversion_action_types(
    doc: StateDocument,
    platform: str,
    account_id: str,
    cleaned: tuple[str, ...] | None,
) -> StateDocument:
    """``doc`` with the platform's conversion override set — the locked step."""
    platforms = dict(doc.platforms) if doc.platforms else {}
    guard_platform_entry_write(platforms, platform, account_id)
    # Campaigns and every rollup are untouched by construction — this call
    # declares the conversion set and nothing else.
    platforms[platform] = replace(
        _platform_base(platforms, platform, account_id),
        account_id=account_id,
        conversion_action_types=cleaned,
    )
    return replace(doc, last_synced_at=_now_iso(), platforms=platforms)


def set_conversion_action_types(
    path: Path,
    platform: str,
    account_id: str,
    conversion_action_types: list[str] | None,
) -> StateDocument:
    """Set a platform's operator conversion ``action_type`` override (#342).

    Declares EXACTLY which Meta ``action_type`` rows count as this account's
    conversions — overriding the built-in deduped generic set
    (``{lead, purchase, complete_registration}``) so a custom-event advertiser
    (``offsite_conversion.custom.<id>``) or a component-only account is counted
    correctly. Pass ``None`` (or an empty list) to clear the override and
    restore the default.

    Replacement semantics: the override is the *complete* conversion set for
    the account — the counters use these and only these, never summed on top of
    the generic set (so two overlapping alias rows can't double-count).

    The platform's campaigns / rollups and every OTHER platform are preserved;
    the entry is created (carrying ``account_id``) when absent. Re-stamps
    ``last_synced_at`` and writes back atomically under the state lock.

    Args:
        path: STATE.json location.
        platform: Platform key (e.g. ``"meta_ads"``).
        account_id: The platform account id, always written onto the entry.
        conversion_action_types: The exact action_types to count, or ``None`` /
            ``[]`` to clear.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: ``platform`` is not a usable platform key, names no
            platform mureo can resolve (a built-in, an installed plugin's
            platform, or a ``plugin:<dist>:<provider>`` key — checked on
            CREATE only, so an existing entry stays writable), or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """
    cleaned = _cleaned_action_types(conversion_action_types)

    def _build(doc: StateDocument) -> StateDocument:
        return _with_conversion_action_types(doc, platform, account_id, cleaned)

    return _locked_state_mutation(path, _build)


__all__ = [
    "set_conversion_action_types",
    "set_platform_daily",
    "set_platform_metrics",
    "set_platform_not_collected",
    "set_workspace_not_collected",
]
