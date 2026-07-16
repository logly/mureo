"""Live-client metrics fetchers for the built-in analytics adapters.

Adapters are registered at process startup, before credentials are
loaded. The fetcher abstraction lets the adapter look up creds + open
a client **only when a workflow actually invokes the module**. That
keeps registry imports cheap (no auth side effects, no network) and
keeps the adapter usable in BYOD mode automatically — the client
factory handles the live-vs-BYOD routing.

Both fetchers return ``(current, baseline)`` :class:`CampaignMetrics`
pairs aggregated across the requested account. ``baseline`` may be
``None`` when:

- the account is new (no prior-window data), or
- credentials are missing (live mode only — BYOD always returns
  zero-cost metrics rather than raising).

Failure modes:

- :class:`NoCredentialsError` — credentials are unset in live mode.
  The adapter catches this and returns an empty anomaly tuple, since
  the absence of credentials is a configuration issue rather than an
  anomaly to report.
- Any other client exception bubbles up; the MCP dispatch layer
  surfaces it as a tool error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analysis.anomaly_detector import CampaignMetrics
from mureo.analytics.builtin._common import (
    google_row_metrics as _google_row_metrics,
)
from mureo.analytics.builtin._common import (
    meta_row_conversions as _meta_row_conversions,
)
from mureo.context.state import load_conversion_action_types

if TYPE_CHECKING:
    from collections.abc import Callable


class NoCredentialsError(RuntimeError):
    """Raised when the platform's credentials are missing.

    Distinct subclass so the adapter can catch this case and return an
    honest empty result rather than surfacing a noisy error to the
    workflow. Subclasses signal other "cannot fetch this account, degrade
    gracefully" conditions (see :class:`AccountNotAvailableError`) and are
    caught by the same ``except NoCredentialsError`` in every adapter method.
    """


class AccountNotAvailableError(NoCredentialsError):
    """The account cannot be fetched in the active workspace scope (#413/#435).

    Raised when the #411 allow-list refuses the ``account_id`` (out-of-set,
    empty allow-list, or an ambiguous multi-account default). A subclass of
    :class:`NoCredentialsError` so every adapter's existing
    ``except NoCredentialsError`` renders the same graceful "not available"
    sentinel — a workspace-scope violation degrades like missing credentials
    rather than propagating a raw ``ValueError`` out of the AnalyticsModule
    Protocol method.
    """


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------

_GOOGLE_WINDOW_TO_PERIOD: dict[int, str] = {
    # window_days -> Google date-range constant. The baseline is derived as the
    # equal-length window immediately *before* this one via
    # ``_get_comparison_date_ranges`` — NOT a preset such as LAST_30_DAYS, which
    # overlaps (7d ⊂ 30d) or, for the 30d case, is literally identical to the
    # current window (baseline == current → ratio always 1.0 → no anomaly can
    # fire). Same non-overlapping period-over-period contract the rest of the
    # analysis layer uses (google_ads/_analysis_constants,
    # meta_ads/_period, #134).
    7: "LAST_7_DAYS",
    14: "LAST_14_DAYS",
    30: "LAST_30_DAYS",
}


def _aggregate_google_metrics(
    rows: list[dict[str, Any]],
    account_id: str,
) -> CampaignMetrics:
    """Collapse a multi-campaign performance report to a single account-level
    :class:`CampaignMetrics`.

    The pure anomaly detector operates per-campaign; account-level
    detection over the aggregate is a Phase-1 simplification chosen so
    the first wired implementation is small and predictable. A future
    iteration can fan out per-campaign.
    """
    cost = 0.0
    impressions = 0
    clicks = 0
    conversions = 0.0
    for row in rows:
        metrics = _google_row_metrics(row)
        cost += float(metrics.get("cost") or 0)
        impressions += int(metrics.get("impressions") or 0)
        clicks += int(metrics.get("clicks") or 0)
        conversions += float(metrics.get("conversions") or 0)
    return CampaignMetrics(
        campaign_id=account_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
    )


def _open_google_ads_client(account_id: str) -> tuple[object, str]:
    """Resolve credentials + open a Google Ads client (live or BYOD).

    Returns ``(client, resolved_account_id)`` — the resolved id (possibly
    canonicalized) so callers label / look up conversions with the same value
    the client was opened with (#435). A workspace-scope refusal raises
    :class:`AccountNotAvailableError`.

    Workspace scoping (#411/#413): ``account_id`` is bound to the active
    client's allow-list via ``_resolve_customer_id`` before use — a
    non-tenant-scoped run passes it through unchanged, a tenant-scoped run
    refuses an out-of-allow-list id (fail-closed). Enforcing here means a
    future tool that wires a caller-supplied id into the AnalyticsModule
    Protocol cannot silently bypass #411 scoping.

    Raises :class:`NoCredentialsError` in live mode when credentials
    are missing. BYOD mode is detected by the client factory itself
    (``mureo.mcp._client_factory``), so this helper does not re-check
    ``byod_has`` — keeping the BYOD branching in one place avoids
    drift if the factory's policy changes.

    Local imports defer auth / google_ads SDK loading until first use
    so the registry import remains cheap. Test patch sites:
    ``mureo.auth.load_google_ads_credentials`` and
    ``mureo.mcp._client_factory.get_google_ads_client``.
    """
    from mureo.auth import load_google_ads_credentials
    from mureo.byod.runtime import byod_has
    from mureo.mcp._client_factory import get_google_ads_client
    from mureo.mcp._handlers_google_ads import _resolve_customer_id

    # Bind the account to the workspace allow-list (#411/#413) before it
    # reaches the client factory; a refusal degrades gracefully (#435).
    try:
        account_id = _resolve_customer_id(account_id, None)
    except ValueError as exc:
        raise AccountNotAvailableError(str(exc)) from exc

    if byod_has("google_ads"):
        return get_google_ads_client(creds=None, customer_id=account_id), account_id

    creds = load_google_ads_credentials()
    if creds is None:
        raise NoCredentialsError("google_ads credentials not configured")
    return get_google_ads_client(creds, account_id), account_id


async def fetch_google_ads_metrics(
    account_id: str,
    *,
    window_days: int,
) -> tuple[CampaignMetrics, CampaignMetrics | None]:
    """Fetch ``(current, baseline)`` metrics for one Google Ads account.

    Raises :class:`NoCredentialsError` when ``account_id`` cannot be
    resolved to a usable client (live mode + missing creds).

    Known limitation: rows are aggregated to a single account-level
    :class:`CampaignMetrics`. A real anomaly affecting one campaign
    while another scales up can net out at the aggregate (current
    [bad, good], baseline [good, good] → no anomaly). Per-campaign
    fan-out is a follow-up; the trade-off is documented and tested
    in ``test_live_clients.py``.
    """
    client, account_id = _open_google_ads_client(account_id)

    # Local import defers the google_ads analysis module until first use (the
    # registry import must stay cheap; see the module docstring).
    from mureo.google_ads._analysis_constants import _get_comparison_date_ranges

    period_token = _GOOGLE_WINDOW_TO_PERIOD.get(window_days, "LAST_7_DAYS")
    # Non-overlapping, equal-length current/previous BETWEEN clauses. The Google
    # client's _period_to_date_clause accepts a BETWEEN clause and validates it
    # against the GAQL whitelist, so this is injection-safe.
    current_period, baseline_period = _get_comparison_date_ranges(period_token)
    current_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=current_period
    )
    baseline_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=baseline_period
    )

    current = _aggregate_google_metrics(current_rows, account_id)
    baseline = _aggregate_google_metrics(baseline_rows, account_id)
    # Treat a zero-spend baseline as "no useful comparison" — the pure
    # detector then suppresses ratio-based alerts and we avoid
    # divide-by-zero churn.
    if baseline.cost <= 0:
        return current, None
    return current, baseline


async def fetch_google_ads_performance_rows(
    account_id: str,
    period: str,
) -> list[dict[str, object]]:
    """Return raw performance rows for ``account_id`` over ``period``.

    Used by :meth:`GoogleAdsAnalyticsModule.diagnose_performance`.
    Raises :class:`NoCredentialsError` uniformly with
    :func:`fetch_google_ads_metrics` so the adapter renders a single
    sentinel headline rather than diverging on the same condition.
    """
    client, account_id = _open_google_ads_client(account_id)
    return await client.get_performance_report(period=period)  # type: ignore[attr-defined,no-any-return]


def _row_to_campaign_metrics(
    row: dict[str, Any],
    *,
    nested_metrics_getter: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    spend_key: str = "cost",
    conversion_getter: Callable[[dict[str, Any]], float] | None = None,
) -> CampaignMetrics | None:
    """Convert one platform row into a :class:`CampaignMetrics`.

    Centralises the BYOD↔Live shape tolerance documented on
    :func:`_google_row_metrics` / :func:`_meta_row_conversions` so both
    fan-out fetchers can reuse the same logic.

    Returns ``None`` when the row has no usable ``campaign_id`` — such
    rows are dropped rather than aggregated into a synthetic
    ``""``-keyed entry that would silently mix multiple campaigns'
    metrics.
    """
    campaign_id = str(row.get("campaign_id") or "").strip()
    if not campaign_id:
        return None

    metrics = nested_metrics_getter(row) if nested_metrics_getter else row
    cost = float(metrics.get(spend_key) or 0)
    impressions = int(metrics.get("impressions") or 0)
    clicks = int(metrics.get("clicks") or 0)
    if conversion_getter is not None:
        conversions = conversion_getter(row)
    else:
        conversions = float(metrics.get("conversions") or 0)
    return CampaignMetrics(
        campaign_id=campaign_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
    )


def _index_google_rows_by_campaign(
    rows: list[dict[str, Any]],
) -> dict[str, CampaignMetrics]:
    """Build ``{campaign_id: metrics}`` from Google rows.

    A campaign appearing multiple times (e.g. day-grain rows) is
    summed; the metrics are added field-by-field on a single
    :class:`CampaignMetrics`. Real per-period reports return one row
    per campaign so the sum is usually a no-op, but the contract is
    explicit either way.
    """
    indexed: dict[str, CampaignMetrics] = {}
    for row in rows:
        metric = _row_to_campaign_metrics(
            row, nested_metrics_getter=_google_row_metrics
        )
        if metric is None:
            continue
        existing = indexed.get(metric.campaign_id)
        if existing is None:
            indexed[metric.campaign_id] = metric
        else:
            indexed[metric.campaign_id] = CampaignMetrics(
                campaign_id=metric.campaign_id,
                cost=existing.cost + metric.cost,
                impressions=existing.impressions + metric.impressions,
                clicks=existing.clicks + metric.clicks,
                conversions=existing.conversions + metric.conversions,
            )
    return indexed


async def fetch_google_ads_per_campaign_metrics(
    account_id: str,
    *,
    window_days: int,
) -> dict[str, tuple[CampaignMetrics, CampaignMetrics | None]]:
    """Return ``{campaign_id: (current, baseline)}`` for one Google account.

    Per-campaign fan-out (#120 follow-up). Replaces the account-level
    aggregation that masked offsetting per-campaign anomalies
    (campaign A drops to zero spend while B scales up — aggregate
    cost unchanged, no anomaly fires).

    Baseline is ``None`` for campaigns that have no rows in the prior
    window (new campaigns) or whose prior-window cost is zero
    (paused/weekend dayparting). The pure detector treats those cases
    correctly — see :func:`mureo.analysis.anomaly_detector.detect_anomalies`.

    Raises :class:`NoCredentialsError` uniformly with
    :func:`fetch_google_ads_metrics`.
    """
    client, account_id = _open_google_ads_client(account_id)
    from mureo.google_ads._analysis_constants import _get_comparison_date_ranges

    period_token = _GOOGLE_WINDOW_TO_PERIOD.get(window_days, "LAST_7_DAYS")
    current_period, baseline_period = _get_comparison_date_ranges(period_token)
    current_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=current_period
    )
    baseline_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=baseline_period
    )

    current_index = _index_google_rows_by_campaign(current_rows)
    baseline_index = _index_google_rows_by_campaign(baseline_rows)

    out: dict[str, tuple[CampaignMetrics, CampaignMetrics | None]] = {}
    for campaign_id, current in current_index.items():
        baseline = baseline_index.get(campaign_id)
        # Zero-spend baseline → no useful comparison; detector
        # suppresses ratio-based alerts in that case anyway.
        if baseline is not None and baseline.cost <= 0:
            baseline = None
        out[campaign_id] = (current, baseline)
    return out


def _index_meta_rows_by_campaign(
    rows: list[dict[str, Any]],
    account_id: str,
) -> dict[str, CampaignMetrics]:
    """Build ``{campaign_id: metrics}`` from Meta rows.

    Mirrors :func:`_index_google_rows_by_campaign` for Meta's flatter
    shape — Meta exposes ``spend`` and either an ``actions`` list
    (Live) or a top-level ``conversions`` field (BYOD). ``account_id``
    resolves the operator's per-account conversion override (#342).
    """
    cv_types = load_conversion_action_types(account_id)
    indexed: dict[str, CampaignMetrics] = {}
    for row in rows:
        metric = _row_to_campaign_metrics(
            row,
            spend_key="spend",
            conversion_getter=lambda r: _meta_row_conversions(
                r, conversion_action_types=cv_types
            ),
        )
        if metric is None:
            continue
        existing = indexed.get(metric.campaign_id)
        if existing is None:
            indexed[metric.campaign_id] = metric
        else:
            indexed[metric.campaign_id] = CampaignMetrics(
                campaign_id=metric.campaign_id,
                cost=existing.cost + metric.cost,
                impressions=existing.impressions + metric.impressions,
                clicks=existing.clicks + metric.clicks,
                conversions=existing.conversions + metric.conversions,
            )
    return indexed


async def fetch_google_ads_list(
    account_id: str,
) -> list[dict[str, object]]:
    """Return ``list_ads`` results for ``account_id`` (live or BYOD).

    Used by :meth:`GoogleAdsAnalyticsModule.audit_creative`. Raises
    :class:`NoCredentialsError` in live mode when creds are missing.
    """
    client, account_id = _open_google_ads_client(account_id)
    return await client.list_ads()  # type: ignore[attr-defined,no-any-return]


async def fetch_meta_ads_list(
    account_id: str,
) -> list[dict[str, object]]:
    """Return ``list_ads`` results for one Meta account."""
    client, account_id = _open_meta_ads_client(account_id)
    return await client.list_ads()  # type: ignore[attr-defined,no-any-return]


async def fetch_meta_ads_per_campaign_metrics(
    account_id: str,
    *,
    window_days: int,
) -> dict[str, tuple[CampaignMetrics, CampaignMetrics | None]]:
    """Per-campaign fan-out for Meta — parallel to
    :func:`fetch_google_ads_per_campaign_metrics`.
    """
    client, account_id = _open_meta_ads_client(account_id)
    from mureo.meta_ads._period import previous_period

    current_period = _META_WINDOW_TO_PERIOD.get(window_days, "last_7d")
    baseline_period = previous_period(current_period)
    current_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=current_period
    )
    baseline_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=baseline_period
    )

    current_index = _index_meta_rows_by_campaign(current_rows, account_id)
    baseline_index = _index_meta_rows_by_campaign(baseline_rows, account_id)

    out: dict[str, tuple[CampaignMetrics, CampaignMetrics | None]] = {}
    for campaign_id, current in current_index.items():
        baseline = baseline_index.get(campaign_id)
        if baseline is not None and baseline.cost <= 0:
            baseline = None
        out[campaign_id] = (current, baseline)
    return out


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------

_META_WINDOW_TO_PERIOD: dict[int, str] = {
    # window_days -> Meta date preset. The baseline is derived from
    # meta_ads._period.previous_period (the equal-length window immediately
    # before this one), NOT last_30d — which overlaps last_7d/last_14d and is
    # identical to last_30d for the 30d case, making the anomaly ratio a
    # meaningless 1.0. This is exactly the #134 fix applied to the anomaly path.
    7: "last_7d",
    14: "last_14d",
    30: "last_30d",
}


def _aggregate_meta_metrics(
    rows: list[dict[str, Any]],
    account_id: str,
) -> CampaignMetrics:
    """Aggregate Meta insights rows to an account-level metric tuple.

    Tolerates both the Live (``actions`` list) and BYOD (flat
    ``conversions``) row shapes — see :func:`_meta_row_conversions`.
    """
    cost = 0.0
    impressions = 0
    clicks = 0
    conversions = 0.0
    cv_types = load_conversion_action_types(account_id)  # #342 per-account override
    for row in rows:
        cost += float(row.get("spend") or 0)
        impressions += int(row.get("impressions") or 0)
        clicks += int(row.get("clicks") or 0)
        conversions += _meta_row_conversions(row, conversion_action_types=cv_types)
    return CampaignMetrics(
        campaign_id=account_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
    )


def _open_meta_ads_client(account_id: str) -> tuple[object, str]:
    """Parallel to :func:`_open_google_ads_client` for Meta Ads.

    Returns ``(client, resolved_account_id)`` — the resolved id is
    canonicalized to the ``act_`` form when tenant-scoped, so callers use the
    same value the client was opened with (#435). A workspace-scope refusal
    raises :class:`AccountNotAvailableError`.

    Workspace scoping (#411/#413): ``account_id`` is bound to the active
    client's allow-list via ``_resolve_account_id`` before use — a
    non-tenant-scoped run passes it through unchanged, a tenant-scoped run
    refuses an out-of-allow-list id (fail-closed). Enforcing here means a
    future tool that wires a caller-supplied id into the AnalyticsModule
    Protocol cannot silently bypass #411 scoping.
    """
    from mureo.auth import load_meta_ads_credentials
    from mureo.byod.runtime import byod_has
    from mureo.mcp._client_factory import get_meta_ads_client
    from mureo.mcp._handlers_meta_ads import _resolve_account_id

    # Bind the account to the workspace allow-list (#411/#413) before it
    # reaches the client factory; a refusal degrades gracefully (#435).
    try:
        account_id = _resolve_account_id(account_id, None)
    except ValueError as exc:
        raise AccountNotAvailableError(str(exc)) from exc

    if byod_has("meta_ads"):
        return get_meta_ads_client(creds=None, account_id=account_id), account_id

    creds = load_meta_ads_credentials()
    if creds is None:
        raise NoCredentialsError("meta_ads credentials not configured")
    return get_meta_ads_client(creds, account_id), account_id


async def fetch_meta_ads_metrics(
    account_id: str,
    *,
    window_days: int,
) -> tuple[CampaignMetrics, CampaignMetrics | None]:
    """Fetch ``(current, baseline)`` metrics for one Meta Ads account.

    Raises :class:`NoCredentialsError` when credentials are missing
    in live mode. Shares the per-campaign aggregation limitation
    documented on :func:`fetch_google_ads_metrics`.
    """
    client, account_id = _open_meta_ads_client(account_id)
    from mureo.meta_ads._period import previous_period

    current_period = _META_WINDOW_TO_PERIOD.get(window_days, "last_7d")
    baseline_period = previous_period(current_period)
    current_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=current_period
    )
    baseline_rows = await client.get_performance_report(  # type: ignore[attr-defined]
        period=baseline_period
    )

    current = _aggregate_meta_metrics(current_rows, account_id)
    baseline = _aggregate_meta_metrics(baseline_rows, account_id)
    if baseline.cost <= 0:
        return current, None
    return current, baseline


async def fetch_meta_ads_performance_rows(
    account_id: str,
    period: str,
) -> list[dict[str, object]]:
    """Return raw performance rows for ``account_id`` over ``period``."""
    client, account_id = _open_meta_ads_client(account_id)
    return await client.get_performance_report(period=period)  # type: ignore[attr-defined,no-any-return]


__all__ = [
    "AccountNotAvailableError",
    "NoCredentialsError",
    "fetch_google_ads_list",
    "fetch_google_ads_metrics",
    "fetch_google_ads_per_campaign_metrics",
    "fetch_google_ads_performance_rows",
    "fetch_meta_ads_list",
    "fetch_meta_ads_metrics",
    "fetch_meta_ads_per_campaign_metrics",
    "fetch_meta_ads_performance_rows",
]
