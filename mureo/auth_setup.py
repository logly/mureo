"""認証セットアップウィザード

mureo auth setup で対話的に認証情報を設定する。
Google Ads: Developer Token入力 -> ブラウザOAuth -> refresh_token取得 -> Customer ID選択
Meta Ads: App ID/Secret入力 -> ブラウザOAuth -> Long-Lived Token取得 -> Account ID選択
"""

from __future__ import annotations

import html
import http.server
import json
import logging
import os
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from google_auth_oauthlib.flow import InstalledAppFlow

from mureo.auth import GoogleAdsCredentials, MetaAdsCredentials

logger = logging.getLogger(__name__)

_GOOGLE_ADS_SCOPE = "https://www.googleapis.com/auth/adwords"


def _select_account(
    accounts: list[dict[str, Any]],
    *,
    label_fn: Any | None = None,
) -> str | None:
    """ターミナル上でアカウントを矢印キーで選択する。

    simple-term-menuが利用可能ならインタラクティブ選択、
    なければ番号入力にフォールバック。

    Returns:
        選択されたアカウントのID、またはNone。
    """
    if label_fn is None:
        label_fn = lambda a: f"{a['name']} ({a['id']})"  # noqa: E731

    labels = [label_fn(a) for a in accounts]

    try:
        from simple_term_menu import TerminalMenu

        menu = TerminalMenu(labels, title="↑↓で選択してEnterで確定:")
        idx = menu.show()
        if idx is None:
            print("選択がキャンセルされました。後から設定できます。")
            return None
        selected = accounts[idx]
        print(f"選択: {selected['name']} ({selected['id']})")
        return selected["id"]
    except ImportError:
        # simple-term-menuがない場合は番号入力にフォールバック
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        print()
        try:
            choice = int(input("番号を入力: ").strip())
            if 1 <= choice <= len(accounts):
                selected = accounts[choice - 1]
                print(f"選択: {selected['name']} ({selected['id']})")
                return selected["id"]
        except (ValueError, IndexError):
            pass
        print("無効な選択です。後から設定できます。")
        return None


_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"
_META_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
_META_OAUTH_SCOPES = "ads_management,ads_read"

_HTTP_TIMEOUT = 30.0

# テスト差し替え用のinput関数
input_func = input


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthResult:
    """OAuth認証結果（イミュータブル）"""

    refresh_token: str
    access_token: str


@dataclass(frozen=True)
class MetaOAuthResult:
    """Meta Ads OAuth認証結果（イミュータブル）"""

    access_token: str  # Long-Lived Token
    expires_in: int  # 秒数（通常5184000 = 60日）


# ---------------------------------------------------------------------------
# ローカルOAuthコールバックサーバー（Google/Meta共通）
# ---------------------------------------------------------------------------


class _OAuthHTTPServer(http.server.HTTPServer):
    """OAuthコールバック受信用HTTPServer。認証結果をサーバー自身に保持する。"""

    authorization_code: str | None = None
    error: str | None = None
    expected_state: str | None = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """OAuthコールバックを受信するHTTPハンドラー（Google/Meta共通）"""

    server: _OAuthHTTPServer  # type: ignore[assignment]

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # stateパラメータの検証（CSRF対策）
        if self.server.expected_state is not None:
            received_state = params.get("state", [None])[0]
            if received_state != self.server.expected_state:
                self.server.error = "state パラメータが一致しません（CSRF検証失敗）"
                self._send_html(
                    "認証エラー: stateパラメータが一致しません。",
                    status=403,
                )
                return

        if "code" in params:
            self.server.authorization_code = params["code"][0]
            self._send_html("認証が完了しました。このウィンドウを閉じてください。")
        elif "error" in params:
            self.server.error = params["error"][0]
            self._send_html(f"認証エラー: {self.server.error}")
        else:
            self._send_html("不正なリクエストです。", status=400)

    def _send_html(self, message: str, status: int = 200) -> None:
        """HTMLレスポンスを送信する。messageはhtml.escape()でエスケープされる。"""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        safe_message = html.escape(message)
        body = f"<html><body><h1>{safe_message}</h1></body></html>"
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        """標準出力へのログ出力を抑制する"""
        logger.debug(fmt, *args)


