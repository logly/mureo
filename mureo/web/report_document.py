"""What mureo can say about one stored document (#678).

Lifted verbatim out of :mod:`mureo.web.reports`, which had grown past the
point where one reader could hold it. Nothing here changed in the move — same
functions, same bodies, same order.

:mod:`mureo.web.reports` assembles the summary payload. This module answers
the questions that payload is made of, each about the STATE.json document
alone:

  - **Read it at all.** ``store.read_state()`` validates strictly; a document
    with one hand-authored campaign entry would otherwise blank out a view
    whose platforms and periods are perfectly renderable. So a failed strict
    read retries tolerantly against the raw file before the view degrades to
    empty. A read-only dashboard degrades; it never 500s.
  - **May these rows be added together?** Two conflict findings (#533),
    deliberately never merged into one warning: they are different facts and
    the operator's next move differs. See :data:`CONFLICT_DUPLICATE_ACCOUNT`
    and :data:`CONFLICT_UNRECOGNIZED_KEY`.
  - **Is this figure still worth showing?** Freshness (#535) against the
    window the figure claims to cover, plus the grace that keeps one missed
    sync from painting a healthy account red.
  - **Which windows does this document actually carry**, and which of them are
    outside the canonical vocabulary.
  - **Why did the figures not move?** The stored ``not_collected`` note (#638),
    per platform and for the workspace, truncated to the same bound the write
    side enforces.
  - **What is safe to put on the wire?** ``totals`` is copied key by key
    against a canonical allow-list, so a stray or secret-shaped key written
    into a document can never reach the dashboard.

Not one figure is computed here that the document does not already state, and
nothing in this module mutates anything — it is read-only, exactly as
``reports.py`` is.

The only sibling this module reads is :mod:`mureo.web.report_labels`, and only
because :data:`CONFLICT_UNRECOGNIZED_KEY` is *defined* as "the key the display
resolver could make nothing of". Deciding recognisability a second time here
is how this layer and the grid it describes would start disagreeing.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

# The stored shapes' own bounds, so the read side and the write helpers agree
# on them: the length a collection failure's reason is truncated to (#638),
# and what a day-grain history key looks like (#690).
from mureo.context.display_codec import display_contract_to_dict
from mureo.context.models import (
    DAILY_DATE_KEY_PATTERN,
    NOT_COLLECTED_REASON_MAX_CHARS,
)
from mureo.context.platform_accounts import (
    duplicate_account_entries,
    normalize_account_id,
)
from mureo.context.state import read_state_file
from mureo.core.metrics_windows import (
    CANONICAL_METRICS_WINDOWS,
    is_canonical_metrics_window,
)
from mureo.web.report_labels import platform_display_name

if TYPE_CHECKING:
    from mureo.context.models import PlatformState, StateDocument
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)


# ``platform_conflicts[].kind`` — the wire vocabulary for "do not add these
# rows together" (#533). TWO findings, deliberately never merged into one
# warning: they are different facts and an operator's next move differs.
CONFLICT_DUPLICATE_ACCOUNT = "duplicate_account"
"""Two or more keys resolve to ONE ad account.

Established by the shared join in :mod:`mureo.context.platform_accounts`.
The consequence is present-tense and certain: any total over these rows
counts that account's spend / conversions / CPA more than once, right now.
"""

CONFLICT_UNRECOGNIZED_KEY = "unrecognized_key"
"""A key no mureo surface can resolve to a platform.

The account join CANNOT find this case. The shape actually reported from the
field had ``account_id = ""`` on one of the two entries, and
``account_ids_match("", "")`` is ``False`` by design (an unknown id is not a
value), so :func:`~mureo.context.platform_accounts.duplicate_account_entries`
deliberately does not report that pair. This second, independent signal is
what catches it: an entry whose identity cannot be established at all, and
which may therefore be a duplicate of a canonical one.

