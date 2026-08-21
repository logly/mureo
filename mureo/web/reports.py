"""Pure data builders for the read-only reporting dashboard.

The configure-UI's (future) reporting dashboard renders KPIs sourced
ENTIRELY from STATE.json — no live API call, no agent run. This module
is the data layer: it reads the active workspace's STATE.json through the
runtime context's :class:`~mureo.core.state_store.StateStore` and shapes a
JSON-safe, **secret-free** summary the ``/api/reports/*`` handlers relay
verbatim. There is no HTTP here (the handlers own that), and nothing in
this module mutates state — it is read-only.

Platform-agnostic by design
----------------------------
``build_report_summary`` enumerates EVERY key in ``platforms`` — built-in
(``google_ads`` / ``meta_ads`` / ``search_console`` / ``ga4``) AND plugin
bridges keyed ``plugin:<dist>`` (the same convention promoted into
``action_log`` by ``_mureo-shared`` → *Plugin platforms*). A platform with
no synced metrics still appears (totals empty), so a bridge shows up as
"advisory / no synced metrics" and the frontend decides how to render it.

Multi-account (Agency) seam
---------------------------
Which clients exist, and which ``StateStore`` to read for one of them,
live in :mod:`mureo.web.report_clients` — the report builders here take
the resolved store and do not decide any of that. The seam's names
(:func:`list_report_clients`, :func:`state_store_for_client`,
:func:`report_clients_payload`, :func:`set_report_client_archived`,
:class:`ClientArchiveError`) are re-exported below so existing importers
keep working; the runtime-context resolution seam that tests patch lives
in that module (``mureo.web.report_clients.get_runtime_context``).

Conflicts and freshness (#533 / #535)
-------------------------------------
Two facts about the document that the frontend cannot work out for itself,
and which this module therefore resolves and puts on the wire:

- ``platform_conflicts`` — reasons this document's platform rows must NOT be
  added together. Grouping happens here because the rows deliberately carry
  no ``account_id`` (see :func:`_platform_row`), so the browser has nothing
  to join on and is given nothing to join on.
- each row's ``freshness`` — how old THAT platform's figures are, judged
  against the window they cover. The document-level ``last_synced_at`` is
  re-stamped on any platform write, so it cannot answer this.

The multi-client triage layer (#651)
------------------------------------
Everything the Reports grid needs to say "this client, today" is already
above — conflicts, freshness, ``not_collected`` — and needs no server-side
addition to be ranked; the browser aggregates it (``reports_triage.js``).
The one exception is how many ``action_log`` observations are past their
review date, which ``recent_actions`` cannot answer: it is capped, and it
carries none of the fields that close an observation. So
``observations_due`` is resolved here.

It rides on the summary **only when the active store declares the Agency
client seam** (:func:`~mureo.web.report_clients.agency_client_seam_present`,
which reads the declaration and invokes nothing — this runs once per client
card per render). A single workspace has no second client to triage against,
so the layer is omitted rather than degraded to one row — and omitted means
the payload keeps the exact keys, in the exact order, it had before this
existed.

Where the pieces live (#678)
----------------------------

This module is the assembly: it resolves the store, walks the document once
and shapes the payload. The questions that payload is made of were moved out
verbatim when this file passed a thousand lines, and are re-exported from
here so every existing importer keeps resolving:

  :mod:`mureo.web.report_document` — everything asked OF the document: the
    tolerant read, the two conflict findings, freshness, the windows it
    carries, its ``not_collected`` notes, and the canonical-key filter that
    decides what may go on the wire.
  :mod:`mureo.web.report_labels` — the platform key to display-name resolver,
    which :data:`~mureo.web.report_document.CONFLICT_UNRECOGNIZED_KEY` is
    defined in terms of.

The import direction is one-way — ``reports`` to ``report_document`` to
``report_labels`` — so there is no cycle to reason about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# "Which observations are still owed a review" — the rule that already
# defines ``mureo_state_get(action_log="pending")``, read here rather than
# restated (#651).
from mureo.context.observations import due_observation_dates
from mureo.core import clock

# The client seam. Imported (not re-implemented) and re-exported through
# ``__all__`` so ``from mureo.web.reports import state_store_for_client``
# keeps resolving for every existing caller.
from mureo.web.report_clients import (
    ClientArchiveError,
    _active_state_store,
    _active_workspace_id,
    agency_client_seam_present,
    list_report_clients,
    report_clients_payload,
    set_report_client_archived,
    state_store_for_client,
)

# The document layer (#678). Most of these are called below; ``_PERIOD_ORDER``
# and ``_PERIOD_LENGTH_DAYS`` are re-export only — the window vocabulary moved
# with the functions that read it, and the suite reads both tables off THIS
# module. Hence the blanket noqa rather than a per-name one.
from mureo.web.report_document import (  # noqa: F401
    _PERIOD_LENGTH_DAYS,
    _PERIOD_ORDER,
    CONFLICT_DUPLICATE_ACCOUNT,
    CONFLICT_UNRECOGNIZED_KEY,
    _available_periods,
    _build_platform_conflicts,
    _daily_delta,
    _daily_series,
    _non_canonical_periods,
    _period_totals,
    _platform_freshness,
    _platform_not_collected,
    _read_state_safe,
    _safe_totals,
    _workspace_not_collected,
)

# The display-name resolver (#678). ``platform_display_name`` is called below
# and is in ``__all__``; the two tables behind it are re-export only, read off
# this module by the suite.
from mureo.web.report_labels import (  # noqa: F401
    _BUILTIN_DISPLAY_NAMES,
    _OFFICIAL_BRIDGE_DISPLAY_NAMES,
    platform_display_name,
)

if TYPE_CHECKING:
    from mureo.context.models import (
        ActionLogEntry,
        PlatformState,
        StateDocument,
    )

__all__ = [
    "CONFLICT_DUPLICATE_ACCOUNT",
    "CONFLICT_UNRECOGNIZED_KEY",
    "ClientArchiveError",
    "build_report_summary",
    "list_report_clients",
    "report_clients_payload",
    "set_report_client_archived",
    "state_store_for_client",
    "platform_display_name",
]


# How many of the most-recent ``action_log`` entries the summary surfaces.
# The dashboard shows a short activity feed, not the full history.
_RECENT_ACTIONS_LIMIT = 20


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def build_report_summary(
    *, client: str | None = None, period: str | None = None
) -> dict[str, Any]:
    """Build a JSON-safe, secret-free report summary from STATE.json.

    Resolves the STATE.json for ``client`` (the active workspace by default;
    a non-default client via the Agency seam — see
    :func:`state_store_for_client`), reads it, and shapes:

    - ``platforms``: one row per key in ``platforms`` — built-in AND
      ``plugin:<dist>`` — each ``{key, display_name, totals, metrics_period,
      campaign_count, freshness, not_collected}``. A platform without metrics
      for the resolved window still appears (``totals`` ``None`` /
      ``metrics_period`` ``None``). ``not_collected`` is why that platform's
      figures were not refreshed (#638), or ``None`` — see
      :func:`_safe_not_collected`. ``daily`` is the last
      :data:`~mureo.web.report_document._DAILY_SERIES_DAYS` days of day-grain
      history, ascending and with its gaps intact, and ``daily_delta`` is how
      the last day moved against the day before it — ``None`` when the two
      most recent stored days are not calendar neighbours, because a
      comparison across a collection gap is not a day-over-day change (#690).
    - ``workspace_not_collected``: why the WHOLE workspace could not be
      collected (#661), or ``None`` — a collection that died before any
      platform was reached. A separate key from a row's ``not_collected``
      because it is a separate fact, and retired on separate evidence; see
      :func:`_workspace_not_collected`.
    - ``platform_conflicts``: reasons these rows must not be added together
      (#533) — see :func:`_build_platform_conflicts`. Always a list, empty
      when the document is healthy, and it carries NO ad account ids.
    - ``periods``: the windows that have data SOMEWHERE in this document
      (union over every platform's per-period rollups plus its legacy
      single-rollup window), in canonical order — so the dashboard renders a
      period toggle only for windows it can actually show.
    - ``non_canonical_periods``: which of those windows are not windows
      mureo defines (#659) — see :func:`_non_canonical_periods`. Always a
      list, empty when the document only carries canonical windows.
    - ``last_synced_at``: the document's sync timestamp (or ``None``).
    - ``recent_actions``: the last :data:`_RECENT_ACTIONS_LIMIT` action-log
      entries, each ``{timestamp, action, platform, campaign_id, summary,
      observation_due}`` — NO ``command`` / ``metrics_at_action`` /
      ``reversible_params`` (those can carry secrets or noise).
    - ``reports``: the stored report summaries verbatim, keyed by kind (or
      ``None``).
    - ``client`` / ``period``: echoed back so the caller knows what was read.
    - ``observations_due``: **only where the Agency client seam is
      declared** (#651) — ``{count, oldest_due}`` for the logged changes
      whose review date has passed. Absent, not zeroed, on a
      single-workspace install; see :func:`_build_observations_due`.
    - ``server_today``: **only where the Agency client seam is declared** —
      the host's local date (``YYYY-MM-DD``) from
      :func:`~mureo.core.clock.server_now`, the same clock that stamps an
      action-log ``timestamp``. It is what lets the multi-client index say
      which logged actions happened *today* without the browser guessing in
      its own timezone.

    Period selection
    ----------------
    - ``period is None`` (the default) → backward-compatible passthrough:
      each platform's stored single rollup (``totals`` / ``metrics_period``)
      is returned as-is. No existing caller regresses.
    - ``period`` set (e.g. ``"YESTERDAY"`` / ``"LAST_30_DAYS"``) → each
      platform's totals are resolved FOR THAT WINDOW from its ``periods``
      rollups, falling back to the legacy single rollup ONLY when its stored
      ``metrics_period`` matches the requested window (never mislabels a
      different window's totals). A platform with no data for the window gets
      ``totals``/``metrics_period`` ``None``.

    Never raises on a missing/empty/malformed STATE.json — it returns an
    empty-but-valid summary instead.
    """
    store = state_store_for_client(client)
    doc = _read_state_safe(store)
    resolved_client = client or _active_workspace_id(_active_state_store())

    summary: dict[str, Any] = {
        "client": resolved_client,
        "period": period,
        "periods": _available_periods(doc),
        "non_canonical_periods": _non_canonical_periods(doc),
        "last_synced_at": doc.last_synced_at if doc is not None else None,
        # A document-level fact, so it sits beside the document-level sync
        # time and above the platform rows — never inside one (#661).
        "workspace_not_collected": _workspace_not_collected(doc),
        "platforms": _build_platforms(doc, period),
        "platform_conflicts": _build_platform_conflicts(doc),
        "recent_actions": _build_recent_actions(doc),
        # ``reports`` is relayed verbatim. Unlike ``totals`` / ``recent_actions``
        # it is NOT whitelisted: it holds the structured analysis summary written
        # ONLY by mureo's own analysis skills via ``mureo_state_report_set``
        # ({generated_at, period, kpis, flags, narrative}). It is trusted-writer
        # content, not arbitrary input — do not start echoing untrusted data
        # here without a whitelist.
        "reports": doc.reports if doc is not None else None,
    }
    # Appended LAST and only where the Agency client seam is declared
    # (#651), so a single-workspace summary keeps the exact keys, in the
    # exact order, it had before the triage layer existed. The predicate
    # reads a declaration and calls nothing — this function runs once per
    # client card per render. See :func:`_build_observations_due`.
    if agency_client_seam_present():
        summary["observations_due"] = _build_observations_due(doc)
        # What day it is on the machine that stamped the action log.
        #
        # The index renders a "what mureo did today" feed off
        # ``recent_actions``, and the browser cannot decide what "today" is:
        # a ``timestamp`` is stamped server-side (#460) from
        # :func:`~mureo.core.clock.server_now`, the host's local wall clock,
        # so a browser drawing the boundary in ITS timezone would list
        # yesterday's work as today's for any operator not sitting in the
        # host's zone. The date therefore comes from the same clock that
        # wrote the timestamps, and the browser only ever compares two
        # strings that came from that one source.
        #
        # A clock read, not a registry read — the cost this function guards
        # against (see :func:`_build_observations_due`) is asking the client
        # registry once per card, and this asks nothing.
        summary["server_today"] = clock.server_now().date().isoformat()
    return summary


def _build_observations_due(doc: StateDocument | None) -> dict[str, Any]:
    """How many of this client's logged changes are past their review date.

    ``{"count": <int>, "oldest_due": <ISO date | None>}`` — the one triage
    fact the browser cannot work out for itself, for two independent
    reasons. ``recent_actions`` is capped at
    :data:`_RECENT_ACTIONS_LIMIT`, so a count taken from it under-reports
    exactly the operator this layer is for; and it deliberately carries no
    ``rollback_of`` / ``evaluation_of``, so a browser-side count would keep
    asking for reviews that were done. Both are answered here, over the
    whole document, by the rule that already defines "pending" for
    ``mureo_state_get`` (:func:`~mureo.context.observations.
    due_observation_dates`).

    ``oldest_due`` is re-rendered from the date mureo itself parsed, never
    relayed verbatim: an ``observation_due`` is writer-supplied text, and an
    entry whose value is not a date is not counted at all — it cannot be
    judged against today, and unknown is not a verdict (the position
    :func:`_platform_freshness` takes on an unparseable ``fetched_at``).

    "Today" comes from :func:`mureo.core.clock.server_now` — the host's
    local wall clock, the same one the skills anchor an ``observation_due``
    to when they write it. Judging a local date against UTC would move the
    boundary by a day for half the world, on a window measured in weeks.
    """
    due = (
        due_observation_dates(doc.action_log, clock.server_now().date())
        if doc is not None and doc.action_log
        else []
    )
    return {
        "count": len(due),
        "oldest_due": min(due).isoformat() if due else None,
    }


def _build_platforms(
    doc: StateDocument | None, period: str | None
) -> list[dict[str, Any]]:
    """One JSON-safe row per ``platforms`` key (insertion order preserved)."""
    if doc is None or not doc.platforms:
        return []
    return [_platform_row(key, state, period) for key, state in doc.platforms.items()]


def _platform_row(key: str, state: PlatformState, period: str | None) -> dict[str, Any]:
    """Shape a single platform's dashboard row (no account ids / secrets).

    ``period is None`` returns the stored single rollup (legacy passthrough);
    a set ``period`` resolves the totals for that window (see
    :func:`_period_totals`).

    ``account_id`` stays off this row (a test pins the omission): identity is
    resolved server-side into ``platform_conflicts`` instead, so the browser
    is never handed an ad account id to join on. ``freshness`` and
    ``not_collected`` ride ALONGSIDE the five original fields — see
    :func:`_platform_freshness` and :func:`_platform_not_collected`.

    ``not_collected`` is resolved from the WHOLE platform entry rather than
    from the window on screen: a note is about the platform, and the
    collection that retires it may have written any window (see
    :func:`_platform_not_collected`).

    ``daily`` / ``daily_delta`` (#690) ride alongside the window rollup and
    are NOT resolved from ``period``: a day-grain history is not a window, so
    selecting one must not replace or hide it. Both are always present — an
    empty list and a ``None`` delta where there is no history — so the
    frontend reads one shape for every row. See :func:`_daily_series` and
    :func:`_daily_delta`.
    """
    if period is None:
        totals = _safe_totals(state.totals)
        metrics_period = state.metrics_period
    else:
        totals = _period_totals(state, period)
        # Only label the row with the window once it actually carries totals,
        # so the frontend can tell "no data for this window" from "this data
        # covers <window>".
        metrics_period = period if totals is not None else None
    daily = _daily_series(state)
    return {
        "key": key,
        "display_name": platform_display_name(key),
        "totals": totals,
        "metrics_period": metrics_period,
        "campaign_count": len(state.campaigns),
        "freshness": _platform_freshness(totals, metrics_period),
        "not_collected": _platform_not_collected(state),
        "daily": daily,
        "daily_delta": _daily_delta(daily),
    }


def _build_recent_actions(doc: StateDocument | None) -> list[dict[str, Any]]:
    """Last N action-log entries as secret-free rows (most recent last)."""
    if doc is None or not doc.action_log:
        return []
    recent = doc.action_log[-_RECENT_ACTIONS_LIMIT:]
    return [_action_row(entry) for entry in recent]


def _action_row(entry: ActionLogEntry) -> dict[str, Any]:
    """Shape a single action-log entry — only display-safe fields.

    Deliberately omits ``command`` (may carry tokens/flags),
    ``metrics_at_action`` and ``reversible_params`` (noise / internal). Only
    timestamp / action / platform / campaign_id / summary / observation_due
    reach the dashboard.
    """
    return {
        "timestamp": entry.timestamp,
        "action": entry.action,
        "platform": entry.platform,
        "campaign_id": entry.campaign_id,
        "summary": entry.summary,
        "observation_due": entry.observation_due,
    }
