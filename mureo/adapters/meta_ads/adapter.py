"""``MetaAdsAdapter`` — Protocol-conformant wrapper over ``MetaAdsApiClient``.

The adapter implements two runtime-checkable Protocols
(:class:`CampaignProvider`, :class:`AudienceProvider`) by delegating
each Phase 1 method to the existing :class:`MetaAdsApiClient`.
:class:`KeywordProvider` and :class:`ExtensionProvider` are deliberately
NOT implemented — Meta has no keyword targeting and no
sitelink / callout / conversion-extension surface.

Sync ↔ async bridge
-------------------
The Protocols are synchronous; the underlying client methods are
``async``. Each Protocol method calls ``asyncio.run`` on the relevant
coroutine. If a caller is already inside a running event loop,
``asyncio.run`` itself raises :class:`RuntimeError` — this is exactly
the documented Phase 1 contract.

AdSet flattening
----------------
Meta's hierarchy is Campaign → AdSet → Ad; the Protocol is Campaign →
Ad direct. Phase 1 hides the AdSet level inside the adapter:
``list_ads(campaign_id)`` makes an N+1 fan-out (one ``list_ad_sets`` +
one ``list_ads`` per ad set). ``create_ad`` interprets
``request.ad_group_id`` as the ``ad_set_id`` (caller responsibility).
``request.headlines[0]`` is the pre-built creative_id (Phase 1
overload; rejected with :class:`UnsupportedOperation` for any other
``headlines`` length).

Module foundation rule
----------------------
Imports are restricted to stdlib, ``mureo.core.providers.*``,
``mureo.meta_ads.client`` (only the public :class:`MetaAdsApiClient`),
and the intra-package ``mappers`` / ``errors`` modules. The AST scan
in ``tests/adapters/meta_ads/test_imports.py`` enforces this allowlist.
"""

# ruff: noqa: TC003
# ``date`` must stay at module top-level so ``typing.get_type_hints()``
# can resolve method annotations (Protocol structural checks).
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from datetime import date
from typing import Any, TypeVar

from mureo.adapters.meta_ads.errors import UnsupportedOperation
from mureo.adapters.meta_ads.mappers import (
    to_ad,
    to_audience,
    to_campaign,
    to_campaigns,
    to_daily_report_row,
)
from mureo.core.providers.capabilities import Capability
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Audience,
    AudienceStatus,
    Campaign,
    CampaignFilters,
    CampaignStatus,
    CreateAdRequest,
    CreateAudienceRequest,
    CreateCampaignRequest,
    DailyReportRow,
    UpdateAdRequest,
    UpdateCampaignRequest,
)
from mureo.meta_ads.client import MetaAdsApiClient

_T = TypeVar("_T")


logger = logging.getLogger(__name__)


# Phase 1: Meta campaign creation requires an objective; we hardcode
# the most general traffic objective. Future iteration may surface this
# on ``CreateCampaignRequest`` (CTO Open Question #2; deferred).
_DEFAULT_OBJECTIVE: str = "OUTCOME_TRAFFIC"

# Phase 1 lookalike defaults — JP-only, 1% audience similarity ratio.
# A future iteration may surface country / ratio on
# ``CreateAudienceRequest`` (CTO Open Question #4; deferred).
_LOOKALIKE_COUNTRY: str = "JP"
_LOOKALIKE_RATIO: float = 0.01


# Adapter-internal write-direction mapping (canonical enum → Meta wire).
# The read-direction inverse lives in ``mappers.py``.
_CAMPAIGN_STATUS_TO_WIRE: dict[CampaignStatus, str] = {
    CampaignStatus.ENABLED: "ACTIVE",
    CampaignStatus.PAUSED: "PAUSED",
    CampaignStatus.REMOVED: "DELETED",
}


def _validate_campaign_id(value: str) -> str:
    """Return ``value`` if it is a bare digit string, else raise ``ValueError``.

    Meta node IDs are integers under the hood; the digits-only check
    blocks query-parameter injection (mirror of P1-09's GAQL safety).
    """
    if not isinstance(value, str) or not value or not value.isdigit():
        raise ValueError(
            f"invalid campaign_id: {value!r} (must be digits-only for the "
            "Meta insights endpoint)"
        )
    return value


