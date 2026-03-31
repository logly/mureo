from __future__ import annotations

import asyncio
import functools
import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.protobuf.field_mask_pb2 import FieldMask as PbFieldMask

if TYPE_CHECKING:
    from google.oauth2.credentials import Credentials

from mureo.google_ads._analysis import _AnalysisMixin
from mureo.google_ads._creative import _CreativeMixin
from mureo.google_ads._diagnostics import _DiagnosticsMixin
from mureo.google_ads._media import _MediaMixin
from mureo.google_ads._monitoring import _MonitoringMixin
from mureo.google_ads.mappers import (
    map_ad_group,
    map_ad_performance_report,
    map_campaign,
    map_entity_status,
    map_performance_report,
)

logger = logging.getLogger(__name__)


_VALID_STATUSES = frozenset({"ENABLED", "PAUSED", "REMOVED"})
_SMART_BIDDING_STRATEGIES = frozenset({
    "MAXIMIZE_CONVERSIONS", "TARGET_CPA", "TARGET_ROAS",
})
_VALID_MATCH_TYPES = frozenset({"BROAD", "PHRASE", "EXACT"})
_VALID_RECOMMENDATION_TYPES = frozenset(
    {
        "CAMPAIGN_BUDGET",
        "KEYWORD",
        "TEXT_AD",
        "TARGET_CPA_OPT_IN",
        "MAXIMIZE_CONVERSIONS_OPT_IN",
        "ENHANCED_CPC_OPT_IN",
        "SEARCH_PARTNERS_OPT_IN",
        "MAXIMIZE_CLICKS_OPT_IN",
        "OPTIMIZE_AD_ROTATION",
        "KEYWORD_MATCH_TYPE",
        "MOVE_UNUSED_BUDGET",
        "RESPONSIVE_SEARCH_AD",
        "MARGINAL_ROI_CAMPAIGN_BUDGET",
        "USE_BROAD_MATCH_KEYWORD",
        "RESPONSIVE_SEARCH_AD_ASSET",
        "RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH",
        "DISPLAY_EXPANSION_OPT_IN",
        "SITELINK_ASSET",
        "CALLOUT_ASSET",
        "CALL_ASSET",
    }
)
_ID_PATTERN = re.compile(r"\d+")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


_F = TypeVar("_F", bound=Callable[..., Any])


def _wrap_mutate_error(label: str) -> Callable[[_F], _F]:
    """GoogleAdsException をログに記録し、汎用メッセージで再送出するデコレータ

    APIエラーの技術的詳細はログのみに記録し、LLMには汎用メッセージを返す。
    """

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(self, *args, **kwargs)
            except GoogleAdsException as exc:
                detail = self._extract_error_detail(exc)
                logger.error(
                    "%sに失敗: %s (campaign=%s)",
                    label,
                    detail,
                    args[0] if args else kwargs,
                )
                # RESOURCE_NOT_FOUND の場合は具体的なヒントを返す
                if self._has_error_code(exc, "mutate_error", "RESOURCE_NOT_FOUND"):
                    raise RuntimeError(
                        f"{label}に失敗: 指定されたリソースが見つかりません。"
                        "IDが正しいか確認してください。"
                        "一覧取得ツール（ads.list等）で最新のIDを取得してから再試行してください。"
                    ) from exc
                raise RuntimeError(
                    f"{label}の処理中にエラーが発生しました。"
                ) from exc

        return wrapper  # type: ignore[return-value]

    return decorator


# _wrap_mutate_error 定義後にインポート（循環参照回避）
from mureo.google_ads._ads import _AdsMixin  # noqa: E402
from mureo.google_ads._extensions import _ExtensionsMixin  # noqa: E402
from mureo.google_ads._keywords import _KeywordsMixin  # noqa: E402

# 検索パートナーCPAがGoogle検索の何倍以上で警告とするかの閾値
PARTNER_CPA_WARNING_RATIO: float = 2.0


