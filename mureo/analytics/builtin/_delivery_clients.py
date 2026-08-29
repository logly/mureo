"""Day-grain delivery fetchers for the collapse detector (#546).

Split out of ``_live_clients`` so that module stays within the project's
file-size budget, and because these two fetchers share a single body:
both platforms expose ``get_daily_delivery_report(days=...)`` returning
the **same normalised row shape**, which is the whole point — the
detector, the baseline, and the elimination ladder are platform-agnostic
and only the fetch is not.

Credential resolution, workspace-scope binding (#411/#413) and the
live-vs-BYOD routing are reused verbatim from ``_live_clients``'s
``_open_*_client`` helpers, so this surface cannot bypass the
allow-list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analysis.delivery_collapse import (
    delivery_series_from_rows,
    detect_delivery_collapses,
    last_reported_day,
)
from mureo.analysis.delivery_collapse_config import load_collapse_thresholds
from mureo.analytics.builtin._live_clients import (
    DeliveryDataUnavailableError,
    NoCredentialsError,
    _open_google_ads_client,
    _open_meta_ads_client,
)
from mureo.analytics.models import DeliveryCollapseReport
from mureo.core import clock

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import date

    from mureo.analysis.delivery_collapse import CollapseThresholds, DeliverySeries

    DeliveryFetcher = Callable[..., Awaitable[tuple[tuple[DeliverySeries, ...], str]]]

#: ``thresholds_source`` when the caller passed thresholds explicitly
#: rather than letting STRATEGY.md's ``## Guardrails`` decide.
SOURCE_EXPLICIT = "explicit"

#: Default trailing window: a 28-day baseline plus room for a collapse
#: that has been running for a month before anyone looked at it.
DEFAULT_HISTORY_DAYS = 60


async def _fetch_series(
    client: object,
    account_id: str,
    *,
    days: int,
    platform: str,
) -> tuple[tuple[DeliverySeries, ...], str]:
    """Pull day-grain rows off ``client`` and group them per campaign."""
    fetch = getattr(client, "get_daily_delivery_report", None)
    if fetch is None:
        raise DeliveryDataUnavailableError(
            f"{platform}: the active client cannot produce day-grain "
            f"delivery data, so no baseline can be built"
        )
    rows: list[dict[str, Any]] = await fetch(days=days)
    return delivery_series_from_rows(rows, platform=platform), account_id


async def fetch_google_ads_delivery_series(
    account_id: str,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
) -> tuple[tuple[DeliverySeries, ...], str]:
    """Return ``(series, resolved_account_id)`` for one Google Ads account.

    Raises :class:`NoCredentialsError` (live mode, missing creds or an
    out-of-scope account) or :class:`DeliveryDataUnavailableError`.
    """
    client, account_id = _open_google_ads_client(account_id)
    return await _fetch_series(client, account_id, days=days, platform="google_ads")


async def fetch_meta_ads_delivery_series(
    account_id: str,
    *,
    days: int = DEFAULT_HISTORY_DAYS,
) -> tuple[tuple[DeliverySeries, ...], str]:
    """Meta twin of :func:`fetch_google_ads_delivery_series`."""
    client, account_id = await _open_meta_ads_client(account_id)
    return await _fetch_series(client, account_id, days=days, platform="meta_ads")


async def run_delivery_collapse(
    *,
    platform: str,
    account_id: str,
    fetcher: DeliveryFetcher,
    history_days: int = DEFAULT_HISTORY_DAYS,
    thresholds: CollapseThresholds | None = None,
    as_of: date | None = None,
) -> DeliveryCollapseReport:
    """Shared body of every built-in ``detect_delivery_collapse``.

    Both adapters differ only in which fetcher they pass, so the
    fetch-failure taxonomy, the threshold resolution and the report
    shape live here once. The two failure branches are the reason this
    returns a report rather than a bare tuple of signals: "could not
    check" and "checked, all healthy" must never look alike.
    """
    resolved, source = (
        (thresholds, SOURCE_EXPLICIT)
        if thresholds is not None
        else load_collapse_thresholds()
    )

    def _report(status: str, **extra: Any) -> DeliveryCollapseReport:
        return DeliveryCollapseReport(
            platform=platform,
            account_id=account_id,
            status=status,
            thresholds=resolved,
            thresholds_source=source,
            **extra,
        )

    try:
        series, resolved_account = await fetcher(account_id, days=history_days)
    except NoCredentialsError as exc:
        return _report("no_credentials", detail=str(exc))
    except DeliveryDataUnavailableError as exc:
        return _report("data_unavailable", detail=str(exc))

    account_id = resolved_account
    reported = last_reported_day(series)
    evaluated_through = as_of or clock.server_now().date()
    return _report(
        "ok",
        evaluated_campaigns=len(series),
        signals=detect_delivery_collapses(series, thresholds=resolved, as_of=as_of),
        reported_through=reported.isoformat() if reported else "",
        # Complete days (i.e. excluding the partial current one) that the
        # platform has not reported at all. Non-zero is not automatically
        # a fault — it is the state the detector cannot see through, so
        # the caller has to be told rather than shown an empty list.
        unreported_days=(
            max(0, (evaluated_through - reported).days - 1) if reported else 0
        ),
    )


__all__ = [
    "DEFAULT_HISTORY_DAYS",
    "SOURCE_EXPLICIT",
    "fetch_google_ads_delivery_series",
    "fetch_meta_ads_delivery_series",
    "run_delivery_collapse",
]
