"""Guarantee tests for the delivery-surface exclusion tools (#544).

The point of #544 is not the tools themselves — it is that excluding a
placement / mobile app / app category becomes an operation mureo can
**guard** (``StrategyPolicyGate``), **record** (``action_log`` with an
``observation_due`` window) and **reverse** (the rollback allow-list).
Adding tools that do not carry those three properties would not resolve
the issue, so they are pinned here rather than left implicit.

Covers both exclusion surfaces mureo owns the schema for:

- Google Ads campaign / ad-group negative placement criteria
  (``google_ads_negative_placements_*``).
- Meta Ads ad-set publisher exclusions
  (``meta_ads_excluded_placements_*``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from mcp.types import TextContent

from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp import native_reversal as nr
from mureo.policy.strategy_gate import Guardrails, evaluate_guardrails
from mureo.rollback.executor import execute_rollback
from mureo.rollback.models import RollbackStatus
from mureo.rollback.planner import plan_rollback

GOOGLE_ADD = "google_ads_negative_placements_add"
GOOGLE_REMOVE = "google_ads_negative_placements_remove"
GOOGLE_LIST = "google_ads_negative_placements_list"
META_SET = "meta_ads_excluded_placements_set"
META_GET = "meta_ads_excluded_placements_get"


def _seed_state(directory: Path) -> None:
    write_state_file(directory / "STATE.json", StateDocument())


def _google_add_result(
    *,
    level: str = "campaign",
    scope_id: str = "100",
    criterion_ids: tuple[str, ...] = ("555", "556"),
) -> list[TextContent]:
    """The exact envelope ``google_ads_negative_placements_add`` returns."""
    key = "campaign_id" if level == "campaign" else "ad_group_id"
    payload: dict[str, Any] = {
        "level": level,
        key: scope_id,
        "count": len(criterion_ids),
        "created": [
            {
                "criterion_id": cid,
                "resource_name": f"customers/1234567890/campaignCriteria/{scope_id}~{cid}",
                "type": "website",
                "value": f"example{i}.com",
            }
            for i, cid in enumerate(criterion_ids)
        ],
    }
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


# ---------------------------------------------------------------------------
# The tools exist and are routable
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolsAreRegistered:
    def test_google_exclusion_tools_are_defined_and_handled(self) -> None:
        from mureo.mcp._handlers_google_ads import HANDLERS
        from mureo.mcp.tools_google_ads import TOOLS

        names = {t.name for t in TOOLS}
        for tool in (GOOGLE_LIST, GOOGLE_ADD, GOOGLE_REMOVE):
            assert tool in names, f"{tool} is not a registered Google Ads tool"
            assert tool in HANDLERS, f"{tool} has no dispatch handler"

    def test_meta_exclusion_tools_are_defined_and_handled(self) -> None:
        from mureo.mcp.tools_meta_ads import _HANDLERS, TOOLS

        names = {t.name for t in TOOLS}
        for tool in (META_GET, META_SET):
            assert tool in names, f"{tool} is not a registered Meta Ads tool"
            assert tool in _HANDLERS, f"{tool} has no dispatch handler"


# ---------------------------------------------------------------------------
# 1. Guardrails — StrategyPolicyGate sees the call
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStrategyPolicyGate:
    @pytest.mark.parametrize("tool", [GOOGLE_ADD, GOOGLE_REMOVE, META_SET])
    def test_blocked_operations_denies_the_exclusion_write(self, tool: str) -> None:
        decision = evaluate_guardrails(
            tool,
            {"campaign_id": "100", "ad_set_id": "s1"},
            Guardrails(blocked_operations=frozenset({tool})),
        )
        assert decision.allowed is False
        assert tool in (decision.reason or "")

    @pytest.mark.asyncio
    async def test_dispatcher_refuses_a_blocked_exclusion_before_the_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import mureo.policy.strategy_gate as sg
        from mureo.mcp.server import handle_call_tool

        sg._cache.clear()
        monkeypatch.setattr(
            sg,
            "_load_guardrails",
            lambda: Guardrails(blocked_operations=frozenset({GOOGLE_ADD})),
        )
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        called: list[str] = []

        async def _boom(name: str, arguments: dict[str, Any]) -> list[Any]:
            called.append(name)
            return []

        monkeypatch.setattr("mureo.mcp.server.handle_google_ads_tool", _boom)

        result = await handle_call_tool(
            GOOGLE_ADD,
            {
                "campaign_id": "100",
                "placements": [{"type": "website", "value": "example.com"}],
            },
        )
        assert called == []
        text = result[0].text
        assert GOOGLE_ADD in text
        assert "refused" in text.lower() or "denied" in text.lower()

    def test_exclusion_tools_are_valid_blocked_operations_names(self) -> None:
        """A guardrail can only block a tool the dispatcher actually routes."""
        from mureo.mcp.tools_google_ads import TOOLS as GOOGLE_TOOLS
        from mureo.mcp.tools_meta_ads import TOOLS as META_TOOLS

        registry = {t.name for t in GOOGLE_TOOLS} | {t.name for t in META_TOOLS}
        assert {GOOGLE_ADD, GOOGLE_REMOVE, META_SET} <= registry


# ---------------------------------------------------------------------------
# 2. action_log + observation_due
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestActionLogPromotion:
    def test_google_add_is_recorded_with_an_observation_window(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        args = {
            "campaign_id": "100",
            "placements": [
                {"type": "website", "value": "example0.com"},
                {"type": "website", "value": "example1.com"},
            ],
        }
        nr.record_native_mutation(GOOGLE_ADD, args, None, _google_add_result())

        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        entry = doc.action_log[0]
        assert entry.action == GOOGLE_ADD
        assert entry.platform == "google_ads"
        assert entry.campaign_id == "100"
        # The single highest-value outcome named in the issue: "N exclusions
        # added on date X, review by date Y".
        assert entry.observation_due is not None
        assert entry.reversible_params == {
            "operation": GOOGLE_REMOVE,
            "params": {"campaign_id": "100", "criterion_ids": ["555", "556"]},
        }

    def test_google_ad_group_level_add_reverses_at_the_ad_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(
            GOOGLE_ADD,
            {"ad_group_id": "200", "placements": []},
            None,
            _google_add_result(level="ad_group", scope_id="200", criterion_ids=("7",)),
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.reversible_params == {
            "operation": GOOGLE_REMOVE,
            "params": {"ad_group_id": "200", "criterion_ids": ["7"]},
        }

    def test_whole_batch_is_one_log_entry_and_one_reversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#549 alignment: one add call = one revertible unit, however many
        exclusions it created."""
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        ids = tuple(str(n) for n in range(1, 37))  # the incident's 36 apps
        nr.record_native_mutation(
            GOOGLE_ADD,
            {"campaign_id": "100"},
            None,
            _google_add_result(criterion_ids=ids),
        )
        doc = read_state_file(tmp_path / "STATE.json")
        assert len(doc.action_log) == 1
        params = doc.action_log[0].reversible_params["params"]
        assert params["criterion_ids"] == list(ids)

    def test_failed_add_is_not_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(
            GOOGLE_ADD,
            {"campaign_id": "100"},
            None,
            [TextContent(type="text", text="API error: boom")],
        )
        assert read_state_file(tmp_path / "STATE.json").action_log == ()

    def test_meta_set_is_recorded_with_prior_exclusions_as_the_reversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        prior = {
            "excluded_publisher_categories": ["dating"],
            "excluded_publisher_list_ids": [],
            "excluded_brand_safety_content_types": [],
        }
        nr.record_native_mutation(
            META_SET,
            {
                "ad_set_id": "s1",
                "excluded_publisher_categories": ["dating", "gambling"],
            },
            prior,
            [TextContent(type="text", text=json.dumps({"ad_set_id": "s1"}))],
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        assert entry.platform == "meta_ads"
        assert entry.observation_due is not None
        assert entry.reversible_params == {
            "operation": META_SET,
            "params": {
                "ad_set_id": "s1",
                "excluded_publisher_categories": ["dating"],
            },
        }

    def test_meta_set_reversal_clears_a_previously_unset_facet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(
            META_SET,
            {"ad_set_id": "s1", "excluded_publisher_list_ids": ["9001"]},
            {"excluded_publisher_categories": ["dating"]},
            [TextContent(type="text", text="{}")],
        )
        entry = read_state_file(tmp_path / "STATE.json").action_log[0]
        # The facet did not exist before ⇒ reversing it means clearing it,
        # NOT leaving the newly-added block list in place.
        assert entry.reversible_params["params"] == {
            "ad_set_id": "s1",
            "excluded_publisher_list_ids": [],
        }

    def test_reads_are_never_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        nr.record_native_mutation(GOOGLE_LIST, {"campaign_id": "100"}, None, None)
        nr.record_native_mutation(META_GET, {"ad_set_id": "s1"}, None, None)
        assert read_state_file(tmp_path / "STATE.json").action_log == ()


# ---------------------------------------------------------------------------
# 3. Before-state capture (Meta needs a read; Google does not)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBeforeStateCapture:
    @pytest.mark.asyncio
    async def test_meta_capture_reads_current_exclusions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock

        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)
        client = AsyncMock()
        client.get_excluded_placements = AsyncMock(
            return_value={
                "ad_set_id": "s1",
                "excluded_publisher_categories": ["dating"],
                "excluded_publisher_list_ids": [],
                "excluded_brand_safety_content_types": [],
            }
        )
        monkeypatch.setattr(
            "mureo.mcp._handlers_meta_ads._get_client", AsyncMock(return_value=client)
        )
        prior = await nr.capture_before_state(META_SET, {"ad_set_id": "s1"})
        assert prior is not None
        assert prior["excluded_publisher_categories"] == ["dating"]

    @pytest.mark.asyncio
    async def test_google_add_needs_no_before_state_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reversal comes from the criterion ids the add RETURNS, so no
        pre-mutation network read is issued."""
        _seed_state(tmp_path)
        monkeypatch.chdir(tmp_path)

        def _explode(_args: dict[str, Any]) -> Any:
            raise AssertionError("no before-state read expected for the add")

        monkeypatch.setattr("mureo.mcp._handlers_google_ads._get_client", _explode)
        assert await nr.capture_before_state(GOOGLE_ADD, {"campaign_id": "1"}) is None


# ---------------------------------------------------------------------------
# 4. Reversibility — the rollback allow-list
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRollbackPlanning:
    def test_added_exclusions_plan_back_to_a_removal(self) -> None:
        entry = ActionLogEntry(
            timestamp="2026-08-07T10:00:00+09:00",
            action=GOOGLE_ADD,
            platform="google_ads",
            campaign_id="100",
            summary="excluded 36 mobile apps",
            reversible_params={
                "operation": GOOGLE_REMOVE,
                "params": {"campaign_id": "100", "criterion_ids": ["555", "556"]},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.SUPPORTED, plan.notes
        assert plan.operation == GOOGLE_REMOVE
        assert plan.params == {"campaign_id": "100", "criterion_ids": ["555", "556"]}

    def test_meta_exclusion_set_plans_back_to_the_prior_lists(self) -> None:
        entry = ActionLogEntry(
            timestamp="2026-08-07T10:00:00+09:00",
            action=META_SET,
            platform="meta_ads",
            summary="excluded publisher categories",
            reversible_params={
                "operation": META_SET,
                "params": {
                    "ad_set_id": "s1",
                    "excluded_publisher_categories": ["dating"],
                },
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.SUPPORTED, plan.notes
        assert plan.operation == META_SET

    def test_unexpected_params_are_still_rejected(self) -> None:
        entry = ActionLogEntry(
            timestamp="2026-08-07T10:00:00+09:00",
            action=GOOGLE_ADD,
            platform="google_ads",
            summary="x",
            reversible_params={
                "operation": GOOGLE_REMOVE,
                "params": {"campaign_id": "100", "customer_id": "999"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.NOT_SUPPORTED
        assert "customer_id" in plan.notes

    def test_other_removals_stay_blocked_by_the_destructive_verb_net(self) -> None:
        """The exemption is per-operation, not a general amnesty for removals."""
        entry = ActionLogEntry(
            timestamp="2026-08-07T10:00:00+09:00",
            action="google_ads_keywords_add",
            platform="google_ads",
            summary="x",
            reversible_params={
                "operation": "google_ads_keywords_remove",
                "params": {"ad_group_id": "1", "criterion_id": "2"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status is RollbackStatus.NOT_SUPPORTED
        assert "destructive" in plan.notes.lower()

    def test_destructive_verb_exemption_is_a_subset_of_the_allow_list(self) -> None:
        """An exempt operation that is not also allow-listed would be a hole."""
        from mureo.rollback.planner import (
            _ALLOWED_OPERATIONS,
            _DESTRUCTIVE_VERB_EXEMPT,
        )

        assert set(_ALLOWED_OPERATIONS) >= _DESTRUCTIVE_VERB_EXEMPT


@pytest.mark.unit
class TestRollbackExecution:
    @pytest.mark.asyncio
    async def test_rollback_dispatches_the_removal_of_exactly_what_was_added(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "STATE.json"
        entry = ActionLogEntry(
            timestamp="2026-08-07T10:00:00+09:00",
            action=GOOGLE_ADD,
            platform="google_ads",
            campaign_id="100",
            summary="excluded 2 websites",
            reversible_params={
                "operation": GOOGLE_REMOVE,
                "params": {"campaign_id": "100", "criterion_ids": ["555", "556"]},
            },
        )
        write_state_file(state_file, StateDocument(version="2", action_log=(entry,)))

        calls: list[tuple[str, dict[str, Any]]] = []

        async def _dispatcher(name: str, arguments: dict[str, Any]) -> list[Any]:
            calls.append((name, dict(arguments)))
            return [TextContent(type="text", text='{"removed_count": 2}')]

        result = await execute_rollback(
            state_file=state_file, index=0, confirm=True, dispatcher=_dispatcher
        )
        assert result["status"] == "applied"
        assert calls == [
            (GOOGLE_REMOVE, {"campaign_id": "100", "criterion_ids": ["555", "556"]})
        ]
        doc = read_state_file(state_file)
        assert doc.action_log[1].rollback_of == 0
