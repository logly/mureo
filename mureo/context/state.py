"""Read, mutate and durably write STATE.json.

The document layer: the atomic write (temp file -> fsync -> rename), the
cross-process lock that makes a read -> modify -> write cycle one critical
section, and the targeted mutators that own STATE.json's merge semantics —
what a partial write inherits rather than resets.

Two halves that used to live here were split out in #538 to bring this file
back under the repo's size limits, both verbatim:

- the JSON codec (:func:`parse_state` / :func:`render_state` and their
  per-field helpers) is now :mod:`mureo.context.state_codec`;
- the account conversion-override lookup
  (:func:`load_conversion_action_types`) is now
  :mod:`mureo.context.conversion_overrides`.

Both are **re-exported from this module**, because ``mureo.context.state`` has
always been the single import site for the whole STATE.json surface and
callers inside and outside this tree import it from here.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mureo.context.models import ActionLogEntry, CampaignSnapshot

from mureo.context.batch import (
    BatchError,
    active_batch,
    batch_members,
    ensure_joinable,
    new_batch_id,
    stamp_batch,
)
from mureo.context.conversion_overrides import load_conversion_action_types
from mureo.context.display_codec import parse_display_contract
from mureo.context.errors import ContextFileError
from mureo.context.models import (
    DAILY_DATE_KEY_PATTERN,
    NOT_COLLECTED_REASON_MAX_CHARS,
    BatchRecord,
    PlatformState,
    StateDocument,
)
from mureo.context.platform_accounts import account_ids_match, normalize_account_id
from mureo.context.platform_guards import (
    guard_platform_entry_write,
    warn_on_duplicate_accounts,
)
from mureo.context.state_codec import parse_state, render_state
from mureo.fsutil import file_lock

#: How many days of ``PlatformState.daily`` history a write keeps (#690).
#:
#: 28 + margin, not a round number: the delivery-collapse detector baselines
#: a day against the trailing
#: :data:`~mureo.analysis.delivery_collapse.DEFAULT_BASELINE_DAYS` (28) days
#: of the same weekday, so a history shorter than that would be unable to
#: answer the question it is collected for. The margin covers the operator who
#: raises ``delivery_collapse_baseline_days`` a little in STRATEGY.md, and the
#: days a collector missed — a gap is not backfilled, so 28 stored keys are
#: not necessarily 28 calendar days.
#:
#: Applied at WRITE time rather than on read: an account collected every day
#: for a year would otherwise grow STATE.json without bound, and the whole
#: document is read and re-rendered on every mutation.
DAILY_RETENTION_DAYS = 35

_DAILY_DATE_KEY_RE = re.compile(DAILY_DATE_KEY_PATTERN)


def _atomic_write(path: Path, content: str) -> None:
    """Atomically and durably write a file (temp file -> fsync -> rename).

    fsync the data before the rename so a crash/power loss just after
    ``os.replace`` cannot leave STATE.json as a zero-length/partial file (which
    would lose campaign history / action_log). Best-effort directory fsync makes
    the rename itself durable on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _fsync_dir(parent: Path) -> None:
    """Best-effort fsync of ``parent`` so a rename is durable (POSIX-only)."""
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def read_state_file(path: Path, *, strict: bool = True) -> StateDocument:
    """Read a STATE.json file and return a StateDocument.

    Returns a default StateDocument if the file does not exist. ``strict`` is
    forwarded to :func:`parse_state`: pass ``strict=False`` from the read-only
    Reports view so a nonconforming campaign entry is skipped instead of
    raising and blanking the whole document.
    """
    if not path.exists():
        return StateDocument()
    try:
        text = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        raise ContextFileError(f"No read permission for STATE.json: {path}") from exc
    try:
        return parse_state(text, strict=strict)
    except json.JSONDecodeError as exc:
        raise ContextFileError(f"Failed to parse JSON in STATE.json: {path}") from exc


def write_state_file(path: Path, doc: StateDocument) -> None:
    """Atomically write a StateDocument to a STATE.json file.

    Also emits the advisory duplicate-account warning (#534) — see
    :func:`mureo.context.platform_guards.warn_on_duplicate_accounts`. The write
    proceeds regardless.
    """
    warn_on_duplicate_accounts(path, doc)
    text = render_state(doc)
    _atomic_write(path, text)


def _state_lock_path(path: Path) -> Path:
    """Sidecar lock file for ``path`` (e.g. ``STATE.json`` -> ``STATE.json.lock``)."""
    return path.with_name(path.name + ".lock")


def _locked_state_mutation(
    path: Path, build: Callable[[StateDocument], StateDocument]
) -> StateDocument:
    """Run a read -> ``build`` -> write cycle as one critical section.

    ``_atomic_write`` only makes the file *replace* atomic; the surrounding
    read-modify-write is not. Holding the cross-process ``file_lock`` across
    read + write serialises every STATE.json mutator, so two concurrent calls
    (built-in <-> built-in, or built-in <-> plugin dispatch) can no longer
    last-writer-wins away each other's changes — e.g. drop an action_log
    entry (issue #115). ``build(doc)`` returns the new document to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(_state_lock_path(path)):
        doc = read_state_file(path)
        new_doc = build(doc)
        write_state_file(path, new_doc)
    return new_doc


def _now_iso() -> str:
    """Current time as a timezone-aware ISO 8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


