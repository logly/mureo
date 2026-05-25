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
test surface — these tests assert *only* the public-API shape.
"""

from __future__ import annotations

import inspect

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
