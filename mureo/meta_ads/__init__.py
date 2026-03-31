"""mureo.meta_ads - Meta Ads API operations (database-independent)."""

from mureo.meta_ads.client import MetaAdsApiClient
from mureo.meta_ads.mappers import (
    map_ad,
    map_ad_set,
    map_campaign,
    map_insights,
)

__all__ = [
    "MetaAdsApiClient",
    "map_ad",
    "map_ad_set",
    "map_campaign",
    "map_insights",
]
