"""Frozen-dataclass and enum invariants for ``mureo.analytics.models``."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, is_dataclass

import pytest

from mureo.analytics.models import (
    Anomaly,
    AnomalySeverity,
    BudgetEfficiency,
    CreativeAudit,
    CreativeFinding,
    PerformanceDiagnosis,
    PerformanceScope,
)

_MODELS = (
    Anomaly,
    PerformanceDiagnosis,
    CreativeFinding,
    CreativeAudit,
    BudgetEfficiency,
)


@pytest.mark.unit
@pytest.mark.parametrize("model", _MODELS)
def test_models_are_frozen_dataclasses(model: type) -> None:
    assert is_dataclass(model), f"{model.__name__} must be a dataclass"
    assert (
        model.__dataclass_params__.frozen
    ), f"{model.__name__} must be frozen=True per the repo immutability rule"


@pytest.mark.unit
def test_anomaly_frozen_raises_on_mutation() -> None:
    a = Anomaly(
        campaign_id="c1",
        metric="cpa",
        severity=AnomalySeverity.HIGH,
        current_value=100.0,
        baseline_value=50.0,
        deviation_pct=1.0,
        sample_size=42,
        message="m",
        recommended_action="r",
    )
    with pytest.raises(FrozenInstanceError):
        a.metric = "cost"  # type: ignore[misc]


@pytest.mark.unit
def test_severity_is_str_for_json_serialization() -> None:
    # str mixin so ``json.dumps`` works without a custom encoder.
    assert AnomalySeverity.CRITICAL == "critical"
    assert AnomalySeverity.HIGH == "high"


@pytest.mark.unit
def test_performance_scope_values() -> None:
    assert PerformanceScope.ACCOUNT == "account"
    assert PerformanceScope.CAMPAIGN == "campaign"
    assert PerformanceScope.DEEP == "deep"


@pytest.mark.unit
def test_performance_diagnosis_defaults() -> None:
    # Optional fields default to empty so a minimal honest stub is cheap.
    d = PerformanceDiagnosis(
        platform="x",
        account_id="a",
        scope=PerformanceScope.ACCOUNT,
        headline="h",
        findings=(),
    )
    assert d.metrics == ()


@pytest.mark.unit
def test_budget_efficiency_defaults() -> None:
    b = BudgetEfficiency(platform="x", account_id="a")
    assert b.per_campaign_score == ()
    assert b.rebalance_suggestion == ""
    assert b.unused_budget_amount == 0.0


@pytest.mark.unit
def test_creative_audit_defaults_empty_findings() -> None:
    audit = CreativeAudit(platform="x", account_id="a")
    assert audit.findings == ()


@pytest.mark.unit
def test_anomaly_field_set_is_stable() -> None:
    # Field set is part of the plugin ABI — new fields must be added
    # with defaults so existing plugins keep constructing.
    expected = {
        "campaign_id",
        "metric",
        "severity",
        "current_value",
        "baseline_value",
        "deviation_pct",
        "sample_size",
        "message",
        "recommended_action",
    }
    assert {f.name for f in fields(Anomaly)} == expected