class GoogleAdsApiClient(
    _AdsMixin,
    _KeywordsMixin,
    _MonitoringMixin,
    _ExtensionsMixin,
    _DiagnosticsMixin,
    _AnalysisMixin,
    _CreativeMixin,
    _MediaMixin,
):
    """Google Ads APIの操作をラップするクライアント"""

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        """IDが数値のみであることを検証する"""
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError(f"不正な{field_name}: {value}")
        return value

    @staticmethod
    def _validate_status(status: str) -> str:
        """ステータス値をホワイトリストで検証する"""
        upper = status.upper()
        if upper not in _VALID_STATUSES:
            raise ValueError(f"不正なステータス: {status}")
        return upper

    @staticmethod
    def _validate_match_type(match_type: str) -> str:
        """マッチタイプをホワイトリストで検証する"""
        upper = match_type.upper()
        if upper not in _VALID_MATCH_TYPES:
            raise ValueError(
                f"不正なmatch_type: {match_type} (BROAD, PHRASE, EXACT のいずれかを指定)"
            )
        return upper

    @staticmethod
    def _validate_recommendation_type(rec_type: str) -> str:
        """推奨事項タイプをホワイトリストで検証する"""
        upper = rec_type.upper()
        if upper not in _VALID_RECOMMENDATION_TYPES:
            raise ValueError(f"不正なrecommendation_type: {rec_type}")
        return upper

    @staticmethod
    def _validate_date(value: str, field_name: str) -> str:
        """YYYY-MM-DD形式であることを検証する"""
        if not _DATE_PATTERN.fullmatch(value):
            raise ValueError(
                f"不正な{field_name}: {value} (YYYY-MM-DD形式で指定してください)"
            )
        return value

    @staticmethod
    def _validate_resource_name(
        value: str, pattern: re.Pattern[str], field_name: str
    ) -> str:
        """リソース名のフォーマットを検証する"""
        if not pattern.fullmatch(value):
            raise ValueError(f"不正な{field_name}: {value}")
        return value

    def __init__(
        self,
        credentials: Credentials,
        customer_id: str,
        developer_token: str,
        login_customer_id: str | None = None,
    ) -> None:
        # login_customer_id の決定順序:
        # 1. 明示的に指定された値
        # 2. customer_id 自身（独立アカウント用フォールバック）
        resolved_login_id = (
            login_customer_id
            or customer_id.replace("-", "")
        )
        self._client = GoogleAdsClient(
            credentials=credentials,
            developer_token=developer_token,
            login_customer_id=resolved_login_id,
        )
        self._customer_id = customer_id.replace("-", "")

    def _get_service(self, service_name: str) -> Any:
        return self._client.get_service(service_name)

    async def _search(self, query: str) -> list[Any]:
        """Google Ads GAQL検索をスレッドプールで実行する

        gRPC呼び出しは同期的でイベントループをブロックするため、
        run_in_executorでスレッドに逃がす。
        """
        ga_service = self._get_service("GoogleAdsService")
        # クエリの先頭部分をログに出力（デバッグ用）
        query_hint = query.strip().split("\n")[0][:60]
        logger.info("_search 開始: %s", query_hint)

        def _do_search() -> list[Any]:
            response = ga_service.search(
                customer_id=self._customer_id, query=query
            )
            return list(response)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _do_search)
        logger.info("_search 完了: %s (%d件)", query_hint, len(result))
        return result

    @staticmethod
    def _extract_error_detail(exc: GoogleAdsException) -> str:
        """GoogleAdsException から最初のエラーメッセージを抽出"""
        for error in exc.failure.errors:
            if hasattr(error, "message"):
                return str(error.message)
        return str(exc)

    @staticmethod
    def _has_error_code(exc: GoogleAdsException, attr_name: str, error_name: str) -> bool:
        """特定のエラーコードを持つか判定"""
        for error in exc.failure.errors:
            err_val = getattr(error.error_code, attr_name, None)
            if err_val is not None:  # noqa: SIM102
                if err_val.name == error_name:
                    return True
        return False

    @staticmethod
    def _escape_gaql_string(value: str) -> str:
        """GAQL文字列リテラル用にエスケープする"""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _extract_evidences(entry: Any) -> list[str]:
        """ポリシートピックエントリからエビデンステキストを抽出する"""
        evidences: list[str] = []
        if not entry.evidences:
            return evidences
        for ev in entry.evidences:
            if ev.text_list and ev.text_list.texts:
                evidences.extend(list(ev.text_list.texts))
        return evidences

    # === アカウント ===

    async def list_accounts(self) -> list[dict[str, Any]]:
        """管理アカウント一覧"""
        service = self._get_service("CustomerService")
        response = service.list_accessible_customers()
        return [{"customer_id": cid} for cid in response.resource_names]

    # === キャンペーン ===

    async def list_campaigns(
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """キャンペーン一覧"""
        query = """
            SELECT
                campaign.id, campaign.name, campaign.status,
                campaign.serving_status,
                campaign.bidding_strategy_type,
                campaign.campaign_budget,
                campaign.primary_status,
                campaign_budget.amount_micros
            FROM campaign
            ORDER BY campaign.id
        """
        if status_filter:
            validated = self._validate_status(status_filter)
            query = query.replace(
                "ORDER BY",
                f"WHERE campaign.status = '{validated}'\n            ORDER BY",
            )
        rows = await self._search(query)
        results = []
        for row in rows:
            camp = map_campaign(row.campaign)
            # campaign_budget.amount_micros から日予算（円）を算出
            if hasattr(row, "campaign_budget") and row.campaign_budget.amount_micros:
                camp["daily_budget"] = (
                    row.campaign_budget.amount_micros / 1_000_000
                )
            results.append(camp)
        return results

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        """キャンペーン詳細（入札戦略パラメータ含む）"""
        self._validate_id(campaign_id, "campaign_id")
        query = f"""
            SELECT
                campaign.id, campaign.name, campaign.status,
                campaign.serving_status,
                campaign.bidding_strategy_type,
                campaign.campaign_budget,
                campaign_budget.amount_micros,
                campaign_budget.status,
                campaign.primary_status,
                campaign.primary_status_reasons,
                campaign.bidding_strategy_system_status,
                campaign.target_impression_share.location,
                campaign.target_impression_share.location_fraction_micros,
                campaign.target_impression_share.cpc_bid_ceiling_micros,
                campaign.maximize_conversions.target_cpa_micros,
                campaign.target_cpa.target_cpa_micros,
                campaign.target_roas.target_roas,
                campaign.target_spend.cpc_bid_ceiling_micros
            FROM campaign
            WHERE campaign.id = {campaign_id}
        """
        response = await self._search(query)
        for row in response:
            result = map_campaign(row.campaign)
            # 予算情報
            b = row.campaign_budget
            result["budget_daily"] = b.amount_micros / 1_000_000
            result["budget_status"] = map_entity_status(b.status)
            # 入札戦略の詳細パラメータ
            result["bidding_details"] = self._extract_bidding_details(row.campaign)
            return result
        return None

    async def _check_budget_bidding_compatibility(
        self, budget_id: str, bidding_strategy: str
    ) -> None:
        """共有予算とスマート入札戦略の互換性を検証する"""
        self._validate_id(budget_id, "budget_id")
        if bidding_strategy.upper() not in _SMART_BIDDING_STRATEGIES:
            return
        query = f"""
            SELECT campaign_budget.explicitly_shared
            FROM campaign_budget
            WHERE campaign_budget.id = {budget_id}
        """
        response = await self._search(query)
        for row in response:
            if row.campaign_budget.explicitly_shared:
                raise ValueError(
                    f"入札戦略 {bidding_strategy} は共有予算と互換性がありません。"
                    "budget.createで個別予算を作成するか、"
                    "MAXIMIZE_CLICKS/MANUAL_CPC戦略を選択してください。"
                )

    async def create_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """キャンペーン作成"""
        name = params["name"]
        if len(name) > 256:
            raise ValueError(
                f"キャンペーン名は256文字以内にしてください（現在{len(name)}文字）"
            )
        bidding_strategy = params.get("bidding_strategy", "MAXIMIZE_CLICKS")
        if "budget_id" in params:
            self._validate_id(params["budget_id"], "budget_id")
            await self._check_budget_bidding_compatibility(
                params["budget_id"], bidding_strategy
            )
        campaign_service = self._get_service("CampaignService")
        campaign_op = self._client.get_type("CampaignOperation")
        campaign = campaign_op.create
        campaign.name = name
        campaign.advertising_channel_type = (
            self._client.enums.AdvertisingChannelTypeEnum.SEARCH
        )
        campaign.status = self._client.enums.CampaignStatusEnum.PAUSED
        campaign.contains_eu_political_advertising = (
            self._client.enums.EuPoliticalAdvertisingStatusEnum
            .DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        )
        campaign.network_settings.target_google_search = True
        campaign.network_settings.target_search_network = True
        campaign.network_settings.target_content_network = False
        campaign.network_settings.target_partner_search_network = False
        self._set_bidding_strategy(campaign, bidding_strategy, params)
        if "budget_id" in params:
            campaign.campaign_budget = self._client.get_service(
                "CampaignBudgetService"
            ).campaign_budget_path(self._customer_id, params["budget_id"])
        try:
            response = campaign_service.mutate_campaigns(
                customer_id=self._customer_id,
                operations=[campaign_op],
            )
            return {"resource_name": response.results[0].resource_name}
        except GoogleAdsException as e:
            if not self._has_error_code(e, "campaign_error", "DUPLICATE_CAMPAIGN_NAME"):
                detail = self._extract_error_detail(e)
                logger.error("キャンペーン作成に失敗: %s", detail)
                raise RuntimeError("キャンペーン作成の処理中にエラーが発生しました。") from e
            logger.warning("同名キャンペーンが既に存在: name=%s", params["name"])
            return await self._find_campaign_by_name(params["name"])

    _SUPPORTED_BIDDING_STRATEGIES = frozenset({
        "MAXIMIZE_CLICKS",
        "MANUAL_CPC",
        "MAXIMIZE_CONVERSIONS",
        "TARGET_CPA",
        "TARGET_ROAS",
    })

    def _set_bidding_strategy(
        self, campaign: Any, strategy: str, params: dict[str, Any]
    ) -> None:
        """キャンペーンの入札戦略を設定"""
        strategy_upper = strategy.upper()
        if strategy_upper not in self._SUPPORTED_BIDDING_STRATEGIES:
            raise ValueError(
                f"サポートされていない入札戦略: {strategy}。"
                f"使用可能: {', '.join(sorted(self._SUPPORTED_BIDDING_STRATEGIES))}"
            )
        if strategy_upper == "MAXIMIZE_CLICKS":
            # v23ではMAXIMIZE_CLICKSはtarget_spendフィールドで制御
            target_spend = self._client.get_type("TargetSpend")
            ceiling = params.get("cpc_bid_ceiling_micros")
            if ceiling is not None:
                ceiling_val = int(ceiling)
                if ceiling_val <= 0:
                    raise ValueError(
                        f"cpc_bid_ceiling_microsは正の整数である必要があります: {ceiling_val}"
                    )
                target_spend.cpc_bid_ceiling_micros = ceiling_val
            self._client.copy_from(campaign.target_spend, target_spend)
        elif strategy_upper == "MANUAL_CPC":
            self._client.copy_from(
                campaign.manual_cpc,
                self._client.get_type("ManualCpc"),
            )
        elif strategy_upper == "MAXIMIZE_CONVERSIONS":
            self._client.copy_from(
                campaign.maximize_conversions,
                self._client.get_type("MaximizeConversions"),
            )
        elif strategy_upper == "TARGET_CPA":
            if "target_cpa_micros" not in params:
                raise ValueError(
                    "TARGET_CPA戦略にはtarget_cpa_micros（目標CPA）の指定が必要です"
                )
            cpa_value = int(params["target_cpa_micros"])
            if cpa_value <= 0:
                raise ValueError(
                    f"target_cpa_microsは正の整数である必要があります: {cpa_value}"
                )
            target_cpa = self._client.get_type("TargetCpa")
            target_cpa.target_cpa_micros = cpa_value
            self._client.copy_from(campaign.target_cpa, target_cpa)
        elif strategy_upper == "TARGET_ROAS":
            if "target_roas_value" not in params:
                raise ValueError(
                    "TARGET_ROAS戦略にはtarget_roas_value（目標ROAS）の指定が必要です"
                )
            roas_value = float(params["target_roas_value"])
            if roas_value <= 0:
                raise ValueError(
                    f"target_roas_valueは正の数値である必要があります: {roas_value}"
                )
            target_roas = self._client.get_type("TargetRoas")
            target_roas.target_roas = roas_value
            self._client.copy_from(campaign.target_roas, target_roas)

    async def _find_campaign_by_name(self, name: str) -> dict[str, Any]:
        """キャンペーン名で既存キャンペーンを検索"""
        safe_name = self._escape_gaql_string(name)
        query = f"""
            SELECT campaign.id, campaign.name, campaign.status
            FROM campaign
            WHERE campaign.name = '{safe_name}'
            LIMIT 1
        """
        response = await self._search(query)
        for row in response:
            return {
                "resource_name": row.campaign.resource_name,
                "campaign_id": str(row.campaign.id),
                "note": "同名のキャンペーンが既に存在するため、既存のキャンペーンを返しました",
            }
        raise ValueError(f"同名キャンペーン '{name}' が見つかりませんでした")

    # 入札戦略 → FieldMask パスの対応
    # v23ではサブフィールドを持つ入札戦略は親パスだと
    # "field with subfields" エラーになるため、リーフパスを指定する
    _BIDDING_FIELD_PATHS: dict[str, list[str]] = {
        "MAXIMIZE_CLICKS": ["target_spend.target_spend_micros"],
        "MANUAL_CPC": ["manual_cpc.enhanced_cpc_enabled"],
        "MAXIMIZE_CONVERSIONS": ["maximize_conversions.target_cpa_micros"],
        "TARGET_CPA": ["target_cpa.target_cpa_micros"],
        "TARGET_ROAS": ["target_roas.target_roas"],
    }

    @_wrap_mutate_error("キャンペーン更新")
    async def update_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """キャンペーンの設定を更新（名前・入札戦略等）"""
        campaign_service = self._get_service("CampaignService")
        campaign_op = self._client.get_type("CampaignOperation")
        campaign = campaign_op.update
        campaign_id = params["campaign_id"]
        self._validate_id(campaign_id, "campaign_id")
        campaign.resource_name = self._client.get_service(
            "CampaignService"
        ).campaign_path(self._customer_id, campaign_id)

        field_paths: list[str] = []
        if "name" in params:
            campaign.name = params["name"]
            field_paths.append("name")

        # パラメータの不正な組み合わせを検出
        strategy_raw = params.get("bidding_strategy", "").upper()
        if strategy_raw == "MAXIMIZE_CLICKS" and "target_cpa_micros" in params:
            raise ValueError(
                "MAXIMIZE_CLICKS（クリック数の最大化）にtarget_cpa_micros（目標CPA）は使用できません。"
                "上限CPCを設定するにはcpc_bid_ceiling_microsを使用してください"
            )

        if "bidding_strategy" in params:
            strategy = params["bidding_strategy"].upper()
            self._set_bidding_strategy(campaign, strategy, params)
            bidding_paths = self._BIDDING_FIELD_PATHS.get(strategy)
            if bidding_paths is None:
                raise ValueError(f"入札戦略 {strategy} のフィールドパスが未定義です")
            field_paths.extend(bidding_paths)
            # 上限CPC指定時は追加パス
            if strategy == "MAXIMIZE_CLICKS" and "cpc_bid_ceiling_micros" in params:
                field_paths.append("target_spend.cpc_bid_ceiling_micros")
        elif "cpc_bid_ceiling_micros" in params:
            # 入札戦略変更なしで上限CPCのみ更新
            ceiling_val = int(params["cpc_bid_ceiling_micros"])
            if ceiling_val <= 0:
                raise ValueError(
                    f"cpc_bid_ceiling_microsは正の整数である必要があります: {ceiling_val}"
                )
            campaign.target_spend.cpc_bid_ceiling_micros = ceiling_val
            field_paths.append("target_spend.cpc_bid_ceiling_micros")

        if not field_paths:
            raise ValueError(
                "更新するフィールドが指定されていません（name, bidding_strategy 等）"
            )

        self._client.copy_from(
            campaign_op.update_mask,
            PbFieldMask(paths=field_paths),
        )
        response = campaign_service.mutate_campaigns(
            customer_id=self._customer_id,
            operations=[campaign_op],
        )
        return {"resource_name": response.results[0].resource_name}

    @_wrap_mutate_error("キャンペーンステータス変更")
    async def update_campaign_status(
        self, campaign_id: str, status: str
    ) -> dict[str, Any]:
        """キャンペーンのステータスを変更

        REMOVEDの場合はAPIの制約上removeオペレーションを使用する。
        ENABLED/PAUSEDの場合はupdateオペレーションでステータスを変更する。
        """
        self._validate_id(campaign_id, "campaign_id")
        validated_status = self._validate_status(status)
        campaign_service = self._get_service("CampaignService")
        campaign_op = self._client.get_type("CampaignOperation")

        if validated_status == "REMOVED":
            # REMOVEDはupdateではなくremoveオペレーションが必要
            campaign_op.remove = campaign_service.campaign_path(
                self._customer_id, campaign_id
            )
        else:
            campaign = campaign_op.update
            campaign.resource_name = campaign_service.campaign_path(
                self._customer_id, campaign_id
            )
            status_enum = self._client.enums.CampaignStatusEnum
            campaign.status = getattr(status_enum, validated_status)
            self._client.copy_from(
                campaign_op.update_mask,
                PbFieldMask(paths=["status"]),
            )

        response = campaign_service.mutate_campaigns(
            customer_id=self._customer_id,
            operations=[campaign_op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === 広告グループ ===

    async def list_ad_groups(
        self,
        campaign_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """広告グループ一覧"""
        query = """
            SELECT
                ad_group.id, ad_group.name, ad_group.status,
                ad_group.campaign, ad_group.cpc_bid_micros,
                campaign.id, campaign.name, campaign.status
            FROM ad_group
        """
        conditions: list[str] = []
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            conditions.append(
                f"ad_group.campaign = 'customers/{self._customer_id}/campaigns/{campaign_id}'"
            )
        if status_filter:
            validated = self._validate_status(status_filter)
            conditions.append(f"ad_group.status = '{validated}'")
        if conditions:
            query += "\n            WHERE " + " AND ".join(conditions)
        query += "\n            ORDER BY ad_group.id"
        response = await self._search(query)
        return [map_ad_group(row.ad_group, row.campaign) for row in response]

    @_wrap_mutate_error("広告グループ作成")
    async def create_ad_group(self, params: dict[str, Any]) -> dict[str, Any]:
        """広告グループ作成"""
        ad_group_service = self._get_service("AdGroupService")
        ad_group_op = self._client.get_type("AdGroupOperation")
        ad_group = ad_group_op.create
        ad_group.name = params["name"]
        ad_group.campaign = self._client.get_service("CampaignService").campaign_path(
            self._customer_id, params["campaign_id"]
        )
        ad_group.status = self._client.enums.AdGroupStatusEnum.ENABLED
        if "cpc_bid_micros" in params:
            ad_group.cpc_bid_micros = params["cpc_bid_micros"]
        response = ad_group_service.mutate_ad_groups(
            customer_id=self._customer_id,
            operations=[ad_group_op],
        )
        return {"resource_name": response.results[0].resource_name}

    @_wrap_mutate_error("広告グループ更新")
    async def update_ad_group(self, params: dict[str, Any]) -> dict[str, Any]:
        """広告グループ更新"""
        ad_group_service = self._get_service("AdGroupService")
        ad_group_op = self._client.get_type("AdGroupOperation")
        ad_group = ad_group_op.update
        ad_group.resource_name = self._client.get_service(
            "AdGroupService"
        ).ad_group_path(self._customer_id, params["ad_group_id"])
        update_fields = []
        if "name" in params:
            ad_group.name = params["name"]
            update_fields.append("name")
        if "status" in params:
            status_map = {
                "ENABLED": self._client.enums.AdGroupStatusEnum.ENABLED,
                "PAUSED": self._client.enums.AdGroupStatusEnum.PAUSED,
            }
            status_val = status_map.get(params["status"].upper())
            if status_val is None:
                return {
                    "error": True,
                    "error_type": "validation_error",
                    "message": f"無効なstatusです: {params['status']}。ENABLED または PAUSED を指定してください。",
                }
            ad_group.status = status_val
            update_fields.append("status")
        if "cpc_bid_micros" in params:
            ad_group.cpc_bid_micros = params["cpc_bid_micros"]
            update_fields.append("cpc_bid_micros")
        if not update_fields:
            return {
                "error": True,
                "error_type": "validation_error",
                "message": "更新するフィールドが指定されていません。name, status, cpc_bid_micros のいずれかを指定してください。",
            }
        self._client.copy_from(
            ad_group_op.update_mask,
            PbFieldMask(paths=update_fields),
        )
        response = ad_group_service.mutate_ad_groups(
            customer_id=self._customer_id,
            operations=[ad_group_op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === 予算 ===

    async def get_budget(self, campaign_id: str) -> dict[str, Any] | None:
        """キャンペーン予算を取得"""
        self._validate_id(campaign_id, "campaign_id")
        query = f"""
            SELECT
                campaign.id,
                campaign_budget.id,
                campaign_budget.amount_micros,
                campaign_budget.total_amount_micros,
                campaign_budget.status
            FROM campaign_budget
            WHERE campaign.id = {campaign_id}
        """
        response = await self._search(query)
        for row in response:
            budget = row.campaign_budget
            return {
                "id": str(budget.id),
                "daily_budget": budget.amount_micros / 1_000_000,
                "daily_budget_micros": budget.amount_micros,
                "status": str(budget.status),
            }
        return None

    @_wrap_mutate_error("予算更新")
    async def update_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """予算更新

        注意: BudgetGuardによるバリデーションはManaged側で実施する。
        """
        new_amount = params["amount"]

        budget_service = self._get_service("CampaignBudgetService")
        budget_op = self._client.get_type("CampaignBudgetOperation")
        budget = budget_op.update
        budget.resource_name = budget_service.campaign_budget_path(
            self._customer_id, params["budget_id"]
        )
        budget.amount_micros = int(new_amount * 1_000_000)
        self._client.copy_from(
            budget_op.update_mask,
            PbFieldMask(paths=["amount_micros"]),
        )
        response = budget_service.mutate_campaign_budgets(
            customer_id=self._customer_id,
            operations=[budget_op],
        )
        return {"resource_name": response.results[0].resource_name}

    # === パフォーマンスレポート ===

    async def get_performance_report(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """パフォーマンスレポート"""
        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.ctr, metrics.average_cpc,
                metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date {date_clause}
        """
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n            AND campaign.id = {campaign_id}"
        response = await self._search(query)
        return map_performance_report(list(response))

    async def get_network_performance_report(
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """ネットワーク別パフォーマンスレポート（Google検索 vs 検索パートナー）"""
        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                campaign.id, campaign.name,
                segments.ad_network_type,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.ctr, metrics.average_cpc,
                metrics.cost_per_conversion
            FROM campaign
            WHERE segments.date {date_clause}
        """
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            query += f"\n            AND campaign.id = {campaign_id}"
        response = await self._search(query)

        results: list[dict[str, Any]] = []
        for row in response:
            network_type = str(row.segments.ad_network_type).replace(
                "AdNetworkType.", ""
            )
            # SEARCH = Google検索, SEARCH_PARTNERS = 検索パートナー, その他はスキップ
            if network_type not in ("SEARCH", "SEARCH_PARTNERS", "2", "3"):
                continue
            cost_micros = row.metrics.cost_micros
            conversions = float(row.metrics.conversions)
            cost = cost_micros / 1_000_000
            cpa = cost / conversions if conversions > 0 else 0
            results.append({
                "campaign_id": str(row.campaign.id),
                "campaign_name": str(row.campaign.name),
                "network_type": (
                    "SEARCH" if network_type in ("SEARCH", "2") else "SEARCH_PARTNERS"
                ),
                "network_label": (
                    "Google検索" if network_type in ("SEARCH", "2") else "検索パートナー"
                ),
                "impressions": int(row.metrics.impressions),
                "clicks": int(row.metrics.clicks),
                "cost": round(cost, 0),
                "conversions": conversions,
                "ctr": round(float(row.metrics.ctr) * 100, 2),
                "average_cpc": round(
                    float(row.metrics.average_cpc) / 1_000_000, 0
                ),
                "cost_per_conversion": round(cpa, 0),
            })
        return results

    async def get_ad_performance_report(
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """広告単位のパフォーマンスレポート"""
        date_clause = self._period_to_date_clause(period)
        query = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.type,
                ad_group_ad.status,
                ad_group.id, ad_group.name,
                campaign.id, campaign.name,
                metrics.impressions, metrics.clicks, metrics.cost_micros,
                metrics.conversions, metrics.ctr, metrics.average_cpc,
                metrics.cost_per_conversion
            FROM ad_group_ad
            WHERE segments.date {date_clause}
        """
        conditions: list[str] = []
        if ad_group_id:
            self._validate_id(ad_group_id, "ad_group_id")
            conditions.append(
                f"ad_group_ad.ad_group = 'customers/{self._customer_id}/adGroups/{ad_group_id}'"
            )
        if campaign_id:
            self._validate_id(campaign_id, "campaign_id")
            conditions.append(f"campaign.id = {campaign_id}")
        if conditions:
            query += "\n            AND " + " AND ".join(conditions)
        response = await self._search(query)
        return map_ad_performance_report(list(response))

    # === 予算作成 ===

    async def create_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """キャンペーン予算を新規作成"""
        name = params["name"]
        if len(name) > 256:
            raise ValueError(
                f"予算名は256文字以内にしてください（現在{len(name)}文字）"
            )
        amount = params["amount"]
        if amount <= 0:
            raise ValueError(
                f"日予算は正の数値を指定してください（指定値: {amount}）"
            )
        # 注意: BudgetGuardによる絶対上限チェックはManaged側で実施する。
        budget_service = self._get_service("CampaignBudgetService")
        budget_op = self._client.get_type("CampaignBudgetOperation")
        budget = budget_op.create
        budget.name = name
        budget.amount_micros = int(amount * 1_000_000)
        budget.explicitly_shared = False
        budget.delivery_method = self._client.enums.BudgetDeliveryMethodEnum.STANDARD
        try:
            response = budget_service.mutate_campaign_budgets(
                customer_id=self._customer_id,
                operations=[budget_op],
            )
            return {"resource_name": response.results[0].resource_name}
        except GoogleAdsException as e:
            if not self._has_error_code(e, "campaign_budget_error", "DUPLICATE_NAME"):
                detail = self._extract_error_detail(e)
                logger.error("予算作成に失敗: %s", detail)
                raise RuntimeError("予算作成の処理中にエラーが発生しました。") from e
            logger.warning("同名予算が既に存在: name=%s", params["name"])
            return await self._find_budget_by_name(params["name"])

    async def _find_budget_by_name(self, name: str) -> dict[str, Any]:
        """予算名で既存予算を検索して返す"""
        safe_name = self._escape_gaql_string(name)
        query = f"""
            SELECT
                campaign_budget.resource_name,
                campaign_budget.id,
                campaign_budget.amount_micros
            FROM campaign_budget
            WHERE campaign_budget.name = '{safe_name}'
            LIMIT 1
        """
        response = await self._search(query)
        for row in response:
            return {
                "resource_name": row.campaign_budget.resource_name,
                "budget_id": str(row.campaign_budget.id),
                "amount_micros": row.campaign_budget.amount_micros,
                "note": "同名の予算が既に存在するため、既存の予算を返しました",
            }
        raise ValueError(f"同名予算 '{name}' が存在するはずですが、検索で見つかりませんでした")

    def _period_to_date_clause(self, period: str) -> str:
        """GAQL の日付条件句を返す。

        定義済み期間 → ``DURING LAST_7_DAYS`` 形式
        カスタム範囲 → ``BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`` 形式

        戻り値は ``WHERE segments.date {return_value}`` としてそのまま使える。
        """
        if period.upper().startswith("BETWEEN"):
            return period
        period_map = {
            "TODAY": "TODAY",
            "YESTERDAY": "YESTERDAY",
            "LAST_7_DAYS": "LAST_7_DAYS",
            "LAST_14_DAYS": "LAST_14_DAYS",
            "LAST_30_DAYS": "LAST_30_DAYS",
            "LAST_MONTH": "LAST_MONTH",
            "THIS_MONTH": "THIS_MONTH",
        }
        result = period_map.get(period.upper())
        if result is None:
            raise ValueError(f"不正なperiod: {period}")
        return f"DURING {result}"
