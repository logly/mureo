"""Rollback planner tests.

Pure, I/O-free. Exercises plan generation from ActionLogEntry
reversible_params hints across supported, partial, and
not-supported action types.
"""

from __future__ import annotations

import pytest

from mureo.context.models import ActionLogEntry
from mureo.rollback import (
    RollbackPlan,
    RollbackStatus,
    plan_rollback,
)


def _entry(
    *,
    action: str = "update_budget",
    platform: str = "google_ads",
    reversible_params: dict | None = None,
    campaign_id: str | None = "123",
    timestamp: str = "2026-04-15T10:00:00",
) -> ActionLogEntry:
    return ActionLogEntry(
        timestamp=timestamp,
        action=action,
        platform=platform,
        campaign_id=campaign_id,
        reversible_params=reversible_params,
    )


@pytest.mark.unit
class TestReversibleHintPresent:
    def test_supported_budget_update(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "456", "amount_micros": 10_000_000_000},
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.SUPPORTED
        assert plan.operation == "google_ads_budget_update"
        assert plan.params == {"budget_id": "456", "amount_micros": 10_000_000_000}
        assert plan.source_timestamp == "2026-04-15T10:00:00"
        assert plan.platform == "google_ads"

    def test_caveats_promote_status_to_partial(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "meta_ads_campaigns_update_status",
                "params": {"campaign_id": "abc", "status": "ACTIVE"},
                "caveats": ["Paused spend is not refundable."],
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.PARTIAL
        assert "Paused spend is not refundable." in plan.caveats

    def test_description_includes_action_name(self) -> None:
        entry = _entry(
            action="update_budget",
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "456", "amount_micros": 10_000_000_000},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert "update_budget" in plan.description


@pytest.mark.unit
class TestNotReversible:
    def test_missing_hint_on_write_action_returns_not_supported(self) -> None:
        entry = _entry(action="update_budget", reversible_params=None)
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert plan.operation is None
        assert plan.params is None

    def test_read_only_action_returns_none(self) -> None:
        # A pure query (e.g., daily-check) has no state change to reverse.
        entry = _entry(action="list_campaigns", reversible_params=None)
        plan = plan_rollback(entry)
        assert plan is None

    def test_hint_missing_operation_key_is_rejected(self) -> None:
        entry = _entry(reversible_params={"params": {"budget_id": "456"}})
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "operation" in plan.notes.lower()

    def test_hint_missing_params_key_is_rejected(self) -> None:
        entry = _entry(reversible_params={"operation": "google_ads_budget_update"})
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED

    def test_operation_not_in_allowlist_rejected(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "google_ads_something_exotic",
                "params": {"id": "1"},
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "allow-list" in plan.notes

    def test_destructive_operation_rejected(self) -> None:
        # Even if we added a ".delete" operation to the allow-list by mistake,
        # the destructive-verb guard is a second line of defense.
        entry = _entry(
            reversible_params={
                "operation": "google_ads_campaigns_delete",
                "params": {"campaign_id": "1"},
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "destructive" in plan.notes

    def test_params_with_extra_keys_rejected(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "google_ads_budget_update",
                # login_customer_id would let an agent pivot to another account.
                "params": {
                    "budget_id": "456",
                    "amount_micros": 1,
                    "login_customer_id": "999",
                },
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "login_customer_id" in plan.notes

    def test_caveats_not_a_list_rejected(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "456", "amount_micros": 1},
                "caveats": "just a string",
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "caveats" in plan.notes

    def test_read_only_action_with_hint_is_flagged_as_bug(self) -> None:
        entry = _entry(
            action="list_campaigns",
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": {"budget_id": "456", "amount_micros": 1},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "agent bug" in plan.notes.lower()


@pytest.mark.unit
class TestRollbackPlanImmutability:
    def test_frozen(self) -> None:
        plan = RollbackPlan(
            source_timestamp="2026-04-15T10:00:00",
            source_action="update_budget",
            platform="google_ads",
            status=RollbackStatus.SUPPORTED,
            operation="google_ads_budget_update",
            params={"budget_id": "456"},
            description="Reverse update_budget",
            caveats=(),
            notes="",
        )
        with pytest.raises(AttributeError):
            plan.status = RollbackStatus.NOT_SUPPORTED  # type: ignore[misc]

    def test_params_defensive_copy(self) -> None:
        src = {"budget_id": "456", "amount_micros": 10_000_000_000}
        entry = _entry(
            reversible_params={
                "operation": "google_ads_budget_update",
                "params": src,
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.params is not None
        assert plan.params is not src

    def test_post_construction_mutation_does_not_affect_stored_plan(self) -> None:
        # Directly constructing a plan should also snapshot params, so a caller
        # mutating the dict they passed in cannot corrupt the stored plan.
        params = {"budget_id": "456", "amount_micros": 1}
        plan = RollbackPlan(
            source_timestamp="t",
            source_action="update_budget",
            platform="google_ads",
            status=RollbackStatus.SUPPORTED,
            operation="google_ads_budget_update",
            params=params,
            description="x",
        )
        params["amount_micros"] = 999
        assert plan.params is not None
        assert plan.params["amount_micros"] == 1


@pytest.mark.unit
class TestStatusValues:
    def test_enum_values_stable(self) -> None:
        assert RollbackStatus.SUPPORTED.value == "supported"
        assert RollbackStatus.PARTIAL.value == "partial"
        assert RollbackStatus.NOT_SUPPORTED.value == "not_supported"
