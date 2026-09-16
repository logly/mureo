"""The Google Ads API version mureo speaks.

One constant, passed to every ``GoogleAdsClient`` mureo builds, so the
services it calls and the ``google.ads.googleads.<version>`` enum / type
modules it imports (mappers, _enum_names, policy.learning_rules) are the
SAME version regardless of which google-ads-python release is installed —
the library's default moved from v23 (29.x) to v25 (32.x) and mureo must
not follow it by accident.
"""

from typing import Final

GOOGLE_ADS_API_VERSION: Final = "v23"
