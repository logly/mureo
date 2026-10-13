"""A namespaced built-in variant is classified like the built-in (#837).

A provider that reaches a built-in platform through another credential source
can expose the built-in tool surface again as
``<builtin_platform>_<suffix>_<operation>`` (see ``_mureo-shared`` →
"Namespaced built-in variants"). The learning-period classifier used to stop
at "starts with a built-in prefix but is not an exact built-in name → read",
so every write made through such a variant was classified as a read and never
reached the ``block_learning_resets`` refusal or the post-dispatch notice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.context.models import CampaignSnapshot, PlatformState, StateDocument
from mureo.policy.learning_reset import (
    build_preflight,
    builtin_equivalent,
    classify_change,
    learning_reset_denial,
)
from mureo.policy.learning_rules import LearningState, ResetRisk

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_hints() -> Iterator[None]:
    """Isolate the process-global hint registry without destroying it."""
    from mureo.policy.declarations import _READ_ONLY_HINTS, reset_read_only_hints

    saved = dict(_READ_ONLY_HINTS)
    reset_read_only_hints()
    yield
    reset_read_only_hints()
    _READ_ONLY_HINTS.update(saved)


def _google_state(status: str, campaign_id: str = "C1") -> StateDocument:
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
                        bidding_details={"bidding_strategy_system_status": status},
                    ),
                ),
            )
        },
    )


# ---------------------------------------------------------------------------
# The equivalence itself
# ---------------------------------------------------------------------------


class TestBuiltinEquivalent:
    @pytest.mark.parametrize(
        ("tool", "expected"),
        [
            ("meta_ads_acme_campaigns_update", "meta_ads_campaigns_update"),
            ("meta_ads_acme_campaigns_list", "meta_ads_campaigns_list"),
            ("meta_ads_acme_eu_campaigns_list", "meta_ads_campaigns_list"),
            ("google_ads_acme_budget_update", "google_ads_budget_update"),
            (
                "google_ads_acme_campaigns_update_status",
                "google_ads_campaigns_update_status",
            ),
            ("search_console_acme_sites_list", "search_console_sites_list"),
        ],
    )
    def test_variant_maps_to_its_builtin(self, tool: str, expected: str) -> None:
        assert builtin_equivalent(tool) == expected

    def test_the_longest_operation_wins(self) -> None:
        """``negative_keywords_add`` and ``keywords_add`` are both built-in
        operations; the variant's operation is the longer one."""
        assert (
            builtin_equivalent("google_ads_acme_negative_keywords_add")
            == "google_ads_negative_keywords_add"
        )

    @pytest.mark.parametrize(
        "tool",
        ["google_ads_campaigns_update", "meta_ads_campaigns_list"],
    )
    def test_an_exact_builtin_is_its_own_equivalent(self, tool: str) -> None:
        assert builtin_equivalent(tool) == tool

    @pytest.mark.parametrize(
        "tool",
        [
            "meta_ads_acme_unknown_thing",
            "meta_ads__campaigns_list",
            "acme_ads_x_campaigns_list",
            "mureo_acme_campaigns_list",
            "mureo_strategy_get",
            "campaign_management-update_campaign",
            "",
        ],
    )
    def test_no_builtin_operation_means_no_equivalent(self, tool: str) -> None:
        assert builtin_equivalent(tool) is None


# ---------------------------------------------------------------------------
# Classification follows the built-in
# ---------------------------------------------------------------------------


