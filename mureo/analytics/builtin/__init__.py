"""Built-in :class:`AnalyticsModule` adapters for mureo-native platforms.

:func:`builtin_analytics_modules` builds one fresh instance of each
adapter; :func:`mureo.analytics.registry.default_analytics_registry`
registers them on the default :class:`AnalyticsRegistry` on first use.
This package does not import the registry: the registry imports it, so
the dependency runs one way (#879) — application code rarely imports
this module directly.

Each adapter is intentionally thin: it advertises which workflow-skill
capabilities the platform's mureo-native surface supports today and
delegates anomaly logic to :mod:`mureo.analysis.anomaly_detector`
(the same pure detector that ``analysis_anomalies_check`` already
uses). Methods the platform does not implement raise
:class:`NotImplementedError`, matching the Protocol contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule

if TYPE_CHECKING:
    from mureo.analytics.protocol import AnalyticsModule


def builtin_analytics_modules() -> tuple[AnalyticsModule, ...]:
    """One fresh instance of every built-in adapter.

    Called by :func:`mureo.analytics.registry.default_analytics_registry`
    on each fresh registry, so tests that clear the registry get the
    built-ins back on the next default-registry lookup.
    """
    return (GoogleAdsAnalyticsModule(), MetaAdsAnalyticsModule())


__all__ = [
    "GoogleAdsAnalyticsModule",
    "MetaAdsAnalyticsModule",
    "builtin_analytics_modules",
]
