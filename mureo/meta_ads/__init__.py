"""mureo.meta_ads - Meta Ads API operations (database-independent)."""

from mureo.meta_ads.accounts import MetaAdAccountList, list_meta_ad_accounts
from mureo.meta_ads.client import MetaAdsApiClient
from mureo.meta_ads.mappers import (
    map_ad,
    map_ad_set,
    map_campaign,
    map_insights,
)

__all__ = [
    "MetaAdAccountList",
    "MetaAdsApiClient",
    "list_meta_ad_accounts",
    "map_ad",
    "map_ad_set",
    "map_campaign",
    "map_insights",
]
