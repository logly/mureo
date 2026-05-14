"""``GoogleAdsAdapter`` — Protocol-conformant wrapper over ``GoogleAdsApiClient``.

The adapter implements three runtime-checkable Protocols
(:class:`CampaignProvider`, :class:`KeywordProvider`,
:class:`ExtensionProvider`) by delegating each Phase 1 method to the
existing :class:`GoogleAdsApiClient`. The Audience Protocol is
deliberately NOT implemented in Phase 1 (CTO decision: ``mureo/google_ads``
has no audience mixin).

Sync ↔ async bridge
-------------------
The Protocols are synchronous; the underlying client methods are
``async``. Each Protocol method calls ``asyncio.run`` on the relevant
coroutine. If a caller is already inside a running event loop,
``asyncio.run`` itself raises ``RuntimeError`` — this is exactly the
documented Phase 1 contract.

Module foundation rule
----------------------
Imports are restricted to stdlib, ``mureo.core.providers.*``,
``mureo.google_ads.client`` (only the public ``GoogleAdsApiClient``),
and the intra-package ``mappers`` / ``errors`` modules. The AST scan in
``tests/adapters/google_ads/test_imports.py`` enforces this allowlist.
"""

# ruff: noqa: TC003
# ``date`` must stay at module top-level so ``typing.get_type_hints()``
# can resolve method annotations (Protocol structural checks).
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from datetime import date
from typing import Any, TypeVar

from mureo.adapters.google_ads.errors import UnsupportedOperation
from mureo.adapters.google_ads.mappers import (
    to_ad,
    to_campaign,
    to_campaigns,
    to_daily_report_row,
    to_extension,
    to_keyword,
    to_search_term,
)
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    CreateAdRequest,
    CreateCampaignRequest,
    DailyReportRow,
    Extension,
    ExtensionKind,
    ExtensionRequest,
    ExtensionStatus,
    Keyword,
    KeywordSpec,
    KeywordStatus,
    SearchTerm,
    UpdateAdRequest,
    UpdateCampaignRequest,
)
from mureo.google_ads.client import GoogleAdsApiClient

_T = TypeVar("_T")


logger = logging.getLogger(__name__)


# Static digit-only check for GAQL ``campaign.id = X`` interpolation.
# Re-derived locally (instead of importing the private gaql_validator)
# so the adapter stays inside its import allowlist.
def _validate_campaign_id(value: str) -> str:
    """Return ``value`` if it is a bare digit string, else raise ``ValueError``."""
    if not isinstance(value, str) or not value or not value.isdigit():
        raise ValueError(
            f"invalid campaign_id: {value!r} (must be digits-only, GAQL safety)"
        )
    return value


