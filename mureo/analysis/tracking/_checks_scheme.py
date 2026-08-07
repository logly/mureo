"""The two zero-configuration scheme checks.

Both answer the same question — "is this ad tagged the way the account
itself says ads here are tagged?" — from evidence already present in
the account, never from a convention mureo guessed:

``foreign_campaign_scheme``
    Some ads of campaign X carry a **whole campaign-identifying
    signature** that is, elsewhere on the same platform, the *sole*
    signature of exactly one other campaign Y — while campaign X also
    contains a different signature. That is the copy-paste signature,
    and it is the check that would have caught the motivating incident
    at upload time.

``same_destination_scheme_conflict``
    Two ads in one campaign send clicks to the same landing page under
    different identifying signatures. It needs no second campaign to
    compare against, so it still fires when the campaign the scheme was
    copied from is outside the record set.

Two design choices keep these from crying wolf:

**Whole signatures, never one parameter at a time.** An earlier
per-parameter form reported "these ads borrowed campaign Y's
``utm_source``" for a value like ``google`` that Y merely happens to
share — and in a two-campaign account, or any account where one
campaign carries a single legitimate one-off ad, ``google`` *is* owned
by exactly one other campaign, so the correctly-tagged majority got
flagged. Requiring the entire identifying signature to match means the
finding says something true: these ads carry another campaign's whole
tracking identity, so reporting cannot tell them apart from Y's.

**Only campaign-identifying parameters.** ``utm_content`` and
``utm_term`` vary within one campaign by design (per creative, per
keyword). See :mod:`mureo.analysis.tracking.scheme`.

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

#: A campaign only "owns" a signature when at least this many of its ads
#: carry it. One ad is an anecdote, not a campaign's scheme.
MIN_ADS_TO_OWN_A_SCHEME = 2


def _campaign_label(views: Sequence[AdView]) -> str:
    for view in views:
        if view.record.campaign_name:
            return view.record.campaign_name
    return views[0].record.campaign_id


def _ad_ids(views: Sequence[AdView]) -> tuple[str, ...]:
    return tuple(sorted({view.ad_id for view in views}))


def _index_signatures(
    views: Sequence[AdView],
) -> tuple[
    dict[_CampaignKey, set[_Signature]],
    dict[tuple[_CampaignKey, _Signature], list[AdView]],
]:
    """Per-campaign identifying signatures, and the ads carrying each."""
    by_campaign: dict[_CampaignKey, set[_Signature]] = defaultdict(set)
    by_campaign_signature: dict[tuple[_CampaignKey, _Signature], list[AdView]] = (
        defaultdict(list)
    )
    for view in views:
        for signature in view.identifying_signatures:
            by_campaign[view.key].add(signature)
            by_campaign_signature[(view.key, signature)].append(view)
    return by_campaign, by_campaign_signature


def foreign_campaign_scheme_findings(
    views: Sequence[AdView],
) -> list[TrackingFinding]:
    """Ads carrying the whole scheme of exactly one other campaign."""
    findings: list[TrackingFinding] = []
    by_platform: dict[str, list[AdView]] = defaultdict(list)
    for view in views:
        by_platform[view.record.platform].append(view)
    for platform in sorted(by_platform):
        findings.extend(_findings_for_platform(by_platform[platform]))
    return findings


def _findings_for_platform(views: Sequence[AdView]) -> list[TrackingFinding]:
    by_campaign, by_campaign_signature = _index_signatures(views)
    findings: list[TrackingFinding] = []
    all_signatures = sorted({s for sigs in by_campaign.values() for s in sigs})
    for signature in all_signatures:
        using = sorted(k for k, sigs in by_campaign.items() if signature in sigs)
        # Traceable to exactly one owner, or it is not evidence of
        # anything: a signature shared by three campaigns is a house
        # style, not a leak.
        if len(using) != 2:
            continue
        for borrower, owner in ((using[0], using[1]), (using[1], using[0])):
            if len(by_campaign[borrower]) < 2:
                continue
            if by_campaign[owner] != {signature}:
                continue
            owner_views = by_campaign_signature[(owner, signature)]
            if len(_ad_ids(owner_views)) < MIN_ADS_TO_OWN_A_SCHEME:
                continue
            findings.append(
                _foreign_finding(
                    signature=signature,
                    offenders=by_campaign_signature[(borrower, signature)],
                    owner_views=owner_views,
                    borrower_signatures=by_campaign[borrower],
                )
            )
    return findings


def _differing_parameters(
    signature: _Signature, others: set[_Signature]
) -> tuple[str, ...]:
    """Identifying parameters where ``signature`` departs from ``others``."""
    mine = dict(signature)
    differing: set[str] = set()
    for other in others:
        if other == signature:
            continue
        theirs = dict(other)
        for name in set(mine) | set(theirs):
            if mine.get(name) != theirs.get(name):
                differing.add(name)
    return tuple(sorted(differing))


def _foreign_finding(
    *,
    signature: _Signature,
    offenders: Sequence[AdView],
    owner_views: Sequence[AdView],
    borrower_signatures: set[_Signature],
) -> TrackingFinding:
    state = aggregate_delivery(offenders)
    borrower_label = _campaign_label(offenders)
    owner_label = _campaign_label(owner_views)
    owner_record = owner_views[0].record
    differing = _differing_parameters(signature, borrower_signatures)
    rendered = format_signature(signature)
    return TrackingFinding(
        code="foreign_campaign_scheme",
        severity=severity_for(state),
        delivery_state=state,
        platform=offenders[0].record.platform,
        campaign_id=offenders[0].record.campaign_id,
        ad_ids=_ad_ids(offenders),
        message=(
            f"{len(_ad_ids(offenders))} ad(s) in campaign '{borrower_label}' carry "
            f"the tracking scheme '{rendered}', which every ad of campaign "
            f"'{owner_label}' uses and no other campaign does. The rest of this "
            f"campaign is tagged differently "
            f"({', '.join(differing) or 'no differing parameter'}), so in "
            f"reporting these ads are indistinguishable from '{owner_label}'."
        ),
        recommended_action=(
            "Confirm which campaign these ads belong to. If they belong here, "
            "re-upload them with this campaign's tracking values; if the tagging "
            "is right, they are in the wrong campaign."
        ),
        evidence=(
            ("scheme", rendered),
            ("differing_parameters", ", ".join(differing)),
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
            if not url.identifiable:
                continue
            grouped[(view.key, url.destination)][url.identifying].append(view)
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
            f"ad(s) to {dest} under {len(schemes)} different campaign-identifying "
            f"schemes: {'; '.join(schemes)}. Reporting will split one landing page "
            f"across two rows."
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
    "MIN_ADS_TO_OWN_A_SCHEME",
    "foreign_campaign_scheme_findings",
    "same_destination_conflict_findings",
]
