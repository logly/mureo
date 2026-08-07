"""Tracking-parameter consistency checks (issue #550).

An ad's final-URL tracking parameters decide which row of everyone's
analytics its clicks land in. When an ad is uploaded into the wrong
campaign carrying another campaign's tags, nothing looks broken —
delivery is healthy, spend is healthy — and the reporting the whole
team trusts is quietly wrong. Nobody investigates, because nothing
appears to be wrong.

This package detects that class of defect from evidence already in the
account, on every platform mureo drives:

- :mod:`~mureo.analysis.tracking.checks` — the platform-neutral
  detector, used both by the ``/tracking-health`` account audit and by
  the pre-flight that runs before ads are created.
- :mod:`~mureo.analysis.tracking.sources` — one thin accessor per
  platform that answers "give me this ad's destination URLs".
- :mod:`~mureo.analysis.tracking.convention` — the opt-in
  ``## Tracking Convention`` section of STRATEGY.md, for the intent
  that evidence alone cannot supply.

What it deliberately does NOT do is infer an account's naming
convention and then judge ads against the guess. See
``docs/tracking-consistency.md`` for the full list of what is and is
not detectable.
"""

from mureo.analysis.tracking.checks import (
    check_tracking_consistency,
    preflight_tracking_consistency,
)
from mureo.analysis.tracking.convention import (
    SECTION_HEADING,
    parse_tracking_convention,
)
from mureo.analysis.tracking.models import (
    AdTrackingRecord,
    DeliveryState,
    TrackingConsistencyReport,
    TrackingConvention,
    TrackingFinding,
    TrackingSeverity,
)
from mureo.analysis.tracking.scheme import (
    DEFAULT_RECOGNIZED,
    destination,
    tracking_parameters,
    value_shape,
)
from mureo.analysis.tracking.sources import (
    records_from_google_ads_ads,
    records_from_mappings,
    records_from_meta_ads_ads,
    records_from_provider_ads,
)

__all__ = [
    "DEFAULT_RECOGNIZED",
    "SECTION_HEADING",
    "AdTrackingRecord",
    "DeliveryState",
    "TrackingConsistencyReport",
    "TrackingConvention",
    "TrackingFinding",
    "TrackingSeverity",
    "check_tracking_consistency",
    "destination",
    "parse_tracking_convention",
    "preflight_tracking_consistency",
    "records_from_google_ads_ads",
    "records_from_mappings",
    "records_from_meta_ads_ads",
    "records_from_provider_ads",
    "tracking_parameters",
    "value_shape",
]
