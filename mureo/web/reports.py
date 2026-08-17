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
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

# The stored shape's own length bound (#638), so the read side and the write
# helper truncate a collection failure's reason to the same length.
from mureo.context.models import NOT_COLLECTED_REASON_MAX_CHARS
from mureo.context.platform_accounts import (
    duplicate_account_entries,
    normalize_account_id,
)

# The plugin half of the platform vocabulary, enumerated ONCE for the whole
# tree (#631). ``web`` -> ``context`` is the direction that already holds
# above; see that module's "One enumeration, two surfaces".
from mureo.context.platform_guards import installed_platform_names
from mureo.context.state import read_state_file
from mureo.core.platform_keys import (
    BUILTIN_PLATFORM_DISPLAY_NAMES,
    PLUGIN_PLATFORM_PREFIX,
    is_plugin_platform_key,
    plugin_platform_parts,
)

# The client seam. Imported (not re-implemented) and re-exported through
# ``__all__`` so ``from mureo.web.reports import state_store_for_client``
# keeps resolving for every existing caller.
from mureo.web.report_clients import (
    ClientArchiveError,
    _active_state_store,
    _active_workspace_id,
    list_report_clients,
    report_clients_payload,
    set_report_client_archived,
    state_store_for_client,
)

if TYPE_CHECKING:
    from mureo.context.models import (
        ActionLogEntry,
        PlatformState,
        StateDocument,
    )
    from mureo.core.state_store import StateStore

logger = logging.getLogger(__name__)

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
#
# The map itself lives in ``mureo.core.platform_keys`` (#609): the write-time
# guard has to accept exactly these keys, and ``mureo.context`` cannot import
# ``mureo.web``. This module keeps the local name because it is the read-side
# resolver's own vocabulary and every reference below reads as one.
_BUILTIN_DISPLAY_NAMES = BUILTIN_PLATFORM_DISPLAY_NAMES

# Distribution → display name for OFFICIAL, in-tree bridges (audit #30).
# These ride the ``plugin:<dist>`` dispatch path to reuse the plugin safety
# layer, but that is an implementation detail: they ship inside mureo, so
# labelling them "(plugin)" would tell the operator a first-party integration
# is third-party. Only in-tree bridges belong here; a genuine third-party
# distribution keeps the suffix.
#
# The key is spelled out rather than imported from
# ``mureo.amazon_ads.provider.AMAZON_SOURCE_DISTRIBUTION`` on purpose: that
# module pulls the bridge (and the mcp SDK types it imports) onto the
# configure-UI import path, which the wizard deliberately avoids. A test pins
# the two strings together.
_OFFICIAL_BRIDGE_DISPLAY_NAMES: dict[str, str] = {
    "mureo-amazon-ads-bridge": "Amazon Ads",
}

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

# Canonical window → the length of that window in days. The stale threshold
# is derived from this rather than written down as a per-window magic number,
# so the rationale below is the only thing to check when a window is added.
_PERIOD_LENGTH_DAYS: dict[str, int] = {
    "YESTERDAY": 1,
    "LAST_7_DAYS": 7,
    "LAST_30_DAYS": 30,
}

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


def platform_display_name(key: str) -> str:
    """Resolve a human label for a ``platforms`` key.

    Rules:
    - A built-in key (``google_ads`` / ``meta_ads`` / ``search_console`` /
      ``ga4``) → its registered name.
    - A plugin key naming an OFFICIAL in-tree bridge → its registered
      name, with no ``" (plugin)"`` suffix (e.g.
      ``plugin:mureo-amazon-ads-bridge`` → ``"Amazon Ads"``). See
      :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES`.
    - A canonical ``plugin:<dist>:<provider>`` key (#537) → a humanized
      label from ``<provider>``, suffixed ``" (plugin)"``: the provider
      names the *platform*, which is what a label is for, while the
      distribution is packaging (e.g.
      ``plugin:mureo-lineyahoo-bridge:yahoo_ads`` → ``"Yahoo Ads
      (plugin)"``, not a mangled ``"Mureo-Lineyahoo-Bridge:Yahoo Ads"``).
      A provider that humanizes to nothing falls back to the distribution.
    - A legacy ``plugin:<dist>`` key → a humanized label from ``<dist>``:
      drop a leading ``mureo-`` and a trailing ``-bridge``, title-case the
      hyphen-separated words, and suffix ``" (plugin)"`` (e.g.
      ``plugin:mureo-logly-bridge`` → ``"Logly (plugin)"``,
      ``plugin:acme-ads`` → ``"Acme Ads (plugin)"``). Unchanged, so state
      written before #537 keeps the label it already had.
    - A bare provider name an INSTALLED plugin registered (#609/#631) → the
      humanized name with the same ``" (plugin)"`` suffix
      (``logly_ads_context`` → ``"Logly Ads Context (plugin)"``). See
      :func:`_installed_plugin_platform_label`.
    - Anything else (an unknown built-in-shaped key) → the key itself, so
      the dashboard never renders a blank label.

    :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES` is keyed by distribution, so an
    official bridge shipping several platforms would label them all alike;
    none does today, and the fix when one appears is a per-provider entry,
    not a change to this resolution order.
    """
    builtin = _BUILTIN_DISPLAY_NAMES.get(key)
    if builtin is not None:
        return builtin
    # Issues #481 / #537: the canonical plugin key — see
    # mureo.core.platform_keys.
    if is_plugin_platform_key(key):
        dist, provider = plugin_platform_parts(key)
        official = _OFFICIAL_BRIDGE_DISPLAY_NAMES.get(dist)
        if official is not None:
            return official
        label = _humanize_words(provider) if provider else ""
        if not label:
            label = _humanize_dist(dist)
        return f"{label} (plugin)" if label else key
    return _installed_plugin_platform_label(key) or key


