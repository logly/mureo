"""Per-platform accessors: "give me this ad's destination URLs".

The core check is platform-neutral, so every platform needs exactly one
thin adapter that reduces its own record shape to
:class:`~mureo.analysis.tracking.models.AdTrackingRecord`. Where the URL
lives differs per platform, and on some platforms mureo cannot read it
at all with the tools available:

``google_ads``
    ``final_urls`` on the ``google_ads_ads_list`` row. Read directly.
    NOT covered: ``tracking_url_template`` / ``final_url_suffix`` set at
    campaign or account level — mureo does not read those fields, so a
    scheme injected there is invisible to this check.

``meta_ads``
    The link lives inside the creative's ``object_story_spec``
    (``link_data.link``, or a call-to-action link on video/photo data),
    and creative-level ``url_tags`` are appended to it at delivery time.
    Creative shapes that carry the destination somewhere else (dynamic
    ``asset_feed_spec`` link sets, catalog-driven ads) come back with no
    URL rather than a guess.

plugin platforms (provider ABI)
    ``Ad.final_url`` — one URL per ad, which is all the ABI models.

bridged / hosted platforms
    mureo does not own their tool schemas. :func:`records_from_mappings`
    takes an explicit field map so the caller states where the URL is;
    when the bridged read surface exposes no destination URL at all (the
    Amazon Ads bridge is the current example), the record is still built
    with no URLs and the report names it as unchecked.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from mureo.analysis.tracking.models import AdTrackingRecord

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from mureo.core.providers.models import Ad

GOOGLE_ADS_PLATFORM = "google_ads"
META_ADS_PLATFORM = "meta_ads"


def _impressions(
    ad_id: str, impressions_by_ad_id: Mapping[str, int] | None
) -> int | None:
    if impressions_by_ad_id is None:
        return None
    return impressions_by_ad_id.get(ad_id)


def _text(value: Any) -> str:
    return str(value) if value is not None else ""


def records_from_google_ads_ads(
    rows: Iterable[Mapping[str, Any]],
    *,
    impressions_by_ad_id: Mapping[str, int] | None = None,
) -> tuple[AdTrackingRecord, ...]:
    """Map ``google_ads_ads_list`` rows to tracking records."""
    records: list[AdTrackingRecord] = []
    for row in rows:
        ad_id = _text(row.get("id"))
        if not ad_id:
            raise ValueError("Google Ads ad row is missing 'id' (ad_id)")
        urls = tuple(str(u) for u in (row.get("final_urls") or ()) if u)
        records.append(
            AdTrackingRecord(
                ad_id=ad_id,
                campaign_id=_text(row.get("campaign_id")),
                final_urls=urls,
                platform=GOOGLE_ADS_PLATFORM,
                campaign_name=_text(row.get("campaign_name")),
                status=_text(row.get("status")),
                impressions=_impressions(ad_id, impressions_by_ad_id),
            )
        )
    return tuple(records)


def _merge_url_tags(link: str, url_tags: str) -> str:
    """Append creative ``url_tags`` to ``link`` the way Meta does."""
    tags = url_tags.strip().lstrip("?&")
    if not tags:
        return link
    separator = "&" if "?" in link else "?"
    return f"{link}{separator}{tags}"


def _meta_links(creative: Mapping[str, Any]) -> tuple[str, ...]:
    """Destination links mureo can read out of a Meta creative."""
    spec = creative.get("object_story_spec")
    if not isinstance(spec, Mapping):
        return ()
    links: list[str] = []
    link_data = spec.get("link_data")
    if isinstance(link_data, Mapping) and link_data.get("link"):
        links.append(str(link_data["link"]))
    for key in ("video_data", "photo_data", "template_data"):
        block = spec.get(key)
        if not isinstance(block, Mapping):
            continue
        if block.get("link"):
            links.append(str(block["link"]))
            continue
        cta = block.get("call_to_action")
        if isinstance(cta, Mapping):
            value = cta.get("value")
            if isinstance(value, Mapping) and value.get("link"):
                links.append(str(value["link"]))
    return tuple(dict.fromkeys(links))


def records_from_meta_ads_ads(
    rows: Iterable[Mapping[str, Any]],
    *,
    impressions_by_ad_id: Mapping[str, int] | None = None,
) -> tuple[AdTrackingRecord, ...]:
    """Map ``meta_ads_ads_list`` rows to tracking records."""
    records: list[AdTrackingRecord] = []
    for row in rows:
        ad_id = _text(row.get("id"))
        if not ad_id:
            raise ValueError("Meta Ads ad row is missing 'id' (ad_id)")
        creative = row.get("creative")
        creative = creative if isinstance(creative, Mapping) else {}
        url_tags = _text(creative.get("url_tags"))
        urls = tuple(_merge_url_tags(link, url_tags) for link in _meta_links(creative))
        records.append(
            AdTrackingRecord(
                ad_id=ad_id,
                campaign_id=_text(row.get("campaign_id")),
                final_urls=urls,
                platform=META_ADS_PLATFORM,
                campaign_name=_text(row.get("campaign_name")),
                status=_text(row.get("effective_status") or row.get("status")),
                impressions=_impressions(ad_id, impressions_by_ad_id),
            )
        )
    return tuple(records)


def records_from_provider_ads(
    ads: Iterable[Ad],
    *,
    platform: str,
    campaign_names: Mapping[str, str] | None = None,
    impressions_by_ad_id: Mapping[str, int] | None = None,
) -> tuple[AdTrackingRecord, ...]:
    """Map provider-ABI :class:`Ad` objects to tracking records.

    ``platform`` must be the canonical platform key the rest of mureo
    joins on (``plugin:<distribution>:<provider>`` for a plugin).
    """
    names = campaign_names or {}
    return tuple(
        AdTrackingRecord(
            ad_id=ad.id,
            campaign_id=ad.campaign_id,
            final_urls=(ad.final_url,) if ad.final_url else (),
            platform=platform,
            campaign_name=names.get(ad.campaign_id, ""),
            status=str(ad.status),
            impressions=_impressions(ad.id, impressions_by_ad_id),
        )
        for ad in ads
    )


def records_from_mappings(
    rows: Iterable[Mapping[str, Any]],
    *,
    platform: str,
    ad_id_key: str,
    campaign_id_key: str,
    url_keys: Sequence[str],
    campaign_name_key: str | None = None,
    status_key: str | None = None,
    impressions_by_ad_id: Mapping[str, int] | None = None,
) -> tuple[AdTrackingRecord, ...]:
    """Map records from a platform whose schema mureo does not own.

    The field map is supplied by the caller rather than sniffed: a
    guessed field name that silently resolves to nothing would turn
    "not checked" into a clean bill of health.
    """
    records: list[AdTrackingRecord] = []
    for row in rows:
        ad_id = _text(row.get(ad_id_key))
        if not ad_id:
            raise ValueError(f"Row is missing ad_id key {ad_id_key!r}: {sorted(row)}")
        urls = tuple(
            _text(row.get(key)) for key in url_keys if _text(row.get(key)).strip()
        )
        records.append(
            AdTrackingRecord(
                ad_id=ad_id,
                campaign_id=_text(row.get(campaign_id_key)),
                final_urls=urls,
                platform=platform,
                campaign_name=(
                    _text(row.get(campaign_name_key)) if campaign_name_key else ""
                ),
                status=_text(row.get(status_key)) if status_key else "",
                impressions=_impressions(ad_id, impressions_by_ad_id),
            )
        )
    return tuple(records)


__all__ = [
    "GOOGLE_ADS_PLATFORM",
    "META_ADS_PLATFORM",
    "records_from_google_ads_ads",
    "records_from_mappings",
    "records_from_meta_ads_ads",
    "records_from_provider_ads",
]
