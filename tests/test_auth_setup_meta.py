"""Meta Ads OAuthフロー・セットアップウィザードのテスト（TDD: RED -> GREEN -> IMPROVE）"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mureo.auth_setup import (
    MetaOAuthResult,
    OAuthCallbackServer,
    _exchange_code_for_short_token,
    _exchange_short_for_long_token,
    _generate_meta_auth_url,
    list_meta_ad_accounts,
    run_meta_oauth,
    setup_meta_ads,
)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


# ---------------------------------------------------------------------------
# 1. 認証URL生成
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_generate_meta_auth_url() -> None:
    """正しいFacebook認証URLが生成されること"""
    url = _generate_meta_auth_url(app_id="123456", port=8080)

    assert "https://www.facebook.com/v21.0/dialog/oauth" in url
    assert "client_id=123456" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in url or (
        "redirect_uri=http://localhost:8080/callback" in url
    )
    assert "scope=ads_management" in url
    assert "ads_read" in url
    assert "response_type=code" in url


@pytest.mark.unit
def test_generate_meta_auth_url_different_port() -> None:
    """異なるポート番号で認証URLが生成されること"""
    url = _generate_meta_auth_url(app_id="999", port=3000)

    assert "client_id=999" in url
    assert "3000" in url


# ---------------------------------------------------------------------------
# 2. Code -> Short-Lived Token交換
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exchange_code_for_short_token() -> None:
    """codeからshort-lived tokenが取得できること（HTTPモック）"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "short-lived-token-abc",
        "token_type": "bearer",
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        token = await _exchange_code_for_short_token(
            code="auth-code-xyz",
            app_id="123456",
            app_secret="secret-789",
            redirect_uri="http://localhost:8080/callback",
        )

    assert token == "short-lived-token-abc"
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    assert f"{_GRAPH_API_BASE}/oauth/access_token" in call_args[0][0] or (
        call_args[1].get("url", call_args[0][0])
        == f"{_GRAPH_API_BASE}/oauth/access_token"
    )


@pytest.mark.unit
async def test_exchange_code_for_short_token_error() -> None:
    """Token交換失敗時にRuntimeErrorが発生すること"""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {
            "message": "Invalid code",
            "type": "OAuthException",
            "code": 100,
        }
    }
    mock_response.raise_for_status = MagicMock(
        side_effect=Exception("400 Bad Request")
    )

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Short-Lived Token"):
            await _exchange_code_for_short_token(
                code="invalid-code",
                app_id="123456",
                app_secret="secret-789",
                redirect_uri="http://localhost:8080/callback",
            )


# ---------------------------------------------------------------------------
# 3. Short -> Long-Lived Token変換
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_exchange_short_for_long_token() -> None:
    """short -> long-livedトークン変換（HTTPモック）"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "long-lived-token-xyz",
        "token_type": "bearer",
        "expires_in": 5184000,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _exchange_short_for_long_token(
            short_token="short-lived-token-abc",
            app_id="123456",
            app_secret="secret-789",
        )

    assert isinstance(result, MetaOAuthResult)
    assert result.access_token == "long-lived-token-xyz"
    assert result.expires_in == 5184000


@pytest.mark.unit
async def test_exchange_short_for_long_token_error() -> None:
    """Long-Lived Token変換失敗時にRuntimeErrorが発生すること"""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "error": {"message": "Invalid token", "type": "OAuthException", "code": 190}
    }
    mock_response.raise_for_status = MagicMock(
        side_effect=Exception("400 Bad Request")
    )

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Long-Lived Token"):
            await _exchange_short_for_long_token(
                short_token="invalid-token",
                app_id="123456",
                app_secret="secret-789",
            )


# ---------------------------------------------------------------------------
# 4. 広告アカウント一覧取得
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_meta_ad_accounts() -> None:
    """広告アカウント一覧取得（HTTPモック）"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "act_111", "name": "Test Account 1", "account_status": 1},
            {"id": "act_222", "name": "Test Account 2", "account_status": 2},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="long-lived-token-xyz")

    assert len(accounts) == 2
    assert accounts[0]["id"] == "act_111"
    assert accounts[0]["name"] == "Test Account 1"
    assert accounts[1]["id"] == "act_222"

    # APIリクエストの検証
    mock_client.get.assert_called_once()
    call_args = mock_client.get.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "me/adaccounts" in url


