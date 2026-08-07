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

# Delivery-collapse models (#546) are NOT mirrored here the way
# :class:`Anomaly` mirrors the detector's own dataclass. They are already
# platform-agnostic and carry no detector-internal type, so a second copy
# would only be two definitions to keep in sync. They are re-exported so
# a plugin implementing ``detect_delivery_collapse`` imports its result
# types from the same ABI module as every other analytics result.
from mureo.analysis.delivery_collapse import (
    BASELINE_SOURCE,
    BaselineMethod,
    CollapseSeverity,
    CollapseSignal,
    CollapseThresholds,
    DailyDelivery,
    DeliverySeries,
)


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

    ``per_campaign_metrics`` is populated when the diagnosis ran at
    :attr:`PerformanceScope.DEEP` — one entry per campaign as
    ``(campaign_id, ((metric_name, value), ...))``. Empty when the
    diagnosis ran at coarser scope, or when the adapter did not
    enumerate campaigns. The skill can do
    ``dict(diag.per_campaign_metrics)`` and then ``dict(...)`` on each
    value to drill in.
    """

    platform: str
    account_id: str
    scope: PerformanceScope
    headline: str
    findings: tuple[str, ...]
    metrics: tuple[tuple[str, float], ...] = ()
    per_campaign_metrics: tuple[tuple[str, tuple[tuple[str, float], ...]], ...] = ()


@dataclass(frozen=True)
class CreativeFinding:
    """One issue or insight from :meth:`AnalyticsModule.audit_creative`.

    ``campaign_id`` is the owning campaign when the platform's
    ``list_ads`` response includes it (it does on both Google and
    Meta, live and BYOD). Defaults to the empty string so an adapter
    that genuinely cannot resolve the campaign keeps the field stable
    and the workflow can branch on ``finding.campaign_id != ""``
    rather than catching ``AttributeError``.
    """

    asset_id: str
    asset_type: str
    severity: AnomalySeverity
    message: str
    recommended_action: str
    campaign_id: str = ""


@dataclass(frozen=True)
class CreativeAudit:
    """Result of :meth:`AnalyticsModule.audit_creative`.

    ``per_campaign_summary`` is a deterministically-sorted list of
    ``(campaign_id, finding_count)`` pairs that lets a workflow skill
    say "campaign X has 3 RSA issues" without walking every finding
    twice. Empty when no findings carry a campaign_id (rare today;
    expected when a platform's ``list_ads`` omits the campaign join).
    """

    platform: str
    account_id: str
    findings: tuple[CreativeFinding, ...] = ()
    per_campaign_summary: tuple[tuple[str, int], ...] = ()


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


@dataclass(frozen=True)
class DeliveryCollapseReport:
    """Result of :meth:`AnalyticsModule.detect_delivery_collapse` (#546).

    ``status`` is the honest three-way outcome, and the distinction
    matters more here than anywhere else in this module: an empty
    ``signals`` tuple means "checked, nothing collapsed" ONLY when
    ``status`` is ``"ok"``. The other two states are why the field
    exists at all — rendering a credentials problem or a platform that
    cannot produce day-grain delivery as "no signals" would be a false
    all-clear on an account that may well be dead.

    - ``"ok"`` — the account was evaluated; ``signals`` is authoritative.
    - ``"no_credentials"`` — credentials are absent or the account is
      outside the active workspace scope; nothing was evaluated.
    - ``"data_unavailable"`` — the platform (or the active data source,
      e.g. a BYOD bundle without a daily tab) cannot produce day-grain
      delivery, so no baseline can be built.

    ``reported_through`` / ``unreported_days`` carry the one case the
    detector deliberately has no opinion on. A missing day only counts as
    zero delivery where the report proves the platform covered it; when
    EVERY campaign stops on the same day, nothing proves anything, and a
    total account outage is indistinguishable from a platform-wide
    reporting failure. Rather than guess, the gap is reported: an account
    whose ``unreported_days`` keeps climbing is a finding in its own
    right, and the caller says so instead of reading an empty ``signals``
    tuple as "all healthy".
    """

    platform: str
    account_id: str
    status: str
    detail: str = ""
    evaluated_campaigns: int = 0
    signals: tuple[CollapseSignal, ...] = ()
    thresholds: CollapseThresholds = CollapseThresholds()
    thresholds_source: str = ""
    baseline_source: str = BASELINE_SOURCE
    #: Latest date the platform reported ANY delivery (ISO, "" when none).
    reported_through: str = ""
    #: Complete days between ``reported_through`` and the evaluation date
    #: that the platform has not reported at all. 0 is the healthy case.
    unreported_days: int = 0


__all__ = [
    "BASELINE_SOURCE",
    "Anomaly",
    "AnomalySeverity",
    "BaselineMethod",
    "BudgetEfficiency",
    "CollapseSeverity",
    "CollapseSignal",
    "CollapseThresholds",
    "CreativeAudit",
    "CreativeFinding",
    "DailyDelivery",
    "DeliveryCollapseReport",
    "DeliverySeries",
    "PerformanceDiagnosis",
    "PerformanceScope",
]
