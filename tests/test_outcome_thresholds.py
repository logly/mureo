"""Outcome thresholds from STRATEGY.md ``## Guardrails`` (#888).

The MCP layer reads the section and passes an ``OutcomeThresholds`` down to
the pure evaluator, so neither ``mureo.analysis`` nor ``mureo.context``
gains an edge onto the guardrail parser. Same fail-open promise as the
delivery-collapse thresholds: a broken file falls back to the defaults.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from mureo.analysis.outcome_eval import DEFAULT_THRESHOLDS, OutcomeThresholds
from mureo.mcp._outcome_thresholds import (
    GUARDRAIL_KEYS,
    load_outcome_thresholds,
    outcome_thresholds_from_guardrails,
)

pytestmark = pytest.mark.unit

GUARDRAILS = (
    "# Strategy\n\n"
    "## Guardrails\n"
    "- max_daily_budget_per_campaign: 50000\n"
    "- outcome_noise_pct: 5\n"
    "- outcome_min_conversions: 3\n"
    "- outcome_min_impressions: 500\n"
    "- outcome_min_clicks: 50\n"
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the runtime context's state store at ``tmp_path``."""
    monkeypatch.chdir(tmp_path)
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield tmp_path
    reset_runtime_context()


def _strategy(root: Path, text: str) -> None:
    (root / "STRATEGY.md").write_text(text, encoding="utf-8")


