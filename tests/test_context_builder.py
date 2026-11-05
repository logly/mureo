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
    PlatformState,
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


def _store(state: StateDocument) -> MagicMock:
    store = MagicMock()
    store.read_state.return_value = state
    store.read_strategy.return_value = []
    return store


def _v2_state(
    platforms: dict[str, tuple[CampaignSnapshot, ...]],
    action_log: tuple[ActionLogEntry, ...] = (),
) -> StateDocument:
    return StateDocument(
        platforms={
            key: PlatformState(account_id="1", campaigns=campaigns)
            for key, campaigns in platforms.items()
        },
        action_log=action_log,
    )


@pytest.mark.unit
class TestBuildQueryPlatforms:
    """v2 STATE.json keeps campaigns under ``platforms.<key>.campaigns``."""

    def test_v2_state_finds_the_campaign_and_names_its_platform(self) -> None:
        snap = CampaignSnapshot(
            campaign_id="c1", campaign_name="Leads", status="ACTIVE", daily_budget=900
        )
        store = _store(_v2_state({"meta_ads": (snap,)}))

        out = build_query(state_store=store, question="CPA up?", campaign_id="c1")

        assert out.splitlines() == [
            "Question: CPA up?",
            "Platform: meta_ads",
            "Campaign: Leads [ACTIVE] (daily_budget=900)",
        ]

    def test_platform_argument_alone_emits_the_line(self) -> None:
        store = _store(StateDocument())

        out = build_query(state_store=store, question="?", platform="google_ads")

        assert out.splitlines() == ["Question: ?", "Platform: google_ads"]

    def test_campaign_type_line_only_when_set(self) -> None:
        typed = CampaignSnapshot(
            campaign_id="c1",
            campaign_name="Brand",
            status="ENABLED",
            campaign_type="SEARCH",
        )
        untyped = CampaignSnapshot(
            campaign_id="c2", campaign_name="Display", status="ENABLED"
        )
        store = _store(_v2_state({"google_ads": (typed, untyped)}))

        with_type = build_query(state_store=store, question="?", campaign_id="c1")
        without_type = build_query(state_store=store, question="?", campaign_id="c2")

        assert "Campaign type: SEARCH" in with_type.splitlines()
        assert "Campaign type" not in without_type

    def test_platform_filter_excludes_a_same_id_under_another_platform(
        self,
    ) -> None:
        google = CampaignSnapshot(campaign_id="42", campaign_name="G", status="X")
        meta = CampaignSnapshot(
            campaign_id="42",
            campaign_name="M",
            status="Y",
            campaign_type="OUTCOME_LEADS",
        )
        log = (
            ActionLogEntry(
                timestamp="t1",
                action="google_change",
                platform="google_ads",
                campaign_id="42",
            ),
            ActionLogEntry(
                timestamp="t2",
                action="meta_change",
                platform="meta_ads",
                campaign_id="42",
            ),
            ActionLogEntry(
                timestamp="t3",
                action="unplaced_change",
                platform="",
                campaign_id="42",
            ),
        )
        store = _store(
            _v2_state({"google_ads": (google,), "meta_ads": (meta,)}, action_log=log)
        )

        out = build_query(
            state_store=store, question="?", campaign_id="42", platform="meta_ads"
        )

        assert "Platform: meta_ads" in out
        assert "Campaign: M [Y]" in out
        assert "Campaign type: OUTCOME_LEADS" in out
        assert "Campaign: G" not in out
        assert "meta_change" in out
        assert "unplaced_change" in out
        assert "google_change" not in out

    def test_without_platform_the_first_match_names_its_platform(self) -> None:
        google = CampaignSnapshot(campaign_id="42", campaign_name="G", status="X")
        store = _store(_v2_state({"google_ads": (google,), "meta_ads": ()}))

        out = build_query(state_store=store, question="?", campaign_id="42")

        assert "Platform: google_ads" in out
        assert "Campaign: G [X]" in out

    def test_v1_campaigns_are_searched_first(self) -> None:
        v1 = CampaignSnapshot(campaign_id="c1", campaign_name="V1", status="A")
        v2 = CampaignSnapshot(campaign_id="c1", campaign_name="V2", status="B")
        state = StateDocument(
            campaigns=(v1,),
            platforms={"google_ads": PlatformState(account_id="1", campaigns=(v2,))},
        )

        out = build_query(state_store=_store(state), question="?", campaign_id="c1")

        assert "Campaign: V1 [A]" in out
        assert "Platform:" not in out

    def test_layout_order(self) -> None:
        snap = CampaignSnapshot(
            campaign_id="c1",
            campaign_name="Brand",
            status="ENABLED",
            campaign_type="SEARCH",
        )
        log = (
            ActionLogEntry(
                timestamp="t1", action="bid", platform="google_ads", campaign_id="c1"
            ),
        )
        store = _store(_v2_state({"google_ads": (snap,)}, action_log=log))
        store.read_strategy.return_value = [
            StrategyEntry(
                context_type="business_category",
                title="Business Category",
                content="ec",
            )
        ]

        out = build_query(state_store=store, question="?", campaign_id="c1")

        assert out.splitlines() == [
            "Question: ?",
            "Platform: google_ads",
            "Campaign: Brand [ENABLED]",
            "Campaign type: SEARCH",
            "Recent actions:",
            "- t1 bid",
            "Strategy:",
            "- Business Category: ec",
        ]
