"""認証情報の読み込みモジュール

~/.mureo/credentials.json からGoogle Ads / Meta Adsの認証情報を読み込む。
ファイルが存在しない場合は環境変数にフォールバックする。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials

from mureo.google_ads import GoogleAdsApiClient
from mureo.meta_ads import MetaAdsApiClient

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoogleAdsCredentials:
    """Google Ads認証情報（イミュータブル）"""

    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    login_customer_id: str | None = None


@dataclass(frozen=True)
class MetaAdsCredentials:
    """Meta Ads認証情報（イミュータブル）"""

    access_token: str
    app_id: str | None = None
    app_secret: str | None = None


# ---------------------------------------------------------------------------
# 読み込み関数
# ---------------------------------------------------------------------------


def load_credentials(path: Path | None = None) -> dict[str, Any]:
    """~/.mureo/credentials.json から認証情報を読み込む。

    Args:
        path: credentials.jsonのパス。Noneの場合はデフォルトパスを使用。

    Returns:
        認証情報の辞書。ファイルが存在しない・不正JSON の場合は空辞書。
    """
    resolved = path if path is not None else _resolve_default_path()

    if not resolved.exists():
        logger.debug("credentials.jsonが見つかりません: %s", resolved)
        return {}

    try:
        text = resolved.read_text(encoding="utf-8")
        data = json.loads(text)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("credentials.jsonの読み込みに失敗: %s", exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("credentials.jsonのルートがオブジェクトではありません")
        return {}

    return data


def load_google_ads_credentials(
    path: Path | None = None,
) -> GoogleAdsCredentials | None:
    """Google Ads認証情報を読み込む。環境変数フォールバック付き。

    優先順位:
        1. credentials.json の google_ads セクション
        2. 環境変数 (GOOGLE_ADS_*)

    Returns:
        GoogleAdsCredentials または None（必須項目が不足している場合）
    """
    data = load_credentials(path)
    google_section = data.get("google_ads")

    if isinstance(google_section, dict):
        developer_token = google_section.get("developer_token", "")
        client_id = google_section.get("client_id", "")
        client_secret = google_section.get("client_secret", "")
        refresh_token = google_section.get("refresh_token", "")
        login_customer_id = google_section.get("login_customer_id")

        if developer_token and client_id and client_secret and refresh_token:
            return GoogleAdsCredentials(
                developer_token=developer_token,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                login_customer_id=login_customer_id,
            )

    # 環境変数フォールバック
    return _load_google_ads_from_env()


def load_meta_ads_credentials(
    path: Path | None = None,
) -> MetaAdsCredentials | None:
    """Meta Ads認証情報を読み込む。環境変数フォールバック付き。

    優先順位:
        1. credentials.json の meta_ads セクション
        2. 環境変数 (META_ADS_*)

    Returns:
        MetaAdsCredentials または None（必須項目が不足している場合）
    """
    data = load_credentials(path)
    meta_section = data.get("meta_ads")

    if isinstance(meta_section, dict):
        access_token = meta_section.get("access_token", "")
        if access_token:
            return MetaAdsCredentials(
                access_token=access_token,
                app_id=meta_section.get("app_id"),
                app_secret=meta_section.get("app_secret"),
            )

    # 環境変数フォールバック
    return _load_meta_ads_from_env()


# ---------------------------------------------------------------------------
# クライアント生成ヘルパー
# ---------------------------------------------------------------------------


def create_google_ads_client(
    credentials: GoogleAdsCredentials,
    customer_id: str,
) -> GoogleAdsApiClient:
    """認証情報からGoogleAdsApiClientを生成する。

    Args:
        credentials: Google Ads認証情報
        customer_id: 操作対象のGoogle Adsアカウント（customer_id）

    Returns:
        GoogleAdsApiClient インスタンス
    """
    oauth_credentials = Credentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri=_TOKEN_URI,
    )

    return GoogleAdsApiClient(
        credentials=oauth_credentials,
        customer_id=customer_id,
        developer_token=credentials.developer_token,
        login_customer_id=credentials.login_customer_id,
    )


def create_meta_ads_client(
    credentials: MetaAdsCredentials,
    account_id: str,
) -> MetaAdsApiClient:
    """認証情報からMetaAdsApiClientを生成する。

    Args:
        credentials: Meta Ads認証情報
        account_id: 広告アカウントID（"act_XXXX" 形式）

    Returns:
        MetaAdsApiClient インスタンス
    """
    return MetaAdsApiClient(
        access_token=credentials.access_token,
        ad_account_id=account_id,
    )


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _resolve_default_path() -> Path:
    """デフォルトのcredentials.jsonパスを解決する"""
    return Path.home() / ".mureo" / "credentials.json"


def _load_google_ads_from_env() -> GoogleAdsCredentials | None:
    """環境変数からGoogle Ads認証情報を読み込む"""
    developer_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "")
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN", "")
    login_customer_id = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")

    if not (developer_token and client_id and client_secret and refresh_token):
        return None

    return GoogleAdsCredentials(
        developer_token=developer_token,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        login_customer_id=login_customer_id,
    )


def _load_meta_ads_from_env() -> MetaAdsCredentials | None:
    """環境変数からMeta Ads認証情報を読み込む"""
    access_token = os.environ.get("META_ADS_ACCESS_TOKEN", "")

    if not access_token:
        return None

    return MetaAdsCredentials(
        access_token=access_token,
        app_id=os.environ.get("META_ADS_APP_ID"),
        app_secret=os.environ.get("META_ADS_APP_SECRET"),
    )
