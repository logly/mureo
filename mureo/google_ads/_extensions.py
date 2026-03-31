"""拡張機能の統合ファサード Mixin。

各サブモジュールの Mixin を多重継承で統合する。
外部からは ``from mureo.google_ads._extensions import _ExtensionsMixin`` で
従来と同じ1つのクラスとしてインポートできる。

後方互換: _DEVICE_ENUM_MAP, _normalize_device_type,
_VALID_CONVERSION_ACTION_TYPES, _VALID_CONVERSION_ACTION_CATEGORIES,
_VALID_CONVERSION_ACTION_STATUSES, _MAX_SITELINKS_PER_CAMPAIGN,
_MAX_CALLOUTS_PER_CAMPAIGN も再エクスポートする。
"""

from __future__ import annotations

# 後方互換用の再エクスポート
from mureo.google_ads._extensions_conversions import (  # noqa: F401
    _VALID_CONVERSION_ACTION_CATEGORIES,
    _VALID_CONVERSION_ACTION_STATUSES,
    _VALID_CONVERSION_ACTION_TYPES,
)
from mureo.google_ads._extensions_sitelinks import (  # noqa: F401
    _MAX_SITELINKS_PER_CAMPAIGN,
)
from mureo.google_ads._extensions_callouts import (  # noqa: F401
    _MAX_CALLOUTS_PER_CAMPAIGN,
)
from mureo.google_ads._extensions_targeting import (  # noqa: F401
    _DEVICE_ENUM_MAP,
    _RESOURCE_NAME_PATTERN,
    _normalize_device_type,
)

from mureo.google_ads._extensions_sitelinks import _SitelinksMixin
from mureo.google_ads._extensions_callouts import _CalloutsMixin
from mureo.google_ads._extensions_conversions import _ConversionsMixin
from mureo.google_ads._extensions_targeting import _TargetingMixin


class _ExtensionsMixin(
    _SitelinksMixin,
    _CalloutsMixin,
    _ConversionsMixin,
    _TargetingMixin,
):
    """サイトリンク・コールアウト・コンバージョン・推奨事項・入札調整・変更履歴・地域・スケジュール"""

    pass
