"""Unit tests for Meta Ads Lead Ads.

Mocks LeadsMixin's _get / _post during testing and also covers the
MCP tool handlers. Verifies that lead data — which contains PII — is
never written to logs.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.meta_ads._leads import _VALID_FORM_STATUSES, LeadsMixin

# ---------------------------------------------------------------------------
# Helpers: mock class that makes the mixin testable
# ---------------------------------------------------------------------------


def _make_mock_client() -> LeadsMixin:
    """Build a LeadsMixin instance with mocked _get/_post/_ad_account_id."""

    class MockClient(LeadsMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})

    return MockClient()


# ===========================================================================
# test_list_lead_forms - fetch lead-form list
# ===========================================================================


@pytest.mark.unit
class TestListLeadForms:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_list_lead_forms(self, client: LeadsMixin) -> None:
        """Can list lead forms by page_id."""
        client._get_as_page = AsyncMock(
            return_value={
                "data": [
                    {"id": "form_1", "name": "問い合わせフォーム", "status": "ACTIVE"},
                    {"id": "form_2", "name": "資料請求フォーム", "status": "ACTIVE"},
                ]
            }
        )
        result = await client.list_lead_forms("page_123")

        assert len(result) == 2
        assert result[0]["id"] == "form_1"
        client._get_as_page.assert_called_once()
        call_args = client._get_as_page.call_args
        assert call_args[0][0] == "page_123"
        assert "/page_123/leadgen_forms" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_list_lead_forms_empty(self, client: LeadsMixin) -> None:
        """Returns an empty list when there are no forms."""
        client._get_as_page = AsyncMock(return_value={"data": []})
        result = await client.list_lead_forms("page_123")

        assert result == []


# ===========================================================================
# test_get_lead_form - fetch lead-form detail
# ===========================================================================


@pytest.mark.unit
class TestGetLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_lead_form(self, client: LeadsMixin) -> None:
        """Can fetch a lead-form detail by form_id."""
        client._get = AsyncMock(
            return_value={
                "id": "form_1",
                "name": "問い合わせフォーム",
                "status": "ACTIVE",
                "questions": [
                    {"type": "FULL_NAME"},
                    {"type": "EMAIL"},
                ],
                "privacy_policy": {"url": "https://example.com/privacy"},
            }
        )
        result = await client.get_lead_form("form_1")

        assert result["id"] == "form_1"
        assert result["name"] == "問い合わせフォーム"
        assert len(result["questions"]) == 2
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/form_1" in call_args[0][0]


# ===========================================================================
# test_create_lead_form - create lead form
# ===========================================================================


@pytest.mark.unit
class TestCreateLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_create_lead_form(self, client: LeadsMixin) -> None:
        """Can create a basic form."""
        client._post = AsyncMock(return_value={"id": "form_new"})
        questions = [
            {"type": "FULL_NAME"},
            {"type": "EMAIL"},
        ]
        result = await client.create_lead_form(
            page_id="page_123",
            name="問い合わせフォーム",
            questions=questions,
            privacy_policy_url="https://example.com/privacy",
        )

        assert result["id"] == "form_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/page_123/leadgen_forms" in call_args[0][0]
        post_data = call_args[0][1]
        assert post_data["name"] == "問い合わせフォーム"
        parsed_privacy = json.loads(post_data["privacy_policy"])
        assert parsed_privacy["url"] == "https://example.com/privacy"
        # questions is sent as a JSON string.
        parsed_questions = json.loads(post_data["questions"])
        assert len(parsed_questions) == 2

    @pytest.mark.asyncio
    async def test_create_lead_form_with_custom_questions(
        self, client: LeadsMixin
    ) -> None:
        """Can create a form with custom questions."""
        client._post = AsyncMock(return_value={"id": "form_custom"})
        questions = [
            {"type": "FULL_NAME"},
            {"type": "EMAIL"},
            {"type": "PHONE_NUMBER"},
            {"type": "COMPANY_NAME"},
            {
                "type": "CUSTOM",
                "key": "budget",
                "label": "予算は？",
                "options": [
                    {"value": "100万以下"},
                    {"value": "100-500万"},
                    {"value": "500万以上"},
                ],
            },
        ]
        result = await client.create_lead_form(
            page_id="page_123",
            name="詳細問い合わせフォーム",
            questions=questions,
            privacy_policy_url="https://example.com/privacy",
            follow_up_action_url="https://example.com/thanks",
        )

        assert result["id"] == "form_custom"
        call_args = client._post.call_args
        post_data = call_args[0][1]
        parsed_questions = json.loads(post_data["questions"])
        assert len(parsed_questions) == 5
        custom_q = parsed_questions[4]
        assert custom_q["type"] == "CUSTOM"
        assert custom_q["key"] == "budget"
        assert len(custom_q["options"]) == 3
        assert post_data["follow_up_action_url"] == "https://example.com/thanks"

    @pytest.mark.asyncio
    async def test_create_lead_form_with_thank_you_page(
        self, client: LeadsMixin
    ) -> None:
        """Can specify follow_up_action_url."""
        client._post = AsyncMock(return_value={"id": "form_ty"})
        result = await client.create_lead_form(
            page_id="page_123",
            name="テストフォーム",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/privacy",
            follow_up_action_url="https://example.com/thanks",
        )

        assert result["id"] == "form_ty"
        post_data = client._post.call_args[0][1]
        assert post_data["follow_up_action_url"] == "https://example.com/thanks"


# ===========================================================================
# test_get_leads - fetch lead data
# ===========================================================================


@pytest.mark.unit
class TestGetLeads:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_leads(self, client: LeadsMixin) -> None:
        """Can fetch lead data submitted to a form."""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "lead_1",
                        "created_time": "2026-03-29T10:00:00+0000",
                        "field_data": [
                            {"name": "full_name", "values": ["田中太郎"]},
                            {"name": "email", "values": ["tanaka@example.com"]},
                        ],
                    },
                    {
                        "id": "lead_2",
                        "created_time": "2026-03-29T11:00:00+0000",
                        "field_data": [
                            {"name": "full_name", "values": ["鈴木花子"]},
                            {"name": "email", "values": ["suzuki@example.com"]},
                        ],
                    },
                ]
            }
        )
        result = await client.get_leads("form_1")

        assert len(result) == 2
        assert result[0]["id"] == "lead_1"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/form_1/leads" in call_args[0][0]
        params = call_args[0][1]
        assert params["limit"] == 100

    @pytest.mark.asyncio
    async def test_get_leads_with_custom_limit(self, client: LeadsMixin) -> None:
        """Can fetch lead data with the `limit` argument."""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_leads("form_1", limit=25)

        params = client._get.call_args[0][1]
        assert params["limit"] == 25

    @pytest.mark.asyncio
    async def test_get_leads_empty(self, client: LeadsMixin) -> None:
        """Returns an empty list when there is no lead data."""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.get_leads("form_1")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_leads_paginates_through_next_cursor(
        self, client: LeadsMixin
    ) -> None:
        """Follow ``paging.next`` cursors via the ``after`` token,
        concatenate the results, and return them all. Forms with
        more than ``limit`` leads must NOT be silently truncated —
        ``get_leads`` should match ``export_leads_to_csv``'s
        pagination behaviour."""
        page_1 = {
            "data": [{"id": f"lead_{i}", "field_data": []} for i in range(2)],
            "paging": {
                "next": (
                    "https://graph.facebook.com/v23.0/form_1/leads"
                    "?fields=id,created_time,field_data,ad_id,ad_name,form_id"
                    "&limit=100&after=CUR_A"
                )
            },
        }
        page_2 = {
            "data": [{"id": "lead_2", "field_data": []}],
            "paging": {},
        }
        client._get = AsyncMock(side_effect=[page_1, page_2])

        result = await client.get_leads("form_1")
        assert [r["id"] for r in result] == ["lead_0", "lead_1", "lead_2"]
        assert client._get.await_count == 2
        # Second call keeps the same relative path; only ``after``
        # is updated.
        second_call = client._get.await_args_list[1]
        assert second_call.args[0] == "/form_1/leads"
        assert second_call.args[1].get("after") == "CUR_A"


# ===========================================================================
# test_get_ad_leads - fetch ad-level lead data
# ===========================================================================


@pytest.mark.unit
class TestGetAdLeads:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_ad_leads(self, client: LeadsMixin) -> None:
        """Can fetch lead data for a specific ad."""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "lead_3",
                        "created_time": "2026-03-29T12:00:00+0000",
                        "field_data": [
                            {"name": "email", "values": ["user@example.com"]},
                        ],
                    },
                ]
            }
        )
        result = await client.get_ad_leads("ad_456")

        assert len(result) == 1
        assert result[0]["id"] == "lead_3"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/ad_456/leads" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_ad_leads_with_limit(self, client: LeadsMixin) -> None:
        """Can fetch per-ad lead data with the `limit` argument."""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_ad_leads("ad_456", limit=50)

        params = client._get.call_args[0][1]
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_ad_leads_paginates_through_next_cursor(
        self, client: LeadsMixin
    ) -> None:
        """Identical ``paging.next`` traversal to :func:`get_leads`."""
        page_1 = {
            "data": [{"id": "lead_a", "field_data": []}],
            "paging": {
                "next": (
                    "https://graph.facebook.com/v23.0/ad_456/leads"
                    "?limit=100&after=AD_CUR_A"
                )
            },
        }
        page_2 = {
            "data": [{"id": "lead_b", "field_data": []}],
            "paging": {},
        }
        client._get = AsyncMock(side_effect=[page_1, page_2])

        result = await client.get_ad_leads("ad_456")
        assert [r["id"] for r in result] == ["lead_a", "lead_b"]
        assert client._get.await_count == 2
        assert client._get.await_args_list[1].args[1].get("after") == "AD_CUR_A"


# ===========================================================================
# test_api_error - API error handling
# ===========================================================================


@pytest.mark.unit
class TestLeadsApiError:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_api_error_propagates(self, client: LeadsMixin) -> None:
        """API errors propagate appropriately."""
        client._get_as_page = AsyncMock(
            side_effect=RuntimeError(
                "Meta API request failed (status=400, path=/page_123/leadgen_forms)"
            )
        )
        with pytest.raises(RuntimeError, match="Meta API request failed"):
            await client.list_lead_forms("page_123")

    @pytest.mark.asyncio
    async def test_api_error_on_create(self, client: LeadsMixin) -> None:
        """API errors during form creation propagate appropriately."""
        client._post = AsyncMock(
            side_effect=RuntimeError(
                "Meta API request failed (status=403, path=/page_123/leadgen_forms)"
            )
        )
        with pytest.raises(RuntimeError, match="Meta API request failed"):
            await client.create_lead_form(
                page_id="page_123",
                name="テスト",
                questions=[{"type": "EMAIL"}],
                privacy_policy_url="https://example.com/privacy",
            )

    @pytest.mark.asyncio
    async def test_api_error_on_get_leads(self, client: LeadsMixin) -> None:
        """API errors during lead-data fetch propagate appropriately."""
        client._get = AsyncMock(side_effect=RuntimeError("Meta API request failed"))
        with pytest.raises(RuntimeError):
            await client.get_leads("form_1")


# ===========================================================================
# MCP tool handler tests
# ===========================================================================


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


def _mock_meta_ads_context():
    """Return mocks for Meta Ads credentials and the API client."""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


@pytest.mark.unit
class TestLeadFormsMcpHandlers:
    """Lead Ads MCP handler tests."""

    async def test_lead_forms_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_lead_forms.return_value = [{"id": "form_1", "name": "問い合わせ"}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_lead_forms_list",
                {"account_id": "act_123", "page_id": "page_456"},
            )

        client.list_lead_forms.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "form_1"

    async def test_lead_forms_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_lead_form.return_value = {
            "id": "form_1",
            "name": "問い合わせ",
        }

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_lead_forms_get",
                {"account_id": "act_123", "form_id": "form_1"},
            )

        client.get_lead_form.assert_awaited_once_with("form_1")

    async def test_lead_forms_create(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_lead_form.return_value = {"id": "form_new"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_lead_forms_create",
                {
                    "account_id": "act_123",
                    "page_id": "page_456",
                    "name": "テストフォーム",
                    "questions": [{"type": "EMAIL"}],
                    "privacy_policy_url": "https://example.com/privacy",
                },
            )

        client.create_lead_form.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "form_new"

    async def test_lead_forms_create_with_follow_up(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.create_lead_form.return_value = {"id": "form_ty"}

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_lead_forms_create",
                {
                    "account_id": "act_123",
                    "page_id": "page_456",
                    "name": "テスト",
                    "questions": [{"type": "EMAIL"}],
                    "privacy_policy_url": "https://example.com/privacy",
                    "follow_up_action_url": "https://example.com/thanks",
                },
            )

        call_kwargs = client.create_lead_form.call_args
        assert call_kwargs[1]["follow_up_action_url"] == "https://example.com/thanks"

    async def test_leads_get(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_leads.return_value = [{"id": "lead_1", "field_data": []}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_leads_get",
                {"account_id": "act_123", "form_id": "form_1"},
            )

        client.get_leads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "lead_1"

    async def test_leads_get_by_ad(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_ad_leads.return_value = [{"id": "lead_2", "field_data": []}]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads_leads_get_by_ad",
                {"account_id": "act_123", "ad_id": "ad_789"},
            )

        client.get_ad_leads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "lead_2"

    async def test_lead_forms_missing_page_id(self) -> None:
        """Raises ValueError when page_id is missing."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            with pytest.raises(ValueError, match="page_id"):
                await mod.handle_tool(
                    "meta_ads_lead_forms_list", {"account_id": "act_123"}
                )

    async def test_leads_no_credentials(self) -> None:
        """Returns error text when no credentials are present."""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        with patch.object(handlers, "load_meta_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "meta_ads_leads_get",
                {"account_id": "act_123", "form_id": "form_1"},
            )
        assert len(result) == 1
        assert "Credentials not found" in result[0].text


