"""Meta Ads Lead Ads (リード広告) ユニットテスト

LeadsMixin の _get / _post をモックしてテストする。
MCPツールハンドラーのテストも含む。
リードデータには個人情報が含まれるためログ出力しないことも検証する。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.meta_ads._leads import LeadsMixin


# ---------------------------------------------------------------------------
# ヘルパー: Mixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_mock_client() -> LeadsMixin:
    """LeadsMixinにモック _get/_post/_ad_account_id を付与したインスタンスを生成"""

    class MockClient(LeadsMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})

    return MockClient()


# ===========================================================================
# test_list_lead_forms — フォーム一覧取得
# ===========================================================================


@pytest.mark.unit
class TestListLeadForms:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_list_lead_forms(self, client: LeadsMixin) -> None:
        """page_id指定でリードフォーム一覧を取得できること"""
        client._get = AsyncMock(
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
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/page_123/leadgen_forms" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_lead_forms_empty(self, client: LeadsMixin) -> None:
        """フォームが存在しない場合は空リストを返すこと"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.list_lead_forms("page_123")

        assert result == []


# ===========================================================================
# test_get_lead_form — フォーム詳細取得
# ===========================================================================


@pytest.mark.unit
class TestGetLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_lead_form(self, client: LeadsMixin) -> None:
        """form_id指定でリードフォーム詳細を取得できること"""
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
# test_create_lead_form — フォーム作成
# ===========================================================================


@pytest.mark.unit
class TestCreateLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_create_lead_form(self, client: LeadsMixin) -> None:
        """基本的なフォームを作成できること"""
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
        # questionsはJSON文字列として送信される
        parsed_questions = json.loads(post_data["questions"])
        assert len(parsed_questions) == 2

    @pytest.mark.asyncio
    async def test_create_lead_form_with_custom_questions(
        self, client: LeadsMixin
    ) -> None:
        """カスタム質問付きフォームを作成できること"""
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
        """follow_up_action_urlを指定できること"""
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
# test_get_leads — リードデータ取得
# ===========================================================================


