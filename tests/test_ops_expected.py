"""The structured ``expected`` effect (#848, ops history phase 1).

``expected`` is the declaration "this change should move THESE metrics in
THIS direction". It is validated against the outcome evaluator's own metric
vocabulary, so a declared metric is always one the evaluation can score.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from mureo.analysis.outcome_eval import _METRIC_DIRECTION
from mureo.context.expected import (
    EXPECTED_DIRECTIONS,
    EXPECTED_HORIZON_MAX_DAYS,
    EXPECTED_MAX_ITEMS,
    EXPECTED_METRICS,
    ExpectedEffect,
    expected_to_list,
    parse_expected,
)

pytestmark = pytest.mark.unit


class TestVocabulary:
    def test_the_metrics_are_the_issue_list(self) -> None:
        assert EXPECTED_METRICS == (
            "cpa",
            "cpc",
            "cpl",
            "cpm",
            "conversions",
            "cvr",
            "ctr",
            "roas",
            "cost",
            "spend",
            "clicks",
            "impressions",
        )

    def test_every_metric_is_known_to_the_outcome_evaluator(self) -> None:
        assert set(EXPECTED_METRICS) <= set(_METRIC_DIRECTION)

    def test_the_directions(self) -> None:
        assert EXPECTED_DIRECTIONS == ("up", "down", "hold")


class TestParseExpected:
    def test_absent_is_empty(self) -> None:
        assert parse_expected(None) == ()

    def test_a_minimal_item(self) -> None:
        parsed = parse_expected([{"metric": "cpa", "direction": "down"}])
        assert parsed == (ExpectedEffect(metric="cpa", direction="down"),)

    def test_target_and_horizon_are_kept(self) -> None:
        parsed = parse_expected(
            [{"metric": "roas", "direction": "up", "target": 4.5, "horizon_days": 14}]
        )
        assert parsed[0].target == 4.5
        assert parsed[0].horizon_days == 14

    def test_metric_and_direction_are_normalised(self) -> None:
        parsed = parse_expected([{"metric": " CPA ", "direction": "Down"}])
        assert parsed[0] == ExpectedEffect(metric="cpa", direction="down")

    def test_already_parsed_items_pass_through(self) -> None:
        effect = ExpectedEffect(metric="ctr", direction="up")
        assert parse_expected([effect]) == (effect,)

    @pytest.mark.parametrize(
        ("raw", "fragment"),
        [
            ("cpa", "array"),
            ({"metric": "cpa"}, "array"),
            (["cpa"], "object"),
            ([{"direction": "down"}], "metric"),
            ([{"metric": "cpa"}], "direction"),
            ([{"metric": "cpa_7d", "direction": "down"}], "cpa_7d"),
            ([{"metric": "cpa", "direction": "lower"}], "lower"),
            ([{"metric": "cpa", "direction": "down", "why": "x"}], "why"),
            ([{"metric": "cpa", "direction": "down", "target": "5000"}], "target"),
            ([{"metric": "cpa", "direction": "down", "target": True}], "target"),
            ([{"metric": "cpa", "direction": "down", "horizon_days": 0}], "horizon"),
            ([{"metric": "cpa", "direction": "down", "horizon_days": 1.5}], "horizon"),
        ],
    )
    def test_refusals_name_the_problem(self, raw: Any, fragment: str) -> None:
        with pytest.raises(ValueError, match=fragment):
            parse_expected(raw)

    def test_a_non_finite_target_is_refused(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            parse_expected([{"metric": "cpa", "direction": "down", "target": math.inf}])

    def test_the_horizon_has_a_ceiling(self) -> None:
        with pytest.raises(ValueError, match="horizon_days"):
            parse_expected(
                [
                    {
                        "metric": "cpa",
                        "direction": "down",
                        "horizon_days": EXPECTED_HORIZON_MAX_DAYS + 1,
                    }
                ]
            )

    def test_a_metric_may_be_declared_once(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            parse_expected(
                [
                    {"metric": "cpa", "direction": "down"},
                    {"metric": "cpa", "direction": "hold"},
                ]
            )

    def test_an_empty_list_is_empty(self) -> None:
        assert parse_expected([]) == ()

    def test_the_item_count_is_bounded(self) -> None:
        assert len(EXPECTED_METRICS) == EXPECTED_MAX_ITEMS


class TestExpectedToList:
    def test_optional_keys_are_omitted_when_unset(self) -> None:
        effects = parse_expected(
            [
                {"metric": "cpa", "direction": "down"},
                {"metric": "cost", "direction": "up", "target": 12000},
            ],
            require_primary=False,
        )
        assert expected_to_list(effects) == [
            {"metric": "cpa", "direction": "down"},
            {"metric": "cost", "direction": "up", "target": 12000},
        ]

    def test_round_trip(self) -> None:
        raw = [{"metric": "roas", "direction": "up", "target": 3, "horizon_days": 7}]
        assert expected_to_list(parse_expected(raw)) == raw

    def test_primary_is_written_only_when_set(self) -> None:
        raw = [
            {"metric": "cpa", "direction": "down", "primary": True},
            {"metric": "ctr", "direction": "up"},
        ]
        assert expected_to_list(parse_expected(raw)) == raw


class TestPrimary:
    """Several declared effects need exactly one ``primary: true`` (#888)."""

    def test_a_single_effect_is_primary_by_itself(self) -> None:
        parsed = parse_expected([{"metric": "cpa", "direction": "down"}])
        assert parsed[0].primary is False

    def test_a_single_effect_may_say_so(self) -> None:
        parsed = parse_expected(
            [{"metric": "cpa", "direction": "down", "primary": True}]
        )
        assert parsed[0].primary is True

    def test_several_with_one_primary(self) -> None:
        parsed = parse_expected(
            [
                {"metric": "cpa", "direction": "down"},
                {"metric": "ctr", "direction": "up", "primary": True},
            ]
        )
        assert [e.primary for e in parsed] == [False, True]

    def test_several_without_a_primary_are_refused(self) -> None:
        with pytest.raises(ValueError, match="expected_primary_required") as info:
            parse_expected(
                [
                    {"metric": "cpa", "direction": "down"},
                    {"metric": "ctr", "direction": "up"},
                ]
            )
        # The message says how to fix it.
        assert '"primary": true' in str(info.value)

    def test_two_primaries_are_refused(self) -> None:
        with pytest.raises(ValueError, match="expected_primary_required"):
            parse_expected(
                [
                    {"metric": "cpa", "direction": "down", "primary": True},
                    {"metric": "ctr", "direction": "up", "primary": True},
                ]
            )

    @pytest.mark.parametrize("value", ["true", 1, None])
    def test_primary_must_be_a_bool(self, value: Any) -> None:
        with pytest.raises(ValueError, match="primary"):
            parse_expected([{"metric": "cpa", "direction": "down", "primary": value}])

    def test_a_stored_declaration_is_read_without_the_rule(self) -> None:
        legacy = [
            {"metric": "cpa", "direction": "down"},
            {"metric": "ctr", "direction": "up"},
        ]
        parsed = parse_expected(legacy, require_primary=False)
        assert [e.metric for e in parsed] == ["cpa", "ctr"]

    def test_a_stored_decision_with_a_legacy_declaration_is_read(self) -> None:
        from mureo.context._decision_codec import parse_decisions

        records = parse_decisions(
            [
                {
                    "decision_id": "dec-1",
                    "recorded_at": "2026-09-01T10:00:00+09:00",
                    "status": "adopted",
                    "title": "t",
                    "rationale": "r",
                    "expected": [
                        {"metric": "cpa", "direction": "down"},
                        {"metric": "ctr", "direction": "up"},
                    ],
                }
            ],
            strict=True,
        )
        assert len(records[0].expected) == 2

    def test_a_stored_decision_naming_cost_and_spend_still_reads(self) -> None:
        # Written before cost became an alias of spend: the stored read keeps
        # the raw-name duplicate rule, so the record is not lost.
        from mureo.context._decision_codec import parse_decisions

        records = parse_decisions(
            [
                {
                    "decision_id": "dec-1",
                    "recorded_at": "2026-09-01T10:00:00+09:00",
                    "status": "adopted",
                    "title": "t",
                    "rationale": "r",
                    "expected": [
                        {"metric": "cost", "direction": "down"},
                        {"metric": "spend", "direction": "down"},
                    ],
                }
            ],
            strict=True,
        )
        assert [e.metric for e in records[0].expected] == ["cost", "spend"]

    def test_a_stored_read_still_refuses_the_same_name_twice(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            parse_expected(
                [
                    {"metric": "cpa", "direction": "down"},
                    {"metric": "cpa", "direction": "up"},
                ],
                require_primary=False,
            )

    def test_cost_and_spend_are_one_metric(self) -> None:
        with pytest.raises(ValueError, match="more than once"):
            parse_expected(
                [
                    {"metric": "cost", "direction": "up", "primary": True},
                    {"metric": "spend", "direction": "up"},
                ]
            )
