"""Delivery-impact preview for bulk exclusions / blocks / negatives (#547).

mureo used to apply an exclusion batch without saying how much of the
account's delivery it removes. Every other item filed from the same
incident post-mortem shortens the recovery; this one is the only mechanism
that stops the mistake being made.

The package is pure and platform-neutral:

- :mod:`~mureo.analysis.exclusion_impact.models` — the vocabulary
  (delivery rows, exclusion targets, the three coverage verdicts).
- :mod:`~mureo.analysis.exclusion_impact.matching` — does excluding this
  entity stop that row delivering, per entity kind.
- :mod:`~mureo.analysis.exclusion_impact.estimator` — the share itself,
  incremental and cumulative.
- :mod:`~mureo.analysis.exclusion_impact.rules` — the ``## Guardrails``
  keys, and the one function that decides a refusal.
- :mod:`~mureo.analysis.exclusion_impact.surfaces` — which tools are
  exclusion surfaces and where their numbers come from (mureo's own, plus
  whatever a plugin registers).

The I/O lives outside it, in :mod:`mureo.mcp.exclusion_sources` (the
built-in Google/Meta data sources) and :mod:`mureo.mcp.exclusion_preflight`
(the dispatcher hook).
"""

from __future__ import annotations

from mureo.analysis.exclusion_impact.estimator import estimate_exclusion_impact
from mureo.analysis.exclusion_impact.matching import (
    normalize_app,
    normalize_website,
    target_matches,
    tokenize,
)
from mureo.analysis.exclusion_impact.models import (
    COVERAGE_MEASURED,
    COVERAGE_PARTIAL,
    COVERAGE_UNKNOWN,
    ENTITY_MOBILE_APP_CATEGORY,
    ENTITY_MOBILE_APPLICATION,
    ENTITY_SEARCH_TERM,
    ENTITY_WEBSITE,
    METRICS,
    DeliveryRecord,
    ExclusionImpact,
    ExclusionTarget,
    MetricShare,
)
from mureo.analysis.exclusion_impact.rules import (
    DEFAULT_METRICS,
    DEFAULT_WINDOW_DAYS,
    MAX_WINDOW_DAYS,
    ExclusionImpactRules,
    UnevaluatedRule,
    evaluate_exclusion_impact,
    exclusion_impact_rules,
    unevaluated_rules,
)
from mureo.analysis.exclusion_impact.surfaces import (
    DeliverySample,
    ExclusionSurface,
    exclusion_surface_for,
    register_exclusion_surface,
    registered_exclusion_tools,
    reset_exclusion_surfaces,
)

__all__ = [
    "COVERAGE_MEASURED",
    "COVERAGE_PARTIAL",
    "COVERAGE_UNKNOWN",
    "DEFAULT_METRICS",
    "DEFAULT_WINDOW_DAYS",
    "ENTITY_MOBILE_APPLICATION",
    "ENTITY_MOBILE_APP_CATEGORY",
    "ENTITY_SEARCH_TERM",
    "ENTITY_WEBSITE",
    "MAX_WINDOW_DAYS",
    "METRICS",
    "DeliveryRecord",
    "DeliverySample",
    "ExclusionImpact",
    "ExclusionImpactRules",
    "ExclusionSurface",
    "ExclusionTarget",
    "MetricShare",
    "UnevaluatedRule",
    "estimate_exclusion_impact",
    "evaluate_exclusion_impact",
    "exclusion_impact_rules",
    "exclusion_surface_for",
    "normalize_app",
    "normalize_website",
    "register_exclusion_surface",
    "registered_exclusion_tools",
    "reset_exclusion_surfaces",
    "target_matches",
    "tokenize",
    "unevaluated_rules",
]
