"""Tests for the platform-configured monthly budget reader (issue #656).

The second rung of ``/budget-pacing``'s precedence: where a platform's
campaigns carry a monthly budget of their own, mureo can sum what the
platform is **configured** to spend instead of making an operator type the
figure by hand. These tests pin the three properties that stop that sum
being mistaken for something it is not:

- it is distinguishable from the operator's agreed target — a different
  ``source``, never :data:`~mureo.context.monthly_budget.
  SOURCE_STRATEGY_SECTION`;
- it fires only for a platform that DECLARED the concept, so an absent
  ``monthly_budget`` on a per-day platform is not read as a gap;
- an incomplete or uncollected campaign set is refused rather than summed,
  because a sum of some campaigns is a smaller number and not a smaller
  budget (the #638 rule for stale rollups, applied to a total).

Marks: unit — pure in-memory models, no network and no filesystem writes.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator

import pytest

from mureo.context.models import CampaignSnapshot, PlatformState
from mureo.context.monthly_budget import (
    SOURCE_NOT_SET,
    SOURCE_PLATFORM_CONFIGURED_SUM,
    SOURCE_STRATEGY_SECTION,
)
from mureo.context.platform_monthly_budget import (
    MonthlyBudgetSupport,
    MonthlyBudgetSupportWarning,
    platform_configured_monthly_budget,
    platforms_with_monthly_budget,
    register_monthly_budget_support,
    reset_monthly_budget_support,
    supports_monthly_budget,
)
from mureo.policy.learning_rules import Evidence

pytestmark = pytest.mark.unit

_EVIDENCE = Evidence(
    source="https://example.invalid/acme/docs/campaigns",
    retrieved="2026-08-19",
    quote="A campaign body accepts monthly_budget alongside daily_budget.",
)


def _support(**overrides: object) -> MonthlyBudgetSupport:
    fields: dict[str, object] = {"platform": "acme_ads", "evidence": _EVIDENCE}
    fields.update(overrides)
    return MonthlyBudgetSupport(**fields)  # type: ignore[arg-type]


def _campaign(
    campaign_id: str,
    *,
    monthly_budget: object = None,
    daily_budget: float | None = None,
) -> CampaignSnapshot:
    return CampaignSnapshot(
        campaign_id=campaign_id,
        campaign_name=f"Campaign {campaign_id}",
        status="ENABLED",
        daily_budget=daily_budget,
        monthly_budget=monthly_budget,  # type: ignore[arg-type]
    )


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    reset_monthly_budget_support()
    yield
    reset_monthly_budget_support()


# ---------------------------------------------------------------------------
# The declaration registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_core_declares_no_platform(self) -> None:
        """Core knows of no monthly-budget platform, and invents none.

        Which platforms have the concept is the plugin's fact to state, the
        same honesty rule ``learning_rules`` and ``platform_model`` apply.
        """
        assert platforms_with_monthly_budget() == ()
        assert not supports_monthly_budget("acme_ads")
        assert not supports_monthly_budget("google_ads")

    def test_third_party_can_declare_and_be_read_back(self) -> None:
        register_monthly_budget_support(_support())
        assert platforms_with_monthly_budget() == ("acme_ads",)
        assert supports_monthly_budget("acme_ads")

    def test_second_declaration_for_a_taken_platform_is_dropped(self) -> None:
        """First wins, as for provider names and platform models."""
        register_monthly_budget_support(_support())
        with pytest.warns(MonthlyBudgetSupportWarning):
            register_monthly_budget_support(
                _support(
                    evidence=Evidence(
                        source="https://example.invalid/other",
                        retrieved="2026-08-19",
                        quote="Something else entirely.",
                    )
                )
            )
        assert platforms_with_monthly_budget() == ("acme_ads",)

    def test_re_registering_the_same_platform_does_not_duplicate_it(self) -> None:
        register_monthly_budget_support(_support())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MonthlyBudgetSupportWarning)
            register_monthly_budget_support(_support())
        assert platforms_with_monthly_budget() == ("acme_ads",)

    @pytest.mark.parametrize("platform", ["", "   "])
    def test_a_nameless_platform_is_refused(self, platform: str) -> None:
        with pytest.raises(ValueError):
            register_monthly_budget_support(_support(platform=platform))

    def test_a_declaration_without_evidence_is_refused(self) -> None:
        """A claim about a platform's API needs the source it rests on."""
        with pytest.raises(ValueError):
            register_monthly_budget_support(_support(evidence=None))

    @pytest.mark.parametrize(
        "evidence",
        [
            Evidence(source="", retrieved="2026-08-19", quote="q"),
            Evidence(source="https://x.invalid", retrieved="", quote="q"),
            Evidence(source="https://x.invalid", retrieved="2026-08-19", quote=""),
            Evidence(source="https://x.invalid", retrieved="yesterday", quote="q"),
        ],
    )
    def test_incomplete_evidence_is_refused(self, evidence: Evidence) -> None:
        with pytest.raises(ValueError):
            register_monthly_budget_support(_support(evidence=evidence))


