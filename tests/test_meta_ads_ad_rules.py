"""Meta Ads Ad Rules (自動ルール) ユニットテスト

AdRulesMixinの全メソッドをモックベースでテストする。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from mureo.meta_ads._ad_rules import AdRulesMixin


# ---------------------------------------------------------------------------
# ヘルパー: Mixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_mock_client() -> AdRulesMixin:
    """AdRulesMixinにモック _get/_post/_delete を付与したインスタンスを生成"""

    class MockClient(AdRulesMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "rule_001"})
            self._delete = AsyncMock(return_value={"success": True})

    return MockClient()


# ===========================================================================
# AdRulesMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestAdRulesMixin:
    @pytest.fixture()
    def client(self) -> AdRulesMixin:
        return _make_mock_client()

    # -----------------------------------------------------------------------
    # 1. test_list_ad_rules
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_ad_rules(self, client: AdRulesMixin) -> None:
        """自動ルール一覧を取得できること"""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {"id": "rule_001", "name": "CPA高騰アラート"},
                    {"id": "rule_002", "name": "予算消化停止"},
                ]
            }
        )
        result = await client.list_ad_rules()
        assert len(result) == 2
        assert result[0]["id"] == "rule_001"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/act_123/adrules_library" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 2. test_get_ad_rule
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_ad_rule(self, client: AdRulesMixin) -> None:
        """自動ルール詳細を取得できること"""
        client._get = AsyncMock(
            return_value={
                "id": "rule_001",
                "name": "CPA高騰アラート",
                "evaluation_spec": {"evaluation_type": "TRIGGER"},
                "execution_spec": {"execution_type": "NOTIFICATION"},
            }
        )
        result = await client.get_ad_rule("rule_001")
        assert result["id"] == "rule_001"
        assert result["name"] == "CPA高騰アラート"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/rule_001" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 3. test_create_ad_rule
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_ad_rule(self, client: AdRulesMixin) -> None:
        """自動ルールを作成できること"""
        client._post = AsyncMock(return_value={"id": "rule_new"})
        evaluation_spec = {
            "evaluation_type": "TRIGGER",
            "filters": [
                {"field": "spent", "operator": "GREATER_THAN", "value": 1000},
            ],
        }
        execution_spec = {"execution_type": "PAUSE_CAMPAIGN"}
        result = await client.create_ad_rule(
            name="CPA高騰停止ルール",
            evaluation_spec=evaluation_spec,
            execution_spec=execution_spec,
        )
        assert result["id"] == "rule_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/act_123/adrules_library" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "CPA高騰停止ルール"

    # -----------------------------------------------------------------------
    # 4. test_update_ad_rule
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_update_ad_rule(self, client: AdRulesMixin) -> None:
        """自動ルールを更新できること"""
        client._post = AsyncMock(return_value={"success": True})
        result = await client.update_ad_rule(
            "rule_001", {"name": "更新後ルール名"}
        )
        assert result["success"] is True
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/rule_001" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "更新後ルール名"

    # -----------------------------------------------------------------------
    # 5. test_delete_ad_rule
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_delete_ad_rule(self, client: AdRulesMixin) -> None:
        """自動ルールを削除できること"""
        client._delete = AsyncMock(return_value={"success": True})
        result = await client.delete_ad_rule("rule_001")
        assert result["success"] is True
        client._delete.assert_called_once()
        call_args = client._delete.call_args
        assert "/rule_001" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 6. test_list_ad_rules_empty
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_ad_rules_empty(self, client: AdRulesMixin) -> None:
        """自動ルールがない場合に空リストを返すこと"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.list_ad_rules()
        assert result == []

    # -----------------------------------------------------------------------
    # 7. test_api_error
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_api_error(self, client: AdRulesMixin) -> None:
        """APIエラー時にRuntimeErrorが伝播すること"""
        client._get = AsyncMock(
            side_effect=RuntimeError("Meta API リクエストに失敗しました")
        )
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.list_ad_rules()

    # -----------------------------------------------------------------------
    # 8. test_create_ad_rule_notification
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_ad_rule_notification(
        self, client: AdRulesMixin
    ) -> None:
        """通知タイプの自動ルールを作成できること"""
        client._post = AsyncMock(return_value={"id": "rule_notify"})
        evaluation_spec = {
            "evaluation_type": "TRIGGER",
            "trigger": {
                "type": "METADATA_CREATION",
                "field": "entity_type",
                "value": "CAMPAIGN",
            },
            "filters": [
                {"field": "spent", "operator": "GREATER_THAN", "value": 1000},
            ],
        }
        execution_spec = {"execution_type": "NOTIFICATION"}
        result = await client.create_ad_rule(
            name="CPA高騰アラート",
            evaluation_spec=evaluation_spec,
            execution_spec=execution_spec,
        )
        assert result["id"] == "rule_notify"
        call_args = client._post.call_args
        data = call_args[1].get("data") or call_args[0][1]
        exec_spec = json.loads(data["execution_spec"])
        assert exec_spec["execution_type"] == "NOTIFICATION"