def _installed_plugin_platform_label(key: str) -> str:
    """Label a bare provider name an installed plugin registered (#631).

    ``key`` is a platform name straight out of the ``mureo.providers`` /
    ``mureo.analytics`` entry points — ``logly_ads_context``, not
    ``plugin:mureo-logly-bridge:logly_ads_context``. That has been a valid
    key to WRITE since #609, and this function is why the read side no longer
    calls it unresolvable: a key the guard accepted was being flagged
    ``unrecognized_key`` on the dashboard at the same moment
    ``mureo repair platform-key`` reported the same entry ``Clean``.

    Same ``" (plugin)"`` suffix as the canonical key for the same platform:
    the entry comes from a plugin under either spelling, and two labels for
    one platform on one dashboard would replace this inconsistency with
    another. :data:`_OFFICIAL_BRIDGE_DISPLAY_NAMES` cannot apply here — it is
    keyed by distribution and a bare name carries none — so an in-tree bridge
    held under its bare provider name keeps the suffix. Resolving that would
    mean reading ``ep.dist``, i.e. reading more of an entry point than the
    guard does, and mureo writes the canonical key for those anyway.

    Fails OPEN exactly as :func:`~mureo.context.platform_guards.
    reject_unknown_platform_key` does: an environment that cannot be
    enumerated labels the key rather than reporting it unrecognised, because
    a broken ``importlib.metadata`` is not evidence that a key is wrong.

    Two shapes are excluded whatever the registry says: a key claiming the
    plugin namespace without naming a platform (``plugin:``,
    ``plugin:<dist>:``), which the write path refuses on shape alone
    (``reject_unusable_platform_key``) and which no enumeration failure can
    make legitimate; and a name that humanizes to nothing. Both yield ``""``
    and the caller falls back to the raw key.
    """
    if key.startswith(PLUGIN_PLATFORM_PREFIX):
        return ""
    installed = installed_platform_names()
    if installed is not None and key not in installed:
        return ""
    label = _humanize_words(key)
    return f"{label} (plugin)" if label else ""


def _humanize_words(name: str) -> str:
    """Title-case a ``-``/``_``-separated identifier.

    ``yahoo_ads`` → ``Yahoo Ads``; ``acme-ads`` → ``Acme Ads``. An
    identifier that carries no word characters yields ``""`` so the
    caller can fall back.
    """
    words = [w for w in name.strip().replace("_", "-").split("-") if w]
    return " ".join(word.capitalize() for word in words)


def _humanize_dist(dist: str) -> str:
    """Turn a distribution name into a Title-Cased label.

    ``mureo-logly-bridge`` → ``Logly``; ``acme-ads`` → ``Acme Ads``. A
    leading ``mureo-`` and a trailing ``-bridge`` are mureo packaging
    conventions, not part of the brand, so they are stripped. An empty
    result (e.g. ``plugin:mureo-``, which is nothing but conventions)
    yields ``""`` and the caller falls back to the raw key.
    """
    name = dist.strip()
    if name.startswith("mureo-"):
        name = name[len("mureo-") :]
    if name.endswith("-bridge"):
        name = name[: -len("-bridge")]
    return _humanize_words(name)


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
      :func:`_safe_not_collected`.
    - ``platform_conflicts``: reasons these rows must not be added together
      (#533) — see :func:`_build_platform_conflicts`. Always a list, empty
      when the document is healthy, and it carries NO ad account ids.
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
    store = state_store_for_client(client)
    doc = _read_state_safe(store)
    resolved_client = client or _active_workspace_id(_active_state_store())

    return {
        "client": resolved_client,
        "period": period,
        "periods": _available_periods(doc),
        "last_synced_at": doc.last_synced_at if doc is not None else None,
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
    :func:`_platform_freshness` and :func:`_safe_not_collected`.
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
        "freshness": _platform_freshness(totals, metrics_period),
        "not_collected": _safe_not_collected(state.not_collected),
    }


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