# ---------------------------------------------------------------------------
# Summing a complete set
# ---------------------------------------------------------------------------


class TestCompleteSet:
    def test_sums_the_campaigns_of_a_declaring_platform(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState(
                    account_id="123",
                    campaigns=(
                        _campaign("1", monthly_budget=120000),
                        _campaign("2", monthly_budget=80000),
                    ),
                )
            }
        )
        assert budget.total == 200000
        assert budget.source == SOURCE_PLATFORM_CONFIGURED_SUM
        assert budget.is_set
        assert budget.is_platform_configured
        assert budget.incomplete_platforms == ()

    def test_the_sum_is_not_the_operators_agreed_target(self) -> None:
        """Rung 2 must never present itself as rung 1 (#656)."""
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"acme_ads": PlatformState("123", (_campaign("1", monthly_budget=1),))}
        )
        assert budget.source != SOURCE_STRATEGY_SECTION
        assert not budget.is_derived

    def test_per_platform_carries_each_platforms_subtotal(self) -> None:
        register_monthly_budget_support(_support())
        register_monthly_budget_support(_support(platform="beta_ads"))
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState("123", (_campaign("1", monthly_budget=100),)),
                "beta_ads": PlatformState(
                    "456",
                    (
                        _campaign("2", monthly_budget=20),
                        _campaign("3", monthly_budget=30),
                    ),
                ),
            }
        )
        assert budget.total == 150
        assert dict(budget.per_platform) == {"acme_ads": 100.0, "beta_ads": 50.0}

    def test_per_platform_mapping_is_read_only(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"acme_ads": PlatformState("123", (_campaign("1", monthly_budget=100),))}
        )
        with pytest.raises(TypeError):
            budget.per_platform["acme_ads"] = 1.0  # type: ignore[index]

    def test_a_configured_zero_is_a_real_figure(self) -> None:
        """Every campaign set to spend nothing is a readable, complete set."""
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"acme_ads": PlatformState("123", (_campaign("1", monthly_budget=0),))}
        )
        assert budget.total == 0.0
        assert budget.source == SOURCE_PLATFORM_CONFIGURED_SUM

    def test_a_float_figure_is_read(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"acme_ads": PlatformState("123", (_campaign("1", monthly_budget=1200.5),))}
        )
        assert budget.total == 1200.5


# ---------------------------------------------------------------------------
# Platforms that never had the concept
# ---------------------------------------------------------------------------


class TestUndeclaredPlatforms:
    def test_an_undeclared_platform_does_not_fire_rung_two(self) -> None:
        """Google/Meta campaigns are configured per day; there is nothing to sum."""
        budget = platform_configured_monthly_budget(
            {
                "google_ads": PlatformState(
                    "123", (_campaign("1", daily_budget=10000),)
                ),
                "meta_ads": PlatformState("456", (_campaign("2", daily_budget=5000),)),
            }
        )
        assert not budget.is_set
        assert budget.total is None
        assert budget.source == SOURCE_NOT_SET
        assert budget.incomplete_platforms == ()

    def test_an_undeclared_platform_is_not_counted_as_a_gap(self) -> None:
        """A per-day platform's absent monthly figure is not a missing one.

        This is what the declaration is FOR: without it, "this platform has
        no such field" and "this campaign's field was not synced" are the
        same absence, and every mixed workspace would look incomplete.
        """
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState("123", (_campaign("1", monthly_budget=100),)),
                "google_ads": PlatformState(
                    "456", (_campaign("2", daily_budget=10000),)
                ),
            }
        )
        assert budget.total == 100
        assert budget.source == SOURCE_PLATFORM_CONFIGURED_SUM
        assert budget.incomplete_platforms == ()

    def test_an_undeclared_platforms_monthly_figure_is_ignored(self) -> None:
        """Declaring the concept is the platform's own act, not a field's."""
        budget = platform_configured_monthly_budget(
            {"google_ads": PlatformState("123", (_campaign("1", monthly_budget=999),))}
        )
        assert not budget.is_set
        assert budget.total is None

    @pytest.mark.parametrize("platforms", [None, {}])
    def test_no_platforms_at_all_is_not_set(self, platforms: object) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(platforms)  # type: ignore[arg-type]
        assert not budget.is_set
        assert budget.incomplete_platforms == ()

    def test_a_declared_platform_absent_from_the_document_says_nothing(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"google_ads": PlatformState("123", (_campaign("1", daily_budget=100),))}
        )
        assert not budget.is_set
        assert budget.incomplete_platforms == ()