class OAuthCallbackServer:
    """OAuth コールバック受信用HTTPサーバー（Google/Meta共通）"""

    def __init__(
        self,
        port: int = 0,
        expected_state: str | None = None,
    ) -> None:
        self.server = _OAuthHTTPServer(("localhost", port), _CallbackHandler)
        self.server.expected_state = expected_state

    @property
    def authorization_code(self) -> str | None:
        return self.server.authorization_code

    @property
    def error(self) -> str | None:
        return self.server.error

    def wait_for_callback(self) -> None:
        """1回のリクエストを処理してサーバーを停止する"""
        self.server.handle_request()

    def shutdown(self) -> None:
        """サーバーを停止する"""
        self.server.server_close()


# ---------------------------------------------------------------------------
# OAuthフロー実行
# ---------------------------------------------------------------------------


async def run_google_oauth(
    client_id: str,
    client_secret: str,
) -> OAuthResult:
    """InstalledAppFlowでブラウザOAuthを実行しrefresh_tokenを取得する。

    google-auth-oauthlibのInstalledAppFlowを使用し、ローカルサーバーの起動・
    ブラウザでの認証・コールバック受信・トークン交換を一括で処理する。

    Args:
        client_id: OAuth Client ID
        client_secret: OAuth Client Secret

    Returns:
        OAuthResult（refresh_token, access_token）

    Raises:
        RuntimeError: OAuth認証に失敗した場合
    """
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=[_GOOGLE_ADS_SCOPE],
    )

    # ブラウザでOAuth認証（ローカルサーバーは自動起動・自動停止）
    credentials = flow.run_local_server(port=8085, prompt="consent")

    if credentials.refresh_token is None:
        raise RuntimeError("refresh_tokenを取得できませんでした")

    return OAuthResult(
        refresh_token=credentials.refresh_token,
        access_token=credentials.token,
    )


# ---------------------------------------------------------------------------
# アカウント一覧取得
# ---------------------------------------------------------------------------


