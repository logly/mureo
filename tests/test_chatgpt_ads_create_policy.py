"""What mureo's safety layer reads off the ChatGPT Ads create and archive tools (#995).

Pinned here: the declarations the plugin safety layer derives, the STRATEGY.md
caps on a campaign create and an ad group create, the change-import kind each
name yields, that neither a create nor an archive records a reversal, and how
the change-import deduper classifies the audit rows these tools leave.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mureo.change_import import ImportVerdict
from mureo.change_import.dedupe import action_kind
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools_create import CREATE_TOOLS
from mureo.context.models import StateDocument
from mureo.context.state import read_state_file, write_state_file
from mureo.mcp import plugin_audit
from mureo.mcp.plugin_semantics import derive_semantics
from mureo.policy.declarations import ArgumentPaths
from mureo.rollback.models import RollbackStatus
from mureo.rollback.planner import plan_rollback
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    by_name,
    install_fake_api,
    strategy_gate,
)
from tests._server_reload import reloaded_server
from tests.test_chatgpt_ads_change_feed import _entry, _row, _verdict
from tests.test_chatgpt_ads_mutation_policy import (  # noqa: F401 — a fixture
    _clean_registries,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mureo.policy.strategy_gate import StrategyPolicyGate

pytestmark = pytest.mark.unit

_BY_NAME = by_name(CREATE_TOOLS)

_GUARDRAILS = (
    "## Guardrails\n"
    "- max_daily_budget_per_campaign: 100\n"
    "- max_lifetime_budget_per_campaign: 1000\n"
    "- max_cpc_bid_per_ad_group: 5\n"
    "- max_total_daily_budget: 500\n"
)


class TestSemantics:
    @pytest.mark.parametrize(
        ("name", "campaign", "ad", "entity"),
        [
            ("chatgpt_ads_campaigns_create", None, None, None),
            ("chatgpt_ads_ad_groups_create", "campaign_id", None, None),
            ("chatgpt_ads_ads_create", None, None, ("ad_group", "ad_group_id")),
            ("chatgpt_ads_campaigns_archive", "campaign_id", None, None),
            (
                "chatgpt_ads_ad_groups_archive",
                None,
                None,
                ("ad_group", "ad_group_id"),
            ),
            ("chatgpt_ads_ads_archive", None, "ad_id", None),
        ],
    )
    def test_identity(
        self,
        name: str,
        campaign: str | None,
        ad: str | None,
        entity: tuple[str, str] | None,
    ) -> None:
        identity = derive_semantics(_BY_NAME[name]).identity
        if campaign is None and ad is None and entity is None:
            # A campaign has no id before it is created.
            assert identity is None
            return
        assert identity is not None
        assert identity.campaign_id_key == campaign
        assert identity.ad_id_key == ad
        assert (identity.entity_type, identity.entity_id_key) == (
            entity if entity else (None, None)
        )

    def test_money_declarations(self) -> None:
        budget = derive_semantics(_BY_NAME["chatgpt_ads_campaigns_create"]).budget
        assert budget is not None and budget.micros is True
        assert budget.daily_key == ArgumentPaths.parse(
            "budget.daily_spend_limit_micros"
        )
        assert budget.lifetime_key == ArgumentPaths.parse(
            "budget.lifetime_spend_limit_micros"
        )
        bid = derive_semantics(_BY_NAME["chatgpt_ads_ad_groups_create"]).bid
        assert bid is not None and bid.micros is True
        path = ArgumentPaths.parse("bidding_config.max_bid_micros")
        assert (bid.cpc_bid_key, bid.bid_amount_key) == (path, path)

    @pytest.mark.parametrize(
        "name",
        [
            "chatgpt_ads_ads_create",
            "chatgpt_ads_campaigns_archive",
            "chatgpt_ads_ad_groups_archive",
            "chatgpt_ads_ads_archive",
        ],
    )
    def test_tools_that_set_no_amount_declare_none(self, name: str) -> None:
        semantics = derive_semantics(_BY_NAME[name])
        assert semantics.budget is None and semantics.bid is None

    @pytest.mark.parametrize(
        ("name", "kind"),
        [
            ("chatgpt_ads_campaigns_create", "campaign"),
            ("chatgpt_ads_ad_groups_create", "ad_group"),
            ("chatgpt_ads_ads_create", "ad"),
            ("chatgpt_ads_campaigns_archive", "campaign"),
            ("chatgpt_ads_ad_groups_archive", "ad_group"),
            # No token of the matcher names an ad on its own ("ads_create" and
            # "ads_update" do), so an ad archive carries no kind.
            ("chatgpt_ads_ads_archive", ""),
            ("chatgpt_ads_images_upload_file", ""),
        ],
    )
    def test_change_import_reads_the_kind_off_the_name(
        self, name: str, kind: str
    ) -> None:
        assert action_kind(name) == kind


@pytest.fixture()
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StrategyPolicyGate:
    return strategy_gate(tmp_path, monkeypatch, CREATE_TOOLS, _GUARDRAILS)


def _campaign(budget: dict[str, int], **context: float) -> dict[str, Any]:
    return {"name": "Spring", "budget": budget, "bidding_type": "clicks", **context}


def _ad_group(micros: int) -> dict[str, Any]:
    return {
        "campaign_id": "c_1",
        "name": "Shoes",
        "bidding_config": {"billing_event_type": "click", "max_bid_micros": micros},
    }


@pytest.mark.usefixtures("_clean_registries")
class TestStrategyGate:
    @pytest.mark.parametrize(
        ("name", "arguments", "allowed"),
        [
            (
                "chatgpt_ads_campaigns_create",
                _campaign({"daily_spend_limit_micros": 99_000_000}),
                True,
            ),
            (
                "chatgpt_ads_campaigns_create",
                _campaign({"daily_spend_limit_micros": 101_000_000}),
                False,
            ),
            (
                "chatgpt_ads_campaigns_create",
                _campaign({"lifetime_spend_limit_micros": 1_100_000_000}),
                False,
            ),
            (
                "chatgpt_ads_campaigns_create",
                _campaign(
                    {"daily_spend_limit_micros": 80_000_000},
                    projected_total_daily_budget=520.0,
                ),
                False,
            ),
            (
                "chatgpt_ads_campaigns_create",
                _campaign(
                    {"daily_spend_limit_micros": 80_000_000},
                    projected_total_daily_budget=480.0,
                ),
                True,
            ),
            ("chatgpt_ads_ad_groups_create", _ad_group(4_000_000), True),
            ("chatgpt_ads_ad_groups_create", _ad_group(6_000_000), False),
        ],
        ids=[
            "daily-within",
            "daily-above",
            "lifetime-above",
            "total-above",
            "total-within",
            "bid-within",
            "bid-above",
        ],
    )
    def test_caps(
        self,
        gate: StrategyPolicyGate,
        name: str,
        arguments: dict[str, Any],
        allowed: bool,
    ) -> None:
        assert gate.evaluate(name, arguments).allowed is allowed

    def test_a_daily_cap_alone_does_not_bound_a_lifetime_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A daily cap is compared with the daily amount only, so a campaign
        with only a lifetime budget passes it however large; only
        ``max_lifetime_budget_per_campaign`` bounds that amount."""
        daily_only = strategy_gate(
            tmp_path,
            monkeypatch,
            CREATE_TOOLS,
            "## Guardrails\n- max_daily_budget_per_campaign: 100\n",
        )
        decision = daily_only.evaluate(
            "chatgpt_ads_campaigns_create",
            _campaign({"lifetime_spend_limit_micros": 1_000_000_000_000}),
        )
        assert decision.allowed is True


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


