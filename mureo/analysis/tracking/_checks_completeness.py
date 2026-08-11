"""Presence checks: parameters an ad is missing, and declared patterns.

``missing_tracking_parameter`` and ``untagged_final_url`` are
zero-configuration but deliberately **evidence-scoped**: mureo does not
assert that every account must carry ``utm_source`` / ``utm_medium`` /
``utm_campaign``. It flags an ad that lacks a parameter *every other ad
in its own campaign carries*. An account that tags with two parameters
instead of three is therefore never nagged, which is the difference
between a check operators keep on and one they mute.

``missing_required_parameter`` and ``convention_violation`` are the
opt-in half: they exist only when the operator declared a convention in
STRATEGY.md, and they say exactly what the operator declared.
"""

from __future__ import annotations

from collections import defaultdict
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING

from mureo.analysis.tracking._views import aggregate_delivery, severity_for
from mureo.analysis.tracking.models import TrackingFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mureo.analysis.tracking._views import AdView
    from mureo.analysis.tracking.models import TrackingConvention

#: An ad is only compared against its campaign when at least this many
#: OTHER ads in it are tagged — one sibling is an anecdote, not a norm.
MIN_SIBLINGS_FOR_NORM = 2


def _group_by_campaign(views: Sequence[AdView]) -> dict[tuple[str, str], list[AdView]]:
    grouped: dict[tuple[str, str], list[AdView]] = defaultdict(list)
    for view in views:
        grouped[view.key].append(view)
    return grouped


def _finding(
    view: AdView,
    *,
    code: str,
    message: str,
    recommended_action: str,
    evidence: tuple[tuple[str, str], ...] = (),
) -> TrackingFinding:
    state = aggregate_delivery([view])
    return TrackingFinding(
        code=code,
        severity=severity_for(state),
        delivery_state=state,
        platform=view.record.platform,
        campaign_id=view.record.campaign_id,
        ad_ids=(view.ad_id,),
        message=message,
        recommended_action=recommended_action,
        evidence=evidence,
    )


def presence_findings(views: Sequence[AdView]) -> list[TrackingFinding]:
    """Ads out of step with the tagging their own campaign already uses."""
    findings: list[TrackingFinding] = []
    for group in _group_by_campaign(views).values():
        tagged = [v for v in group if v.tagged]
        if len(tagged) < MIN_SIBLINGS_FOR_NORM:
            continue
        findings.extend(_untagged_findings(group, tagged))
        findings.extend(_missing_parameter_findings(tagged))
    return findings


def _untagged_findings(
    group: Sequence[AdView], tagged: Sequence[AdView]
) -> list[TrackingFinding]:
    return [
        _finding(
            view,
            code="untagged_final_url",
            message=(
                f"Ad {view.ad_id} has no tracking parameters on its final URL, "
                f"while {len(tagged)} other ads in this campaign are tagged. Its "
                f"traffic will land in the analytics bucket for untagged visits."
            ),
            recommended_action=(
                "Re-upload the ad with the same tracking parameters the rest of "
                "the campaign uses."
            ),
        )
        for view in group
        if view.has_readable_url and not view.tagged
    ]


def _missing_parameter_findings(tagged: Sequence[AdView]) -> list[TrackingFinding]:
    findings: list[TrackingFinding] = []
    for view in tagged:
        siblings = [other for other in tagged if other.ad_id != view.ad_id]
        if len(siblings) < MIN_SIBLINGS_FOR_NORM:
            continue
        shared = frozenset.intersection(*[s.parameter_names() for s in siblings])
        for name in sorted(shared - view.parameter_names()):
            findings.append(_missing_parameter_finding(view, name, len(siblings)))
    return findings


def _missing_parameter_finding(
    view: AdView, name: str, sibling_count: int
) -> TrackingFinding:
    return _finding(
        view,
        code="missing_tracking_parameter",
        message=(
            f"Ad {view.ad_id} has no '{name}' parameter, while all {sibling_count} "
            f"other tagged ads in this campaign carry it."
        ),
        recommended_action=(
            f"Add '{name}' to the ad's final URL so its traffic joins the same "
            f"reporting dimension as the rest of the campaign."
        ),
        evidence=(("parameter", name),),
    )


def convention_findings(
    views: Sequence[AdView], convention: TrackingConvention
) -> list[TrackingFinding]:
    """Violations of a convention the operator declared in STRATEGY.md."""
    findings: list[TrackingFinding] = []
    patterns = dict(convention.patterns)
    for view in views:
        if not view.tagged:
            continue
        findings.extend(_required_findings(view, convention.require))
        findings.extend(_pattern_findings(view, patterns))
    return findings


def _required_findings(view: AdView, required: Sequence[str]) -> list[TrackingFinding]:
    carried = view.parameter_names()
    return [
        _finding(
            view,
            code="missing_required_parameter",
            message=(
                f"Ad {view.ad_id} is missing '{name}', which STRATEGY.md's "
                f"Tracking Convention declares as required."
            ),
            recommended_action=f"Add '{name}' to the ad's final URL.",
            evidence=(("parameter", name), ("source", "STRATEGY.md")),
        )
        for name in required
        if name not in carried
    ]


def _pattern_findings(
    view: AdView, patterns: dict[str, tuple[str, ...]]
) -> list[TrackingFinding]:
    findings: list[TrackingFinding] = []
    for name, allowed in sorted(patterns.items()):
        for value in view.values_for(name):
            if any(fnmatchcase(value, pattern) for pattern in allowed):
                continue
            findings.append(_pattern_finding(view, name, value, allowed))
    return findings


def _pattern_finding(
    view: AdView, name: str, value: str, allowed: Sequence[str]
) -> TrackingFinding:
    return _finding(
        view,
        code="convention_violation",
        message=(
            f"Ad {view.ad_id} has {name}={value}, which matches none of the "
            f"patterns STRATEGY.md's Tracking Convention declares for it "
            f"({', '.join(allowed)})."
        ),
        recommended_action=(
            f"Re-upload the ad with a '{name}' value that follows the declared "
            f"convention, or update the convention if it has changed."
        ),
        evidence=(
            ("parameter", name),
            ("value", value),
            ("declared_patterns", ", ".join(allowed)),
            ("source", "STRATEGY.md"),
        ),
    )


__all__ = [
    "MIN_SIBLINGS_FOR_NORM",
    "convention_findings",
    "presence_findings",
]