class TestVariantClassification:
    def test_variant_update_is_a_mutation(self) -> None:
        a = classify_change("meta_ads_acme_campaigns_update", {"campaign_id": "1"})
        assert a.risk is ResetRisk.UNKNOWN
        assert a.platform == "meta_ads"
        assert "Read-only" not in a.detail
        assert "meta_ads_acme_campaigns_update" in a.detail

    def test_variant_list_is_a_read(self) -> None:
        a = classify_change("meta_ads_acme_campaigns_list", {})
        assert a.risk is ResetRisk.NO_RESET
        assert "Read-only" in a.detail

    def test_a_hint_cannot_reclassify_a_variant_of_a_builtin(self) -> None:
        """The variant has the built-in's operation, so the built-in's pinned
        classification stays authoritative, exactly as for the built-in."""
        from mureo.policy.declarations import register_read_only_hint

        register_read_only_hint("meta_ads_acme_campaigns_update", True)
        register_read_only_hint("meta_ads_acme_campaigns_list", False)
        assert (
            classify_change("meta_ads_acme_campaigns_update", {}).risk
            is ResetRisk.UNKNOWN
        )
        assert (
            classify_change("meta_ads_acme_campaigns_list", {}).risk
            is ResetRisk.NO_RESET
        )

    def test_google_variant_budget_update_resets(self) -> None:
        a = classify_change(
            "google_ads_acme_budget_update", {"budget_id": "B", "amount": 1}
        )
        assert a.risk is ResetRisk.RESETS
        assert a.change_class == "budget_change"
        assert a.platform == "google_ads"
        assert "google_ads_acme_budget_update" in a.detail

    def test_google_variant_keys_on_the_same_arguments(self) -> None:
        bid = classify_change(
            "google_ads_acme_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
        )
        rename = classify_change(
            "google_ads_acme_campaigns_update", {"campaign_id": "C1", "name": "N"}
        )
        enable = classify_change(
            "google_ads_acme_campaigns_update_status",
            {"campaign_id": "C1", "status": "ENABLED"},
        )
        pause = classify_change(
            "google_ads_acme_campaigns_update_status",
            {"campaign_id": "C1", "status": "PAUSED"},
        )
        assert bid.risk is ResetRisk.RESETS
        assert bid.change_class == "bidding_strategy_change"
        assert rename.risk is ResetRisk.NO_RESET
        assert enable.risk is ResetRisk.RESETS
        assert enable.change_class == "reactivation"
        assert pause.risk is ResetRisk.NO_RESET

    @pytest.mark.parametrize(
        ("variant", "builtin", "arguments"),
        [
            (
                "google_ads_acme_negative_keywords_add",
                "google_ads_negative_keywords_add",
                {"campaign_id": "C1", "keywords": ["x"]},
            ),
            (
                "google_ads_acme_keywords_add",
                "google_ads_keywords_add",
                {"ad_group_id": "A", "keywords": ["x"]},
            ),
            (
                "google_ads_acme_conversions_update",
                "google_ads_conversions_update",
                {"conversion_action_id": "CA1", "name": "Renamed"},
            ),
            ("meta_ads_acme_ad_sets_update", "meta_ads_ad_sets_update", {}),
            (
                "search_console_acme_sitemaps_submit",
                "search_console_sitemaps_submit",
                {},
            ),
        ],
    )
    def test_variant_verdict_equals_the_builtin_verdict(
        self, variant: str, builtin: str, arguments: dict[str, Any]
    ) -> None:
        got = classify_change(variant, arguments)
        want = classify_change(builtin, arguments)
        assert (got.risk, got.change_class, got.platform) == (
            want.risk,
            want.change_class,
            want.platform,
        )

    def test_variant_reaches_the_incident_refusal(self) -> None:
        pre = build_preflight(
            "google_ads_acme_campaigns_update",
            {"campaign_id": "C1", "bidding_strategy": "TARGET_CPA"},
            _google_state("LEARNING_NEW"),
        )
        assert pre.platform == "google_ads"
        assert pre.campaign_id == "C1"
        assert pre.learning.state is LearningState.LEARNING
        reason = learning_reset_denial(pre, block_all=False, block_during_incident=True)
        assert reason is not None
        assert "google_ads_acme_campaigns_update" in reason


# ---------------------------------------------------------------------------
# No equivalent: the declaration and the name decide, as for any plugin tool
# ---------------------------------------------------------------------------


class TestPrefixedNameWithoutAnEquivalent:
    def test_declared_mutation_is_a_mutation(self) -> None:
        from mureo.policy.declarations import register_read_only_hint

        register_read_only_hint("meta_ads_acme_unknown_thing", False)
        a = classify_change("meta_ads_acme_unknown_thing", {})
        assert a.risk is ResetRisk.UNKNOWN

    def test_declared_read_is_a_read(self) -> None:
        from mureo.policy.declarations import register_read_only_hint

        register_read_only_hint("meta_ads_acme_unknown_thing", True)
        assert (
            classify_change("meta_ads_acme_unknown_thing", {}).risk
            is ResetRisk.NO_RESET
        )

    def test_undeclared_name_falls_back_to_the_name_pattern(self) -> None:
        assert (
            classify_change("meta_ads_acme_unknown_thing", {}).risk is ResetRisk.UNKNOWN
        )
        assert (
            classify_change("meta_ads_acme-list_things", {}).risk is ResetRisk.NO_RESET
        )


# ---------------------------------------------------------------------------
# Unchanged: exact built-ins and mureo's own tools
# ---------------------------------------------------------------------------


class TestUnchanged:
    @pytest.mark.parametrize(
        ("tool", "arguments", "expected"),
        [
            ("google_ads_budget_update", {"budget_id": "B"}, ResetRisk.RESETS),
            ("google_ads_campaigns_list", {}, ResetRisk.NO_RESET),
            ("meta_ads_campaigns_update", {}, ResetRisk.UNKNOWN),
            ("meta_ads_insights_report", {}, ResetRisk.NO_RESET),
            ("search_console_sites_list", {}, ResetRisk.NO_RESET),
        ],
    )
    def test_exact_builtins(
        self, tool: str, arguments: dict[str, Any], expected: ResetRisk
    ) -> None:
        assert classify_change(tool, arguments).risk is expected

    def test_mureo_tools_stay_owned_by_the_builtin_classifier(self) -> None:
        """``mureo_`` names are mureo's own; a declaration does not reach them."""
        from mureo.policy.declarations import register_read_only_hint

        register_read_only_hint("mureo_acme_thing", False)
        assert classify_change("mureo_acme_thing", {}).risk is ResetRisk.NO_RESET
        assert classify_change("mureo_strategy_get", {}).risk is ResetRisk.NO_RESET
