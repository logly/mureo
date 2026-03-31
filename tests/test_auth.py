"""認証情報の読み込みモジュールのテスト（TDD: RED → GREEN → IMPROVE）"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mureo.auth import (
    GoogleAdsCredentials,
    MetaAdsCredentials,
    create_google_ads_client,
    create_meta_ads_client,
    load_credentials,
    load_google_ads_credentials,
    load_meta_ads_credentials,
)

# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

SAMPLE_CREDENTIALS = {
    "google_ads": {
        "developer_token": "dev-token-123",
        "client_id": "client-id.apps.googleusercontent.com",
        "client_secret": "client-secret-456",
        "refresh_token": "refresh-token-789",
        "login_customer_id": "1234567890",
    },
    "meta_ads": {
        "access_token": "meta-access-token-abc",
        "app_id": "meta-app-id-111",
        "app_secret": "meta-app-secret-222",
    },
}


@pytest.fixture()
def credentials_file(tmp_path: Path) -> Path:
    """一時ディレクトリにcredentials.jsonを作成する"""
    cred_path = tmp_path / "credentials.json"
    cred_path.write_text(json.dumps(SAMPLE_CREDENTIALS), encoding="utf-8")
    return cred_path


@pytest.fixture()
def google_only_credentials_file(tmp_path: Path) -> Path:
    """Google Adsのみのcredentials.json"""
    cred_path = tmp_path / "credentials.json"
    data = {"google_ads": SAMPLE_CREDENTIALS["google_ads"]}
    cred_path.write_text(json.dumps(data), encoding="utf-8")
    return cred_path


@pytest.fixture()
def meta_only_credentials_file(tmp_path: Path) -> Path:
    """Meta Adsのみのcredentials.json"""
    cred_path = tmp_path / "credentials.json"
    data = {"meta_ads": SAMPLE_CREDENTIALS["meta_ads"]}
    cred_path.write_text(json.dumps(data), encoding="utf-8")
    return cred_path


# ---------------------------------------------------------------------------
# 1. ファイルからGoogle Ads認証情報を読み込む
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_google_ads_credentials_from_file(credentials_file: Path) -> None:
    creds = load_google_ads_credentials(path=credentials_file)

    assert creds is not None
    assert isinstance(creds, GoogleAdsCredentials)
    assert creds.developer_token == "dev-token-123"
    assert creds.client_id == "client-id.apps.googleusercontent.com"
    assert creds.client_secret == "client-secret-456"
    assert creds.refresh_token == "refresh-token-789"
    assert creds.login_customer_id == "1234567890"


# ---------------------------------------------------------------------------
# 2. ファイルからMeta Ads認証情報を読み込む
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_meta_ads_credentials_from_file(credentials_file: Path) -> None:
    creds = load_meta_ads_credentials(path=credentials_file)

    assert creds is not None
    assert isinstance(creds, MetaAdsCredentials)
    assert creds.access_token == "meta-access-token-abc"
    assert creds.app_id == "meta-app-id-111"
    assert creds.app_secret == "meta-app-secret-222"


# ---------------------------------------------------------------------------
# 3. ファイルが存在しない場合 → None
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_credentials_file_not_found(tmp_path: Path) -> None:
    nonexistent = tmp_path / "nonexistent.json"
    result = load_credentials(path=nonexistent)
    assert result == {}


@pytest.mark.unit
def test_load_google_ads_credentials_file_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ファイルなし + 環境変数もなし → None"""
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)

    nonexistent = tmp_path / "nonexistent.json"
    creds = load_google_ads_credentials(path=nonexistent)
    assert creds is None


