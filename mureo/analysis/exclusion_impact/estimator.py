"""The estimate itself: how much of MY delivery does this exclusion remove?

Pure and I/O-free. The caller supplies the account's own recent delivery
rows and the entities a batch is about to exclude; this module answers with
a share per metric, and with an explicit verdict about what it could not
see.

Two figures, deliberately:

``incremental``
    The share attributable to the entities in THIS call.
``cumulative``
    The share attributable to the whole standing exclusion set once this
    call lands — the entities already excluded plus the new ones. This is
    the figure that catches incremental tightening, because an entity
    excluded a week ago still carries its pre-exclusion impressions inside
    a 30-day window. Its limit is the window: an exclusion older than the
    window contributed nothing to it and is therefore invisible. The
    cumulative share is a lower bound for that reason.

Zero total is not zero impact. When the window served nothing at all the
share is ``None``, not ``0.0`` — the batch may still be removing all of a
future recovery, and a printed ``0%`` reads as "safe".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.analysis.exclusion_impact.matching import target_matches
from mureo.analysis.exclusion_impact.models import (
    COVERAGE_MEASURED,
    COVERAGE_PARTIAL,
    COVERAGE_UNKNOWN,
    METRICS,
    DeliveryRecord,
    ExclusionImpact,
    ExclusionTarget,
    MetricShare,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Sequence


def _matched_indices(
    targets: Sequence[ExclusionTarget], records: Sequence[DeliveryRecord]
) -> tuple[set[int], set[int]]:
    """Return (record indices covered, target indices that covered something)."""
    covered: set[int] = set()
    hitting: set[int] = set()
    for t_index, target in enumerate(targets):
        for r_index, record in enumerate(records):
            if target_matches(target, record):
                covered.add(r_index)
                hitting.add(t_index)
    return covered, hitting


def _shares(
    records: Sequence[DeliveryRecord], covered: Collection[int]
) -> tuple[MetricShare, ...]:
    shares: list[MetricShare] = []
    for metric in METRICS:
        total = sum(record.metric(metric) for record in records)
        removed = sum(records[i].metric(metric) for i in covered)
        share = (removed / total * 100.0) if total > 0 else None
        shares.append(
            MetricShare(
                metric=metric,
                total=total,
                removed=removed,
                share_pct=share,
            )
        )
    return tuple(shares)


def _split_targets(
    targets: Iterable[ExclusionTarget], attributable_types: Collection[str]
) -> tuple[list[ExclusionTarget], list[ExclusionTarget]]:
    attributable: list[ExclusionTarget] = []
    unattributable: list[ExclusionTarget] = []
    for target in targets:
        bucket = (
            attributable if target.entity_type in attributable_types else unattributable
        )
        bucket.append(target)
    return attributable, unattributable


def _coverage(
    attributable: Sequence[ExclusionTarget],
    unattributable: Sequence[ExclusionTarget],
) -> str:
    if not attributable:
        return COVERAGE_UNKNOWN
    return COVERAGE_PARTIAL if unattributable else COVERAGE_MEASURED


def _unattributable_reason(
    unattributable: Sequence[ExclusionTarget], basis: str
) -> str:
    kinds = sorted({t.entity_type for t in unattributable})
    return (
        f"{len(unattributable)} of the excluded entities are of a kind "
        f"({', '.join(kinds)}) that '{basis}' does not attribute past "
        f"delivery to, so the reported share is a lower bound."
    )


def estimate_exclusion_impact(
    *,
    targets: Iterable[ExclusionTarget],
    records: Sequence[DeliveryRecord] | None,
    attributable_types: Collection[str],
    basis: str,
    window_days: int,
    standing: Iterable[ExclusionTarget] | None = None,
    coverage_reason: str = "",
    cumulative_reason: str = "",
) -> ExclusionImpact:
    """Compute the delivery share a batch of exclusions removes.

    Args:
        targets: The entities this call excludes.
        records: The account's own delivery in the window, or ``None`` when
            the platform cannot attribute delivery to these entities at
            all. ``None`` yields ``coverage='unknown'``; an EMPTY sequence
            is a measured "the window served nothing".
        attributable_types: Entity kinds ``records`` can speak about. A
            target outside this set is reported, never silently dropped.
        basis: What the denominator is, named for the operator (e.g.
            ``google_ads_group_placement_view``). Never "the campaign" —
            a placement report totals placement-attributed delivery only.
        window_days: The window ``records`` covers.
        standing: Entities already excluded on this scope, for the
            cumulative figure. ``None`` (not ``()``) means mureo could not
            list them, and the cumulative figure is withheld rather than
            reported as equal to the incremental one.
        coverage_reason: Why ``records`` is ``None``, in operator words.
        cumulative_reason: Why ``standing`` is ``None``, in operator words.
    """
    target_list = list(targets)
    attributable, unattributable = _split_targets(target_list, attributable_types)
    unattributable_values = tuple(t.value for t in unattributable)

    if records is None:
        return ExclusionImpact(
            coverage=COVERAGE_UNKNOWN,
            basis=basis,
            window_days=window_days,
            incremental=None,
            cumulative=None,
            unattributable_targets=unattributable_values,
            coverage_reason=coverage_reason
            or f"'{basis}' does not attribute past delivery to these entities.",
            cumulative_reason=cumulative_reason,
        )

    coverage = _coverage(attributable, unattributable)
    if coverage == COVERAGE_UNKNOWN:
        return ExclusionImpact(
            coverage=COVERAGE_UNKNOWN,
            basis=basis,
            window_days=window_days,
            incremental=None,
            cumulative=None,
            unattributable_targets=unattributable_values,
            coverage_reason=coverage_reason
            or _unattributable_reason(unattributable, basis),
            cumulative_reason=cumulative_reason,
        )

    covered, hitting = _matched_indices(attributable, records)
    incremental = _shares(records, covered)
    matched = tuple(dict.fromkeys(records[i].entity for i in sorted(covered)))
    unmatched = tuple(
        target.value
        for index, target in enumerate(attributable)
        if index not in hitting
    )

    cumulative: tuple[MetricShare, ...] | None = None
    if standing is not None:
        standing_attributable, _ = _split_targets(standing, attributable_types)
        standing_covered, _ = _matched_indices(standing_attributable, records)
        cumulative = _shares(records, covered | standing_covered)

    reason = coverage_reason
    if coverage == COVERAGE_PARTIAL and not reason:
        reason = _unattributable_reason(unattributable, basis)

    return ExclusionImpact(
        coverage=coverage,
        basis=basis,
        window_days=window_days,
        incremental=incremental,
        cumulative=cumulative,
        matched=matched,
        unmatched_targets=unmatched,
        unattributable_targets=unattributable_values,
        coverage_reason=reason,
        cumulative_reason=cumulative_reason if cumulative is None else "",
    )


__all__ = ["estimate_exclusion_impact"]
