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
                "params": {"budget_id": "456", "amount": 10_000_000_000},
            }
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.SUPPORTED
        assert plan.operation == "google_ads_budget_update"
        assert plan.params == {"budget_id": "456", "amount": 10_000_000_000}
        assert plan.source_timestamp == "2026-04-15T10:00:00"
        assert plan.platform == "google_ads"

    def test_caveats_promote_status_to_partial(self) -> None:
        entry = _entry(
            reversible_params={
                "operation": "meta_ads_campaigns_enable",
                "params": {"campaign_id": "abc"},
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
                "params": {"budget_id": "456", "amount": 10_000_000_000},
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
                    "amount": 1,
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
                "params": {"budget_id": "456", "amount": 1},
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
                "params": {"budget_id": "456", "amount": 1},
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
        src = {"budget_id": "456", "amount": 10_000_000_000}
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
        params = {"budget_id": "456", "amount": 1}
        plan = RollbackPlan(
            source_timestamp="t",
            source_action="update_budget",
            platform="google_ads",
            status=RollbackStatus.SUPPORTED,
            operation="google_ads_budget_update",
            params=params,
            description="x",
        )
        params["amount"] = 999
        assert plan.params is not None
        assert plan.params["amount"] == 1


@pytest.mark.unit
class TestStatusValues:
    def test_enum_values_stable(self) -> None:
        assert RollbackStatus.SUPPORTED.value == "supported"
        assert RollbackStatus.PARTIAL.value == "partial"
        assert RollbackStatus.NOT_SUPPORTED.value == "not_supported"


@pytest.mark.unit
class TestPluginReversalEscapeHatch:
    """Guardrail parity (#114 follow-up): a plugin-declared reversal that
    names a *registered* plugin tool is planned (and so executable),
    bounded by that tool's schema property keys. The plugin lookup is
    monkeypatched so these stay pure — the live wiring is exercised in
    ``test_mcp_server_plugin_wiring`` / ``test_rollback_execute``.
    """

    def test_registered_plugin_reversal_is_supported(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "mureo.rollback.planner._plugin_reversal_keys",
            lambda op: (True, frozenset({"campaign_id"})),
        )
        entry = _entry(
            action="acme_pause",
            platform="plugin:acme-dist",
            reversible_params={
                "operation": "acme_resume",
                "params": {"campaign_id": "123"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.SUPPORTED
        assert plan.operation == "acme_resume"
        assert plan.params == {"campaign_id": "123"}

    def test_unregistered_operation_still_not_supported(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "mureo.rollback.planner._plugin_reversal_keys",
            lambda op: (False, None),
        )
        entry = _entry(
            action="acme_pause",
            reversible_params={
                "operation": "acme_resume",
                "params": {"campaign_id": "123"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "allow-list" in plan.notes

    def test_plugin_reversal_extra_params_rejected(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "mureo.rollback.planner._plugin_reversal_keys",
            lambda op: (True, frozenset({"campaign_id"})),
        )
        entry = _entry(
            action="acme_pause",
            reversible_params={
                "operation": "acme_resume",
                "params": {"campaign_id": "123", "smuggled": "evil"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "unexpected params" in plan.notes

    def test_schemaless_plugin_reversal_skips_key_restriction(
        self, monkeypatch
    ) -> None:
        # (True, None) = registered plugin tool with no usable schema:
        # no plan-time key restriction (execution re-validates + re-gates).
        monkeypatch.setattr(
            "mureo.rollback.planner._plugin_reversal_keys",
            lambda op: (True, None),
        )
        entry = _entry(
            action="acme_pause",
            reversible_params={
                "operation": "acme_resume",
                "params": {"anything": "goes", "more": 1},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.SUPPORTED

    def test_reversal_naming_builtin_tool_is_not_a_plugin_op(self) -> None:
        """Cross-namespace boundary: a plugin reversal whose ``operation``
        names a *built-in* tool not in the static allow-list is refused — the
        real ``_plugin_reversal_keys`` lazily resolves it against the live
        server and returns ``(False, None)`` because built-in names are never
        in ``_PLUGIN_NAMES``. No monkeypatch — exercises the real lazy import.
        """
        entry = _entry(
            action="acme_pause",
            reversible_params={
                # A real built-in tool name, but NOT in _ALLOWED_OPERATIONS.
                "operation": "google_ads_campaigns_create",
                "params": {"campaign_id": "123"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "allow-list" in plan.notes

    def test_destructive_plugin_reversal_rejected_before_lookup(
        self, monkeypatch
    ) -> None:
        """The destructive-verb refusal runs *before* the plugin hook, so a
        plugin can never declare a reversal that deletes."""
        consulted: list[str] = []

        def _spy(op: str):
            consulted.append(op)
            return (True, None)

        monkeypatch.setattr("mureo.rollback.planner._plugin_reversal_keys", _spy)
        entry = _entry(
            action="acme_pause",
            reversible_params={
                "operation": "acme_campaigns_delete",
                "params": {},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "destructive" in plan.notes.lower()
        assert consulted == []  # hook never reached for a destructive op


@pytest.mark.unit
class TestHyphenNamespacedToolNames:
    """A bridged MCP server may namespace its tools with a hyphen
    (``campaign_management-delete_campaign``). The verb / read-only
    detection keyed on ``_delete`` and ``list_`` never matched those, so a
    destructive reversal read as harmless and a read-only action read as a
    write. Native (hyphen-free) names are unaffected.
    """

    @pytest.mark.parametrize(
        "action",
        [
            "campaign_management-list_campaigns",
            "reporting-get_report",
            "campaign_management-search_keywords",
        ],
    )
    def test_hyphen_namespaced_reads_are_read_only(self, action: str) -> None:
        assert plan_rollback(_entry(action=action, reversible_params=None)) is None

    def test_a_hyphen_namespaced_read_with_a_hint_is_flagged(self) -> None:
        entry = _entry(
            action="campaign_management-list_campaigns",
            reversible_params={"operation": "x", "params": {}},
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "Read-only action" in plan.notes

    @pytest.mark.parametrize(
        "operation",
        [
            "campaign_management-delete_campaign",
            "campaign_management-remove_keywords",
            "billing-transfer_funds",
        ],
    )
    def test_hyphen_namespaced_destructive_verbs_are_refused(
        self, operation: str, monkeypatch
    ) -> None:
        consulted: list[str] = []

        def _spy(op: str):
            consulted.append(op)
            return (True, None)

        monkeypatch.setattr("mureo.rollback.planner._plugin_reversal_keys", _spy)
        entry = _entry(
            action="campaign_management-update_campaign",
            reversible_params={"operation": operation, "params": {}},
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
        assert "destructive" in plan.notes.lower()
        assert consulted == []

    def test_a_hyphen_namespaced_write_is_still_plannable(self, monkeypatch) -> None:
        """Generalizing the match must not turn every namespaced name into a
        refusal — a harmless namespaced reversal still plans."""
        monkeypatch.setattr(
            "mureo.rollback.planner._plugin_reversal_keys",
            lambda op: (True, frozenset({"campaign_id"})),
        )
        entry = _entry(
            action="campaign_management-update_campaign",
            platform="plugin:acme-dist",
            reversible_params={
                "operation": "campaign_management-update_campaign",
                "params": {"campaign_id": "123"},
            },
        )
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.SUPPORTED

    @pytest.mark.parametrize(
        "action",
        [
            "update_budget",
            # A verb that is only a prefix of a longer word is still not a
            # verb: `listing` is not `list`, and the trailing-verb reading
            # tokenises on `_` for the same reason.
            "listing_update",
            "getter_config",
        ],
    )
    def test_a_native_write_is_still_a_write(self, action: str) -> None:
        entry = _entry(action=action, reversible_params=None)
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED

    @pytest.mark.parametrize(
        "action",
        [
            # mureo's own convention puts the verb at the END, which the
            # prefix-only rule never matched — so every native read reached
            # here as a write with no hint and was reported as something the
            # operator has to undo by hand.
            "google_ads_campaigns_list",
            "google_ads_budget_get",
            "google_ads_search_terms_report",
            "analysis_anomalies_check",
        ],
    )
    def test_a_native_read_is_read_only(self, action: str) -> None:
        assert plan_rollback(_entry(action=action, reversible_params=None)) is None

    @pytest.mark.parametrize(
        "action",
        [
            # Real names from the installed plugin surface; each a mutation
            # whose segment happens to END in a read verb.
            "yahoo_ads_update_placement_url_list",
            "yahoo_ads_remove_placement_url_list",
            "yahoo_ads_create_placement_url_list",
            "yahoo_ads_display_update_placement_url_list",
            "yahoo_ads_display_remove_placement_url_list",
            "yahoo_ads_display_create_placement_url_list",
            "reporting-delete_report",
            "reporting-create_report",
            "reporting-create_campaign_report",
            "reporting-create_inventory_report",
            "reporting-create_product_report",
            "amc-execute_query",
            "logly_ads_context_merge_adgroup_list",
            # Verbs no installed tool uses today. A hardcoded vocabulary is
            # only as good as the next plugin's naming, so the ones a review
            # found missing are pinned here rather than left to be
            # rediscovered.
            "yahoo_ads_patch_placement_url_list",
            "yahoo_ads_replace_placement_url_list",
            "yahoo_ads_cancel_placement_url_list",
            "yahoo_ads_duplicate_placement_url_list",
            "yahoo_ads_attach_placement_url_list",
            "yahoo_ads_detach_placement_url_list",
            "campaigns-publish_report",
            "campaigns-restore_report",
        ],
    )
    def test_a_write_verb_beats_a_trailing_read_verb(self, action: str) -> None:
        """The guard that makes the trailing reading safe to have at all.

        This surface reports what an operator can be asked to undo, so a
        mutation misread here is a real gap hidden inside a batch that claims
        full coverage. The vocabulary is single-sourced from
        ``mureo.byod._client_common._MUTATION_PREFIXES``, which AGENTS.md
        calls authoritative, so a verb learned there is known here too.

        The guarded reading is confined to THIS surface. The plugin-facing
        callers of ``is_read_only_tool_name`` — the guardrail money scan
        above all — keep the strict verb-first rule, because mureo does not
        name plugin tools and no hardcoded vocabulary can be complete for
        names it does not control.
        """
        entry = _entry(action=action, reversible_params=None)
        plan = plan_rollback(entry)
        assert plan is not None
        assert plan.status == RollbackStatus.NOT_SUPPORTED
