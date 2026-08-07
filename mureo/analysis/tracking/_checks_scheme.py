"""The two zero-configuration scheme checks.

Both answer the same question — "is this ad tagged the way the account
itself says ads here are tagged?" — from evidence already present in
the account, never from a convention mureo guessed:

``foreign_campaign_scheme``
    A value shape that some ads of campaign X carry is, elsewhere in
    the same platform's account, the *sole* shape of exactly one other
    campaign Y — while campaign X also contains a different shape for
    that parameter. That is the copy-paste signature, and it is the
    check that would have caught the motivating incident at upload
    time. Requiring exactly one other campaign is what keeps
    ``utm_source=google`` (used by everything) from ever firing.

``same_destination_scheme_conflict``
    Two ads in one campaign send clicks to the same landing page but
    carry different tracking schemes. It needs no second campaign to
    compare against, so it still fires when the campaign the scheme was
    copied from is outside the record set.

Neither check declares which group is correct. mureo does not know
that, and pretending to would be the fastest way to have the check
ignored.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from mureo.analysis.tracking._views import aggregate_delivery, severity_for
from mureo.analysis.tracking.models import TrackingFinding
from mureo.analysis.tracking.scheme import format_signature

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mureo.analysis.tracking._views import AdView

_CampaignKey = tuple[str, str]
_Signature = tuple[tuple[str, str], ...]


def _campaign_label(views: Sequence[AdView]) -> str:
    for view in views:
        if view.record.campaign_name:
            return view.record.campaign_name
    return views[0].record.campaign_id


def _ad_ids(views: Sequence[AdView]) -> tuple[str, ...]:
    return tuple(sorted({view.ad_id for view in views}))


def foreign_campaign_scheme_findings(
    views: Sequence[AdView],
) -> list[TrackingFinding]:
    """Ads carrying a value shape that belongs to exactly one other campaign."""
    findings: list[TrackingFinding] = []
    by_platform: dict[str, list[AdView]] = defaultdict(list)
    for view in views:
        by_platform[view.record.platform].append(view)
    for platform_views in by_platform.values():
        names = sorted({name for v in platform_views for name in v.parameter_names()})
        for name in names:
            findings.extend(_findings_for_parameter(platform_views, name))
    return findings


def _index_parameter(views: Sequence[AdView], name: str) -> tuple[
    dict[_CampaignKey, set[str]],
    dict[tuple[_CampaignKey, str], list[AdView]],
    dict[_CampaignKey, set[str]],
]:
    """Per-campaign shapes, per-(campaign, shape) ads, and ads carrying ``name``."""
    shapes_by_campaign: dict[_CampaignKey, set[str]] = defaultdict(set)
    views_by_campaign_shape: dict[tuple[_CampaignKey, str], list[AdView]] = defaultdict(
        list
    )
    carriers_by_campaign: dict[_CampaignKey, set[str]] = defaultdict(set)
    for view in views:
        shapes = view.shapes_for(name)
        if not shapes:
            continue
        carriers_by_campaign[view.key].add(view.ad_id)
        for shape in shapes:
            shapes_by_campaign[view.key].add(shape)
            views_by_campaign_shape[(view.key, shape)].append(view)
    return shapes_by_campaign, views_by_campaign_shape, carriers_by_campaign


def _findings_for_parameter(
    views: Sequence[AdView], name: str
) -> list[TrackingFinding]:
    shapes_by_campaign, views_by_shape, carriers = _index_parameter(views, name)
    findings: list[TrackingFinding] = []
    all_shapes = sorted({s for shapes in shapes_by_campaign.values() for s in shapes})
    for shape in all_shapes:
        using = sorted(k for k, shapes in shapes_by_campaign.items() if shape in shapes)
        # Traceable to exactly one owner, or it is not evidence of anything:
        # a shape shared by three campaigns is a house style, not a leak.
        if len(using) != 2:
            continue
        for borrower, owner in ((using[0], using[1]), (using[1], using[0])):
            if len(shapes_by_campaign[borrower]) < 2:
                continue
            if shapes_by_campaign[owner] != {shape}:
                continue
            if len(carriers[owner]) < 2:
                continue
            findings.append(
                _foreign_finding(
                    name=name,
                    shape=shape,
                    offenders=views_by_shape[(borrower, shape)],
                    owner_views=views_by_shape[(owner, shape)],
                )
            )
    return findings


def _foreign_finding(
    *,
    name: str,
    shape: str,
    offenders: Sequence[AdView],
    owner_views: Sequence[AdView],
) -> TrackingFinding:
    state = aggregate_delivery(offenders)
    borrower_label = _campaign_label(offenders)
    owner_label = _campaign_label(owner_views)
    owner_record = owner_views[0].record
    return TrackingFinding(
        code="foreign_campaign_scheme",
        severity=severity_for(state),
        delivery_state=state,
        platform=offenders[0].record.platform,
        campaign_id=offenders[0].record.campaign_id,
        ad_ids=_ad_ids(offenders),
        message=(
            f"{len(_ad_ids(offenders))} ad(s) in campaign '{borrower_label}' carry "
            f"{name} values shaped '{shape}', which every ad of campaign "
            f"'{owner_label}' uses and no other campaign does. The rest of this "
            f"campaign uses a different {name} scheme."
        ),
        recommended_action=(
            f"Confirm which campaign these ads belong to. If they belong here, "
            f"re-upload them with this campaign's {name} value; if the tagging is "
            f"right, they are in the wrong campaign."
        ),
        evidence=(
            ("parameter", name),
            ("value_shape", shape),
            ("owning_campaign_id", owner_record.campaign_id),
            ("owning_campaign_name", owner_record.campaign_name),
        ),
    )


def same_destination_conflict_findings(
    views: Sequence[AdView],
) -> list[TrackingFinding]:
    """Ads sharing a landing page inside one campaign but not a scheme."""
    grouped: dict[tuple[_CampaignKey, str], dict[_Signature, list[AdView]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for view in views:
        for url in view.urls:
            if not url.tagged:
                continue
            grouped[(view.key, url.destination)][url.signature].append(view)
    findings: list[TrackingFinding] = []
    for (key, dest), by_signature in sorted(grouped.items(), key=lambda kv: kv[0][1]):
        if len(by_signature) < 2:
            continue
        findings.append(_conflict_finding(key, dest, by_signature))
    return findings


def _conflict_finding(
    key: _CampaignKey,
    dest: str,
    by_signature: dict[_Signature, list[AdView]],
) -> TrackingFinding:
    involved = [view for group in by_signature.values() for view in group]
    state = aggregate_delivery(involved)
    schemes = sorted(format_signature(sig) for sig in by_signature)
    return TrackingFinding(
        code="same_destination_scheme_conflict",
        severity=severity_for(state),
        delivery_state=state,
        platform=key[0],
        campaign_id=key[1],
        ad_ids=_ad_ids(involved),
        message=(
            f"Campaign '{_campaign_label(involved)}' sends {len(_ad_ids(involved))} "
            f"ad(s) to {dest} under {len(schemes)} different tracking schemes: "
            f"{'; '.join(schemes)}. Reporting will split one landing page across "
            f"two rows."
        ),
        recommended_action=(
            "Decide which scheme this landing page should report under and "
            "re-upload the ads that use the other one."
        ),
        evidence=(
            ("destination", dest),
            ("schemes", " | ".join(schemes)),
        ),
    )


__all__ = [
    "foreign_campaign_scheme_findings",
    "same_destination_conflict_findings",
]
