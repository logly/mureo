"""A bulk operation is one revertible unit (#549).

Three properties, one per section below:

1. **Grouping.** Every ``action_log`` write path stamps the open batch's id,
   so N operations dispatched as one logical batch become one reviewable set
   — regardless of which platform each member ran on.
2. **Coverage.** ``rollback_plan_get`` accepts that batch id and returns a
   plan covering EVERY member, not just the reversible ones.
3. **Honesty.** A batch whose members are not uniformly reversible says so
   BEFORE anything is applied — per member, and per platform.

The platform mix is deliberate. Reversibility is not uniform across
platforms, so a single-platform test would prove nothing about the case the
issue exists for. These tests cover ``google_ads`` and ``meta_ads`` (native),
``tiktok_ads`` (hosted connector, recorded through
``mureo_state_action_log_append``) and ``plugin:<dist>:<provider>`` (the
bridged / plugin ABI path, recorded through
``plugin_semantics.record_mutation_action_log``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.context.batch import BatchError, active_batch, batch_members, new_batch_id
from mureo.context.models import ActionLogEntry, StateDocument
from mureo.context.state import (
    append_action_log,
    begin_batch,
    end_batch,
    read_state_file,
    write_state_file,
)
from mureo.mcp.tools_batch import TOOLS as BATCH_TOOLS
from mureo.mcp.tools_batch import handle_tool as handle_batch_tool
from mureo.mcp.tools_rollback import handle_tool as handle_rollback_tool
from mureo.rollback.batch import plan_batch_rollback
from mureo.rollback.models import BatchCoverage, BatchMemberStatus

_PLUGIN_PLATFORM = "plugin:mureo-amazon-ads-bridge:amazon_ads"


@pytest.fixture(autouse=True)
def _clear_runtime_context_cache():
    """Reset the workspace resolver cache around every test (see
    tests/test_mcp_tools_rollback.py — same reason)."""
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    yield
    reset_runtime_context()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace with an existing STATE.json, as cwd."""
    monkeypatch.chdir(tmp_path)
    write_state_file(tmp_path / "STATE.json", StateDocument(version="2"))
    return tmp_path


def _payload(result: list[Any]) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(result[0].text)
    return parsed


def _entry(
    action: str,
    platform: str,
    *,
    reversible_params: dict[str, Any] | None = None,
) -> ActionLogEntry:
    return ActionLogEntry(
        timestamp="2026-08-07T10:00:00+09:00",
        action=action,
        platform=platform,
        reversible_params=reversible_params,
    )


# Reversal hints, one per platform family, all through the SAME core shape.
_GOOGLE_REVERSAL = {
    "operation": "google_ads_campaigns_update_status",
    "params": {"campaign_id": "G1", "status": "ENABLED"},
}
_META_REVERSAL = {
    "operation": "meta_ads_ad_sets_enable",
    "params": {"ad_set_id": "M1"},
}
_META_REVERSAL_WITH_CAVEAT = {
    "operation": "meta_ads_campaigns_enable",
    "params": {"campaign_id": "M9"},
    "caveats": ["Spend already incurred cannot be refunded."],
}
# A bridged/plugin tool mureo does not own: the hint names the provider's own
# operation, which is NOT in the built-in allow-list and (with no such plugin
# tool registered) cannot be dispatched. This is the member that must be
# reported as irreversible rather than quietly counted as covered.
_BRIDGED_REVERSAL = {
    "operation": "amazon_ads_negative_keywords_restore",
    "params": {"keyword_id": "A1"},
}


