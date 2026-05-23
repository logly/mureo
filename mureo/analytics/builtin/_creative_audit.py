"""Creative audit logic for the built-in analytics adapters.

Pure functions that consume the platform's ``list_ads`` response and
produce :class:`CreativeFinding` lists. Kept platform-specific because
RSA / RDA / Meta-creative have genuinely different surfaces; sharing
across them would invent a generic that fits neither well.

Severity follows the same CRITICAL / HIGH scheme as
:class:`mureo.analytics.models.AnomalySeverity` — CRITICAL is something
the system would otherwise reject (RSA with <3 headlines is policy-
violating in Google's UI), HIGH is a strong recommendation (no image,
missing description).

Tolerates BYOD shape: the Google BYOD adapter returns ads with
``headlines`` as a 2-element list of ``[headline_1, headline_2]``,
which trips the "must have ≥3 headlines" check naturally. We surface
the finding rather than guess at the missing strings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mureo.analytics.models import AnomalySeverity, CreativeFinding

if TYPE_CHECKING:
    from collections.abc import Iterable

# Google RSA policy thresholds — match the values shown in the Google
# Ads UI's "Ad strength" panel.
_RSA_MIN_HEADLINES = 3
_RSA_MIN_DESCRIPTIONS = 2
_RSA_RECOMMENDED_HEADLINES = 15  # Google recommends filling all 15 slots
_RSA_RECOMMENDED_DESCRIPTIONS = 4


def _is_rsa(ad: dict[str, Any]) -> bool:
    ad_type = str(ad.get("type", "") or ad.get("ad_type", "")).upper()
    return ad_type in {"RESPONSIVE_SEARCH_AD", "RSA"}


def _is_rda(ad: dict[str, Any]) -> bool:
    ad_type = str(ad.get("type", "") or ad.get("ad_type", "")).upper()
    return ad_type in {"RESPONSIVE_DISPLAY_AD", "RDA"}


def _non_empty_strings(values: Any) -> list[str]:
    """Filter to non-empty trimmed strings.

    Accepts the variety of shapes the live + BYOD clients return:
    a list of plain strings, a list of dicts with ``text`` keys, or
    ``None``.
    """
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        if isinstance(v, str):
            text = v.strip()
        elif isinstance(v, dict):
            text = str(v.get("text") or "").strip()
        else:
            text = ""
        if text:
            out.append(text)
    return out


def _extract_campaign_id(ad: dict[str, Any]) -> str:
    """Return the owning campaign_id from an ad row.

    Both Google and Meta — live and BYOD — expose ``campaign_id`` at
    the top level of the ``list_ads`` row, but Google's live response
    also nests campaign info under ``ad["campaign"]`` (the mapper
    flattens this on its own). We accept either, falling back to
    ``ad["campaign"]["id"]`` for forward compat in case the mapper
    ever stops flattening.

    Coerces non-string values (e.g. an ``int`` campaign id from a
    loose BYOD adapter) the same way :func:`audit_*` coerces
    ``ad_id`` — keeps the result a usable string instead of silently
    dropping the join.
    """
    direct = ad.get("campaign_id")
    if direct is not None:
        text = str(direct).strip()
        if text:
            return text
    campaign = ad.get("campaign")
    if isinstance(campaign, dict):
        nested = campaign.get("id")
        if nested is not None:
            text = str(nested).strip()
            if text:
                return text
    return ""


def audit_google_ads_creatives(
    ads: list[dict[str, Any]],
) -> list[CreativeFinding]:
    """Inspect a list of Google Ads ads and return policy/quality findings.

    Only RSA + RDA ads are audited today; other ad types pass through
    silently. The function is pure — no network, no I/O — so the
    adapter can call it on whatever shape the live or BYOD client
    returns without further plumbing.

    Each finding carries the owning ``campaign_id`` (when the row
    includes it) so the adapter can build a per-campaign drilldown
    summary without re-walking ``ads``.
    """
    findings: list[CreativeFinding] = []
    for ad in ads:
        ad_id = str(ad.get("id") or ad.get("ad_id") or "").strip()
        if not ad_id:
            continue
        campaign_id = _extract_campaign_id(ad)

        if _is_rsa(ad):
            findings.extend(_audit_rsa(ad, ad_id, campaign_id))
        elif _is_rda(ad):
            findings.extend(_audit_rda(ad, ad_id, campaign_id))
    return findings


def _audit_rsa(
    ad: dict[str, Any], ad_id: str, campaign_id: str
) -> list[CreativeFinding]:
    findings: list[CreativeFinding] = []
    headlines = _non_empty_strings(ad.get("headlines"))
    descriptions = _non_empty_strings(ad.get("descriptions"))

    if len(headlines) < _RSA_MIN_HEADLINES:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RSA",
                severity=AnomalySeverity.CRITICAL,
                message=(
                    f"RSA has only {len(headlines)} headline(s) — "
                    f"minimum is {_RSA_MIN_HEADLINES}"
                ),
                recommended_action=(
                    "Add headlines until at least 3 are present; "
                    "Google recommends filling all 15 slots for full "
                    "Ad-Strength evaluation."
                ),
                campaign_id=campaign_id,
            )
        )
    elif len(headlines) < _RSA_RECOMMENDED_HEADLINES:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RSA",
                severity=AnomalySeverity.HIGH,
                message=(
                    f"RSA has {len(headlines)} headlines — "
                    f"Google recommends {_RSA_RECOMMENDED_HEADLINES}"
                ),
                recommended_action=("Add headline variants to improve Ad Strength."),
                campaign_id=campaign_id,
            )
        )

    if len(descriptions) < _RSA_MIN_DESCRIPTIONS:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RSA",
                severity=AnomalySeverity.CRITICAL,
                message=(
                    f"RSA has only {len(descriptions)} description(s) — "
                    f"minimum is {_RSA_MIN_DESCRIPTIONS}"
                ),
                recommended_action="Add at least 2 descriptions.",
                campaign_id=campaign_id,
            )
        )

    return findings


def _audit_rda(
    ad: dict[str, Any], ad_id: str, campaign_id: str
) -> list[CreativeFinding]:
    findings: list[CreativeFinding] = []
    headlines = _non_empty_strings(ad.get("headlines"))
    long_headline = str(ad.get("long_headline") or "").strip()
    descriptions = _non_empty_strings(ad.get("descriptions"))
    images = ad.get("marketing_images") or ad.get("square_marketing_images") or []

    if not headlines:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RDA",
                severity=AnomalySeverity.CRITICAL,
                message="RDA has no short headlines",
                recommended_action="Add at least one short headline (≤30 chars).",
                campaign_id=campaign_id,
            )
        )
    if not long_headline:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RDA",
                severity=AnomalySeverity.HIGH,
                message="RDA missing long headline",
                recommended_action="Add a long headline (≤90 chars).",
                campaign_id=campaign_id,
            )
        )
    if not descriptions:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RDA",
                severity=AnomalySeverity.CRITICAL,
                message="RDA has no descriptions",
                recommended_action="Add at least one description.",
                campaign_id=campaign_id,
            )
        )
    if not isinstance(images, list) or not images:
        findings.append(
            CreativeFinding(
                asset_id=ad_id,
                asset_type="RDA",
                severity=AnomalySeverity.HIGH,
                message="RDA has no marketing images",
                recommended_action="Add at least one landscape image.",
                campaign_id=campaign_id,
            )
        )
    return findings


def audit_meta_ads_creatives(
    ads: list[dict[str, Any]],
) -> list[CreativeFinding]:
    """Inspect a list of Meta ads and return creative-quality findings.

    Meta's ad model nests the creative under ``ad["creative"]``; on the
    BYOD side the same fields may be at the top level. Both shapes are
    accepted.
    """
    findings: list[CreativeFinding] = []
    for ad in ads:
        ad_id = str(ad.get("id") or ad.get("ad_id") or "").strip()
        if not ad_id:
            continue
        campaign_id = _extract_campaign_id(ad)

        creative = ad.get("creative")
        if not isinstance(creative, dict):
            creative = ad

        title = str(creative.get("title") or "").strip()
        body = str(creative.get("body") or "").strip()
        image_url = str(
            creative.get("image_url") or creative.get("thumbnail_url") or ""
        ).strip()
        story_spec = creative.get("object_story_spec") or {}
        link_data = (
            story_spec.get("link_data") if isinstance(story_spec, dict) else None
        )
        cta = ""
        if isinstance(link_data, dict):
            call_to_action = link_data.get("call_to_action") or {}
            if isinstance(call_to_action, dict):
                cta = str(call_to_action.get("type") or "").strip()

        if not body:
            findings.append(
                CreativeFinding(
                    asset_id=ad_id,
                    asset_type="META_AD",
                    severity=AnomalySeverity.CRITICAL,
                    message="Ad has no primary text",
                    recommended_action="Add a primary text variant.",
                    campaign_id=campaign_id,
                )
            )
        if not title:
            findings.append(
                CreativeFinding(
                    asset_id=ad_id,
                    asset_type="META_AD",
                    severity=AnomalySeverity.HIGH,
                    message="Ad has no headline",
                    recommended_action="Add a headline.",
                    campaign_id=campaign_id,
                )
            )
        if not image_url:
            findings.append(
                CreativeFinding(
                    asset_id=ad_id,
                    asset_type="META_AD",
                    severity=AnomalySeverity.CRITICAL,
                    message="Ad has no image",
                    recommended_action="Attach an image or thumbnail.",
                    campaign_id=campaign_id,
                )
            )
        if not cta:
            findings.append(
                CreativeFinding(
                    asset_id=ad_id,
                    asset_type="META_AD",
                    severity=AnomalySeverity.HIGH,
                    message="Ad has no call_to_action",
                    recommended_action=(
                        "Set a call_to_action.type (e.g. LEARN_MORE, SIGN_UP)."
                    ),
                    campaign_id=campaign_id,
                )
            )
    return findings


def summarise_findings_by_campaign(
    findings: Iterable[CreativeFinding],
) -> tuple[tuple[str, int], ...]:
    """Group findings by ``campaign_id`` and return ``(campaign_id, count)``.

    Findings whose ``campaign_id`` is empty are dropped — there is no
    meaningful "ungrouped" bucket to report. The result is sorted by
    campaign_id so the workflow renders deterministically regardless
    of dict-insertion order.
    """
    counts: dict[str, int] = {}
    for finding in findings:
        cid = finding.campaign_id.strip()
        if not cid:
            continue
        counts[cid] = counts.get(cid, 0) + 1
    return tuple(sorted(counts.items()))


__all__ = [
    "audit_google_ads_creatives",
    "audit_meta_ads_creatives",
    "summarise_findings_by_campaign",
]