@pytest.mark.unit
def test_load_meta_ads_credentials_file_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ファイルなし + 環境変数もなし → None"""
    monkeypatch.delenv("META_ADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ADS_APP_ID", raising=False)
    monkeypatch.delenv("META_ADS_APP_SECRET", raising=False)

    nonexistent = tmp_path / "nonexistent.json"
    creds = load_meta_ads_credentials(path=nonexistent)
    assert creds is None


# ---------------------------------------------------------------------------
# 4. 環境変数フォールバック — Google Ads
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_google_ads_credentials_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nonexistent = tmp_path / "nonexistent.json"
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "env-dev-token")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "env-client-secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "env-refresh-token")
    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "9999999999")

    creds = load_google_ads_credentials(path=nonexistent)

    assert creds is not None
    assert creds.developer_token == "env-dev-token"
    assert creds.client_id == "env-client-id"
    assert creds.client_secret == "env-client-secret"
    assert creds.refresh_token == "env-refresh-token"
    assert creds.login_customer_id == "9999999999"


@pytest.mark.unit
def test_load_google_ads_credentials_from_env_without_login_customer_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """login_customer_idは省略可能"""
    nonexistent = tmp_path / "nonexistent.json"
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "env-dev-token")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "env-client-secret")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "env-refresh-token")
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)

    creds = load_google_ads_credentials(path=nonexistent)

    assert creds is not None
    assert creds.login_customer_id is None


# ---------------------------------------------------------------------------
# 5. 環境変数フォールバック — Meta Ads
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_meta_ads_credentials_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nonexistent = tmp_path / "nonexistent.json"
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "env-meta-token")
    monkeypatch.setenv("META_ADS_APP_ID", "env-app-id")
    monkeypatch.setenv("META_ADS_APP_SECRET", "env-app-secret")

    creds = load_meta_ads_credentials(path=nonexistent)

    assert creds is not None
    assert creds.access_token == "env-meta-token"
    assert creds.app_id == "env-app-id"
    assert creds.app_secret == "env-app-secret"


@pytest.mark.unit
def test_load_meta_ads_credentials_from_env_minimal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app_id/app_secretは省略可能"""
    nonexistent = tmp_path / "nonexistent.json"
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "env-meta-token")
    monkeypatch.delenv("META_ADS_APP_ID", raising=False)
    monkeypatch.delenv("META_ADS_APP_SECRET", raising=False)

    creds = load_meta_ads_credentials(path=nonexistent)

    assert creds is not None
    assert creds.access_token == "env-meta-token"
    assert creds.app_id is None
    assert creds.app_secret is None


# ---------------------------------------------------------------------------
# 6. ファイルも環境変数もない → None
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_google_ads_credentials_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)

    nonexistent = tmp_path / "nonexistent.json"
    creds = load_google_ads_credentials(path=nonexistent)
    assert creds is None


@pytest.mark.unit
def test_load_meta_ads_credentials_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("META_ADS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ADS_APP_ID", raising=False)
    monkeypatch.delenv("META_ADS_APP_SECRET", raising=False)

    nonexistent = tmp_path / "nonexistent.json"
    creds = load_meta_ads_credentials(path=nonexistent)
    assert creds is None


# ---------------------------------------------------------------------------
# 7. frozen=True のイミュータビリティ確認
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_credentials_immutable() -> None:
    google_creds = GoogleAdsCredentials(
        developer_token="a",
        client_id="b",
        client_secret="c",
        refresh_token="d",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        google_creds.developer_token = "changed"  # type: ignore[misc]

    meta_creds = MetaAdsCredentials(access_token="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta_creds.access_token = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 8. create_google_ads_client
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_google_ads_client() -> None:
    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
        login_customer_id="1234567890",
    )

    with patch("mureo.auth.Credentials") as mock_cred_cls, patch(
        "mureo.auth.GoogleAdsApiClient"
    ) as mock_client_cls:
        mock_cred_cls.return_value = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        client = create_google_ads_client(creds, customer_id="5555555555")

        assert client is mock_client_instance
        mock_cred_cls.assert_called_once_with(
            token=None,
            refresh_token="rtok",
            client_id="cid",
            client_secret="csec",
            token_uri="https://oauth2.googleapis.com/token",
        )
        mock_client_cls.assert_called_once_with(
            credentials=mock_cred_cls.return_value,
            customer_id="5555555555",
            developer_token="dev-tok",
            login_customer_id="1234567890",
        )


@pytest.mark.unit
def test_create_google_ads_client_without_login_customer_id() -> None:
    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
    )

    with patch("mureo.auth.Credentials") as mock_cred_cls, patch(
        "mureo.auth.GoogleAdsApiClient"
    ) as mock_client_cls:
        mock_cred_cls.return_value = MagicMock()
        mock_client_cls.return_value = MagicMock()

        create_google_ads_client(creds, customer_id="5555555555")

        mock_client_cls.assert_called_once_with(
            credentials=mock_cred_cls.return_value,
            customer_id="5555555555",
            developer_token="dev-tok",
            login_customer_id=None,
        )


