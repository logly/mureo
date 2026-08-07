"""Public entry points for the tracking-parameter consistency check.

Two callers, one detector:

- :func:`check_tracking_consistency` — the account-wide audit
  (``/tracking-health``). Reports everything it finds.
- :func:`preflight_tracking_consistency` — the pre-upload check. Runs
  the same detector over the account *plus* the ads about to be
  created, then reports only what the new ads are responsible for. An
  operator uploading one ad is never handed the account's backlog.

The detector is platform-neutral: it compares ads only against other
ads on the same platform, and it only ever sees
:class:`~mureo.analysis.tracking.models.AdTrackingRecord`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.analysis.tracking._checks_completeness import (
    convention_findings,
    presence_findings,
)
from mureo.analysis.tracking._checks_scheme import (
    foreign_campaign_scheme_findings,
    same_destination_conflict_findings,
)
from mureo.analysis.tracking._views import (
    build_views,
    resolve_identifying,
    resolve_recognized,
)
from mureo.analysis.tracking.models import (
    DeliveryState,
    TrackingConsistencyReport,
    TrackingFinding,
    TrackingSeverity,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mureo.analysis.tracking._views import AdView
    from mureo.analysis.tracking.models import AdTrackingRecord, TrackingConvention

_SEVERITY_ORDER = {TrackingSeverity.CRITICAL: 0, TrackingSeverity.HIGH: 1}

_UNKNOWN_DELIVERY_NOTE = (
    "Per-ad delivery data was not supplied for every ad, so findings marked "
    "delivery_state=unknown may be understated: a mis-tagged ad that has "
    "already served is a data-integrity incident, not a cheap fix."
)


def check_tracking_consistency(
    records: Sequence[AdTrackingRecord],
    *,
    convention: TrackingConvention | None = None,
) -> TrackingConsistencyReport:
    """Audit ``records`` for tracking-parameter inconsistency.

    ``records`` may mix platforms; ads are only ever compared with ads
    on the same platform. An ad whose destination URL the caller could
    not read is counted and named rather than dropped.
    """
    views = build_views(
        records,
        resolve_recognized(convention),
        resolve_identifying(convention),
    )
    findings = _run_checks(views, convention)
    return TrackingConsistencyReport(
        findings=_ordered(findings),
        ads_examined=len(views),
        campaigns_examined=len({view.key for view in views}),
        ads_without_readable_url=tuple(
            view.ad_id for view in views if not view.has_readable_url
        ),
        notes=_notes(views),
    )


def preflight_tracking_consistency(
    planned: Sequence[AdTrackingRecord],
    existing: Sequence[AdTrackingRecord],
    *,
    convention: TrackingConvention | None = None,
) -> TrackingConsistencyReport:
    """Check ads about to be created against the account they land in.

    Only findings a planned ad takes part in are returned, and each is
    re-projected onto the planned ads: the existing ads that provided
    the evidence move into ``evidence["conflicting_ad_ids"]``.
    """
    planned_records = tuple(
        record if record.planned else _as_planned(record) for record in planned
    )
    planned_ids = {record.ad_id for record in planned_records}
    report = check_tracking_consistency(
        [*existing, *planned_records], convention=convention
    )
    findings = tuple(
        _project_onto_planned(finding, planned_ids)
        for finding in report.findings
        if planned_ids & set(finding.ad_ids)
    )
    return TrackingConsistencyReport(
        findings=findings,
        ads_examined=report.ads_examined,
        campaigns_examined=report.campaigns_examined,
        ads_without_readable_url=tuple(
            ad_id for ad_id in report.ads_without_readable_url if ad_id in planned_ids
        ),
        notes=report.notes,
    )


def _as_planned(record: AdTrackingRecord) -> AdTrackingRecord:
    from dataclasses import replace

    return replace(record, planned=True)


def _project_onto_planned(
    finding: TrackingFinding, planned_ids: set[str]
) -> TrackingFinding:
    from dataclasses import replace

    mine = tuple(ad_id for ad_id in finding.ad_ids if ad_id in planned_ids)
    others = tuple(ad_id for ad_id in finding.ad_ids if ad_id not in planned_ids)
    evidence = finding.evidence
    if others:
        evidence = (*evidence, ("conflicting_ad_ids", ", ".join(others)))
    return replace(finding, ad_ids=mine, evidence=evidence)


def _run_checks(
    views: Sequence[AdView], convention: TrackingConvention | None
) -> list[TrackingFinding]:
    findings = [
        *foreign_campaign_scheme_findings(views),
        *same_destination_conflict_findings(views),
        *presence_findings(views),
    ]
    if convention is not None:
        findings.extend(convention_findings(views, convention))
    return findings


def _ordered(findings: Sequence[TrackingFinding]) -> tuple[TrackingFinding, ...]:
    """Deterministic order: severity first, then code, campaign, ads."""
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                _SEVERITY_ORDER[f.severity],
                f.code,
                f.platform,
                f.campaign_id,
                f.ad_ids,
            ),
        )
    )


def _notes(views: Sequence[AdView]) -> tuple[str, ...]:
    notes: list[str] = []
    if any(view.record.delivery_state is DeliveryState.UNKNOWN for view in views):
        notes.append(_UNKNOWN_DELIVERY_NOTE)
    unreadable = [view for view in views if not view.has_readable_url]
    if unreadable:
        notes.append(
            f"{len(unreadable)} ad(s) had no readable destination URL and were not "
            f"checked. They are listed in ads_without_readable_url — on some "
            f"bridged platforms mureo cannot read the URL at all, and 'no finding' "
            f"there means 'not checked', not 'clean'."
        )
    return tuple(notes)


__all__ = [
    "check_tracking_consistency",
    "preflight_tracking_consistency",
]
