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
dict shape will remain supported for at least one minor. A listing
that fails outright raises :class:`GoogleAdsAccountListError` rather
than returning an empty list (#746).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mureo.google_ads._gaql_validator import validate_static_query

if TYPE_CHECKING:
    from collections.abc import Callable

    from mureo.auth import GoogleAdsCredentials

logger = logging.getLogger(__name__)


class GoogleAdsAccountListError(RuntimeError):
    """The account listing failed — no roster could be built (#746).

    Distinct from an empty list, which is the legitimate "these
    credentials reach no accounts" answer. Collapsing the two meant an
    expired refresh token, a rejected developer token and a brand-new
    Google account with nothing in it were all reported as "no accounts",
    and every caller carried on as if that were a fact.

    The message names the failing exception's CLASS only. See the raise
    site for why its text must not travel with it.
    """


def _enum_name(value: Any) -> str | None:
    """Render a proto-plus enum value as its name string.

    ``customer.status`` and ``customer_client.status`` come back as enum
    wrappers whose ``.name`` is the GAQL string (``"ENABLED"``,
    ``"SUSPENDED"``, ``"CANCELED"``, …), which is the form worth showing
    an operator — the raw value is an integer. Anything without a string
    ``.name`` falls back to ``str()``, and an unset field reads as
    ``None`` rather than the misleading ``"0"``.
    """

    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    if value:
        return str(value)
    return None


def _describe_customer(
    ga_service: Any, customer_id: str
) -> tuple[str | None, bool, str | None]:
    """Return ``(name, is_manager, status)`` for one accessible customer.

    Degrades rather than fails: a customer whose info query the API
    refuses still belongs in the roster — the caller already knows its id
    — it simply has no metadata to show, so it reads
    ``(None, False, None)``. ``name`` is ``None`` (not the id) when the
    account has no descriptive name, so a consumer can tell an unnamed
    account from one named after its own id.
    """

    try:
        query = validate_static_query(
            "SELECT customer.descriptive_name, customer.manager, "
            "customer.status FROM customer LIMIT 1"
        )
        for row in ga_service.search(customer_id=customer_id, query=query):
            return (
                row.customer.descriptive_name or None,
                bool(row.customer.manager),
                _enum_name(row.customer.status),
            )
    except Exception as exc:  # noqa: BLE001
        # Class name only — see the note above list_accessible_customers.
        logger.debug(
            "Failed to retrieve account info: %s (%s)",
            customer_id,
            type(exc).__name__,
        )
    return None, False, None


def _traverse_children(ga_service: Any, mcc_id: str, add: Callable[..., None]) -> None:
    """Hand every enabled child account under ``mcc_id`` to ``add``.

    ``ga_service`` must already be built with ``mcc_id`` as its
    ``login_customer_id``. Degrades rather than fails: an MCC whose
    traversal is refused contributes no children and the walk moves on —
    the manager account itself is already in the roster.
    """

    try:
        child_query = validate_static_query(
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
        for child_row in ga_service.search(customer_id=mcc_id, query=child_query):
            child = child_row.customer_client
            add(
                str(child.id),
                child.descriptive_name or None,
                is_manager=bool(child.manager),
                parent_id=mcc_id,
                level=int(child.level),
                status=_enum_name(child.status),
            )
    except Exception as exc:  # noqa: BLE001
        # Class name only — see the note above list_accessible_customers.
        logger.warning(
            "Failed to retrieve child accounts for MCC %s (%s)",
            mcc_id,
            type(exc).__name__,
        )


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
        List of account info dicts. An empty list means the credentials
        reached the API and it reported no accounts. Each dict contains:

        - ``id``: Customer ID (10-digit string).
        - ``name``: Descriptive name, or ``None`` when the account has
          none (the id is NOT copied in — an unnamed account and one
          named after its own id are different things).
        - ``is_manager``: ``True`` when this is an MCC account.
        - ``parent_id``: Parent MCC ID for child accounts reached via
          MCC traversal. ``None`` for directly accessible accounts.
          When set, it is the value to pass as ``login_customer_id``
          when operating on the child.
        - ``level``: Depth below the MCC the account was reached
          through. ``0`` for a directly accessible account.
        - ``status``: The account status enum's name (``"ENABLED"``,
          ``"SUSPENDED"``, …), or ``None`` when it could not be read.

    Raises:
        GoogleAdsAccountListError: When the listing call itself failed,
            so no roster could be built. Never confuse this with an
            empty list — see the class docstring.
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
    except Exception as exc:  # noqa: BLE001
        # Class name only. GoogleAdsException does not curate its __str__:
        # it never calls super().__init__ with a safe message, so
        # BaseException keeps the raw constructor args and formatting the
        # exception prints the underlying grpc.Call repr — which carries
        # debug_error_string, and with it the request metadata
        # (developer-token, authorization header). A traceback via
        # exc_info=True would put that in the configure log. Callers of this
        # function already log the class only for exactly this reason (see
        # mureo/cli/web_auth.py); doing it there and not here left the leak
        # in place.
        logger.warning("Failed to retrieve account list (%s)", type(exc).__name__)
        # ``from None`` for the same reason the message carries the class
        # name alone: a printed ``__cause__`` would put the whole grpc repr
        # — request metadata included — in front of whoever sees the error.
        raise GoogleAdsAccountListError(
            f"Failed to retrieve account list ({type(exc).__name__})"
        ) from None

    accounts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _add(
        customer_id: str,
        name: str | None,
        is_manager: bool = False,
        parent_id: str | None = None,
        level: int = 0,
        status: str | None = None,
    ) -> None:
        if customer_id in seen_ids:
            return
        accounts.append(
            {
                "id": customer_id,
                "name": name,
                "is_manager": is_manager,
                "parent_id": parent_id,
                "level": level,
                "status": status,
            }
        )
        seen_ids.add(customer_id)

    # Step 2: For each directly accessible account, get info and traverse
    # children if it's an MCC.
    #
    # ``listAccessibleCustomers`` can return customers reachable via a
    # manager-link to an MCC other than ``credentials.login_customer_id``
    # — direct access to those customers requires the request's
    # ``login_customer_id`` header to match their own MCC context, not
    # the operator-wide default. Build a fresh client per customer so
    # both the info query and the child traversal run against the
    # right context; the operator-default ``base_client`` is reserved
    # for the ``listAccessibleCustomers`` call itself.
    for resource_name in response.resource_names:
        customer_id = resource_name.split("/")[-1]

        own_client = _make_client(login_cid=customer_id)
        own_ga_service = own_client.get_service("GoogleAdsService")

        name, is_manager, status = _describe_customer(own_ga_service, customer_id)
        _add(
            customer_id,
            name,
            is_manager=is_manager,
            parent_id=None,
            level=0,
            status=status,
        )

        # Step 3: Traverse child accounts under this MCC. Same client
        # already has ``login_customer_id`` set to the MCC.
        if is_manager:
            _traverse_children(own_ga_service, customer_id, _add)

    return accounts


__all__ = ["GoogleAdsAccountListError", "list_accessible_accounts"]