async def list_accessible_accounts(
    credentials: GoogleAdsCredentials,
) -> list[dict[str, Any]]:
    """Google Ads APIでアクセス可能なアカウント一覧を取得する。

    Google Ads SDKを直接使用してアクセス可能なアカウントを列挙する。
    mureo-coreのGoogleAdsApiClientはcustomer_id必須のため、
    セットアップ時のアカウント発見にはSDK直接呼び出しが必要。

    Args:
        credentials: Google Ads認証情報

    Returns:
        アカウント情報のリスト（id, name）
    """
    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials as OAuthCredentials

    oauth_creds = OAuthCredentials(
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    ga_client = GoogleAdsClient(
        credentials=oauth_creds,
        developer_token=credentials.developer_token,
        login_customer_id=credentials.login_customer_id,
    )

    try:
        customer_service = ga_client.get_service("CustomerService")
        response = customer_service.list_accessible_customers()
    except Exception:
        logger.warning("アカウント一覧の取得に失敗しました", exc_info=True)
        return []

    # 各アカウントのdescriptive_nameを取得
    ga_service = ga_client.get_service("GoogleAdsService")
    accounts: list[dict[str, Any]] = []
    for resource_name in response.resource_names:
        customer_id = resource_name.split("/")[-1]
        name = customer_id  # フォールバック
        try:
            query = "SELECT customer.descriptive_name FROM customer LIMIT 1"
            rows = ga_service.search(customer_id=customer_id, query=query)
            for row in rows:
                name = row.customer.descriptive_name or customer_id
                break
        except Exception:
            logger.debug("アカウント名の取得に失敗: %s", customer_id)
        accounts.append({"id": customer_id, "name": name})

    return accounts


# ---------------------------------------------------------------------------
# MCP設定の配置
# ---------------------------------------------------------------------------

_MCP_SERVER_CONFIG = {
    "command": "python",
    "args": ["-m", "mureo.mcp"],
}


def install_mcp_config(scope: str = "global") -> Path | None:
    """MCP設定をClaude Code用の設定ファイルに追加する。

    グローバル: ~/.claude/settings.json の mcpServers にマージ
    プロジェクト: カレントディレクトリの .mcp.json にマージ

    既にmureoが設定済みの場合はスキップ。

    Args:
        scope: "global" (~/.claude/settings.json) または "project" (.mcp.json)

    Returns:
        設定ファイルのパス。スキップした場合はNone。
    """
    if scope == "global":
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        # プロジェクト単位のMCP設定は .mcp.json に書く
        settings_path = Path.cwd() / ".mcp.json"

    # 既存設定の読み込み
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # mcpServersセクションの取得または作成
    mcp_servers = existing.setdefault("mcpServers", {})

    # 既にmureoが設定済みならスキップ
    if "mureo" in mcp_servers:
        logger.info("MCP設定は既に存在します: %s", settings_path)
        return None

    # mureoを追加
    mcp_servers["mureo"] = _MCP_SERVER_CONFIG
    existing["mcpServers"] = mcp_servers

    # ディレクトリ作成・書き込み
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    logger.info("MCP設定を追加しました: %s", settings_path)
    return settings_path


def setup_mcp_config() -> None:
    """対話型でMCP設定を配置する。"""
    print("\n=== MCP設定 ===\n")
    print("AIエージェント（Claude Code等）からmureoを使うにはMCP設定が必要です。")
    print()

    try:
        from simple_term_menu import TerminalMenu

        options = [
            "グローバル (~/.claude/settings.json) — 全プロジェクトで使用",
            "このディレクトリ (.mcp.json) — このプロジェクトのみ",
            "スキップ（手動で設定する）",
        ]
        menu = TerminalMenu(options, title="MCP設定をどこに配置しますか？")
        idx = menu.show()
        if idx is None or idx == 2:
            print("MCP設定をスキップしました。")
            return
        scope = "global" if idx == 0 else "project"
    except ImportError:
        # フォールバック: 番号入力
        print("MCP設定をどこに配置しますか？")
        print("  1. グローバル (~/.claude/settings.json) — 全プロジェクトで使用")
        print("  2. このディレクトリ (.mcp.json) — このプロジェクトのみ")
        print("  3. スキップ（手動で設定する）")
        print()
        choice = input_func("番号を入力 [1]: ").strip() or "1"
        if choice == "3":
            print("MCP設定をスキップしました。")
            return
        scope = "global" if choice != "2" else "project"

    result = install_mcp_config(scope=scope)
    if result is not None:
        print(f"MCP設定を追加しました: {result}")
    else:
        print("MCP設定は既に存在しています。")


# ---------------------------------------------------------------------------
# credentials.json保存
# ---------------------------------------------------------------------------


def save_credentials(
    path: Path | None = None,
    google: GoogleAdsCredentials | None = None,
    meta: MetaAdsCredentials | None = None,
    customer_id: str | None = None,
    account_id: str | None = None,
) -> None:
    """credentials.jsonに認証情報を保存する（既存データとマージ）。

    Args:
        path: credentials.jsonのパス。Noneの場合はデフォルトパスを使用。
        google: Google Ads認証情報
        meta: Meta Ads認証情報
        customer_id: Google Adsアカウント（login_customer_id）
        account_id: Meta Ads広告アカウントID
    """
    resolved = path if path is not None else _resolve_default_path()

    # ディレクトリ作成
    resolved.parent.mkdir(parents=True, exist_ok=True)

    # 既存データの読み込み
    existing: dict[str, Any] = {}
    if resolved.exists():
        try:
            existing = json.loads(resolved.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Google Ads認証情報のマージ
    if google is not None:
        google_data: dict[str, Any] = {
            "developer_token": google.developer_token,
            "client_id": google.client_id,
            "client_secret": google.client_secret,
            "refresh_token": google.refresh_token,
        }
        login_cid = customer_id or google.login_customer_id
        if login_cid is not None:
            google_data["login_customer_id"] = login_cid
        else:
            google_data["login_customer_id"] = None
        existing["google_ads"] = google_data

    # Meta Ads認証情報のマージ
    if meta is not None:
        meta_data: dict[str, Any] = {
            "access_token": getattr(meta, "access_token", ""),
        }
        app_id = getattr(meta, "app_id", None)
        if app_id is not None:
            meta_data["app_id"] = app_id
        app_secret = getattr(meta, "app_secret", None)
        if app_secret is not None:
            meta_data["app_secret"] = app_secret
        if account_id is not None:
            meta_data["account_id"] = account_id
        existing["meta_ads"] = meta_data

    # ファイル書き込み
    resolved.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # パーミッション設定（owner read/write のみ）
    os.chmod(resolved, 0o600)

    logger.info("認証情報を保存しました: %s", resolved)


# ---------------------------------------------------------------------------
# セットアップウィザード
# ---------------------------------------------------------------------------


async def setup_google_ads(
    credentials_path: Path | None = None,
) -> GoogleAdsCredentials:
    """Google Ads認証の対話型セットアップ。

    1. 事前準備ガイダンスを表示
    2. Developer Token入力
    3. OAuth Client ID入力
    4. OAuth Client Secret入力
    5. ブラウザOAuth -> refresh_token取得
    6. アカウント一覧取得 -> Customer ID選択
    7. credentials.jsonに保存

    Args:
        credentials_path: credentials.jsonのパス。Noneの場合はデフォルトパスを使用。

    Returns:
        GoogleAdsCredentials
    """
    print("\n=== Google Ads セットアップ ===\n")
    print("事前に以下を準備してください:")
    print("  1. Google Ads Developer Token（Google Ads APIセンターから取得）")
    print("  2. OAuth 2.0 Client ID / Client Secret（GCPコンソールから作成）")
    print("     - アプリケーションの種類: デスクトップアプリ")
    print("     （リダイレクトURIはInstalledAppFlowが自動管理します）")
    print()

    # Developer Token入力
    developer_token = input_func("Developer Token: ").strip()

    # OAuth Client ID / Secret入力
    client_id = input_func("OAuth Client ID: ").strip()
    client_secret = input_func("OAuth Client Secret: ").strip()

    # ブラウザOAuthフロー
    print(
        "\nブラウザが開きます。Googleアカウントでログインし、アクセスを許可してください..."
    )
    oauth_result = await run_google_oauth(
        client_id=client_id,
        client_secret=client_secret,
    )
    print("OAuth認証が完了しました。\n")

    # 一時的なcredentialsでアカウント一覧取得
    temp_creds = GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=oauth_result.refresh_token,
    )

    accounts = await list_accessible_accounts(temp_creds)

    login_customer_id: str | None = None

    if accounts:
        print("アクセス可能なアカウント:\n")
        login_customer_id = _select_account(accounts)
    else:
        print("アクセス可能なアカウントが見つかりませんでした。")
        print("Customer IDは後から credentials.json に手動で追加できます。")

    # 最終的なcredentials生成
    final_creds = GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=oauth_result.refresh_token,
        login_customer_id=login_customer_id,
    )

    # 保存
    save_credentials(
        path=credentials_path,
        google=final_creds,
        customer_id=login_customer_id,
    )

    print(f"\n認証情報を保存しました: {credentials_path or _resolve_default_path()}")
    print("Google Adsのセットアップが完了しました。\n")

    return final_creds


