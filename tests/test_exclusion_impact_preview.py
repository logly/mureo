"""Delivery-impact preview before bulk exclusions / blocks (#547).

The incident this exists for: placement exclusions tightened incrementally
over two weeks, then one larger pass, and delivery went to zero for a week.
The direction was right; the *magnitude* was never shown at the moment of
the decision.

So these tests pin the four properties that decide whether the feature
actually prevents that, rather than the shape of the code:

1. The share of the recent window's delivery attributable to the entities
   being excluded is **computed and surfaced** at the moment of the write.
2. A threshold written in ``## Guardrails`` in STRATEGY.md **actually
   blocks** the call — end to end through ``handle_call_tool``, before any
   mutation reaches the platform.
3. A small exclusion is **not** warned about and **not** blocked. A check
   that fires on everything gets switched off.
4. A surface whose delivery mureo cannot attribute reports **unknown** —
   never a silent "no impact".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mureo.analysis.exclusion_impact import (
    COVERAGE_MEASURED,
    COVERAGE_PARTIAL,
    COVERAGE_UNKNOWN,
    DEFAULT_WINDOW_DAYS,
    DeliveryRecord,
    ExclusionTarget,
    estimate_exclusion_impact,
    evaluate_exclusion_impact,
    exclusion_impact_rules,
    unevaluated_rules,
)
from mureo.policy.strategy_gate import Guardrails, guardrails_from_strategy_text

GOOGLE_ADD = "google_ads_negative_placements_add"
GOOGLE_NEG_KW = "google_ads_negative_keywords_add"
META_SET = "meta_ads_excluded_placements_set"

_WEBSITE = "website"
_APP = "mobile_application"
_APP_CATEGORY = "mobile_app_category"
_SEARCH_TERM = "search_term"

_PLACEMENT_TYPES = frozenset({_WEBSITE, _APP})


def _rec(entity: str, impressions: float, **kw: Any) -> DeliveryRecord:
    return DeliveryRecord(
        entity=entity,
        entity_type=kw.pop("entity_type", _WEBSITE),
        impressions=impressions,
        clicks=kw.pop("clicks", 0.0),
        cost=kw.pop("cost", 0.0),
        conversions=kw.pop("conversions", 0.0),
    )


def _site(value: str) -> ExclusionTarget:
    return ExclusionTarget(value=value, entity_type=_WEBSITE)


# ---------------------------------------------------------------------------
# 1. The share is computed and surfaced
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShareIsComputed:
    def test_dominant_entity_share_is_reported(self) -> None:
        """Excluding what carried 94% of the window's impressions says 94%."""
        records = [
            _rec("bigsite.com", 9400, clicks=470, cost=94000, conversions=47),
            _rec("small.example", 600, clicks=30, cost=6000, conversions=3),
        ]
        impact = estimate_exclusion_impact(
            targets=[_site("bigsite.com")],
            records=records,
            attributable_types=_PLACEMENT_TYPES,
            basis="google_ads_group_placement_view",
            window_days=30,
        )
        assert impact.coverage == COVERAGE_MEASURED
        assert impact.share_pct("impressions") == pytest.approx(94.0)
        assert impact.share_pct("clicks") == pytest.approx(94.0)
        assert impact.share_pct("cost") == pytest.approx(94.0)
        assert impact.share_pct("conversions") == pytest.approx(94.0)
        assert "bigsite.com" in impact.matched

    def test_subdomains_of_an_excluded_domain_count(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("example.com")],
            records=[
                _rec("news.example.com", 700),
                _rec("example.com", 200),
                _rec("notexample.com", 100),
            ],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.share_pct("impressions") == pytest.approx(90.0)

    def test_excluding_a_subdomain_does_not_claim_the_parent(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("news.example.com")],
            records=[_rec("news.example.com", 100), _rec("example.com", 900)],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.share_pct("impressions") == pytest.approx(10.0)

    def test_url_forms_normalize_to_the_same_host(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("https://WWW.Example.com/section?a=1")],
            records=[_rec("example.com", 500), _rec("other.jp", 500)],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.share_pct("impressions") == pytest.approx(50.0)

    def test_mobile_app_placement_prefix_normalizes(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[ExclusionTarget("1-com.example.app", _APP)],
            records=[
                _rec("mobileapp::1-com.example.app", 800, entity_type=_APP),
                _rec("mobileapp::2-999", 200, entity_type=_APP),
            ],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.share_pct("impressions") == pytest.approx(80.0)

    def test_negative_keyword_match_types(self) -> None:
        records = [
            DeliveryRecord("cheap running shoes", _SEARCH_TERM, impressions=500),
            DeliveryRecord("running shoes cheap", _SEARCH_TERM, impressions=300),
            DeliveryRecord("running blue shoes", _SEARCH_TERM, impressions=200),
        ]
        common = {
            "records": records,
            "attributable_types": frozenset({_SEARCH_TERM}),
            "basis": "google_ads_search_term_view",
            "window_days": 30,
        }
        exact = estimate_exclusion_impact(
            targets=[ExclusionTarget("cheap running shoes", _SEARCH_TERM, "EXACT")],
            **common,
        )
        phrase = estimate_exclusion_impact(
            targets=[ExclusionTarget("running shoes", _SEARCH_TERM, "PHRASE")],
            **common,
        )
        broad = estimate_exclusion_impact(
            targets=[ExclusionTarget("blue shoes", _SEARCH_TERM, "BROAD")],
            **common,
        )
        # EXACT is the whole term, so only the first row.
        assert exact.share_pct("impressions") == pytest.approx(50.0)
        # "running shoes" is contiguous in rows 1 and 2, split in row 3.
        assert phrase.share_pct("impressions") == pytest.approx(80.0)
        # Both tokens present in row 3 only, order-free.
        assert broad.share_pct("impressions") == pytest.approx(20.0)

    def test_zero_delivery_is_not_reported_as_zero_percent(self) -> None:
        """An empty window is 'no share to compute', not 'no impact'."""
        impact = estimate_exclusion_impact(
            targets=[_site("example.com")],
            records=[],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.coverage == COVERAGE_MEASURED
        assert impact.share_pct("impressions") is None
        assert impact.as_dict()["incremental"]["impressions"]["share_pct"] is None


# ---------------------------------------------------------------------------
# 2. A `## Guardrails` threshold blocks
# ---------------------------------------------------------------------------


_STRATEGY_WITH_CAP = """# Strategy

## Guardrails

- max_delivery_share_removed_pct: 25
- exclusion_impact_window_days: 30
"""


@pytest.mark.unit
class TestGuardrailParsing:
    def test_guardrail_keys_parse_from_strategy_text(self) -> None:
        rails = guardrails_from_strategy_text(_STRATEGY_WITH_CAP)
        assert rails.max_delivery_share_removed_pct == 25
        assert rails.exclusion_impact_window_days == 30
        rules = exclusion_impact_rules(rails)
        assert rules.enabled() is True
        assert rules.window_days == 30
        assert rules.metrics == ("impressions",)

    def test_defaults_are_not_hardcoded_at_the_call_site(self) -> None:
        rules = exclusion_impact_rules(Guardrails(max_delivery_share_removed_pct=10.0))
        assert rules.window_days == DEFAULT_WINDOW_DAYS
        assert rules.metrics == ("impressions",)

    def test_metrics_and_block_without_data_parse(self) -> None:
        rails = guardrails_from_strategy_text(
            "## Guardrails\n\n"
            "- max_delivery_share_removed_pct: 40\n"
            "- exclusion_impact_metrics: impressions, cost\n"
            "- block_exclusions_without_impact_data: true\n"
        )
        rules = exclusion_impact_rules(rails)
        assert rules.metrics == ("impressions", "cost")
        assert rules.block_without_data is True

    def test_no_exclusion_rule_written_means_disabled(self) -> None:
        rules = exclusion_impact_rules(guardrails_from_strategy_text("# Strategy\n"))
        assert rules.enabled() is False


@pytest.mark.unit
class TestEvaluationBlocks:
    def _impact(self, share: float) -> Any:
        return estimate_exclusion_impact(
            targets=[_site("big.example")],
            records=[
                _rec("big.example", share),
                _rec("rest.example", 100 - share),
            ],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )

    def test_over_threshold_produces_a_block_reason(self) -> None:
        rules = exclusion_impact_rules(Guardrails(max_delivery_share_removed_pct=25.0))
        reason = evaluate_exclusion_impact(self._impact(94), rules)
        assert reason is not None
        assert "94" in reason
        assert "max_delivery_share_removed_pct" in reason

    def test_under_threshold_does_not_block(self) -> None:
        rules = exclusion_impact_rules(Guardrails(max_delivery_share_removed_pct=25.0))
        assert evaluate_exclusion_impact(self._impact(3), rules) is None

    def test_a_metric_not_listed_cannot_block(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("big.example")],
            records=[
                _rec("big.example", 1, cost=9000),
                _rec("rest.example", 999, cost=1000),
            ],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        impressions_only = exclusion_impact_rules(
            Guardrails(max_delivery_share_removed_pct=25.0)
        )
        with_cost = exclusion_impact_rules(
            Guardrails(
                max_delivery_share_removed_pct=25.0,
                exclusion_impact_metrics=("impressions", "cost"),
            )
        )
        assert evaluate_exclusion_impact(impact, impressions_only) is None
        assert evaluate_exclusion_impact(impact, with_cost) is not None


# ---------------------------------------------------------------------------
# 3. Cumulative tightening
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCumulativeTightening:
    def test_standing_exclusions_are_added_to_the_new_batch(self) -> None:
        """Two weeks of small passes plus one more must show the total."""
        records = [_rec(f"site{i}.example", 100) for i in range(10)]
        impact = estimate_exclusion_impact(
            targets=[_site("site9.example")],
            records=records,
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
            standing=[_site(f"site{i}.example") for i in range(8)],
        )
        assert impact.share_pct("impressions") == pytest.approx(10.0)
        assert impact.cumulative_share_pct("impressions") == pytest.approx(90.0)

    def test_cumulative_cap_blocks_when_incremental_does_not(self) -> None:
        records = [_rec(f"site{i}.example", 100) for i in range(10)]
        impact = estimate_exclusion_impact(
            targets=[_site("site9.example")],
            records=records,
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
            standing=[_site(f"site{i}.example") for i in range(8)],
        )
        rules = exclusion_impact_rules(
            Guardrails(
                max_delivery_share_removed_pct=25.0,
                max_cumulative_delivery_share_removed_pct=60.0,
            )
        )
        reason = evaluate_exclusion_impact(impact, rules)
        assert reason is not None
        assert "max_cumulative_delivery_share_removed_pct" in reason

    def test_unavailable_standing_list_is_not_reported_as_zero(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("a.example")],
            records=[_rec("a.example", 10), _rec("b.example", 90)],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
            standing=None,
            cumulative_reason="mureo cannot list ad-group-level standing exclusions",
        )
        assert impact.cumulative is None
        assert impact.cumulative_share_pct("impressions") is None
        assert impact.as_dict()["cumulative"] is None
        assert "ad-group-level" in impact.as_dict()["cumulative_reason"]


# ---------------------------------------------------------------------------
# 4. Unknown coverage is never a silent pass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUnknownCoverage:
    def test_no_records_is_unknown_not_zero(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[ExclusionTarget("household", "publisher_category")],
            records=None,
            attributable_types=frozenset(),
            basis="meta_ads_ad_set_targeting",
            window_days=30,
            coverage_reason=(
                "Meta insights breakdowns do not attribute delivery to "
                "publisher categories"
            ),
        )
        assert impact.coverage == COVERAGE_UNKNOWN
        assert impact.incremental is None
        assert impact.share_pct("impressions") is None
        payload = impact.as_dict()
        assert payload["coverage"] == COVERAGE_UNKNOWN
        assert payload["incremental"] is None
        assert "publisher categories" in payload["coverage_reason"]

    def test_block_without_data_refuses_an_unknown_batch(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[ExclusionTarget("household", "publisher_category")],
            records=None,
            attributable_types=frozenset(),
            basis="meta_ads_ad_set_targeting",
            window_days=30,
            coverage_reason="no attributable breakdown",
        )
        permissive = exclusion_impact_rules(
            Guardrails(max_delivery_share_removed_pct=25.0)
        )
        strict = exclusion_impact_rules(
            Guardrails(
                max_delivery_share_removed_pct=25.0,
                block_exclusions_without_impact_data=True,
            )
        )
        assert evaluate_exclusion_impact(impact, permissive) is None
        reason = evaluate_exclusion_impact(impact, strict)
        assert reason is not None
        assert "block_exclusions_without_impact_data" in reason

    def test_a_target_type_the_basis_cannot_attribute_is_partial(self) -> None:
        impact = estimate_exclusion_impact(
            targets=[_site("a.example"), ExclusionTarget("60000", _APP_CATEGORY)],
            records=[_rec("a.example", 10), _rec("b.example", 90)],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.coverage == COVERAGE_PARTIAL
        assert impact.unattributable_targets == ("60000",)
        assert impact.share_pct("impressions") == pytest.approx(10.0)

    def test_a_target_that_simply_never_served_is_still_measured(self) -> None:
        """Not the same as unattributable — it served nothing, and we know it."""
        impact = estimate_exclusion_impact(
            targets=[_site("never-served.example")],
            records=[_rec("a.example", 100)],
            attributable_types=_PLACEMENT_TYPES,
            basis="b",
            window_days=30,
        )
        assert impact.coverage == COVERAGE_MEASURED
        assert impact.share_pct("impressions") == pytest.approx(0.0)
        assert impact.unmatched_targets == ("never-served.example",)


# ---------------------------------------------------------------------------
# Surface registry — what mureo knows how to check
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSurfaceRegistry:
    def test_the_mureo_owned_exclusion_tools_are_registered(self) -> None:
        from mureo.mcp.exclusion_sources import register_builtin_exclusion_surfaces

        register_builtin_exclusion_surfaces()
        from mureo.analysis.exclusion_impact import exclusion_surface_for

        for tool in (
            GOOGLE_ADD,
            GOOGLE_NEG_KW,
            "google_ads_negative_keywords_add_to_ad_group",
            META_SET,
        ):
            assert exclusion_surface_for(tool) is not None, tool

    def test_a_non_exclusion_tool_has_no_surface(self) -> None:
        from mureo.analysis.exclusion_impact import exclusion_surface_for

        assert exclusion_surface_for("google_ads_budget_update") is None

    def test_a_plugin_can_register_its_own_surface(self) -> None:
        from mureo.analysis.exclusion_impact import (
            DeliverySample,
            ExclusionSurface,
            exclusion_surface_for,
            register_exclusion_surface,
            reset_exclusion_surfaces,
        )

        async def _delivery(args: dict[str, Any], days: int) -> DeliverySample:
            return DeliverySample(records=None, basis="x", reason="no supply view")

        try:
            register_exclusion_surface(
                ExclusionSurface(
                    tool="logly_ads_block_adspots",
                    platform="logly",
                    targets=lambda args: (
                        ExclusionTarget(str(a), "adspot")
                        for a in args.get("adspots", [])
                    ),
                    delivery=_delivery,
                )
            )
            assert exclusion_surface_for("logly_ads_block_adspots") is not None
        finally:
            reset_exclusion_surfaces()
            register_builtin = __import__(
                "mureo.mcp.exclusion_sources", fromlist=["x"]
            ).register_builtin_exclusion_surfaces
            register_builtin()


# ---------------------------------------------------------------------------
# End to end: the guardrail refuses the call before the mutation
# ---------------------------------------------------------------------------


class _FakeGoogleClient:
    def __init__(
        self,
        placements: list[dict[str, Any]],
        standing: list[dict[str, Any]] | None = None,
    ) -> None:
        self._placements = placements
        self._standing = standing or []
        self.mutated = False

    async def get_placement_performance(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._placements

    async def list_negative_placements(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._standing

    async def add_negative_placements(self, params: dict[str, Any]) -> dict[str, Any]:
        self.mutated = True
        return {"level": "campaign", "campaign_id": "100", "count": 1, "created": []}


def _activate_workspace(
    monkeypatch: pytest.MonkeyPatch, directory: Path, body: str
) -> None:
    """Make ``directory`` the workspace the guardrail loader reads.

    ``RuntimeContext`` is a process singleton bound to the cwd of its first
    resolution, so a bare ``chdir`` would leave the gate reading the repo's
    own STRATEGY.md. Resetting it is the documented way to swap it.
    """
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context

    (directory / "STRATEGY.md").write_text(body, encoding="utf-8")
    monkeypatch.chdir(directory)
    reset_runtime_context()
    sg._cache.clear()


@pytest.fixture(autouse=True)
def _restore_workspace() -> Any:
    """Undo the singleton swap so a later test file is unaffected."""
    yield
    import mureo.policy.strategy_gate as sg
    from mureo.core.runtime_context import reset_runtime_context

    reset_runtime_context()
    sg._cache.clear()


@pytest.mark.asyncio
class TestDispatcherEnforcement:
    async def _call(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        strategy: str,
        placements: list[dict[str, Any]],
        excluded: str = "bigsite.com",
    ) -> tuple[Any, _FakeGoogleClient]:
        import mureo.mcp.exclusion_sources as sources
        from mureo.mcp.server import handle_call_tool

        _activate_workspace(monkeypatch, tmp_path, strategy)
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        client = _FakeGoogleClient(placements)

        async def _fake_client(args: dict[str, Any]) -> Any:
            return client

        monkeypatch.setattr(sources, "google_ads_client", _fake_client)
        monkeypatch.setattr(
            "mureo.mcp._handlers_google_ads._get_client", lambda args: client
        )
        result = await handle_call_tool(
            GOOGLE_ADD,
            {
                "customer_id": "1234567890",
                "campaign_id": "100",
                "placements": [{"type": "website", "value": excluded}],
            },
        )
        return result, client

    async def test_over_cap_exclusion_is_refused_before_the_mutation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        result, client = await self._call(
            monkeypatch,
            tmp_path,
            strategy=_STRATEGY_WITH_CAP,
            placements=[
                {"placement": "bigsite.com", "type": "website", "impressions": 9400},
                {"placement": "small.example", "type": "website", "impressions": 600},
            ],
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert "94" in text
        assert "refused" in text.lower()
        assert client.mutated is False

    async def test_small_exclusion_is_not_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        result, client = await self._call(
            monkeypatch,
            tmp_path,
            strategy=_STRATEGY_WITH_CAP,
            placements=[
                {"placement": "bigsite.com", "type": "website", "impressions": 30},
                {"placement": "small.example", "type": "website", "impressions": 9970},
            ],
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert "refused" not in text.lower()
        assert client.mutated is True

    async def test_an_allowed_batch_still_reports_what_it_removed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The measured size is recorded so the NEXT pass is not made blind."""
        result, client = await self._call(
            monkeypatch,
            tmp_path,
            strategy=_STRATEGY_WITH_CAP,
            placements=[
                {"placement": "bigsite.com", "type": "website", "impressions": 30},
                {"placement": "small.example", "type": "website", "impressions": 9970},
            ],
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert client.mutated is True
        assert "[mureo] Delivery impact" in text
        assert "impressions 0.3%" in text

    async def test_no_guardrail_written_reaches_no_report_api(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Fail-open: with no rule written, the pre-dispatch check does no I/O."""
        import mureo.mcp.exclusion_sources as sources
        from mureo.mcp.server import handle_call_tool

        _activate_workspace(monkeypatch, tmp_path, "# Strategy\n\n## Goals\n\n- grow\n")
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        calls: list[str] = []

        async def _boom(args: dict[str, Any]) -> Any:
            calls.append("client")
            raise AssertionError("no client must be built with no guardrail written")

        client = _FakeGoogleClient([])
        monkeypatch.setattr(sources, "google_ads_client", _boom)
        monkeypatch.setattr(
            "mureo.mcp._handlers_google_ads._get_client", lambda args: client
        )
        await handle_call_tool(
            GOOGLE_ADD,
            {
                "customer_id": "1234567890",
                "campaign_id": "100",
                "placements": [{"type": "website", "value": "x.example"}],
            },
        )
        assert calls == []
        assert client.mutated is True

    async def test_a_read_failure_is_unknown_and_still_dispatches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A broken report must not take the exclusion tools offline."""
        import mureo.mcp.exclusion_sources as sources
        from mureo.mcp.server import handle_call_tool

        _activate_workspace(monkeypatch, tmp_path, _STRATEGY_WITH_CAP)
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        class _Broken(_FakeGoogleClient):
            async def get_placement_performance(
                self, **kwargs: Any
            ) -> list[dict[str, Any]]:
                raise RuntimeError("report unavailable")

        client = _Broken([])

        async def _fake_client(args: dict[str, Any]) -> Any:
            return client

        monkeypatch.setattr(sources, "google_ads_client", _fake_client)
        monkeypatch.setattr(
            "mureo.mcp._handlers_google_ads._get_client", lambda args: client
        )
        result = await handle_call_tool(
            GOOGLE_ADD,
            {
                "customer_id": "1234567890",
                "campaign_id": "100",
                "placements": [{"type": "website", "value": "x.example"}],
            },
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert client.mutated is True
        assert "Coverage: unknown" in text
        assert "WITHOUT a measured size" in text

    async def test_block_without_impact_data_refuses_the_meta_surface(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Meta's facets are unattributable; the opt-in rule refuses them."""
        from mureo.mcp.server import handle_call_tool

        _activate_workspace(
            monkeypatch,
            tmp_path,
            "## Guardrails\n\n- block_exclusions_without_impact_data: true\n",
        )
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        mutated: list[str] = []

        class _FakeMetaClient:
            async def set_excluded_placements(
                self, ad_set_id: str, **facets: Any
            ) -> dict[str, Any]:
                mutated.append(ad_set_id)
                return {"ad_set_id": ad_set_id}

        async def _client(args: dict[str, Any]) -> Any:
            return _FakeMetaClient()

        monkeypatch.setattr("mureo.mcp._handlers_meta_ads._get_client", _client)
        result = await handle_call_tool(
            META_SET,
            {
                "ad_set_id": "1",
                "excluded_publisher_categories": ["household"],
            },
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert mutated == []
        assert "block_exclusions_without_impact_data" in text
        assert "publisher categories" in text


# ---------------------------------------------------------------------------
# The read-only preview tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPreviewTool:
    async def test_tool_is_registered(self) -> None:
        from mureo.mcp.tools_analysis import TOOLS

        assert "analysis_exclusion_impact_preview" in {t.name for t in TOOLS}

    async def test_preview_over_supplied_records_needs_no_platform(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        result = await handle_tool(
            "analysis_exclusion_impact_preview",
            {
                "excluded_entities": [
                    {"value": "adspot-1", "entity_type": "adspot"},
                ],
                "delivery_records": [
                    {"entity": "adspot-1", "entity_type": "adspot", "impressions": 800},
                    {"entity": "adspot-2", "entity_type": "adspot", "impressions": 200},
                ],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["impact"]["coverage"] == COVERAGE_MEASURED
        assert payload["impact"]["incremental"]["impressions"][
            "share_pct"
        ] == pytest.approx(80.0)

    async def test_would_block_agrees_with_the_enforcement(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        _activate_workspace(monkeypatch, tmp_path, _STRATEGY_WITH_CAP)
        result = await handle_tool(
            "analysis_exclusion_impact_preview",
            {
                "excluded_entities": [{"value": "a.example", "entity_type": "website"}],
                "delivery_records": [
                    {
                        "entity": "a.example",
                        "entity_type": "website",
                        "impressions": 940,
                    },
                    {
                        "entity": "b.example",
                        "entity_type": "website",
                        "impressions": 60,
                    },
                ],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["would_block"] is True
        assert "max_delivery_share_removed_pct" in payload["block_reason"]

    async def test_unattributable_surface_reports_unknown(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        result = await handle_tool(
            "analysis_exclusion_impact_preview",
            {
                "tool": META_SET,
                "arguments": {
                    "ad_set_id": "1",
                    "excluded_publisher_categories": ["household"],
                },
            },
        )
        payload = json.loads(result[0].text)
        assert payload["impact"]["coverage"] == COVERAGE_UNKNOWN
        assert payload["impact"]["coverage_reason"]
        assert payload["impact"]["incremental"] is None


# ---------------------------------------------------------------------------
# A rule that cannot fire must say so at the moment it cannot fire
# ---------------------------------------------------------------------------


_STRATEGY_CUMULATIVE_ONLY = """# Strategy

## Guardrails

- max_cumulative_delivery_share_removed_pct: 60
"""


def _impact_without_standing() -> Any:
    return estimate_exclusion_impact(
        targets=[_site("a.example")],
        records=[_rec("a.example", 10), _rec("b.example", 90)],
        attributable_types=_PLACEMENT_TYPES,
        basis="b",
        window_days=30,
        standing=None,
        cumulative_reason="mureo cannot list ad-group-level standing exclusions",
    )


@pytest.mark.unit
class TestInertRulesAreNamed:
    def test_a_cumulative_only_rule_is_reported_as_unevaluated(self) -> None:
        rules = exclusion_impact_rules(
            Guardrails(max_cumulative_delivery_share_removed_pct=60.0)
        )
        impact = _impact_without_standing()
        # It genuinely enforces nothing here — that is the defect being named.
        assert evaluate_exclusion_impact(impact, rules) is None
        inert = unevaluated_rules(impact, rules)
        assert [r.key for r in inert] == ["max_cumulative_delivery_share_removed_pct"]
        assert "ad-group-level" in inert[0].reason

    def test_an_evaluable_rule_is_not_reported(self) -> None:
        rules = exclusion_impact_rules(Guardrails(max_delivery_share_removed_pct=25.0))
        impact = _impact_without_standing()
        assert unevaluated_rules(impact, rules) == ()

    def test_an_unmeasurable_batch_makes_the_incremental_rule_inert(self) -> None:
        rules = exclusion_impact_rules(Guardrails(max_delivery_share_removed_pct=25.0))
        impact = estimate_exclusion_impact(
            targets=[ExclusionTarget("household", "publisher_category")],
            records=None,
            attributable_types=frozenset(),
            basis="meta_ads_ad_set_targeting",
            window_days=30,
            coverage_reason="no attributable breakdown",
        )
        assert [r.key for r in unevaluated_rules(impact, rules)] == [
            "max_delivery_share_removed_pct"
        ]


@pytest.mark.asyncio
class TestInertRuleSurfacing:
    async def test_the_notice_names_the_inert_rule_and_the_backstop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An ad-group-scoped write with only the cumulative rule written."""
        import mureo.mcp.exclusion_sources as sources
        from mureo.mcp.server import handle_call_tool

        _activate_workspace(monkeypatch, tmp_path, _STRATEGY_CUMULATIVE_ONLY)
        monkeypatch.setattr("mureo.mcp.server._load_policy_gates", lambda: ())

        client = _FakeGoogleClient(
            [
                {"placement": "a.example", "type": "website", "impressions": 100},
                {"placement": "b.example", "type": "website", "impressions": 900},
            ]
        )

        async def _fake_client(args: dict[str, Any]) -> Any:
            return client

        monkeypatch.setattr(sources, "google_ads_client", _fake_client)
        monkeypatch.setattr(
            "mureo.mcp._handlers_google_ads._get_client", lambda args: client
        )
        result = await handle_call_tool(
            GOOGLE_ADD,
            {
                "customer_id": "1234567890",
                "ad_group_id": "200",
                "placements": [{"type": "website", "value": "a.example"}],
            },
        )
        text = "\n".join(getattr(c, "text", "") for c in result)
        assert client.mutated is True
        assert "NOT ENFORCED on this call" in text
        assert "max_cumulative_delivery_share_removed_pct" in text
        assert "Add max_delivery_share_removed_pct" in text

    async def test_the_preview_tool_reports_the_same_inert_rule(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        _activate_workspace(monkeypatch, tmp_path, _STRATEGY_CUMULATIVE_ONLY)
        result = await handle_tool(
            "analysis_exclusion_impact_preview",
            {
                "excluded_entities": [{"value": "a.example", "entity_type": "website"}],
                "delivery_records": [
                    {
                        "entity": "a.example",
                        "entity_type": "website",
                        "impressions": 940,
                    },
                ],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["would_block"] is False
        assert [r["key"] for r in payload["unevaluated_rules"]] == [
            "max_cumulative_delivery_share_removed_pct"
        ]

    async def test_no_inert_rules_when_everything_could_be_evaluated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        _activate_workspace(monkeypatch, tmp_path, _STRATEGY_WITH_CAP)
        result = await handle_tool(
            "analysis_exclusion_impact_preview",
            {
                "excluded_entities": [{"value": "a.example", "entity_type": "website"}],
                "delivery_records": [
                    {"entity": "a.example", "entity_type": "website", "impressions": 5},
                    {
                        "entity": "b.example",
                        "entity_type": "website",
                        "impressions": 95,
                    },
                ],
            },
        )
        payload = json.loads(result[0].text)
        assert payload["unevaluated_rules"] == []
        assert payload["would_block"] is False


# ---------------------------------------------------------------------------
# A malformed caller payload must never read as "measured, 0% impact"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMalformedPayloadIsRefused:
    async def test_an_entity_without_a_type_is_refused(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        with pytest.raises(ValueError, match="entity_type"):
            await handle_tool(
                "analysis_exclusion_impact_preview",
                {
                    "excluded_entities": [{"value": "a.example"}],
                    "delivery_records": [
                        {
                            "entity": "a.example",
                            "entity_type": "website",
                            "impressions": 100,
                        }
                    ],
                },
            )

    async def test_an_entity_without_a_value_is_refused(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        with pytest.raises(ValueError, match="value"):
            await handle_tool(
                "analysis_exclusion_impact_preview",
                {"excluded_entities": [{"entity_type": "website"}]},
            )

    async def test_a_delivery_row_without_a_type_is_refused(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        with pytest.raises(ValueError, match="entity_type"):
            await handle_tool(
                "analysis_exclusion_impact_preview",
                {
                    "excluded_entities": [
                        {"value": "a.example", "entity_type": "website"}
                    ],
                    "delivery_records": [{"entity": "a.example", "impressions": 100}],
                },
            )

    async def test_a_blank_standing_exclusion_is_refused(self) -> None:
        from mureo.mcp.tools_analysis import handle_tool

        with pytest.raises(ValueError, match="standing_exclusions"):
            await handle_tool(
                "analysis_exclusion_impact_preview",
                {
                    "excluded_entities": [
                        {"value": "a.example", "entity_type": "website"}
                    ],
                    "standing_exclusions": [{"value": "", "entity_type": "website"}],
                    "delivery_records": [],
                },
            )


# ---------------------------------------------------------------------------
# The placement mappers keep their own module (file-size budget)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_placement_mappers_live_outside_mappers_py() -> None:
    from mureo.google_ads import _placement_mappers, mappers

    assert hasattr(_placement_mappers, "map_negative_placement")
    assert hasattr(_placement_mappers, "map_placement_performance")
    assert not hasattr(mappers, "map_placement_performance")
    root = Path(mappers.__file__).parent
    for name in ("mappers.py", "_placement_mappers.py"):
        lines = len((root / name).read_text(encoding="utf-8").splitlines())
        assert lines <= 800, f"{name} is {lines} lines, over the 800-line budget"
