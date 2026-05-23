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

from typing import Any

from mureo.analysis.anomaly_detector import CampaignMetrics


class NoCredentialsError(RuntimeError):
    """Raised when the platform's credentials are missing.

    Distinct subclass so the adapter can catch this case and return an
    honest empty result rather than surfacing a noisy error to the
    workflow.
    """


# ---------------------------------------------------------------------------
# Google Ads
# ---------------------------------------------------------------------------

_GOOGLE_PERIOD_MAP: dict[int, tuple[str, str]] = {
    # window_days -> (current period token, baseline period token).
    # Tokens passed to GoogleAdsApiClient.get_performance_report —
    # see mureo/google_ads/_analysis_constants.py _PERIOD_DAYS.
    7: ("LAST_7_DAYS", "LAST_30_DAYS"),
    14: ("LAST_14_DAYS", "LAST_30_DAYS"),
    30: ("LAST_30_DAYS", "LAST_30_DAYS"),
}


def _google_row_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Return the metrics view of a Google Ads performance row.

    Live :func:`mureo.google_ads.mappers.map_performance_report` nests
    metrics under ``row["metrics"]``; BYOD
    :class:`mureo.byod.clients.ByodGoogleAdsClient.get_performance_report`
    returns them flat at the top level. Both shapes are valid responses
    from :func:`mureo.mcp._client_factory.get_google_ads_client`, so
    the aggregator has to accept either or it silently double-zeros
    the BYOD path (confirmed bug during #120 live-wiring validation).
    """
    nested = row.get("metrics")
    if isinstance(nested, dict) and nested:
        return nested
    return row


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


def _open_google_ads_client(account_id: str) -> object:
    """Resolve credentials + open a Google Ads client (live or BYOD).

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

    if byod_has("google_ads"):
        return get_google_ads_client(creds=None, customer_id=account_id)

    creds = load_google_ads_credentials()
    if creds is None:
        raise NoCredentialsError("google_ads credentials not configured")
    return get_google_ads_client(creds, account_id)


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
    client = _open_google_ads_client(account_id)

    current_period, baseline_period = _GOOGLE_PERIOD_MAP.get(
        window_days, ("LAST_7_DAYS", "LAST_30_DAYS")
    )
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
    client = _open_google_ads_client(account_id)
    return await client.get_performance_report(period=period)  # type: ignore[attr-defined,no-any-return]


# ---------------------------------------------------------------------------
# Meta Ads
# ---------------------------------------------------------------------------

_META_PERIOD_MAP: dict[int, tuple[str, str]] = {
    # window_days -> (current period preset, baseline period preset).
    # Tokens passed to MetaAdsApiClient.get_performance_report —
    # see mureo/meta_ads/_period.py for supported presets.
    7: ("last_7d", "last_30d"),
    14: ("last_14d", "last_30d"),
    30: ("last_30d", "last_30d"),
}


def _meta_row_conversions(row: dict[str, Any]) -> float:
    """Return conversion count for a Meta performance row.

    Two shapes have to be accepted:

    * Live :class:`MetaAdsApiClient` returns the raw Marketing API
      response — conversions live inside an ``actions`` list keyed by
      ``action_type``.
    * BYOD :class:`ByodMetaAdsClient.get_performance_report` pre-
      aggregates conversions into a top-level ``conversions`` field
      and provides a ``result_indicator`` instead of the ``actions``
      list.

    Detected during #120 live-wiring validation — accepting only the
    Live shape silently zeroes BYOD conversions.
    """
    actions = row.get("actions")
    if isinstance(actions, list):
        total = 0.0
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = str(action.get("action_type", ""))
            # Match the existing analysis-surface convention
            # (mureo/meta_ads/_analysis.py): leads + purchases are
            # the canonical conversion actions.
            if "lead" in action_type or "purchase" in action_type:
                total += float(action.get("value") or 0)
        return total
    # BYOD path — already aggregated.
    return float(row.get("conversions") or 0)


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
    for row in rows:
        cost += float(row.get("spend") or 0)
        impressions += int(row.get("impressions") or 0)
        clicks += int(row.get("clicks") or 0)
        conversions += _meta_row_conversions(row)
    return CampaignMetrics(
        campaign_id=account_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
    )


def _open_meta_ads_client(account_id: str) -> object:
    """Parallel to :func:`_open_google_ads_client` for Meta Ads."""
    from mureo.auth import load_meta_ads_credentials
    from mureo.byod.runtime import byod_has
    from mureo.mcp._client_factory import get_meta_ads_client

    if byod_has("meta_ads"):
        return get_meta_ads_client(creds=None, account_id=account_id)

    creds = load_meta_ads_credentials()
    if creds is None:
        raise NoCredentialsError("meta_ads credentials not configured")
    return get_meta_ads_client(creds, account_id)


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
    client = _open_meta_ads_client(account_id)

    current_period, baseline_period = _META_PERIOD_MAP.get(
        window_days, ("last_7d", "last_30d")
    )
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
    client = _open_meta_ads_client(account_id)
    return await client.get_performance_report(period=period)  # type: ignore[attr-defined,no-any-return]


__all__ = [
    "NoCredentialsError",
    "fetch_google_ads_metrics",
    "fetch_google_ads_performance_rows",
    "fetch_meta_ads_metrics",
    "fetch_meta_ads_performance_rows",
]
