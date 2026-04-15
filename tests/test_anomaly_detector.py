"""Anomaly detector tests.

Pure detection functions: no I/O, no mocks. Exercises the three
signals prioritized by the 2026-04 X research — zero spend, CPA
spike, CTR drop — plus sample-size and severity rules.
"""

from __future__ import annotations

import pytest

from mureo.analysis.anomaly_detector import (
    CPA_MIN_CONVERSIONS,
    CTR_MIN_IMPRESSIONS,
    Anomaly,
    CampaignMetrics,
    Severity,
    baseline_from_history,
    detect_anomalies,
)
from mureo.context.models import ActionLogEntry


def _metrics(
    campaign_id: str = "123",
    *,
    cost: float = 10000,
    impressions: int = 5000,
    clicks: int = 200,
    conversions: float = 50,
    cpa: float | None = None,
    ctr: float | None = None,
) -> CampaignMetrics:
    return CampaignMetrics(
        campaign_id=campaign_id,
        cost=cost,
        impressions=impressions,
        clicks=clicks,
        conversions=conversions,
        cpa=cpa,
        ctr=ctr,
    )


@pytest.mark.unit
class TestCampaignMetrics:
    def test_derived_cpa(self) -> None:
        m = _metrics(cost=1000, conversions=10)
        assert m.derived_cpa() == 100

    def test_derived_cpa_zero_conversions(self) -> None:
        m = _metrics(cost=1000, conversions=0)
        assert m.derived_cpa() is None

    def test_derived_ctr(self) -> None:
        m = _metrics(clicks=50, impressions=1000)
        assert m.derived_ctr() == 0.05

    def test_derived_ctr_zero_impressions(self) -> None:
        m = _metrics(clicks=0, impressions=0)
        assert m.derived_ctr() is None

    def test_explicit_cpa_wins(self) -> None:
        m = _metrics(cost=1000, conversions=10, cpa=200)
        assert m.derived_cpa() == 200


@pytest.mark.unit
class TestZeroSpendDetection:
    def test_zero_spend_with_prior_spend_flagged(self) -> None:
        current = _metrics(cost=0, impressions=0, clicks=0, conversions=0)
        baseline = _metrics(cost=10000, conversions=50)
        anomalies = detect_anomalies(current, baseline, had_prior_spend=True)
        zero_spend = [a for a in anomalies if a.metric == "cost"]
        assert len(zero_spend) == 1
        assert zero_spend[0].severity == Severity.CRITICAL

    def test_zero_spend_without_prior_not_flagged(self) -> None:
        current = _metrics(cost=0)
        anomalies = detect_anomalies(current, None, had_prior_spend=False)
        assert not any(a.metric == "cost" for a in anomalies)

    def test_zero_spend_no_baseline_but_prior_flag_still_fires(self) -> None:
        current = _metrics(cost=0)
        anomalies = detect_anomalies(current, None, had_prior_spend=True)
        assert any(a.metric == "cost" for a in anomalies)

    def test_zero_spend_suppressed_when_baseline_also_zero(self) -> None:
        # Paused campaign or weekend dayparting — the "zero now" state was
        # already the historical norm, so alerting is noise.
        current = _metrics(cost=0)
        baseline = _metrics(cost=0, conversions=0)
        anomalies = detect_anomalies(current, baseline, had_prior_spend=True)
        assert not any(a.metric == "cost" for a in anomalies)


