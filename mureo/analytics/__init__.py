"""Analytics-module surface for external-integration platforms (Issue #120).

External integrations — official MCPs and third-party plugins alike —
expose only tool names, input schemas, and opaque result blobs. mureo
cannot synthesize platform-specific anomaly heuristics, CV-definition
checks, or budget analyses from that surface; doing so would fabricate
plausible-but-wrong analysis and violate the trustworthiness principle.

This package defines the **hand-authored, opt-in** analytics-module
contract that lets a package (built-in adapter, official-MCP wrapper,
or third-party plugin) ship platform-specific analytics that mureo's
workflow skills can consume uniformly. Absence of a module for a given
platform is a first-class, honestly-reported state.

Public surface (re-exports):

- :class:`AnalyticsModule` — the Protocol every analytics module
  implements.
- :class:`AnalyticsCapability` — declarative capability flags so skills
  can ask "does this platform support X" without invoking it.
- :class:`Anomaly`, :class:`PerformanceDiagnosis`,
  :class:`CreativeAudit`, :class:`BudgetEfficiency` — frozen
  dataclasses returned by the four Protocol methods.
- :class:`AnalyticsRegistry`, :func:`get_analytics_module`,
  :func:`list_analytics_platforms`,
  :func:`discover_analytics_modules`, :func:`register_analytics_module`
  — discovery + lookup of registered modules.
- :class:`AnalyticsModuleWarning` — warning emitted when a plugin's
  analytics module is skipped (fault-isolated discovery).
- :data:`ANALYTICS_ENTRY_POINT_GROUP` — the entry-points group plugins
  register against (``"mureo.analytics"``).
"""

from __future__ import annotations

from mureo.analytics.models import (
    Anomaly,
    AnomalySeverity,
    BudgetEfficiency,
    CreativeAudit,
    CreativeFinding,
    PerformanceDiagnosis,
    PerformanceScope,
)
from mureo.analytics.protocol import AnalyticsCapability, AnalyticsModule
from mureo.analytics.registry import (
    ANALYTICS_ENTRY_POINT_GROUP,
    AnalyticsModuleWarning,
    AnalyticsRegistry,
    clear_analytics_registry,
    default_analytics_registry,
    discover_analytics_modules,
    get_analytics_module,
    list_analytics_platforms,
    plugin_source,
    register_analytics_module,
)

__all__ = [
    "ANALYTICS_ENTRY_POINT_GROUP",
    "AnalyticsCapability",
    "AnalyticsModule",
    "AnalyticsModuleWarning",
    "AnalyticsRegistry",
    "Anomaly",
    "AnomalySeverity",
    "BudgetEfficiency",
    "CreativeAudit",
    "CreativeFinding",
    "PerformanceDiagnosis",
    "PerformanceScope",
    "clear_analytics_registry",
    "default_analytics_registry",
    "discover_analytics_modules",
    "get_analytics_module",
    "list_analytics_platforms",
    "plugin_source",
    "register_analytics_module",
]
