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
:func:`list_report_clients` and the per-client STATE.json resolution are
defined against a small capability seam on the active ``StateStore``:

- ``list_clients()`` → the selectable clients (an Agency backend plugs in
  here). Absent (OSS default) → exactly one client for the active
  workspace.
- ``state_store_for_client(slug)`` → the ``StateStore`` for a non-default
  client (Agency backend). Absent → the active store is used regardless of
  the requested client, so a single-account OSS install works today and an
  Agency backend can plug in multiple clients later without touching this
  module's call sites.

Both seams are read defensively (``getattr`` + ``callable``); a store that
does not advertise them keeps the standalone single-workspace behaviour.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.context.state import read_state_file
from mureo.core.runtime_context import get_runtime_context

if TYPE_CHECKING:
    from mureo.context.models import (
        ActionLogEntry,
        PlatformState,
        StateDocument,
    )
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

__all__ = [
    "build_report_summary",
    "list_report_clients",
    "platform_display_name",
]

# How many of the most-recent ``action_log`` entries the summary surfaces.
# The dashboard shows a short activity feed, not the full history.
_RECENT_ACTIONS_LIMIT = 20

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

# Built-in platform key → human display name. Plugin keys (``plugin:<dist>``)
# and any unknown key are resolved by :func:`platform_display_name` instead.
_BUILTIN_DISPLAY_NAMES: dict[str, str] = {
    "google_ads": "Google Ads",
    "meta_ads": "Meta Ads",
    "search_console": "Search Console",
    "ga4": "GA4",
    # Hosted-connector platform (no native mureo tools; added as a Claude.ai
    # connector). Skills write its snapshots under this key — give it a friendly
    # dashboard label instead of falling back to the raw "tiktok_ads".
    "tiktok_ads": "TikTok Ads",
}

_PLUGIN_PREFIX = "plugin:"

# Canonical period tokens in dashboard-toggle order. The default view is the
# most recent day (``YESTERDAY``) — daily-check runs every day, so the prior
# day's state is what an operator checks first; ``LAST_30_DAYS`` is the
# trend window written by sync-state. Windows not listed here sort after
# these, alphabetically (see :func:`_available_periods`).
_PERIOD_ORDER: tuple[str, ...] = (
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_30_DAYS",
)


def platform_display_name(key: str) -> str:
    """Resolve a human label for a ``platforms`` key.

    Rules:
    - A built-in key (``google_ads`` / ``meta_ads`` / ``search_console`` /
      ``ga4``) → its registered name.
    - A ``plugin:<dist>`` key → a humanized label from ``<dist>``: drop a
      leading ``mureo-`` and a trailing ``-bridge``, title-case the
      hyphen-separated words, and suffix ``" (plugin)"`` (e.g.
      ``plugin:mureo-logly-bridge`` → ``"Logly (plugin)"``,
      ``plugin:acme-ads`` → ``"Acme Ads (plugin)"``).
    - Anything else (an unknown built-in-shaped key) → the key itself, so
      the dashboard never renders a blank label.
    """
    builtin = _BUILTIN_DISPLAY_NAMES.get(key)
    if builtin is not None:
        return builtin
    if key.startswith(_PLUGIN_PREFIX):
        dist = key[len(_PLUGIN_PREFIX) :]
        label = _humanize_dist(dist)
        return f"{label} (plugin)" if label else key
    return key


def _humanize_dist(dist: str) -> str:
    """Turn a distribution name into a Title-Cased label.

    ``mureo-logly-bridge`` → ``Logly``; ``acme-ads`` → ``Acme Ads``. A
    leading ``mureo-`` and a trailing ``-bridge`` are mureo packaging
    conventions, not part of the brand, so they are stripped. An empty
    result (e.g. ``plugin:`` with nothing after) yields ``""`` and the
    caller falls back to the raw key.
    """
    name = dist.strip()
    if name.startswith("mureo-"):
        name = name[len("mureo-") :]
    if name.endswith("-bridge"):
        name = name[: -len("-bridge")]
    words = [w for w in name.replace("_", "-").split("-") if w]
    return " ".join(word.capitalize() for word in words)


# ---------------------------------------------------------------------------
# Multi-account (Agency) seam
# ---------------------------------------------------------------------------


def list_report_clients() -> list[dict[str, Any]]:
    """Enumerate the selectable reporting clients.

    Agency seam: when the active ``StateStore`` exposes a callable
    ``list_clients()`` (a multi-account backend), its result is normalized
    and returned. Otherwise (the OSS default single-workspace store) this
    returns exactly one entry describing the active workspace:
    ``[{"slug": <id>, "name": <id>, "active": True}]``.

    Never raises — a broken/odd ``list_clients`` degrades to the single
    active-workspace entry so the dashboard's client picker always renders.
    """
    store = _active_state_store()
    rows = _agency_list_clients(store)
    if rows is not None:
        return rows
    slug = _active_workspace_id(store)
    return [{"slug": slug, "name": slug, "active": True}]


def _agency_list_clients(store: StateStore) -> list[dict[str, Any]] | None:
    """Call the store's ``list_clients`` seam, normalized, or ``None``.

    ``None`` means "no Agency seam" (use the single-workspace fallback). A
    seam that raises or returns a non-list is treated as absent — a backend
    bug must not blank out the picker.
    """
    fn = getattr(store, "list_clients", None)
    if not callable(fn):
        return None
    try:
        raw = fn()
    except Exception:  # noqa: BLE001 — a backend bug must not 500 the picker
        logger.exception("state store list_clients() failed; using single workspace")
        return None
    if not isinstance(raw, list):
        return None
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        if not slug:
            continue
        rows.append(
            {
                "slug": slug,
                "name": str(item.get("name", slug)),
                "active": bool(item.get("active", False)),
            }
        )
    return rows or None