@pytest.mark.unit
class TestLeadAdsToolDefinitions:
    """Verify Lead Ads tool definitions."""

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("meta_ads_lead_forms_list", ["page_id"]),
            ("meta_ads_lead_forms_get", ["form_id"]),
            (
                "meta_ads_lead_forms_create",
                ["page_id", "name", "questions", "privacy_policy_url"],
            ),
            ("meta_ads_lead_forms_update", ["form_id", "status"]),
            (
                "meta_ads_lead_forms_duplicate",
                ["form_id", "page_id", "new_name"],
            ),
            ("meta_ads_leads_get", ["form_id"]),
            ("meta_ads_leads_get_by_ad", ["ad_id"]),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """Each tool's required field list is correct."""
        mod = _import_meta_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"Tool {tool_name} not found"
        assert set(tool.inputSchema["required"]) == set(expected_required)

    def test_all_lead_tools_exist(self) -> None:
        """All 8 Lead Ads tools are registered."""
        mod = _import_meta_ads_tools()
        tool_names = {t.name for t in mod.TOOLS}
        expected = {
            "meta_ads_lead_forms_list",
            "meta_ads_lead_forms_get",
            "meta_ads_lead_forms_create",
            "meta_ads_lead_forms_update",
            "meta_ads_lead_forms_duplicate",
            "meta_ads_leads_get",
            "meta_ads_leads_get_by_ad",
            "meta_ads_leads_export_csv",
        }
        assert expected.issubset(tool_names)