# ---------------------------------------------------------------------------
# 1. Grouping — N operations, one batch id, four platforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchGrouping:
    @pytest.mark.asyncio
    async def test_members_of_one_dispatched_batch_share_a_batch_id(
        self, workspace: Path
    ) -> None:
        """Native, hosted-connector and bridged/plugin writes join one batch.

        Each of the four members enters ``action_log`` through a DIFFERENT
        recording path, which is the point: batch membership is a core
        concern, not a per-platform one.
        """
        state_file = workspace / "STATE.json"
        begin = _payload(
            await handle_batch_tool(
                "mureo_batch_begin", {"label": "bulk exclusion pass"}
            )
        )
        batch_id = begin["batch_id"]
        assert batch_id

        # (a) native google_ads + (b) hosted connector tiktok_ads, both via the
        # generic append tool an agent uses for a non-auto-recorded mutation.
        from mureo.mcp.tools_mureo_context import handle_tool as handle_context_tool

        for action, platform in (
            ("google_ads_placement_exclusions_add", "google_ads"),
            ("tiktok_ads_ad_groups_update", "tiktok_ads"),
        ):
            await handle_context_tool(
                "mureo_state_action_log_append",
                {"entry": {"action": action, "platform": platform}},
            )

        # (c) native meta_ads status toggle, via the native recording path.
        from mureo.mcp.native_reversal import record_native_mutation

        record_native_mutation(
            "meta_ads_ad_sets_pause", {"ad_set_id": "M1"}, "ACTIVE", None
        )

        # (d) bridged / plugin mutation, via the plugin ABI recording path.
        from mureo.mcp.plugin_semantics import record_mutation_action_log

        record_mutation_action_log(
            tool="amazon_ads_negative_keywords_create",
            source="mureo-amazon-ads-bridge",
            provider="amazon_ads",
            reversal=None,
            arguments={"campaign_id": "A9"},
        )

        end = _payload(await handle_batch_tool("mureo_batch_end", {}))
        assert end["batch_id"] == batch_id
        assert end["member_count"] == 4

        doc = read_state_file(state_file)
        assert [e.batch_id for e in doc.action_log] == [batch_id] * 4
        assert {e.platform for e in doc.action_log} == {
            "google_ads",
            "tiktok_ads",
            "meta_ads",
            _PLUGIN_PLATFORM,
        }
        assert [i for i, _ in batch_members(doc, batch_id)] == [0, 1, 2, 3]

    def test_entries_written_outside_a_batch_carry_no_batch_id(
        self, workspace: Path
    ) -> None:
        state_file = workspace / "STATE.json"
        append_action_log(state_file, _entry("google_ads_budget_update", "google_ads"))
        doc = read_state_file(state_file)
        assert doc.action_log[0].batch_id is None
        assert active_batch(doc) is None

    def test_begin_refuses_to_nest(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        begin_batch(state_file, label="first")
        with pytest.raises(BatchError):
            begin_batch(state_file, label="second")

    def test_end_without_an_open_batch_is_refused(self, workspace: Path) -> None:
        with pytest.raises(BatchError):
            end_batch(workspace / "STATE.json")

    def test_explicit_batch_id_on_the_entry_wins(self, workspace: Path) -> None:
        """An imported / backfilled entry keeps the batch it declares."""
        state_file = workspace / "STATE.json"
        begin_batch(state_file, label="open")
        foreign = new_batch_id()
        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-08-07T10:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
                batch_id=foreign,
            ),
        )
        assert read_state_file(state_file).action_log[0].batch_id == foreign

    def test_rollback_entries_do_not_join_the_open_batch(self, workspace: Path) -> None:
        """A reversal appended while a batch is open must not become a member.

        Otherwise reverting a batch would grow the batch it is reverting, and
        the next plan would list the reversals as things still to reverse.
        """
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="open")
        append_action_log(
            state_file,
            _entry("google_ads_campaigns_update_status", "google_ads"),
            join_active_batch=False,
        )
        doc = read_state_file(state_file)
        assert doc.action_log[0].batch_id is None
        assert active_batch(doc) is not None
        assert batch_members(doc, batch.batch_id) == ()


# ---------------------------------------------------------------------------
# 2/3. Coverage + honesty — the plan reports every member and every gap
# ---------------------------------------------------------------------------


def _mixed_batch(state_file: Path) -> str:
    """Write a four-member, three-platform batch with mixed reversibility."""
    batch = begin_batch(state_file, label="monday bulk pass")
    append_action_log(
        state_file,
        _entry(
            "google_ads_campaigns_update_status",
            "google_ads",
            reversible_params=_GOOGLE_REVERSAL,
        ),
    )
    append_action_log(
        state_file,
        _entry(
            "meta_ads_campaigns_pause",
            "meta_ads",
            reversible_params=_META_REVERSAL_WITH_CAVEAT,
        ),
    )
    append_action_log(
        state_file,
        _entry(
            "amazon_ads_negative_keywords_create",
            _PLUGIN_PLATFORM,
            reversible_params=_BRIDGED_REVERSAL,
        ),
    )
    append_action_log(
        state_file,
        _entry("tiktok_ads_ad_groups_update", "tiktok_ads"),
    )
    end_batch(state_file)
    return batch.batch_id


