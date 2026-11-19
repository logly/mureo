"""The ChatGPT Ads custom audience read and create tools (#995), and what
mureo's safety layer reads off every new audience and measurement change.

Each call goes provider → handler → client → ``httpx.MockTransport``; the
contract fixture checks every request's method, path, query and body fields.
The membership add and remove tools have their own module
(``test_chatgpt_ads_audience_members.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

from mureo.change_import.dedupe import _ACTION_OPERATIONS, action_kind
from mureo.chatgpt_ads._errors import MAY_HAVE_BEEN_APPLIED
from mureo.chatgpt_ads.provider import ChatGPTAdsProvider
from mureo.chatgpt_ads.tools import NAME_MAX_CHARS
from mureo.chatgpt_ads.tools_audiences import (
    AUDIENCE_DESCRIPTION_MAX_CHARS,
    AUDIENCE_TOOLS,
    MIN_MATCHED_USERS,
)
from mureo.chatgpt_ads.tools_create import DESTROYS
from mureo.chatgpt_ads.tools_measurement import MEASUREMENT_TOOLS
from mureo.chatgpt_ads.tools_mutations import MUTATES
from mureo.mcp.plugin_semantics import derive_semantics
from tests._chatgpt_ads_fakes import (
    FakeAPI,
    by_name,
    call_tool,
    fail_tool,
    install_fake_api,
    page,
    rows,
    schema_errors,
    sent_body,
)

pytestmark = pytest.mark.unit

_BY_NAME = by_name((*AUDIENCE_TOOLS, *MEASUREMENT_TOOLS))
_MUTATIONS = (
    "chatgpt_ads_audiences_create",
    "chatgpt_ads_audiences_members_add",
    "chatgpt_ads_audiences_members_remove",
    "chatgpt_ads_pixels_create",
    "chatgpt_ads_conversion_events_create",
)


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    return install_fake_api(monkeypatch)


class TestDefinitions:
    def test_the_six_audience_tools(self) -> None:
        assert [t.name for t in AUDIENCE_TOOLS] == [
            "chatgpt_ads_audiences_list",
            "chatgpt_ads_audiences_get",
            "chatgpt_ads_audiences_create",
            "chatgpt_ads_audiences_members_add",
            "chatgpt_ads_audiences_members_remove",
            "chatgpt_ads_audiences_operations_get",
        ]

    @pytest.mark.parametrize("name", sorted(_BY_NAME))
    def test_only_the_five_changes_mutate(self, name: str) -> None:
        semantics = derive_semantics(_BY_NAME[name])
        assert semantics.mutating is (name in _MUTATIONS)
        assert _BY_NAME[name].inputSchema["additionalProperties"] is False

    @pytest.mark.parametrize(
        ("name", "annotations"),
        [
            ("chatgpt_ads_audiences_members_add", MUTATES),
            ("chatgpt_ads_audiences_members_remove", DESTROYS),
        ],
    )
    def test_remove_is_destructive_and_add_is_not(
        self, name: str, annotations: Any
    ) -> None:
        assert _BY_NAME[name].annotations == annotations
        assert derive_semantics(_BY_NAME[name]).mutating is True

    def test_remove_warns_about_the_matched_user_minimum(self) -> None:
        text = _BY_NAME["chatgpt_ads_audiences_members_remove"].description or ""
        assert f"below the {MIN_MATCHED_USERS:,} matched users" in text

    def test_audience_id_is_the_id_argument(self) -> None:
        for tool in AUDIENCE_TOOLS:
            properties = tool.inputSchema["properties"]
            assert "custom_audience_id" not in properties
        assert (
            "audience_id"
            in _BY_NAME["chatgpt_ads_audiences_get"].inputSchema["properties"]
        )

    def test_description_is_bounded(self) -> None:
        tool = _BY_NAME["chatgpt_ads_audiences_create"]
        too_long = "x" * (AUDIENCE_DESCRIPTION_MAX_CHARS + 1)
        assert schema_errors(tool, {"name": "List", "description": too_long})
        assert AUDIENCE_DESCRIPTION_MAX_CHARS == NAME_MAX_CHARS

    def test_create_states_the_eligibility_rules(self) -> None:
        text = _BY_NAME["chatgpt_ads_audiences_create"].description or ""
        for phrase in (
            "empty",
            "small-audience enablement",
            "25,000",
            "exclusion has no minimum",
            "EEA",
            "Switzerland",
            "first-party data",
        ):
            assert phrase in text, phrase


class TestReads:
    async def test_list_follows_the_cursor_with_the_filter(self, api: FakeAPI) -> None:
        api.add("/custom_audiences", body=page(rows("caud", 0, 2), has_more=True))
        api.add("/custom_audiences", body=page(rows("caud", 2, 1), has_more=False))
        result = await call_tool(
            "chatgpt_ads_audiences_list", {"intended_use": "exclusion", "limit": 3}
        )
        assert [r["id"] for r in result] == ["caud_0", "caud_1", "caud_2"]
        assert api.params(0) == [("intended_use", "exclusion"), ("limit", "3")]
        assert api.params(1) == [
            ("intended_use", "exclusion"),
            ("limit", "1"),
            ("after", "caud_1"),
        ]

    async def test_list_default_sends_only_the_limit(self, api: FakeAPI) -> None:
        api.add("/custom_audiences", body=page([], has_more=False))
        assert await call_tool("chatgpt_ads_audiences_list", {}) == []
        assert api.params() == [("limit", "50")]

    async def test_list_refuses_an_unknown_intended_use(self, api: FakeAPI) -> None:
        with pytest.raises(ValueError, match="intended_use"):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_audiences_list", {"intended_use": "lookalike"}
            )
        assert api.requests == []

    async def test_get(self, api: FakeAPI) -> None:
        api.add("/custom_audiences/caud_1", body={"id": "caud_1", "status": "ready"})
        result = await call_tool("chatgpt_ads_audiences_get", {"audience_id": "caud_1"})
        assert result == {"id": "caud_1", "status": "ready"}
        assert api.requests[0].method == "GET"

    async def test_operations_get(self, api: FakeAPI) -> None:
        answer = {"operation_id": "caudop_1", "status": "succeeded"}
        api.add("/custom_audiences/caud_1/operations/caudop_1", body=answer)
        result = await call_tool(
            "chatgpt_ads_audiences_operations_get",
            {"audience_id": "caud_1", "operation_id": "caudop_1"},
        )
        assert result == answer

    @pytest.mark.parametrize(
        ("name", "arguments"),
        [
            ("chatgpt_ads_audiences_get", {"audience_id": "../ad_account"}),
            (
                "chatgpt_ads_audiences_operations_get",
                {"audience_id": "caud_1", "operation_id": "a/b"},
            ),
        ],
    )
    async def test_path_ids_are_checked(
        self, api: FakeAPI, name: str, arguments: dict[str, Any]
    ) -> None:
        assert schema_errors(_BY_NAME[name], arguments)
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(name, arguments)
        assert api.requests == []


class TestCreate:
    async def test_only_name_and_description_are_sent(self, api: FakeAPI) -> None:
        api.add("/custom_audiences", body={"id": "caud_9", "status": "ready"})
        await call_tool(
            "chatgpt_ads_audiences_create",
            {"name": "Past buyers", "description": "Bought in 2026"},
        )
        request = api.requests[0]
        assert sent_body(request) == {
            "name": "Past buyers",
            "description": "Bought in 2026",
        }
        assert "Idempotency-Key" not in request.headers

    async def test_name_alone(self, api: FakeAPI) -> None:
        api.add("/custom_audiences", body={"id": "caud_9"})
        await call_tool("chatgpt_ads_audiences_create", {"name": "Past buyers"})
        assert sent_body(api.requests[0]) == {"name": "Past buyers"}

    @pytest.mark.parametrize(
        "arguments",
        [
            {"name": "ab"},
            {"name": "Past buyers", "description": 5},
            {"name": "Past buyers", "description": "x" * 1001},
            {"description": "no name"},
        ],
        ids=["short-name", "description-type", "description-length", "no-name"],
    )
    async def test_bad_arguments_send_nothing(
        self, api: FakeAPI, arguments: dict[str, Any]
    ) -> None:
        with pytest.raises(ValueError):
            await ChatGPTAdsProvider().handle_mcp_tool(
                "chatgpt_ads_audiences_create", arguments
            )
        assert api.requests == []

    async def test_a_lost_answer_may_have_been_applied(self, api: FakeAPI) -> None:
        api.add("/custom_audiences", 503, {"error": {"message": "busy"}})
        failure = await fail_tool("chatgpt_ads_audiences_create", {"name": "Buyers"})
        assert len(api.requests) == 1
        assert failure.detail.endswith(MAY_HAVE_BEEN_APPLIED)
        assert "check the account" in MAY_HAVE_BEEN_APPLIED


class TestPolicy:
    @pytest.mark.parametrize(
        ("name", "entity"),
        [
            ("chatgpt_ads_audiences_create", None),
            ("chatgpt_ads_audiences_members_add", ("audience", "audience_id")),
            ("chatgpt_ads_audiences_members_remove", ("audience", "audience_id")),
            ("chatgpt_ads_pixels_create", None),
            ("chatgpt_ads_conversion_events_create", None),
        ],
    )
    def test_identity_and_no_money(
        self, name: str, entity: tuple[str, str] | None
    ) -> None:
        semantics = derive_semantics(_BY_NAME[name])
        assert semantics.budget is None and semantics.bid is None
        if entity is None:
            # Nothing these create has an id before the call.
            assert semantics.identity is None
            return
        identity = semantics.identity
        assert identity is not None
        assert (identity.entity_type, identity.entity_id_key) == entity
        assert identity.campaign_id_key is None and identity.ad_id_key is None

    @pytest.mark.parametrize(
        ("name", "kind", "operation"),
        [
            ("chatgpt_ads_audiences_create", "criterion", "create"),
            ("chatgpt_ads_audiences_members_add", "criterion", "create"),
            ("chatgpt_ads_audiences_members_remove", "criterion", "remove"),
            ("chatgpt_ads_pixels_create", "", "create"),
            ("chatgpt_ads_conversion_events_create", "", "create"),
        ],
    )
    def test_change_import_reads_kind_and_operation_off_the_name(
        self, name: str, kind: str, operation: str
    ) -> None:
        assert action_kind(name) == kind
        derived = next(op for token, op in _ACTION_OPERATIONS if token in name)
        assert derived == operation

    @pytest.mark.parametrize(
        ("name", "arguments"),
        [
            ("chatgpt_ads_audiences_create", {"name": "Buyers"}),
            ("chatgpt_ads_pixels_create", {"name": "Site"}),
            (
                "chatgpt_ads_conversion_events_create",
                {"name": "Orders", "event_type": "order_created", "source_id": "s_1"},
            ),
        ],
    )
    async def test_no_reversal(
        self, api: FakeAPI, name: str, arguments: dict[str, Any]
    ) -> None:
        assert await ChatGPTAdsProvider().capture_reversal(name, arguments) is None
        assert api.requests == []
