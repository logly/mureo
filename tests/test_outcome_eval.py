"""Tests for deterministic outcome evaluation (mureo.analysis.outcome_eval).

The verdict is the PRIMARY metric's verdict (#888). Every other metric is a
reference row: still scored, never deciding. The primary is judged only once
both sides reach the volume floor, and a count primary only per day.
"""

from __future__ import annotations

import json

import pytest

from mureo.analysis.outcome_eval import (
    BASIS_DEFAULT,
    BASIS_EXPECTED,
    DEFAULT_MIN_CLICKS,
    DEFAULT_MIN_CONVERSIONS,
    DEFAULT_MIN_IMPRESSIONS,
    DEFAULT_NOISE_PCT,
    DEFAULT_THRESHOLDS,
    OUTCOME_REASONS,
    VOLUME_GATE,
    OutcomeThresholds,
    PrimaryChoice,
    Verdict,
    canonical_metrics,
    evaluate_metric,
    evaluate_outcome,
    period_days,
)
from mureo.core.metrics_windows import CANONICAL_METRICS_WINDOWS

pytestmark = pytest.mark.unit

#: Enough volume on both sides for every gate.
VOLUME = {"conversions": 100, "impressions": 50_000, "clicks": 5_000}


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


class TestThresholds:
    def test_the_defaults(self) -> None:
        assert DEFAULT_NOISE_PCT == 10.0
        assert (DEFAULT_MIN_CONVERSIONS, DEFAULT_MIN_IMPRESSIONS) == (30, 1000)
        assert DEFAULT_MIN_CLICKS == 200
        assert (
            OutcomeThresholds(
                noise_pct=10.0,
                min_conversions=30,
                min_impressions=1000,
                min_clicks=200,
            )
            == DEFAULT_THRESHOLDS
        )

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"noise_pct": 0.0},
            {"noise_pct": -5.0},
            {"noise_pct": 150.0},
            {"min_conversions": 0},
            {"min_impressions": -1},
            {"min_clicks": 0},
            {"min_clicks": True},
            {"min_conversions": 2.5},
        ],
    )
    def test_out_of_range_is_refused(self, kwargs: dict[str, object]) -> None:
        fields: dict[str, object] = {
            "noise_pct": 10.0,
            "min_conversions": 30,
            "min_impressions": 1000,
            "min_clicks": 200,
            **kwargs,
        }
        with pytest.raises(ValueError):
            OutcomeThresholds(**fields)  # type: ignore[arg-type]

    def test_the_volume_gate_table(self) -> None:
        # cvr is a rate over clicks: its floor is the clicks the
        # _mureo-learning skill table states.
        assert VOLUME_GATE == {
            "cpa": "conversions",
            "cpl": "conversions",
            "roas": "conversions",
            "conversions": "conversions",
            "cvr": "clicks",
            "ctr": "impressions",
            "cpm": "impressions",
            "cpc": "clicks",
        }

    def test_the_reasons_are_a_closed_set(self) -> None:
        assert OUTCOME_REASONS == (
            "no_primary_metric",
            "insufficient_volume",
            "volume_unknown",
            "period_unknown",
            "zero_baseline",
            "target_not_reached",
            "no_change",
        )


class TestPeriodDays:
    def test_explicit_days(self) -> None:
        assert period_days({"days": 7}) == 7

    def test_days_wins_over_period(self) -> None:
        assert period_days({"days": 14, "period": "LAST_30_DAYS"}) == 14

    @pytest.mark.parametrize("token", list(CANONICAL_METRICS_WINDOWS))
    def test_every_window_token(self, token: str) -> None:
        assert period_days({"period": token}) == CANONICAL_METRICS_WINDOWS[token]

    def test_a_token_is_normalised(self) -> None:
        assert period_days({"period": " last_7_days "}) == 7

    @pytest.mark.parametrize(
        "metrics",
        [
            {},
            {"days": 0},
            {"days": -7},
            {"days": True},
            {"days": "7"},
            {"period": "SINCE_LAUNCH"},
            {"period": 30},
        ],
    )
    def test_unknown(self, metrics: dict[str, object]) -> None:
        assert period_days(metrics) is None


