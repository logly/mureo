"""分析・調査系の統合ファサード Mixin。

各サブモジュールの Mixin を多重継承で統合する。
外部からは ``from mureo.google_ads._analysis import _AnalysisMixin`` で
従来と同じ1つのクラスとしてインポートできる。

後方互換: _PERIOD_DAYS, _get_comparison_date_ranges, _calc_change_rate,
_safe_metrics, _extract_ngrams, _INFORMATIONAL_PATTERNS も再エクスポートする。
"""

from __future__ import annotations

# 後方互換用の再エクスポート
from mureo.google_ads._analysis_constants import (  # noqa: F401
    _INFORMATIONAL_PATTERNS,
    _MATCH_TYPE_MAP,
    _PERIOD_DAYS,
    _STATUS_MAP,
    _calc_change_rate,
    _extract_ngrams,
    _get_comparison_date_ranges,
    _safe_metrics,
)

from mureo.google_ads._analysis_auction import _AuctionAnalysisMixin
from mureo.google_ads._analysis_btob import _BtoBAnalysisMixin
from mureo.google_ads._analysis_budget import _BudgetAnalysisMixin
from mureo.google_ads._analysis_keywords import _KeywordsAnalysisMixin
from mureo.google_ads._analysis_performance import _PerformanceAnalysisMixin
from mureo.google_ads._analysis_rsa import _RsaAnalysisMixin
from mureo.google_ads._analysis_search_terms import _SearchTermsAnalysisMixin


class _AnalysisMixin(
    _PerformanceAnalysisMixin,
    _SearchTermsAnalysisMixin,
    _KeywordsAnalysisMixin,
    _BudgetAnalysisMixin,
    _RsaAnalysisMixin,
    _AuctionAnalysisMixin,
    _BtoBAnalysisMixin,
):
    """分析・調査系の複合ツールを提供する Mixin（ファサード）"""

    pass