def _no_thirdparty(**_kw: Any) -> tuple[()]:
    return ()


async def _dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    """Dispatch ``name`` through a fresh server; the action_log entry it left."""
    write_state_file(tmp_path / "STATE.json", StateDocument())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plugin_audit, "_audit_path", lambda: tmp_path / "audit.jsonl")
    with reloaded_server(
        _no_thirdparty, patches={"mureo.core.providers.default_registry._entries": {}}
    ) as mod:
        await mod.handle_call_tool(name, arguments)
    return read_state_file(tmp_path / "STATE.json").action_log[0]


_NO_REVERSAL = [
    ("chatgpt_ads_campaigns_archive", "/campaigns/c_1/archive", {"campaign_id": "c_1"}),
    ("chatgpt_ads_ad_groups_archive", "/ad_groups/g_1/archive", {"ad_group_id": "g_1"}),
    ("chatgpt_ads_ads_archive", "/ads/a_1/archive", {"ad_id": "a_1"}),
    (
        "chatgpt_ads_campaigns_create",
        "/campaigns",
        _campaign({"daily_spend_limit_micros": 5_000_000}),
    ),
]


class TestNoReversal:
    @pytest.mark.parametrize(("name", "path", "arguments"), _NO_REVERSAL)
    async def test_capture_returns_none_without_a_request(
        self, api: FakeAPI, name: str, path: str, arguments: dict[str, Any]
    ) -> None:
        assert await ChatGPTAdsProvider().capture_reversal(name, arguments) is None
        assert api.requests == []

    @pytest.mark.integration
    @pytest.mark.parametrize(("name", "path", "arguments"), _NO_REVERSAL)
    async def test_rollback_is_not_supported(
        self,
        api: FakeAPI,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        name: str,
        path: str,
        arguments: dict[str, Any],
    ) -> None:
        api.add(path, body={"id": "x", "status": "archived"})
        entry = await _dispatch(tmp_path, monkeypatch, name, arguments)
        assert entry.action == name
        assert entry.reversible_params is None
        assert plan_rollback(entry).status is RollbackStatus.NOT_SUPPORTED
        assert [r.method for r in api.requests] == ["POST"]