# ---------------------------------------------------------------------------
# 9. create_meta_ads_client
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_meta_ads_client() -> None:
    creds = MetaAdsCredentials(
        access_token="meta-tok",
        app_id="app123",
        app_secret="secret456",
    )

    with patch("mureo.auth.MetaAdsApiClient") as mock_client_cls:
        mock_client_instance = MagicMock()
        mock_client_cls.return_value = mock_client_instance

        client = create_meta_ads_client(creds, account_id="act_12345")

        assert client is mock_client_instance
        mock_client_cls.assert_called_once_with(
            access_token="meta-tok",
            ad_account_id="act_12345",
        )


# ---------------------------------------------------------------------------
# 10. 不正なJSON
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_credentials_invalid_json(tmp_path: Path) -> None:
    bad_file = tmp_path / "credentials.json"
    bad_file.write_text("{invalid json!!", encoding="utf-8")

    result = load_credentials(path=bad_file)
    assert result == {}


@pytest.mark.unit
def test_load_google_ads_credentials_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不正JSONファイル + 環境変数なし → None"""
    monkeypatch.delenv("GOOGLE_ADS_DEVELOPER_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_ADS_REFRESH_TOKEN", raising=False)

    bad_file = tmp_path / "credentials.json"
    bad_file.write_text("{invalid}", encoding="utf-8")

    creds = load_google_ads_credentials(path=bad_file)
    assert creds is None


# ---------------------------------------------------------------------------
# 11. ファイル優先（ファイルと環境変数の両方がある場合はファイルを優先）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_file_takes_precedence_over_env(
    credentials_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "env-should-not-be-used")

    creds = load_google_ads_credentials(path=credentials_file)

    assert creds is not None
    assert creds.developer_token == "dev-token-123"


# ---------------------------------------------------------------------------
# 12. Google Adsキーがないファイル → 環境変数フォールバック
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_google_ads_from_file_without_google_key(
    meta_only_credentials_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ファイルにgoogle_adsキーがない場合、環境変数にフォールバック"""
    monkeypatch.setenv("GOOGLE_ADS_DEVELOPER_TOKEN", "env-dev")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_ID", "env-cid")
    monkeypatch.setenv("GOOGLE_ADS_CLIENT_SECRET", "env-csec")
    monkeypatch.setenv("GOOGLE_ADS_REFRESH_TOKEN", "env-rtok")

    creds = load_google_ads_credentials(path=meta_only_credentials_file)

    assert creds is not None
    assert creds.developer_token == "env-dev"


@pytest.mark.unit
def test_load_meta_ads_from_file_without_meta_key(
    google_only_credentials_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ファイルにmeta_adsキーがない場合、環境変数にフォールバック"""
    monkeypatch.setenv("META_ADS_ACCESS_TOKEN", "env-meta-tok")

    creds = load_meta_ads_credentials(path=google_only_credentials_file)

    assert creds is not None
    assert creds.access_token == "env-meta-tok"


# ---------------------------------------------------------------------------
# 13. load_credentials — 正常読み込み
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_credentials_success(credentials_file: Path) -> None:
    data = load_credentials(path=credentials_file)
    assert "google_ads" in data
    assert "meta_ads" in data
    assert data["google_ads"]["developer_token"] == "dev-token-123"


# ---------------------------------------------------------------------------
# 14. デフォルトパス（~/.mureo/credentials.json）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_load_credentials_default_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """デフォルトパスは ~/.mureo/credentials.json"""
    mureo_dir = tmp_path / ".mureo"
    mureo_dir.mkdir()
    cred_path = mureo_dir / "credentials.json"
    cred_path.write_text(json.dumps(SAMPLE_CREDENTIALS), encoding="utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))
    # Windowsも考慮して Path.home() をモック
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    data = load_credentials()
    assert "google_ads" in data