class GoogleAdsAdapter:
    """Adapter that exposes ``GoogleAdsApiClient`` as three Phase 1 Protocols.

    BaseProvider attributes are class attributes so the registry can
    introspect them without instantiation.
    """

    name: str = "google_ads"
    display_name: str = "Google Ads"
    capabilities: frozenset[Capability] = frozenset(
        {
            Capability.READ_CAMPAIGNS,
            Capability.READ_PERFORMANCE,
            Capability.READ_KEYWORDS,
            Capability.READ_SEARCH_TERMS,
            Capability.READ_EXTENSIONS,
            Capability.WRITE_BUDGET,
            Capability.WRITE_CREATIVE,
            Capability.WRITE_KEYWORDS,
            Capability.WRITE_EXTENSIONS,
            Capability.WRITE_CAMPAIGN_STATUS,
        }
    )

    def __init__(self, client: GoogleAdsApiClient) -> None:
        if not isinstance(client, GoogleAdsApiClient):
            raise TypeError(
                f"GoogleAdsAdapter requires a GoogleAdsApiClient instance, "
                f"got {type(client).__name__}"
            )
        self._client: GoogleAdsApiClient = client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _account_id(self) -> str:
        # CTO-approved single private-attribute read; tracked for a
        # follow-up rename of ``GoogleAdsApiClient._customer_id`` → public.
        return self._client._customer_id  # noqa: SLF001

    @staticmethod
    def _run(coro: Awaitable[_T]) -> _T:
        """Run ``coro`` to completion on a fresh event loop.

        ``asyncio.run`` raises ``RuntimeError`` when called from inside a
        running loop — that is the documented Phase 1 behaviour for
        async callers and is allowed to propagate.
        """
        return asyncio.run(coro)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # CampaignProvider — campaigns
    # ------------------------------------------------------------------

    def list_campaigns(
        self, filters: CampaignFilters | None = None
    ) -> tuple[Campaign, ...]:
        """List campaigns, applying optional client-side filters.

        ``filters.status`` is forwarded to the underlying client as the
        upper-case enum string. ``filters.name_contains`` is honored
        **client-side** after fetch (Phase 1; push-down to GAQL is a
        future refactor).
        """
        status_filter: str | None = None
        if filters is not None and filters.status is not None:
            status_filter = filters.status.value.upper()
        rows = self._run(self._client.list_campaigns(status_filter=status_filter))
        campaigns = to_campaigns(rows, account_id=self._account_id)
        if filters is not None and filters.name_contains is not None:
            needle = filters.name_contains
            campaigns = tuple(c for c in campaigns if needle in c.name)
        return campaigns

    def get_campaign(self, campaign_id: str) -> Campaign:
        raw = self._run(self._client.get_campaign(campaign_id))
        if raw is None:
            raise KeyError(campaign_id)
        return to_campaign(raw, account_id=self._account_id)

    def create_campaign(self, request: CreateCampaignRequest) -> Campaign:
        """Create a campaign and return the post-create refreshed entity.

        Builds a budget first (when ``daily_budget_micros > 0``), then
        the campaign, then re-fetches the campaign for a typed return.

        Phase 1 limitations
        -------------------
        * ``request.start_date`` and ``request.end_date`` are NOT wired
          through to the underlying client yet. Supplying either field
          raises :class:`UnsupportedOperation` instead of being silently
          dropped (CTO directive: silent failures are worse than an
          explicit refusal).
        * The budget micros value is forwarded to
          ``GoogleAdsApiClient.create_budget`` via the integer
          ``amount_micros`` key so float precision is preserved
          end-to-end (no ``micros / 1_000_000`` round-trip).
        """
        if request.start_date is not None or request.end_date is not None:
            raise UnsupportedOperation(
                "create_campaign: start_date/end_date are not yet wired in Phase 1; "
                "schedule fields will be implemented in a follow-up task."
            )

        params: dict[str, Any] = {"name": request.name}
        if request.daily_budget_micros and request.daily_budget_micros > 0:
            budget_response = self._run(
                self._client.create_budget(
                    {
                        "name": f"budget-{request.name}",
                        "amount_micros": request.daily_budget_micros,
                    }
                )
            )
            budget_id = budget_response.get("budget_id") or budget_response.get(
                "resource_name"
            )
            if budget_id is not None:
                params["budget_id"] = str(budget_id)
        if request.bidding_strategy is not None:
            params["bidding_strategy"] = request.bidding_strategy.value.upper()

        created = self._run(self._client.create_campaign(params))
        new_campaign_id = self._extract_new_id(created, key="campaign_id")
        return self.get_campaign(new_campaign_id)

    def update_campaign(
        self, campaign_id: str, request: UpdateCampaignRequest
    ) -> Campaign:
        """Apply the partial ``request`` and return the refreshed campaign.

        Phase 1 limitation
        ------------------
        ``request.daily_budget_micros`` is NOT wired through to the
        underlying client yet — budget mutation lives on a different
        resource (``CampaignBudget``) and the cross-resource update path
        is deferred to a follow-up task. Supplying the field raises
        :class:`UnsupportedOperation` instead of being silently dropped.
        """
        if request.daily_budget_micros is not None:
            raise UnsupportedOperation(
                "update_campaign: daily_budget_micros is not yet wired in Phase 1; "
                "budget mutation is deferred to a follow-up task."
            )

        params: dict[str, Any] = {"campaign_id": campaign_id}
        if request.name is not None:
            params["name"] = request.name
        if request.bidding_strategy is not None:
            params["bidding_strategy"] = request.bidding_strategy.value.upper()

        # update_campaign requires at least one mutable field; only
        # invoke it when there is something to set besides status.
        if len(params) > 1:
            self._run(self._client.update_campaign(params))

        if request.status is not None:
            self._run(
                self._client.update_campaign_status(
                    campaign_id, request.status.value.upper()
                )
            )

        return self.get_campaign(campaign_id)

    # ------------------------------------------------------------------
    # CampaignProvider — ads
    # ------------------------------------------------------------------

    def list_ads(self, campaign_id: str) -> tuple[Ad, ...]:
        # The underlying client filters by ``ad_group_id``, not
        # ``campaign_id``; Phase 1 fetches all ads (status not filtered)
        # and the post-mapping ``campaign_id`` is sourced from the
        # protocol parameter rather than the row. This keeps the
        # adapter contract honest about its scope while accepting the
        # higher fetch cost — a future refactor can introduce a
        # campaign-scoped GAQL helper on the client.
        rows = self._run(self._client.list_ads())
        return tuple(
            to_ad(row, account_id=self._account_id, campaign_id=campaign_id)
            for row in rows
        )

    def get_ad(self, campaign_id: str, ad_id: str) -> Ad:
        for ad in self.list_ads(campaign_id):
            if ad.id == ad_id:
                return ad
        raise KeyError(ad_id)

    def create_ad(self, campaign_id: str, request: CreateAdRequest) -> Ad:
        params: dict[str, Any] = {
            "ad_group_id": request.ad_group_id,
            "headlines": list(request.headlines),
            "descriptions": list(request.descriptions),
        }
        if request.final_urls is not None:
            params["final_urls"] = list(request.final_urls)
        if request.path1 is not None:
            params["path1"] = request.path1
        if request.path2 is not None:
            params["path2"] = request.path2

        created = self._run(self._client.create_ad(params))
        new_ad_id = self._extract_new_id(created, key="ad_id")
        return self.get_ad(campaign_id, new_ad_id)

    def update_ad(self, campaign_id: str, ad_id: str, request: UpdateAdRequest) -> Ad:
        params: dict[str, Any] = {"ad_id": ad_id}
        if request.headlines is not None:
            params["headlines"] = list(request.headlines)
        if request.descriptions is not None:
            params["descriptions"] = list(request.descriptions)
        if request.final_urls is not None:
            params["final_urls"] = list(request.final_urls)
        if request.path1 is not None:
            params["path1"] = request.path1
        if request.path2 is not None:
            params["path2"] = request.path2

        self._run(self._client.update_ad(params))
        return self.get_ad(campaign_id, ad_id)

    def set_ad_status(self, campaign_id: str, ad_id: str, status: AdStatus) -> Ad:
        # The underlying client requires ``ad_group_id`` for the mutate
        # call. Phase 1 retrieves it from the most recent list_ads row
        # for the requested ``ad_id`` so the protocol surface stays
        # ad-group-free.
        ad_group_id = self._resolve_ad_group_id(campaign_id, ad_id)
        self._run(
            self._client.update_ad_status(ad_group_id, ad_id, status.value.upper())
        )
        return self.get_ad(campaign_id, ad_id)

    # ------------------------------------------------------------------
    # CampaignProvider — daily report
    # ------------------------------------------------------------------

    def daily_report(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[DailyReportRow, ...]:
        """Return day-grain rows using ``client.search_gaql``.

        The GAQL is built from ``datetime.date.isoformat()`` (locked by
        Python to ``YYYY-MM-DD``) and the digit-only-validated
        ``campaign_id`` — no user-controlled string lands in the query
        unsanitized.
        """
        validated_id = _validate_campaign_id(campaign_id)
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        query = (
            "SELECT segments.date, "
            "metrics.impressions, metrics.clicks, "
            "metrics.cost_micros, metrics.conversions "
            "FROM campaign "
            f"WHERE campaign.id = {validated_id} "
            f"AND segments.date BETWEEN '{start_iso}' AND '{end_iso}'"
        )
        rows = self._run(self._client.search_gaql(query))
        return tuple(to_daily_report_row(r) for r in rows)

    # ------------------------------------------------------------------
    # KeywordProvider
    # ------------------------------------------------------------------

    def list_keywords(self, campaign_id: str) -> tuple[Keyword, ...]:
        rows = self._run(self._client.list_keywords(campaign_id=campaign_id))
        return tuple(
            to_keyword(row, account_id=self._account_id, campaign_id=campaign_id)
            for row in rows
        )

    def add_keywords(
        self, campaign_id: str, keywords: Sequence[KeywordSpec]
    ) -> tuple[Keyword, ...]:
        spec_list = list(keywords)
        params: dict[str, Any] = {
            "campaign_id": campaign_id,
            "keywords": [
                {
                    "text": spec.text,
                    "match_type": spec.match_type.value.upper(),
                    **(
                        {"cpc_bid_micros": spec.cpc_bid_micros}
                        if spec.cpc_bid_micros is not None
                        else {}
                    ),
                }
                for spec in spec_list
            ],
        }
        self._run(self._client.add_keywords(params))
        # Phase 1: re-fetch keywords list for the typed return surface.
        # A future refactor can build Keyword instances directly from
        # the mutate response when the legacy mapper exposes a richer
        # add-keyword result shape.
        return self.list_keywords(campaign_id)

    def set_keyword_status(
        self, campaign_id: str, keyword_id: str, status: KeywordStatus
    ) -> Keyword:
        params: dict[str, Any] = {
            "campaign_id": campaign_id,
            "criterion_id": keyword_id,
        }
        if status is KeywordStatus.REMOVED:
            self._run(self._client.remove_keyword(params))
        elif status is KeywordStatus.PAUSED:
            self._run(self._client.pause_keyword(params))
        else:
            raise UnsupportedOperation(
                "set_keyword_status: ENABLED transition is not supported by the "
                "Google Ads adapter in Phase 1 (no enable_keyword counterpart)."
            )
        keyword = self._find_keyword(campaign_id, keyword_id)
        if keyword is None:
            raise KeyError(keyword_id)
        return keyword

    def search_terms(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[SearchTerm, ...]:
        period = f"BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'"
        rows = self._run(
            self._client.get_search_terms_report(campaign_id=campaign_id, period=period)
        )
        return tuple(to_search_term(row, campaign_id=campaign_id) for row in rows)

    # ------------------------------------------------------------------
    # ExtensionProvider
    # ------------------------------------------------------------------

    def list_extensions(
        self, campaign_id: str, kind: ExtensionKind
    ) -> tuple[Extension, ...]:
        rows = self._fetch_extension_rows(campaign_id, kind)
        return tuple(
            to_extension(row, account_id=self._account_id, kind=kind) for row in rows
        )

    def add_extension(
        self,
        campaign_id: str,
        kind: ExtensionKind,
        request: ExtensionRequest,
    ) -> Extension:
        params: dict[str, Any] = {
            "campaign_id": campaign_id,
            "text": request.text,
        }
        if request.url is not None:
            params["url"] = request.url
        if request.description1 is not None:
            params["description1"] = request.description1
        if request.description2 is not None:
            params["description2"] = request.description2

        if kind is ExtensionKind.SITELINK:
            created = self._run(self._client.create_sitelink(params))
        elif kind is ExtensionKind.CALLOUT:
            created = self._run(self._client.create_callout(params))
        elif kind is ExtensionKind.CONVERSION:
            params.setdefault("name", request.text)
            created = self._run(self._client.create_conversion_action(params))
        else:  # pragma: no cover — exhaustive on ExtensionKind enum
            raise UnsupportedOperation(f"unsupported extension kind: {kind!r}")

        new_id = self._extract_new_id(created, key="id")
        for ext in self.list_extensions(campaign_id, kind):
            if ext.id == new_id:
                return ext
        # Some legacy mutate responses do not surface the new id — fall
        # back to the most recent entry of the same kind.
        listing = self.list_extensions(campaign_id, kind)
        if listing:
            return listing[-1]
        raise KeyError(new_id)

    def set_extension_status(
        self,
        campaign_id: str,
        extension_id: str,
        status: ExtensionStatus,
    ) -> Extension:
        if status is not ExtensionStatus.REMOVED:
            raise UnsupportedOperation(
                f"set_extension_status: {status.value} transition is not supported "
                "by the Google Ads adapter in Phase 1 (extension mixins expose "
                "remove-only mutations)."
            )

        resolved_kind = self._resolve_extension_kind(campaign_id, extension_id)
        params: dict[str, Any] = {
            "campaign_id": campaign_id,
            "extension_id": extension_id,
        }
        if resolved_kind is ExtensionKind.SITELINK:
            self._run(self._client.remove_sitelink(params))
        elif resolved_kind is ExtensionKind.CALLOUT:
            self._run(self._client.remove_callout(params))
        elif resolved_kind is ExtensionKind.CONVERSION:
            self._run(self._client.remove_conversion_action(params))
        else:  # pragma: no cover — _resolve_extension_kind exhausts enum
            raise KeyError(extension_id)

        # Return a synthesized post-remove dataclass — the entity is
        # gone, so a fresh listing won't contain it.
        return Extension(
            id=extension_id,
            account_id=self._account_id,
            kind=resolved_kind,
            status=ExtensionStatus.REMOVED,
            text="",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_extension_rows(
        self, campaign_id: str, kind: ExtensionKind
    ) -> list[dict[str, Any]]:
        if kind is ExtensionKind.SITELINK:
            return list(self._run(self._client.list_sitelinks(campaign_id)))
        if kind is ExtensionKind.CALLOUT:
            return list(self._run(self._client.list_callouts(campaign_id)))
        if kind is ExtensionKind.CONVERSION:
            return list(self._run(self._client.list_conversion_actions()))
        raise UnsupportedOperation(f"unsupported extension kind: {kind!r}")

    def _resolve_extension_kind(
        self, campaign_id: str, extension_id: str
    ) -> ExtensionKind:
        """Find which extension kind ``extension_id`` belongs to.

        Phase 1 cost: up to three list-style calls. The caller already
        knows the campaign scope, so the search is bounded.
        """
        for kind in (
            ExtensionKind.SITELINK,
            ExtensionKind.CALLOUT,
            ExtensionKind.CONVERSION,
        ):
            for row in self._fetch_extension_rows(campaign_id, kind):
                if str(row.get("id")) == extension_id:
                    return kind
        raise KeyError(extension_id)

    def _find_keyword(self, campaign_id: str, keyword_id: str) -> Keyword | None:
        for kw in self.list_keywords(campaign_id):
            if kw.id == keyword_id:
                return kw
        return None

    def _resolve_ad_group_id(self, campaign_id: str, ad_id: str) -> str:
        """Look up the ``ad_group_id`` of ``ad_id`` from the listing.

        Phase 1 cost: one ``list_ads`` call per ``set_ad_status``. The
        underlying mutate API needs the parent ad-group resource and the
        protocol surface does not carry it.
        """
        rows = self._run(self._client.list_ads())
        for row in rows:
            if str(row.get("id")) == ad_id:
                resolved = row.get("ad_group_id")
                if resolved is not None:
                    return str(resolved)
        raise KeyError(ad_id)

    @staticmethod
    def _extract_new_id(response: dict[str, Any], *, key: str) -> str:
        """Extract a new entity id from a mutate response.

        Prefers an explicit ``key`` (e.g. ``"campaign_id"`` / ``"ad_id"``
        / ``"id"``), falling back to parsing ``resource_name`` so legacy
        mutate responses still work.
        """
        explicit = response.get(key)
        if explicit is not None:
            return str(explicit)
        resource_name = response.get("resource_name")
        if isinstance(resource_name, str) and "/" in resource_name:
            return resource_name.rsplit("/", maxsplit=1)[-1]
        raise KeyError(f"mutate response missing {key!r}: {response!r}")


__all__ = ["GoogleAdsAdapter"]