# ===========================================================================
# Meta Ads セクション
# ===========================================================================


# ---------------------------------------------------------------------------
# Meta認証URL生成
# ---------------------------------------------------------------------------


def _generate_meta_auth_url(
    app_id: str,
    port: int,
    state: str | None = None,
) -> str:
    """Facebook OAuth認証URLを生成する。

    Args:
        app_id: Meta（Facebook）アプリID
        port: ローカルコールバックサーバーのポート番号
        state: CSRF対策用stateパラメータ

    Returns:
        認証URL文字列
    """
    params: dict[str, str] = {
        "client_id": app_id,
        "redirect_uri": f"http://localhost:{port}/callback",
        "scope": _META_OAUTH_SCOPES,
        "response_type": "code",
    }
    if state is not None:
        params["state"] = state
    return f"{_META_AUTH_URL}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# Meta Token交換: Code -> Short-Lived Token
# ---------------------------------------------------------------------------


async def _exchange_code_for_short_token(
    *,
    code: str,
    app_id: str,
    app_secret: str,
    redirect_uri: str,
) -> str:
    """認証コードからShort-Lived Tokenを取得する。

    Args:
        code: Facebook認証で取得したauthorization code
        app_id: Meta（Facebook）アプリID
        app_secret: Meta（Facebook）アプリシークレット
        redirect_uri: コールバックURI

    Returns:
        Short-Lived access token

    Raises:
        RuntimeError: Short-Lived Token の取得に失敗した場合
    """
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "client_secret": app_secret,
        "code": code,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/oauth/access_token",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data["access_token"]
    except Exception as exc:
        raise RuntimeError(f"Short-Lived Token の取得に失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# Meta Token交換: Short-Lived -> Long-Lived Token
# ---------------------------------------------------------------------------


async def _exchange_short_for_long_token(
    *,
    short_token: str,
    app_id: str,
    app_secret: str,
) -> MetaOAuthResult:
    """Short-Lived TokenをLong-Lived Token（60日有効）に変換する。

    Args:
        short_token: Short-Lived access token
        app_id: Meta（Facebook）アプリID
        app_secret: Meta（Facebook）アプリシークレット

    Returns:
        MetaOAuthResult（Long-Lived Token + 有効期限）

    Raises:
        RuntimeError: Long-Lived Token への変換に失敗した場合
    """
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/oauth/access_token",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return MetaOAuthResult(
                access_token=data["access_token"],
                expires_in=data.get("expires_in", 5184000),
            )
    except Exception as exc:
        raise RuntimeError(f"Long-Lived Token への変換に失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# Meta広告アカウント一覧取得
# ---------------------------------------------------------------------------


async def list_meta_ad_accounts(access_token: str) -> list[dict[str, Any]]:
    """Graph APIで広告アカウント一覧を取得する。

    GET https://graph.facebook.com/v21.0/me/adaccounts?
        fields=id,name,account_status&
        access_token={access_token}

    Args:
        access_token: Meta Ads access token

    Returns:
        広告アカウントのリスト（id, name, account_status）

    Raises:
        RuntimeError: 広告アカウント一覧の取得に失敗した場合
    """
    params = {
        "fields": "id,name,account_status",
        "access_token": access_token,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(
                f"{_META_GRAPH_API_BASE}/me/adaccounts",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
    except Exception as exc:
        raise RuntimeError(f"広告アカウント一覧の取得に失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# Meta Ads OAuthフロー
# ---------------------------------------------------------------------------


async def run_meta_oauth(
    app_id: str,
    app_secret: str,
    port: int = 0,
) -> MetaOAuthResult:
    """Facebook OAuthフローを実行しLong-Lived Tokenを取得する。

    1. ローカルHTTPサーバーを起動（バックグラウンド）
    2. Facebook OAuth認証URLをブラウザで開く
    3. ユーザーがFacebookアカウント認証・承認
    4. コールバックでauthorization codeを受信
    5. Code -> Short-Lived Token -> Long-Lived Token に変換

    Args:
        app_id: Meta（Facebook）アプリID
        app_secret: Meta（Facebook）アプリシークレット
        port: ローカルサーバーのポート（0=自動選択）

    Returns:
        MetaOAuthResult（Long-Lived Token + 有効期限）
    """
    # CSRF対策: ランダムなstateトークンを生成
    state = secrets.token_urlsafe(32)

    # 共通OAuthCallbackServerを使用
    callback_server = OAuthCallbackServer(port=port, expected_state=state)
    actual_port = callback_server.server.server_address[1]

    # 認証URLを生成
    auth_url = _generate_meta_auth_url(app_id=app_id, port=actual_port, state=state)

    # バックグラウンドでコールバックを待つ
    server_thread = threading.Thread(
        target=callback_server.wait_for_callback, daemon=True
    )
    server_thread.start()

    # ブラウザで認証URLを開く
    print("\nブラウザで認証ページを開きます...")
    print(f"URL: {auth_url}")
    webbrowser.open(auth_url)

    # コールバック受信を待つ
    server_thread.join(timeout=300)

    if callback_server.error:
        raise RuntimeError(f"認証エラー: {callback_server.error}")

    if callback_server.authorization_code is None:
        raise RuntimeError("認証がタイムアウトしました")

    redirect_uri = f"http://localhost:{actual_port}/callback"
    code = callback_server.authorization_code

    # Code -> Short-Lived Token
    print("Short-Lived Tokenを取得中...")
    short_token = await _exchange_code_for_short_token(
        code=code,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
    )

    # Short-Lived -> Long-Lived Token
    print("Long-Lived Tokenに変換中...")
    result = await _exchange_short_for_long_token(
        short_token=short_token,
        app_id=app_id,
        app_secret=app_secret,
    )

    print(f"認証成功! トークン有効期限: {result.expires_in // 86400}日")
    return result


# ---------------------------------------------------------------------------
# Meta Ads セットアップウィザード
# ---------------------------------------------------------------------------


async def setup_meta_ads(
    credentials_path: Path | None = None,
) -> MetaAdsCredentials:
    """Meta Ads認証の対話型セットアップ。

    1. 事前準備ガイダンスを表示
    2. App ID入力
    3. App Secret入力
    4. ブラウザOAuth -> access_token取得 -> Long-Lived変換
    5. 広告アカウント一覧取得 -> Account ID選択
    6. credentials.jsonに保存

    Args:
        credentials_path: credentials.jsonのパス。Noneの場合はデフォルトパスを使用。

    Returns:
        MetaAdsCredentials
    """
    resolved_path = (
        credentials_path if credentials_path is not None else _resolve_default_path()
    )

    # ガイダンス表示
    print("\n=== Meta Ads セットアップ ===")
    print("")
    print("事前準備:")
    print("  1. Meta for Developers (https://developers.facebook.com/) でアプリを作成")
    print("  2. アプリの設定からApp IDとApp Secretを取得")
    print("  3. プロダクト > Facebookログイン > 設定 で")
    print("     有効なOAuthリダイレクトURIに http://localhost を追加")
    print("")

    # App ID / App Secret 入力（input_func使用でテスト差し替え可能）
    app_id = input_func("App ID: ").strip()
    app_secret = input_func("App Secret: ").strip()

    # OAuthフロー実行
    print("\nFacebook認証を開始します...")
    oauth_result = await run_meta_oauth(app_id=app_id, app_secret=app_secret)

    # 広告アカウント一覧取得
    print("\n広告アカウント一覧を取得中...")
    accounts = await list_meta_ad_accounts(access_token=oauth_result.access_token)

    if not accounts:
        raise RuntimeError(
            "広告アカウントが見つかりません。アクセス権限を確認してください。"
        )

    # アカウント選択
    if len(accounts) == 1:
        selected = accounts[0]
        print(f"\n広告アカウント: {selected['name']} ({selected['id']})")
    else:
        print("\n広告アカウントを選択してください:\n")

        def _meta_label(a: dict[str, Any]) -> str:
            status = "有効" if a.get("account_status") == 1 else "無効"
            return f"{a['name']} ({a['id']}) [{status}]"

        selected_id = _select_account(accounts, label_fn=_meta_label)
        if selected_id is not None:
            selected = next(a for a in accounts if a["id"] == selected_id)
        else:
            selected = accounts[0]
            print(f"デフォルト: {selected['name']} ({selected['id']})")

    account_id: str = selected["id"]

    # credentials.jsonに保存（save_credentials共通関数を使用）
    meta_creds = MetaAdsCredentials(
        access_token=oauth_result.access_token,
        app_id=app_id,
        app_secret=app_secret,
    )

    save_credentials(
        path=resolved_path,
        meta=meta_creds,
        account_id=account_id,
    )

    print(f"\n認証情報を保存しました: {resolved_path}")
    print(f"アカウント: {selected['name']} ({account_id})")

    return meta_creds


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _resolve_default_path() -> Path:
    """デフォルトのcredentials.jsonパスを解決する"""
    return Path.home() / ".mureo" / "credentials.json"
