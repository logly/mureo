"""``CampaignProvider`` Protocol — campaigns, ads, and daily reports.

The runtime-checkable Protocol every adapter that supports campaign /
ad / daily-report operations must satisfy. Method signatures only;
implementations live in adapters (P1-09/10) and third-party plugins.

Capability gate
---------------
Implementing this Protocol does NOT automatically grant capabilities.
The provider's ``capabilities`` frozenset must explicitly include the
relevant ``Capability`` members for any given method to be callable:

==============================  =================================
Method                          Required capability
==============================  =================================
``list_campaigns`` /            ``READ_CAMPAIGNS``
``get_campaign``
``create_campaign`` /           ``WRITE_BUDGET`` (for budget) +
``update_campaign``             ``WRITE_CAMPAIGN_STATUS``
``list_ads`` / ``get_ad``       ``READ_CAMPAIGNS``
``create_ad`` / ``update_ad``   ``WRITE_CREATIVE``
``set_ad_status``               ``WRITE_CAMPAIGN_STATUS``
``daily_report``                ``READ_PERFORMANCE``
==============================  =================================

Delete-via-status convention
----------------------------
There is no ``delete_ad`` method. Per the Capability ABI rule
("Deletion operations are folded into write capabilities"), the
canonical delete signal is
``set_ad_status(campaign_id, ad_id, AdStatus.REMOVED)``. Adapters
translate ``REMOVED`` to a platform-native delete call.
"""

# ruff: noqa: TC001, TC003
# Model + stdlib imports must stay at module top-level (NOT under
# ``TYPE_CHECKING``) so ``typing.get_type_hints(Protocol.method)`` can
# resolve them at test/registry introspection time on Python 3.10.
from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from mureo.core.providers.base import BaseProvider
from mureo.core.providers.models import (
    Ad,
    AdStatus,
    Campaign,
    CampaignFilters,
    CreateAdRequest,
    CreateCampaignRequest,
    DailyReportRow,
    UpdateAdRequest,
    UpdateCampaignRequest,
)


@runtime_checkable
class CampaignProvider(BaseProvider, Protocol):
    """Structural contract for campaign / ad / daily-report operations.

    See the module docstring for the capability gate map and the
    delete-via-status convention.
    """

    def list_campaigns(
        self, filters: CampaignFilters | None = None
    ) -> tuple[Campaign, ...]:
        """Return campaigns, optionally narrowed by ``filters``."""
        ...

    def get_campaign(self, campaign_id: str) -> Campaign:
        """Return a single campaign by id."""
        ...

    def create_campaign(self, request: CreateCampaignRequest) -> Campaign:
        """Create a new campaign from ``request`` and return it."""
        ...

    def update_campaign(
        self, campaign_id: str, request: UpdateCampaignRequest
    ) -> Campaign:
        """Apply the partial ``request`` to ``campaign_id`` and return the
        updated campaign.
        """
        ...

    def list_ads(self, campaign_id: str) -> tuple[Ad, ...]:
        """Return all ads under ``campaign_id``."""
        ...

    def get_ad(self, campaign_id: str, ad_id: str) -> Ad:
        """Return a single ad scoped to ``campaign_id``."""
        ...

    def create_ad(self, campaign_id: str, request: CreateAdRequest) -> Ad:
        """Create a new ad under ``campaign_id`` and return it."""
        ...

    def update_ad(self, campaign_id: str, ad_id: str, request: UpdateAdRequest) -> Ad:
        """Apply the partial ``request`` to ``ad_id`` and return the
        updated ad.
        """
        ...

    def set_ad_status(self, campaign_id: str, ad_id: str, status: AdStatus) -> Ad:
        """Set the status of ``ad_id``; use ``AdStatus.REMOVED`` to
        delete (delete-via-status convention).
        """
        ...

    def daily_report(
        self, campaign_id: str, start_date: date, end_date: date
    ) -> tuple[DailyReportRow, ...]:
        """Return day-grain performance rows for ``campaign_id`` over the
        inclusive ``[start_date, end_date]`` window.
        """
        ...


__all__ = ["CampaignProvider"]