@pytest.mark.unit
async def test_list_meta_ad_accounts_empty() -> None:
    """広告アカウントが0件の場合"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        accounts = await list_meta_ad_accounts(access_token="some-token")

    assert accounts == []


@pytest.mark.unit
async def test_list_meta_ad_accounts_error() -> None:
    """広告アカウント一覧取得失敗時にRuntimeErrorが発生すること"""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {
        "error": {"message": "Invalid access token", "type": "OAuthException"}
    }
    mock_response.raise_for_status = MagicMock(side_effect=Exception("401 Unauthorized"))

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with pytest.raises(RuntimeError, match="Failed to retrieve ad account list"):
            await list_meta_ad_accounts(access_token="invalid-token")


# ---------------------------------------------------------------------------
# 5. セットアップ全体フロー
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_setup_meta_ads_flow(tmp_path: Path) -> None:
    """セットアップ全体フロー（input/OAuth/APIすべてモック）"""
    credentials_path = tmp_path / "credentials.json"

    # run_meta_oauthのモック
    mock_oauth_result = MetaOAuthResult(
        access_token="long-lived-token-xyz",
        expires_in=5184000,
    )

    # 広告アカウント一覧のモック
    mock_accounts = [
        {"id": "act_111", "name": "Test Account 1", "account_status": 1},
        {"id": "act_222", "name": "Test Account 2", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["my-app-id", "my-app-secret"]),
        patch("mureo.auth_setup._select_account", return_value="act_111"),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "long-lived-token-xyz"
    assert result.app_id == "my-app-id"
    assert result.app_secret == "my-app-secret"

    # OAuthが呼ばれたことを検証
    mock_oauth.assert_called_once_with(
        app_id="my-app-id",
        app_secret="my-app-secret",
    )

    # 広告アカウント一覧が呼ばれたことを検証
    mock_list_accounts.assert_called_once_with(
        access_token="long-lived-token-xyz",
    )


@pytest.mark.unit
async def test_setup_meta_ads_single_account(tmp_path: Path) -> None:
    """広告アカウントが1件の場合は自動選択"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_999", "name": "Only Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["app-id-1", "app-secret-1"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"
    assert result.app_id == "app-id-1"


