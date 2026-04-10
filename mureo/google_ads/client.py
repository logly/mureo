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

    from mureo.throttle import Throttler

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
_SMART_BIDDING_STRATEGIES = frozenset(
    {
        "MAXIMIZE_CONVERSIONS",
        "TARGET_CPA",
        "TARGET_ROAS",
    }
)
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
    """Decorator that logs GoogleAdsException details and re-raises with a generic message.

    Technical API error details are only logged; a generic message is returned to the LLM.
    """

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(self, *args, **kwargs)
            except GoogleAdsException as exc:
                detail = self._extract_error_detail(exc)
                logger.error(
                    "%s failed: %s (campaign=%s)",
                    label,
                    detail,
                    args[0] if args else kwargs,
                )
                # Return a specific hint for RESOURCE_NOT_FOUND
                if self._has_error_code(exc, "mutate_error", "RESOURCE_NOT_FOUND"):
                    raise RuntimeError(
                        f"{label} failed: The specified resource was not found. "
                        "Please verify the ID is correct. "
                        "Retrieve the latest ID using a list tool (e.g., ads.list) and try again."
                    ) from exc
                raise RuntimeError(
                    f"An error occurred while processing {label}."
                ) from exc

        return wrapper  # type: ignore[return-value]

    return decorator


# Import after _wrap_mutate_error definition (avoid circular import)
from mureo.google_ads._ads import _AdsMixin  # noqa: E402
from mureo.google_ads._ads_display import _DisplayAdsMixin  # noqa: E402
from mureo.google_ads._extensions import _ExtensionsMixin  # noqa: E402
from mureo.google_ads._keywords import _KeywordsMixin  # noqa: E402

# Threshold ratio for warning when search partner CPA exceeds Google Search CPA
PARTNER_CPA_WARNING_RATIO: float = 2.0


