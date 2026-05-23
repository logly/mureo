"""The :class:`AnalyticsModule` Protocol and capability enum.

A module is **opt-in** and **hand-authored** per platform. The four
methods cover the workflow-skill surface mureo cares about today:

- :meth:`detect_anomalies` — daily-check / rescue.
- :meth:`diagnose_performance` — daily-check / weekly-report.
- :meth:`audit_creative` — creative-refresh.
- :meth:`analyze_budget_efficiency` — budget-rebalance.

A module SHOULD declare its true surface via :meth:`capabilities`. A
skill MAY consult capabilities to short-circuit before calling a method
that the module does not implement — calling an unsupported method
SHOULD raise :class:`NotImplementedError` (the registry does NOT
synthesize a stub).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mureo.analytics.models import (
        Anomaly,
        BudgetEfficiency,
        CreativeAudit,
        PerformanceDiagnosis,
        PerformanceScope,
    )


class AnalyticsCapability(str, Enum):
    """Declarative flags a module advertises via :meth:`capabilities`.

    A skill that needs ``DETECT_ANOMALIES`` and finds a module that
    does not list it should treat that module as silent for that
    workflow rather than calling the method and catching
    :class:`NotImplementedError`.
    """

    DETECT_ANOMALIES = "detect_anomalies"
    DIAGNOSE_PERFORMANCE = "diagnose_performance"
    AUDIT_CREATIVE = "audit_creative"
    ANALYZE_BUDGET_EFFICIENCY = "analyze_budget_efficiency"


@runtime_checkable
class AnalyticsModule(Protocol):
    """Opt-in, hand-authored analytics contract for one ad platform.

    Implementations live in:

    - ``mureo.analytics.builtin.*`` for mureo-native platforms
      (google_ads, meta_ads); these are auto-registered.
    - A third-party package registering an entry point in the
      ``mureo.analytics`` group; these are discovered lazily.

    The Protocol is :func:`runtime_checkable` so the registry can do
    duck-typed validation. Concrete implementations are typically
    classes with no-argument constructors (mirrors
    :class:`mureo.mcp.tool_provider.MCPToolProvider`'s contract).
    """

    platform: str
    """Stable platform identifier (e.g. ``"google_ads"``, ``"amazon_ads"``).

    MUST match the platform name used in STATE.json ``platforms`` and in
    the corresponding provider's ``name`` so a skill can join the two.
    """

    def capabilities(self) -> frozenset[AnalyticsCapability]:
        """Return the set of methods this module actually supports.

        MUST be pure and cheap — called at lookup time, not per workflow
        invocation. Implementations SHOULD return a class-level constant
        rather than re-computing per call.
        """
        ...

    async def detect_anomalies(
        self,
        account_id: str,
        *,
        window_days: int = 7,
    ) -> tuple[Anomaly, ...]:
        """Detect anomalies on ``account_id`` over the trailing window.

        Implementations MUST gate alerts by sample size (per the
        ``_mureo-learning`` skill's evidence rules) — single-day noise
        must not fire an alert.

        Raises :class:`NotImplementedError` when the module does not
        advertise ``DETECT_ANOMALIES``.
        """
        ...

    async def diagnose_performance(
        self,
        account_id: str,
        *,
        scope: PerformanceScope,
    ) -> PerformanceDiagnosis:
        """Diagnose account/campaign performance at the requested ``scope``.

        Raises :class:`NotImplementedError` when the module does not
        advertise ``DIAGNOSE_PERFORMANCE``.
        """
        ...

    async def audit_creative(
        self,
        account_id: str,
    ) -> CreativeAudit:
        """Audit creative assets (RSA, RDA, image, video, copy).

        Raises :class:`NotImplementedError` when the module does not
        advertise ``AUDIT_CREATIVE``.
        """
        ...

    async def analyze_budget_efficiency(
        self,
        account_id: str,
    ) -> BudgetEfficiency:
        """Score budget efficiency and suggest reallocation.

        Raises :class:`NotImplementedError` when the module does not
        advertise ``ANALYZE_BUDGET_EFFICIENCY``.
        """
        ...


__all__ = [
    "AnalyticsCapability",
    "AnalyticsModule",
]
