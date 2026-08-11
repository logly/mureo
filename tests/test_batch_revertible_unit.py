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
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from mureo.context.batch import (
    STALE_AFTER_HOURS,
    BatchError,
    active_batch,
    batch_members,
    batch_open_hours,
    stale_batch_warning,
    stamp_batch,
)
from mureo.context.models import (
    EXTERNAL_ORIGIN,
    ActionLogEntry,
    BatchRecord,
    StateDocument,
)
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

    def test_explicit_batch_id_must_name_the_open_batch(self, workspace: Path) -> None:
        """An explicit ``batch_id`` is an assertion, and it is checked."""
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="open")
        append_action_log(
            state_file,
            ActionLogEntry(
                timestamp="2026-08-07T10:00:00+09:00",
                action="google_ads_budget_update",
                platform="google_ads",
                batch_id=batch.batch_id,
            ),
        )
        assert read_state_file(state_file).action_log[0].batch_id == batch.batch_id

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


#: One distinctive value per :class:`ActionLogEntry` field. Driven off the
#: dataclass's own field list by the tests below, so ADDING A FIELD TO
#: ``ActionLogEntry`` WITHOUT ADDING IT HERE FAILS — which is the point. The
#: hazard being guarded is silent: a field dropped while joining a batch reads
#: downstream as "the caller never set it", so nothing else would notice.
_ENTRY_FIELD_VALUES: dict[str, Any] = {
    "timestamp": "2026-08-07T10:00:00+09:00",
    "action": "google_ads_placement_exclusions_add",
    "platform": "google_ads",
    "campaign_id": "C-1",
    "ad_id": "A-1",
    "summary": "excluded 12 placements",
    "command": "/search-term-cleanup",
    "metrics_at_action": {"cpa": 5200, "conversions": 45},
    "observation_due": "2026-08-21",
    "reversible_params": {
        "operation": "google_ads_campaigns_update_status",
        "params": {"campaign_id": "C-1", "status": "ENABLED"},
    },
    "rollback_of": 3,
    "evaluation_of": 4,
    "entity_type": "ad_group",
    "entity_id": "G-1",
    # #545 provenance. These are the fields the enumerated ``stamp_batch``
    # actually dropped, and the loss was invisible: without ``origin`` an
    # observed change reads as one mureo made, and ``plan_rollback`` will
    # plan a reversal from a ``reversible_params`` hint that came from
    # outside mureo. ``external_id`` requires ``origin="external"``, so the
    # three move together.
    "origin": EXTERNAL_ORIGIN,
    "external_id": "google_ads|customers/1/changeEvents/abc",
    "occurred_at": "2026-08-05T09:14:00+09:00",
    # The one field the round-trip is ALLOWED to change: it arrives unset and
    # comes back carrying the open batch.
    "batch_id": None,
}


def _fully_populated_entry() -> ActionLogEntry:
    """An entry with every field set, checked against the dataclass itself."""
    declared = {f.name for f in fields(ActionLogEntry)}
    missing = declared - set(_ENTRY_FIELD_VALUES)
    assert not missing, (
        f"ActionLogEntry gained field(s) {sorted(missing)} with no value in "
        "_ENTRY_FIELD_VALUES. Add one, then confirm the field survives "
        "stamp_batch and the STATE.json codec — a new field that is silently "
        "dropped when an entry joins a batch is exactly the bug this guards."
    )
    stale = set(_ENTRY_FIELD_VALUES) - declared
    assert not stale, f"_ENTRY_FIELD_VALUES names removed field(s) {sorted(stale)}"
    return ActionLogEntry(**_ENTRY_FIELD_VALUES)


