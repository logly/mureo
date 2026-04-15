"""Anomaly detection for marketing campaign metrics.

Pure, I/O-free detection logic. Given a point-in-time
:class:`CampaignMetrics` snapshot and (optionally) a baseline built
from historical ``action_log`` entries, return a prioritized list of
:class:`Anomaly` objects describing what broke and what to do about
it.

Scope (2026-04 X research):
- Zero spend on a previously-spending campaign → CRITICAL
- CPA spike ≥ 1.5× baseline, gated by 30+ conversions
- CTR drop ≤ 0.5× baseline, gated by 1000+ impressions

Gates come from the mureo-learning skill's sample-size rules: below
these thresholds, a single bad day is noise and must not trigger an
alert.

This module deliberately does *not* touch the network, the filesystem,
or ``STATE.json``. Callers fetch metrics, build baselines, and act on
the returned anomalies.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mureo.context.models import ActionLogEntry

CPA_SPIKE_RATIO = 1.5
CPA_SPIKE_CRITICAL_RATIO = 2.0
CPA_MIN_CONVERSIONS = 30

CTR_DROP_RATIO = 0.5
CTR_DROP_CRITICAL_RATIO = 0.3
CTR_MIN_IMPRESSIONS = 1000


class Severity(str, Enum):
    """Ordered severity levels. ``str`` mixin makes JSON serialization trivial.

    Only CRITICAL and HIGH are emitted today. A lower tier (e.g. MEDIUM
    for mild deviations) can be added if a real use case appears —
    adding it prematurely invites the sample-size noise this module is
    designed to suppress.
    """

    CRITICAL = "critical"
    HIGH = "high"


_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
}


@dataclass(frozen=True)
class CampaignMetrics:
    """Point-in-time metrics for one campaign.

    CPA and CTR can be passed explicitly (preferred — the API may
    round differently than a naive division) or derived from the raw
    counters.
    """

    campaign_id: str
    cost: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    cpa: float | None = None
    ctr: float | None = None

    def derived_cpa(self) -> float | None:
        if self.cpa is not None:
            return self.cpa
        if self.conversions <= 0:
            return None
        return self.cost / self.conversions

    def derived_ctr(self) -> float | None:
        if self.ctr is not None:
            return self.ctr
        if self.impressions <= 0:
            return None
        return self.clicks / self.impressions


@dataclass(frozen=True)
class Anomaly:
    """A single detected anomaly with recommended follow-up."""

    campaign_id: str
    metric: str
    severity: Severity
    current_value: float
    baseline_value: float | None
    deviation_pct: float | None
    sample_size: int
    message: str
    recommended_action: str


def detect_anomalies(
    current: CampaignMetrics,
    baseline: CampaignMetrics | None,
    *,
    had_prior_spend: bool = True,
) -> list[Anomaly]:
    """Compare ``current`` against ``baseline`` and return prioritized anomalies.

    ``had_prior_spend`` tells us whether zero spend is suspicious; a
    fresh campaign that never spent before should not trigger that
    alert. Pass ``False`` for brand-new campaigns. When ``baseline``
    is provided and its own ``cost`` is zero (paused campaign, weekend
    dayparting), zero-spend is suppressed regardless of the flag.
    """
    anomalies: list[Anomaly] = []

    zero_spend = _check_zero_spend(current, baseline, had_prior_spend)
    if zero_spend is not None:
        anomalies.append(zero_spend)

    if baseline is not None:
        cpa = _check_cpa_spike(current, baseline)
        if cpa is not None:
            anomalies.append(cpa)

        ctr = _check_ctr_drop(current, baseline)
        if ctr is not None:
            anomalies.append(ctr)

    anomalies.sort(key=lambda a: _SEVERITY_ORDER[a.severity])
    return anomalies


def _check_zero_spend(
    current: CampaignMetrics,
    baseline: CampaignMetrics | None,
    had_prior_spend: bool,
) -> Anomaly | None:
    if current.cost > 0 or not had_prior_spend:
        return None
    # If baseline itself had zero spend, the campaign was already paused/inactive;
    # alerting would be noise.
    if baseline is not None and baseline.cost <= 0:
        return None
    return Anomaly(
        campaign_id=current.campaign_id,
        metric="cost",
        severity=Severity.CRITICAL,
        current_value=0.0,
        baseline_value=None,
        deviation_pct=None,
        sample_size=0,
        message="支出がゼロです。配信が停止している可能性があります。",
        recommended_action=(
            "キャンペーンの配信ステータス、予算残高、入札・ポリシー制限を確認してください。"
        ),
    )


def _check_cpa_spike(
    current: CampaignMetrics, baseline: CampaignMetrics
) -> Anomaly | None:
    current_cpa = current.derived_cpa()
    baseline_cpa = baseline.derived_cpa()
    if current_cpa is None or baseline_cpa is None or baseline_cpa <= 0:
        return None
    # Gate on whichever side has enough conversions: if current collapsed to
    # 20/day from a 200/day baseline, the baseline's sample is what gives us
    # confidence the spike isn't noise.
    if max(current.conversions, baseline.conversions) < CPA_MIN_CONVERSIONS:
        return None

    ratio = current_cpa / baseline_cpa
    if ratio < CPA_SPIKE_RATIO:
        return None

    severity = Severity.CRITICAL if ratio >= CPA_SPIKE_CRITICAL_RATIO else Severity.HIGH
    deviation_pct = ratio - 1.0
    return Anomaly(
        campaign_id=current.campaign_id,
        metric="cpa",
        severity=severity,
        current_value=current_cpa,
        baseline_value=baseline_cpa,
        deviation_pct=deviation_pct,
        sample_size=round(current.conversions),
        message=(
            f"CPAがベースラインの{ratio:.2f}倍に上昇しました "
            f"(current={current_cpa:.0f}, baseline={baseline_cpa:.0f})。"
        ),
        recommended_action=(
            "高CPAキーワード・検索語句の特定と停止、または入札調整を検討してください。"
        ),
    )


def _check_ctr_drop(
    current: CampaignMetrics, baseline: CampaignMetrics
) -> Anomaly | None:
    current_ctr = current.derived_ctr()
    baseline_ctr = baseline.derived_ctr()
    if current_ctr is None or baseline_ctr is None or baseline_ctr <= 0:
        return None
    if max(current.impressions, baseline.impressions) < CTR_MIN_IMPRESSIONS:
        return None

    ratio = current_ctr / baseline_ctr
    if ratio > CTR_DROP_RATIO:
        return None

    severity = Severity.CRITICAL if ratio <= CTR_DROP_CRITICAL_RATIO else Severity.HIGH
    deviation_pct = ratio - 1.0
    return Anomaly(
        campaign_id=current.campaign_id,
        metric="ctr",
        severity=severity,
        current_value=current_ctr,
        baseline_value=baseline_ctr,
        deviation_pct=deviation_pct,
        sample_size=current.impressions,
        message=(
            f"CTRがベースラインの{ratio:.2f}倍まで低下しました "
            f"(current={current_ctr:.3%}, baseline={baseline_ctr:.3%})。"
        ),
        recommended_action=(
            "広告文の刷新、検索語句レビュー、マッチタイプ・ネガティブキーワードの見直しを検討してください。"
        ),
    )


def baseline_from_history(
    campaign_id: str,
    action_log: Iterable[ActionLogEntry],
    *,
    min_entries: int = 7,
) -> CampaignMetrics | None:
    """Build a baseline by taking the median of historical ``metrics_at_action``.

    Median — not mean — because a single outlier entry (e.g. a rescue
    action during a CPA spike) would otherwise pull the baseline
    toward the bad state and suppress future alerts.

    Ratio metrics (CPA, CTR) are computed **per entry first** and then
    medianed, so the returned baseline CPA is a real median daily CPA
    rather than ``median(cost) / median(conversions)`` — those two can
    diverge on noisy days and mismatch the real historical reality.

    Returns ``None`` if fewer than ``min_entries`` usable entries
    exist. Default is 7 (one week) — enough that median resists one
    or two outlier days. Callers that deliberately want a tighter
    window can pass a smaller ``min_entries``.
    """
    relevant = [
        entry.metrics_at_action
        for entry in action_log
        if entry.campaign_id == campaign_id and entry.metrics_at_action is not None
    ]
    if len(relevant) < min_entries:
        return None

    def _numeric(m: dict[str, Any], key: str) -> float | None:
        # Tolerate malformed entries (string-typed values, "N/A", empty strings)
        # that can appear when action_log is loaded from JSON written by a
        # platform with inconsistent typing. One bad row must not take out the
        # whole baseline.
        raw = m.get(key)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _median_of(values: list[float]) -> float | None:
        return statistics.median(values) if values else None

    per_entry_cpas: list[float] = []
    per_entry_ctrs: list[float] = []
    for m in relevant:
        cpa = _numeric(m, "cpa")
        if cpa is None:
            cost = _numeric(m, "cost")
            conv = _numeric(m, "conversions")
            if cost is not None and conv is not None and conv > 0:
                cpa = cost / conv
        if cpa is not None:
            per_entry_cpas.append(cpa)

        ctr = _numeric(m, "ctr")
        if ctr is None:
            clicks = _numeric(m, "clicks")
            impressions = _numeric(m, "impressions")
            if clicks is not None and impressions is not None and impressions > 0:
                ctr = clicks / impressions
        if ctr is not None:
            per_entry_ctrs.append(ctr)

    costs = [v for v in (_numeric(m, "cost") for m in relevant) if v is not None]
    imps = [v for v in (_numeric(m, "impressions") for m in relevant) if v is not None]
    clks = [v for v in (_numeric(m, "clicks") for m in relevant) if v is not None]
    convs = [v for v in (_numeric(m, "conversions") for m in relevant) if v is not None]

    return CampaignMetrics(
        campaign_id=campaign_id,
        cost=_median_of(costs) or 0.0,
        impressions=int(_median_of(imps) or 0),
        clicks=int(_median_of(clks) or 0),
        conversions=_median_of(convs) or 0.0,
        cpa=_median_of(per_entry_cpas),
        ctr=_median_of(per_entry_ctrs),
    )
