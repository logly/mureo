"""Meta Ads Instagram/ページ投稿連携 ユニットテスト

PagePostsMixin / InstagramMixin の _get / _post をモックしてテストする。
MCPツールハンドラーのテストも含む。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from mureo.meta_ads._page_posts import PagePostsMixin
from mureo.meta_ads._instagram import InstagramMixin


# ---------------------------------------------------------------------------
# ヘルパー: Mixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_page_posts_client() -> PagePostsMixin:
    """PagePostsMixinにモック _get/_post/_ad_account_id を付与したインスタンスを生成"""

    class MockClient(PagePostsMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})

    return MockClient()


def _make_instagram_client() -> InstagramMixin:
    """InstagramMixinにモック _get/_post/_ad_account_id を付与したインスタンスを生成"""

    class MockClient(InstagramMixin):
        def __init__(self) -> None:
            self._ad_account_id = "act_123"
            self._get = AsyncMock(return_value={"data": []})
            self._post = AsyncMock(return_value={"id": "new_id"})

    return MockClient()


# ===========================================================================
# PagePostsMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestListPagePosts:
    @pytest.fixture()
    def client(self) -> PagePostsMixin:
        return _make_page_posts_client()

    @pytest.mark.asyncio
    async def test_list_page_posts(self, client: PagePostsMixin) -> None:
        """ページ投稿一覧を取得できること"""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "111_222",
                        "message": "テスト投稿",
                        "created_time": "2026-01-01T00:00:00+0000",
                        "permalink_url": "https://www.facebook.com/111/posts/222",
                    },
                    {
                        "id": "111_333",
                        "message": "2番目の投稿",
                        "created_time": "2026-01-02T00:00:00+0000",
                        "permalink_url": "https://www.facebook.com/111/posts/333",
                    },
                ]
            }
        )
        result = await client.list_page_posts("111")

        assert len(result) == 2
        assert result[0]["id"] == "111_222"
        assert result[0]["message"] == "テスト投稿"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/111/posts" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_page_posts_empty(self, client: PagePostsMixin) -> None:
        """投稿がない場合は空リストが返ること"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.list_page_posts("111")

        assert result == []

    @pytest.mark.asyncio
    async def test_list_page_posts_with_limit(self, client: PagePostsMixin) -> None:
        """limit指定が渡ること"""
        client._get = AsyncMock(return_value={"data": []})
        await client.list_page_posts("111", limit=10)

        call_args = client._get.call_args
        params = call_args[0][1]
        assert params["limit"] == 10


@pytest.mark.unit
class TestBoostPost:
    @pytest.fixture()
    def client(self) -> PagePostsMixin:
        return _make_page_posts_client()

    @pytest.mark.asyncio
    async def test_boost_post(self, client: PagePostsMixin) -> None:
        """ページ投稿を広告化できること"""
        client._post = AsyncMock(return_value={"id": "ad_999"})
        result = await client.boost_post(
            page_id="111",
            post_id="222",
            ad_set_id="adset_456",
        )

        assert result["id"] == "ad_999"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/act_123/ads" in call_args[0][0]
        data = call_args[0][1]
        creative = json.loads(data["creative"])
        assert creative["object_story_id"] == "111_222"
        assert data["adset_id"] == "adset_456"
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_boost_post_custom_name(self, client: PagePostsMixin) -> None:
        """カスタム名を指定して投稿を広告化できること"""
        client._post = AsyncMock(return_value={"id": "ad_999"})
        result = await client.boost_post(
            page_id="111",
            post_id="222",
            ad_set_id="adset_456",
            name="カスタム広告名",
        )

        call_args = client._post.call_args
        data = call_args[0][1]
        assert data["name"] == "カスタム広告名"

    @pytest.mark.asyncio
    async def test_boost_post_default_name(self, client: PagePostsMixin) -> None:
        """名前未指定の場合はデフォルト名が付くこと"""
        client._post = AsyncMock(return_value={"id": "ad_999"})
        await client.boost_post(
            page_id="111",
            post_id="222",
            ad_set_id="adset_456",
        )

        call_args = client._post.call_args
        data = call_args[0][1]
        assert "111_222" in data["name"]

    @pytest.mark.asyncio
    async def test_boost_post_api_error(self, client: PagePostsMixin) -> None:
        """APIエラー時にRuntimeErrorが発生すること"""
        client._post = AsyncMock(side_effect=RuntimeError("Meta API request failed"))
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.boost_post(
                page_id="111",
                post_id="222",
                ad_set_id="adset_456",
            )


# ===========================================================================
# InstagramMixin テスト
# ===========================================================================