@pytest.mark.unit
class TestCPASpikeDetection:
    def test_spike_above_threshold_flagged(self) -> None:
        baseline = _metrics(cpa=1000)
        current = _metrics(cost=80_000, conversions=40, cpa=2000)
        anomalies = detect_anomalies(current, baseline)
        cpa = [a for a in anomalies if a.metric == "cpa"]
        assert len(cpa) == 1
        assert cpa[0].current_value == 2000
        assert cpa[0].baseline_value == 1000

    def test_spike_under_sample_size_suppressed(self) -> None:
        # Both current and baseline below threshold — no confidence either way.
        baseline = _metrics(conversions=10, cpa=1000)
        current = _metrics(cost=20_000, conversions=10, cpa=2000)
        anomalies = detect_anomalies(current, baseline)
        assert not any(a.metric == "cpa" for a in anomalies)
        assert CPA_MIN_CONVERSIONS == 30

    def test_spike_severity_scales(self) -> None:
        baseline = _metrics(cpa=1000)
        critical = detect_anomalies(_metrics(conversions=40, cpa=2500), baseline)
        assert any(
            a.metric == "cpa" and a.severity == Severity.CRITICAL for a in critical
        )
        high = detect_anomalies(_metrics(conversions=40, cpa=1600), baseline)
        assert any(a.metric == "cpa" and a.severity == Severity.HIGH for a in high)

    def test_spike_within_tolerance_not_flagged(self) -> None:
        baseline = _metrics(cpa=1000)
        current = _metrics(conversions=40, cpa=1100)
        anomalies = detect_anomalies(current, baseline)
        assert not any(a.metric == "cpa" for a in anomalies)

    def test_baseline_conversions_count_toward_sample_size(self) -> None:
        # Current conversions collapsed to 20, but baseline averaged 200/day.
        # The spike is real — the sample-size gate should rely on baseline.
        baseline = _metrics(conversions=200, cpa=1000)
        current = _metrics(conversions=20, cpa=2500)
        anomalies = detect_anomalies(current, baseline)
        assert any(a.metric == "cpa" for a in anomalies)


@pytest.mark.unit
class TestCTRDropDetection:
    def test_drop_below_threshold_flagged(self) -> None:
        baseline = _metrics(ctr=0.04)
        current = _metrics(impressions=10_000, clicks=100, ctr=0.01)
        anomalies = detect_anomalies(current, baseline)
        ctr = [a for a in anomalies if a.metric == "ctr"]
        assert len(ctr) == 1
        assert ctr[0].severity in (Severity.HIGH, Severity.CRITICAL)

    def test_drop_under_sample_size_suppressed(self) -> None:
        baseline = _metrics(impressions=500, ctr=0.04)
        current = _metrics(impressions=500, clicks=5, ctr=0.01)
        anomalies = detect_anomalies(current, baseline)
        assert not any(a.metric == "ctr" for a in anomalies)
        assert CTR_MIN_IMPRESSIONS == 1000

    def test_drop_severity_scales(self) -> None:
        baseline = _metrics(ctr=0.04)
        critical = detect_anomalies(_metrics(impressions=10_000, ctr=0.01), baseline)
        assert any(
            a.metric == "ctr" and a.severity == Severity.CRITICAL for a in critical
        )
        high = detect_anomalies(_metrics(impressions=10_000, ctr=0.018), baseline)
        assert any(a.metric == "ctr" and a.severity == Severity.HIGH for a in high)

    def test_drop_within_tolerance_not_flagged(self) -> None:
        baseline = _metrics(ctr=0.04)
        current = _metrics(impressions=10_000, ctr=0.035)
        anomalies = detect_anomalies(current, baseline)
        assert not any(a.metric == "ctr" for a in anomalies)


@pytest.mark.unit
class TestAnomalyPrioritization:
    def test_sorted_by_severity_critical_first(self) -> None:
        baseline = _metrics(cpa=1000, ctr=0.04)
        current = _metrics(impressions=10_000, conversions=40, cpa=2500, ctr=0.018)
        anomalies = detect_anomalies(current, baseline)
        assert len(anomalies) >= 2
        assert anomalies[0].severity == Severity.CRITICAL

    def test_no_anomalies_returns_empty_list(self) -> None:
        baseline = _metrics(cpa=1000, ctr=0.04)
        current = _metrics(conversions=40, cpa=1000, ctr=0.04)
        assert detect_anomalies(current, baseline) == []