_TO_ARCHIVED = {"status": {"before": "paused", "after": "archived"}}
_CREATED = {"name": {"before": None, "after": "New"}, "status": {"after": "paused"}}


def _audit(obj_type: str, obj_id: str, log_type: str, changes: Any) -> dict[str, Any]:
    """One audit row for ``obj_id`` in campaign ``cmpn_1``."""
    return _row(
        obj_type=obj_type,
        obj_id=obj_id,
        campaign_id="cmpn_1",
        audit_log_type=log_type,
        changes=changes,
    )


#: (tool, its arguments, the audit row, the verdict, test id).
_ATTRIBUTION = [
    # Creates: mureo's record names no created entity, so nothing matches.
    (
        "chatgpt_ads_campaigns_create",
        {},
        _audit("Campaign", "cmpn_1", "create_campaign", _CREATED),
        ImportVerdict.IMPORT,
        "campaign-create",
    ),
    (
        "chatgpt_ads_ad_groups_create",
        {"campaign_id": "cmpn_1"},
        _audit("AdGroup", "adgrp_1", "create_ad_group", _CREATED),
        ImportVerdict.IMPORT,
        "ad-group-create",
    ),
    (
        "chatgpt_ads_ads_create",
        {"ad_group_id": "adgrp_1"},
        _audit("Ad", "ad_1", "create_ad", _CREATED),
        ImportVerdict.IMPORT,
        "ad-create",
    ),
    # Archives reported as a status change: the row reads as a status kind
    # and the archive names read as an entity kind, so they do not match.
    *(
        (tool, arguments, _audit(obj, obj_id, log_type, _TO_ARCHIVED), verdict, label)
        for tool, arguments, obj, obj_id, prefix, verdict, label in (
            (
                "chatgpt_ads_campaigns_archive",
                {"campaign_id": "cmpn_1"},
                "Campaign",
                "cmpn_1",
                "campaign",
                ImportVerdict.IMPORT,
                "campaign",
            ),
            (
                "chatgpt_ads_ad_groups_archive",
                {"ad_group_id": "adgrp_1"},
                "AdGroup",
                "adgrp_1",
                "ad_group",
                ImportVerdict.IMPORT,
                "ad-group",
            ),
            (
                "chatgpt_ads_ads_archive",
                {"ad_id": "ad_1"},
                "Ad",
                "ad_1",
                "ad",
                ImportVerdict.IMPORT,
                "ad",
            ),
        )
        for log_type, label in (
            (f"archive_{prefix}", f"{label}-archive-row"),
            (f"update_{prefix}", f"{label}-update-row"),
        )
    ),
    # An archive row that names no changed field reads as an entity kind:
    # a campaign or ad group archive then matches; an ad archive, whose name
    # yields no kind, still does not.
    (
        "chatgpt_ads_campaigns_archive",
        {"campaign_id": "cmpn_1"},
        _audit("Campaign", "cmpn_1", "archive_campaign", {}),
        ImportVerdict.ATTRIBUTED_TO_MUREO,
        "campaign-archive-row-no-fields",
    ),
    (
        "chatgpt_ads_ad_groups_archive",
        {"ad_group_id": "adgrp_1"},
        _audit("AdGroup", "adgrp_1", "archive_ad_group", {}),
        ImportVerdict.ATTRIBUTED_TO_MUREO,
        "ad-group-archive-row-no-fields",
    ),
    (
        "chatgpt_ads_ads_archive",
        {"ad_id": "ad_1"},
        _audit("Ad", "ad_1", "archive_ad", {}),
        ImportVerdict.IMPORT,
        "ad-archive-row-no-fields",
    ),
]


@pytest.mark.parametrize(
    ("tool", "arguments", "row", "verdict"),
    [pytest.param(*case[:4], id=case[4]) for case in _ATTRIBUTION],
)
def test_change_import_verdict_as_measured(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, Any],
    row: dict[str, Any],
    verdict: ImportVerdict,
) -> None:
    """The audit row each tool plausibly leaves, through the real deduper.

    A create's record cannot name the entity it created (the id exists only
    once the call returns), so the row for the new entity is imported as an
    external change. The verdicts are pinned as the deduper gives them today.
    """
    assert _verdict(tmp_path, _entry(tool, arguments), row) is verdict