def _merge_ads(
    existing: CampaignSnapshot, incoming: CampaignSnapshot
) -> CampaignSnapshot:
    """Inherit ``ads`` from ``existing`` when ``incoming`` did not supply it.

    An upsert replaces the whole snapshot, but ad-level state has no input on
    most calls: the standard flows fetch ads only for ACTIVE campaigns (an
    API-cost guard), so the first upsert after a campaign is paused — exactly
    when "what were its ads doing?" matters most — would otherwise reset
    ``ads`` from the last known statuses back to ``None`` ("never fetched"),
    silently destroying the audit trail #468 exists to create.

    Only ``None`` ("not supplied") inherits. An empty tuple is a real
    observation ("fetched, this campaign has no ads") and overwrites, as does
    any non-empty list. Each :class:`AdState` carries its own ``as_of``, so an
    inherited entry stays honestly dated rather than passing for fresh.
    """
    if incoming.ads is not None or existing.ads is None:
        return incoming
    return replace(incoming, ads=existing.ads)


def _upsert_into(
    campaigns: tuple[CampaignSnapshot, ...],
    campaign: CampaignSnapshot,
    *,
    inherit_ads: bool = False,
) -> tuple[CampaignSnapshot, ...]:
    """Return ``campaigns`` with ``campaign`` replacing any same-id entry
    (or appended when new), preserving order.

    ``inherit_ads`` enables the :func:`_merge_ads` carry-over and is safe ONLY
    for a platform-scoped list. The legacy v1 flat list matches on
    ``campaign_id`` alone — Google and Meta ids are independent namespaces, so
    a collision there matches two unrelated campaigns — and inheriting across
    that blind match would attach one account's ads to another's campaign.
    The flat list therefore keeps plain full-replace semantics.
    """
    result: list[CampaignSnapshot] = []
    found = False
    for c in campaigns:
        if c.campaign_id == campaign.campaign_id:
            result.append(_merge_ads(c, campaign) if inherit_ads else campaign)
            found = True
        else:
            result.append(c)
    if not found:
        result.append(campaign)
    return tuple(result)


def _platform_base(
    platforms: dict[str, PlatformState], platform: str, account_id: str
) -> PlatformState:
    """The :class:`PlatformState` a targeted write should build on.

    The existing entry when there is one, otherwise a minimal new entry
    carrying only ``account_id`` — whose remaining fields take the dataclass's
    own defaults rather than a hand-written copy of them.

    Every caller then uses ``dataclasses.replace`` to change ONLY the fields it
    actually has input for, which is what makes preservation structural: a
    field added to :class:`PlatformState` later is carried across by every
    mutator without any of them being edited. Enumerating instead is how a
    campaign upsert once wiped the dashboard rollups, and how a metrics write
    once wiped the #342 conversion override — both silent, because a reset
    field is indistinguishable from one that was never set.

    One exception, and it is about identity rather than preservation:
    re-pointing a key at a DIFFERENT ad account (allowed when no other key
    holds it) drops ``not_collected``. That note names a collection failure
    for the account the entry used to describe; carried over, it would be
    rendered as a fact about the account that replaced it. Everything else
    survives the re-point exactly as before — the rollups are figures the
    next sync overwrites, while a note nothing overwrites would simply be
    wrong from here on. An entry with no ``account_id`` claims no account, so
    learning one identifies the entry rather than replacing it and the note
    stays; ``act_`` spellings of one account are one account (the same
    reading :func:`~mureo.context.platform_accounts.account_ids_match` gives
    every other surface).
    """
    existing = platforms.get(platform)
    if existing is None:
        return PlatformState(account_id=account_id)
    if (
        existing.not_collected is not None
        and normalize_account_id(existing.account_id)
        and normalize_account_id(account_id)
        and not account_ids_match(existing.account_id, account_id)
    ):
        return replace(existing, not_collected=None)
    return existing


def _stamp_fetched_at(rollup: Any, written_at: str) -> Any:
    """Return ``rollup`` carrying a ``fetched_at``, stamping ``written_at``
    when it has none (#637).

    ``fetched_at`` is what the dashboard's staleness marker reads. It used to
    be a field every writer had to remember, and the writer that reaches it
    most often is an agent following a skill — so "optional" became "usually
    missing" and most cards read *"update time unknown"*, which is worse than
    a stamp accurate to the minute. The server knows when the write happened;
    for the supported path (pull the figures, then write them) that IS when
    they were pulled.

    Two things it deliberately does not do:

    - **A supplied value is relayed verbatim**, including one that is not a
      timestamp at all: a caller writing a historical window is stating
      something the server cannot re-derive, and the read side keeps an
      uninterpretable string on purpose (see
      :func:`mureo.web.report_document._platform_freshness`) because it is the only
      clue to the writer that produced it.
    - **An empty rollup is left empty.** An advisory bridge keeps an entry
      with no figures; a lone ``fetched_at`` would turn "no synced metrics"
      into a rollup claiming a collection time for numbers that do not exist.

    Supplied means **a non-blank string**, not merely the key being present.
    ``None``, ``""`` and whitespace state no time at all — they are the
    absence, spelled out — and the tool's ``totals`` schema is a free-form
    object with no per-property types, so a model filling in an optional
    field explicitly sends exactly those. Honouring the key alone would let
    the writer this whole change is about reproduce the symptom it removes:
    the read side ignores a value that is not a string, so the card would go
    on saying *"update time unknown"*. Nothing is lost either way — a blank
    is not a clue to anything, unlike ``"today"``, which is kept.

    Anything that is not a dict is passed through untouched — this is a write
    helper, not a validator.
    """
    if not isinstance(rollup, dict) or not rollup:
        return rollup
    supplied = rollup.get("fetched_at")
    if isinstance(supplied, str) and supplied.strip():
        return rollup
    return {**rollup, "fetched_at": written_at}


