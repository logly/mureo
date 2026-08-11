"""Platform-neutral value types for the exclusion delivery-impact preview.

One vocabulary for every inventory-restriction surface mureo touches —
excluded placements, excluded apps, negative keywords, blocked adspots,
publisher block lists — so the estimator itself never learns a platform.

Three coverage verdicts, and the distinction between them is the point of
the feature:

``measured``
    Every entity in the batch is of a kind this delivery basis can
    attribute. The reported shares are the account's own numbers.
``partial``
    Some entities are of a kind the basis cannot attribute at all (a
    Google Ads *mobile app category* against a placement report, say —
    categories are not themselves placements that serve). The shares are
    real but are a LOWER bound on what the batch removes.
``unknown``
    Nothing in the batch can be attributed. Reported honestly; never
    rendered as "0% impact", because a false "this removes nothing" is
    read as approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The four metrics a share is computed for. Order is the reporting order.
METRICS: tuple[str, ...] = ("impressions", "clicks", "cost", "conversions")

COVERAGE_MEASURED = "measured"
COVERAGE_PARTIAL = "partial"
COVERAGE_UNKNOWN = "unknown"

#: Entity kinds mureo names itself. A plugin may use any other string; the
#: estimator compares kinds, it does not enumerate them.
ENTITY_WEBSITE = "website"
ENTITY_MOBILE_APPLICATION = "mobile_application"
ENTITY_MOBILE_APP_CATEGORY = "mobile_app_category"
ENTITY_SEARCH_TERM = "search_term"


@dataclass(frozen=True)
class DeliveryRecord:
    """One row of the account's OWN recent delivery, keyed by entity.

    ``entity`` is whatever the platform's report calls the placement /
    search term / adspot; normalization happens at match time, so a row is
    stored exactly as reported.
    """

    entity: str
    entity_type: str
    impressions: float = 0.0
    clicks: float = 0.0
    cost: float = 0.0
    conversions: float = 0.0

    def metric(self, name: str) -> float:
        return float(getattr(self, name))


@dataclass(frozen=True)
class ExclusionTarget:
    """One entity a batch is about to exclude, block, or negate.

    ``match_type`` carries a negative keyword's ``EXACT`` / ``PHRASE`` /
    ``BROAD``; it is ``None`` for every surface whose entities are matched
    by identity rather than by text.
    """

    value: str
    entity_type: str
    match_type: str | None = None


@dataclass(frozen=True)
class MetricShare:
    """How much of one metric a batch removes, in the measured window."""

    metric: str
    total: float
    removed: float
    share_pct: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "removed": self.removed,
            "share_pct": self.share_pct,
        }


def _shares_as_dict(
    shares: tuple[MetricShare, ...] | None,
) -> dict[str, Any] | None:
    if shares is None:
        return None
    return {share.metric: share.as_dict() for share in shares}


def _pct(shares: tuple[MetricShare, ...] | None, metric: str) -> float | None:
    if shares is None:
        return None
    for share in shares:
        if share.metric == metric:
            return share.share_pct
    return None


@dataclass(frozen=True)
class ExclusionImpact:
    """What a batch of exclusions removes from the account's own delivery.

    ``incremental`` is what THIS batch removes. ``cumulative`` is what the
    account's whole standing exclusion set removes once this batch lands —
    the figure the incremental one hides, because the incident that
    motivated #547 was two weeks of individually-small passes.

    Either may be ``None``, and ``None`` never means zero:
    ``incremental is None`` ⇔ coverage is ``unknown``; ``cumulative is
    None`` means the standing set could not be listed, with the reason in
    ``cumulative_reason``.
    """

    coverage: str
    basis: str
    window_days: int
    incremental: tuple[MetricShare, ...] | None
    cumulative: tuple[MetricShare, ...] | None = None
    matched: tuple[str, ...] = ()
    unmatched_targets: tuple[str, ...] = ()
    unattributable_targets: tuple[str, ...] = ()
    coverage_reason: str = ""
    cumulative_reason: str = ""

    def share_pct(self, metric: str) -> float | None:
        """Incremental share of ``metric``, or ``None`` when not computable."""
        return _pct(self.incremental, metric)

    def cumulative_share_pct(self, metric: str) -> float | None:
        """Cumulative share of ``metric``, or ``None`` when not computable."""
        return _pct(self.cumulative, metric)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coverage": self.coverage,
            "coverage_reason": self.coverage_reason,
            "basis": self.basis,
            "window_days": self.window_days,
            "incremental": _shares_as_dict(self.incremental),
            "cumulative": _shares_as_dict(self.cumulative),
            "cumulative_reason": self.cumulative_reason,
            "matched_entities": list(self.matched),
            "unmatched_targets": list(self.unmatched_targets),
            "unattributable_targets": list(self.unattributable_targets),
        }


__all__ = [
    "COVERAGE_MEASURED",
    "COVERAGE_PARTIAL",
    "COVERAGE_UNKNOWN",
    "ENTITY_MOBILE_APPLICATION",
    "ENTITY_MOBILE_APP_CATEGORY",
    "ENTITY_SEARCH_TERM",
    "ENTITY_WEBSITE",
    "METRICS",
    "DeliveryRecord",
    "ExclusionImpact",
    "ExclusionTarget",
    "MetricShare",
]
