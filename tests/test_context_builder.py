"""Tests for ``mureo.learning.context_builder``.

The context builder turns ``(question, campaign_id)`` into a single
query string by pulling the relevant slice of mureo's local state —
campaign metrics, recent action log entries, and STRATEGY.md excerpt —
into a compact prefix the advisor's vector search can match against.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mureo.context.models import (
    ActionLogEntry,
    CampaignSnapshot,
    StateDocument,
    StrategyEntry,
)
from mureo.learning.context_builder import build_query


def _state(
    *campaigns: CampaignSnapshot, action_log: tuple[ActionLogEntry, ...] = ()
) -> StateDocument:
    return StateDocument(campaigns=tuple(campaigns), action_log=action_log)


@pytest.mark.unit
class TestBuildQuery:
    def test_question_only_when_no_campaign(self) -> None:
        store = MagicMock()
        store.read_state.return_value = _state()
        store.read_strategy.return_value = []
        out = build_query(state_store=store, question="why is CPA up?")
        assert "why is CPA up?" in out

    def test_includes_campaign_name_and_status(self) -> None:
        store = MagicMock()
        snap = CampaignSnapshot(
            campaign_id="123",
            campaign_name="Brand-Search",
            status="ENABLED",
            daily_budget=5000,
        )
        store.read_state.return_value = _state(snap)
        store.read_strategy.return_value = []
        out = build_query(state_store=store, question="CPA up?", campaign_id="123")
        assert "Brand-Search" in out
        assert "ENABLED" in out
        assert "CPA up?" in out

    def test_includes_recent_action_log_for_campaign(self) -> None:
        store = MagicMock()
        snap = CampaignSnapshot(campaign_id="c1", campaign_name="X", status="ENABLED")
        log = (
            ActionLogEntry(
                timestamp="2026-05-29T00:00:00Z",
                action="budget_update",
                platform="google_ads",
                campaign_id="c1",
                summary="bumped 10k→15k",
            ),
            ActionLogEntry(
                timestamp="2026-05-28T00:00:00Z",
                action="paused_keyword",
                platform="google_ads",
                campaign_id="other",
            ),
        )
        store.read_state.return_value = _state(snap, action_log=log)
        store.read_strategy.return_value = []
        out = build_query(state_store=store, question="why CV down?", campaign_id="c1")
        assert "budget_update" in out
        assert "paused_keyword" not in out  # other campaign filtered out

    def test_includes_strategy_excerpt(self) -> None:
        store = MagicMock()
        store.read_state.return_value = _state()
        store.read_strategy.return_value = [
            StrategyEntry(
                context_type="goal",
                title="Q2 goal",
                content="Target CPA 5000 JPY",
            )
        ]
        out = build_query(state_store=store, question="?")
        assert "Q2 goal" in out
        assert "Target CPA 5000 JPY" in out

    def test_unknown_campaign_id_falls_back_gracefully(self) -> None:
        store = MagicMock()
        store.read_state.return_value = _state()
        store.read_strategy.return_value = []
        # No exception — just the question
        out = build_query(state_store=store, question="?", campaign_id="missing")
        assert "?" in out

    def test_state_read_failure_falls_back_to_question(self) -> None:
        store = MagicMock()
        store.read_state.side_effect = OSError("disk gone")
        store.read_strategy.side_effect = OSError("disk gone")
        out = build_query(state_store=store, question="hello?")
        assert "hello?" in out