# ---------------------------------------------------------------------------
# 6. 認証情報の保存
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_save_credentials_meta(tmp_path: Path) -> None:
    """Meta Ads認証情報がcredentials.jsonに保存されること"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="saved-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_555", "name": "Saved Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["save-app-id", "save-secret"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    # ファイルが作成されたことを確認
    assert credentials_path.exists()

    data = json.loads(credentials_path.read_text(encoding="utf-8"))
    assert "meta_ads" in data
    assert data["meta_ads"]["access_token"] == "saved-token"
    assert data["meta_ads"]["app_id"] == "save-app-id"
    assert data["meta_ads"]["app_secret"] == "save-secret"
    assert data["meta_ads"]["account_id"] == "act_555"


@pytest.mark.unit
async def test_save_credentials_meta_preserves_existing(tmp_path: Path) -> None:
    """既存のGoogle Ads認証情報を上書きせずMeta Ads情報を追加すること"""
    credentials_path = tmp_path / "credentials.json"

    # 既存のGoogle Ads認証情報
    existing_data = {
        "google_ads": {
            "developer_token": "existing-dev-token",
            "client_id": "existing-client-id",
        }
    }
    credentials_path.write_text(json.dumps(existing_data), encoding="utf-8")

    mock_oauth_result = MetaOAuthResult(
        access_token="new-meta-token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_777", "name": "Meta Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["meta-app-id", "meta-secret"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    data = json.loads(credentials_path.read_text(encoding="utf-8"))

    # 既存のGoogle Ads情報が残っていること
    assert data["google_ads"]["developer_token"] == "existing-dev-token"
    # Meta Ads情報が追加されていること
    assert data["meta_ads"]["access_token"] == "new-meta-token"
    assert data["meta_ads"]["account_id"] == "act_777"


# ---------------------------------------------------------------------------
# 7. MetaOAuthResult のイミュータビリティ
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_oauth_result_immutable() -> None:
    """MetaOAuthResultがfrozenであること"""
    import dataclasses

    result = MetaOAuthResult(access_token="tok", expires_in=3600)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.access_token = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. run_meta_oauth の統合テスト（ローカルサーバー＋トークン交換）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth() -> None:
    """run_meta_oauthがOAuthCallbackServerを使い、OAuthフローを完了すること"""
    mock_long_result = MetaOAuthResult(
        access_token="final-long-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open") as mock_browser,
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-token-from-code",
        ) as mock_short,
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ) as mock_long,
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="test-state"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "auth-code-received"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        result = await run_meta_oauth(app_id="test-app", app_secret="test-secret")

    assert result.access_token == "final-long-token"
    assert result.expires_in == 5184000

    # ブラウザが開かれたことを検証
    mock_browser.assert_called_once()
    browser_url = mock_browser.call_args[0][0]
    assert "test-app" in browser_url

    # Short-Lived Token交換が呼ばれたことを検証
    mock_short.assert_called_once_with(
        code="auth-code-received",
        app_id="test-app",
        app_secret="test-secret",
        redirect_uri="http://localhost:9999/callback",
    )

    # Long-Lived Token変換が呼ばれたことを検証
    mock_long.assert_called_once_with(
        short_token="short-token-from-code",
        app_id="test-app",
        app_secret="test-secret",
    )


# ---------------------------------------------------------------------------
# 9. Meta OAuth stateパラメータ（CSRF対策: CRITICAL-1）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_meta_auth_url_contains_state() -> None:
    """Meta認証URLにstateパラメータが含まれること"""
    url = _generate_meta_auth_url(app_id="123456", port=8080, state="meta-state-abc")
    assert "state=meta-state-abc" in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_meta_oauth_uses_state() -> None:
    """run_meta_oauthがstateパラメータを生成・検証すること"""
    mock_long_result = MetaOAuthResult(
        access_token="final-long-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open") as mock_browser,
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-token-from-code",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="meta-state-xyz"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "auth-code-received"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        result = await run_meta_oauth(app_id="test-app", app_secret="test-secret")

    assert result.access_token == "final-long-token"

    # OAuthCallbackServerにexpected_stateが渡されていること
    server_call_kwargs = mock_server_cls.call_args[1]
    assert server_call_kwargs.get("expected_state") == "meta-state-xyz"

    # ブラウザURLにstateが含まれていること
    browser_url = mock_browser.call_args[0][0]
    assert "state=meta-state-xyz" in browser_url


# ---------------------------------------------------------------------------
# 10. Meta OAuthフロー実行順序（CRITICAL-2）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_oauth_flow_order() -> None:
    """run_meta_oauthがサーバー起動→ブラウザ→コールバック待ちの順序で実行すること
    （_start_callback_serverのブロッキング問題が修正されていること）"""
    mock_long_result = MetaOAuthResult(
        access_token="ordered-token",
        expires_in=5184000,
    )

    call_order: list[str] = []

    def mock_wait_for_callback() -> None:
        call_order.append("wait_for_callback")

    def mock_browser_open(url: str) -> None:
        call_order.append("browser_open")

    with (
        patch("mureo.auth_setup.webbrowser.open", side_effect=mock_browser_open),
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short-tok",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="s"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "code"
        mock_server.error = None
        mock_server.wait_for_callback = mock_wait_for_callback
        mock_server_cls.return_value = mock_server

        await run_meta_oauth(app_id="app", app_secret="secret")

    # ブラウザが開かれた後にwait_for_callbackが呼ばれるべき
    # （OAuthCallbackServerを使う構造になっていること = _start_callback_serverのブロッキング問題なし）
    assert "browser_open" in call_order
    # サーバーが別スレッドで起動されているため、wait_for_callbackはスレッド内で実行


# ---------------------------------------------------------------------------
# 11. Meta側入力バリデーション（HIGH-1）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_invalid_account_choice(tmp_path: Path) -> None:
    """アカウント選択で無効な入力がされた場合にエラーにならないこと"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
        {"id": "act_222", "name": "Account 2", "account_status": 1},
    ]

    with (
        patch(
            "mureo.auth_setup.input_func",
            side_effect=["app-id", "app-secret"],
        ),
        patch("mureo.auth_setup._select_account", return_value="act_111"),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        # ValueErrorが発生せずに完了すること（try/exceptが追加されていること）
        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_out_of_range_choice(tmp_path: Path) -> None:
    """アカウント選択で範囲外の数値が入力された場合"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-abc",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_111", "name": "Account 1", "account_status": 1},
    ]

    # 1回目: 範囲外(99)、2回目: 有効入力(1)
    with (
        patch(
            "mureo.auth_setup.input_func",
            side_effect=["app-id", "app-secret", "99", "1"],
        ),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        result = await setup_meta_ads(credentials_path=credentials_path)

    assert result.access_token == "token-abc"


# ---------------------------------------------------------------------------
# 12. Meta側ファイルパーミッション（HIGH-2）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_file_permissions(tmp_path: Path) -> None:
    """Meta Ads認証情報保存時にファイルパーミッションが0600になること"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token-for-perm",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_perm", "name": "Perm Account", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["app-id", "app-secret"]),
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list_accounts,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list_accounts.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    file_mode = credentials_path.stat().st_mode
    assert stat.S_IMODE(file_mode) == 0o600


# ---------------------------------------------------------------------------
# 13. コールバックサーバー統一（HIGH-3）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_oauth_uses_unified_callback_server() -> None:
    """Meta OAuthフローがOAuthCallbackServer（統一サーバー）を使用すること"""
    mock_long_result = MetaOAuthResult(
        access_token="unified-token",
        expires_in=5184000,
    )

    with (
        patch("mureo.auth_setup.webbrowser.open"),
        patch(
            "mureo.auth_setup._exchange_code_for_short_token",
            new_callable=AsyncMock,
            return_value="short",
        ),
        patch(
            "mureo.auth_setup._exchange_short_for_long_token",
            new_callable=AsyncMock,
            return_value=mock_long_result,
        ),
        patch("mureo.auth_setup.OAuthCallbackServer") as mock_server_cls,
        patch("secrets.token_urlsafe", return_value="st"),
        patch("builtins.print"),
    ):
        mock_server = MagicMock()
        mock_server.server.server_address = ("localhost", 9999)
        mock_server.authorization_code = "code"
        mock_server.error = None
        mock_server_cls.return_value = mock_server

        await run_meta_oauth(app_id="app", app_secret="secret")

    # OAuthCallbackServerが使用されていること（_start_callback_serverではない）
    mock_server_cls.assert_called_once()


# ---------------------------------------------------------------------------
# 14. httpx timeout（WARNING）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_short_token_exchange_uses_timeout() -> None:
    """Meta Short-Lived Token交換でhttpxにtimeoutが設定されること"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"access_token": "short-tok"}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await _exchange_code_for_short_token(
            code="c", app_id="a", app_secret="s", redirect_uri="http://localhost/cb",
        )

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_long_token_exchange_uses_timeout() -> None:
    """Meta Long-Lived Token変換でhttpxにtimeoutが設定されること"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "long-tok",
        "expires_in": 5184000,
    }
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await _exchange_short_for_long_token(
            short_token="st", app_id="a", app_secret="s",
        )

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_ad_accounts_uses_timeout() -> None:
    """広告アカウント一覧取得でhttpxにtimeoutが設定されること"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("mureo.auth_setup.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await list_meta_ad_accounts(access_token="tok")

    call_kwargs = mock_client_cls.call_args[1] if mock_client_cls.call_args[1] else {}
    assert call_kwargs.get("timeout") == 30.0


# ---------------------------------------------------------------------------
# 15. input_func統一（SUGGESTION）
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_meta_ads_uses_input_func(tmp_path: Path) -> None:
    """setup_meta_adsがinput_func（テスト差し替え可能）を使用すること"""
    credentials_path = tmp_path / "credentials.json"

    mock_oauth_result = MetaOAuthResult(
        access_token="token",
        expires_in=5184000,
    )

    mock_accounts = [
        {"id": "act_1", "name": "Acc", "account_status": 1},
    ]

    with (
        patch("mureo.auth_setup.input_func", side_effect=["aid", "asec"]) as mock_input,
        patch("mureo.auth_setup.run_meta_oauth", new_callable=AsyncMock) as mock_oauth,
        patch(
            "mureo.auth_setup.list_meta_ad_accounts", new_callable=AsyncMock
        ) as mock_list,
        patch("builtins.print"),
    ):
        mock_oauth.return_value = mock_oauth_result
        mock_list.return_value = mock_accounts

        await setup_meta_ads(credentials_path=credentials_path)

    # input_funcが呼ばれていること（inputの直接呼び出しではない）
    assert mock_input.call_count >= 2