@pytest.mark.unit
class TestJoiningABatchPreservesTheEntry:
    """Joining a batch must change ``batch_id`` and nothing else.

    ``stamp_batch`` used to rebuild the entry field-by-field, so any field
    added to :class:`ActionLogEntry` afterwards was dropped the moment an entry
    joined an open batch — and ``join_active_batch`` defaults to ``True``, so
    that is the ordinary path, not a corner. The loss was silent: a missing
    field is indistinguishable from one the caller never set. It cost the
    provenance fields (``origin`` / ``external_id``), and with them the
    ``is_external`` marker that stops a forged ``reversible_params`` on an
    imported entry from being planned as a real reversal.

    Both tests below are driven off ``dataclasses.fields(ActionLogEntry)``
    rather than a hand-written list, so they cannot rot the same way.
    """

    def test_stamp_batch_changes_only_batch_id(self) -> None:
        """The pure function, so a failure localizes here and not in the codec."""
        entry = _fully_populated_entry()
        record = BatchRecord(
            batch_id="batch-x", label="pass", started_at="2026-08-07T09:00:00+09:00"
        )
        stamped = stamp_batch(entry, record)

        assert stamped.batch_id == "batch-x"
        for field in fields(ActionLogEntry):
            if field.name == "batch_id":
                continue
            assert getattr(stamped, field.name) == getattr(entry, field.name), (
                f"stamp_batch dropped or altered {field.name!r} while joining a "
                "batch. Use dataclasses.replace; never enumerate fields."
            )

    def test_every_field_survives_the_append_round_trip(self, workspace: Path) -> None:
        """End to end: through ``stamp_batch``, the codec, and back off disk.

        Covers the second enumerating surface too — ``state_codec`` maps the
        entry to JSON field-by-field in both directions, so a field missing
        from either half is lost on the way to STATE.json rather than on the
        way into the batch.
        """
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="preserve everything")
        entry = _fully_populated_entry()
        append_action_log(state_file, entry)

        stored = read_state_file(state_file).action_log[0]
        assert stored.batch_id == batch.batch_id
        for field in fields(ActionLogEntry):
            if field.name == "batch_id":
                continue
            assert getattr(stored, field.name) == _ENTRY_FIELD_VALUES[field.name], (
                f"{field.name!r} did not survive append_action_log with an open "
                "batch — check stamp_batch and both halves of state_codec."
            )


@pytest.mark.unit
class TestMembershipCannotBeForged:
    """Membership is the one thing this feature asks the operator to trust.

    A batch id supplied by a caller is untrusted input: an unchecked one lets
    an entry conjure a change set that never happened, or grow one whose
    membership was already reported as final.
    """

    def test_an_unknown_batch_id_is_refused(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        with pytest.raises(BatchError, match="Unknown batch_id"):
            append_action_log(
                state_file,
                ActionLogEntry(
                    timestamp="2026-08-07T10:00:00+09:00",
                    action="google_ads_budget_update",
                    platform="google_ads",
                    batch_id="batch-i-made-this-up",
                ),
            )
        assert read_state_file(state_file).action_log == ()

    def test_a_closed_batch_cannot_be_rejoined(self, workspace: Path) -> None:
        """The member_count mureo_batch_end reported must stay true."""
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="monday pass")
        append_action_log(state_file, _entry("google_ads_budget_update", "google_ads"))
        _, indices = end_batch(state_file)
        assert indices == (0,)

        with pytest.raises(BatchError, match="closed"):
            append_action_log(
                state_file,
                ActionLogEntry(
                    timestamp="2026-08-07T12:00:00+09:00",
                    action="google_ads_keywords_add",
                    platform="google_ads",
                    batch_id=batch.batch_id,
                ),
            )
        doc = read_state_file(state_file)
        assert [i for i, _ in batch_members(doc, batch.batch_id)] == list(indices)

    @pytest.mark.asyncio
    async def test_forged_batch_id_is_refused_through_the_mcp_tool(
        self, workspace: Path
    ) -> None:
        """The reproduction from review: no begin, arbitrary id, real batch."""
        from mureo.mcp.tools_mureo_context import handle_tool as handle_context_tool

        with pytest.raises(ValueError, match="Unknown batch_id"):
            await handle_context_tool(
                "mureo_state_action_log_append",
                {
                    "entry": {
                        "action": "google_ads_placement_exclusions_add",
                        "platform": "google_ads",
                        "batch_id": "batch-fabricated",
                    }
                },
            )
        payload = _payload(
            await handle_rollback_tool(
                "rollback_plan_get", {"batch_id": "batch-fabricated"}
            )
        )
        assert payload["coverage"] == "empty"
        assert payload["members"] == []


