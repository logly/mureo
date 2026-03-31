"""Integrated extensions facade mixin.

Integrates sub-module mixins via multiple inheritance.
Can be imported as ``from mureo.google_ads._extensions import _ExtensionsMixin``
as a single class, maintaining backward compatibility.

Backward compatibility: re-exports _DEVICE_ENUM_MAP, _normalize_device_type,
_VALID_CONVERSION_ACTION_TYPES, _VALID_CONVERSION_ACTION_CATEGORIES,
_VALID_CONVERSION_ACTION_STATUSES, _MAX_SITELINKS_PER_CAMPAIGN,
_MAX_CALLOUTS_PER_CAMPAIGN.
"""

from __future__ import annotations

from mureo.google_ads._extensions_callouts import (  # noqa: F401
    _MAX_CALLOUTS_PER_CAMPAIGN,
    _CalloutsMixin,
)

# Backward-compatible re-exports
from mureo.google_ads._extensions_conversions import (  # noqa: F401
    _VALID_CONVERSION_ACTION_CATEGORIES,
    _VALID_CONVERSION_ACTION_STATUSES,
    _VALID_CONVERSION_ACTION_TYPES,
    _ConversionsMixin,
)
from mureo.google_ads._extensions_sitelinks import (  # noqa: F401
    _MAX_SITELINKS_PER_CAMPAIGN,
    _SitelinksMixin,
)
from mureo.google_ads._extensions_targeting import (  # noqa: F401
    _DEVICE_ENUM_MAP,
    _RESOURCE_NAME_PATTERN,
    _normalize_device_type,
    _TargetingMixin,
)


class _ExtensionsMixin(
    _SitelinksMixin,
    _CalloutsMixin,
    _ConversionsMixin,
    _TargetingMixin,
):
    """Sitelinks, callouts, conversions, recommendations, bid adjustments, change history, location, and schedule."""

    pass