class TestCanonicalMetrics:
    def test_cost_and_spend_merge(self) -> None:
        assert canonical_metrics({"cost": 100}) == {"spend": 100.0}

    def test_the_canonical_name_wins(self) -> None:
        merged = canonical_metrics({"cost_per_conversion": 900, "cpa": 1000})
        assert merged == {"cpa": 1000.0}

    def test_otherwise_the_first_in_sorted_order(self) -> None:
        merged = canonical_metrics(
            {"cost_per_conversion": 900, "cost_per_acquisition": 800}
        )
        assert merged == {"cpa": 800.0}

    def test_period_keys_and_text_are_not_figures(self) -> None:
        merged = canonical_metrics(
            {"cpa": 1, "days": 7, "period": "LAST_7_DAYS", "note": "x"}
        )
        assert merged == {"cpa": 1.0}


class TestPrimaryMetric:
    def test_cpa_down_with_ctr_down_is_improved(self) -> None:
        """The case "any regression wins" got wrong (#888 problem 1)."""
        report = evaluate_outcome(
            {"cpa": 5000, "ctr": 2.0, **VOLUME},
            {"cpa": 3500, "ctr": 1.78, **VOLUME},
        )
        assert report.overall is Verdict.IMPROVED
        assert report.primary == "cpa"
        assert report.basis == BASIS_DEFAULT
        assert report.reason is None
        assert report.summary == "Improved on cpa (primary)."
        ctr = next(m for m in report.metrics if m.metric == "ctr")
        assert ctr.verdict is Verdict.REGRESSED

    def test_a_regressed_cpa_is_regressed_whatever_else_improved(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "ctr": 2.0, **VOLUME},
            {"cpa": 7000, "ctr": 3.0, **VOLUME},
        )
        assert report.overall is Verdict.REGRESSED
        assert report.summary == "Regressed on cpa (primary)."

    def test_inside_the_band_is_no_change(self) -> None:
        report = evaluate_outcome({"cpa": 5000, **VOLUME}, {"cpa": 5100, **VOLUME})
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.reason == "no_change"
        assert report.summary == "Inconclusive: no_change on cpa."

    def test_without_conversions_there_is_no_primary(self) -> None:
        report = evaluate_outcome(
            {"ctr": 2.0, "impressions": 50_000}, {"ctr": 3.0, "impressions": 50_000}
        )
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.primary is None
        assert report.reason == "no_primary_metric"
        assert report.summary == "Inconclusive: no_primary_metric."

    def test_zero_conversions_on_one_side_is_no_primary(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 0}, {"cpa": 4000, "conversions": 50}
        )
        assert report.reason == "no_primary_metric"

    def test_a_volume_only_change_is_inconclusive(self) -> None:
        report = evaluate_outcome({"cost": 100000}, {"cost": 200000})
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.reason == "no_primary_metric"

    def test_only_common_numeric_metrics_are_rows(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "note": "text", "conversions": 50},
            {"cpa": 4000},
        )
        assert {m.metric for m in report.metrics} == {"cpa"}

    def test_string_numbers_are_coerced(self) -> None:
        report = evaluate_outcome(
            {"cpa": "5,000", "conversions": "100"},
            {"cpa": "4,000", "conversions": "120"},
        )
        assert report.overall is Verdict.IMPROVED

    def test_a_given_primary_decides(self) -> None:
        report = evaluate_outcome(
            {"roas": 3.0, "cpa": 5000, **VOLUME},
            {"roas": 4.0, "cpa": 9000, **VOLUME},
            primary=PrimaryChoice(metric="roas", basis="bidding_target", effect=None),
        )
        assert report.overall is Verdict.IMPROVED
        assert (report.primary, report.basis) == ("roas", "bidding_target")

    def test_a_zero_baseline_names_its_reason(self) -> None:
        report = evaluate_outcome(
            {"roas": 0, **VOLUME},
            {"roas": 3.0, **VOLUME},
            primary=PrimaryChoice(metric="roas", basis="bidding_target", effect=None),
        )
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.reason == "zero_baseline"
        assert report.summary == "Inconclusive: zero_baseline on roas."
        row = next(m for m in report.metrics if m.metric == "roas")
        assert row.verdict is Verdict.INCONCLUSIVE
        assert "zero_baseline" in row.note

    def test_a_count_primary_with_unknown_days_names_it_on_the_row(self) -> None:
        report = evaluate_outcome(
            {"spend": 1000},
            {"spend": 1500},
            primary=PrimaryChoice(metric="spend", basis=BASIS_EXPECTED, effect=None),
        )
        assert report.reason == "period_unknown"
        row = next(m for m in report.metrics if m.metric == "spend")
        assert row.verdict is Verdict.INCONCLUSIVE
        assert "period_unknown" in row.note

    def test_a_declared_primary_without_figures_keeps_its_name(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, **VOLUME},
            {"cpa": 4000, **VOLUME},
            primary=PrimaryChoice(metric="spend", basis=BASIS_EXPECTED, effect=None),
        )
        assert report.reason == "no_primary_metric"
        assert report.primary == "spend"
        assert report.summary == "Inconclusive: no_primary_metric on spend."

    def test_a_given_primary_without_figures_is_no_primary(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, **VOLUME},
            {"cpa": 4000, **VOLUME},
            primary=PrimaryChoice(metric="roas", basis=BASIS_EXPECTED, effect=None),
        )
        assert report.reason == "no_primary_metric"
        assert report.basis == BASIS_EXPECTED


