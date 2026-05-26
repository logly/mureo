"""Public-API surface tests for the account-listing helpers.

``list_accessible_accounts`` (Google Ads) and ``list_meta_ad_accounts``
(Meta) were promoted out of :mod:`mureo.auth_setup` into the
platform-specific public modules so configure-wizard tooling and
third-party consumers can build account-picker UIs without reaching
into the wizard's internal module.

These tests pin the public import paths and the backward-compat
aliases so a future refactor can't silently strand callers.

Behavioural correctness is exercised by ``tests/test_auth_setup.py``
(via the legacy import path) and stays the canonical functional
test surface — these tests assert *only* the public-API shape, plus
one regression test for separately-linked-MCC name resolution.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
def test_google_ads_list_accessible_accounts_publicly_exported() -> None:
    """``mureo.google_ads.list_accessible_accounts`` is part of the
    public ``__all__`` and resolves to the canonical implementation
    in :mod:`mureo.google_ads.accounts`.
    """
    import mureo.google_ads
    from mureo.google_ads import list_accessible_accounts
    from mureo.google_ads.accounts import (
        list_accessible_accounts as canonical,
    )

    assert "list_accessible_accounts" in mureo.google_ads.__all__
    assert list_accessible_accounts is canonical


@pytest.mark.unit
def test_meta_ads_list_meta_ad_accounts_publicly_exported() -> None:
    """``mureo.meta_ads.list_meta_ad_accounts`` is part of the public
    ``__all__`` and resolves to the canonical implementation in
    :mod:`mureo.meta_ads.accounts`.
    """
    import mureo.meta_ads
    from mureo.meta_ads import list_meta_ad_accounts
    from mureo.meta_ads.accounts import (
        list_meta_ad_accounts as canonical,
    )

    assert "list_meta_ad_accounts" in mureo.meta_ads.__all__
    assert list_meta_ad_accounts is canonical


@pytest.mark.unit
def test_auth_setup_alias_for_list_accessible_accounts() -> None:
    """The legacy import path ``mureo.auth_setup.list_accessible_accounts``
    keeps working — alias re-export, same callable identity.
    """
    from mureo.auth_setup import list_accessible_accounts as legacy
    from mureo.google_ads.accounts import list_accessible_accounts as canonical

    assert legacy is canonical


@pytest.mark.unit
def test_auth_setup_alias_for_list_meta_ad_accounts() -> None:
    """The legacy import path ``mureo.auth_setup.list_meta_ad_accounts``
    keeps working — alias re-export, same callable identity.
    """
    from mureo.auth_setup import list_meta_ad_accounts as legacy
    from mureo.meta_ads.accounts import list_meta_ad_accounts as canonical

    assert legacy is canonical


@pytest.mark.unit
def test_list_accessible_accounts_signature_is_stable() -> None:
    """Argument shape stays ``(credentials: GoogleAdsCredentials) ->
    list[dict[str, Any]]`` so consumers don't break on the move.
    """
    from mureo.google_ads import list_accessible_accounts

    sig = inspect.signature(list_accessible_accounts)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "credentials"
    assert inspect.iscoroutinefunction(list_accessible_accounts)


@pytest.mark.unit
def test_list_meta_ad_accounts_signature_is_stable() -> None:
    """Argument shape stays ``(access_token: str) -> list[dict[str, Any]]``."""
    from mureo.meta_ads import list_meta_ad_accounts

    sig = inspect.signature(list_meta_ad_accounts)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "access_token"
    assert inspect.iscoroutinefunction(list_meta_ad_accounts)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_resolves_name_for_account_under_separate_mcc() -> None:
    """Each customer's info query uses its own ID as ``login_customer_id``.

    ``listAccessibleCustomers`` can return customers that live outside
    the hierarchy of ``credentials.login_customer_id`` (e.g. another
    MCC the operator has been manager-linked to). Querying those with
    the operator-wide default ``login_customer_id`` returns
    ``PERMISSION_DENIED``, which previously caused them to fall back
    to the raw ID for ``name`` and ``False`` for ``is_manager`` — and
    skipped child traversal entirely.

    The fix builds a fresh client per customer so the info query and
    the child traversal both run against the customer's own MCC
    context.
    """
    from mureo.auth import GoogleAdsCredentials
    from mureo.google_ads import list_accessible_accounts

    mcc_a = "1111111111"
    mcc_b = "2222222222"
    child_of_b = "3333333333"

    creds = GoogleAdsCredentials(
        developer_token="dev-tok",
        client_id="cid",
        client_secret="csec",
        refresh_token="rtok",
        login_customer_id=mcc_a,
    )

    list_customers_response = MagicMock()
    list_customers_response.resource_names = [
        f"customers/{mcc_a}",
        f"customers/{mcc_b}",
    ]

    info_names = {mcc_a: "MCC-A", mcc_b: "MCC-B"}

    def _info_row(customer_id: str) -> MagicMock:
        row = MagicMock()
        row.customer.descriptive_name = info_names[customer_id]
        row.customer.manager = True
        return row

    def _child_row(cid: str, name: str) -> MagicMock:
        row = MagicMock()
        row.customer_client.id = int(cid)
        row.customer_client.descriptive_name = name
        row.customer_client.manager = False
        return row

    constructed_login_cids: list[str | None] = []

    def _build_mock_client(login_cid: str | None) -> MagicMock:
        client = MagicMock()
        customer_service = MagicMock()
        customer_service.list_accessible_customers.return_value = (
            list_customers_response
        )
        ga_service = MagicMock()

        def _search(*, customer_id: str, query: str) -> list[MagicMock]:
            # Real Google Ads API rejects a query when ``customer_id``
            # is not reachable via the request's ``login_customer_id``.
            if customer_id != login_cid:
                raise RuntimeError(
                    f"PERMISSION_DENIED: customer {customer_id} not "
                    f"reachable via login_customer_id={login_cid}"
                )
            if "customer_client" in query:
                if customer_id == mcc_b:
                    return [_child_row(child_of_b, "child-of-B")]
                return []
            return [_info_row(customer_id)]

        ga_service.search.side_effect = _search

        def _get_service(name: str) -> MagicMock:
            if name == "CustomerService":
                return customer_service
            return ga_service

        client.get_service.side_effect = _get_service
        return client

    def _client_factory(**kwargs: Any) -> MagicMock:
        login_cid = kwargs.get("login_customer_id")
        constructed_login_cids.append(login_cid)
        return _build_mock_client(login_cid)

    with patch(
        "google.ads.googleads.client.GoogleAdsClient",
        side_effect=_client_factory,
    ):
        accounts = await list_accessible_accounts(creds)

    by_id = {a["id"]: a for a in accounts}

    assert by_id[mcc_a]["name"] == "MCC-A"
    assert by_id[mcc_a]["is_manager"] is True
    assert by_id[mcc_b]["name"] == "MCC-B"
    assert by_id[mcc_b]["is_manager"] is True
    assert child_of_b in by_id, (
        "child traversal must run for an MCC reached outside the "
        "operator's default login_customer_id hierarchy"
    )
    assert by_id[child_of_b]["parent_id"] == mcc_b

    assert mcc_b in constructed_login_cids, (
        "a client must be constructed with the separately-linked MCC "
        "as its own login_customer_id"
    )