@pytest.mark.unit
class TestBatchPlanCoverage:
    def test_plan_covers_every_member_of_the_batch(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        batch_id = _mixed_batch(state_file)
        plan = plan_batch_rollback(read_state_file(state_file), batch_id)

        assert plan.batch_id == batch_id
        assert plan.label == "monday bulk pass"
        assert [m.index for m in plan.members] == [0, 1, 2, 3]

    def test_partial_reversibility_is_reported_before_anything_is_applied(
        self, workspace: Path
    ) -> None:
        state_file = workspace / "STATE.json"
        batch_id = _mixed_batch(state_file)
        before = read_state_file(state_file)
        plan = plan_batch_rollback(before, batch_id)

        statuses = {m.index: m.status for m in plan.members}
        assert statuses[0] is BatchMemberStatus.REVERSIBLE
        assert statuses[1] is BatchMemberStatus.REVERSIBLE_WITH_CAVEATS
        # The bridged member names an operation mureo cannot dispatch.
        assert statuses[2] is BatchMemberStatus.IRREVERSIBLE
        # The hosted-connector member was recorded with no reversal hint.
        assert statuses[3] is BatchMemberStatus.IRREVERSIBLE

        assert plan.coverage is BatchCoverage.PARTIAL
        # Every irreversible member states WHY, in the plan, up front.
        assert all(m.reason for m in plan.members if not m.is_reversible)
        # Planning is pure: nothing was applied, nothing was written.
        assert read_state_file(state_file).action_log == before.action_log

    def test_coverage_is_reported_per_platform(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        batch_id = _mixed_batch(state_file)
        plan = plan_batch_rollback(read_state_file(state_file), batch_id)

        coverage = dict(plan.platform_coverage)
        assert coverage["google_ads"] is BatchCoverage.FULL
        assert coverage["meta_ads"] is BatchCoverage.FULL
        assert coverage[_PLUGIN_PLATFORM] is BatchCoverage.NONE
        assert coverage["tiktok_ads"] is BatchCoverage.NONE

    def test_fully_reversible_batch_reports_full(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="two platforms, both reversible")
        append_action_log(
            state_file,
            _entry(
                "google_ads_campaigns_update_status",
                "google_ads",
                reversible_params=_GOOGLE_REVERSAL,
            ),
        )
        append_action_log(
            state_file,
            _entry(
                "meta_ads_ad_sets_pause", "meta_ads", reversible_params=_META_REVERSAL
            ),
        )
        end_batch(state_file)
        plan = plan_batch_rollback(read_state_file(state_file), batch.batch_id)
        assert plan.coverage is BatchCoverage.FULL
        assert plan.apply_order == (1, 0)

    def test_already_reversed_member_is_not_offered_again(
        self, workspace: Path
    ) -> None:
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="one member")
        append_action_log(
            state_file,
            _entry(
                "google_ads_campaigns_update_status",
                "google_ads",
                reversible_params=_GOOGLE_REVERSAL,
            ),
        )
        end_batch(state_file)
        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-08-07T11:00:00+09:00",
                action="google_ads_campaigns_update_status",
                platform="google_ads",
                rollback_of=0,
            ),
        )
        plan = plan_batch_rollback(read_state_file(state_file), batch.batch_id)
        assert plan.members[0].status is BatchMemberStatus.ALREADY_REVERSED
        assert plan.apply_order == ()

    def test_unknown_batch_id_is_empty_not_a_lie(self, workspace: Path) -> None:
        plan = plan_batch_rollback(read_state_file(workspace / "STATE.json"), "nope")
        assert plan.coverage is BatchCoverage.EMPTY
        assert plan.members == ()