# ===========================================================================
# update_lead_form - change form status (PR 2)
# ===========================================================================


@pytest.mark.unit
class TestUpdateLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_update_lead_form_archived(self, client: LeadsMixin) -> None:
        """Send status="ARCHIVED" via POST /{form_id}."""
        await client.update_lead_form("form_1", status="ARCHIVED")
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/form_1" in call_args[0][0]
        assert call_args[0][1] == {"status": "ARCHIVED"}

    @pytest.mark.asyncio
    async def test_update_lead_form_active(self, client: LeadsMixin) -> None:
        """Can re-activate a form by setting status="ACTIVE"."""
        await client.update_lead_form("form_1", status="ACTIVE")
        call_args = client._post.call_args
        assert call_args[0][1] == {"status": "ACTIVE"}

    @pytest.mark.asyncio
    async def test_update_lead_form_rejects_invalid_status(
        self, client: LeadsMixin
    ) -> None:
        """Reject status values Meta does not allow with an early ValueError.

        Failing at the helper layer is easier for operators to debug than
        making a server round-trip just to see a 400.
        """
        with pytest.raises(ValueError) as excinfo:
            await client.update_lead_form("form_1", status="DELETED")
        assert "status" in str(excinfo.value)
        # The API call must not run.
        client._post.assert_not_called()

    def test_valid_statuses_pinned(self) -> None:
        """The validation constant is exactly the two values {ARCHIVED, ACTIVE}."""
        assert frozenset({"ACTIVE", "ARCHIVED"}) == _VALID_FORM_STATUSES