The condition itself is narrower than that motivating case: it tests the
KEY only, so it also fires on a key mureo cannot label whose ``account_id``
resolves perfectly well. Both belong here — the operator has to look at the
key either way — but they are not the same finding, so the row carries
``account_known`` and the dashboard says the milder thing (mureo cannot
tell which *platform* this is) when the account is in fact known. Claiming
the ad account is unidentifiable there would contradict the
``duplicate_account`` row sitting on the same key (#606).

Recognition is delegated to :func:`platform_display_name`, which returns the
key unchanged exactly when it can make nothing of it — that is already how
mureo answers "is this key recognisable", and asking the dashboard's own
resolver means this can never drift from what the dashboard renders. The
alternative, an alias table mapping arbitrary keys onto platforms, would be a
guess.

That resolver now reads the **same** installed-plugin enumeration the write
guard does (:func:`~mureo.context.platform_guards.installed_platform_names`,
#631), so this signal can no longer fire on a key mureo itself accepted on
write. Until it did, a bare provider name — ``logly_ads_context``, the LOGLY
bridge's real platform name — was accepted by the guard, reported ``Clean``
by ``mureo repair platform-key``, and flagged here, all on one machine at one
moment. An operator who learns this fires on healthy state stops reading it,
which costs more than the finding is worth.
"""

# The canonical metric keys a platform's ``totals`` may carry (the shared
# vocabulary documented in ``_mureo-strategy`` → *Performance Metrics*). The
# summary copies only these keys so a future stray/secret-shaped key written
# into ``totals`` can never reach the dashboard. ``result_indicator`` is
# Meta-only but harmless to allow for every platform.
_CANONICAL_TOTAL_KEYS: tuple[str, ...] = (
    "spend",
    "impressions",
    "clicks",
    "conversions",
    "cpa",
    "ctr",
    "result_indicator",
    "period",
    "fetched_at",
)

# Canonical period tokens in dashboard-toggle order. The default view is the
# most recent day (``YESTERDAY``) — daily-check runs every day, so the prior
# day's state is what an operator checks first; ``LAST_30_DAYS`` is the
# trend window written by sync-state. Windows not listed here sort after
# these, alphabetically (see :func:`_available_periods`).
#
# The table itself lives in ``mureo.core.metrics_windows`` (#659), for the
# same reason the display names do: the WRITE guard has to refuse exactly the
# windows this view cannot render, and ``mureo.context`` cannot import
# ``mureo.web``. Two copies would be free to drift, and the drift is the bug
# — a writer accepting a window nothing here reads.
_PERIOD_ORDER: tuple[str, ...] = tuple(CANONICAL_METRICS_WINDOWS)

# Canonical window → the length of that window in days. The stale threshold
# is derived from this rather than written down as a per-window magic number,
# so the rationale below is the only thing to check when a window is added.
_PERIOD_LENGTH_DAYS: dict[str, int] = dict(CANONICAL_METRICS_WINDOWS)

_DAILY_SERIES_DAYS = 7
"""How many days of ``daily`` history a platform row carries (#690).

A week, because that is the span a day-over-day question is asked inside —
"is today's dip the weekend again?" — and because a row is a summary, not the
archive. The document keeps more (see
:data:`~mureo.context.state.DAILY_RETENTION_DAYS`); nothing is lost by the
row showing less.
"""

_DAILY_DATE_KEY_RE = re.compile(DAILY_DATE_KEY_PATTERN)

_DAILY_DELTA_KEYS: tuple[str, ...] = tuple(
    key
    for key in _CANONICAL_TOTAL_KEYS
    if key not in {"result_indicator", "period", "fetched_at"}
)
"""The canonical keys a day-over-day delta is computed for.

Derived from :data:`_CANONICAL_TOTAL_KEYS` rather than written out again, so
a metric added to the vocabulary is deltaed without a second list being
remembered. The three excluded keys are the non-numeric ones — subtracting
two ``fetched_at`` strings, or two ``result_indicator`` labels, is not a
change in performance.
"""

_STALE_GRACE_DAYS = 1
"""Slack added to a window's own length before its figure is called stale.

Absorbs one missed daily sync run and the platforms' own reporting lag
(conversions backfill for a day or two is normal), so a single hiccup does
not paint a healthy account red.
"""

_STALE_AFTER_DAYS_DEFAULT = max(_PERIOD_LENGTH_DAYS.values()) + _STALE_GRACE_DAYS
"""Threshold for a window whose length mureo does not know.

The most forgiving known threshold, not the strictest: a window we cannot
reason about must not be flagged on a guess. Crying wolf on figures mureo
cannot judge would teach operators to ignore the marker, which costs more
than the occasional missed stale entry.
"""


def _read_state_safe(store: StateStore) -> StateDocument | None:
    """Read the document, returning ``None`` on any failure.

    ``read_state_file`` already returns a default document for a missing
    file, but a malformed STATE.json raises ``ContextFileError`` and an
    alternate backend could raise anything — the dashboard must degrade to
    an empty summary, never 500.

    When the strict read fails, retry tolerantly against the raw file before
    giving up: ``store.read_state()`` validates the campaign list strictly, so
    one variant / hand-authored campaign entry (e.g. ``name`` instead of
    ``campaign_name``) would otherwise blank out a document whose
    platforms/periods/reports the read-only dashboard can still render.
    """
    try:
        return store.read_state()
    except Exception:  # noqa: BLE001 — read-only view degrades, never raises
        # Expected + handled for a STATE.json with nonconforming entries (e.g. a
        # hand-authored legacy campaign list, or a platform missing account_id):
        # the tolerant retry below renders the view fine. The read-only
        # dashboard re-reads on every poll, so log this at DEBUG — a per-render
        # WARNING + traceback would flood the daemon log on every refresh and
        # read as a failure when it is not.
        logger.debug(
            "strict STATE.json read failed; retrying tolerantly for the "
            "read-only Reports view",
            exc_info=True,
        )
        return _read_state_tolerant(store)


def _read_state_tolerant(store: StateStore) -> StateDocument | None:
    """Re-read ``store``'s STATE.json skipping nonconforming campaign entries.

    Needs the backing file path (``state_path``), which the filesystem store —
    including the Agency per-client stores resolved by
    :func:`state_store_for_client` — exposes. A store without one cannot be
    re-read tolerantly, so the view degrades to an empty summary.
    """
    path = getattr(store, "state_path", None)
    if path is None:
        logger.warning("STATE.json unreadable and no path to retry; empty summary")
        return None
    try:
        return read_state_file(path, strict=False)
    except Exception:  # noqa: BLE001 — last-resort guard; never raise from a read
        logger.exception("tolerant STATE.json read also failed; empty summary")
        return None


# ---------------------------------------------------------------------------
# Conflicts — why these rows must not be added together (#533)
# ---------------------------------------------------------------------------


def _build_platform_conflicts(doc: StateDocument | None) -> list[dict[str, Any]]:
    """Reasons the caller must NOT sum this document's platform rows.

    Each row is ``{"kind": <CONFLICT_*>, "platform_keys": [...],
    "account_known": <bool>}`` — the grouping the browser cannot do, since
    the rows carry no ``account_id``. Nothing here identifies an ad account:
    the keys alone are what an operator needs to find the entries in
    STATE.json, and putting the id on the wire would undo
    :func:`_platform_row`'s omission. ``account_known`` is a presence bit,
    not an id — it says only whether the entries behind the row named an ad
    account mureo could resolve, which is a fact about the *document*, not
    about the account.

    Two independent signals, reported separately (see
    :data:`CONFLICT_DUPLICATE_ACCOUNT` and
    :data:`CONFLICT_UNRECOGNIZED_KEY` for why neither can stand in for the
    other). A single key can legitimately appear in both — and when it does,
    ``account_known`` is what keeps the two notes from asserting opposite
    facts about it (#606). The unrecognised-key condition never inspects the
    id, so without this bit the renderer would have to claim the ad account
    is unidentifiable for an entry the duplicate finding just identified.
    On a duplicate-account row it is always ``True``: that group is built BY
    a resolvable id. It is stated anyway so every row answers the same
    question and no consumer has to special-case a kind.

    **Detection, not repair.** Duplicated entries typically hold different
    *partial* figures, so summing over-counts exactly as much as dropping
    one under-counts. This module never merges, drops or reorders a row; it
    reports, and the operator decides.
    """
    if doc is None or not doc.platforms:
        return []
    rows: list[dict[str, Any]] = [
        {
            "kind": CONFLICT_DUPLICATE_ACCOUNT,
            "platform_keys": list(group.platform_keys),
            "account_known": True,
        }
        for group in duplicate_account_entries(doc.platforms)
    ]
    rows.extend(
        {
            "kind": CONFLICT_UNRECOGNIZED_KEY,
            "platform_keys": [key],
            # Folded the way the account join folds it, so "known here" and
            # "joinable there" can never mean two different things.
            "account_known": bool(normalize_account_id(entry.account_id)),
        }
        for key, entry in doc.platforms.items()
        if platform_display_name(key) == key
    )
    return rows


# ---------------------------------------------------------------------------
# Per-platform freshness (#535)
# ---------------------------------------------------------------------------


def _platform_freshness(
    totals: dict[str, Any] | None, metrics_period: str | None
) -> dict[str, Any]:
    """How old THIS platform's figures are — ``{fetched_at, stale,
    stale_after_days}``.

    ``fetched_at`` is the optional, writer-stamped time the numbers were
    pulled (canonical vocabulary; see ``_mureo-strategy`` → *Performance
    Metrics*). It is read off the rollup actually being rendered, so a
    period-toggled view reports the freshness of the window on screen, and it
    is relayed **verbatim** — including a value that is not a timestamp at
    all. ``stale`` is the authoritative "could this be interpreted?" answer;
    blanking an uninterpretable string would throw away the only clue an
    operator has for finding the writer that produced it, and this module
    reports what the document says rather than silently normalising it.
    Consumers must therefore treat ``fetched_at`` as an opaque string unless
    ``stale`` is not ``None``.

    ``stale`` is deliberately three-valued. ``None`` means **unknown** —
    ``fetched_at`` was absent or unparseable — and that is a real state, not
    an error: the field is optional and writer-dependent, so claiming either
    "fresh" or "stale" would assert something mureo cannot back. Callers
    render it as its own thing.

    Why this exists at all: the only freshness the dashboard used to show was
    the document-level ``last_synced_at``, which the state layer re-stamps on
    ANY platform write — so refreshing one platform made every other
    platform's months-old numbers read as just-synced (#535). That timestamp
    is still correct about what it means; it just cannot answer this
    question.
    """
    stale_after = _stale_after_days(metrics_period)
    fetched_raw = totals.get("fetched_at") if totals else None
    fetched_at = fetched_raw if isinstance(fetched_raw, str) and fetched_raw else None
    parsed = _parse_timestamp(fetched_at)
    stale = (
        None
        if parsed is None
        else parsed < datetime.now(timezone.utc) - timedelta(days=stale_after)
    )
    return {
        "fetched_at": fetched_at,
        "stale": stale,
        "stale_after_days": stale_after,
    }


def _stale_after_days(metrics_period: str | None) -> int:
    """Age at which a figure covering ``metrics_period`` is called stale.

    **The window's own length, plus one grace day.** A figure fetched longer
    ago than the window it summarises no longer overlaps that window at all:
    a ``LAST_30_DAYS`` rollup pulled 31 days ago describes days -31 to -61,
    while today's ``LAST_30_DAYS`` is days 0 to -30 — not one shared day. So
    the figure is not "a bit old", it is about a different period than the
    label claims. :data:`_STALE_GRACE_DAYS` then absorbs one missed daily
    sync and platform reporting lag.

    That is why a ``YESTERDAY`` figure (stale after 2 days) and a
    ``LAST_30_DAYS`` figure (stale after 31) are judged so differently: they
    are not the same claim aging at the same rate.

    An unrecognised window falls back to :data:`_STALE_AFTER_DAYS_DEFAULT`.
    """
    if metrics_period is None:
        return _STALE_AFTER_DAYS_DEFAULT
    length = _PERIOD_LENGTH_DAYS.get(metrics_period)
    if length is None:
        return _STALE_AFTER_DAYS_DEFAULT
    return length + _STALE_GRACE_DAYS


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 ``fetched_at``, or ``None`` if it is not one.

    Tolerates a trailing ``Z`` (Python < 3.11 ``fromisoformat`` does not) and
    treats a naive timestamp as UTC — writers are inconsistent about the
    offset and refusing one would report a real timestamp as unknown.
    A value that is not a timestamp at all yields ``None`` (unknown) rather
    than a guess, and never an exception out of this read-only view.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _period_totals(state: PlatformState, period: str) -> dict[str, Any] | None:
    """Resolve a platform's totals for ``period`` (whitelisted) or ``None``.

    Precedence:
    1. ``periods[period]`` when the key is PRESENT — authoritative, even if
       it whitelists down to nothing (``None``).
    2. else the legacy single rollup (``totals``) ONLY when its stored
       ``metrics_period`` equals ``period`` — never mislabel another window.
    3. else ``None`` (no data for this window).
    """
    if state.periods is not None and period in state.periods:
        bucket = state.periods[period]
        return _safe_totals(bucket if isinstance(bucket, dict) else None)
    if state.metrics_period == period:
        return _safe_totals(state.totals)
    return None


def _daily_series(
    state: PlatformState, days: int = _DAILY_SERIES_DAYS
) -> list[dict[str, Any]]:
    """The platform's most recent ``days`` of day-grain history, ascending.

    ``[{"date": "2026-08-19", "totals": {...}}, …]`` — oldest first, because
    that is the order a trend is read in, and each bucket whitelisted through
    :func:`_safe_totals` exactly as a window rollup is, so a stray or
    secret-shaped key a writer slipped in never reaches the page.

    **Gaps are not filled.** A day the collector missed is simply absent from
    the list; nothing invents a zero for it, because "not collected" and
    "collected, and the answer was zero" are different facts and a
    manufactured zero would show as a day of no spend. The consumer is handed
    a list of the days that exist, never a fixed-length week with holes
    guessed at.

    A key that is not ``YYYY-MM-DD`` is left out — not as a judgement on it,
    but because a timeline is the one thing that cannot be drawn without a
    date. It stays in the document (the write side keeps it too, see
    :func:`~mureo.context.state._capped_daily`); it simply has no position
    here.
    """
    stored = state.daily
    if not isinstance(stored, dict):
        return []
    dated = sorted(
        key for key in stored if isinstance(key, str) and _DAILY_DATE_KEY_RE.match(key)
    )
    return [
        {
            "date": key,
            "totals": _safe_totals(
                stored[key] if isinstance(stored[key], dict) else None
            ),
        }
        for key in dated[-days:]
    ]


def _daily_delta(series: list[dict[str, Any]]) -> dict[str, Any] | None:
    """How the last day moved against the day before it, or ``None`` (#690).

    ``{"from": <date>, "to": <date>, "metrics": {<key>: <after - before>}}``
    — absolute differences only, for every
    :data:`canonical numeric metric <_DAILY_DELTA_KEYS>` BOTH days carry. A
    percentage would need a rule for a zero baseline, and picking one metric
    to be *the* delta would be this layer deciding what an operator cares
    about; the renderer chooses from the ones that are real.

    Resolved here rather than in the browser for the reason every other
    verdict on this page is: it is one rule, and a second copy of it is how
    two surfaces start answering one question differently.

    ``None`` — *unknown*, and unknown is not zero — in every case the
    comparison cannot honestly be made:

    - **fewer than two days.** There is nothing to compare against, and a
      first day is not a change.
    - **a gap between the last two.** They are stored neighbours, not
      calendar neighbours: a Monday and the Thursday before it differ by
      three days of something, and calling that a day-over-day change is a
      made-up comparison presented as a measurement.
    - **no metric the two days share**, or one carried as a non-number. There
      is a difference to state only where both sides are figures.
    """
    if len(series) < 2:
        return None
    previous, latest = series[-2], series[-1]
    try:
        gap = date.fromisoformat(latest["date"]) - date.fromisoformat(previous["date"])
    except ValueError:
        # A key that matched the shape but is not a real date (2026-02-30).
        # The write guard refuses one; a document written elsewhere may not.
        return None
    if gap != timedelta(days=1):
        return None
    before = previous.get("totals") or {}
    after = latest.get("totals") or {}
    metrics = {
        key: after[key] - before[key]
        for key in _DAILY_DELTA_KEYS
        if _is_number(after.get(key)) and _is_number(before.get(key))
    }
    if not metrics:
        return None
    return {"from": previous["date"], "to": latest["date"], "metrics": metrics}


def _is_number(value: Any) -> bool:
    """Is ``value`` a figure that can be subtracted from another one?

    ``bool`` is excluded on purpose: it is an ``int`` in Python, and
    ``True - False`` is a number nobody meant.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _available_periods(doc: StateDocument | None) -> list[str]:
    """Windows with data anywhere in the document, in canonical order.

    Union over every platform's ``periods`` keys plus its legacy
    ``metrics_period`` (so a legacy single-rollup window still advertises
    itself). Sorted with :data:`_PERIOD_ORDER` first, unknown windows
    appended alphabetically — gives the dashboard a stable toggle order.

    **This stays tolerant of a non-canonical window, on purpose (#659).**
    The write path now refuses one (see
    :func:`~mureo.context.state.set_platform_metrics`), but a window already
    on disk was written before that guard existed: real figures, correctly
    collected, filed under a name no view expects. Refusing to READ them
    would delete data mureo did collect in order to tidy a vocabulary. They
    are surfaced separately instead — see :func:`_non_canonical_periods` —
    so an operator can see what accumulated and decide, rather than have the
    dashboard decide silently in either direction.
    """
    if doc is None or not doc.platforms:
        return []
    found = _periods_present(doc)
    known = [p for p in _PERIOD_ORDER if p in found]
    extra = sorted(p for p in found if p not in _PERIOD_ORDER)
    return known + extra


def _periods_present(doc: StateDocument | None) -> set[str]:
    """Every window token this document carries, canonical or not."""
    if doc is None or not doc.platforms:
        return set()
    found: set[str] = set()
    for state in doc.platforms.values():
        if state.periods:
            found.update(k for k in state.periods if isinstance(k, str) and k)
        if state.metrics_period:
            found.add(state.metrics_period)
    return found


def _non_canonical_periods(doc: StateDocument | None) -> list[str]:
    """Windows on disk that are not windows mureo defines (#659).

    Neither silent option is right. Dropping them from the toggle hides
    figures mureo really did collect; keeping them unmarked leaves an
    operator choosing between seven tabs, four of which are one agent's
    ad-hoc phrasings from one session, with no way to tell which window
    their reports are keyed to. So the summary NAMES them, and the operator
    decides.

    Empty (never absent) on a healthy document, like ``platform_conflicts``:
    "nothing accumulated" and "this mureo cannot tell you" must not be the
    same payload.
    """
    return sorted(
        p for p in _periods_present(doc) if not is_canonical_metrics_window(p)
    )


def _platform_not_collected(state: PlatformState) -> dict[str, Any] | None:
    """Why this platform's figures did not move — unless a later collection
    already answered that (#638).

    The stored note is dropped here when ANY of this platform's rollups was
    collected AFTER the failure it describes. Retiring the note is the
    collector's job (see
    :func:`mureo.context.state.set_platform_not_collected`), but the
    correctness of what an operator sees must not depend on a writer
    remembering to do it: nothing in the ``mureo_state_platform_metrics_set``
    path forces a second call, so a document would otherwise carry a fresh
    ``fetched_at`` and a days-old collection failure at once, permanently,
    and the card would render both. Two independent answers to one question,
    with nothing checking them against each other, is the defect this whole
    issue is about — a dashboard stating something untrue and no one able to
    tell.

    Decided ONCE, here, exactly as the staleness verdict is: the browser is
    handed a resolved answer rather than a second copy of the rule.

    Three deliberate asymmetries:

    - **Any window counts.** The note is platform-level, so a daily-check
      writing ``YESTERDAY`` proves the platform was reachable just as well as
      a sync writing ``LAST_30_DAYS``. The comparison uses the NEWEST
      ``fetched_at`` in the entry, not the window the toggle happens to show
      — otherwise switching window could resurrect a retired note.
    - **No collection time, no retirement.** A platform with no ``fetched_at``
      anywhere has never been collected as far as the document knows, and
      that is the case where the note is the only thing the card can say.
    - **Retirement must be PROVED.** An unparseable ``fetched_at`` or a note
      with no ``attempted_at`` (mureo's own writer always stamps one) leaves
      the question open, and open is not retired — the same position
      :func:`_platform_freshness` takes on a value it cannot interpret.
    """
    note = _safe_not_collected(state.not_collected)
    if note is None:
        return None
    attempted = _parse_timestamp(note.get("attempted_at"))
    if attempted is None:
        return note
    collected = _newest_collection(state)
    if collected is not None and collected > attempted:
        return None
    return note


def _workspace_not_collected(doc: StateDocument | None) -> dict[str, Any] | None:
    """Why this WORKSPACE could not be collected — unless a later collection
    already answered that (#661).

    #638's retirement rule, one level up. The stored note is dropped here
    when ANY rollup ANYWHERE in the document was collected after the failure
    it describes: the note is about the workspace, so any platform being
    reached is evidence the collection ran. Retiring it is the collector's
    job (see :func:`mureo.context.state.set_workspace_not_collected`), but
    what an operator SEES must not depend on a writer remembering — a
    document carrying a fresh ``fetched_at`` and a days-old
    "could not be collected" states two contradictory answers to one
    question, and that is the defect this field exists to remove, not to
    reintroduce.

    Put on the wire under its OWN key, never merged into a platform row: the
    acceptance condition is that "this workspace could not be collected" and
    "this workspace's Meta failed" do not render as one sentence. Their
    evidence differs too — a rollup on ANY platform retires this one, while a
    platform's note is retired only by its own rollups — so one is never
    computed from the other.

    The same three limits as the per-platform rule: any window counts, no
    collection time means no retirement, and retirement must be PROVED (an
    unparseable ``fetched_at``, or a note with no ``attempted_at``, leaves
    the question open, and open is not retired).
    """
    if doc is None:
        return None
    note = _safe_not_collected(doc.workspace_not_collected)
    if note is None:
        return None
    attempted = _parse_timestamp(note.get("attempted_at"))
    if attempted is None:
        return note
    collected = _newest_document_collection(doc)
    if collected is not None and collected > attempted:
        return None
    return note


def _display_contract(doc: StateDocument | None) -> dict[str, Any] | None:
    """What the dashboard is allowed to render for this client (#706).

    ``None`` when the document states no contract — and ``None`` is put on
    the wire explicitly, so the frontend reads one shape for every client
    rather than testing whether a key exists.

    No whitelist is applied here, and none is needed: unlike ``totals`` or a
    ``not_collected`` note — free-form objects relayed from whatever wrote
    them — the contract has already been through
    :func:`~mureo.context.display_codec.parse_display_contract` into frozen
    dataclasses with fixed fields. A stray or secret-shaped key a buggy or
    hostile writer slipped into the section did not survive the parse, so
    there is nothing left here to filter. Emitting it is the same function
    the codec writes STATE.json with, so what the dashboard reads and what
    is on disk cannot drift into two shapes.
    """
    if doc is None or not doc.display:
        return None
    return display_contract_to_dict(doc.display)


def _newest_document_collection(doc: StateDocument) -> datetime | None:
    """The most recent ``fetched_at`` across EVERY platform's rollups.

    ``None`` when not one platform in the document carries a usable
    timestamp — which is not "never collected" as a fact about the world,
    only about what the document can show.
    """
    newest: datetime | None = None
    for state in (doc.platforms or {}).values():
        collected = _newest_collection(state)
        if collected is not None and (newest is None or collected > newest):
            newest = collected
    return newest


def _newest_collection(state: PlatformState) -> datetime | None:
    """The most recent ``fetched_at`` across ALL of a platform's rollups.

    ``totals`` and every ``periods`` bucket, because any of them landing is
    evidence the platform was reached. ``None`` when not one of them carries
    a usable timestamp — which is not "never collected" as a fact about the
    world, only about what the document can show.
    """
    rollups: list[Any] = [state.totals]
    if isinstance(state.periods, dict):
        rollups.extend(state.periods.values())
    newest: datetime | None = None
    for rollup in rollups:
        if not isinstance(rollup, dict):
            continue
        raw = rollup.get("fetched_at")
        parsed = _parse_timestamp(raw if isinstance(raw, str) else None)
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
    return newest


def _safe_not_collected(note: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored "why the figures did not move" note, fit to render (#638).

    Returns ``{"attempted_at", "reason"}`` — the two known keys and nothing
    else, the same whitelist discipline :func:`_safe_totals` applies, so a
    stray or secret-shaped key a buggy or hostile writer slipped in can never
    reach the page. ``None`` when there is no usable note, and ``None`` is put
    on the wire explicitly so every row has one shape.

    ``reason`` is truncated to
    :data:`~mureo.context.models.NOT_COLLECTED_REASON_MAX_CHARS`. The write
    helper caps what it stores, but a digest can write the whole document
    without going near it, and a page of raw API JSON in a card is not a
    reason an operator can read.

    A note with no usable ``reason`` is no note: it would say something
    happened and refuse to say what, which is the state this field exists to
    end. ``attempted_at`` is relayed verbatim, like ``fetched_at`` — the only
    clue to the writer that produced an uninterpretable one.
    """
    if not isinstance(note, dict):
        return None
    reason = note.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    attempted_at = note.get("attempted_at")
    return {
        "attempted_at": (
            attempted_at.strip()
            if isinstance(attempted_at, str) and attempted_at.strip()
            else None
        ),
        "reason": reason.strip()[:NOT_COLLECTED_REASON_MAX_CHARS],
    }


def _safe_totals(totals: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy only canonical metric keys out of ``totals`` (or ``None``).

    Whitelisting the keys means a stray/secret-shaped key a buggy or hostile
    writer slipped into ``totals`` can never reach the dashboard. ``None``
    (no rollup) is preserved so the frontend can distinguish "no metrics"
    from "zeroed metrics".
    """
    if not totals:
        return None
    return {k: totals[k] for k in _CANONICAL_TOTAL_KEYS if k in totals} or None