# ---------------------------------------------------------------------------
# Incomplete and uncollected sets — the #638 rule applied to a total
# ---------------------------------------------------------------------------


class TestIncompleteSetIsRefused:
    def test_a_campaign_without_a_figure_makes_the_set_unusable(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState(
                    "123",
                    (
                        _campaign("1", monthly_budget=120000),
                        _campaign("2"),  # never synced a monthly figure
                    ),
                )
            }
        )
        assert budget.total is None
        assert not budget.is_set
        assert budget.incomplete_platforms == ("acme_ads",)

    def test_the_partial_sum_is_never_the_answer(self) -> None:
        """Three of five campaigns is a smaller number, not a smaller budget."""
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState(
                    "123",
                    (
                        _campaign("1", monthly_budget=100),
                        _campaign("2", monthly_budget=100),
                        _campaign("3", monthly_budget=100),
                        _campaign("4"),
                        _campaign("5"),
                    ),
                )
            }
        )
        assert budget.total != 300
        assert budget.total is None
        assert dict(budget.per_platform) == {}

    @pytest.mark.parametrize(
        "value", [-1, "oops", "", "120000", float("nan"), float("inf"), True, [100]]
    )
    def test_an_unreadable_figure_makes_the_set_unusable(self, value: object) -> None:
        """STATE.json's schema says number: anything else is a gap, not a figure."""
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState(
                    "123",
                    (
                        _campaign("1", monthly_budget=100),
                        _campaign("2", monthly_budget=value),
                    ),
                )
            }
        )
        assert budget.total is None
        assert budget.incomplete_platforms == ("acme_ads",)

    def test_an_uncollected_platform_makes_the_set_unusable(self) -> None:
        """#638: mureo knows this platform did not refresh. It says so."""
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState(
                    "123",
                    (_campaign("1", monthly_budget=100),),
                    not_collected={
                        "attempted_at": "2026-08-19T09:00:00+09:00",
                        "reason": "auth expired",
                    },
                )
            }
        )
        assert budget.total is None
        assert budget.incomplete_platforms == ("acme_ads",)

    def test_a_platform_holding_no_campaigns_is_unusable_not_zero(self) -> None:
        register_monthly_budget_support(_support())
        budget = platform_configured_monthly_budget(
            {"acme_ads": PlatformState("123", ())}
        )
        assert budget.total is None
        assert budget.total != 0
        assert budget.incomplete_platforms == ("acme_ads",)

    def test_one_bad_platform_withholds_the_whole_sum(self) -> None:
        """A cross-platform total that silently drops a platform is the defect."""
        register_monthly_budget_support(_support())
        register_monthly_budget_support(_support(platform="beta_ads"))
        budget = platform_configured_monthly_budget(
            {
                "acme_ads": PlatformState("123", (_campaign("1", monthly_budget=100),)),
                "beta_ads": PlatformState("456", (_campaign("2"),)),
            }
        )
        assert budget.total is None
        assert budget.incomplete_platforms == ("beta_ads",)

    def test_every_unusable_platform_is_named_in_order(self) -> None:
        register_monthly_budget_support(_support())
        register_monthly_budget_support(_support(platform="beta_ads"))
        budget = platform_configured_monthly_budget(
            {
                "beta_ads": PlatformState("456", ()),
                "acme_ads": PlatformState("123", (_campaign("1"),)),
            }
        )
        assert budget.incomplete_platforms == ("acme_ads", "beta_ads")