def _active_state_store() -> StateStore:
    """The active workspace's ``StateStore`` (default single-workspace).

    Tolerant of a misconfigured ``mureo.runtime_context_factory`` (>1 entry
    point raises ``RuntimeContextFactoryError``): fall back to the default
    filesystem store so the Reports endpoints keep their documented "never
    raises" contract instead of dropping the connection with no envelope.
    """
    try:
        return get_runtime_context().state_store
    except Exception:  # noqa: BLE001 — a broken factory must not 500 the reports view
        logger.exception("runtime context factory failed; using default state store")
        from mureo.core.state_store import FilesystemStateStore

        return FilesystemStateStore()


def _active_workspace_id(store: StateStore) -> str:
    """A stable, non-empty client slug for the active workspace.

    Prefers the runtime context's opaque ``workspace_id`` (``"default"`` for
    OSS), falling back to a literal so the slug is never blank.
    """
    try:
        workspace_id = getattr(get_runtime_context(), "workspace_id", "")
    except Exception:  # noqa: BLE001 — mirror _active_state_store's tolerance
        workspace_id = ""
    slug = str(workspace_id).strip()
    return slug or "default"


def _state_store_for_client(client: str | None) -> StateStore:
    """Resolve the ``StateStore`` to read for ``client``.

    Agency seam: when a non-default ``client`` is requested and the active
    store exposes a callable ``state_store_for_client(slug)``, its result is
    used. Otherwise the active store is returned — so OSS (single workspace)
    ignores the ``client`` argument by construction. A seam that raises or
    returns a non-store falls back to the active store rather than 500-ing.
    """
    active = _active_state_store()
    if not client:
        return active
    if client == _active_workspace_id(active):
        return active
    fn = getattr(active, "state_store_for_client", None)
    if not callable(fn):
        return active
    try:
        resolved = fn(client)
    except Exception:  # noqa: BLE001 — backend bug must not 500 the summary
        logger.exception("state_store_for_client(%r) failed; using active", client)
        return active
    # Duck-typed: a usable store exposes read_state(). Anything else is
    # ignored so a malformed return can't break the read below.
    return resolved if hasattr(resolved, "read_state") else active


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def build_report_summary(
    *, client: str | None = None, period: str | None = None
) -> dict[str, Any]:
    """Build a JSON-safe, secret-free report summary from STATE.json.

    Resolves the STATE.json for ``client`` (the active workspace by default;
    a non-default client via the Agency seam — see
    :func:`_state_store_for_client`), reads it, and shapes:

    - ``platforms``: one row per key in ``platforms`` — built-in AND
      ``plugin:<dist>`` — each ``{key, display_name, totals, metrics_period,
      campaign_count}``. A platform without metrics for the resolved window
      still appears (``totals`` ``None`` / ``metrics_period`` ``None``).
    - ``periods``: the windows that have data SOMEWHERE in this document
      (union over every platform's per-period rollups plus its legacy
      single-rollup window), in canonical order — so the dashboard renders a
      period toggle only for windows it can actually show.
    - ``last_synced_at``: the document's sync timestamp (or ``None``).
    - ``recent_actions``: the last :data:`_RECENT_ACTIONS_LIMIT` action-log
      entries, each ``{timestamp, action, platform, campaign_id, summary,
      observation_due}`` — NO ``command`` / ``metrics_at_action`` /
      ``reversible_params`` (those can carry secrets or noise).
    - ``reports``: the daily/weekly/goal summaries verbatim (or ``None``).
    - ``client`` / ``period``: echoed back so the caller knows what was read.

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
    store = _state_store_for_client(client)
    doc = _read_state_safe(store)
    resolved_client = client or _active_workspace_id(_active_state_store())

    return {
        "client": resolved_client,
        "period": period,
        "periods": _available_periods(doc),
        "last_synced_at": doc.last_synced_at if doc is not None else None,
        "platforms": _build_platforms(doc, period),
        "recent_actions": _build_recent_actions(doc),
        # ``reports`` is relayed verbatim. Unlike ``totals`` / ``recent_actions``
        # it is NOT whitelisted: it holds the structured analysis summary written
        # ONLY by mureo's own analysis skills via ``mureo_state_report_set``
        # ({generated_at, period, kpis, flags, narrative}). It is trusted-writer
        # content, not arbitrary input — do not start echoing untrusted data
        # here without a whitelist.
        "reports": doc.reports if doc is not None else None,
    }


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
    :func:`_state_store_for_client` — exposes. A store without one cannot be
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
    return {
        "key": key,
        "display_name": platform_display_name(key),
        "totals": totals,
        "metrics_period": metrics_period,
        "campaign_count": len(state.campaigns),
    }


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


def _available_periods(doc: StateDocument | None) -> list[str]:
    """Windows with data anywhere in the document, in canonical order.

    Union over every platform's ``periods`` keys plus its legacy
    ``metrics_period`` (so a legacy single-rollup window still advertises
    itself). Sorted with :data:`_PERIOD_ORDER` first, unknown windows
    appended alphabetically — gives the dashboard a stable toggle order.
    """
    if doc is None or not doc.platforms:
        return []
    found: set[str] = set()
    for state in doc.platforms.values():
        if state.periods:
            found.update(k for k in state.periods if isinstance(k, str) and k)
        if state.metrics_period:
            found.add(state.metrics_period)
    known = [p for p in _PERIOD_ORDER if p in found]
    extra = sorted(p for p in found if p not in _PERIOD_ORDER)
    return known + extra


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