class MetaAdsAdapter:
    """Adapter that exposes :class:`MetaAdsApiClient` as Phase 1 Protocols.

    Implements :class:`CampaignProvider` + :class:`AudienceProvider`.
    Does NOT implement :class:`KeywordProvider` (no Meta keyword surface)
    or :class:`ExtensionProvider` (no Meta sitelink/callout/conversion-
    extension surface). BaseProvider attributes are class attributes so
    the registry can introspect them without instantiation.
    """

    name: str = "meta_ads"
    display_name: str = "Meta Ads"
    capabilities: frozenset[Capability] = frozenset(
        {
            Capability.READ_CAMPAIGNS,
            Capability.READ_PERFORMANCE,
            Capability.READ_AUDIENCES,
            Capability.WRITE_BUDGET,
            Capability.WRITE_CREATIVE,
            Capability.WRITE_CAMPAIGN_STATUS,
            Capability.WRITE_AUDIENCES,
        }
    )

    def __init__(self, client: MetaAdsApiClient) -> None:
        if not isinstance(client, MetaAdsApiClient):
            raise TypeError(
                f"MetaAdsAdapter requires a MetaAdsApiClient instance, "
                f"got {type(client).__name__}"
            )
        self._client: MetaAdsApiClient = client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _account_id(self) -> str:
        # CTO-approved single private-attribute read; tracked for a
        # follow-up rename of ``MetaAdsApiClient._ad_account_id`` →
        # public.
        return self._client._ad_account_id  # noqa: SLF001

    @staticmethod
    def _run(coro: Awaitable[_T]) -> _T:
        """Run ``coro`` to completion on a fresh event loop.

        ``asyncio.run`` raises :class:`RuntimeError` when called from
        inside a running loop — that is the documented Phase 1 behaviour
        for async callers and is allowed to propagate.
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
        Meta wire-string (e.g. ``"ACTIVE"`` / ``"PAUSED"``).
        ``filters.name_contains`` is honored **client-side** after fetch.
        """
        status_filter: str | None = None
        if filters is not None and filters.status is not None:
            status_filter = _CAMPAIGN_STATUS_TO_WIRE[filters.status]
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

        Phase 1 limitations
        -------------------
        * ``request.start_date`` / ``request.end_date`` are NOT wired
          through to Meta's ``start_time`` / ``stop_time`` yet.
          Supplying either field raises :class:`UnsupportedOperation`.
        * ``request.bidding_strategy`` would require an AdSet
          ``bid_strategy`` mapping which is out of scope; supplying it
          raises :class:`UnsupportedOperation`.
        * ``objective`` is hardcoded to ``"OUTCOME_TRAFFIC"`` (CTO
          decision #2; future iteration may surface it on the request).
        """
        self._reject_unsupported_create_fields(request)

        daily_budget_cents = _micros_to_cents(request.daily_budget_micros)
        created = self._run(
            self._client.create_campaign(
                name=request.name,
                objective=_DEFAULT_OBJECTIVE,
                status="PAUSED",
                daily_budget=daily_budget_cents,
            )
        )
        new_campaign_id = self._extract_new_id(created, key="id")
        return self.get_campaign(new_campaign_id)

    @staticmethod
    def _reject_unsupported_create_fields(request: CreateCampaignRequest) -> None:
        """Raise :class:`UnsupportedOperation` for any deferred field."""
        if request.start_date is not None:
            raise UnsupportedOperation(
                "create_campaign: start_date is not wired in Phase 1; "
                "Meta start_time/stop_time mapping deferred."
            )
        if request.end_date is not None:
            raise UnsupportedOperation(
                "create_campaign: end_date is not wired in Phase 1; "
                "Meta start_time/stop_time mapping deferred."
            )
        if request.bidding_strategy is not None:
            raise UnsupportedOperation(
                "create_campaign: bidding_strategy is not wired in Phase 1; "
                "Meta AdSet bid_strategy mapping deferred."
            )

    def update_campaign(
        self, campaign_id: str, request: UpdateCampaignRequest
    ) -> Campaign:
        """Apply the partial ``request`` and return the refreshed campaign.

        Unlike Google Ads, Meta supports ``daily_budget`` mutation on the
        campaign resource directly — the adapter converts micros → cents
        (``micros // 10_000``) at the boundary.

        ``status`` transitions are wired through ``update_campaign`` with
        the inverse mapping (ENABLED → ``"ACTIVE"``, PAUSED → ``"PAUSED"``,
        REMOVED → ``"DELETED"``).
        """
        params: dict[str, Any] = {}
        if request.name is not None:
            params["name"] = request.name
        if request.daily_budget_micros is not None:
            params["daily_budget"] = _micros_to_cents(request.daily_budget_micros)
        if request.status is not None:
            params["status"] = _CAMPAIGN_STATUS_TO_WIRE[request.status]
        if request.bidding_strategy is not None:
            raise UnsupportedOperation(
                "update_campaign: bidding_strategy is not wired in Phase 1."
            )

        self._run(self._client.update_campaign(campaign_id, **params))
        return self.get_campaign(campaign_id)

    # ------------------------------------------------------------------
    # CampaignProvider — ads (AdSet hierarchy hidden)
    # ------------------------------------------------------------------

    def list_ads(self, campaign_id: str) -> tuple[Ad, ...]:
        """List every ad under ``campaign_id`` by flattening the AdSet level.

        Phase 1 cost: N+1 calls (one ``list_ad_sets`` + one ``list_ads``
        per ad set). Documented trade-off; a campaign-scoped Meta
        endpoint is not exposed by the current mixin surface.
        """
        ad_sets = self._run(self._client.list_ad_sets(campaign_id))
        all_ads: list[Ad] = []
        for ad_set in ad_sets:
            ad_set_id = str(ad_set["id"])
            rows = self._run(self._client.list_ads(ad_set_id))
            for row in rows:
                all_ads.append(
                    to_ad(row, account_id=self._account_id, campaign_id=campaign_id)
                )
        return tuple(all_ads)

    def get_ad(self, campaign_id: str, ad_id: str) -> Ad:
        """Return a single ad; raise ``KeyError`` on campaign mismatch."""
        raw = self._run(self._client.get_ad(ad_id))
        if raw is None:
            raise KeyError(ad_id)
        if str(raw.get("campaign_id")) != campaign_id:
            raise KeyError(f"ad {ad_id!r} does not belong to campaign {campaign_id!r}")
        return to_ad(raw, account_id=self._account_id, campaign_id=campaign_id)

    def create_ad(self, campaign_id: str, request: CreateAdRequest) -> Ad:
        """Create an ad under ``request.ad_group_id`` (interpreted as ad_set_id).

        Phase 1 overload (CTO decision #3): ``request.headlines[0]`` is
        interpreted as the pre-built ``creative_id``. Any other tuple
        length raises :class:`UnsupportedOperation`. ``request.ad_group_id``
        is interpreted as the parent ``ad_set_id``.
        """
        if len(request.headlines) != 1:
            raise UnsupportedOperation(
                f"create_ad: Phase 1 expects exactly one element in "
                f"headlines (interpreted as creative_id); got "
                f"{len(request.headlines)} element(s). Pre-build the "
                "creative with creatives.create and pass its id as the "
                "sole headline."
            )
        creative_id = request.headlines[0]
        ad_set_id = request.ad_group_id

        created = self._run(
            self._client.create_ad(
                ad_set_id=ad_set_id,
                name=f"ad-{creative_id}",
                creative_id=creative_id,
            )
        )
        new_ad_id = self._extract_new_id(created, key="id")
        return self.get_ad(campaign_id, new_ad_id)

    def update_ad(self, campaign_id: str, ad_id: str, request: UpdateAdRequest) -> Ad:
        """Apply the partial ``request`` to an existing ad.

        Phase 1 limitation: Meta cannot mutate a live ad's creative
        without recreating the ad. Supplying ANY creative field
        (``headlines`` / ``descriptions`` / ``final_urls`` / ``path1`` /
        ``path2``) raises :class:`UnsupportedOperation`. Status changes
        flow through :meth:`set_ad_status`.
        """
        self._reject_unsupported_update_fields(request)
        # No mutable fields left in Phase 1 — return the current state.
        return self.get_ad(campaign_id, ad_id)

    @staticmethod
    def _reject_unsupported_update_fields(request: UpdateAdRequest) -> None:
        """Raise :class:`UnsupportedOperation` for any deferred field."""
        if request.headlines is not None:
            raise UnsupportedOperation(
                "update_ad: headlines mutation is not supported by Meta "
                "(creative is immutable post-creation; recreate the ad)."
            )
        if request.descriptions is not None:
            raise UnsupportedOperation(
                "update_ad: descriptions mutation is not supported by Meta."
            )
        if request.final_urls is not None:
            raise UnsupportedOperation(
                "update_ad: final_urls mutation is not supported by Meta."
            )
        if request.path1 is not None or request.path2 is not None:
            raise UnsupportedOperation(
                "update_ad: path1/path2 are Google Ads concepts; Meta has "
                "no counterpart."
            )

    def set_ad_status(self, campaign_id: str, ad_id: str, status: AdStatus) -> Ad:
        """Route the status transition to the right Meta mutate verb.

        - ``PAUSED`` → :meth:`MetaAdsApiClient.pause_ad`
        - ``ENABLED`` → :meth:`MetaAdsApiClient.enable_ad`
        - ``REMOVED`` → :meth:`MetaAdsApiClient.update_ad(status="DELETED")`
        """
        if status is AdStatus.PAUSED:
            self._run(self._client.pause_ad(ad_id))
        elif status is AdStatus.ENABLED:
            self._run(self._client.enable_ad(ad_id))
        elif status is AdStatus.REMOVED:
            self._run(self._client.update_ad(ad_id, status="DELETED"))
        else:  # pragma: no cover — AdStatus is exhaustive
            raise UnsupportedOperation(f"set_ad_status: unsupported status {status!r}")
        return self.get_ad(campaign_id, ad_id)

    # ------------------------------------------------------------------
    # CampaignProvider — daily report
    # ------------------------------------------------------------------

    def daily_report(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[DailyReportRow, ...]:
        """Return day-grain rows via ``client.insights_time_range``.

        ``campaign_id`` is digit-validated before being interpolated
        into the Meta insights URL path — mirrors P1-09's GAQL safety
        check. ``start_date`` / ``end_date`` are ISO-formatted via
        ``date.isoformat()`` (locked by Python to ``YYYY-MM-DD``).
        """
        validated_id = _validate_campaign_id(campaign_id)
        rows = self._run(
            self._client.insights_time_range(
                validated_id,
                since=start_date.isoformat(),
                until=end_date.isoformat(),
                time_increment=1,
                level="campaign",
            )
        )
        return tuple(to_daily_report_row(row) for row in rows)

    # ------------------------------------------------------------------
    # AudienceProvider
    # ------------------------------------------------------------------

    def list_audiences(self) -> tuple[Audience, ...]:
        rows = self._run(self._client.list_custom_audiences())
        return tuple(to_audience(row, account_id=self._account_id) for row in rows)

    def get_audience(self, audience_id: str) -> Audience:
        raw = self._run(self._client.get_custom_audience(audience_id))
        if raw is None:
            raise KeyError(audience_id)
        return to_audience(raw, account_id=self._account_id)

    def create_audience(self, request: CreateAudienceRequest) -> Audience:
        """Create a Custom or Lookalike audience.

        ``request.seed_audience_id`` is the branching signal:
        - ``None`` → Custom audience (``client.create_custom_audience``).
        - present → Lookalike with Phase 1 defaults ``country="JP"``,
          ``ratio=0.01`` (CTO decision #4).
        """
        if request.seed_audience_id is None:
            created = self._run(
                self._client.create_custom_audience(
                    request.name,
                    "CUSTOM",
                    description=request.description,
                )
            )
        else:
            created = self._run(
                self._client.create_lookalike_audience(
                    request.name,
                    request.seed_audience_id,
                    _LOOKALIKE_COUNTRY,
                    _LOOKALIKE_RATIO,
                )
            )
        new_id = self._extract_new_id(created, key="id")
        return self.get_audience(new_id)

    def set_audience_status(self, audience_id: str, status: AudienceStatus) -> Audience:
        """Route the status transition to the right Meta mutate verb.

        - ``REMOVED`` → :meth:`MetaAdsApiClient.delete_custom_audience`.
        - ``ENABLED`` → :class:`UnsupportedOperation` (Meta has no
          re-enable counterpart for deleted audiences).
        """
        if status is AudienceStatus.REMOVED:
            self._run(self._client.delete_custom_audience(audience_id))
            # The audience is gone — return a synthesized post-delete
            # snapshot rather than a fresh fetch (which would 404).
            return Audience(
                id=audience_id,
                account_id=self._account_id,
                name="",
                status=AudienceStatus.REMOVED,
            )
        raise UnsupportedOperation(
            f"set_audience_status: {status.value} transition is not supported "
            "by Meta in Phase 1 (audience status is derived from "
            "delivery_status, not set directly)."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_new_id(response: dict[str, Any], *, key: str) -> str:
        """Extract a new entity id from a Meta mutate response.

        Meta's mutate endpoints return ``{"id": ...}`` (sometimes with a
        ``success`` flag). The ``key`` arg lets callers pick a specific
        field; ``id`` is the standard fallback.
        """
        explicit = response.get(key)
        if explicit is not None:
            return str(explicit)
        # Fall back to the canonical Meta "id" field if a different key
        # was requested and is absent.
        fallback = response.get("id")
        if fallback is not None:
            return str(fallback)
        raise KeyError(f"mutate response missing {key!r}: {response!r}")


def _micros_to_cents(micros: int) -> int:
    """Convert a micros amount to a Meta cents integer (``micros // 10_000``).

    Negative / zero values are passed through; the caller is responsible
    for surfacing zero-budget semantics to Meta.
    """
    return micros // 10_000


__all__ = ["MetaAdsAdapter"]
