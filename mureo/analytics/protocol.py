"""The :class:`AnalyticsModule` Protocol and capability enum.

A module is **opt-in** and **hand-authored** per platform. The four
required methods cover the workflow-skill surface mureo cares about
today:

- :meth:`detect_anomalies` — daily-check / rescue.
- :meth:`diagnose_performance` — daily-check / weekly-report.
- :meth:`audit_creative` — creative-refresh.
- :meth:`analyze_budget_efficiency` — budget-rebalance.

Delivery-collapse detection (#546) is an **optional extension** and is
deliberately NOT a fifth method on :class:`AnalyticsModule`. That
Protocol is ``runtime_checkable``, and ``isinstance`` against a
runtime-checkable Protocol requires *every* member — so adding a member
would have silently made every already-published four-method plugin fail
the check. The extension lives in its own
:class:`DeliveryCollapseModule` Protocol instead: a module opts in by
implementing ``detect_delivery_collapse`` and adding
:attr:`AnalyticsCapability.DETECT_DELIVERY_COLLAPSE` to its
:meth:`capabilities`. A module that does not simply never advertises it,
and ``mureo_analytics_run`` reports ``capability_not_available``.

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
    from datetime import date

    from mureo.analysis.delivery_collapse import CollapseThresholds
    from mureo.analytics.models import (
        Anomaly,
        BudgetEfficiency,
        CreativeAudit,
        DeliveryCollapseReport,
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
    #: #546 — optional. Only advertise it if the module can produce
    #: day-grain delivery for the account; the detector needs weeks of
    #: daily history to build a baseline, not a period aggregate.
    DETECT_DELIVERY_COLLAPSE = "detect_delivery_collapse"


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
    """Stable platform identifier (e.g. ``"google_ads"``, ``"meta_ads"``).

    For a **built-in** module this IS the STATE.json ``platforms`` key.

    For a platform mureo reaches through a **plugin or bridge**, this is the
    module's *registry name* and MUST equal the corresponding provider's
    ``name`` in the ``mureo.providers`` group. It is the ``<provider>`` half
    of the canonical key
    ``plugin:<distribution>:<provider>`` (#537), which mureo builds via
    :func:`mureo.core.platform_keys.plugin_platform_key` from the
    distribution that shipped the entry point. Naming the module differently
    from the provider produces two different keys for one platform, and
    analytics that silently never join with the action log or the
    ``platforms`` snapshots the bridge's own dispatch records.

    Do NOT write a ``plugin:``-prefixed value here: that namespace is
    reserved for keys mureo builds, and the registry refuses such a name.
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


@runtime_checkable
class DeliveryCollapseModule(Protocol):
    """Optional extension: scheduled delivery-collapse detection (#546).

    Separate from :class:`AnalyticsModule` on purpose — see that class's
    module docstring for why folding it in would have de-registered
    existing plugins. Implement BOTH Protocols to offer collapse
    detection; ``isinstance(module, DeliveryCollapseModule)`` is the
    structural check, and
    :attr:`AnalyticsCapability.DETECT_DELIVERY_COLLAPSE` is the
    advertised one.
    """

    platform: str

    async def detect_delivery_collapse(
        self,
        account_id: str,
        *,
        history_days: int = 60,
        thresholds: CollapseThresholds | None = None,
        as_of: date | None = None,
    ) -> DeliveryCollapseReport:
        """Flag campaigns whose delivery collapsed while set to serve.

        Implementations fetch
        ``history_days`` of day-grain delivery for ``account_id``,
        normalise it with
        :func:`mureo.analysis.delivery_collapse.delivery_series_from_rows`,
        and run the shared
        :func:`mureo.analysis.delivery_collapse.detect_delivery_collapses`.
        The detector is platform-agnostic on purpose: only the fetch is
        the module's job.

        A module that cannot produce day-grain delivery MUST return a
        report with ``status="data_unavailable"`` rather than an empty
        ``signals`` tuple — the two mean opposite things to an operator.

        ``thresholds=None`` means "read the operator's STRATEGY.md
        ``## Guardrails``" (see
        :func:`mureo.analysis.delivery_collapse_config.load_collapse_thresholds`).
        """
        ...


__all__ = [
    "AnalyticsCapability",
    "AnalyticsModule",
    "DeliveryCollapseModule",
]
