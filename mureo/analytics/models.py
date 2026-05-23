"""Frozen data models returned by :class:`AnalyticsModule` methods.

All dataclasses are ``frozen=True`` per the repo-wide immutability rule.
Field names use stable, platform-agnostic vocabulary so a workflow skill
can present results from any platform with the same code path.

Severity follows the same two-tier scheme as
:mod:`mureo.analysis.anomaly_detector` (CRITICAL / HIGH) to avoid noise;
lower tiers can be added later if a real use case appears.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AnomalySeverity(str, Enum):
    """Anomaly severity. ``str`` mixin makes JSON serialization trivial.

    Mirrors :class:`mureo.analysis.anomaly_detector.Severity` so a
    built-in adapter can pass anomalies through unchanged.
    """

    CRITICAL = "critical"
    HIGH = "high"


@dataclass(frozen=True)
class Anomaly:
    """One detected anomaly with recommended follow-up."""

    campaign_id: str
    metric: str
    severity: AnomalySeverity
    current_value: float
    baseline_value: float | None
    deviation_pct: float | None
    sample_size: int
    message: str
    recommended_action: str


class PerformanceScope(str, Enum):
    """Diagnosis depth requested by the caller.

    A workflow skill picks scope based on the operation mode it is
    running under: TURNAROUND_RESCUE wants ``DEEP`` (per-ad-group /
    per-keyword), EFFICIENCY_STABILIZE wants ``ACCOUNT``.
    """

    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    DEEP = "deep"


@dataclass(frozen=True)
class PerformanceDiagnosis:
    """Result of :meth:`AnalyticsModule.diagnose_performance`.

    ``findings`` is a free-form list of short human-readable strings (UI
    is the skill's responsibility). ``metrics`` carries the structured
    numbers the skill may want to render in a table; key names should be
    stable per platform.
    """

    platform: str
    account_id: str
    scope: PerformanceScope
    headline: str
    findings: tuple[str, ...]
    metrics: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class CreativeFinding:
    """One issue or insight from :meth:`AnalyticsModule.audit_creative`."""

    asset_id: str
    asset_type: str
    severity: AnomalySeverity
    message: str
    recommended_action: str


@dataclass(frozen=True)
class CreativeAudit:
    """Result of :meth:`AnalyticsModule.audit_creative`."""

    platform: str
    account_id: str
    findings: tuple[CreativeFinding, ...] = ()


@dataclass(frozen=True)
class BudgetEfficiency:
    """Result of :meth:`AnalyticsModule.analyze_budget_efficiency`.

    ``per_campaign_score`` is keyed by ``campaign_id`` and ranges
    [0.0, 1.0] (1.0 = most efficient). ``rebalance_suggestion`` is a
    short human-readable recommendation; skills may use it verbatim or
    layer their own framing on top.
    """

    platform: str
    account_id: str
    per_campaign_score: tuple[tuple[str, float], ...] = ()
    rebalance_suggestion: str = ""
    unused_budget_amount: float = 0.0


__all__ = [
    "Anomaly",
    "AnomalySeverity",
    "BudgetEfficiency",
    "CreativeAudit",
    "CreativeFinding",
    "PerformanceDiagnosis",
    "PerformanceScope",
]
