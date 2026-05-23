"""Tests for the live-client metrics fetchers."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from mureo.analytics.builtin._live_clients import (
    NoCredentialsError,
    _aggregate_google_metrics,
    _aggregate_meta_metrics,
    fetch_google_ads_metrics,
    fetch_meta_ads_metrics,
)

# ---------------------------------------------------------------------------
# Aggregation helpers (pure)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_aggregate_google_metrics_sums_rows() -> None:
    rows: list[dict[str, Any]] = [
        {
            "metrics": {
                "cost": 100.0,
                "impressions": 500,
                "clicks": 20,
                "conversions": 3,
            }
        },
        {
            "metrics": {
                "cost": 250.0,
                "impressions": 1000,
                "clicks": 50,
                "conversions": 7,
            }
        },
    ]
    result = _aggregate_google_metrics(rows, account_id="acct-1")
    assert result.campaign_id == "acct-1"
    assert result.cost == 350.0
    assert result.impressions == 1500
    assert result.clicks == 70
    assert result.conversions == 10


@pytest.mark.unit
def test_aggregate_google_metrics_handles_empty() -> None:
    result = _aggregate_google_metrics([], account_id="acct-2")
    assert result.cost == 0.0
    assert result.impressions == 0


@pytest.mark.unit
def test_aggregate_google_metrics_accepts_byod_flat_shape() -> None:
    """BYOD ``get_performance_report`` returns rows with metrics at the
    top level, not nested under ``metrics``. The aggregator must accept
    both shapes — regression for the silent-zero bug found during #120
    live-wiring validation.
    """
    rows: list[dict[str, Any]] = [
        # BYOD shape — flat
        {
            "campaign_id": "camp_abc",
            "cost": 392000.0,
            "impressions": 5600,
            "clicks": 1120,
            "conversions": 179.2,
        },
    ]
    result = _aggregate_google_metrics(rows, account_id="byod-acct")
    assert result.cost == 392000.0
    assert result.impressions == 5600
    assert result.conversions == pytest.approx(179.2)


@pytest.mark.unit
def test_aggregate_google_metrics_handles_none_values() -> None:
    rows: list[dict[str, Any]] = [
        {"metrics": {"cost": None, "impressions": None, "clicks": None}}
    ]
    result = _aggregate_google_metrics(rows, account_id="a")
    assert result.cost == 0.0


@pytest.mark.unit
def test_aggregate_meta_metrics_sums_actions() -> None:
    rows: list[dict[str, Any]] = [
        {
            "spend": "50.0",
            "impressions": "1000",
            "clicks": "40",
            "actions": [
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": "3"},
                {"action_type": "link_click", "value": "40"},
            ],
        },
        {
            "spend": 30.0,
            "impressions": 500,
            "clicks": 15,
            "actions": [
                {"action_type": "lead", "value": 2},
                {"action_type": "purchase", "value": 1},
            ],
        },
    ]
    result = _aggregate_meta_metrics(rows, account_id="act_123")
    assert result.cost == 80.0
    assert result.impressions == 1500
    assert result.clicks == 55
    # 3 (lead) + 2 (lead) + 1 (purchase) = 6
    assert result.conversions == 6


@pytest.mark.unit
def test_aggregate_meta_metrics_accepts_byod_flat_conversions() -> None:
    """BYOD Meta returns conversions as a top-level field with no
    ``actions`` list. Regression for the silent-zero bug found during
    #120 live-wiring validation.
    """
    rows: list[dict[str, Any]] = [
        {
            "campaign_id": "camp_1",
            "spend": 100.0,
            "impressions": 500,
            "clicks": 30,
            "conversions": 12.0,
            "result_indicator": "actions:offsite_conversion.fb_pixel_lead",
        }
    ]
    result = _aggregate_meta_metrics(rows, account_id="act_byod")
    assert result.cost == 100.0
    assert result.conversions == 12.0


@pytest.mark.unit
def test_aggregate_meta_metrics_handles_missing_actions() -> None:
    rows: list[dict[str, Any]] = [
        {"spend": 10, "impressions": 100, "clicks": 5},
    ]
    result = _aggregate_meta_metrics(rows, account_id="x")
    assert result.conversions == 0.0


# ---------------------------------------------------------------------------
# fetch_google_ads_metrics (live path mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_google_ads_metrics_raises_when_creds_missing() -> None:
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=None),
        pytest.raises(NoCredentialsError),
    ):
        await fetch_google_ads_metrics("acct-1", window_days=7)


@pytest.mark.asyncio
async def test_fetch_google_ads_metrics_returns_current_and_baseline() -> None:
    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [
                {
                    "metrics": {
                        "cost": 100.0,
                        "impressions": 500,
                        "clicks": 20,
                        "conversions": 5,
                    }
                }
            ],
            [
                {
                    "metrics": {
                        "cost": 200.0,
                        "impressions": 1000,
                        "clicks": 40,
                        "conversions": 10,
                    }
                }
            ],
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_google_ads_client",
            return_value=fake_client,
        ),
    ):
        current, baseline = await fetch_google_ads_metrics("acct-1", window_days=7)

    assert current.cost == 100.0
    assert baseline is not None
    assert baseline.cost == 200.0


@pytest.mark.asyncio
async def test_fetch_google_ads_metrics_returns_none_baseline_when_zero_spend() -> None:
    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [
                {
                    "metrics": {
                        "cost": 50.0,
                        "impressions": 200,
                        "clicks": 5,
                        "conversions": 1,
                    }
                }
            ],
            [
                {
                    "metrics": {
                        "cost": 0.0,
                        "impressions": 0,
                        "clicks": 0,
                        "conversions": 0,
                    }
                }
            ],
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_google_ads_client",
            return_value=fake_client,
        ),
    ):
        current, baseline = await fetch_google_ads_metrics("acct-1", window_days=7)

    assert current.cost == 50.0
    assert baseline is None


@pytest.mark.asyncio
async def test_fetch_google_ads_metrics_uses_byod_when_registered() -> None:
    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        return_value=[
            {"metrics": {"cost": 10, "impressions": 100, "clicks": 1, "conversions": 0}}
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=True),
        patch(
            "mureo.mcp._client_factory.get_google_ads_client",
            return_value=fake_client,
        ) as get_client,
    ):
        await fetch_google_ads_metrics("byod-acct", window_days=7)

    # BYOD path must pass creds=None.
    get_client.assert_called_once()
    _, kwargs = get_client.call_args
    assert kwargs["creds"] is None


# ---------------------------------------------------------------------------
# fetch_meta_ads_metrics (live path mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_meta_ads_metrics_raises_when_creds_missing() -> None:
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
        pytest.raises(NoCredentialsError),
    ):
        await fetch_meta_ads_metrics("act_x", window_days=7)


@pytest.mark.asyncio
async def test_fetch_google_ads_performance_rows_raises_when_creds_missing() -> None:
    """Uniform missing-creds semantics: the rows fetcher raises the
    same :class:`NoCredentialsError` as the metrics fetcher so the
    adapter can render a single sentinel headline.
    """
    from mureo.analytics.builtin._live_clients import (
        fetch_google_ads_performance_rows,
    )

    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=None),
        pytest.raises(NoCredentialsError, match="google_ads"),
    ):
        await fetch_google_ads_performance_rows("acct-1", "LAST_7_DAYS")


@pytest.mark.asyncio
async def test_fetch_meta_ads_performance_rows_raises_when_creds_missing() -> None:
    from mureo.analytics.builtin._live_clients import (
        fetch_meta_ads_performance_rows,
    )

    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_meta_ads_credentials", return_value=None),
        pytest.raises(NoCredentialsError, match="meta_ads"),
    ):
        await fetch_meta_ads_performance_rows("act_x", "last_7d")


@pytest.mark.unit
def test_aggregation_masks_per_campaign_anomaly_legacy_path() -> None:
    """The legacy aggregate path (still used by the
    ``metrics_fetcher`` injection point) collapses N campaigns into
    one :class:`CampaignMetrics`, so offsetting per-campaign movements
    net out and no anomaly fires.

    Per-campaign fan-out (now the default live path) fixes this — see
    ``test_per_campaign_fanout_surfaces_masked_anomaly``. This test
    pins the **legacy** behaviour so removing the back-compat path is
    a deliberate decision rather than silent breakage.
    """
    from mureo.analysis.anomaly_detector import detect_anomalies

    current_rows: list[dict[str, Any]] = [
        # Campaign A: cost collapsed to zero.
        {
            "metrics": {
                "cost": 0.0,
                "impressions": 0,
                "clicks": 0,
                "conversions": 0,
            }
        },
        # Campaign B: scaled up to compensate.
        {
            "metrics": {
                "cost": 1000.0,
                "impressions": 5000,
                "clicks": 200,
                "conversions": 20,
            }
        },
    ]
    baseline_rows: list[dict[str, Any]] = [
        {
            "metrics": {
                "cost": 500.0,
                "impressions": 2500,
                "clicks": 100,
                "conversions": 10,
            }
        },
        {
            "metrics": {
                "cost": 500.0,
                "impressions": 2500,
                "clicks": 100,
                "conversions": 10,
            }
        },
    ]
    current = _aggregate_google_metrics(current_rows, account_id="acct")
    baseline = _aggregate_google_metrics(baseline_rows, account_id="acct")
    # Aggregate: current cost == baseline cost == 1000. No anomaly.
    anomalies = detect_anomalies(current, baseline, had_prior_spend=True)
    assert anomalies == [], (
        "Phase-1 aggregation should mask per-campaign offsets — if this "
        "assertion fires, the trade-off has changed and the docstring on "
        "fetch_google_ads_metrics must be updated."
    )


# ---------------------------------------------------------------------------
# Per-campaign fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_google_ads_per_campaign_metrics_keys_by_campaign() -> None:
    """Per-campaign fetcher returns one entry per campaign with the
    matching baseline joined from the prior window.
    """
    from mureo.analytics.builtin._live_clients import (
        fetch_google_ads_per_campaign_metrics,
    )

    fake_client = AsyncMock()
    # Current: 2 campaigns. Baseline: same 2 campaigns + 1 ghost
    # ("camp_C" exists in prior but not current — must NOT appear in
    # the per-campaign dict because we only iterate current).
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [
                {
                    "campaign_id": "camp_A",
                    "cost": 100,
                    "impressions": 500,
                    "clicks": 30,
                    "conversions": 5,
                },
                {
                    "campaign_id": "camp_B",
                    "cost": 200,
                    "impressions": 1000,
                    "clicks": 60,
                    "conversions": 10,
                },
            ],
            [
                {
                    "campaign_id": "camp_A",
                    "cost": 80,
                    "impressions": 400,
                    "clicks": 24,
                    "conversions": 4,
                },
                {
                    "campaign_id": "camp_B",
                    "cost": 180,
                    "impressions": 900,
                    "clicks": 55,
                    "conversions": 9,
                },
                {
                    "campaign_id": "camp_C",
                    "cost": 50,
                    "impressions": 250,
                    "clicks": 15,
                    "conversions": 2,
                },
            ],
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_google_ads_client",
            return_value=fake_client,
        ),
    ):
        result = await fetch_google_ads_per_campaign_metrics("acct", window_days=7)

    assert set(result.keys()) == {"camp_A", "camp_B"}
    current_a, baseline_a = result["camp_A"]
    assert current_a.cost == 100
    assert baseline_a is not None
    assert baseline_a.cost == 80


@pytest.mark.asyncio
async def test_fetch_google_ads_per_campaign_metrics_baseline_none_for_new_campaign() -> (
    None
):
    """A campaign present in current but not in baseline (new
    campaign) gets ``baseline=None`` rather than a synthetic zero —
    that's the contract the pure detector expects.
    """
    from mureo.analytics.builtin._live_clients import (
        fetch_google_ads_per_campaign_metrics,
    )

    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [
                {
                    "campaign_id": "new_camp",
                    "cost": 100,
                    "impressions": 500,
                    "clicks": 30,
                    "conversions": 5,
                }
            ],
            [],  # no rows in baseline
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_google_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_google_ads_client",
            return_value=fake_client,
        ),
    ):
        result = await fetch_google_ads_per_campaign_metrics("acct", window_days=7)
    _, baseline = result["new_camp"]
    assert baseline is None


@pytest.mark.asyncio
async def test_fetch_meta_ads_per_campaign_metrics_keys_by_campaign() -> None:
    """Parallel of the Google per-campaign test for Meta."""
    from mureo.analytics.builtin._live_clients import (
        fetch_meta_ads_per_campaign_metrics,
    )

    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [
                {
                    "campaign_id": "c1",
                    "spend": 100,
                    "impressions": 500,
                    "clicks": 30,
                    "conversions": 5,
                },
            ],
            [
                {
                    "campaign_id": "c1",
                    "spend": 80,
                    "impressions": 400,
                    "clicks": 25,
                    "conversions": 4,
                },
            ],
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_meta_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_meta_ads_client",
            return_value=fake_client,
        ),
    ):
        result = await fetch_meta_ads_per_campaign_metrics("act_1", window_days=7)

    assert set(result.keys()) == {"c1"}
    current, baseline = result["c1"]
    assert current.cost == 100
    assert baseline is not None
    assert baseline.cost == 80


@pytest.mark.unit
def test_index_google_rows_drops_rows_without_campaign_id() -> None:
    """Rows missing a usable ``campaign_id`` are dropped rather than
    aggregated into a synthetic ``""``-keyed entry.
    """
    from mureo.analytics.builtin._live_clients import (
        _index_google_rows_by_campaign,
    )

    rows: list[dict[str, Any]] = [
        {"cost": 100, "impressions": 500},  # no campaign_id
        {"campaign_id": "", "cost": 100},  # empty campaign_id
        {
            "campaign_id": "valid",
            "cost": 200,
            "impressions": 800,
            "clicks": 50,
            "conversions": 8,
        },
    ]
    indexed = _index_google_rows_by_campaign(rows)
    assert set(indexed.keys()) == {"valid"}


@pytest.mark.unit
def test_index_google_rows_sums_repeated_campaign_id() -> None:
    """Multiple rows for the same campaign (day-grain) get summed."""
    from mureo.analytics.builtin._live_clients import (
        _index_google_rows_by_campaign,
    )

    rows: list[dict[str, Any]] = [
        {
            "campaign_id": "x",
            "cost": 100,
            "impressions": 500,
            "clicks": 30,
            "conversions": 5,
        },
        {
            "campaign_id": "x",
            "cost": 150,
            "impressions": 800,
            "clicks": 50,
            "conversions": 7,
        },
    ]
    indexed = _index_google_rows_by_campaign(rows)
    assert indexed["x"].cost == 250
    assert indexed["x"].clicks == 80
    assert indexed["x"].conversions == 12


@pytest.mark.asyncio
async def test_fetch_meta_ads_metrics_returns_current_and_baseline() -> None:
    fake_client = AsyncMock()
    fake_client.get_performance_report = AsyncMock(
        side_effect=[
            [{"spend": 100.0, "impressions": 500, "clicks": 20, "actions": []}],
            [{"spend": 200.0, "impressions": 1000, "clicks": 40, "actions": []}],
        ]
    )
    with (
        patch("mureo.byod.runtime.byod_has", return_value=False),
        patch("mureo.auth.load_meta_ads_credentials", return_value=object()),
        patch(
            "mureo.mcp._client_factory.get_meta_ads_client",
            return_value=fake_client,
        ),
    ):
        current, baseline = await fetch_meta_ads_metrics("act_x", window_days=7)

    assert current.cost == 100.0
    assert baseline is not None
    assert baseline.cost == 200.0
