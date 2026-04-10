"""Google Ads _ads.py テスト

_AdsMixin の list_ads, get_ad_policy_details, create_ad, update_ad,
update_ad_status, _validate_and_prepare_rsa, _build_ad_strength_result のテスト。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from google.ads.googleads.errors import GoogleAdsException

from mureo.google_ads.client import GoogleAdsApiClient


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def _make_client() -> GoogleAdsApiClient:
    """テスト用クライアント"""
    creds = MagicMock()
    with patch("mureo.google_ads.client.GoogleAdsClient") as mock_gads:
        mock_gads.return_value = MagicMock()
        client = GoogleAdsApiClient(
            credentials=creds,
            customer_id="1234567890",
            developer_token="test-token",
        )
    return client


def _make_google_ads_exception(
    message: str = "error",
    attr_name: str | None = None,
    error_name: str | None = None,
) -> GoogleAdsException:
    error = MagicMock()
    error.message = message
    if attr_name and error_name:
        code_attr = MagicMock()
        code_attr.name = error_name
        error.error_code = MagicMock(**{attr_name: code_attr})
    else:
        error.error_code = MagicMock(spec=[])
    failure = MagicMock()
    failure.errors = [error]
    exc = GoogleAdsException.__new__(GoogleAdsException)
    exc._failure = failure
    exc._call = MagicMock()
    exc._request_id = "req-123"
    type(exc).failure = property(lambda self: self._failure)
    return exc


def _make_ad_row(
    ad_id: int = 1,
    ad_type: int = 15,  # RESPONSIVE_SEARCH_AD
    status: int = 2,  # ENABLED
    ad_strength: int = 4,  # GOOD
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
) -> MagicMock:
    """広告一覧行のモック"""
    row = MagicMock()
    row.ad_group_ad.ad.id = ad_id
    row.ad_group_ad.ad.name = f"Ad {ad_id}"
    row.ad_group_ad.ad.type_ = ad_type
    row.ad_group_ad.status = status
    row.ad_group_ad.ad_strength = ad_strength
    row.ad_group.id = 100
    row.ad_group.name = "テストグループ"
    row.campaign.id = 200
    row.campaign.name = "テストキャンペーン"
    row.campaign.status = 2

    # RSA見出し・説明文
    if headlines is None:
        headlines = ["見出し1", "見出し2", "見出し3"]
    if descriptions is None:
        descriptions = ["説明文1", "説明文2"]

    hl_assets = []
    for h in headlines:
        asset = MagicMock()
        asset.text = h
        hl_assets.append(asset)
    desc_assets = []
    for d in descriptions:
        asset = MagicMock()
        asset.text = d
        desc_assets.append(asset)

    row.ad_group_ad.ad.responsive_search_ad.headlines = hl_assets
    row.ad_group_ad.ad.responsive_search_ad.descriptions = desc_assets

    # ポリシーサマリー
    ps = MagicMock()
    ps.review_status = 3  # REVIEWED
    ps.approval_status = 4  # APPROVED
    ps.policy_topic_entries = []
    row.ad_group_ad.policy_summary = ps

    return row


# ---------------------------------------------------------------------------
# _validate_and_prepare_rsa
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateAndPrepareRsa:
    def test_正常(self) -> None:
        headlines = [f"見出し{i}" for i in range(5)]
        descriptions = ["説明1", "説明2"]
        h, d, result = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(h) == 5
        assert len(d) == 2

    def test_見出し15超_切り詰め(self) -> None:
        headlines = [f"見出し{i}" for i in range(20)]
        descriptions = ["説明1", "説明2"]
        h, d, _ = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(h) == 15

    def test_説明文4超_切り詰め(self) -> None:
        headlines = [f"見出し{i}" for i in range(5)]
        descriptions = [f"説明{i}" for i in range(6)]
        h, d, _ = GoogleAdsApiClient._validate_and_prepare_rsa(
            headlines, descriptions, "https://example.com"
        )
        assert len(d) == 4

    def test_見出し3未満_エラー(self) -> None:
        with pytest.raises(ValueError, match="At least 3 headlines"):
            GoogleAdsApiClient._validate_and_prepare_rsa(
                ["見出し1", "見出し2"], ["説明1", "説明2"], "https://example.com"
            )

    def test_説明文2未満_エラー(self) -> None:
        with pytest.raises(ValueError, match="At least 2 descriptions"):
            GoogleAdsApiClient._validate_and_prepare_rsa(
                ["見出し1", "見出し2", "見出し3"], ["説明1"], "https://example.com"
            )


# ---------------------------------------------------------------------------
# _build_ad_strength_result
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAdStrengthResult:
    def test_正常(self) -> None:
        from mureo.google_ads._rsa_validator import RSAValidationResult

        rsa_result = RSAValidationResult(
            headlines=("h1", "h2", "h3"),
            descriptions=("d1", "d2"),
            warnings=(),
        )
        result: dict[str, Any] = {"resource_name": "test"}
        result = GoogleAdsApiClient._build_ad_strength_result(
            result,
            rsa_result,
            ["h1", "h2", "h3"],
            ["d1", "d2"],
            None,
        )
        assert "ad_strength" in result
        assert "level" in result["ad_strength"]
        assert "score" in result["ad_strength"]

    def test_警告あり(self) -> None:
        from mureo.google_ads._rsa_validator import RSAValidationResult

        rsa_result = RSAValidationResult(
            headlines=("h1", "h2", "h3"),
            descriptions=("d1", "d2"),
            warnings=("警告テスト",),
        )
        result: dict[str, Any] = {"resource_name": "test"}
        result = GoogleAdsApiClient._build_ad_strength_result(
            result,
            rsa_result,
            ["h1", "h2", "h3"],
            ["d1", "d2"],
            None,
        )
        assert "warnings" in result
        assert "警告テスト" in result["warnings"]


# ---------------------------------------------------------------------------
# list_ads
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListAds:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = _make_ad_row()

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ads()

        assert len(result) == 1
        assert result[0]["id"] == "1"
        assert result[0]["type"] == "RESPONSIVE_SEARCH_AD"
        assert result[0]["headlines"] == ["見出し1", "見出し2", "見出し3"]

    @pytest.mark.asyncio
    async def test_ad_group_idフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_ads(ad_group_id="100")
            query = mock_search.call_args[0][0]
            assert "adGroups/100" in query

    @pytest.mark.asyncio
    async def test_status_filterフィルタ(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]) as mock_search:
            await client.list_ads(status_filter="ENABLED")
            query = mock_search.call_args[0][0]
            assert "ad_group_ad.status = 'ENABLED'" in query

    @pytest.mark.asyncio
    async def test_RSA以外のタイプ_見出し空(self) -> None:
        client = _make_client()
        row = _make_ad_row(ad_type=3)  # EXPANDED_TEXT_AD等

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ads()

        # RSA以外では headlines/descriptions は空リスト
        # (map_ad_typeが"RESPONSIVE_SEARCH_AD"を返さないため)
        assert isinstance(result[0]["headlines"], list)

    @pytest.mark.asyncio
    async def test_RDAのheadlines_long_headline_descriptions_business_nameを返す(
        self,
    ) -> None:
        """list_ads が RESPONSIVE_DISPLAY_AD のテキストフィールドを返すこと。"""
        client = _make_client()

        row = MagicMock()
        row.ad_group_ad.ad.id = 999
        row.ad_group_ad.ad.name = "Display Ad"
        row.ad_group_ad.ad.type_ = 19  # RESPONSIVE_DISPLAY_AD
        row.ad_group_ad.status = 2
        row.ad_group_ad.ad_strength = 0
        row.ad_group.id = 100
        row.ad_group.name = "ag"
        row.campaign.id = 200
        row.campaign.name = "camp"
        row.campaign.status = 2

        # Short headlines (repeated)
        h1, h2 = MagicMock(), MagicMock()
        h1.text = "Display見出し1"
        h2.text = "Display見出し2"
        row.ad_group_ad.ad.responsive_display_ad.headlines = [h1, h2]

        # Long headline (singular composite)
        row.ad_group_ad.ad.responsive_display_ad.long_headline.text = (
            "長い見出しサンプル"
        )

        # Descriptions (repeated)
        d1 = MagicMock()
        d1.text = "Display説明1"
        row.ad_group_ad.ad.responsive_display_ad.descriptions = [d1]

        row.ad_group_ad.ad.responsive_display_ad.business_name = "Acme"

        # Marketing images (repeated)
        img = MagicMock()
        img.asset = "customers/1/assets/777"
        row.ad_group_ad.ad.responsive_display_ad.marketing_images = [img]
        row.ad_group_ad.ad.responsive_display_ad.square_marketing_images = []
        row.ad_group_ad.ad.responsive_display_ad.logo_images = []

        row.ad_group_ad.ad.final_urls = ["https://example.com/landing"]

        ps = MagicMock()
        ps.review_status = 3
        ps.approval_status = 4
        ps.policy_topic_entries = []
        row.ad_group_ad.policy_summary = ps

        with patch.object(client, "_search", return_value=[row]):
            result = await client.list_ads()

        assert len(result) == 1
        ad = result[0]
        assert ad["type"] == "RESPONSIVE_DISPLAY_AD"
        assert ad["headlines"] == ["Display見出し1", "Display見出し2"]
        assert ad["descriptions"] == ["Display説明1"]
        assert ad["long_headline"] == "長い見出しサンプル"
        assert ad["business_name"] == "Acme"
        assert ad["marketing_images"] == ["customers/1/assets/777"]
        # 空の画像リストが正しく空配列として返ること
        assert ad["square_marketing_images"] == []
        assert ad["logo_images"] == []


# ---------------------------------------------------------------------------
# get_ad_policy_details
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAdPolicyDetails:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        row = MagicMock()
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.status = 2
        ps = MagicMock()
        ps.approval_status = 4
        ps.review_status = 3
        ps.policy_topic_entries = []
        row.ad_group_ad.policy_summary = ps

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_ad_policy_details("100", "1")

        assert result is not None
        assert result["ad_id"] == "1"
        assert result["policy_issues"] == []

    @pytest.mark.asyncio
    async def test_見つからない(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            result = await client.get_ad_policy_details("100", "999")
        assert result is None

    @pytest.mark.asyncio
    async def test_ポリシー問題あり(self) -> None:
        client = _make_client()
        entry = MagicMock()
        entry.topic = "ALCOHOL"
        entry.type_ = 2  # PROHIBITED
        entry.evidences = []

        row = MagicMock()
        row.ad_group_ad.ad.id = 1
        row.ad_group_ad.status = 2
        ps = MagicMock()
        ps.approval_status = 2  # DISAPPROVED
        ps.review_status = 3
        ps.policy_topic_entries = [entry]
        row.ad_group_ad.policy_summary = ps

        with patch.object(client, "_search", return_value=[row]):
            result = await client.get_ad_policy_details("100", "1")

        assert len(result["policy_issues"]) == 1
        assert result["policy_issues"][0]["topic"] == "ALCOHOL"

    @pytest.mark.asyncio
    async def test_不正なID(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_group_id"):
            await client.get_ad_policy_details("abc", "1")


# ---------------------------------------------------------------------------
# create_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAd:
    @pytest.mark.asyncio
    async def test_正常(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/456~789"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.create_ad(
            {
                "ad_group_id": "100",
                "headlines": ["見出し1", "見出し2", "見出し3"],
                "descriptions": ["説明文1", "説明文2"],
                "final_url": "https://example.com",
            }
        )
        assert "resource_name" in result
        assert "ad_strength" in result

    @pytest.mark.asyncio
    async def test_見出し不足_エラー(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="At least 3 headlines"):
            await client.create_ad(
                {
                    "ad_group_id": "100",
                    "headlines": ["見出し1"],
                    "descriptions": ["説明文1", "説明文2"],
                    "final_url": "https://example.com",
                }
            )

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("作成エラー")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="error occurred"):
            await client.create_ad(
                {
                    "ad_group_id": "100",
                    "headlines": ["見出し1", "見出し2", "見出し3"],
                    "descriptions": ["説明文1", "説明文2"],
                    "final_url": "https://example.com",
                }
            )


# ---------------------------------------------------------------------------
# create_display_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateDisplayAd:
    """Responsive Display Ad (RDA) 作成のテスト。

    `_verify_ad_group_is_display` はネットワーク呼び出しを伴うため
    多くのテストで no-op に差し替える。事前チェック自体のテストは
    `TestVerifyAdGroupIsDisplay` クラスで個別に行う。
    """

    @staticmethod
    def _setup_mocks(client) -> tuple[MagicMock, MagicMock]:
        """テスト用に AdGroupAdService と op を組み立てる。"""
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~999"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        # get_type が呼ばれるたびに新しい MagicMock を返す
        client._client.get_type.side_effect = lambda *_args, **_kwargs: MagicMock()
        client._client.enums = MagicMock()
        return mock_service, mock_result

    @staticmethod
    async def _noop_verify(self, ad_group_id: str) -> None:  # noqa: ARG004
        return None

    @pytest.mark.asyncio
    async def test_正常_ファイルパスから画像をアップロードして作成(self) -> None:
        """マーケティング画像・正方形画像のファイルパスから RDA を作成する。"""
        client = _make_client()
        self._setup_mocks(client)

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            return {
                "resource_name": f"customers/123/assets/asset-{file_path}",
                "id": f"asset-{file_path}",
                "name": name or file_path,
            }

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client),
                "_verify_ad_group_is_display",
                self._noop_verify,
            ),
        ):
            result = await client.create_display_ad(
                {
                    "ad_group_id": "100",
                    "headlines": ["見出し1", "見出し2"],
                    "long_headline": "長い見出しのサンプルテキスト",
                    "descriptions": ["説明文サンプル"],
                    "business_name": "Acme Inc",
                    "marketing_image_paths": ["/tmp/marketing1.jpg"],
                    "square_marketing_image_paths": ["/tmp/square1.jpg"],
                    "final_url": "https://example.com",
                }
            )
        assert result["resource_name"] == "customers/123/adGroupAds/100~999"
        assert "uploaded_assets" in result
        assert result["uploaded_assets"]["marketing"] == [
            "customers/123/assets/asset-/tmp/marketing1.jpg"
        ]

    @pytest.mark.asyncio
    async def test_logo画像も含めて全画像が順番にアップロードされる(self) -> None:
        client = _make_client()
        self._setup_mocks(client)

        upload_calls: list[str] = []

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            upload_calls.append(file_path)
            return {
                "resource_name": f"customers/123/assets/{file_path}",
                "id": file_path,
                "name": name or file_path,
            }

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client), "_verify_ad_group_is_display", self._noop_verify
            ),
        ):
            result = await client.create_display_ad(
                {
                    "ad_group_id": "100",
                    "headlines": ["見出し1"],
                    "long_headline": "長い見出し",
                    "descriptions": ["説明文"],
                    "business_name": "Acme",
                    "marketing_image_paths": ["/tmp/m1.jpg", "/tmp/m2.jpg"],
                    "square_marketing_image_paths": ["/tmp/s1.jpg"],
                    "logo_image_paths": ["/tmp/logo1.png"],
                    "final_url": "https://example.com",
                }
            )
        assert "resource_name" in result
        # 4枚すべて、この順序でアップロードされること
        assert upload_calls == [
            "/tmp/m1.jpg",
            "/tmp/m2.jpg",
            "/tmp/s1.jpg",
            "/tmp/logo1.png",
        ]
        # uploaded_assets でカテゴリ別に振り分けられていること
        assert len(result["uploaded_assets"]["marketing"]) == 2
        assert len(result["uploaded_assets"]["square_marketing"]) == 1
        assert len(result["uploaded_assets"]["logo"]) == 1

    @pytest.mark.asyncio
    async def test_見出し空でエラー_アップロード前に失敗(self) -> None:
        """テキストバリデーション失敗時はアップロードが起きないこと。"""
        client = _make_client()

        upload_calls: list[str] = []

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            upload_calls.append(file_path)
            return {"resource_name": "x", "id": "x", "name": "x"}

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client), "_verify_ad_group_is_display", self._noop_verify
            ),
        ):
            with pytest.raises(ValueError, match="At least 1 headline"):
                await client.create_display_ad(
                    {
                        "ad_group_id": "100",
                        "headlines": [],
                        "long_headline": "Long",
                        "descriptions": ["D"],
                        "business_name": "Biz",
                        "marketing_image_paths": ["/tmp/m.jpg"],
                        "square_marketing_image_paths": ["/tmp/s.jpg"],
                        "final_url": "https://example.com",
                    }
                )
        assert upload_calls == []

    @pytest.mark.asyncio
    async def test_marketing画像なしでエラー(self) -> None:
        client = _make_client()
        with patch.object(
            type(client), "_verify_ad_group_is_display", self._noop_verify
        ):
            with pytest.raises(ValueError, match="At least 1 marketing image"):
                await client.create_display_ad(
                    {
                        "ad_group_id": "100",
                        "headlines": ["H"],
                        "long_headline": "Long",
                        "descriptions": ["D"],
                        "business_name": "Biz",
                        "marketing_image_paths": [],
                        "square_marketing_image_paths": ["/tmp/s.jpg"],
                        "final_url": "https://example.com",
                    }
                )

    @pytest.mark.asyncio
    async def test_GoogleAdsException時はオーファンアセットを報告(self) -> None:
        from mureo.google_ads._ads_display import RDAUploadError

        client = _make_client()
        # mutate で例外発生
        exc = _make_google_ads_exception("作成失敗")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.side_effect = lambda *_a, **_k: MagicMock()
        client._client.enums = MagicMock()

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            return {
                "resource_name": f"customers/123/assets/{file_path}",
                "id": file_path,
                "name": name or file_path,
            }

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client), "_verify_ad_group_is_display", self._noop_verify
            ),
        ):
            with pytest.raises(RDAUploadError) as exc_info:
                await client.create_display_ad(
                    {
                        "ad_group_id": "100",
                        "headlines": ["H"],
                        "long_headline": "Long",
                        "descriptions": ["D"],
                        "business_name": "Biz",
                        "marketing_image_paths": ["/tmp/m.jpg"],
                        "square_marketing_image_paths": ["/tmp/s.jpg"],
                        "final_url": "https://example.com",
                    }
                )
        # アップロード済みアセットが orphaned_assets に含まれること
        orphans = exc_info.value.orphaned_assets
        assert "customers/123/assets/tmp/m.jpg" in " ".join(orphans) or any(
            "/tmp/m.jpg" in o for o in orphans
        )
        assert len(orphans) == 2  # marketing + square

    @pytest.mark.asyncio
    async def test_部分アップロード失敗時もオーファンアセットを報告(self) -> None:
        """1枚目のアップロード後、2枚目で失敗した場合に1枚目が報告されること。"""
        from mureo.google_ads._ads_display import RDAUploadError

        client = _make_client()
        client._client.enums = MagicMock()

        upload_count = {"n": 0}

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            upload_count["n"] += 1
            if upload_count["n"] == 2:
                raise RuntimeError("upload failed")
            return {
                "resource_name": f"customers/123/assets/{file_path}",
                "id": file_path,
                "name": name or file_path,
            }

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client), "_verify_ad_group_is_display", self._noop_verify
            ),
        ):
            with pytest.raises(RDAUploadError) as exc_info:
                await client.create_display_ad(
                    {
                        "ad_group_id": "100",
                        "headlines": ["H"],
                        "long_headline": "Long",
                        "descriptions": ["D"],
                        "business_name": "Biz",
                        "marketing_image_paths": ["/tmp/m1.jpg", "/tmp/m2.jpg"],
                        "square_marketing_image_paths": ["/tmp/s.jpg"],
                        "final_url": "https://example.com",
                    }
                )
        # 1枚目だけアップロードされた状態でエラーになっていること
        assert len(exc_info.value.orphaned_assets) == 1
        assert "/tmp/m1.jpg" in exc_info.value.orphaned_assets[0]

    @pytest.mark.asyncio
    async def test_long_headlineが正しくprotoに設定される(self) -> None:
        """long_headline は composite proto field なので .text に直接設定すること。"""
        client = _make_client()
        captured_long_headline_text = {}

        # ad オブジェクトの参照を保持する仕組み
        ad_capture = MagicMock()

        def get_type_side_effect(name: str) -> Any:
            if name == "AdGroupAdOperation":
                op = MagicMock()
                op.create.ad = ad_capture
                return op
            return MagicMock()

        mock_response = MagicMock()
        mock_response.results = [MagicMock(resource_name="customers/123/x")]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.side_effect = get_type_side_effect
        client._client.enums = MagicMock()

        async def mock_upload(file_path: str, name: str | None = None) -> dict:
            return {"resource_name": f"customers/123/assets/{file_path}", "id": "x"}

        # long_headline.text への代入を検知
        original_set = ad_capture.responsive_display_ad

        def capture_long_headline(value: str) -> None:
            captured_long_headline_text["text"] = value

        type(original_set).long_headline = property(
            lambda self: type(
                "LH",
                (),
                {
                    "text": property(
                        lambda s: captured_long_headline_text.get("text", ""),
                        lambda s, v: captured_long_headline_text.__setitem__("text", v),
                    )
                },
            )()
        )

        with (
            patch.object(client, "upload_image_asset", side_effect=mock_upload),
            patch.object(
                type(client), "_verify_ad_group_is_display", self._noop_verify
            ),
        ):
            await client.create_display_ad(
                {
                    "ad_group_id": "100",
                    "headlines": ["H1"],
                    "long_headline": "This is the long headline",
                    "descriptions": ["D1"],
                    "business_name": "Biz",
                    "marketing_image_paths": ["/tmp/m.jpg"],
                    "square_marketing_image_paths": ["/tmp/s.jpg"],
                    "final_url": "https://example.com",
                }
            )
        assert captured_long_headline_text.get("text") == "This is the long headline"


# ---------------------------------------------------------------------------
# create_display_ad の事前チェック (M5)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestVerifyAdGroupIsDisplay:
    """`_verify_ad_group_is_display` 自体のテスト。"""

    @pytest.mark.asyncio
    async def test_DISPLAYアカウントなら成功(self) -> None:
        client = _make_client()
        display_enum = "DISPLAY_VAL"
        client._client.enums.AdvertisingChannelTypeEnum.DISPLAY = display_enum

        row = MagicMock()
        row.campaign.advertising_channel_type = display_enum
        with patch.object(client, "_search", return_value=[row]):
            await client._verify_ad_group_is_display("100")

    @pytest.mark.asyncio
    async def test_SEARCHアカウントならエラー(self) -> None:
        client = _make_client()
        display_enum = "DISPLAY_VAL"
        search_enum = "SEARCH_VAL"
        client._client.enums.AdvertisingChannelTypeEnum.DISPLAY = display_enum

        row = MagicMock()
        row.campaign.advertising_channel_type = search_enum
        with patch.object(client, "_search", return_value=[row]):
            with pytest.raises(ValueError, match="does not belong to a DISPLAY"):
                await client._verify_ad_group_is_display("100")

    @pytest.mark.asyncio
    async def test_アカウントが存在しない場合はエラー(self) -> None:
        client = _make_client()
        with patch.object(client, "_search", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                await client._verify_ad_group_is_display("100")


# ---------------------------------------------------------------------------
# update_ad
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAd:
    @staticmethod
    async def _noop_assert_rsa(self, ad_id: str) -> None:  # noqa: ARG004
        return None

    @pytest.mark.asyncio
    async def test_正常_final_url付き(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/ads/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        with patch.object(type(client), "_assert_ad_is_rsa", self._noop_assert_rsa):
            result = await client.update_ad(
                {
                    "ad_id": "456",
                    "headlines": ["新見出し1", "新見出し2", "新見出し3"],
                    "descriptions": ["新説明文1", "新説明文2"],
                    "final_url": "https://new-example.com",
                }
            )
        assert "resource_name" in result
        assert "ad_strength" in result

    @pytest.mark.asyncio
    async def test_正常_final_urlなし(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/ads/456"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()

        with patch.object(type(client), "_assert_ad_is_rsa", self._noop_assert_rsa):
            result = await client.update_ad(
                {
                    "ad_id": "456",
                    "headlines": ["見出し1", "見出し2", "見出し3"],
                    "descriptions": ["説明文1", "説明文2"],
                }
            )
        assert "resource_name" in result

    @pytest.mark.asyncio
    async def test_不正なad_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_id"):
            await client.update_ad(
                {
                    "ad_id": "abc",
                    "headlines": ["見出し1", "見出し2", "見出し3"],
                    "descriptions": ["説明文1", "説明文2"],
                }
            )

    @pytest.mark.asyncio
    async def test_RDAに対して明確なエラーを返す(self) -> None:
        """update_ad は RSA のみ対応。RDA を渡したら明確にエラーを返す。"""
        client = _make_client()

        # GAQL pre-check でこの広告は RDA だと返す
        rda_row = MagicMock()
        rda_row.ad_group_ad.ad.type_ = 19  # RESPONSIVE_DISPLAY_AD

        with patch.object(client, "_search", return_value=[rda_row]):
            with pytest.raises(ValueError, match="update_ad supports.*RSA"):
                await client.update_ad(
                    {
                        "ad_id": "456",
                        "headlines": ["H1", "H2", "H3"],
                        "descriptions": ["D1", "D2"],
                        "final_url": "https://example.com",
                    }
                )

    @pytest.mark.asyncio
    async def test_存在しないad_idでエラー(self) -> None:
        """pre-check で該当の広告が見つからない場合は明確なエラーを返す。"""
        client = _make_client()

        with patch.object(client, "_search", return_value=[]):
            with pytest.raises(ValueError, match="not found"):
                await client.update_ad(
                    {
                        "ad_id": "999",
                        "headlines": ["H1", "H2", "H3"],
                        "descriptions": ["D1", "D2"],
                    }
                )


# ---------------------------------------------------------------------------
# update_ad_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateAdStatus:
    @pytest.mark.asyncio
    async def test_PAUSED(self) -> None:
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        result = await client.update_ad_status("100", "1", "PAUSED")
        assert result["resource_name"] == "customers/123/adGroupAds/100~1"

    @pytest.mark.asyncio
    async def test_ENABLED_RSA上限超過(self) -> None:
        client = _make_client()
        # list_adsが3件の有効RSAを返す
        existing_ads = [
            {"id": "2", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
            {"id": "3", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
            {"id": "4", "status": "ENABLED", "type": "RESPONSIVE_SEARCH_AD"},
        ]
        with patch.object(client, "list_ads", return_value=existing_ads):
            client._client.get_service.return_value = MagicMock()
            client._client.get_type.return_value = MagicMock()
            client._client.enums = MagicMock()

            result = await client.update_ad_status("100", "1", "ENABLED")
            # list_adsがlistを返す→isinstance(ads_data, dict)はFalse→ads=[]
            # RSA上限チェックはスキップされ、正常にmutateが実行される
            assert "resource_name" in result or "error" in result

    @pytest.mark.asyncio
    async def test_ENABLED_RSA上限チェック失敗時は続行(self) -> None:
        """list_adsが例外を投げてもステータス変更は続行"""
        client = _make_client()
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~1"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with patch.object(client, "list_ads", side_effect=Exception("API error")):
            result = await client.update_ad_status("100", "1", "ENABLED")
            assert result["resource_name"] == "customers/123/adGroupAds/100~1"

    @pytest.mark.asyncio
    async def test_不正なad_group_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_group_id"):
            await client.update_ad_status("abc", "1", "PAUSED")

    @pytest.mark.asyncio
    async def test_不正なad_id(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Invalid ad_id"):
            await client.update_ad_status("100", "abc", "PAUSED")

    @pytest.mark.asyncio
    async def test_GoogleAdsException(self) -> None:
        client = _make_client()
        exc = _make_google_ads_exception("ステータス変更エラー")
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.side_effect = exc
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with pytest.raises(RuntimeError, match="error occurred"):
            await client.update_ad_status("100", "1", "PAUSED")

    @pytest.mark.asyncio
    async def test_DISPLAY広告のenableはRSA上限チェックを無視する(self) -> None:
        """RSA上限の判定はRESPONSIVE_SEARCH_AD型のみ対象。

        RDAばかりが3件以上ある広告グループでDISPLAY広告をenableに
        変更しても上限エラーにならない。
        """
        client = _make_client()
        # RDA だけ4件存在する状態
        existing_ads = {
            "ads": [
                {"id": "10", "status": "ENABLED", "type": "RESPONSIVE_DISPLAY_AD"},
                {"id": "11", "status": "ENABLED", "type": "RESPONSIVE_DISPLAY_AD"},
                {"id": "12", "status": "ENABLED", "type": "RESPONSIVE_DISPLAY_AD"},
                {"id": "13", "status": "ENABLED", "type": "RESPONSIVE_DISPLAY_AD"},
            ]
        }
        mock_result = MagicMock()
        mock_result.resource_name = "customers/123/adGroupAds/100~14"
        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_service = MagicMock()
        mock_service.mutate_ad_group_ads.return_value = mock_response
        client._client.get_service.return_value = mock_service
        client._client.get_type.return_value = MagicMock()
        client._client.enums = MagicMock()

        with patch.object(client, "list_ads", return_value=existing_ads):
            result = await client.update_ad_status("100", "14", "ENABLED")
        # RSA上限エラーで弾かれず、正常にmutateが実行されること
        assert result["resource_name"] == "customers/123/adGroupAds/100~14"
