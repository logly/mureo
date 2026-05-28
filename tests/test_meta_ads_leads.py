"""Meta Ads Lead Ads (リード広告) ユニットテスト

LeadsMixin の _get / _post をモックしてテストする。
MCPツールハンドラーのテストも含む。
リードデータには個人情報が含まれるためログ出力しないことも検証する。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.meta_ads._leads import _VALID_FORM_STATUSES, LeadsMixin

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
        """フォームが存在しない場合は空リストを返すこと"""
        client._get_as_page = AsyncMock(return_value={"data": []})
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
        client._get_as_page = AsyncMock(
            side_effect=RuntimeError(
                "Meta API request failed (status=400, path=/page_123/leadgen_forms)"
            )
        )
        with pytest.raises(RuntimeError, match="Meta API request failed"):
            await client.list_lead_forms("page_123")

    @pytest.mark.asyncio
    async def test_api_error_on_create(self, client: LeadsMixin) -> None:
        """フォーム作成時のAPIエラーが適切に伝播すること"""
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
        """リードデータ取得時のAPIエラーが適切に伝播すること"""
        client._get = AsyncMock(side_effect=RuntimeError("Meta API request failed"))
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
                    "meta_ads_lead_forms_list", {"account_id": "act_123"}
                )

    async def test_leads_no_credentials(self) -> None:
        """認証情報なしでエラーテキストを返す"""
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
    """Lead Adsツール定義の検証"""

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
        """各ツールのrequiredフィールドが正しいこと"""
        mod = _import_meta_ads_tools()
        tool = next((t for t in mod.TOOLS if t.name == tool_name), None)
        assert tool is not None, f"ツール {tool_name} が見つかりません"
        assert set(tool.inputSchema["required"]) == set(expected_required)

    def test_all_lead_tools_exist(self) -> None:
        """8つのLead Adsツールがすべて登録されていること"""
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
# update_lead_form — フォームステータス変更 (PR 2)
# ===========================================================================


@pytest.mark.unit
class TestUpdateLeadForm:
    @pytest.fixture()
    def client(self) -> LeadsMixin:
        return _make_mock_client()

    @pytest.mark.asyncio
    async def test_update_lead_form_archived(self, client: LeadsMixin) -> None:
        """status="ARCHIVED" を POST /{form_id} に送る"""
        await client.update_lead_form("form_1", status="ARCHIVED")
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/form_1" in call_args[0][0]
        assert call_args[0][1] == {"status": "ARCHIVED"}

    @pytest.mark.asyncio
    async def test_update_lead_form_active(self, client: LeadsMixin) -> None:
        """status="ACTIVE" でフォームを復活できること"""
        await client.update_lead_form("form_1", status="ACTIVE")
        call_args = client._post.call_args
        assert call_args[0][1] == {"status": "ACTIVE"}

    @pytest.mark.asyncio
    async def test_update_lead_form_rejects_invalid_status(
        self, client: LeadsMixin
    ) -> None:
        """Meta が許す status 値以外は ValueError で早期に弾く

        サーバラウンドトリップして 400 を見るより、helper 段階で型エラーに
        するほうがオペレーター視点でデバッグしやすい。
        """
        with pytest.raises(ValueError) as excinfo:
            await client.update_lead_form("form_1", status="DELETED")
        assert "status" in str(excinfo.value)
        # API call は走らない
        client._post.assert_not_called()

    def test_valid_statuses_pinned(self) -> None:
        """validation の根拠となる定数が ARCHIVED / ACTIVE の 2 値であること"""
        assert frozenset({"ACTIVE", "ARCHIVED"}) == _VALID_FORM_STATUSES


# ===========================================================================
# duplicate_lead_form — フォーム複製 (PR 2)
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
        """source form を get_lead_form で取得 → page_id 経由で
        leadgen_forms に POST する"""
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
            # privacy_policy はネストされた dict として返ってくる
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
        # questions は JSON エンコードされて渡る
        assert json.loads(post_data["questions"]) == [
            {"type": "FULL_NAME"},
            {"type": "EMAIL"},
        ]
        # privacy_policy.url が抜き出されて privacy_policy={"url": ...} に再構築される
        assert json.loads(post_data["privacy_policy"]) == {
            "url": "https://example.com/policy"
        }
        # follow_up_action_url / locale は preserved
        assert post_data["follow_up_action_url"] == "https://example.com/thanks"
        assert post_data["locale"] == "ja_JP"

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_handles_missing_optional_fields(
        self, client: LeadsMixin
    ) -> None:
        """source に follow_up_action_url / locale が無い場合も動く"""
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
        # 任意フィールドは追加されない
        assert "follow_up_action_url" not in post_data
        assert "locale" not in post_data

    @pytest.mark.asyncio
    async def test_duplicate_lead_form_accepts_string_privacy_policy_url(
        self, client: LeadsMixin
    ) -> None:
        """旧形式で privacy_policy_url 文字列が返ってくるケースも吸収する"""
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
        """新しい name で複製されること (source の name は使わない)"""
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
        """privacy_policy も privacy_policy_url も無い場合は ValueError

        Meta は lead form 作成時に privacy_policy.url を必須としているので、
        source から取れなかったら早期にエラーにする (Meta から 400 を返さ
        れる前に弾く)。
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
        """privacy_policy.url が空文字 / 欠落の場合も同じ ValueError 経路を通る

        Meta は url が空のままだと 400 を返すので、helper 段階で拾って
        オペレーターに即座に分かるエラーにする。
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
        """privacy_policy dict が link_text だけで url を持たないケースも
        ValueError (Meta は url 必須)
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
        """新しい optional kwargs を全て省略しても従来の payload と一致
        — 既存 caller を破壊しないことを ABI レベルで pin する"""
        await client.create_lead_form(
            page_id="page_123",
            name="basic",
            questions=[{"type": "EMAIL"}],
            privacy_policy_url="https://example.com/policy",
        )
        data = client._post.call_args[0][1]
        # 新フィールドは送られない
        assert "context_card" not in data
        assert "thank_you_page" not in data
        assert "is_higher_intent" not in data
        assert "conditional_questions_choices" not in data

    @pytest.mark.asyncio
    async def test_context_card_serialised_into_payload(
        self, client: LeadsMixin
    ) -> None:
        """intro 画面の構成情報が JSON エンコードされて context_card に入る"""
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
        """完了画面の構成情報が JSON エンコードされて thank_you_page に入る"""
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
        """higher-intent は 3-step (入力→確認→送信) に切り替える bool flag

        Meta API は文字列ではなく真偽値を期待する。
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
        """デフォルト (False) は payload に出ない — Meta の標準 = False と
        一致するので、明示的に送る必要はない"""
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
        """conditional question 分岐情報は JSON エンコードされて送られる"""
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
        """CSV 1 行目は form の questions の順序に従う — operator が
        export を何度走らせても列順が安定する"""
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
        # id / created_time + 質問キー
        assert header[:2] == ["id", "created_time"]
        assert set(header[2:]) == {"full_name", "email", "phone_number"}
        # 列順は form の question 順
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
        """lead の field_data の値は log 出力に絶対現れない"""
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
        """caller が field_order を明示したら form の question 順より優先する"""
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
        """lead が一部 field を持たない場合は空セルにする (raise しない)"""
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
                    # full_name 欠落
                    {"name": "email", "values": ["a@example.com"]},
                ],
            },
        ]
        client._get = AsyncMock(side_effect=[form, {"data": leads}])

        out: Path = tmp_path / "out.csv"  # type: ignore[assignment]
        count = await client.export_leads_to_csv("form_1", out)
        assert count == 1
        rows = out.read_text(encoding="utf-8").splitlines()
        # 欠落セルは空 — 値そのものを assert するため csv パーサで読む
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
        """値が ``=``, ``+``, ``-``, ``@``, タブ, CR で始まると
        spreadsheet で formula として実行される (CSV injection)。
        helper は単一引用符を先頭に付けて無害化する。"""
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
        """multi-select の値は ``" | "`` で結合 — 値自体に comma が
        含まれても spreadsheet 上で意味が壊れない"""
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
        """1 ページに収まらない件数の lead も全件取得する"""
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
        # 2nd & 3rd call は paging.next の URL を path にして呼ぶ —
        # 4 回目以降は呼ばれない (= ループ終了が正常)
        assert client._get.await_count == 3

    @pytest.mark.asyncio
    async def test_csv_pagination_uses_relative_path_with_after_cursor(
        self,
        client: LeadsMixin,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        """``paging.next`` は絶対 URL だが ``_get`` は BASE_URL を必ず
        前置するため、絶対 URL を path に渡すと URL が二重連結されて
        404 になる。helper は ``after`` cursor だけ抜き出して相対 path
        で再呼び出しすべきこと。
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

        # 2 回目の lead fetch (= 3 番目の _get 呼び出し) は
        # 相対 path を維持し、after cursor だけ params に渡す。
        third_call = client._get.await_args_list[2]
        third_path, third_params = third_call.args[0], third_call.args[1]
        assert third_path == "/form_1/leads"
        assert third_params.get("after") == "CURSOR_ABC"
        # 既存の fields / limit も保持される
        assert "fields" in third_params
        assert third_params.get("limit") == 1000