def upsert_campaign(
    path: Path,
    campaign: CampaignSnapshot,
    *,
    platform: str,
    account_id: str,
) -> StateDocument:
    """Upsert a campaign into STATE.json under its platform.

    Writes the v2 ``platforms[platform]`` section — the schema the
    dashboard reads — with the **required** ``account_id`` and the
    campaign, and stamps ``last_synced_at`` to now. Without these the
    document is schema-incomplete and the client renders as "not yet
    bootstrapped" / inactive even though campaigns exist.

    The legacy v1 flat ``campaigns`` list is updated in lockstep so
    readers still on the v1 shape keep working (the field is retained
    for backward compatibility — see :class:`StateDocument`). That list
    is platform-blind, so it takes the snapshot as given; ad-level state
    is inherited only in the platform-scoped v2 section (see
    :func:`_upsert_into`).

    Args:
        path: STATE.json location.
        campaign: The campaign snapshot to insert or update.
        platform: Platform key the campaign belongs to (e.g.
            ``"google_ads"``, ``"meta_ads"``) — the ``platforms`` dict key.
        account_id: The platform account id (Google ``customer_id`` /
            Meta ``act_*``). Always written onto the platform entry so a
            per-account override is never silently dropped.

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

    def _build(doc: StateDocument) -> StateDocument:
        # v1 flat list — preserved for backward compatibility.
        flat_campaigns = _upsert_into(doc.campaigns, campaign)

        # v2 per-platform — the shape the dashboard reads. Ensure the platform
        # entry exists, carries the (required) account_id, and holds the
        # campaign.
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)
        base = _platform_base(platforms, platform, account_id)
        # Everything a campaign upsert has no input for — the platform-level
        # rollup (totals / metrics_period / periods) and the #342 conversion
        # override — is carried over by ``replace``. Each was a real
        # regression when it was enumerated and forgotten: an upsert wiped the
        # dashboard KPIs, and another wiped the account's conversion setting.
        platforms[platform] = replace(
            base,
            account_id=account_id,
            campaigns=_upsert_into(
                base.campaigns,
                campaign,
                # Platform-scoped: a same-id match here IS the same campaign,
                # so carrying its ad-level state over is safe (#468).
                inherit_ads=True,
            ),
        )

        # ``reports`` and ``action_log`` are likewise untouched by construction;
        # dropping the former used to wipe the stored report summaries the
        # dashboard renders on every upsert that followed a report write.
        return replace(
            doc,
            last_synced_at=_now_iso(),
            campaigns=flat_campaigns,
            platforms=platforms,
        )

    return _locked_state_mutation(path, _build)


def append_action_log(
    path: Path, entry: ActionLogEntry, *, join_active_batch: bool = True
) -> StateDocument:
    """Append an action log entry to STATE.json.

    Reads the current state, appends the entry, and writes back atomically.

    This is the single choke point every recording path funnels through —
    native status toggles, ``mureo_state_action_log_append``, and the
    bridged / plugin promotion — so it is also where the workspace's open batch
    is stamped onto the entry (#549). Doing it here, inside the lock, is what
    makes batch membership platform-agnostic: no tool schema, no per-platform
    recorder and no plugin ABI has to know the batch exists.

    An explicit ``batch_id`` on the entry is **validated, not trusted**: it must
    name a batch that exists and is still open
    (:func:`mureo.context.batch.ensure_joinable`). Checking here rather than in
    the MCP handler means no caller — handler, library user or future recorder
    — can invent a change set or grow one after it was closed and reported.

    Args:
        path: STATE.json location.
        entry: The entry to append. An explicit ``batch_id`` on it wins over the
            open batch (see :func:`mureo.context.batch.stamp_batch`) once it has
            passed :func:`~mureo.context.batch.ensure_joinable`.
        join_active_batch: Pass ``False`` for an entry that must NOT become a
            member of whatever batch is open — the rollback executor's
            ``rollback_of`` record does, because a reversal joining the batch
            it reverses would grow that batch and make the next plan offer the
            reversals as things still to reverse.

    Returns:
        Updated StateDocument

    Raises:
        BatchError: ``entry.batch_id`` names no declared batch, or names one
            that has already been closed.
        ValueError: ``entry.display_title`` / ``entry.display_summary`` is over
            its bound (#706). Refused, never truncated, and refused BEFORE the
            file is opened — so a rejected append leaves the log exactly as it
            was and the caller still holds the sentence it can shorten.
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context`` ->
    # ``state_store`` -> this module, so a module-level import would be a cycle
    # (the same reason ``metrics_windows`` and ``report_summary`` are imported
    # inside their callers below).
    from mureo.core.display_contract import validate_action_log_display

    # Outside the lock: the dashboard's one-line rendering is a WRITE rule, so
    # this is the moment to refuse it. An entry already on disk is history and
    # is read back exactly as it is.
    validate_action_log_display(
        display_title=entry.display_title,
        display_summary=entry.display_summary,
    )

    def _build(doc: StateDocument) -> StateDocument:
        if entry.batch_id is not None:
            ensure_joinable(doc, entry.batch_id)
        stamped = stamp_batch(entry, active_batch(doc)) if join_active_batch else entry
        # ``last_synced_at`` is deliberately NOT re-stamped: appending an action
        # is not a sync, and the dashboard's "Synced N ago" freshness must keep
        # reflecting the last real sync. Every other section is carried over by
        # ``replace`` — including ``batches`` (#549), which is why this no longer
        # enumerates the untouched fields by hand.
        return replace(doc, action_log=(*doc.action_log, stamped))

    return _locked_state_mutation(path, _build)


def begin_batch(path: Path, *, label: str) -> BatchRecord:
    """Open a batch: every later ``action_log`` entry joins it until it is ended.

    Args:
        path: STATE.json location.
        label: What this change set is, in the operator's words. Required and
            non-blank — an unlabelled batch id is a string the operator has to
            decode later, which is the reconstruction work #549 removes.

    Returns:
        The opened :class:`~mureo.context.models.BatchRecord`.

    Raises:
        BatchError: A batch is already open. Refused rather than nested: two
            change sets merged into one cannot be told apart afterwards.
        ValueError: ``label`` is blank.
    """
    cleaned = label.strip() if isinstance(label, str) else ""
    if not cleaned:
        raise ValueError("label must be a non-empty string")

    opened: list[BatchRecord] = []

    def _build(doc: StateDocument) -> StateDocument:
        open_batch = active_batch(doc)
        if open_batch is not None:
            raise BatchError(
                f"Batch {open_batch.batch_id!r} ({open_batch.label!r}) is already "
                "open; end it before beginning another."
            )
        started_at = _now_iso()
        batch = BatchRecord(
            batch_id=new_batch_id(started_at),
            label=cleaned,
            started_at=started_at,
        )
        opened.append(batch)
        return replace(doc, batches=(*doc.batches, batch))

    _locked_state_mutation(path, _build)
    return opened[0]


def end_batch(path: Path) -> tuple[BatchRecord, tuple[int, ...]]:
    """Close the open batch and report exactly what it collected.

    The record is kept (with ``ended_at`` set) rather than deleted, so the
    batch's label still answers "what was batch-2026… ?" long after the pass.

    Returns:
        The closed :class:`~mureo.context.models.BatchRecord` and the
        ``action_log`` indices of its members — the checklist that replaces
        reconstructing the change set by hand.

    Raises:
        BatchError: No batch is open.
    """
    closed: list[tuple[BatchRecord, tuple[int, ...]]] = []

    def _build(doc: StateDocument) -> StateDocument:
        open_batch = active_batch(doc)
        if open_batch is None:
            raise BatchError("No batch is open.")
        ended = replace(open_batch, ended_at=_now_iso())
        closed.append(
            (ended, tuple(index for index, _ in batch_members(doc, ended.batch_id)))
        )
        return replace(
            doc,
            batches=tuple(
                ended if b.batch_id == ended.batch_id else b for b in doc.batches
            ),
        )

    _locked_state_mutation(path, _build)
    return closed[0]


def set_report(path: Path, report: str, summary: dict[str, Any]) -> StateDocument:
    """Persist a structured analysis ``summary`` into STATE.json ``reports``.

    Merges ``reports[report] = summary`` into the document's ``reports``
    section (a ``{<kind>: <summary>}`` map the read-only dashboard renders),
    re-stamps ``last_synced_at``, and writes back atomically. Other report
    keys and the rest of the document (campaigns, platforms, action_log) are
    preserved. When ``reports`` is ``None`` (old STATE.json), it starts from
    ``{}`` — so the call is backward compatible.

    The kind is not checked here. The vocabulary
    (:data:`~mureo.core.report_kinds.REPORT_KINDS`) is enforced on the MCP
    tool over this function, as an ``enum`` the schema layer applies before
    any handler runs — the same place the caller reads what the kinds ARE.
    A document that arrived from elsewhere carrying some other key keeps it:
    strict on write, tolerant on read (#671).

    The summary must state its structure (#662): the narrative is bounded and
    a headline figure is a number — see
    :func:`~mureo.core.report_summary.validate_report_summary` for the rule
    and for what is deliberately left free. Validation happens BEFORE the
    lock is taken, so a refused write leaves the document byte-for-byte
    untouched, and it is a WRITE rule only: a paragraph already on disk still
    reads back verbatim and survives a write of a sibling report kind.

    Args:
        path: STATE.json location.
        report: Report kind key — see
            :data:`~mureo.core.report_kinds.REPORT_KINDS`.
        summary: The free-form summary object to store under that key.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: if ``summary`` states a narrative over the bound, or a
            headline figure that is not a number.
    """
    from mureo.core.report_summary import validate_report_summary

    validate_report_summary(summary)

    def _build(doc: StateDocument) -> StateDocument:
        # Start from a shallow copy of the existing reports (or {} when the
        # document predates the reports section) so sibling report kinds are
        # preserved rather than wiped.
        reports = dict(doc.reports) if doc.reports else {}
        reports[report] = summary
        return replace(doc, last_synced_at=_now_iso(), reports=reports)

    return _locked_state_mutation(path, _build)


def set_display(
    path: Path,
    *,
    nav_message: str | None = None,
    highlights: list[dict[str, Any]] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    breakdown: dict[str, Any] | None = None,
    stated_values: list[dict[str, Any]] | None = None,
) -> StateDocument:
    """Write the client's ``display`` contract — what the DASHBOARD reads (#706).

    STATE.json is the agent's working memory and is prose-heavy by design.
    This section is the other audience: the operator's screen. Every value
    here is bounded and every vocabulary closed, and an over-long or
    off-vocabulary write is **refused, never truncated** — see
    :func:`~mureo.core.display_contract.validate_display_contract` for the
    rule and for what is deliberately not checked.

    **The whole section is replaced by exactly what this call states.** An
    omitted section is written as absent, not inherited.

    That is the same granularity :func:`set_report` keeps, read one level up.
    ``set_report``'s unit is a report KIND — what one skill writes in one pass
    — and it preserves the other kinds because they are other reports, written
    by other passes, about other questions. The display contract's unit is the
    whole contract, because that is what one pass produces: the nav line, the
    highlights, the proposals, the tables and the chips all describe ONE
    client at ONE moment, off one set of figures. Merging them per section
    would put last week's highlights beside today's nav line with nothing on
    screen able to say they came from different runs — and a screen that
    silently mixes two moments is worse than one that shows a section fewer.

    So a call that states nothing CLEARS the contract, and the document loses
    the key entirely rather than keeping an empty one a reader could render.

    **One writer per run, and it owns the whole screen.** The contract is
    written by exactly ONE skill per run — the one producing that run's
    report — and that skill states every section it wants shown. Two skills
    writing different sections in the same run is outside the design: the
    second call does not merge into the first, it replaces it, so what
    survives is whatever ran last. There is deliberately no partial-update
    entry point and no per-section lock beyond the document lock every
    mutator here shares; concurrent partial writers would need a merge policy,
    and any merge policy re-creates the mixed-moment screen this whole-section
    replacement exists to prevent. If a future run needs two writers, they
    compose their sections BEFORE calling, not by calling twice.

    Everything else in the document — platforms, campaigns, ``action_log``,
    ``reports``, ``batches`` — is untouched by construction (``replace``).
    ``last_synced_at`` IS re-stamped, as :func:`set_report` re-stamps it: this
    write happens in the same pass as the report it summarises, so treating
    the two differently would make the card's age depend on which of them ran
    last.

    Validation happens BEFORE the lock is taken, so a refused write leaves
    STATE.json byte-for-byte untouched, and it is a WRITE rule only: a
    contract already on disk is read back exactly as it is (see
    :func:`mureo.context.display_codec.parse_display_contract`).

    Args:
        path: STATE.json location.
        nav_message: The one operator-facing line (運用ナビ).
        highlights: Up to three ``{tone, text}`` chips.
        proposals: ``{title, body, status, date}`` rows.
        breakdown: ``{campaigns: [...], adgroups: [...]}`` — rows of
            ``{name, spend, mcpa, target_cpa, state, note}``.
        stated_values: ``{label, value}`` chips, the value a raw number or a
            short string.

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: a value is over its bound, names a value outside a closed
            vocabulary, or states prose where a figure belongs.
    """
    # Imported lazily — the ``mureo.core`` -> ``mureo.context.state`` cycle
    # again (see ``set_platform_metrics``).
    from mureo.core.display_contract import validate_display_contract

    supplied: dict[str, Any] = {
        key: value
        for key, value in (
            ("nav_message", nav_message),
            ("highlights", highlights),
            ("proposals", proposals),
            ("breakdown", breakdown),
            ("stated_values", stated_values),
        )
        if value is not None
    }
    # Outside the lock and before the file is opened: a rejected write must
    # leave the document exactly as it was, including its ``last_synced_at``.
    validate_display_contract(supplied)
    contract = parse_display_contract(supplied)

    def _build(doc: StateDocument) -> StateDocument:
        # One field, by ``replace``: every other section is carried over.
        return replace(doc, last_synced_at=_now_iso(), display=contract)

    return _locked_state_mutation(path, _build)


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

    ``fetched_at`` — the freshness the dashboard reads — is stamped with the
    write time on every rollup this call SUPPLIES without one (``totals`` and
    each ``periods`` bucket), and a rollup this call merely preserves is never
    re-stamped. A value the caller did supply is relayed verbatim. See
    :func:`_stamp_fetched_at` (#637).

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

    Re-stamps ``last_synced_at`` and writes back atomically under the state
    lock. Other document sections (root campaigns, action_log, reports) are
    preserved.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
        totals: The single-rollup totals to set (or ``None`` to preserve).
        metrics_period: The window ``totals`` covers — a canonical window (or
            ``None`` to preserve).
        periods: Per-window rollups to merge in, keyed by canonical window
            (or ``None`` to preserve).

    Returns:
        The updated :class:`StateDocument`.

    Raises:
        ValueError: ``metrics_period`` or a ``periods`` key is not a
            canonical metrics window (#659), or ``platform`` is not a usable
            platform key, names no
            platform mureo can resolve (a built-in, an installed plugin's
            platform, or a ``plugin:<dist>:<provider>`` key — checked on
            CREATE only, so an existing entry stays writable), or the write
            would create a SECOND key for an account another key already
            holds (see
            :func:`mureo.context.platform_guards.guard_platform_entry_write`).
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context`` ->
    # ``state_store`` -> this module, so a module-level import would be a
    # cycle (same reason as ``platform_guards``).
    from mureo.core.metrics_windows import reject_non_canonical_metrics_window

    # Outside the lock and before the file is opened: a rejected write must
    # leave the document exactly as it was, including its ``last_synced_at``.
    if metrics_period is not None:
        reject_non_canonical_metrics_window(metrics_period, field="metrics_period")
    for window in periods or {}:
        reject_non_canonical_metrics_window(window, field="periods key")

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)

        base = _platform_base(platforms, platform, account_id)
        # One clock read for the whole write, so a rollup's age and the
        # document's cannot disagree by a hair and read as two events.
        written_at = _now_iso()

        merged_periods: dict[str, dict[str, Any]] | None
        if periods is not None:
            merged = dict(base.periods) if base.periods else {}
            # Only the buckets THIS write supplies are stamped; the ones it
            # merely preserves keep the age they were collected at.
            merged.update(
                {
                    window: _stamp_fetched_at(bucket, written_at)
                    for window, bucket in periods.items()
                }
            )
            merged_periods = merged
        else:
            merged_periods = base.periods

        # ``campaigns`` and the #342 conversion override have no input on a
        # metrics write and are carried over by ``replace``; a ``None``
        # argument means "leave as it was", not "clear it".
        platforms[platform] = replace(
            base,
            account_id=account_id,
            totals=(
                _stamp_fetched_at(totals, written_at)
                if totals is not None
                else base.totals
            ),
            metrics_period=(
                metrics_period if metrics_period is not None else base.metrics_period
            ),
            periods=merged_periods,
        )

        return replace(doc, last_synced_at=written_at, platforms=platforms)

    return _locked_state_mutation(path, _build)


def _reject_unusable_daily_keys(days: dict[str, Any]) -> None:
    """Refuse a ``daily`` key that is not one COMPLETE PAST day (#690).

    Two checks, both about shape rather than vocabulary — unlike a metrics
    window, the set of valid dates cannot be enumerated:

    - the key is ``YYYY-MM-DD`` (:data:`~mureo.context.models.
      DAILY_DATE_KEY_PATTERN`) **and parses as a real date**. The pattern
      alone is not validation: ``2026-02-30`` matches it perfectly, and a key
      no reader can place on a timeline is a bucket nothing will ever show.
    - the day is over. Today is still being spent into, so a rollup for it is
      a partial day — the same reason
      :mod:`mureo.analysis.delivery_collapse` drops everything at or after
      ``as_of`` before comparing anything. Stored, it would be a false low
      forever, because nothing revisits a day already in the map. A future
      date is refused with it: it is not a day anyone collected.

    "Today" is the HOST's local day (:func:`mureo.core.clock.server_now`), the
    same clock the skills anchor their dates to — judging a local date against
    UTC would move the boundary by a day for half the world.

    Raises on the FIRST bad key, before the file is opened and before the lock
    is taken, so a refused call leaves the document exactly as it was —
    ``last_synced_at`` included — and the caller still holds every figure and
    can re-file it. A half-written call is what makes that impossible.
    """
    # Imported lazily: ``mureo.core.__init__`` pulls in ``runtime_context`` ->
    # ``state_store`` -> this module, so a module-level import would be a
    # cycle (same reason as ``metrics_windows`` above).
    from mureo.core import clock

    today = clock.server_now().date()
    for key in days:
        if not isinstance(key, str) or not _DAILY_DATE_KEY_RE.match(key):
            raise ValueError(
                f"daily key {key!r} is not a date: use YYYY-MM-DD, one key per "
                "calendar day"
            )
        try:
            day = date.fromisoformat(key)
        except ValueError:
            raise ValueError(
                f"daily key {key!r} is not a date that exists (YYYY-MM-DD)"
            ) from None
        if day >= today:
            raise ValueError(
                f"daily key {key!r} is not a complete day yet (server today is "
                f"{today.isoformat()}): write a day only once it is over, so a "
                "part-spent day is never stored as the whole of it"
            )


def _capped_daily(daily: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """``daily`` trimmed to the most recent :data:`DAILY_RETENTION_DAYS` days.

    Order is preserved (the merge appends, exactly as ``periods`` does); only
    the oldest date keys beyond the cap are dropped.

    A key this module could not have written — anything that is not
    ``YYYY-MM-DD`` — is **kept, and does not count towards the cap**. The write
    guard refuses such a key today, but one already on disk is still figures
    somebody collected, filed under a name mureo cannot date; a retention
    sweep has no way to tell whether it is the oldest entry or the newest, and
    deleting data to tidy a vocabulary is the asymmetry the read side already
    refuses to make (see :func:`~mureo.web.report_document._available_periods`).
    """
    dated = [key for key in daily if _DAILY_DATE_KEY_RE.match(key)]
    if len(dated) <= DAILY_RETENTION_DAYS:
        return daily
    dropped = set(sorted(dated)[:-DAILY_RETENTION_DAYS])
    return {key: value for key, value in daily.items() if key not in dropped}


def set_platform_daily(
    path: Path,
    platform: str,
    account_id: str,
    *,
    days: dict[str, dict[str, Any]],
) -> StateDocument:
    """Merge day-grain rollups into a platform's ``daily`` history (#690).

    ``periods`` carries one rollup per WINDOW and every collection overwrites
    it, so the figure it replaces is gone and nothing in the document can
    answer "was yesterday better than the day before?". This map is the half
    that accumulates: one totals-shaped bucket per ``YYYY-MM-DD``, the same
    canonical metric vocabulary, merged PER DATE KEY.

    Merge semantics:

    - a date this call supplies REPLACES that day's bucket wholesale, so
      re-writing a day is idempotent rather than additive;
    - every OTHER date already stored is preserved — that is the whole point;
    - the platform's campaigns, rollups, conversion override and
      ``not_collected`` note, and every other platform, are untouched.

    **A day nobody collected is not written.** Nothing here fills a gap with
    zeros: "not collected" and "collected, and the answer was zero" are
    different facts (the distinction ``not_collected`` exists for), and a
    zero-filled day is indistinguishable from an account that stopped
    spending — while also poisoning the median the collapse detector baselines
    against. Supply only the days you actually pulled; readers render a gap as
    a gap.

    **Only complete past days are accepted.** Each key must be ``YYYY-MM-DD``,
    must be a date that exists, and must be before the host's today — see
    :func:`_reject_unusable_daily_keys`, which runs before the file is opened.

    ``fetched_at`` is stamped with the write time on every bucket this call
    supplies without one, and a day it merely preserves is never re-stamped —
    the same contract :func:`set_platform_metrics` keeps (#637).

    The stored history is capped at :data:`DAILY_RETENTION_DAYS` days on every
    write (see :func:`_capped_daily`).

    Re-stamps ``last_synced_at`` and writes back atomically under the state
    lock.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>:<provider>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
        days: Day-grain rollups keyed ``YYYY-MM-DD``. An empty map writes no
            day and leaves the stored history alone.

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
    # Outside the lock and before the file is opened: a rejected write must
    # leave the document exactly as it was, including its ``last_synced_at``.
    _reject_unusable_daily_keys(days)

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)

        base = _platform_base(platforms, platform, account_id)
        # One clock read for the whole write, so a bucket's age and the
        # document's cannot disagree by a hair and read as two events.
        written_at = _now_iso()

        merged = dict(base.daily) if base.daily else {}
        # Only the days THIS write supplies are stamped; the ones it merely
        # preserves keep the age they were collected at.
        merged.update(
            {day: _stamp_fetched_at(bucket, written_at) for day, bucket in days.items()}
        )

        # Every other field has no input on a daily write and is carried over
        # by ``replace``.
        platforms[platform] = replace(
            base, account_id=account_id, daily=_capped_daily(merged)
        )

        return replace(doc, last_synced_at=written_at, platforms=platforms)

    return _locked_state_mutation(path, _build)


def set_platform_not_collected(
    path: Path,
    platform: str,
    account_id: str,
    *,
    reason: str | None,
) -> StateDocument:
    """Record — or clear — why a platform's figures were not refreshed (#638).

    Writes ``platforms[platform].not_collected`` as
    ``{"attempted_at": <now>, "reason": <reason>}``, or removes it when
    ``reason`` is ``None`` / blank. ``attempted_at`` is stamped SERVER-side
    (the #460 rule): the caller states what happened, never when.

    **This says the numbers were not UPDATED. It does not say they are
    wrong.** ``totals`` / ``periods`` are left exactly as they were — they are
    still the last figures that were truly collected — because writing 0 for a
    collection that failed would be the lie
    :func:`set_platform_metrics`' merge semantics deliberately avoid. What was
    missing was the other half: with the failure unrecorded, "not collected"
    and "collected, and the answer was zero" are the same document, and an
    operator watching a card whose figures had not moved for eleven days could
    not tell a stopped account from a stopped collector.

    **A clear must be said, and whoever collects says it.** Every other
    targeted mutator here treats an omitted argument as "leave it alone", so
    nothing else in this module can retire the note: a successful collection
    writes a rollup, and one window's rollup landing does not prove the
    platform-level collection recovered. The collector therefore calls this
    with ``reason=None`` on success, in the same pass. A note that outlives
    its failure is permanently stale information stated with confidence —
    exactly what this field exists to remove.

    The dashboard does not TRUST that contract, and should not have to: it
    drops a note any later collection has already answered (see
    :func:`mureo.web.report_document._platform_not_collected`). Clearing it here is
    still what keeps the document itself honest — the read rule only decides
    what is shown.

    ``last_synced_at`` is deliberately NOT re-stamped, for the same reason
    :func:`append_action_log` does not: a collection that FAILED is not a
    sync, and re-stamping it would make the card report itself just-synced on
    the strength of nothing having been collected.

    The platform's campaigns, rollups and conversion override — and every
    OTHER platform — are preserved; the entry is created (carrying
    ``account_id``) when absent, because a platform that failed on its very
    first collection is precisely the one an operator cannot otherwise
    diagnose. The write is atomic, under the state lock.

    Args:
        path: STATE.json location.
        platform: Platform key (``"google_ads"`` / ``"meta_ads"`` /
            ``"plugin:<dist>:<provider>"`` / …) — the ``platforms`` dict key.
        account_id: The platform account id, always written onto the entry.
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
    cleaned = reason.strip() if isinstance(reason, str) else ""

    def _build(doc: StateDocument) -> StateDocument:
        platforms = dict(doc.platforms) if doc.platforms else {}
        guard_platform_entry_write(platforms, platform, account_id)
        note = (
            {
                "attempted_at": _now_iso(),
                "reason": cleaned[:NOT_COLLECTED_REASON_MAX_CHARS],
            }
            if cleaned
            else None
        )
        # Campaigns, rollups and the conversion override have no input on this
        # call and are carried over by ``replace``: it declares one fact.
        platforms[platform] = replace(
            _platform_base(platforms, platform, account_id),
            account_id=account_id,
            not_collected=note,
        )
        return replace(doc, platforms=platforms)

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

    **The counterpart of :func:`set_platform_not_collected`, one level up —
    and it deliberately takes neither a platform key nor an ``account_id``.**
    Those two are exactly what a collection that died before reaching any
    platform failed to resolve, so requiring them to record "resolving them
    failed" is circular. Writing the note onto every existing platform entry
    would state a different fact ("Meta failed, and Google failed, and…"),
    and a workspace that has NEVER been collected — the case this exists for
    — has no entry to write onto: inventing one with a blank ``account_id``
    creates the poisoned entry #533/#536 removed.

    **Nothing else in the document is touched.** ``platforms`` is left
    exactly as it was, including any per-platform note: the two record
    different failures and neither implies the other. The stored figures are
    still the last ones truly collected — this says they were not UPDATED,
    never that they are wrong.

    **A clear must be said, and whoever collects says it.** Call this with
    ``reason=None`` on the next successful collection, in the same pass;
    every targeted mutator in this module treats an omitted argument as
    "leave it alone", so nothing else retires the note.

    The read side does not TRUST that contract and should not have to: it
    drops a note that any later collection anywhere in the document has
    already answered (see
    :func:`mureo.web.report_document._workspace_not_collected`), the same
    evidence-based retirement #638 gave the per-platform note.

    ``last_synced_at`` is deliberately NOT re-stamped, for the same reason
    :func:`set_platform_not_collected` does not: a collection that FAILED is
    not a sync, and re-stamping it would report the document as just-synced
    on the strength of nothing having been collected.

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
    cleaned = reason.strip() if isinstance(reason, str) else ""

    def _build(doc: StateDocument) -> StateDocument:
        note = (
            {
                "attempted_at": _now_iso(),
                "reason": cleaned[:NOT_COLLECTED_REASON_MAX_CHARS],
            }
            if cleaned
            else None
        )
        # One field, by ``replace``: everything else — platforms and their own
        # notes, campaigns, action_log, reports, batches — is carried over.
        return replace(doc, workspace_not_collected=note)

    return _locked_state_mutation(path, _build)


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
    cleaned: tuple[str, ...] | None = None
    if conversion_action_types:
        cleaned = tuple(
            str(x).strip()
            for x in conversion_action_types
            if isinstance(x, str) and x.strip()
        )
        cleaned = cleaned or None

    def _build(doc: StateDocument) -> StateDocument:
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

    return _locked_state_mutation(path, _build)


def get_campaign(doc: StateDocument, campaign_id: str) -> CampaignSnapshot | None:
    """Search for a campaign by campaign_id."""
    for c in doc.campaigns:
        if c.campaign_id == campaign_id:
            return c
    return None


__all__ = [
    # Re-exported from mureo.context.state_codec / .conversion_overrides so
    # every existing ``from mureo.context.state import ...`` keeps working
    # (#538). Listed here, not merely imported, so the re-export is explicit
    # under mypy's ``no_implicit_reexport``.
    "load_conversion_action_types",
    "parse_state",
    "render_state",
    # Defined here.
    "append_action_log",
    "begin_batch",
    "end_batch",
    "get_campaign",
    "read_state_file",
    "set_conversion_action_types",
    "set_display",
    "set_platform_metrics",
    "set_platform_not_collected",
    "set_report",
    "set_workspace_not_collected",
    "upsert_campaign",
    "write_state_file",
]
