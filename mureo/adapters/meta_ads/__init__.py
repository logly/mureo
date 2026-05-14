"""Meta Ads provider adapter.

Re-exports the public surface so callers can ``from
mureo.adapters.meta_ads import MetaAdsAdapter`` without reaching into
submodules.
"""

from mureo.adapters.meta_ads.adapter import MetaAdsAdapter
from mureo.adapters.meta_ads.errors import (
    MetaAdsAdapterError,
    UnsupportedOperation,
)

__all__ = [
    "MetaAdsAdapter",
    "MetaAdsAdapterError",
    "UnsupportedOperation",
]