class TestSynonyms:
    def test_cpa_and_cost_per_conversion_are_one_row(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "cost_per_conversion": 5000, **VOLUME},
            {"cpa": 4000, "cost_per_conversion": 9000, **VOLUME},
        )
        assert [m.metric for m in report.metrics].count("cpa") == 1
        assert "cost_per_conversion" not in {m.metric for m in report.metrics}
        assert report.overall is Verdict.IMPROVED

    def test_a_cost_baseline_meets_a_spend_snapshot(self) -> None:
        report = evaluate_outcome({"cost": 1000, "days": 7}, {"spend": 1500, "days": 7})
        assert [m.metric for m in report.metrics] == ["spend"]


class TestVolumeGate:
    def test_three_conversions_to_two_is_insufficient_volume(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 3}, {"cpa": 7500, "conversions": 2}
        )
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.reason == "insufficient_volume"
        assert report.primary == "cpa"
        assert report.summary == "Inconclusive: insufficient_volume on cpa."
        # The primary row agrees with the verdict: 5000 -> 7500 is not
        # reported as a regression the gate held back.
        row = next(m for m in report.metrics if m.metric == "cpa")
        assert row.verdict is Verdict.INCONCLUSIVE
        assert "insufficient_volume" in row.note
        # A reference row is still judged on its own.
        conversions = next(m for m in report.metrics if m.metric == "conversions")
        assert conversions.verdict is Verdict.REGRESSED

    def test_one_side_under_the_floor_is_enough_to_hold_back(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 100}, {"cpa": 2000, "conversions": 29}
        )
        assert report.reason == "insufficient_volume"

    def test_the_floor_itself_passes(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 30}, {"cpa": 4000, "conversions": 30}
        )
        assert report.overall is Verdict.IMPROVED

    def test_a_missing_count_is_volume_unknown(self) -> None:
        report = evaluate_outcome(
            {"ctr": 2.0},
            {"ctr": 3.0},
            primary=PrimaryChoice(metric="ctr", basis=BASIS_EXPECTED, effect=None),
        )
        assert report.reason == "volume_unknown"

    @pytest.mark.parametrize(
        ("metric", "count", "floor"),
        [
            ("ctr", "impressions", 1000),
            ("cpm", "impressions", 1000),
            ("cpc", "clicks", 200),
            ("cvr", "clicks", 200),
        ],
    )
    def test_each_count_key(self, metric: str, count: str, floor: int) -> None:
        choice = PrimaryChoice(metric=metric, basis=BASIS_EXPECTED, effect=None)
        low = evaluate_outcome(
            {metric: 1.0, count: floor - 1}, {metric: 2.0, count: floor}, primary=choice
        )
        assert low.reason == "insufficient_volume"
        enough = evaluate_outcome(
            {metric: 1.0, count: floor}, {metric: 2.0, count: floor}, primary=choice
        )
        assert enough.reason != "insufficient_volume"

    def test_the_floor_comes_from_the_thresholds(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 3},
            {"cpa": 4000, "conversions": 3},
            thresholds=OutcomeThresholds(
                noise_pct=10.0, min_conversions=3, min_impressions=1, min_clicks=1
            ),
        )
        assert report.overall is Verdict.IMPROVED

    def test_the_gate_uses_raw_counts_not_per_day(self) -> None:
        # 60 conversions over 30 days is 2 a day; the floor is on the 60.
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 60, "days": 30},
            {"cpa": 4000, "conversions": 60, "days": 30},
        )
        assert report.overall is Verdict.IMPROVED


