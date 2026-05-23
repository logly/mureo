"""Built-in :class:`AnalyticsModule` adapters for mureo-native platforms.

Importing this package self-registers the adapters on the default
:class:`AnalyticsRegistry`. Side-effect import is the standard Python
pattern for plugin-style registration and is invoked by
:func:`mureo.analytics.registry.default_analytics_registry` on first
use — application code rarely imports this module directly.

Each adapter is intentionally thin: it advertises which workflow-skill
capabilities the platform's mureo-native surface supports today and
delegates anomaly logic to :mod:`mureo.analysis.anomaly_detector`
(the same pure detector that ``analysis_anomalies_check`` already
uses). Methods the platform does not implement raise
:class:`NotImplementedError`, matching the Protocol contract.
"""

from __future__ import annotations

from mureo.analytics.builtin.google_ads import GoogleAdsAnalyticsModule
from mureo.analytics.builtin.meta_ads import MetaAdsAnalyticsModule


def register_builtin_analytics_modules() -> None:
    """Register every built-in adapter on the default registry.

    Idempotent: the registry's :meth:`register` enforces first-wins so a
    second call is a no-op. Called by
    :func:`mureo.analytics.registry.default_analytics_registry` on each
    fresh registry; tests that clear the registry get the built-ins back
    on the next default-registry lookup.

    Separated from a module-level side effect because Python caches
    imports in :data:`sys.modules` — a side-effect statement would fire
    only on the first interpreter import, leaving cleared test
    registries empty.
    """
    # Local import keeps the registry module free of an import cycle.
    from mureo.analytics.registry import register_analytics_module

    register_analytics_module(GoogleAdsAnalyticsModule())
    register_analytics_module(MetaAdsAnalyticsModule())


__all__ = [
    "GoogleAdsAnalyticsModule",
    "MetaAdsAnalyticsModule",
    "register_builtin_analytics_modules",
]
