"""Tests for deterministic outcome evaluation (mureo.analysis.outcome_eval)."""

from __future__ import annotations

import pytest

from mureo.analysis.outcome_eval import Verdict, evaluate_metric, evaluate_outcome

pytestmark = pytest.mark.unit


class TestEvaluateMetric:
    def test_cpa_drop_is_improvement(self) -> None:
        o = evaluate_metric("cpa", 5000, 4000)
        assert o.verdict is Verdict.IMPROVED
        assert o.delta_pct == -20.0

    def test_cpa_rise_is_regression(self) -> None:
        assert evaluate_metric("cpa", 4000, 5000).verdict is Verdict.REGRESSED

    def test_conversions_up_is_improvement(self) -> None:
        assert evaluate_metric("conversions", 40, 60).verdict is Verdict.IMPROVED

    def test_conversions_down_is_regression(self) -> None:
        assert evaluate_metric("conversions", 60, 40).verdict is Verdict.REGRESSED

    def test_small_change_within_noise_is_inconclusive(self) -> None:
        assert evaluate_metric("cpa", 5000, 4750).verdict is Verdict.INCONCLUSIVE

    def test_custom_noise_band(self) -> None:
        assert (
            evaluate_metric("cpa", 5000, 4750, noise_pct=2.0).verdict
            is Verdict.IMPROVED
        )

    def test_zero_baseline_is_inconclusive(self) -> None:
        o = evaluate_metric("conversions", 0, 30)
        assert o.verdict is Verdict.INCONCLUSIVE
        assert o.delta_pct is None

    def test_volume_metric_has_no_verdict(self) -> None:
        assert evaluate_metric("cost", 100000, 200000).verdict is Verdict.INCONCLUSIVE

    def test_metric_name_is_case_insensitive(self) -> None:
        assert evaluate_metric("CPA", 5000, 4000).verdict is Verdict.IMPROVED


class TestEvaluateOutcome:
    def test_regression_dominates_overall(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 50},
            {"cpa": 7000, "conversions": 55},
        )
        assert report.overall is Verdict.REGRESSED

    def test_improvement_when_no_regression(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 50},
            {"cpa": 4000, "conversions": 50},
        )
        assert report.overall is Verdict.IMPROVED

    def test_inconclusive_when_all_within_noise(self) -> None:
        assert (
            evaluate_outcome({"cpa": 5000}, {"cpa": 5100}).overall
            is Verdict.INCONCLUSIVE
        )

    def test_only_common_numeric_metrics_compared(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "note": "text", "conversions": 50},
            {"cpa": 4000},
        )
        assert {m.metric for m in report.metrics} == {"cpa"}

    def test_volume_only_change_is_inconclusive_overall(self) -> None:
        assert (
            evaluate_outcome({"cost": 100000}, {"cost": 200000}).overall
            is Verdict.INCONCLUSIVE
        )

    def test_string_numbers_coerced(self) -> None:
        # Metrics arriving as formatted strings (e.g. from a hosted connector).
        report = evaluate_outcome({"cpa": "5,000"}, {"cpa": "4,000"})
        assert report.overall is Verdict.IMPROVED


class TestMcpTool:
    """The mureo_outcome_evaluate MCP tool is registered and returns JSON."""

    @pytest.mark.asyncio
    async def test_tool_registered_and_evaluates(self) -> None:
        import json

        from mureo.mcp.tools_mureo_context import TOOLS, handle_tool

        assert any(t.name == "mureo_outcome_evaluate" for t in TOOLS)

        result = await handle_tool(
            "mureo_outcome_evaluate",
            {"before": {"cpa": 5000}, "after": {"cpa": 4000}},
        )
        payload = json.loads(result[0].text)
        assert payload["overall"] == "improved"
        assert payload["metrics"][0]["metric"] == "cpa"
        assert payload["metrics"][0]["delta_pct"] == -20.0

    @pytest.mark.asyncio
    async def test_tool_rejects_non_object_args(self) -> None:
        from mureo.mcp.tools_mureo_context import handle_tool

        with pytest.raises(ValueError):
            await handle_tool(
                "mureo_outcome_evaluate", {"before": [1, 2], "after": {"cpa": 1}}
            )
