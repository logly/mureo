"""The Google Ads API version mureo speaks.

One constant, passed to every ``GoogleAdsClient`` mureo builds, so the
services it calls and the ``google.ads.googleads.<version>`` enum / type
modules it imports (mappers, _enum_names) are the SAME version regardless of which google-ads-python release is installed and
whatever the library's own default happens to be.

Bumping it is a deliberate migration (#753), never a drive-by edit: every
``google.ads.googleads.<version>`` import in the tree has to move with it,
and ``tests/test_gaql_field_names.py`` re-validates every GAQL field mureo
selects and every mapper attribute it reads against the new protos.
"""

from typing import Final

GOOGLE_ADS_API_VERSION: Final = "v25"
