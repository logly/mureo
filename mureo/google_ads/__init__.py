"""mureo.google_ads - Google Ads API operations (database-independent)."""

from mureo.google_ads.accounts import (
    GoogleAdsAccountListError,
    list_accessible_accounts,
)
from mureo.google_ads.client import GoogleAdsApiClient

__all__ = [
    "GoogleAdsAccountListError",
    "GoogleAdsApiClient",
    "list_accessible_accounts",
]