@pytest.mark.unit
class TestListInstagramAccounts:
    @pytest.fixture()
    def client(self) -> InstagramMixin:
        return _make_instagram_client()

    @pytest.mark.asyncio
    async def test_list_instagram_accounts(self, client: InstagramMixin) -> None:
        """連携Instagramアカウント一覧を取得できること"""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "ig_111",
                        "username": "testuser",
                        "profile_pic": "https://example.com/pic.jpg",
                    },
                ]
            }
        )
        result = await client.list_instagram_accounts()

        assert len(result) == 1
        assert result[0]["id"] == "ig_111"
        assert result[0]["username"] == "testuser"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/act_123/instagram_accounts" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_instagram_accounts_empty(self, client: InstagramMixin) -> None:
        """Instagramアカウントがない場合は空リストが返ること"""
        client._get = AsyncMock(return_value={"data": []})
        result = await client.list_instagram_accounts()
        assert result == []


@pytest.mark.unit
class TestListInstagramMedia:
    @pytest.fixture()
    def client(self) -> InstagramMixin:
        return _make_instagram_client()

    @pytest.mark.asyncio
    async def test_list_instagram_media(self, client: InstagramMixin) -> None:
        """Instagram投稿一覧を取得できること"""
        client._get = AsyncMock(
            return_value={
                "data": [
                    {
                        "id": "media_111",
                        "caption": "テスト投稿",
                        "media_type": "IMAGE",
                        "media_url": "https://example.com/img.jpg",
                        "permalink": "https://www.instagram.com/p/xxx/",
                        "timestamp": "2026-01-01T00:00:00+0000",
                    },
                    {
                        "id": "media_222",
                        "caption": "動画投稿",
                        "media_type": "VIDEO",
                        "media_url": "https://example.com/vid.mp4",
                        "permalink": "https://www.instagram.com/p/yyy/",
                        "timestamp": "2026-01-02T00:00:00+0000",
                    },
                ]
            }
        )
        result = await client.list_instagram_media("ig_111")

        assert len(result) == 2
        assert result[0]["id"] == "media_111"
        assert result[0]["media_type"] == "IMAGE"
        client._get.assert_called_once()
        call_args = client._get.call_args
        assert "/ig_111/media" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_list_instagram_media_with_limit(
        self, client: InstagramMixin
    ) -> None:
        """limit指定が渡ること"""
        client._get = AsyncMock(return_value={"data": []})
        await client.list_instagram_media("ig_111", limit=5)

        call_args = client._get.call_args
        params = call_args[0][1]
        assert params["limit"] == 5


@pytest.mark.unit
class TestBoostInstagramPost:
    @pytest.fixture()
    def client(self) -> InstagramMixin:
        return _make_instagram_client()

    @pytest.mark.asyncio
    async def test_boost_instagram_post(self, client: InstagramMixin) -> None:
        """Instagram投稿を広告化できること"""
        client._post = AsyncMock(return_value={"id": "ad_888"})
        result = await client.boost_instagram_post(
            ig_user_id="ig_111",
            media_id="media_222",
            ad_set_id="adset_456",
        )

        assert result["id"] == "ad_888"
        client._post.assert_called_once()
        call_args = client._post.call_args
        assert "/act_123/ads" in call_args[0][0]
        data = call_args[0][1]
        creative = json.loads(data["creative"])
        assert creative["object_story_id"] == "ig_111_media_222"
        assert "instagram_actor_id" in creative
        assert creative["instagram_actor_id"] == "ig_111"
        assert data["adset_id"] == "adset_456"
        assert data["status"] == "PAUSED"

    @pytest.mark.asyncio
    async def test_boost_instagram_post_custom_name(
        self, client: InstagramMixin
    ) -> None:
        """カスタム名を指定してInstagram投稿を広告化できること"""
        client._post = AsyncMock(return_value={"id": "ad_888"})
        await client.boost_instagram_post(
            ig_user_id="ig_111",
            media_id="media_222",
            ad_set_id="adset_456",
            name="Instagram広告",
        )

        call_args = client._post.call_args
        data = call_args[0][1]
        assert data["name"] == "Instagram広告"

    @pytest.mark.asyncio
    async def test_boost_instagram_post_api_error(self, client: InstagramMixin) -> None:
        """APIエラー時にRuntimeErrorが発生すること"""
        client._post = AsyncMock(side_effect=RuntimeError("Meta API request failed"))
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.boost_instagram_post(
                ig_user_id="ig_111",
                media_id="media_222",
                ad_set_id="adset_456",
            )