@pytest.mark.unit
class TestGetLeads:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_leads(self, client: LeadsMixin) -> None:
        """フォームに送信されたリードデータを取得できること"""
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
        """limit指定でリードデータを取得できること"""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_leads("form_1", limit=25)

        params = client._get.call_args[0][1]
        assert params["limit"] == 25

    @pytest.mark.asyncio
    async def test_get_leads_empty(self, client: LeadsMixin) -> None:
        """リードデータが空の場合は空リストを返すこと"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.get_leads("form_1")

        assert result == []


# ===========================================================================
# test_get_ad_leads — 広告別リードデータ取得
# ===========================================================================


@pytest.mark.unit
class TestGetAdLeads:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_get_ad_leads(self, client: LeadsMixin) -> None:
        """広告経由のリードデータを取得できること"""
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
        """limit指定で広告別リードデータを取得できること"""
        client._get = AsyncMock(return_value={"data": []})
        await client.get_ad_leads("ad_456", limit=50)

        params = client._get.call_args[0][1]
        assert params["limit"] == 50


# ===========================================================================
# test_api_error — APIエラーハンドリング
# ===========================================================================


@pytest.mark.unit
class TestLeadsApiError:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_api_error_propagates(self, client: LeadsMixin) -> None:
        """APIエラーが適切に伝播すること"""
        client._get = AsyncMock(
            side_effect=RuntimeError("Meta API request failed (status=400, path=/page_123/leadgen_forms)")
        )
        with pytest.raises(RuntimeError, match="Meta API request failed"):
            await client.list_lead_forms("page_123")

    @pytest.mark.asyncio
    async def test_api_error_on_create(self, client: LeadsMixin) -> None:
        """フォーム作成時のAPIエラーが適切に伝播すること"""
        client._post = AsyncMock(
            side_effect=RuntimeError("Meta API request failed (status=403, path=/page_123/leadgen_forms)")
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
        """リードデータ取得時のAPIエラーが適切に伝播すること"""
        client._get = AsyncMock(
            side_effect=RuntimeError("Meta API request failed")
        )
        with pytest.raises(RuntimeError):
            await client.get_leads("form_1")


# ===========================================================================
# MCPツールハンドラーテスト
# ===========================================================================


def _import_meta_ads_tools():
    from mureo.mcp import tools_meta_ads

    return tools_meta_ads


def _import_handlers():
    from mureo.mcp import _handlers_meta_ads

    return _handlers_meta_ads


def _mock_meta_ads_context():
    """Meta Ads認証情報とクライアントのモックを返す"""
    mock_client = AsyncMock()
    mock_creds = MagicMock()
    return mock_creds, mock_client


@pytest.mark.unit
class TestLeadFormsMcpHandlers:
    """Lead Ads系MCPハンドラーテスト"""

    async def test_lead_forms_list(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.list_lead_forms.return_value = [
            {"id": "form_1", "name": "問い合わせ"}
        ]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.lead_forms.list",
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
                "meta_ads.lead_forms.get",
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
                "meta_ads.lead_forms.create",
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
                "meta_ads.lead_forms.create",
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
        client.get_leads.return_value = [
            {"id": "lead_1", "field_data": []}
        ]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.leads.get",
                {"account_id": "act_123", "form_id": "form_1"},
            )

        client.get_leads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "lead_1"

    async def test_leads_get_by_ad(self) -> None:
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        client.get_ad_leads.return_value = [
            {"id": "lead_2", "field_data": []}
        ]

        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            result = await mod.handle_tool(
                "meta_ads.leads.get_by_ad",
                {"account_id": "act_123", "ad_id": "ad_789"},
            )

        client.get_ad_leads.assert_awaited_once()
        parsed = json.loads(result[0].text)
        assert parsed[0]["id"] == "lead_2"

    async def test_lead_forms_missing_page_id(self) -> None:
        """page_id欠損でValueErrorが発生"""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        creds, client = _mock_meta_ads_context()
        with (
            patch.object(handlers, "load_meta_ads_credentials", return_value=creds),
            patch.object(handlers, "create_meta_ads_client", return_value=client),
        ):
            with pytest.raises(ValueError, match="page_id"):
                await mod.handle_tool(
                    "meta_ads.lead_forms.list", {"account_id": "act_123"}
                )

    async def test_leads_no_credentials(self) -> None:
        """認証情報なしでエラーテキストを返す"""
        mod = _import_meta_ads_tools()
        handlers = _import_handlers()
        with patch.object(handlers, "load_meta_ads_credentials", return_value=None):
            result = await mod.handle_tool(
                "meta_ads.leads.get",
                {"account_id": "act_123", "form_id": "form_1"},
            )
        assert len(result) == 1
        assert "Credentials not found" in result[0].text


@pytest.mark.unit
class TestLeadAdsToolDefinitions:
    """Lead Adsツール定義の検証"""

    @pytest.mark.parametrize(
        "tool_name,expected_required",
        [
            ("meta_ads.lead_forms.list", ["account_id", "page_id"]),
            ("meta_ads.lead_forms.get", ["account_id", "form_id"]),
            (
                "meta_ads.lead_forms.create",
                ["account_id", "page_id", "name", "questions", "privacy_policy_url"],
            ),
            ("meta_ads.leads.get", ["account_id", "form_id"]),
            ("meta_ads.leads.get_by_ad", ["account_id", "ad_id"]),
        ],
    )
    def test_required_fields(
        self, tool_name: str, expected_required: list[str]
    ) -> None:
        """各ツールのrequiredフィールドが正しいこと"""
        mod = _import_meta_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"ツール {tool_name} が見つかりません"
        assert set(tool.inputSchema["required"]) == set(expected_required)

    def test_all_lead_tools_exist(self) -> None:
        """5つのLead Adsツールがすべて登録されていること"""
        mod = _import_meta_ads_tools()
        tool_names = {t.name for t in mod.TOOLS}
        expected = {
            "meta_ads.lead_forms.list",
            "meta_ads.lead_forms.get",
            "meta_ads.lead_forms.create",
            "meta_ads.leads.get",
            "meta_ads.leads.get_by_ad",
        }
        assert expected.issubset(tool_names)