@pytest.mark.unit
class TestBaselineFromHistory:
    def _log(self, ts: str, cpa: float, ctr: float = 0.03) -> ActionLogEntry:
        return ActionLogEntry(
            timestamp=ts,
            action="update",
            platform="google_ads",
            campaign_id="123",
            metrics_at_action={
                "cpa": cpa,
                "ctr": ctr,
                "cost": 10_000,
                "conversions": 50,
                "impressions": 10_000,
                "clicks": 300,
            },
        )

    def test_median_of_history(self) -> None:
        log = (
            self._log("2026-04-01", 800),
            self._log("2026-04-05", 1000),
            self._log("2026-04-10", 1200),
        )
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 1000

    def test_filters_by_campaign_id(self) -> None:
        other = ActionLogEntry(
            timestamp="2026-04-01",
            action="update",
            platform="google_ads",
            campaign_id="999",
            metrics_at_action={"cpa": 99_999},
        )
        log = (
            other,
            self._log("2026-04-02", 1000),
            self._log("2026-04-03", 1000),
            self._log("2026-04-04", 1000),
        )
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 1000

    def test_insufficient_entries_returns_none(self) -> None:
        log = (self._log("2026-04-01", 1000),)
        assert baseline_from_history("123", log, min_entries=3) is None

    def test_default_min_entries_is_week(self) -> None:
        # Six days of history is not enough for the default; caller must opt
        # into a tighter window explicitly.
        log = tuple(self._log(f"2026-04-0{i}", 1000) for i in range(1, 7))
        assert baseline_from_history("123", log) is None
        log_week = tuple(self._log(f"2026-04-0{i}", 1000) for i in range(1, 8))
        assert baseline_from_history("123", log_week) is not None

    def test_cpa_medianed_per_entry_not_from_mixed_medians(self) -> None:
        # Entries are constructed so that median(cost)/median(conv) differs
        # from median of per-entry CPAs. Per-entry is the honest answer.
        def _e(cost: float, conv: float) -> ActionLogEntry:
            return ActionLogEntry(
                timestamp="2026-04-01",
                action="update",
                platform="google_ads",
                campaign_id="123",
                metrics_at_action={"cost": cost, "conversions": conv},
            )

        # per-entry CPAs: 10, 50, 1 → median = 10
        # independently: median(cost)=100, median(conv)=20 → 100/20 = 5
        log = (_e(100, 10), _e(1000, 20), _e(20, 20))
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 10

    def test_tolerates_string_values_from_json(self) -> None:
        # action_log round-tripped through JSON may arrive with string numerics
        # ("1000") or sentinels ("N/A"). One bad row must not take out the
        # baseline.
        bad = ActionLogEntry(
            timestamp="2026-04-01",
            action="update",
            platform="google_ads",
            campaign_id="123",
            metrics_at_action={"cpa": "N/A", "ctr": 0.03},
        )
        log = (
            bad,
            self._log("2026-04-02", 1000),
            self._log("2026-04-03", 1000),
            self._log("2026-04-04", 1000),
        )
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 1000

    def test_accepts_string_numerics(self) -> None:
        stringy = ActionLogEntry(
            timestamp="2026-04-01",
            action="update",
            platform="google_ads",
            campaign_id="123",
            metrics_at_action={"cpa": "1500", "cost": "20000"},
        )
        log = (
            stringy,
            self._log("2026-04-02", 1000),
            self._log("2026-04-03", 1000),
        )
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 1000  # median of [1000, 1000, 1500]

    def test_ignores_entries_without_metrics(self) -> None:
        no_metrics = ActionLogEntry(
            timestamp="2026-04-01",
            action="update",
            platform="google_ads",
            campaign_id="123",
        )
        log = (
            no_metrics,
            self._log("2026-04-02", 1000),
            self._log("2026-04-03", 1100),
            self._log("2026-04-04", 900),
        )
        baseline = baseline_from_history("123", log, min_entries=3)
        assert baseline is not None
        assert baseline.cpa == 1000


@pytest.mark.unit
class TestAnomalyFields:
    def test_anomaly_is_frozen_dataclass(self) -> None:
        a = Anomaly(
            campaign_id="123",
            metric="cpa",
            severity=Severity.HIGH,
            current_value=2000.0,
            baseline_value=1000.0,
            deviation_pct=1.0,
            sample_size=40,
            message="CPA has spiked 100% above baseline.",
            recommended_action="Pause high-CPA keywords or review bids.",
        )
        with pytest.raises(AttributeError):
            a.severity = Severity.CRITICAL  # type: ignore[misc]

    def test_severity_values_stable(self) -> None:
        # Only CRITICAL and HIGH are emitted today. MEDIUM was removed from
        # the enum to avoid dead API surface.
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert not hasattr(Severity, "MEDIUM")
