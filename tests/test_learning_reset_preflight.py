"""Tests for the learning-period reset pre-flight check (#548).

Four properties matter more than coverage here, and each has its own class:

- a reset-triggering dispatch SURFACES the current learning state and the
  reset verdict (``TestDispatchSurfacing``);
- a ``## Guardrails`` refusal actually BLOCKS rather than merely reporting
  (``TestGateEnforcement``);
- a change that resets nothing is NOT warned about (``TestChangeClassification``
  / ``TestDispatchSurfacing.test_non_reset_dispatch_appends_no_notice``);
- a platform whose learning state mureo cannot read says so, and never says
  "safe" (``TestLearningStateReading``, ``TestPreflightTool``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from mureo.context.models import CampaignSnapshot, PlatformState, StateDocument
from mureo.context.state import write_state_file
from mureo.core.runtime_context import reset_runtime_context
from mureo.policy.learning_reset import (
    LearningReading,
    build_preflight,
    classify_change,
    learning_reset_denial,
    read_learning_state,
)
from mureo.policy.learning_rules import (
    LearningState,
    ResetRisk,
    platform_learning_rules,
    reset_platform_learning_rules,
)
from mureo.policy.strategy_gate import (
    Guardrails,
    StrategyPolicyGate,
    evaluate_guardrails,
    parse_guardrails,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _state_with(status: str | None, campaign_id: str = "C1") -> StateDocument:
    """A STATE.json document whose Google campaign carries ``status``."""
    details: dict[str, Any] | None = (
        None if status is None else {"bidding_strategy_system_status": status}
    )
    return StateDocument(
        version="2",
        platforms={
            "google_ads": PlatformState(
                account_id="1234567890",
                campaigns=(
                    CampaignSnapshot(
                        campaign_id=campaign_id,
                        campaign_name="Brand Search",
                        status="ENABLED",
                        bidding_details=details,
                    ),
                ),
            )
        },
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated cwd with a fresh runtime context and gate cache."""
    from mureo.policy import strategy_gate

    monkeypatch.chdir(tmp_path)
    reset_runtime_context()
    strategy_gate._cache.clear()
    yield tmp_path
    reset_runtime_context()
    strategy_gate._cache.clear()


