"""Accessible-account discovery for the Google Ads API.

Public surface for tooling that needs to enumerate the customer
accounts a given set of Google Ads credentials can reach — both
directly accessible accounts and child accounts reached via MCC
(Manager Customer Account) traversal.

The function was previously defined inside
:mod:`mureo.auth_setup` for the interactive OAuth wizard's account-
picker step. Promoting it to ``mureo.google_ads.accounts`` exposes
the same logic as a stable public API so configure-UI consumers
(in-tree and third-party) can build account pickers without reaching
into the wizard's internal module.

The original import path ``mureo.auth_setup.list_accessible_accounts``
remains valid via a thin re-export there — existing callers do not
need to change.

The returned shape stays ``list[dict[str, Any]]`` (the same dict
shape the auth-setup wizard has always produced). A future minor
release MAY introduce a frozen-dataclass parallel return type; the
dict shape will remain supported for at least one minor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mureo.auth import GoogleAdsCredentials

logger = logging.getLogger(__name__)


async def list_accessible_accounts(
    credentials: GoogleAdsCredentials,
) -> list[dict[str, Any]]:
    """Retrieve the list of Google Ads accounts the credentials can reach.

    Enumerates all accounts the user can operate on:

    1. Directly accessible accounts (from ``listAccessibleCustomers``).
    2. Child accounts under any accessible Manager (MCC) account,
       traversed via the ``customer_client`` table.

    This handles the common case where a user has been granted access
    only to an MCC but needs to operate on its child accounts.

    Args:
        credentials: Google Ads credentials (developer token + OAuth
            client + refresh token). ``credentials.login_customer_id``
            is used as the operator-wide MCC for the initial
            ``listAccessibleCustomers`` call; per-child traversal uses
            each MCC as its own ``login_customer_id``.

    Returns:
        List of account info dicts. Each dict contains:

        - ``id``: Customer ID (10-digit string).
        - ``name``: Descriptive name (falls back to the ID when the
          API does not surface one).
        - ``is_manager``: ``True`` when this is an MCC account.
        - ``parent_id``: Parent MCC ID for child accounts reached via
          MCC traversal. ``None`` for directly accessible accounts.
          When set, it is the value to pass as ``login_customer_id``
          when operating on the child.
    """
    from google.ads.googleads.client import GoogleAdsClient
    from google.oauth2.credentials import Credentials as OAuthCredentials

    oauth_creds = OAuthCredentials(  # type: ignore[no-untyped-call]
        token=None,
        refresh_token=credentials.refresh_token,
        client_id=credentials.client_id,
        client_secret=credentials.client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )

    def _make_client(login_cid: str | None = None) -> Any:
        return GoogleAdsClient(
            credentials=oauth_creds,
            developer_token=credentials.developer_token,
            login_customer_id=login_cid,
        )

    # Step 1: Get directly accessible accounts
    base_client = _make_client(login_cid=credentials.login_customer_id)
    try:
        customer_service = base_client.get_service("CustomerService")
        response = customer_service.list_accessible_customers()
    except Exception:
        logger.warning("Failed to retrieve account list", exc_info=True)
        return []

    accounts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add(
        customer_id: str,
        name: str,
        is_manager: bool = False,
        parent_id: str | None = None,
    ) -> None:
        if customer_id in seen_ids:
            return
        accounts.append(
            {
                "id": customer_id,
                "name": name,
                "is_manager": is_manager,
                "parent_id": parent_id,
            }
        )
        seen_ids.add(customer_id)

    # Step 2: For each directly accessible account, get info and traverse
    # children if it's an MCC
    base_ga_service = base_client.get_service("GoogleAdsService")
    for resource_name in response.resource_names:
        customer_id = resource_name.split("/")[-1]

        name = customer_id
        is_manager = False
        try:
            query = (
                "SELECT customer.descriptive_name, customer.manager "
                "FROM customer LIMIT 1"
            )
            rows = base_ga_service.search(customer_id=customer_id, query=query)
            for row in rows:
                name = row.customer.descriptive_name or customer_id
                is_manager = bool(row.customer.manager)
                break
        except Exception:
            logger.debug(
                "Failed to retrieve account info: %s", customer_id, exc_info=True
            )

        _add(customer_id, name, is_manager=is_manager, parent_id=None)

        if not is_manager:
            continue

        # Step 3: Traverse child accounts under this MCC.
        # Requires login_customer_id set to the MCC.
        try:
            mcc_client = _make_client(login_cid=customer_id)
            mcc_ga_service = mcc_client.get_service("GoogleAdsService")
            child_query = (
                "SELECT "
                "  customer_client.id, "
                "  customer_client.descriptive_name, "
                "  customer_client.manager, "
                "  customer_client.level, "
                "  customer_client.status "
                "FROM customer_client "
                "WHERE customer_client.status = 'ENABLED' "
                "AND customer_client.level > 0"
            )
            child_rows = mcc_ga_service.search(
                customer_id=customer_id, query=child_query
            )
            for child_row in child_rows:
                child = child_row.customer_client
                child_id = str(child.id)
                child_name = child.descriptive_name or child_id
                _add(
                    child_id,
                    child_name,
                    is_manager=bool(child.manager),
                    parent_id=customer_id,
                )
        except Exception:
            logger.warning(
                "Failed to retrieve child accounts for MCC %s",
                customer_id,
                exc_info=True,
            )

    return accounts


__all__ = ["list_accessible_accounts"]