class TestGuardrailThresholds:
    def test_the_keys(self) -> None:
        assert set(GUARDRAIL_KEYS) == {
            "outcome_noise_pct",
            "outcome_min_conversions",
            "outcome_min_impressions",
            "outcome_min_clicks",
        }

    def test_no_bullets_is_the_defaults(self) -> None:
        assert outcome_thresholds_from_guardrails({}) == DEFAULT_THRESHOLDS

    def test_overrides_are_applied(self) -> None:
        thresholds = outcome_thresholds_from_guardrails(
            {
                "outcome_noise_pct": "5",
                "outcome_min_conversions": "10",
                "outcome_min_impressions": "2,000",
                "outcome_min_clicks": "50",
                "max_total_daily_budget": "90000",
            }
        )
        assert thresholds == OutcomeThresholds(
            noise_pct=5.0, min_conversions=10, min_impressions=2000, min_clicks=50
        )

    @pytest.mark.parametrize(
        ("key", "raw"),
        [
            ("outcome_noise_pct", "lots"),
            ("outcome_noise_pct", "0"),
            ("outcome_noise_pct", "120"),
            ("outcome_min_conversions", "0"),
            ("outcome_min_conversions", "-3"),
            ("outcome_min_impressions", "1.5"),
            ("outcome_min_clicks", "many"),
        ],
    )
    def test_a_bad_value_keeps_the_default_and_warns(
        self, key: str, raw: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        neighbour = (
            "outcome_min_conversions"
            if key == "outcome_min_clicks"
            else "outcome_min_clicks"
        )
        with caplog.at_level(logging.WARNING, logger="mureo.mcp._outcome_thresholds"):
            thresholds = outcome_thresholds_from_guardrails({key: raw, neighbour: "77"})
        field = GUARDRAIL_KEYS[key]
        assert getattr(thresholds, field) == getattr(DEFAULT_THRESHOLDS, field)
        # The good bullet next to it still applies.
        assert getattr(thresholds, GUARDRAIL_KEYS[neighbour]) == 77
        assert key in caplog.text


class TestLoad:
    def test_absent_strategy_is_the_defaults(self, workspace: Path) -> None:
        assert load_outcome_thresholds() == DEFAULT_THRESHOLDS

    def test_no_guardrails_section_is_the_defaults(self, workspace: Path) -> None:
        _strategy(workspace, "# Strategy\n\n## Persona\nBuyers.\n")
        assert load_outcome_thresholds() == DEFAULT_THRESHOLDS

    def test_the_overrides_are_applied(self, workspace: Path) -> None:
        _strategy(workspace, GUARDRAILS)
        assert load_outcome_thresholds() == OutcomeThresholds(
            noise_pct=5.0, min_conversions=3, min_impressions=500, min_clicks=50
        )

    def test_a_bad_value_is_the_default_with_a_warning(
        self, workspace: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _strategy(
            workspace,
            "## Guardrails\n- outcome_min_conversions: zero\n- outcome_min_clicks: 9\n",
        )
        with caplog.at_level(logging.WARNING):
            thresholds = load_outcome_thresholds()
        assert thresholds.min_conversions == DEFAULT_THRESHOLDS.min_conversions
        assert thresholds.min_clicks == 9
        assert "outcome_min_conversions" in caplog.text

    def test_an_unreadable_strategy_is_the_defaults(self, workspace: Path) -> None:
        (workspace / "STRATEGY.md").mkdir()
        assert load_outcome_thresholds() == DEFAULT_THRESHOLDS

    def test_the_noise_override_wins_over_the_guardrails(self, workspace: Path) -> None:
        _strategy(workspace, GUARDRAILS)
        thresholds = load_outcome_thresholds(noise_pct=20)
        assert thresholds.noise_pct == 20.0
        assert thresholds.min_conversions == 3

    @pytest.mark.parametrize("value", ["ten", [10], 0, 150])
    def test_a_bad_noise_override_is_refused(
        self, workspace: Path, value: object
    ) -> None:
        with pytest.raises(ValueError, match="noise_pct"):
            load_outcome_thresholds(noise_pct=value)


class TestTheTools:
    def test_the_noise_pct_description_states_its_range(self) -> None:
        from mureo.mcp.tools_mureo_context import TOOLS

        tool = next(t for t in TOOLS if t.name == "mureo_outcome_evaluate")
        noise = tool.inputSchema["properties"]["noise_pct"]["description"]
        assert "(0, 100]" in noise

    async def test_outcome_evaluate_reads_the_guardrails(self, workspace: Path) -> None:
        from mureo.mcp.tools_mureo_context import handle_tool

        _strategy(workspace, GUARDRAILS)
        result = await handle_tool(
            "mureo_outcome_evaluate",
            {
                "before": {"cpa": 5000, "conversions": 3},
                "after": {"cpa": 4000, "conversions": 4},
            },
        )
        assert json.loads(result[0].text)["overall"] == "improved"

    async def test_outcome_evaluate_noise_pct_still_overrides(
        self, workspace: Path
    ) -> None:
        from mureo.mcp.tools_mureo_context import handle_tool

        _strategy(workspace, GUARDRAILS)
        result = await handle_tool(
            "mureo_outcome_evaluate",
            {
                "before": {"cpa": 5000, "conversions": 40},
                "after": {"cpa": 4500, "conversions": 40},
                "noise_pct": 20,
            },
        )
        payload = json.loads(result[0].text)
        assert payload["overall"] == "inconclusive"
        assert payload["reason"] == "no_change"

    async def test_the_automatic_closure_reads_the_guardrails(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import datetime, timezone

        import mureo.core.clock as clock
        from mureo.mcp.tools_mureo_context import handle_tool

        monkeypatch.setattr(
            clock,
            "server_now",
            lambda: datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc),
        )
        _strategy(workspace, GUARDRAILS)
        state = {
            "version": "2",
            "platforms": {
                "google_ads": {
                    "account_id": "acct-1",
                    "campaigns": [
                        {
                            "campaign_id": "camp_1",
                            "campaign_name": "Brand",
                            "status": "ENABLED",
                            "metrics": {
                                "cpa": 5000,
                                "conversions": 10,
                                "fetched_at": "2026-07-27",
                            },
                        }
                    ],
                }
            },
            "action_log": [
                {
                    "timestamp": "2026-07-10T10:00:00+09:00",
                    "action": "google_ads_budget_update",
                    "platform": "google_ads",
                    "campaign_id": "camp_1",
                    "metrics_at_action": {"cpa": 10000, "conversions": 5},
                    "observation_due": "2026-07-20",
                }
            ],
        }
        (workspace / "STATE.json").write_text(json.dumps(state), encoding="utf-8")
        result = await handle_tool("mureo_state_get", {})
        payload = json.loads(result[0].text)
        # 5 and 10 conversions are under the default floor of 30, over the
        # workspace's own floor of 3.
        assert payload["auto_evaluations"][0]["overall"] == "improved"