def _write_strategy(path: Path, guardrails: str) -> None:
    (path / "STRATEGY.md").write_text(
        f"## Persona\nSMB\n\n## Guardrails\n{guardrails}\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# (b) is the pending change in the reset-triggering class?
# ---------------------------------------------------------------------------


class TestChangeClassification:
    def test_google_budget_update_is_reset_triggering(self) -> None:
        a = classify_change("google_ads_budget_update", {"budget_id": "B", "amount": 1})
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "budget_change"

    def test_google_campaign_update_with_bidding_strategy_is_reset(self) -> None:
        a = classify_change(
            "google_ads_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
        )
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "bidding_strategy_change"

    def test_google_campaign_rename_is_not_a_reset(self) -> None:
        """A rename through the SAME tool must not inherit the bid verdict."""
        a = classify_change(
            "google_ads_campaigns_update", {"campaign_id": "C1", "name": "New name"}
        )
        assert a.risk is ResetRisk.NO_RESET

    def test_google_keyword_add_is_composition_change(self) -> None:
        a = classify_change(
            "google_ads_keywords_add", {"ad_group_id": "A", "keywords": ["x"]}
        )
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "composition_change"

    def test_google_reactivation_is_reset_but_pause_is_not(self) -> None:
        enable = classify_change(
            "google_ads_campaigns_update_status",
            {"campaign_id": "C1", "status": "ENABLED"},
        )
        pause = classify_change(
            "google_ads_campaigns_update_status",
            {"campaign_id": "C1", "status": "PAUSED"},
        )
        assert enable.risk is ResetRisk.RESETS
        assert pause.risk is ResetRisk.NO_RESET

    def test_conversion_rename_is_not_a_reset(self) -> None:
        """Review finding: a cosmetic rename of a conversion action classified
        the same as changing its value, so an operator who declared
        block_learning_resets_during_incident could never rename one."""
        a = classify_change(
            "google_ads_conversions_update",
            {"conversion_action_id": "CA1", "name": "Renamed"},
        )
        assert a.risk is ResetRisk.NO_RESET

    @pytest.mark.parametrize(
        "field,value",
        [
            ("category", "PURCHASE"),
            ("status", "REMOVED"),
            ("default_value", 5000),
            ("always_use_default_value", True),
            ("click_through_lookback_window_days", 30),
            ("view_through_lookback_window_days", 1),
        ],
    )
    def test_conversion_setting_edits_are_resets(self, field: str, value: Any) -> None:
        a = classify_change(
            "google_ads_conversions_update",
            {"conversion_action_id": "CA1", field: value},
        )
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "conversion_settings_change"

    @pytest.mark.parametrize(
        "tool", ["google_ads_conversions_create", "google_ads_conversions_remove"]
    )
    def test_conversion_type_changes_stay_resets(self, tool: str) -> None:
        """create / remove have no cosmetic-only mode, so they stay
        unconditional — narrowing must not become under-reporting."""
        a = classify_change(tool, {"conversion_action_id": "CA1"})
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "conversion_type_change"

    def test_reset_verdict_carries_the_classification_caveats(self) -> None:
        """The caveats must reach the person who is BLOCKED, not only the one
        who is waved through."""
        a = classify_change("google_ads_budget_update", {"amount": 1})
        assert "manual-CPC" in a.detail
        for change_class in ("budget_change", "composition_change", "reactivation"):
            assert change_class in a.detail

    @pytest.mark.parametrize(
        "tool",
        [
            "google_ads_campaigns_list",
            "google_ads_campaigns_get",
            "google_ads_performance_report",
            "google_ads_search_terms_report",
            "meta_ads_insights_report",
            "campaign_management-query_campaign",
        ],
    )
    def test_reads_never_warn(self, tool: str) -> None:
        assert classify_change(tool, {}).risk is ResetRisk.NO_RESET

    def test_meta_mutation_is_unknown_not_safe(self) -> None:
        """Meta has a learning phase but mureo has no first-party trigger
        list for it, so the verdict is UNKNOWN — never NO_RESET."""
        a = classify_change("meta_ads_ad_sets_update", {"ad_set_id": "S1"})
        assert a.risk is ResetRisk.UNKNOWN

    def test_bridged_amazon_mutation_is_unknown(self) -> None:
        a = classify_change("campaign_management-update_campaign_budget", {"body": {}})
        assert a.risk is ResetRisk.UNKNOWN

    def test_every_trigger_cites_first_party_evidence(self) -> None:
        rules = platform_learning_rules("google_ads")
        assert rules is not None
        assert rules.triggers
        for trigger in rules.triggers:
            assert trigger.evidence.source.startswith("https://")
            assert trigger.evidence.retrieved
            assert trigger.evidence.quote


# ---------------------------------------------------------------------------
# (a) what is the campaign's current learning state?
# ---------------------------------------------------------------------------


class TestLearningStateReading:
    def test_google_learning_status_is_read(self) -> None:
        r = read_learning_state(
            "google_ads", "C1", _state_with("LEARNING_SETTING_CHANGE")
        )
        assert r.state is LearningState.LEARNING
        assert "LEARNING_SETTING_CHANGE" in r.detail

    def test_google_enabled_status_is_steady(self) -> None:
        r = read_learning_state("google_ads", "C1", _state_with("ENABLED"))
        assert r.state is LearningState.STEADY

    def test_google_unavailable_is_unreportable(self) -> None:
        """Google's own enum says UNAVAILABLE means the strategy does not
        support status reporting — that is not 'steady'."""
        r = read_learning_state("google_ads", "C1", _state_with("UNAVAILABLE"))
        assert r.state is LearningState.UNREPORTABLE

    def test_no_observation_is_unknown_not_steady(self) -> None:
        r = read_learning_state("google_ads", "C1", _state_with(None))
        assert r.state is LearningState.UNKNOWN

    def test_no_campaign_id_is_unknown(self) -> None:
        r = read_learning_state("google_ads", None, _state_with("ENABLED"))
        assert r.state is LearningState.UNKNOWN

    def test_meta_is_unreportable_by_mureo(self) -> None:
        r = read_learning_state("meta_ads", "C1", StateDocument())
        assert r.state is LearningState.UNREPORTABLE
        assert "learning_stage_info" in r.detail

    def test_unknown_platform_is_unreportable(self) -> None:
        r = read_learning_state("plugin:mureo-x-bridge:x", "C1", StateDocument())
        assert r.state is LearningState.UNREPORTABLE

    def test_reading_never_claims_safe_without_evidence(self) -> None:
        for state in (LearningState.UNKNOWN, LearningState.UNREPORTABLE):
            reading = LearningReading(state=state, detail="d", source="s")
            assert reading.is_known_not_learning() is False


# ---------------------------------------------------------------------------
# (d) the hard refusal in STRATEGY.md ## Guardrails
# ---------------------------------------------------------------------------


class TestGuardrailParsing:
    def test_parses_both_learning_keys(self) -> None:
        g = parse_guardrails(
            "- block_learning_resets: true\n"
            "- block_learning_resets_during_incident: yes\n"
        )
        assert g.block_learning_resets is True
        assert g.block_learning_resets_during_incident is True

    def test_absent_keys_default_false_and_stay_empty(self) -> None:
        g = parse_guardrails("- some_other_rule: 3")
        assert g.block_learning_resets is False
        assert g.block_learning_resets_during_incident is False
        assert g.is_empty()

    def test_learning_key_alone_makes_guardrails_non_empty(self) -> None:
        assert not parse_guardrails("- block_learning_resets: true").is_empty()

    def test_false_value_is_not_enabled(self) -> None:
        g = parse_guardrails("- block_learning_resets: false")
        assert g.block_learning_resets is False


class TestGateEnforcement:
    def _pre(self, tool: str, args: dict[str, Any], status: str | None):
        return build_preflight(tool, args, _state_with(status))

    def test_denial_when_block_learning_resets(self) -> None:
        pre = self._pre(
            "google_ads_budget_update", {"budget_id": "B", "amount": 1}, "ENABLED"
        )
        reason = learning_reset_denial(pre, block_all=True, block_during_incident=False)
        assert reason is not None
        assert "budget_change" in reason

    def test_no_denial_for_non_reset_change(self) -> None:
        pre = self._pre(
            "google_ads_campaigns_update", {"campaign_id": "C1", "name": "x"}, "ENABLED"
        )
        assert (
            learning_reset_denial(pre, block_all=True, block_during_incident=True)
            is None
        )

    def test_incident_guardrail_denies_when_already_learning(self) -> None:
        pre = self._pre(
            "google_ads_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
            "LEARNING_BUDGET_CHANGE",
        )
        reason = learning_reset_denial(pre, block_all=False, block_during_incident=True)
        assert reason is not None
        assert "LEARNING_BUDGET_CHANGE" in reason

    def test_incident_guardrail_needs_a_campaign_subject(self) -> None:
        """'During incident' names a specific unstable campaign. An
        account-level change identifies none, so the rule has no subject and
        must not refuse — otherwise editing a conversion action is refused
        forever, with no relation to any incident."""
        pre = self._pre(
            "google_ads_conversions_update",
            {"conversion_action_id": "CA1", "status": "REMOVED"},
            "LEARNING_NEW",
        )
        assert pre.campaign_id is None
        assert pre.change.risk is ResetRisk.RESETS
        assert (
            learning_reset_denial(pre, block_all=False, block_during_incident=True)
            is None
        )

    def test_block_all_still_refuses_without_a_campaign_subject(self) -> None:
        """The blunt rule stays blunt: a freeze needs no subject."""
        pre = self._pre(
            "google_ads_conversions_update",
            {"conversion_action_id": "CA1", "status": "REMOVED"},
            "LEARNING_NEW",
        )
        assert (
            learning_reset_denial(pre, block_all=True, block_during_incident=False)
            is not None
        )

    def test_incident_guardrail_allows_when_steady(self) -> None:
        pre = self._pre(
            "google_ads_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
            "ENABLED",
        )
        assert (
            learning_reset_denial(pre, block_all=False, block_during_incident=True)
            is None
        )

    def test_incident_guardrail_denies_when_state_unknown(self) -> None:
        """Unverifiable is refused, not treated as steady."""
        pre = self._pre(
            "google_ads_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
            None,
        )
        reason = learning_reset_denial(pre, block_all=False, block_during_incident=True)
        assert reason is not None
        assert "unknown" in reason.lower()

    def test_gate_denies_end_to_end_via_strategy_md(self, workspace: Path) -> None:
        _write_strategy(workspace, "- block_learning_resets: true")
        write_state_file(workspace / "STATE.json", _state_with("ENABLED"))
        decision = StrategyPolicyGate().evaluate(
            "google_ads_budget_update", {"budget_id": "B", "amount": 1000}
        )
        assert decision.allowed is False

    def test_gate_allows_without_the_guardrail(self, workspace: Path) -> None:
        _write_strategy(workspace, "- max_daily_budget_per_campaign: 999999")
        write_state_file(workspace / "STATE.json", _state_with("ENABLED"))
        decision = StrategyPolicyGate().evaluate(
            "google_ads_budget_update", {"budget_id": "B", "amount": 1000}
        )
        assert decision.allowed is True

    def test_evaluate_guardrails_ignores_learning_without_reading(self) -> None:
        """The pure layer stays pure: no learning preflight ⇒ no learning
        denial, even with the guardrail set."""
        g = Guardrails(block_learning_resets=True)
        d = evaluate_guardrails("google_ads_budget_update", {"amount": 1}, g)
        assert d.allowed is True


# ---------------------------------------------------------------------------
# (c) surfaced at dispatch
# ---------------------------------------------------------------------------


class TestDispatchSurfacing:
    async def _dispatch(self, tool: str, args: dict[str, Any]) -> list[Any]:
        """Run the real dispatcher with the platform handler stubbed out.

        The gate and the notice hook are what is under test; the Google
        handler's credential / tenant resolution is not, and stubbing it keeps
        this test independent of what the local machine has configured.
        """
        from mcp.types import TextContent

        from mureo.mcp import server as mod

        stub = AsyncMock(
            return_value=[TextContent(type="text", text=json.dumps({"id": "C1"}))]
        )
        with patch.object(mod, "_dispatch_tool", stub):
            return await mod.handle_call_tool(tool, args)

    async def test_reset_triggering_dispatch_surfaces_state_and_verdict(
        self, workspace: Path
    ) -> None:
        write_state_file(
            workspace / "STATE.json", _state_with("LEARNING_SETTING_CHANGE")
        )
        result = await self._dispatch(
            "google_ads_campaigns_update",
            {
                "customer_id": "1234567890",
                "campaign_id": "C1",
                "bidding_strategy": "TARGET_CPA",
            },
        )
        blob = "\n".join(r.text for r in result)
        assert "bidding_strategy_change" in blob  # the reset verdict
        assert "LEARNING_SETTING_CHANGE" in blob  # the current learning state

    async def test_non_reset_dispatch_appends_no_notice(self, workspace: Path) -> None:
        write_state_file(
            workspace / "STATE.json", _state_with("LEARNING_SETTING_CHANGE")
        )
        result = await self._dispatch(
            "google_ads_campaigns_update",
            {"customer_id": "1234567890", "campaign_id": "C1", "name": "Renamed"},
        )
        blob = "\n".join(r.text for r in result)
        assert "learning" not in blob.lower()

    async def test_guardrail_refusal_reaches_the_agent(self, workspace: Path) -> None:
        _write_strategy(workspace, "- block_learning_resets: true")
        write_state_file(workspace / "STATE.json", _state_with("ENABLED"))
        result = await self._dispatch(
            "google_ads_campaigns_update",
            {
                "customer_id": "1234567890",
                "campaign_id": "C1",
                "bidding_strategy": "TARGET_CPA",
            },
        )
        blob = "\n".join(r.text for r in result)
        assert "refused by policy gate" in blob
        assert "bidding_strategy_change" in blob


# ---------------------------------------------------------------------------
# The pre-flight MCP tool
# ---------------------------------------------------------------------------


class TestPreflightTool:
    async def _run(self, args: dict[str, Any]) -> dict[str, Any]:
        from mureo.mcp import server as mod

        result = await mod.handle_call_tool("mureo_learning_reset_preflight", args)
        return json.loads(result[0].text)

    async def test_tool_is_registered(self) -> None:
        from mureo.mcp import server as mod

        names = {t.name for t in await mod.handle_list_tools()}
        assert "mureo_learning_reset_preflight" in names

    async def test_reports_state_and_verdict(self, workspace: Path) -> None:
        write_state_file(workspace / "STATE.json", _state_with("LEARNING_NEW"))
        out = await self._run(
            {
                "tool_name": "google_ads_budget_update",
                "arguments": {"budget_id": "B", "amount": 1},
                "campaign_id": "C1",
            }
        )
        assert out["reset_risk"] == "resets"
        assert out["change_class"] == "budget_change"
        assert out["learning_state"]["state"] == "learning"
        assert out["would_block"] is False

    async def test_unreadable_platform_says_unknown_not_safe(
        self, workspace: Path
    ) -> None:
        out = await self._run(
            {
                "tool_name": "campaign_management-update_campaign_budget",
                "arguments": {"body": {}},
            }
        )
        assert out["reset_risk"] == "unknown"
        assert out["learning_state"]["state"] == "unreportable"
        # It must NOT claim the change is safe.
        assert out["reset_risk"] != "no_reset"

    async def test_would_block_agrees_with_the_gate(self, workspace: Path) -> None:
        _write_strategy(workspace, "- block_learning_resets: true")
        write_state_file(workspace / "STATE.json", _state_with("ENABLED"))
        args = {"budget_id": "B", "amount": 1}
        out = await self._run(
            {
                "tool_name": "google_ads_budget_update",
                "arguments": args,
                "campaign_id": "C1",
            }
        )
        gate = StrategyPolicyGate().evaluate("google_ads_budget_update", args)
        assert out["would_block"] is True
        assert gate.allowed is False


# ---------------------------------------------------------------------------
# Plugin / bridge registration hook
# ---------------------------------------------------------------------------


class TestDeclaredReadOnlyHintBeatsTheName:
    """For a plugin tool the NAME is a guess; ``readOnlyHint`` is a declaration.

    A plugin or bridge can register its own learning rules under a
    ``tool_prefix``, so plugin tool names really do reach this classifier. With
    only the name to go on it was wrong in both directions: a read-shaped name
    that declares ``readOnlyHint=False`` got no learning-period notice and no
    ``block_learning_resets`` refusal, and a mutation-shaped name that declares
    ``readOnlyHint=True`` risked a spurious refusal. The declaration decides;
    the name is the fallback for a tool that declared nothing.
    """

    @pytest.fixture(autouse=True)
    def _clean_hints(self) -> Iterator[None]:
        """Isolate the process-global hint registry WITHOUT destroying it.

        ``mureo.mcp.server`` populates it once at import from real plugin
        discovery; a destructive clear would drop those registrations for the
        rest of the pytest session.
        """
        from mureo.policy.declarations import _READ_ONLY_HINTS, reset_read_only_hints

        saved = dict(_READ_ONLY_HINTS)
        reset_read_only_hints()
        yield
        reset_read_only_hints()
        _READ_ONLY_HINTS.update(saved)

    def test_a_declared_mutation_on_a_read_shaped_name_is_a_mutation(self) -> None:
        from mureo.policy.declarations import register_read_only_hint

        tool = "acme-list_and_delete_campaigns"
        register_read_only_hint(tool, False)
        assessment = classify_change(tool, {})
        assert assessment.risk is not ResetRisk.NO_RESET
        assert "Read-only" not in assessment.detail

    def test_a_declared_read_on_a_mutation_shaped_name_is_a_read(self) -> None:
        from mureo.policy.declarations import register_read_only_hint

        tool = "acme-update_report_layout"
        register_read_only_hint(tool, True)
        assessment = classify_change(tool, {})
        assert assessment.risk is ResetRisk.NO_RESET
        assert "Read-only" in assessment.detail

    @pytest.mark.parametrize(
        ("tool", "expected"),
        [
            ("acme-list_campaigns", ResetRisk.NO_RESET),
            ("acme-update_campaign", ResetRisk.UNKNOWN),
        ],
    )
    def test_with_nothing_declared_the_name_still_decides(
        self, tool: str, expected: ResetRisk
    ) -> None:
        """The pre-existing behaviour for an undeclared tool, both ways."""
        assert classify_change(tool, {}).risk is expected

    def test_a_hint_cannot_reclassify_a_builtin_tool(self) -> None:
        """mureo owns its own tool names, so the pinned built-in classifier
        stays authoritative — a stray registration must not turn a real
        mutation into a read (or the reverse)."""
        from mureo.policy.declarations import register_read_only_hint

        register_read_only_hint("google_ads_campaigns_update", True)
        register_read_only_hint("google_ads_campaigns_list", False)
        assert (
            classify_change(
                "google_ads_campaigns_update",
                {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
            ).risk
            is ResetRisk.RESETS
        )
        assert classify_change("google_ads_campaigns_list", {}).risk is (
            ResetRisk.NO_RESET
        )


class TestPluginRegistration:
    def teardown_method(self) -> None:
        reset_platform_learning_rules()

    def test_plugin_can_advertise_its_own_rules(self) -> None:
        from mureo.policy.learning_rules import (
            Evidence,
            PlatformLearningRules,
            ResetTrigger,
            register_platform_learning_rules,
        )

        register_platform_learning_rules(
            PlatformLearningRules(
                platform="plugin:mureo-demo-bridge:demo",
                tool_prefix="demo_",
                observation=None,
                triggers=(
                    ResetTrigger(
                        change_class="target_change",
                        tools=frozenset({"demo_update_target"}),
                        evidence=Evidence(
                            source="https://example.invalid/docs",
                            retrieved="2026-08-07",
                            quote="target changes restart the adjustment period",
                        ),
                    ),
                ),
                triggers_are_enumerated=True,
                notes="demo",
            )
        )
        assert classify_change("demo_update_target", {}).risk is ResetRisk.RESETS
        assert classify_change("demo_update_name", {}).risk is ResetRisk.NO_RESET
