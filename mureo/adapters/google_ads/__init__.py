"""Google Ads provider adapter.

Re-exports the public surface so callers can ``from
mureo.adapters.google_ads import GoogleAdsAdapter`` without reaching into
submodules.
"""

from mureo.adapters.google_ads.adapter import GoogleAdsAdapter
from mureo.adapters.google_ads.errors import (
    GoogleAdsAdapterError,
    UnsupportedOperation,
)

__all__ = [
    "GoogleAdsAdapter",
    "GoogleAdsAdapterError",
    "UnsupportedOperation",
]