class GoogleAdsApiClient(  # type: ignore[misc]
    _AdsMixin,
    _DisplayAdsMixin,
    _KeywordsMixin,
    _MonitoringMixin,
    _ExtensionsMixin,
    _DiagnosticsMixin,
    _AnalysisMixin,
    _CreativeMixin,
    _MediaMixin,
):
    """Client wrapping Google Ads API operations."""

    @staticmethod
    def _validate_id(value: str, field_name: str) -> str:
        """Validate that ID contains only digits."""
        if not _ID_PATTERN.fullmatch(value):
            raise ValueError(f"Invalid {field_name}: {value}")
        return value

    @staticmethod
    def _validate_status(status: str) -> str:
        """Validate status value against whitelist."""
        upper = status.upper()
        if upper not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        return upper

    @staticmethod
    def _validate_match_type(match_type: str) -> str:
        """Validate match type against whitelist."""
        upper = match_type.upper()
        if upper not in _VALID_MATCH_TYPES:
            raise ValueError(
                f"Invalid match_type: {match_type} (must be one of BROAD, PHRASE, EXACT)"
            )
        return upper

    @staticmethod
    def _validate_recommendation_type(rec_type: str) -> str:
        """Validate recommendation type against whitelist."""
        upper = rec_type.upper()
        if upper not in _VALID_RECOMMENDATION_TYPES:
            raise ValueError(f"Invalid recommendation_type: {rec_type}")
        return upper

    @staticmethod
    def _validate_date(value: str, field_name: str) -> str:
        """Validate YYYY-MM-DD date format."""
        if not _DATE_PATTERN.fullmatch(value):
            raise ValueError(
                f"Invalid {field_name}: {value} (please specify in YYYY-MM-DD format)"
            )
        return value

    @staticmethod
    def _validate_resource_name(
        value: str, pattern: re.Pattern[str], field_name: str
    ) -> str:
        """Validate resource name format."""
        if not pattern.fullmatch(value):
            raise ValueError(f"Invalid {field_name}: {value}")
        return value

    def __init__(
        self,
        credentials: Credentials,
        customer_id: str,
        developer_token: str,
        login_customer_id: str | None = None,
        throttler: Throttler | None = None,
    ) -> None:
        # login_customer_id resolution order:
        # 1. Explicitly provided value
        # 2. customer_id itself (fallback for standalone accounts)
        resolved_login_id = login_customer_id or customer_id.replace("-", "")
        self._client = GoogleAdsClient(
            credentials=credentials,
            developer_token=developer_token,
            login_customer_id=resolved_login_id,
        )
        self._customer_id = customer_id.replace("-", "")
        self._throttler = throttler

    def _get_service(self, service_name: str) -> Any:
        return self._client.get_service(service_name)

    async def _search(self, query: str) -> list[Any]:
        """Execute Google Ads GAQL search in thread pool.

        gRPC calls are synchronous and block the event loop,
        so we offload them to a thread via run_in_executor.
        """
        if self._throttler is not None:
            await self._throttler.acquire()
        ga_service = self._get_service("GoogleAdsService")
        # Log the beginning of the query for debugging
        query_hint = query.strip().split("\n")[0][:60]
        logger.info("_search start: %s", query_hint)

        def _do_search() -> list[Any]:
            response = ga_service.search(customer_id=self._customer_id, query=query)
            return list(response)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _do_search)
        logger.info("_search done: %s (%d rows)", query_hint, len(result))
        return result

    @staticmethod
    def _extract_error_detail(exc: GoogleAdsException) -> str:
        """Extract the first error message from GoogleAdsException."""
        for error in exc.failure.errors:
            if hasattr(error, "message"):
                return str(error.message)
        return str(exc)

    @staticmethod
    def _has_error_code(
        exc: GoogleAdsException, attr_name: str, error_name: str
    ) -> bool:
        """Check if the exception has a specific error code."""
        for error in exc.failure.errors:
            err_val = getattr(error.error_code, attr_name, None)
            if err_val is not None:  # noqa: SIM102
                if err_val.name == error_name:
                    return True
        return False

    @staticmethod
    def _escape_gaql_string(value: str) -> str:
        """Escape for GAQL string literals."""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    @staticmethod
    def _extract_evidences(entry: Any) -> list[str]:
        """Extract evidence text from a policy topic entry."""
        evidences: list[str] = []
        if not entry.evidences:
            return evidences
        for ev in entry.evidences:
            if ev.text_list and ev.text_list.texts:
                evidences.extend(list(ev.text_list.texts))
        return evidences

    # === Account ===

    async def list_accounts(self) -> list[dict[str, Any]]:
        """List accessible accounts."""
        service = self._get_service("CustomerService")
        response = service.list_accessible_customers()
        return [{"customer_id": cid} for cid in response.resource_names]

    # === Campaigns ===

    async def list_campaigns(
        self, status_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """List campaigns."""
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
            # Calculate daily budget from campaign_budget.amount_micros
            if hasattr(row, "campaign_budget") and row.campaign_budget.amount_micros:
                camp["daily_budget"] = row.campaign_budget.amount_micros / 1_000_000
            results.append(camp)
        return results

    async def get_campaign(self, campaign_id: str) -> dict[str, Any] | None:
        """Campaign details (including bidding strategy parameters)."""
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
            # Budget information
            b = row.campaign_budget
            result["budget_daily"] = b.amount_micros / 1_000_000
            result["budget_status"] = map_entity_status(b.status)
            # Bidding strategy detail parameters
            result["bidding_details"] = self._extract_bidding_details(row.campaign)
            return result
        return None

    async def _check_budget_bidding_compatibility(
        self, budget_id: str, bidding_strategy: str
    ) -> None:
        """Validate compatibility between shared budgets and smart bidding strategies."""
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
                    f"Bidding strategy {bidding_strategy} is not compatible with shared budgets. "
                    "Create an individual budget with budget.create, or "
                    "select MAXIMIZE_CLICKS/MANUAL_CPC strategy."
                )

    async def create_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create campaign.

        Args:
            params: Campaign parameters.
                name: Campaign name (required, max 256 chars)
                bidding_strategy: Bidding strategy (default: MAXIMIZE_CLICKS)
                budget_id: Optional budget ID
                channel_type: "SEARCH" (default) or "DISPLAY"
        """
        name = params["name"]
        if len(name) > 256:
            raise ValueError(
                f"Campaign name must be 256 characters or less (currently {len(name)} chars)"
            )
        channel_type = params.get("channel_type", "SEARCH").upper()
        if channel_type not in ("SEARCH", "DISPLAY"):
            raise ValueError(
                f"channel_type must be 'SEARCH' or 'DISPLAY' (got '{channel_type}')"
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
        # Channel type and network settings. Use explicit branches so a
        # future third channel type cannot silently fall through to the
        # SEARCH branch — every value must be handled explicitly.
        if channel_type == "SEARCH":
            campaign.advertising_channel_type = (
                self._client.enums.AdvertisingChannelTypeEnum.SEARCH
            )
        elif channel_type == "DISPLAY":
            campaign.advertising_channel_type = (
                self._client.enums.AdvertisingChannelTypeEnum.DISPLAY
            )
        else:  # pragma: no cover - validated above
            raise ValueError(f"Unsupported channel_type: {channel_type}")
        campaign.status = self._client.enums.CampaignStatusEnum.PAUSED
        campaign.contains_eu_political_advertising = (
            self._client.enums.EuPoliticalAdvertisingStatusEnum.DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING
        )
        if channel_type == "SEARCH":
            campaign.network_settings.target_google_search = True
            campaign.network_settings.target_search_network = True
            campaign.network_settings.target_content_network = False
            campaign.network_settings.target_partner_search_network = False
        elif channel_type == "DISPLAY":
            campaign.network_settings.target_google_search = False
            campaign.network_settings.target_search_network = False
            campaign.network_settings.target_content_network = True
            campaign.network_settings.target_partner_search_network = False
        else:  # pragma: no cover - validated above
            raise ValueError(f"Unsupported channel_type: {channel_type}")
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
                logger.error("Campaign creation failed: %s", detail)
                raise RuntimeError(
                    "An error occurred while processing campaign creation."
                ) from e
            logger.warning(
                "Campaign with same name already exists: name=%s", params["name"]
            )
            return await self._find_campaign_by_name(params["name"])

    _SUPPORTED_BIDDING_STRATEGIES = frozenset(
        {
            "MAXIMIZE_CLICKS",
            "MANUAL_CPC",
            "MAXIMIZE_CONVERSIONS",
            "TARGET_CPA",
            "TARGET_ROAS",
        }
    )

    def _set_bidding_strategy(
        self, campaign: Any, strategy: str, params: dict[str, Any]
    ) -> None:
        """Set campaign bidding strategy."""
        strategy_upper = strategy.upper()
        if strategy_upper not in self._SUPPORTED_BIDDING_STRATEGIES:
            raise ValueError(
                f"Unsupported bidding strategy: {strategy}. "
                f"Available: {', '.join(sorted(self._SUPPORTED_BIDDING_STRATEGIES))}"
            )
        if strategy_upper == "MAXIMIZE_CLICKS":
            # In v23, MAXIMIZE_CLICKS is controlled via target_spend field
            target_spend = self._client.get_type("TargetSpend")
            ceiling = params.get("cpc_bid_ceiling_micros")
            if ceiling is not None:
                ceiling_val = int(ceiling)
                if ceiling_val <= 0:
                    raise ValueError(
                        f"cpc_bid_ceiling_micros must be a positive integer: {ceiling_val}"
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
                    "TARGET_CPA strategy requires target_cpa_micros (target CPA)"
                )
            cpa_value = int(params["target_cpa_micros"])
            if cpa_value <= 0:
                raise ValueError(
                    f"target_cpa_micros must be a positive integer: {cpa_value}"
                )
            target_cpa = self._client.get_type("TargetCpa")
            target_cpa.target_cpa_micros = cpa_value
            self._client.copy_from(campaign.target_cpa, target_cpa)
        elif strategy_upper == "TARGET_ROAS":
            if "target_roas_value" not in params:
                raise ValueError(
                    "TARGET_ROAS strategy requires target_roas_value (target ROAS)"
                )
            roas_value = float(params["target_roas_value"])
            if roas_value <= 0:
                raise ValueError(
                    f"target_roas_value must be a positive number: {roas_value}"
                )
            target_roas = self._client.get_type("TargetRoas")
            target_roas.target_roas = roas_value
            self._client.copy_from(campaign.target_roas, target_roas)

    async def _find_campaign_by_name(self, name: str) -> dict[str, Any]:
        """Search for existing campaign by name."""
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
                "note": "A campaign with the same name already exists; returning the existing campaign",
            }
        raise ValueError(f"Campaign with same name '{name}' was not found")

    # Bidding strategy -> FieldMask path mapping
    # In v23, bidding strategies with sub-fields cause
    # "field with subfields" error with parent paths, so we specify leaf paths
    _BIDDING_FIELD_PATHS: dict[str, list[str]] = {
        "MAXIMIZE_CLICKS": ["target_spend.target_spend_micros"],
        "MANUAL_CPC": ["manual_cpc.enhanced_cpc_enabled"],
        "MAXIMIZE_CONVERSIONS": ["maximize_conversions.target_cpa_micros"],
        "TARGET_CPA": ["target_cpa.target_cpa_micros"],
        "TARGET_ROAS": ["target_roas.target_roas"],
    }

    @_wrap_mutate_error("campaign update")
    async def update_campaign(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update campaign settings (name, bidding strategy, etc.)."""
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

        # Detect invalid parameter combinations
        strategy_raw = params.get("bidding_strategy", "").upper()
        if strategy_raw == "MAXIMIZE_CLICKS" and "target_cpa_micros" in params:
            raise ValueError(
                "MAXIMIZE_CLICKS does not support target_cpa_micros. "
                "Use cpc_bid_ceiling_micros to set a max CPC"
            )

        if "bidding_strategy" in params:
            strategy = params["bidding_strategy"].upper()
            self._set_bidding_strategy(campaign, strategy, params)
            bidding_paths = self._BIDDING_FIELD_PATHS.get(strategy)
            if bidding_paths is None:
                raise ValueError(
                    f"Field paths for bidding strategy {strategy} are undefined"
                )
            field_paths.extend(bidding_paths)
            # Additional path when max CPC is specified
            if strategy == "MAXIMIZE_CLICKS" and "cpc_bid_ceiling_micros" in params:
                field_paths.append("target_spend.cpc_bid_ceiling_micros")
        elif "cpc_bid_ceiling_micros" in params:
            # Update only max CPC without changing bidding strategy
            ceiling_val = int(params["cpc_bid_ceiling_micros"])
            if ceiling_val <= 0:
                raise ValueError(
                    f"cpc_bid_ceiling_micros must be a positive integer: {ceiling_val}"
                )
            campaign.target_spend.cpc_bid_ceiling_micros = ceiling_val
            field_paths.append("target_spend.cpc_bid_ceiling_micros")

        if not field_paths:
            raise ValueError(
                "No fields specified for update (name, bidding_strategy, etc.)"
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

    @_wrap_mutate_error("campaign status change")
    async def update_campaign_status(
        self, campaign_id: str, status: str
    ) -> dict[str, Any]:
        """Change campaign status

        For REMOVED, use remove operation due to API constraints。
        For ENABLED/PAUSED, use update operation to change status。
        """
        self._validate_id(campaign_id, "campaign_id")
        validated_status = self._validate_status(status)
        campaign_service = self._get_service("CampaignService")
        campaign_op = self._client.get_type("CampaignOperation")

        if validated_status == "REMOVED":
            # REMOVED requires a remove operation, not update
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

    # === Ad Groups ===

    async def list_ad_groups(  # type: ignore[override]
        self,
        campaign_id: str | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List ad groups."""
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

    @_wrap_mutate_error("ad group creation")
    async def create_ad_group(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create ad group."""
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

    @_wrap_mutate_error("ad group update")
    async def update_ad_group(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update ad group."""
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
                    "message": f"Invalid status: {params['status']}. Specify ENABLED or PAUSED.",
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
                "message": "No fields specified for update. Specify at least one of name, status, or cpc_bid_micros.",
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

    # === Budgets ===

    async def get_budget(self, campaign_id: str) -> dict[str, Any] | None:
        """Get campaign budget."""
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

    @_wrap_mutate_error("budget update")
    async def update_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """Update budget

        Note: BudgetGuard validation is performed on the Managed side.
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

    # === Performance Report ===

    async def get_performance_report(  # type: ignore[override]
        self,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """Performance report."""
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
        """Network-level performance report (Google Search vs Search Partners)."""
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
            # SEARCH = Google Search, SEARCH_PARTNERS = Search Partners, skip others
            if network_type not in ("SEARCH", "SEARCH_PARTNERS", "2", "3"):
                continue
            cost_micros = row.metrics.cost_micros
            conversions = float(row.metrics.conversions)
            cost = cost_micros / 1_000_000
            cpa = cost / conversions if conversions > 0 else 0
            results.append(
                {
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": str(row.campaign.name),
                    "network_type": (
                        "SEARCH"
                        if network_type in ("SEARCH", "2")
                        else "SEARCH_PARTNERS"
                    ),
                    "network_label": (
                        "Google Search"
                        if network_type in ("SEARCH", "2")
                        else "Search Partners"
                    ),
                    "impressions": int(row.metrics.impressions),
                    "clicks": int(row.metrics.clicks),
                    "cost": round(cost, 0),
                    "conversions": conversions,
                    "ctr": round(float(row.metrics.ctr) * 100, 2),
                    "average_cpc": round(float(row.metrics.average_cpc) / 1_000_000, 0),
                    "cost_per_conversion": round(cpa, 0),
                }
            )
        return results

    async def get_ad_performance_report(
        self,
        ad_group_id: str | None = None,
        campaign_id: str | None = None,
        period: str = "LAST_30_DAYS",
    ) -> list[dict[str, Any]]:
        """Ad-level performance report."""
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

    # === Budget Creation ===

    async def create_budget(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a new campaign budget."""
        name = params["name"]
        if len(name) > 256:
            raise ValueError(
                f"Budget name must be 256 characters or less (currently {len(name)} chars)"
            )
        amount = params["amount"]
        if amount <= 0:
            raise ValueError(
                f"Daily budget must be a positive number (specified: {amount})"
            )
        # Note: BudgetGuard absolute ceiling check is performed on the Managed side.
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
                logger.error("Budget creation failed: %s", detail)
                raise RuntimeError(
                    "An error occurred while processing budget creation."
                ) from e
            logger.warning(
                "Budget with same name already exists: name=%s", params["name"]
            )
            return await self._find_budget_by_name(params["name"])

    async def _find_budget_by_name(self, name: str) -> dict[str, Any]:
        """Search for existing budget by name and return it."""
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
                "note": "A budget with the same name already exists; returning the existing budget",
            }
        raise ValueError(
            f"Budget with same name '{name}' should exist but was not found"
        )

    def _period_to_date_clause(self, period: str) -> str:
        """Return a GAQL date condition clause.

        Predefined period -> ``DURING LAST_7_DAYS`` format
        Custom range -> ``BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'`` format

        The return value can be used directly as ``WHERE segments.date {return_value}``.
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
            raise ValueError(f"Invalid period: {period}")
        return f"DURING {result}"