# ===========================================================================
# duplicate_lead_form - duplicate form (PR 2)
# ===========================================================================


@pytest.mark.unit
class TestDuplicateLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_fetches_source_then_creates(
        self, client: LeadsMixin
    ) -> None:
        """Fetch the source form via get_lead_form, then POST to
        leadgen_forms via page_id."""
        source = {
            "id": "form_1",
            "name": "原本",
            "status": "ACTIVE",
            "locale": "ja_JP",
            "questions": [
                {"type": "FULL_NAME"},
                {"type": "EMAIL"},
            ],
            "follow_up_action_url": "https://example.com/thanks",
            # privacy_policy is returned as a nested dict.
            "privacy_policy": {"url": "https://example.com/policy"},
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2", "name": "複製"})

        result = await client.duplicate_lead_form(
            "form_1", page_id="page_123", new_name="複製"
        )

        assert result == {"id": "form_2", "name": "複製"}
        # source fetch
        assert client._get.call_args[0][0] == "/form_1"
        # create call
        post_path = client._post.call_args[0][0]
        post_data = client._post.call_args[0][1]
        assert post_path == "/page_123/leadgen_forms"
        assert post_data["name"] == "複製"
        # questions is passed JSON-encoded.
        assert json.loads(post_data["questions"]) == [
            {"type": "FULL_NAME"},
            {"type": "EMAIL"},
        ]
        # privacy_policy.url is extracted and re-emitted as privacy_policy={"url": ...}.
        assert json.loads(post_data["privacy_policy"]) == {
            "url": "https://example.com/policy"
        }
        # follow_up_action_url / locale are preserved.
        assert post_data["follow_up_action_url"] == "https://example.com/thanks"
        assert post_data["locale"] == "ja_JP"

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_handles_missing_optional_fields(
        self, client: LeadsMixin
    ) -> None:
        """Works even when source omits follow_up_action_url / locale."""
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form("form_1", page_id="page_123", new_name="Copy")

        post_data = client._post.call_args[0][1]
        # Optional fields are not added.
        assert "follow_up_action_url" not in post_data
        assert "locale" not in post_data

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_accepts_string_privacy_policy_url(
        self, client: LeadsMixin
    ) -> None:
        """Also handles the legacy form that returns a privacy_policy_url string."""
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy_url": "https://example.com/policy",
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form("form_1", page_id="page_123", new_name="Copy")

        post_data = client._post.call_args[0][1]
        assert json.loads(post_data["privacy_policy"]) == {
            "url": "https://example.com/policy"
        }

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_uses_new_name_not_source_name(
        self, client: LeadsMixin
    ) -> None:
        """The duplicate uses the new name (not the source's name)."""
        source = {
            "id": "form_1",
            "name": "オリジナル",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form(
            "form_1", page_id="page_123", new_name="まったく違う名前"
        )

        post_data = client._post.call_args[0][1]
        assert post_data["name"] == "まったく違う名前"

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_missing_privacy_policy_raises(
        self, client: LeadsMixin
    ) -> None:
        """Raises ValueError when neither privacy_policy nor privacy_policy_url is present.

        Meta requires privacy_policy.url when creating a lead form, so if the
        source has none, error out early (before Meta returns a 400).
        """
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
        }
        client._get = AsyncMock(return_value=source)

        with pytest.raises(ValueError) as excinfo:
            await client.duplicate_lead_form(
                "form_1", page_id="page_123", new_name="Copy"
            )
        assert "privacy_policy" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_empty_privacy_url_raises(
        self, client: LeadsMixin
    ) -> None:
        """An empty / missing privacy_policy.url goes through the same ValueError path.

        Meta returns 400 if url is empty, so we catch it at the helper layer
        and surface an immediately recognisable error to the operator.
        """
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": ""},
        }
        client._get = AsyncMock(return_value=source)

        with pytest.raises(ValueError) as excinfo:
            await client.duplicate_lead_form(
                "form_1", page_id="page_123", new_name="Copy"
            )
        assert "privacy_policy" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_link_text_only_privacy_raises(
        self, client: LeadsMixin
    ) -> None:
        """A privacy_policy dict that has only link_text and no url also raises
        ValueError (Meta requires url).
        """
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"link_text": "Privacy Policy"},
        }
        client._get = AsyncMock(return_value=source)

        with pytest.raises(ValueError):
            await client.duplicate_lead_form(
                "form_1", page_id="page_123", new_name="Copy"
            )

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_copies_advanced_fields(
        self, client: LeadsMixin
    ) -> None:
        """A source form carrying the PR 3 advanced fields
        (``context_card`` / ``thank_you_page`` / ``is_higher_intent`` /
        ``conditional_questions_choices``) must round-trip those
        fields onto the new form when duplicated.

        This fulfils the v0.9.15 docstring promise that "PR 3 will
        widen the copied surface", which was deferred at the time.
        """
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
            "context_card": {
                "title": "資料請求",
                "content": "60秒で完了",
                "style": "PARAGRAPH_STYLE",
            },
            "thank_you_page": {
                "title": "ありがとうございます",
                "body": "担当者から連絡します",
                "button_type": "VIEW_WEBSITE",
                "website_url": "https://example.com/thanks",
            },
            "is_higher_intent": True,
            "conditional_questions_choices": [
                {
                    "question": "predefined",
                    "value": "INTERESTED",
                    "next_question_key": "company_size",
                },
            ],
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form(
            "form_1", page_id="page_123", new_name="Copy"
        )

        post_data = client._post.call_args[0][1]
        assert json.loads(post_data["context_card"]) == source["context_card"]
        assert (
            json.loads(post_data["thank_you_page"]) == source["thank_you_page"]
        )
        assert post_data["is_higher_intent"] is True
        assert (
            json.loads(post_data["conditional_questions_choices"])
            == source["conditional_questions_choices"]
        )

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_skips_absent_advanced_fields(
        self, client: LeadsMixin
    ) -> None:
        """A source form without the advanced fields produces a
        payload that does not gain extra empty keys — preserves the
        backward-compatible shape pinned by earlier tests.
        """
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form(
            "form_1", page_id="page_123", new_name="Copy"
        )

        post_data = client._post.call_args[0][1]
        assert "context_card" not in post_data
        assert "thank_you_page" not in post_data
        assert "is_higher_intent" not in post_data
        assert "conditional_questions_choices" not in post_data

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_higher_intent_false_not_sent(
        self, client: LeadsMixin
    ) -> None:
        """``is_higher_intent=False`` on the source is elided from
        the payload — it matches Meta's default, so omitting it
        keeps the request body minimal."""
        source = {
            "id": "form_1",
            "name": "原本",
            "questions": [{"type": "EMAIL"}],
            "privacy_policy": {"url": "https://example.com/policy"},
            "is_higher_intent": False,
        }
        client._get = AsyncMock(return_value=source)
        client._post = AsyncMock(return_value={"id": "form_2"})

        await client.duplicate_lead_form(
            "form_1", page_id="page_123", new_name="Copy"
        )

        post_data = client._post.call_args[0][1]
        assert "is_higher_intent" not in post_data


