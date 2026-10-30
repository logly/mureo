"""``serves_platform`` — a plugin provider standing in for a built-in platform.

A provider that serves Google Ads, Meta Ads or Search Console
through its own credentials section declares which one on the class. The
defensive reader mirrors ``get_account_oauth_config``: absent attribute →
``None``, a mis-typed attribute → ``TypeError``, and a value outside the
known platforms → ``ValueError``, so a typo fails loudly at the boundary
instead of silently leaving the platform row "not configured".
"""

from __future__ import annotations

import pytest

from mureo.core.providers import SERVED_PLATFORMS, get_serves_platform


class _PlainProvider:
    name = "demo_ads"


def _provider(value: object) -> object:
    class _Served:
        name = "google_ads_vendor"
        serves_platform = value

    return _Served()


@pytest.mark.unit
def test_absent_attribute_returns_none() -> None:
    assert get_serves_platform(_PlainProvider()) is None


@pytest.mark.unit
@pytest.mark.parametrize("platform", ["google_ads", "meta_ads", "search_console"])
def test_each_served_platform_is_returned(platform: str) -> None:
    assert get_serves_platform(_provider(platform)) == platform


@pytest.mark.unit
def test_served_platforms_are_the_three_builtins() -> None:
    assert frozenset({"google_ads", "meta_ads", "search_console"}) == SERVED_PLATFORMS


@pytest.mark.unit
def test_non_str_raises_type_error_naming_the_provider() -> None:
    with pytest.raises(TypeError, match="google_ads_vendor"):
        get_serves_platform(_provider(["google_ads"]))


@pytest.mark.unit
@pytest.mark.parametrize("value", ["ga4", "tiktok_ads"])
def test_unknown_platform_raises_value_error_naming_the_provider(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="google_ads_vendor") as excinfo:
        get_serves_platform(_provider(value))
    assert value in str(excinfo.value)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["amazon_ads"])
def test_platform_without_a_wizard_choice_is_rejected(value: str) -> None:
    """Amazon Ads is a built-in platform, but the Setup wizard offers no
    connection choice for it, so accepting it would promise a choice the
    configure UI never shows."""
    with pytest.raises(ValueError, match="google_ads_vendor") as excinfo:
        get_serves_platform(_provider(value))
    assert value in str(excinfo.value)


@pytest.mark.unit
def test_class_itself_is_read_like_an_instance() -> None:
    class _Served:
        name = "meta_ads_vendor"
        serves_platform = "meta_ads"

    assert get_serves_platform(_Served) == "meta_ads"
