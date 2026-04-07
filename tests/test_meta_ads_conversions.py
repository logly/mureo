"""Meta Ads Conversions API (CAPI) ユニットテスト

send_event / send_purchase_event / send_lead_event および
ハッシュ化ユーティリティ（hash_email, hash_phone, normalize_user_data）をテストする。
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest

from mureo.meta_ads._hash_utils import (
    hash_email,
    hash_phone,
    normalize_user_data,
)
from mureo.meta_ads._conversions import ConversionsMixin


# ---------------------------------------------------------------------------
# ヘルパー: ConversionsMixinをテスト可能にするモッククラス
# ---------------------------------------------------------------------------


def _make_conversions_client() -> ConversionsMixin:
    """ConversionsMixinにモック _post を付与したインスタンスを生成"""

    class MockClient(ConversionsMixin):
        def __init__(self) -> None:
            self._post = AsyncMock(  # type: ignore[assignment]
                return_value={"events_received": 1, "fbtrace_id": "trace123"}
            )

    return MockClient()


# ===========================================================================
# hash_email テスト
# ===========================================================================


@pytest.mark.unit
class TestHashEmail:
    def test_basic(self) -> None:
        """メールをSHA-256ハッシュ化"""
        result = hash_email("Test@Example.COM")
        expected = hashlib.sha256("test@example.com".encode()).hexdigest()
        assert result == expected

    def test_strips_whitespace(self) -> None:
        """前後の空白を除去してからハッシュ化"""
        result = hash_email("  user@test.com  ")
        expected = hashlib.sha256("user@test.com".encode()).hexdigest()
        assert result == expected


# ===========================================================================
# hash_phone テスト
# ===========================================================================


@pytest.mark.unit
class TestHashPhone:
    def test_basic(self) -> None:
        """電話番号を数字のみに正規化してSHA-256ハッシュ化"""
        result = hash_phone("+81-90-1234-5678")
        expected = hashlib.sha256("819012345678".encode()).hexdigest()
        assert result == expected

    def test_strips_spaces_and_parens(self) -> None:
        """スペース・括弧・ハイフンを除去"""
        result = hash_phone("(090) 1234-5678")
        expected = hashlib.sha256("09012345678".encode()).hexdigest()
        assert result == expected


# ===========================================================================
# normalize_user_data テスト
# ===========================================================================


@pytest.mark.unit
class TestNormalizeUserData:
    def test_hashes_em_and_ph(self) -> None:
        """em(email)とph(phone)を自動ハッシュ化"""
        user_data = {
            "em": "user@example.com",
            "ph": "+81901234567",
            "client_ip_address": "1.2.3.4",
            "client_user_agent": "Mozilla/5.0",
        }
        result = normalize_user_data(user_data)
        # emとphはハッシュ化される
        assert result["em"] == hash_email("user@example.com")
        assert result["ph"] == hash_phone("+81901234567")
        # 非PIIフィールドはそのまま
        assert result["client_ip_address"] == "1.2.3.4"
        assert result["client_user_agent"] == "Mozilla/5.0"

    def test_already_hashed_skips(self) -> None:
        """既にSHA-256ハッシュ済み（64文字の16進数）ならスキップ"""
        already_hashed = hashlib.sha256("test@example.com".encode()).hexdigest()
        user_data = {
            "em": already_hashed,
            "ph": hashlib.sha256("09012345678".encode()).hexdigest(),
        }
        result = normalize_user_data(user_data)
        assert result["em"] == already_hashed
        assert result["ph"] == user_data["ph"]

    def test_list_values_hashed(self) -> None:
        """emやphがリスト形式の場合も各要素をハッシュ化"""
        user_data = {
            "em": ["user1@example.com", "user2@example.com"],
        }
        result = normalize_user_data(user_data)
        assert isinstance(result["em"], list)
        assert result["em"][0] == hash_email("user1@example.com")
        assert result["em"][1] == hash_email("user2@example.com")

    def test_handles_fn_ln_and_other_pii_fields(self) -> None:
        """fn(名), ln(姓)等のPIIフィールドもハッシュ化"""
        user_data = {
            "fn": "Taro",
            "ln": "Yamada",
            "ct": "Tokyo",
            "st": "Tokyo",
            "zp": "1000001",
            "country": "jp",
        }
        result = normalize_user_data(user_data)
        assert result["fn"] == hashlib.sha256("taro".encode()).hexdigest()
        assert result["ln"] == hashlib.sha256("yamada".encode()).hexdigest()
        assert result["ct"] == hashlib.sha256("tokyo".encode()).hexdigest()
        assert result["st"] == hashlib.sha256("tokyo".encode()).hexdigest()
        assert result["zp"] == hashlib.sha256("1000001".encode()).hexdigest()
        assert result["country"] == hashlib.sha256("jp".encode()).hexdigest()


# ===========================================================================
# ConversionsMixin.send_event テスト
# ===========================================================================


@pytest.mark.unit
class TestSendEvent:
    @pytest.fixture()
    def client(self) -> ConversionsMixin:
        return _make_conversions_client()

    @pytest.mark.asyncio
    async def test_send_event(self, client: ConversionsMixin) -> None:
        """正常にイベントを送信"""
        events = [
            {
                "event_name": "Purchase",
                "event_time": 1700000000,
                "action_source": "website",
                "user_data": {
                    "em": hashlib.sha256("test@example.com".encode()).hexdigest(),
                    "client_ip_address": "1.2.3.4",
                },
                "custom_data": {"currency": "USD", "value": 100.0},
            }
        ]
        result = await client.send_event("pixel123", events)

        assert result["events_received"] == 1
        client._post.assert_called_once()  # type: ignore[union-attr]
        call_args = client._post.call_args  # type: ignore[union-attr]
        assert "/pixel123/events" in call_args[0][0]

        # dataパラメータにイベントが含まれる
        post_data = call_args[1].get("data") or call_args[0][1]
        assert "data" in post_data

    @pytest.mark.asyncio
    async def test_send_event_with_test_code(self, client: ConversionsMixin) -> None:
        """テストイベントコード付きで送信"""
        events = [
            {
                "event_name": "Lead",
                "event_time": 1700000000,
                "action_source": "website",
                "user_data": {"client_ip_address": "1.2.3.4"},
            }
        ]
        result = await client.send_event(
            "pixel123", events, test_event_code="TEST12345"
        )

        assert result["events_received"] == 1
        call_args = client._post.call_args  # type: ignore[union-attr]
        post_data = call_args[1].get("data") or call_args[0][1]
        assert post_data.get("test_event_code") == "TEST12345"

    @pytest.mark.asyncio
    async def test_send_event_api_error(self, client: ConversionsMixin) -> None:
        """APIエラー時にRuntimeErrorを伝搬"""
        client._post = AsyncMock(  # type: ignore[assignment]
            side_effect=RuntimeError("Meta API request failed")
        )
        events = [
            {
                "event_name": "Purchase",
                "event_time": 1700000000,
                "action_source": "website",
                "user_data": {"client_ip_address": "1.2.3.4"},
            }
        ]
        with pytest.raises(RuntimeError, match="Meta API"):
            await client.send_event("pixel123", events)


# ===========================================================================
# ConversionsMixin.send_purchase_event テスト
# ===========================================================================


@pytest.mark.unit
class TestSendPurchaseEvent:
    @pytest.fixture()
    def client(self) -> ConversionsMixin:
        return _make_conversions_client()

    @pytest.mark.asyncio
    async def test_send_purchase_event(self, client: ConversionsMixin) -> None:
        """購入イベントを正しい形式で送信"""
        user_data = {
            "em": "buyer@example.com",
            "client_ip_address": "1.2.3.4",
        }
        result = await client.send_purchase_event(
            pixel_id="pixel123",
            event_time=1700000000,
            user_data=user_data,
            currency="JPY",
            value=9800.0,
            content_ids=["product_001"],
            event_source_url="https://example.com/checkout",
        )

        assert result["events_received"] == 1
        call_args = client._post.call_args  # type: ignore[union-attr]
        post_data = call_args[1].get("data") or call_args[0][1]

        # dataフィールドのイベント確認
        import json

        events = json.loads(post_data["data"])
        event = events[0]
        assert event["event_name"] == "Purchase"
        assert event["event_time"] == 1700000000
        assert event["action_source"] == "website"
        assert event["event_source_url"] == "https://example.com/checkout"
        assert event["custom_data"]["currency"] == "JPY"
        assert event["custom_data"]["value"] == 9800.0
        assert event["custom_data"]["content_ids"] == ["product_001"]


# ===========================================================================
# ConversionsMixin.send_lead_event テスト
# ===========================================================================


@pytest.mark.unit
class TestSendLeadEvent:
    @pytest.fixture()
    def client(self) -> ConversionsMixin:
        return _make_conversions_client()

    @pytest.mark.asyncio
    async def test_send_lead_event(self, client: ConversionsMixin) -> None:
        """リードイベントを正しい形式で送信"""
        user_data = {
            "em": "lead@example.com",
            "client_ip_address": "10.0.0.1",
        }
        result = await client.send_lead_event(
            pixel_id="pixel456",
            event_time=1700001000,
            user_data=user_data,
            event_source_url="https://example.com/contact",
            test_event_code="TEST99",
        )

        assert result["events_received"] == 1
        call_args = client._post.call_args  # type: ignore[union-attr]
        post_data = call_args[1].get("data") or call_args[0][1]

        import json

        events = json.loads(post_data["data"])
        event = events[0]
        assert event["event_name"] == "Lead"
        assert event["event_time"] == 1700001000
        assert event["action_source"] == "website"
        assert event["event_source_url"] == "https://example.com/contact"
        assert post_data.get("test_event_code") == "TEST99"
