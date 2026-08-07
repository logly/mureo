"""Per-platform accessors that feed the tracking-consistency core (#550).

Each adapter answers exactly one question — "give me this ad's
destination URLs" — for one platform's record shape. The core check
never sees a platform-specific field name.

These tests also pin the *honest* half of the contract: an ad whose
destination URL the platform's read surface does not expose comes back
with no URLs rather than being dropped, so the report can name it.
"""

from __future__ import annotations

import pytest

from mureo.analysis.tracking import (
    records_from_google_ads_ads,
    records_from_mappings,
    records_from_meta_ads_ads,
    records_from_provider_ads,
)
from mureo.core.providers.models import Ad, AdStatus

_URL = "https://example.com/article/1/?utm_source=google&utm_medium=cpc&utm_campaign=segb01"


@pytest.mark.unit
class TestGoogleAdsSource:
    def test_maps_google_ads_ads_list_rows(self) -> None:
        rows = [
            {
                "id": "111",
                "campaign_id": "c1",
                "campaign_name": "Display / Segment B",
                "status": "ENABLED",
                "final_urls": [_URL],
            }
        ]
        (record,) = records_from_google_ads_ads(rows)
        assert record.platform == "google_ads"
        assert record.ad_id == "111"
        assert record.campaign_id == "c1"
        assert record.campaign_name == "Display / Segment B"
        assert record.final_urls == (_URL,)

    def test_joins_impressions_when_supplied(self) -> None:
        rows = [{"id": "111", "campaign_id": "c1", "final_urls": [_URL]}]
        (record,) = records_from_google_ads_ads(rows, impressions_by_ad_id={"111": 0})
        assert record.impressions == 0

    def test_ad_without_final_urls_is_kept_with_no_urls(self) -> None:
        (record,) = records_from_google_ads_ads([{"id": "111", "campaign_id": "c1"}])
        assert record.final_urls == ()


@pytest.mark.unit
class TestMetaAdsSource:
    def test_reads_the_link_from_object_story_spec(self) -> None:
        rows = [
            {
                "id": "222",
                "campaign_id": "c2",
                "status": "ACTIVE",
                "creative": {"object_story_spec": {"link_data": {"link": _URL}}},
            }
        ]
        (record,) = records_from_meta_ads_ads(rows)
        assert record.platform == "meta_ads"
        assert record.final_urls == (_URL,)

    def test_url_tags_are_merged_onto_the_link(self) -> None:
        """Meta appends creative ``url_tags`` to the link at delivery time."""
        rows = [
            {
                "id": "222",
                "campaign_id": "c2",
                "creative": {
                    "object_story_spec": {
                        "link_data": {"link": "https://example.com/article/1/"}
                    },
                    "url_tags": "utm_source=facebook&utm_medium=cpc&utm_campaign=segb01",
                },
            }
        ]
        (record,) = records_from_meta_ads_ads(rows)
        assert record.final_urls == (
            "https://example.com/article/1/?utm_source=facebook&utm_medium=cpc&utm_campaign=segb01",
        )

    def test_video_creative_call_to_action_link(self) -> None:
        rows = [
            {
                "id": "223",
                "campaign_id": "c2",
                "creative": {
                    "object_story_spec": {
                        "video_data": {"call_to_action": {"value": {"link": _URL}}}
                    }
                },
            }
        ]
        (record,) = records_from_meta_ads_ads(rows)
        assert record.final_urls == (_URL,)

    def test_creative_shape_without_a_readable_link_yields_no_urls(self) -> None:
        rows = [{"id": "224", "campaign_id": "c2", "creative": {"id": "cr1"}}]
        (record,) = records_from_meta_ads_ads(rows)
        assert record.final_urls == ()


@pytest.mark.unit
class TestProviderAbiSource:
    def test_maps_provider_abi_ads_for_a_plugin_platform(self) -> None:
        ads = (
            Ad(
                id="333",
                account_id="acct",
                campaign_id="c3",
                status=AdStatus.ENABLED,
                headlines=("h",),
                descriptions=("d",),
                final_url=_URL,
            ),
        )
        (record,) = records_from_provider_ads(
            ads, platform="plugin:mureo-lineyahoo-bridge:yahoo_ads"
        )
        assert record.platform == "plugin:mureo-lineyahoo-bridge:yahoo_ads"
        assert record.campaign_id == "c3"
        assert record.final_urls == (_URL,)

    def test_empty_final_url_is_kept_with_no_urls(self) -> None:
        ads = (
            Ad(
                id="334",
                account_id="acct",
                campaign_id="c3",
                status=AdStatus.PAUSED,
                headlines=(),
                descriptions=(),
                final_url="",
            ),
        )
        (record,) = records_from_provider_ads(ads, platform="plugin:acme:acme_ads")
        assert record.final_urls == ()


@pytest.mark.unit
class TestGenericMappingSource:
    """For bridged / hosted platforms whose record shape mureo does not own."""

    def test_maps_arbitrary_records_with_an_explicit_field_map(self) -> None:
        rows = [
            {
                "adId": "444",
                "campaignId": "c4",
                "landingPageUrl": _URL,
                "state": "enabled",
            }
        ]
        records = records_from_mappings(
            rows,
            platform="plugin:mureo-amazon-ads-bridge:amazon_ads",
            ad_id_key="adId",
            campaign_id_key="campaignId",
            url_keys=("landingPageUrl",),
            status_key="state",
        )
        (record,) = records
        assert record.platform == "plugin:mureo-amazon-ads-bridge:amazon_ads"
        assert record.ad_id == "444"
        assert record.final_urls == (_URL,)
        assert record.status == "enabled"

    def test_row_missing_the_url_key_is_kept_with_no_urls(self) -> None:
        rows = [{"adId": "445", "campaignId": "c4"}]
        (record,) = records_from_mappings(
            rows,
            platform="plugin:mureo-amazon-ads-bridge:amazon_ads",
            ad_id_key="adId",
            campaign_id_key="campaignId",
            url_keys=("landingPageUrl",),
        )
        assert record.final_urls == ()

    def test_row_missing_the_ad_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="ad_id"):
            records_from_mappings(
                [{"campaignId": "c4"}],
                platform="x",
                ad_id_key="adId",
                campaign_id_key="campaignId",
                url_keys=("landingPageUrl",),
            )