class TestCountRowsWithoutPeriods:
    def test_a_count_row_with_unknown_days_says_it_is_a_raw_total(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "clicks": 900, "conversions": 100},
            {"cpa": 4000, "clicks": 950, "conversions": 100},
        )
        clicks = next(m for m in report.metrics if m.metric == "clicks")
        assert "raw totals, periods unknown" in clicks.note
        cpa = next(m for m in report.metrics if m.metric == "cpa")
        assert "raw totals" not in cpa.note

    def test_a_count_row_with_known_days_is_per_day_not_raw(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "clicks": 900, "conversions": 100, "days": 7},
            {"cpa": 4000, "clicks": 950, "conversions": 100, "days": 7},
        )
        clicks = next(m for m in report.metrics if m.metric == "clicks")
        assert "per day over" in clicks.note
        assert "raw totals" not in clicks.note


class TestPeriods:
    def test_a_7_day_and_a_30_day_count_are_compared_per_day(self) -> None:
        # 70 in 7 days and 300 in 30 days are both 10 a day: no change, not
        # the +329% the raw totals would read as.
        report = evaluate_outcome(
            {"conversions": 70, "days": 7},
            {"conversions": 300, "period": "LAST_30_DAYS"},
            primary=PrimaryChoice(
                metric="conversions", basis=BASIS_EXPECTED, effect=None
            ),
        )
        row = report.metrics[0]
        assert (row.before, row.after) == (10.0, 10.0)
        assert row.delta_pct == 0.0
        assert "per day" in row.note
        assert report.reason == "no_change"

    def test_an_unknown_day_count_is_period_unknown(self) -> None:
        report = evaluate_outcome(
            {"conversions": 70},
            {"conversions": 300, "period": "LAST_30_DAYS"},
            primary=PrimaryChoice(
                metric="conversions", basis=BASIS_EXPECTED, effect=None
            ),
        )
        assert report.overall is Verdict.INCONCLUSIVE
        assert report.reason == "period_unknown"
        assert report.summary == "Inconclusive: period_unknown on conversions."

    def test_a_ratio_primary_compares_across_lengths(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 40, "days": 7},
            {"cpa": 4000, "conversions": 200, "period": "LAST_30_DAYS"},
        )
        assert report.overall is Verdict.IMPROVED

    def test_a_ratio_primary_needs_no_day_count(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 40}, {"cpa": 4000, "conversions": 40}
        )
        assert report.overall is Verdict.IMPROVED

    def test_reference_counts_without_days_stay_totals(self) -> None:
        report = evaluate_outcome(
            {"cpa": 5000, "conversions": 40, "clicks": 700},
            {"cpa": 4000, "conversions": 40, "clicks": 3000},
        )
        clicks = next(m for m in report.metrics if m.metric == "clicks")
        assert (clicks.before, clicks.after) == (700.0, 3000.0)


class TestMcpTool:
    """The mureo_outcome_evaluate MCP tool is registered and returns JSON."""

    @pytest.mark.asyncio
    async def test_tool_registered_and_evaluates(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS, handle_tool

        assert any(t.name == "mureo_outcome_evaluate" for t in TOOLS)

        result = await handle_tool(
            "mureo_outcome_evaluate",
            {
                "before": {"cpa": 5000, "conversions": 40},
                "after": {"cpa": 4000, "conversions": 50},
            },
        )
        payload = json.loads(result[0].text)
        assert payload["overall"] == "improved"
        assert payload["primary"] == "cpa"
        assert payload["basis"] == "default"
        assert "reason" not in payload
        cpa = next(m for m in payload["metrics"] if m["metric"] == "cpa")
        assert cpa["delta_pct"] == -20.0

    @pytest.mark.asyncio
    async def test_an_inconclusive_result_names_its_reason(self) -> None:
        from mureo.mcp.tools_mureo_context import handle_tool

        result = await handle_tool(
            "mureo_outcome_evaluate",
            {
                "before": {"cpa": 5000, "conversions": 3},
                "after": {"cpa": 7500, "conversions": 2},
            },
        )
        payload = json.loads(result[0].text)
        assert payload["overall"] == "inconclusive"
        assert payload["reason"] == "insufficient_volume"
        assert payload["summary"] == "Inconclusive: insufficient_volume on cpa."

    @pytest.mark.asyncio
    async def test_tool_rejects_non_object_args(self) -> None:
        from mureo.mcp.tools_mureo_context import handle_tool

        with pytest.raises(ValueError):
            await handle_tool(
                "mureo_outcome_evaluate", {"before": [1, 2], "after": {"cpa": 1}}
            )
