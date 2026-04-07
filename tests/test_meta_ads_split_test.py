"""Meta Ads Split Test (A/Bテスト) ユニットテスト

SplitTestMixinの全メソッドをモックベースでテストする。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mureo.meta_ads._split_test import SplitTestMixin


# ---------------------------------------------------------------------------
# ヘルパー: Mixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_mock_client() -> SplitTestMixin:
    """SplitTestMixinにモック _get/_post を付与したインスタンスを生成"""

    class MockClient(SplitTestMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "study_001"})

    return MockClient()


# ===========================================================================
# SplitTestMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestSplitTestMixin:
    @pytest.fixture()
    def client(self) -> SplitTestMixin:
        return _make_mock_client()

    # -----------------------------------------------------------------------
    # 1. test_list_split_tests
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_split_tests(self, client: SplitTestMixin) -> None:
        """スプリットテスト一覧を取得できること"""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {"id": "study_001", "name": "CPA比較テスト"},
                    {"id": "study_002", "name": "クリエイティブテスト"},
                ]
            }
        )
        result = await client.list_split_tests()
        assert len(result) == 2
        assert result[0]["id"] == "study_001"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/act_123/ad_studies" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 2. test_get_split_test
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_split_test(self, client: SplitTestMixin) -> None:
        """スプリットテスト詳細を取得できること"""
        client._get = AsyncMock(
            return_value={
                "id": "study_001",
                "name": "CPA比較テスト",
                "type": "SPLIT_TEST",
                "start_time": "2024-01-01T00:00:00+0000",
                "end_time": "2024-01-15T00:00:00+0000",
            }
        )
        result = await client.get_split_test("study_001")
        assert result["id"] == "study_001"
        assert result["type"] == "SPLIT_TEST"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/study_001" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 3. test_create_split_test
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_split_test(self, client: SplitTestMixin) -> None:
        """スプリットテストをデフォルト信頼度(95)で作成できること"""
        client._post = AsyncMock(return_value={"id": "study_new"})
        cells = [
            {"name": "Control", "adsets": ["adset_1"]},
            {"name": "Test", "adsets": ["adset_2"]},
        ]
        objectives = [{"type": "COST_PER_RESULT"}]
        result = await client.create_split_test(
            name="CPA比較テスト",
            cells=cells,
            objectives=objectives,
            start_time="2024-01-01T00:00:00+0000",
            end_time="2024-01-15T00:00:00+0000",
        )
        assert result["id"] == "study_new"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/act_123/ad_studies" in call_args[0][0]
        data = call_args[1].get("data") or call_args[0][1]
        assert data["name"] == "CPA比較テスト"
        assert data["confidence_level"] == 95

    # -----------------------------------------------------------------------
    # 4. test_create_split_test_custom_confidence
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_split_test_custom_confidence(
        self, client: SplitTestMixin
    ) -> None:
        """カスタム信頼度でスプリットテストを作成できること"""
        client._post = AsyncMock(return_value={"id": "study_custom"})
        cells = [
            {"name": "A", "adsets": ["adset_a"]},
            {"name": "B", "adsets": ["adset_b"]},
        ]
        objectives = [{"type": "COST_PER_RESULT"}]
        result = await client.create_split_test(
            name="カスタム信頼度テスト",
            cells=cells,
            objectives=objectives,
            start_time="2024-02-01T00:00:00+0000",
            end_time="2024-02-15T00:00:00+0000",
            confidence_level=90,
        )
        assert result["id"] == "study_custom"
        call_args = client._post.call_args
        data = call_args[1].get("data") or call_args[0][1]
        assert data["confidence_level"] == 90

    # -----------------------------------------------------------------------
    # 5. test_end_split_test
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_end_split_test(self, client: SplitTestMixin) -> None:
        """スプリットテストを終了できること"""
        client._post = AsyncMock(return_value={"success": True})
        result = await client.end_split_test("study_001")
        assert result["success"] is True
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/study_001" in call_args[0][0]

    # -----------------------------------------------------------------------
    # 6. test_list_split_tests_empty
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_list_split_tests_empty(self, client: SplitTestMixin) -> None:
        """スプリットテストがない場合に空リストを返すこと"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.list_split_tests()
        assert result == []

    # -----------------------------------------------------------------------
    # 7. test_api_error
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_api_error(self, client: SplitTestMixin) -> None:
        """APIエラー時にRuntimeErrorが伝播すること"""
        client._get = AsyncMock(side_effect=RuntimeError("Meta API request failed"))
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.list_split_tests()

    # -----------------------------------------------------------------------
    # 8. test_create_split_test_invalid_confidence
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_create_split_test_invalid_confidence(
        self, client: SplitTestMixin
    ) -> None:
        """無効なconfidence_levelでValueErrorが発生すること"""
        cells = [
            {"name": "A", "adsets": ["adset_a"]},
            {"name": "B", "adsets": ["adset_b"]},
        ]
        objectives = [{"type": "COST_PER_RESULT"}]
        with pytest.raises(ValueError, match="confidence_level"):
            await client.create_split_test(
                name="無効テスト",
                cells=cells,
                objectives=objectives,
                start_time="2024-01-01T00:00:00+0000",
                end_time="2024-01-15T00:00:00+0000",
                confidence_level=99,
            )

    # -----------------------------------------------------------------------
    # 9. test_get_split_test_with_results
    # -----------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_get_split_test_with_results(self, client: SplitTestMixin) -> None:
        """結果付きスプリットテスト詳細を取得できること"""
        client._get = AsyncMock(
            return_value={
                "id": "study_001",
                "name": "CPA比較テスト",
                "type": "SPLIT_TEST",
                "results": [
                    {"cell_id": "cell_1", "winner": True},
                    {"cell_id": "cell_2", "winner": False},
                ],
            }
        )
        result = await client.get_split_test("study_001")
        assert "results" in result
        assert len(result["results"]) == 2
