"""Canonical plugin platform-key helpers (Issue #481).

One key per plugin platform — ``plugin:<distribution>`` — shared by the
STATE.json write path, the ``action_log`` promoter, the reporting
dashboard's label resolver, and ``mureo_analytics_modules_list``. These
tests pin the shape so a second convention cannot creep back in.
"""

from __future__ import annotations

import pytest

from mureo.core.platform_keys import (
    PLUGIN_PLATFORM_PREFIX,
    is_plugin_platform_key,
    plugin_distribution,
    plugin_platform_key,
)


@pytest.mark.unit
def test_prefix_is_the_documented_literal() -> None:
    assert PLUGIN_PLATFORM_PREFIX == "plugin:"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("distribution", "expected"),
    [
        ("mureo-logly-bridge", "plugin:mureo-logly-bridge"),
        ("acme-ads", "plugin:acme-ads"),
        ("unknown", "plugin:unknown"),
    ],
)
def test_plugin_platform_key_prefixes_the_distribution(
    distribution: str, expected: str
) -> None:
    assert plugin_platform_key(distribution) == expected


@pytest.mark.unit
def test_plugin_platform_key_is_idempotent() -> None:
    """An already-canonical key passed back in is not double-prefixed."""
    once = plugin_platform_key("acme-ads")
    assert plugin_platform_key(once) == once


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plugin:mureo-logly-bridge", True),
        ("plugin:acme-ads", True),
        ("google_ads", False),
        ("meta_ads", False),
        ("tiktok_ads", False),
        ("acme_ads_platform", False),
        ("", False),
        # A bare prefix carries no distribution — not a usable plugin key.
        ("plugin:", False),
    ],
)
def test_is_plugin_platform_key(key: str, expected: bool) -> None:
    assert is_plugin_platform_key(key) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plugin:mureo-logly-bridge", "mureo-logly-bridge"),
        ("plugin:acme-ads", "acme-ads"),
        # Non-plugin keys carry no distribution.
        ("google_ads", ""),
        ("plugin:", ""),
        ("", ""),
    ],
)
def test_plugin_distribution_strips_the_prefix(key: str, expected: str) -> None:
    assert plugin_distribution(key) == expected


@pytest.mark.unit
def test_colon_bearing_remainder_is_taken_verbatim() -> None:
    """Only the FIRST ``plugin:`` is the prefix; the rest is the distribution.

    A PyPI distribution name is limited to ASCII letters, digits, ``-``,
    ``_`` and ``.`` (PEP 503 / PEP 508), so it can never contain ``:`` —
    ``plugin:a:b`` is not a key mureo can produce. Pinning the behaviour
    anyway so a future change cannot quietly start splitting on the last
    colon or rejecting the key outright.
    """
    assert plugin_distribution("plugin:a:b") == "a:b"
    assert is_plugin_platform_key("plugin:a:b") is True


@pytest.mark.unit
def test_round_trip_key_to_distribution() -> None:
    for dist in ("mureo-logly-bridge", "acme-ads", "a"):
        assert plugin_distribution(plugin_platform_key(dist)) == dist
