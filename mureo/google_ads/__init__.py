"""mureo.google_ads - Google Ads API operations (database-independent)."""

from mureo.google_ads.accounts import list_accessible_accounts
from mureo.google_ads.client import GoogleAdsApiClient

__all__ = [
    "GoogleAdsApiClient",
    "list_accessible_accounts",
]