# ===========================================================================
# Advanced lead form creation (PR 3) — context_card / thank_you_page /
# is_higher_intent / conditional_questions_choices
# ===========================================================================


@pytest.mark.unit
class TestCreateLeadFormAdvanced:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_advanced_kwargs_all_omitted_keeps_backcompat_shape(
        self, client: LeadsMixin
    ) -> None:
        """Omitting every new optional kwarg yields a payload identical to the
        legacy one — pins the ABI to avoid breaking existing callers."""
        await client.create_lead_form(
            page_id="page_123",
            name="basic",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
        )
        data = client._post.call_args[0][1]
        # The new fields are not sent.
        assert "context_card" not in data
        assert "thank_you_page" not in data
        assert "is_higher_intent" not in data
        assert "conditional_questions_choices" not in data

    @pytest.mark.asyncio
    async def test_context_card_serialised_into_payload(
        self, client: LeadsMixin
    ) -> None:
        """The intro-screen config is JSON-encoded into context_card."""
        card = {
            "title": "資料請求はこちら",
            "content": "60秒で完了します。",
            "style": "PARAGRAPH_STYLE",
            "cover_photo_id": "img_123",
        }
        await client.create_lead_form(
            page_id="page_123",
            name="intro form",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
            context_card=card,
        )
        data = client._post.call_args[0][1]
        assert json.loads(data["context_card"]) == card

    @pytest.mark.asyncio
    async def test_thank_you_page_serialised_into_payload(
        self, client: LeadsMixin
    ) -> None:
        """The thank-you-screen config is JSON-encoded into thank_you_page."""
        page = {
            "title": "ありがとうございます",
            "body": "担当者から連絡します。",
            "button_type": "VIEW_WEBSITE",
            "website_url": "https://example.com/landing",
            "button_text": "サイトを見る",
        }
        await client.create_lead_form(
            page_id="page_123",
            name="ty form",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
            thank_you_page=page,
        )
        data = client._post.call_args[0][1]
        assert json.loads(data["thank_you_page"]) == page

    @pytest.mark.asyncio
    async def test_is_higher_intent_true_added_as_boolean(
        self, client: LeadsMixin
    ) -> None:
        """higher-intent is a boolean flag switching to a 3-step form
        (input → confirm → submit).

        The Meta API expects a boolean, not a string.
        """
        await client.create_lead_form(
            page_id="page_123",
            name="HI form",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
            is_higher_intent=True,
        )
        data = client._post.call_args[0][1]
        assert data["is_higher_intent"] is True

    @pytest.mark.asyncio
    async def test_is_higher_intent_false_default_not_sent(
        self, client: LeadsMixin
    ) -> None:
        """The default (False) is omitted from the payload — Meta's default is also
        False, so there is no need to send it explicitly."""
        await client.create_lead_form(
            page_id="page_123",
            name="standard form",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
        )
        data = client._post.call_args[0][1]
        assert "is_higher_intent" not in data

    @pytest.mark.asyncio
    async def test_conditional_questions_choices_serialised(
        self, client: LeadsMixin
    ) -> None:
        """Conditional-question branch info is JSON-encoded before sending."""
        choices = [
            {
                "question": "predefined",
                "value": "INTERESTED_IN_DEMO",
                "next_question_key": "company_size",
            },
        ]
        await client.create_lead_form(
            page_id="page_123",
            name="branching form",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
            conditional_questions_choices=choices,
        )
        data = client._post.call_args[0][1]
        assert json.loads(data["conditional_questions_choices"]) == choices