@pytest.mark.unit
class TestForgottenBatchAnnouncesItself:
    """A missed ``end`` is worse than a missed ``begin``.

    A missed begin yields no batch — obvious and harmless. A missed end yields
    a batch that keeps swallowing unrelated changes and then reports them,
    confidently, as one unit. Nothing auto-closes: that would trade a visible
    wrong answer for an invisible one.
    """

    def test_a_fresh_batch_is_not_stale(self, workspace: Path) -> None:
        batch = begin_batch(workspace / "STATE.json", label="just opened")
        assert stale_batch_warning(batch) is None

    def test_a_long_open_batch_warns(self) -> None:
        started = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        record = BatchRecord(
            batch_id="batch-old",
            label="monday pass",
            started_at=started.isoformat(),
        )
        now = started + timedelta(hours=STALE_AFTER_HOURS + 1)
        warning = stale_batch_warning(record, now)
        assert warning is not None
        assert "batch-old" in warning
        assert "mureo_batch_end" in warning
        # Never auto-closed — the record is untouched.
        assert record.ended_at is None

    def test_a_closed_batch_never_warns(self) -> None:
        record = BatchRecord(
            batch_id="batch-done",
            label="done",
            started_at="2026-08-01T09:00:00+00:00",
            ended_at="2026-08-01T10:00:00+00:00",
        )
        assert stale_batch_warning(record, datetime.now(timezone.utc)) is None

    def test_staleness_follows_the_server_clock_seam(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default ``now`` is ``clock.server_now``, not a raw wall clock.

        Without this, the production path would be the only caller outside the
        one clock seam (#460) — every other test here passes ``now`` explicitly,
        so a drift back to ``datetime.now`` would pass unnoticed. Freezing the
        seam must move the verdict.
        """
        from mureo.core import clock

        started = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        record = BatchRecord(
            batch_id="batch-seam", label="pass", started_at=started.isoformat()
        )

        monkeypatch.setattr(clock, "server_now", lambda: started + timedelta(hours=1))
        assert batch_open_hours(record) == pytest.approx(1.0)
        assert stale_batch_warning(record) is None

        monkeypatch.setattr(
            clock, "server_now", lambda: started + timedelta(hours=STALE_AFTER_HOURS)
        )
        assert batch_open_hours(record) == pytest.approx(float(STALE_AFTER_HOURS))
        assert stale_batch_warning(record) is not None

    def test_an_unparseable_start_is_not_reported_as_fresh(self) -> None:
        """An unknown age must not pass for a small one."""
        record = BatchRecord(batch_id="b", label="l", started_at="not-a-date")
        assert batch_open_hours(record) is None
        assert stale_batch_warning(record) is None

    @pytest.mark.asyncio
    async def test_batch_status_carries_the_warning(self, workspace: Path) -> None:
        state_file = workspace / "STATE.json"
        begin_batch(state_file, label="forgotten")
        doc = read_state_file(state_file)
        stale = replace(
            doc.batches[0],
            started_at=(
                datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS + 2)
            ).isoformat(),
        )
        write_state_file(state_file, replace(doc, batches=(stale,)))

        payload = _payload(await handle_batch_tool("mureo_batch_status", {}))
        assert payload["warning"] is not None
        assert "mureo_batch_end" in payload["warning"]

    @pytest.mark.asyncio
    async def test_reminder_fires_only_while_a_stale_batch_is_open(
        self, workspace: Path
    ) -> None:
        from mureo.mcp._handlers_batch import maybe_build_batch_reminder

        assert maybe_build_batch_reminder() is None  # nothing open

        state_file = workspace / "STATE.json"
        begin_batch(state_file, label="forgotten")
        assert maybe_build_batch_reminder() is None  # open, but fresh

        doc = read_state_file(state_file)
        stale = replace(
            doc.batches[0],
            started_at=(
                datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS + 2)
            ).isoformat(),
        )
        write_state_file(state_file, replace(doc, batches=(stale,)))
        assert maybe_build_batch_reminder() is not None

    @pytest.mark.asyncio
    async def test_reminder_can_be_disabled(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mureo.mcp._handlers_batch import maybe_build_batch_reminder

        state_file = workspace / "STATE.json"
        begin_batch(state_file, label="forgotten")
        doc = read_state_file(state_file)
        stale = replace(
            doc.batches[0],
            started_at=(
                datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS + 2)
            ).isoformat(),
        )
        write_state_file(state_file, replace(doc, batches=(stale,)))
        assert maybe_build_batch_reminder() is not None

        monkeypatch.setenv("MUREO_DISABLE_BATCH_REMINDER", "1")
        assert maybe_build_batch_reminder() is None


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

    def test_native_read_only_member_is_not_counted_as_a_gap(
        self, workspace: Path
    ) -> None:
        """A read in the batch is not something the operator must undo by hand.

        KNOWN DEFECT, pinned deliberately — read this before "fixing" it.

        **What is wrong.** ``mureo.core.tool_names.is_read_only_tool_name``
        anchors its verbs at the START of a hyphen-delimited name segment
        (``list_campaigns``), but mureo's own tools put the verb at the END
        (``google_ads_campaigns_list``). So::

            is_read_only_tool_name("google_ads_campaigns_list")  # False, wrong

        A NATIVE read therefore reaches ``plan_rollback`` as a write with no
        ``reversible_params`` hint and is classified IRREVERSIBLE instead of
        NOTHING_TO_REVERSE. The error direction is safe — nothing is offered
        for reversal that should not be — but the batch report shows the
        operator a read among the "cannot be reverted" items, which is untrue
        and corrodes trust in exactly the surface #549 adds. The bridged
        spelling (``campaign_management-list_campaigns``) is matched correctly
        today, which is why both are asserted here.

        **Why it is not fixed in the #549 PR.** The obvious fix — also match a
        verb at the END of a segment — is wrong, not merely broad. Three
        modules share this vocabulary, and one of them gates a DENIAL:
        ``mureo.mcp.server._register_pattern_fallbacks`` skips
        ``register_pattern_fallback_tool(name)`` when the name reads as a read,
        so a name wrongly classified as a read loses its guardrail money
        pattern-scan. Measured on a 294-tool installed plugin surface, a naive
        suffix rule flips 23 names, and **13 of them are**
        ``ToolSemantics(mutating=True)`` — i.e. 13 real mutations would be
        newly exempted from the money scan::

            amc-execute_query
            logly_ads_context_merge_adgroup_list
            reporting-create_campaign_report
            reporting-create_inventory_report
            reporting-create_product_report
            reporting-create_report
            reporting-delete_report          <- a DELETE reading as a read
            yahoo_ads_create_placement_url_list
            yahoo_ads_display_create_placement_url_list
            yahoo_ads_display_remove_placement_url_list
            yahoo_ads_display_update_placement_url_list
            yahoo_ads_remove_placement_url_list
            yahoo_ads_update_placement_url_list

        (On the native side the same rule flips 70 of 208 names, none carrying
        a write verb — the native direction alone is safe.)

        **What a correct fix must do.** Match a trailing verb only when no
        write verb (``create`` / ``update`` / ``delete`` / ``remove`` / ``set``
        / ``add`` / ``merge`` / ``execute`` …) appears elsewhere in the same
        segment, so ``google_ads_campaigns_list`` becomes a read while
        ``reporting-delete_report`` and ``yahoo_ads_update_placement_url_list``
        stay writes. It changes plugin guardrail registration, plugin
        ``derive_semantics`` classification and ``mureo rollback list`` output,
        so it needs its own tests in ``test_strategy_gate_pattern_fallback.py``,
        ``test_mcp_plugin_semantics.py``, ``test_rollback.py`` and
        ``test_cli_rollback.py``.

        **What flips here when it lands.** The ``by_index[0]`` assertion below
        becomes ``BatchMemberStatus.NOTHING_TO_REVERSE``. ``by_index[1]``,
        ``by_index[2]`` and ``apply_order`` are unchanged.
        """
        state_file = workspace / "STATE.json"
        batch = begin_batch(state_file, label="a pass that also read things")
        append_action_log(state_file, _entry("google_ads_campaigns_list", "google_ads"))
        append_action_log(
            state_file,
            _entry("campaign_management-list_campaigns", _PLUGIN_PLATFORM),
        )
        append_action_log(
            state_file,
            _entry(
                "google_ads_campaigns_update_status",
                "google_ads",
                reversible_params=_GOOGLE_REVERSAL,
            ),
        )
        end_batch(state_file)

        plan = plan_batch_rollback(read_state_file(state_file), batch.batch_id)
        by_index = {m.index: m for m in plan.members}
        # Bridged spelling: correctly recognised as a read today.
        assert by_index[1].status is BatchMemberStatus.NOTHING_TO_REVERSE
        # Native spelling: misclassified today. Flip this to
        # NOTHING_TO_REVERSE with the tool_names fix.
        assert by_index[0].status is BatchMemberStatus.IRREVERSIBLE
        assert by_index[2].status is BatchMemberStatus.REVERSIBLE
        # Either way a read is never offered for reversal.
        assert plan.apply_order == (2,)

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