# ---------------------------------------------------------------------------
# rollback_plan_get — the MCP surface named in the issue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRollbackPlanGetBatchMode:
    @pytest.mark.asyncio
    async def test_plan_get_by_batch_id_returns_every_member(
        self, workspace: Path
    ) -> None:
        batch_id = _mixed_batch(workspace / "STATE.json")
        payload = _payload(
            await handle_rollback_tool("rollback_plan_get", {"batch_id": batch_id})
        )
        assert payload["batch_id"] == batch_id
        assert [m["index"] for m in payload["members"]] == [0, 1, 2, 3]
        assert payload["counts"]["total"] == 4

    @pytest.mark.asyncio
    async def test_plan_get_by_batch_id_names_the_irreversible_members(
        self, workspace: Path
    ) -> None:
        batch_id = _mixed_batch(workspace / "STATE.json")
        payload = _payload(
            await handle_rollback_tool("rollback_plan_get", {"batch_id": batch_id})
        )
        assert payload["coverage"] == "partial"
        assert payload["counts"]["irreversible"] == 2
        irreversible = [
            m for m in payload["members"] if m["reversibility"] == "irreversible"
        ]
        assert {m["platform"] for m in irreversible} == {
            _PLUGIN_PLATFORM,
            "tiktok_ads",
        }
        assert all(m["reason"] for m in irreversible)
        assert payload["platform_coverage"]["google_ads"] == "full"
        assert payload["platform_coverage"][_PLUGIN_PLATFORM] == "none"

    @pytest.mark.asyncio
    async def test_plan_get_by_index_is_unchanged(self, workspace: Path) -> None:
        """The single-entry contract keeps working byte-for-byte."""
        state_file = workspace / "STATE.json"
        append_action_log(
            state_file,
            _entry(
                "google_ads_campaigns_update_status",
                "google_ads",
                reversible_params=_GOOGLE_REVERSAL,
            ),
        )
        payload = _payload(
            await handle_rollback_tool("rollback_plan_get", {"index": 0})
        )
        assert payload["status"] == "supported"
        assert payload["operation"] == "google_ads_campaigns_update_status"
        assert "members" not in payload

    @pytest.mark.asyncio
    async def test_plan_get_requires_exactly_one_selector(
        self, workspace: Path
    ) -> None:
        for arguments in ({}, {"index": 0, "batch_id": "b"}):
            payload = _payload(
                await handle_rollback_tool("rollback_plan_get", arguments)
            )
            assert payload["plan"] is None
            assert "exactly one" in payload["reason"]


# ---------------------------------------------------------------------------
# Backward compatibility with pre-#549 STATE.json files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackwardCompatibility:
    def test_legacy_action_log_round_trips_without_gaining_keys(
        self, tmp_path: Path
    ) -> None:
        raw = {
            "version": "2",
            "last_synced_at": None,
            "customer_id": None,
            "campaigns": [],
            "platforms": None,
            "action_log": [
                {
                    "timestamp": "2026-04-15T10:00:00",
                    "action": "google_ads_budget_update",
                    "platform": "google_ads",
                }
            ],
        }
        path = tmp_path / "STATE.json"
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        doc = read_state_file(path)
        assert doc.action_log[0].batch_id is None
        assert doc.batches == ()

        write_state_file(path, doc)
        written = json.loads(path.read_text(encoding="utf-8"))
        assert "batch_id" not in written["action_log"][0]
        assert "batches" not in written

    def test_legacy_entries_are_planned_exactly_as_before(self, tmp_path: Path) -> None:
        entry = _entry(
            "google_ads_campaigns_update_status",
            "google_ads",
            reversible_params=_GOOGLE_REVERSAL,
        )
        from mureo.rollback import plan_rollback

        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status.value == "supported"


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchToolRegistration:
    def test_batch_tools_are_named_and_registered(self) -> None:
        assert {t.name for t in BATCH_TOOLS} == {
            "mureo_batch_begin",
            "mureo_batch_end",
            "mureo_batch_status",
        }

    @pytest.mark.asyncio
    async def test_batch_tools_are_in_the_server_tool_list(self) -> None:
        from mureo.mcp.server import handle_list_tools

        names = {t.name for t in await handle_list_tools()}
        assert {"mureo_batch_begin", "mureo_batch_end", "mureo_batch_status"} <= names

    @pytest.mark.asyncio
    async def test_batch_status_reports_the_open_batch(self, workspace: Path) -> None:
        idle = _payload(await handle_batch_tool("mureo_batch_status", {}))
        assert idle["active_batch"] is None
        begin = _payload(
            await handle_batch_tool("mureo_batch_begin", {"label": "pass"})
        )
        status = _payload(await handle_batch_tool("mureo_batch_status", {}))
        assert status["active_batch"]["batch_id"] == begin["batch_id"]
        assert status["member_count"] == 0