# ===========================================================================
# export_leads_to_csv (PR 3)
# ===========================================================================


@pytest.mark.unit
class TestExportLeadsToCsv:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_writes_csv_header_from_form_questions(
        self, client: LeadsMixin, tmp_path: pytest.TempPathFactory
    ) -> None:
        """The first CSV row follows the form's questions order — the column
        order remains stable across repeated exports."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "name": "Test",
            "questions": [
                {"type": "FULL_NAME", "key": "full_name"},
                {"type": "EMAIL", "key": "email"},
                {"type": "PHONE_NUMBER", "key": "phone_number"},
            ],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    {"name": "full_name", "values": ["田中 太郎"]},
                    {"name": "email", "values": ["taro@example.com"]},
                    {"name": "phone_number", "values": ["0901234567"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 1

        rows = out.read_text(encoding="utf-8").splitlines()
        header = rows[0].split(",")
        # id / created_time + question keys
        assert header[:2] == ["id", "created_time"]
        assert set(header[2:]) == {"full_name", "email", "phone_number"}
        # Column order matches the form's question order.
        assert header[2:] == ["full_name", "email", "phone_number"]

    @pytest.mark.asyncio
    async def test_csv_one_row_per_lead(
        self, client: LeadsMixin, tmp_path: pytest.TempPathFactory
    ) -> None:
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [{"name": "email", "values": ["a@example.com"]}],
            },
            {
                "id": "lead_2",
                "created_time": "2026-01-02T00:00:00+0000",
                "field_data": [{"name": "email", "values": ["b@example.com"]}],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 2

        rows = out.read_text(encoding="utf-8").splitlines()
        # header + 2 leads
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_csv_zero_leads_writes_header_only(
        self, client: LeadsMixin, tmp_path: pytest.TempPathFactory
    ) -> None:
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        client._get = AsyncMock(side_effect=[form, {"data": []}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 0

        rows = out.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1  # header only

    @pytest.mark.asyncio
    async def test_csv_does_not_log_pii(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """lead.field_data values must never appear in log output."""
        from pathlib import Path
        import logging

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        sentinel = "ultra-secret-email-address@example.com"
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [{"name": "email", "values": [sentinel]}],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        with caplog.at_level(logging.DEBUG, logger="mureo.meta_ads._leads"):
            await client.export_leads_to_csv("form_1", out)

        log_text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert sentinel not in log_text

    @pytest.mark.asyncio
    async def test_csv_field_order_override(
        self, client: LeadsMixin, tmp_path: pytest.TempPathFactory
    ) -> None:
        """When the caller specifies field_order, it takes priority over the form's question order."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [
                {"type": "FULL_NAME", "key": "full_name"},
                {"type": "EMAIL", "key": "email"},
            ],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    {"name": "full_name", "values": ["A"]},
                    {"name": "email", "values": ["a@example.com"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        await client.export_leads_to_csv(
            "form_1", out, field_order=["email", "full_name"]
        )
        header = out.read_text(encoding="utf-8").splitlines()[0].split(",")
        assert header[2:] == ["email", "full_name"]

    @pytest.mark.asyncio
    async def test_csv_handles_missing_field_data(
        self, client: LeadsMixin, tmp_path: pytest.TempPathFactory
    ) -> None:
        """When a lead is missing some fields, the cells are blank (do not raise)."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [
                {"type": "FULL_NAME", "key": "full_name"},
                {"type": "EMAIL", "key": "email"},
            ],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    # full_name missing
                    {"name": "email", "values": ["a@example.com"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 1
        rows = out.read_text(encoding="utf-8").splitlines()
        # Missing cells are blank — use a csv parser to assert the exact value.
        import csv

        with open(out, encoding="utf-8") as f:
            parsed = list(csv.DictReader(f))
        assert parsed[0]["full_name"] == ""
        assert parsed[0]["email"] == "a@example.com"

    @pytest.mark.asyncio
    async def test_csv_standard_question_without_key_uses_lowercase_type(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Standard questions usually omit ``key``. Meta's
        ``field_data[].name`` returns the lowercased type
        (``EMAIL`` → ``email``); the header must match that wire
        format so the value lookup actually hits the cell."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [
                {"type": "FULL_NAME"},  # no key
                {"type": "EMAIL"},  # no key
            ],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    {"name": "full_name", "values": ["山田 太郎"]},
                    {"name": "email", "values": ["t@example.com"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        await client.export_leads_to_csv("form_1", out)

        import csv

        with open(out, encoding="utf-8") as f:
            parsed = list(csv.DictReader(f))
        assert parsed[0]["full_name"] == "山田 太郎"
        assert parsed[0]["email"] == "t@example.com"

    @pytest.mark.asyncio
    async def test_csv_injection_values_are_escaped(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Values starting with ``=``, ``+``, ``-``, ``@``, tab, or CR are executed
        as a formula by spreadsheets (CSV injection); the helper neutralises
        them by prefixing a single quote."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "CUSTOM", "key": "free_text"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    {"name": "free_text", "values": ['=cmd|"/c calc"!A1']},
                ],
            },
            {
                "id": "lead_2",
                "created_time": "2026-01-02T00:00:00+0000",
                "field_data": [
                    {"name": "free_text", "values": ["@SUM(A1:A10)"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        await client.export_leads_to_csv("form_1", out)

        import csv

        with open(out, encoding="utf-8") as f:
            parsed = list(csv.DictReader(f))
        assert parsed[0]["free_text"].startswith("'=")
        assert parsed[1]["free_text"].startswith("'@")

    @pytest.mark.asyncio
    async def test_csv_multi_value_uses_pipe_separator(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """multi-select values are joined with ``" | "`` — even if a value itself
        contains a comma, the spreadsheet semantics stay intact."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "CUSTOM", "key": "interests"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        leads = [
            {
                "id": "lead_1",
                "created_time": "2026-01-01T00:00:00+0000",
                "field_data": [
                    {
                        "name": "interests",
                        "values": ["AI, ML", "infra", "DX"],
                    },
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        await client.export_leads_to_csv("form_1", out)

        import csv

        with open(out, encoding="utf-8") as f:
            parsed = list(csv.DictReader(f))
        assert parsed[0]["interests"] == "AI, ML | infra | DX"

    @pytest.mark.asyncio
    async def test_csv_pagination_follows_next_cursor(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """Fetches every lead even when the result spans multiple pages."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        page_1 = {
            "data": [
                {
                    "id": f"lead_{i}",
                    "created_time": "2026-01-01T00:00:00+0000",
                    "field_data": [
                        {"name": "email", "values": [f"u{i}@example.com"]}
                    ],
                }
                for i in range(2)
            ],
            "paging": {
                "next": "https://graph.facebook.com/v23.0/form_1/leads?after=cursor1"
            },
        }
        page_2 = {
            "data": [
                {
                    "id": "lead_2",
                    "created_time": "2026-01-01T00:00:00+0000",
                    "field_data": [
                        {"name": "email", "values": ["u2@example.com"]}
                    ],
                },
            ],
            # No paging.next → loop terminates.
        }
        client._get = AsyncMock(side_effect=[form, page_1, page_2])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 3

        import csv

        with open(out, encoding="utf-8") as f:
            parsed = list(csv.DictReader(f))
        assert {row["email"] for row in parsed} == {
            "u0@example.com",
            "u1@example.com",
            "u2@example.com",
        }
        # 2nd & 3rd calls use the paging.next URL as the path —
        # the 4th call must not happen (= loop termination is normal).
        assert client._get.await_count == 3

    @pytest.mark.asyncio
    async def test_csv_pagination_bails_when_next_has_no_after_cursor(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """A non-standard ``paging.next`` URL missing the ``after``
        query parameter must terminate the loop immediately — pins
        the defensive break path so we never infinite-loop on a
        malformed cursor."""
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        page = {
            "data": [
                {
                    "id": "lead_only",
                    "created_time": "2026-01-01T00:00:00+0000",
                    "field_data": [{"name": "email", "values": ["a@x.io"]}],
                }
            ],
            # ``next`` is present but has no ``after=`` query.
            "paging": {
                "next": "https://graph.facebook.com/v23.0/form_1/leads?foo=bar"
            },
        }
        client._get = AsyncMock(side_effect=[form, page])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 1
        # form fetch + 1 page fetch = 2 calls; no third call.
        assert client._get.await_count == 2

    @pytest.mark.asyncio
    async def test_csv_pagination_uses_relative_path_with_after_cursor(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """``paging.next`` is an absolute URL, but ``_get`` always prepends
        BASE_URL — passing the absolute URL would double-concatenate into a
        404. The helper must extract only the ``after`` cursor and re-call
        with a relative path.
        """
        from pathlib import Path

        form = {
            "id": "form_1",
            "questions": [{"type": "EMAIL", "key": "email"}],
            "privacy_policy": {"url": "https://example.com/p"},
        }
        page_1 = {
            "data": [
                {
                    "id": "lead_0",
                    "created_time": "2026-01-01T00:00:00+0000",
                    "field_data": [
                        {"name": "email", "values": ["u0@example.com"]}
                    ],
                }
            ],
            "paging": {
                "next": (
                    "https://graph.facebook.com/v23.0/form_1/leads"
                    "?fields=id,created_time,field_data&limit=1000"
                    "&after=CURSOR_ABC"
                )
            },
        }
        page_2 = {"data": [], "paging": {}}
        client._get = AsyncMock(side_effect=[form, page_1, page_2])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        await client.export_leads_to_csv("form_1", out)

        # The 2nd lead fetch (= 3rd _get call) keeps the relative
        # path and only passes the after cursor in params.
        third_call = client._get.await_args_list[2]
        third_path, third_params = third_call.args[0], third_call.args[1]
        assert third_path == "/form_1/leads"
        assert third_params.get("after") == "CURSOR_ABC"
        # The existing fields / limit are also preserved.
        assert "fields" in third_params
        assert third_params.get("limit") == 1000
