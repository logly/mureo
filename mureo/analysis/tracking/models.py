"""Frozen, platform-neutral data models for tracking-parameter checks.

The core check knows exactly three things about an ad: which campaign
it lives in, where it sends the click, and (optionally) whether it has
delivered. Every platform accessor in :mod:`mureo.analysis.tracking.sources`
reduces its platform's record shape to :class:`AdTrackingRecord`, so no
platform-specific field name reaches the detector.

All dataclasses are ``frozen=True`` per the repo-wide immutability rule.
Severity mirrors :class:`mureo.analytics.models.AnomalySeverity`
(CRITICAL / HIGH) so a workflow skill renders tracking findings on the
same two-tier scale as anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrackingSeverity(str, Enum):
    """Severity of a tracking finding. ``str`` mixin keeps JSON trivial."""

    CRITICAL = "critical"
    HIGH = "high"


class DeliveryState(str, Enum):
    """Whether the ads a finding covers have actually served.

    The distinction is the whole point of grading these findings: a
    mis-tagged ad that has already served is a data-integrity incident
    that needs a reporting caveat, while one that has never served is a
    cheap fix. ``UNKNOWN`` is reported honestly rather than assumed —
    it means the caller did not supply per-ad delivery data, so the
    severity may be understated.
    """

    SERVED = "served"
    NOT_SERVED = "not_served"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AdTrackingRecord:
    """One ad reduced to what the tracking check needs.

    ``final_urls`` is empty when the platform's read surface does not
    expose the ad's destination URL (several bridged tool sets do not).
    Such an ad is never silently dropped: it is counted and named in
    :attr:`TrackingConsistencyReport.ads_without_readable_url`.

    ``impressions`` is ``None`` when the caller did not join delivery
    data — it is NOT the same as ``0``, and the two produce different
    severities.

    ``planned`` marks an ad that does not exist yet (pre-flight); it
    takes part in the analysis but is the only kind of ad a pre-flight
    run reports on.
    """

    ad_id: str
    campaign_id: str
    final_urls: tuple[str, ...] = ()
    platform: str = ""
    campaign_name: str = ""
    status: str = ""
    impressions: int | None = None
    planned: bool = False

    @property
    def delivery_state(self) -> DeliveryState:
        if self.impressions is None:
            return DeliveryState.UNKNOWN
        return (
            DeliveryState.SERVED if self.impressions > 0 else DeliveryState.NOT_SERVED
        )


@dataclass(frozen=True)
class TrackingFinding:
    """One tracking-consistency problem.

    ``code`` is drawn from a fixed vocabulary so a skill can branch on
    it; ``evidence`` carries the ordered key/value detail that makes the
    finding actionable (which parameter, which campaign owns the value,
    which landing page the schemes collided on). Values are strings so
    the finding serialises unchanged into an MCP JSON response.
    """

    code: str
    severity: TrackingSeverity
    delivery_state: DeliveryState
    platform: str
    campaign_id: str
    ad_ids: tuple[str, ...]
    message: str
    recommended_action: str
    evidence: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TrackingConsistencyReport:
    """Result of one consistency run.

    ``notes`` carries scope caveats the operator must see to read the
    findings correctly — most importantly that delivery data was absent,
    which caps every severity at HIGH.
    """

    findings: tuple[TrackingFinding, ...] = ()
    ads_examined: int = 0
    campaigns_examined: int = 0
    ads_without_readable_url: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrackingConvention:
    """An operator-declared tracking convention (opt-in, from STRATEGY.md).

    ``recognize`` extends the parameter names the zero-config checks
    read at all (glob patterns, e.g. ``utm_*``). ``identify`` extends
    the parameters whose values identify **which campaign** traffic came
    from — the only ones schemes are compared on — and ``differentiate``
    removes a default one from that set. ``require`` names the
    parameters every tagged final URL must carry; ``patterns`` maps a
    parameter name to the glob patterns its value must match (any one).

    Everything is opt-in: an account that declares nothing still gets
    the zero-config checks, and mureo never infers a convention.
    """

    recognize: tuple[str, ...] = ()
    identify: tuple[str, ...] = ()
    differentiate: tuple[str, ...] = ()
    require: tuple[str, ...] = ()
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = ()


__all__ = [
    "AdTrackingRecord",
    "DeliveryState",
    "TrackingConsistencyReport",
    "TrackingConvention",
    "TrackingFinding",
    "TrackingSeverity",
]
