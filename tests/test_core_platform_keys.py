"""Canonical plugin platform-key helpers (Issues #481, #537).

One key per plugin **platform** — ``plugin:<distribution>:<provider>`` —
shared by the STATE.json write path, the ``action_log`` promoter, the
reporting dashboard's label resolver, and
``mureo_analytics_modules_list``. The #481 ``plugin:<distribution>``
short form stays valid on read. These tests pin both shapes so a second
convention cannot creep back in.
"""

from __future__ import annotations

import inspect

import pytest

from mureo.core.platform_keys import (
    PLUGIN_PLATFORM_PREFIX,
    PLUGIN_PLATFORM_SEPARATOR,
    is_plugin_platform_key,
    plugin_distribution,
    plugin_platform_key,
    plugin_platform_key_matches,
    plugin_platform_parts,
    plugin_provider,
)


@pytest.mark.unit
def test_prefix_is_the_documented_literal() -> None:
    assert PLUGIN_PLATFORM_PREFIX == "plugin:"


@pytest.mark.unit
def test_separator_is_the_documented_literal() -> None:
    assert PLUGIN_PLATFORM_SEPARATOR == ":"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("distribution", "provider", "expected"),
    [
        (
            "mureo-lineyahoo-bridge",
            "yahoo_ads",
            "plugin:mureo-lineyahoo-bridge:yahoo_ads",
        ),
        (
            "mureo-logly-bridge",
            "logly_ads_context",
            "plugin:mureo-logly-bridge:logly_ads_context",
        ),
        ("acme-ads", "acme_ads", "plugin:acme-ads:acme_ads"),
    ],
)
def test_plugin_platform_key_carries_distribution_and_provider(
    distribution: str, provider: str, expected: str
) -> None:
    assert plugin_platform_key(distribution, provider) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("distribution", "expected"),
    [
        ("mureo-logly-bridge", "plugin:mureo-logly-bridge"),
        ("acme-ads", "plugin:acme-ads"),
        ("unknown", "plugin:unknown"),
    ],
)
def test_omitting_the_provider_yields_the_legacy_short_form(
    distribution: str, expected: str
) -> None:
    """A caller that cannot name the provider says so rather than inventing one."""
    assert plugin_platform_key(distribution) == expected


@pytest.mark.unit
def test_key_shape_cannot_depend_on_how_many_platforms_a_distribution_ships() -> None:
    """#537's central constraint, pinned so it cannot be reintroduced.

    Making the format count-dependent — short key while a distribution
    ships one platform, long key once it ships two — would silently change
    the first platform's key the day a second is added, breaking joins for
    data already written under it. The builder therefore takes the two
    names and NOTHING else: no registry, no count, no installed-set
    parameter it could consult.
    """
    parameters = list(inspect.signature(plugin_platform_key).parameters)
    assert parameters == ["distribution", "provider"], (
        "plugin_platform_key must not gain a parameter that could carry "
        "how many platforms a distribution ships (#537)"
    )

    # Same distribution, same builder call — the shape does not move when a
    # sibling provider appears.
    solo = plugin_platform_key("solo-dist", "solo_ads")
    first_of_many = plugin_platform_key("multi-dist", "aaa_ads")
    plugin_platform_key("multi-dist", "bbb_ads")
    assert solo == "plugin:solo-dist:solo_ads"
    assert first_of_many == "plugin:multi-dist:aaa_ads"
    assert plugin_platform_key("multi-dist", "aaa_ads") == first_of_many


@pytest.mark.unit
def test_plugin_platform_key_is_idempotent() -> None:
    """An already-canonical key passed back in is not double-prefixed."""
    once = plugin_platform_key("acme-ads", "acme_ads")
    assert plugin_platform_key(once) == once
    # A long-form key keeps its own provider rather than taking the argument.
    assert plugin_platform_key(once, "other_ads") == once

    short = plugin_platform_key("acme-ads")
    assert plugin_platform_key(short) == short
    # A short-form key plus a provider is completed, not double-prefixed.
    assert plugin_platform_key(short, "acme_ads") == once


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("plugin:mureo-lineyahoo-bridge:yahoo_ads", True),
        # The #481 short form stays valid on read.
        ("plugin:mureo-logly-bridge", True),
        ("plugin:acme-ads", True),
        ("google_ads", False),
        ("meta_ads", False),
        ("tiktok_ads", False),
        ("acme_ads_platform", False),
        ("", False),
        # A bare prefix carries no distribution — not a usable plugin key.
        ("plugin:", False),
        # Claims the per-provider form but names no provider.
        ("plugin:acme-ads:", False),
        ("plugin::acme_ads", False),
    ],
)
def test_is_plugin_platform_key(key: str, expected: bool) -> None:
    assert is_plugin_platform_key(key) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (
            "plugin:mureo-lineyahoo-bridge:yahoo_ads",
            ("mureo-lineyahoo-bridge", "yahoo_ads"),
        ),
        # Legacy short form — a distribution, and no provider.
        ("plugin:mureo-logly-bridge", ("mureo-logly-bridge", "")),
        # Not plugin keys at all.
        ("google_ads", ("", "")),
        ("plugin:", ("", "")),
        ("plugin:acme-ads:", ("", "")),
        ("", ("", "")),
    ],
)
def test_plugin_platform_parts(key: str, expected: tuple[str, str]) -> None:
    assert plugin_platform_parts(key) == expected
    assert plugin_distribution(key) == expected[0]
    assert plugin_provider(key) == expected[1]


@pytest.mark.unit
def test_a_colon_bearing_provider_round_trips_instead_of_truncating() -> None:
    """Why ``:`` is safe — and it is NOT "neither half can contain one".

    A pip distribution name cannot contain ``:`` (PEP 503 / PEP 508 allow
    only ASCII letters, digits, ``-``, ``_`` and ``.``) and mureo always
    takes that half from the installing metadata, so the first segment
    cannot forge a separator. An **entry-point name**, though, may contain
    one: ``importlib.metadata`` splits each ``entry_points.txt`` line on
    the first ``=`` only, so ``weird:name = mod:attr`` yields
    ``ep.name == "weird:name"``. mureo is safe on that path because it
    never keys the provider half on a raw ``ep.name`` — and because the
    split is on the FIRST separator, which makes a colon-bearing provider
    round-trip verbatim rather than be truncated or steal the
    distribution's segment.
    """
    assert plugin_platform_parts("plugin:a:b:c") == ("a", "b:c")
    assert plugin_platform_key("a", "b:c") == "plugin:a:b:c"
    # The distribution half is unaffected by anything the provider carries.
    assert plugin_distribution("plugin:a:b:c") == "a"
    assert plugin_platform_key_matches("plugin:a:b:c", "a", "b:c")
    assert not plugin_platform_key_matches("plugin:a:b:c", "a:b", "c")


@pytest.mark.unit
def test_round_trip_key_to_parts() -> None:
    for dist, provider in (
        ("mureo-lineyahoo-bridge", "yahoo_ads"),
        ("acme-ads", "acme_ads"),
        ("a", "b"),
    ):
        key = plugin_platform_key(dist, provider)
        assert plugin_platform_parts(key) == (dist, provider)


@pytest.mark.unit
def test_round_trip_legacy_key_to_distribution() -> None:
    for dist in ("mureo-logly-bridge", "acme-ads", "a"):
        assert plugin_distribution(plugin_platform_key(dist)) == dist


# ---------------------------------------------------------------------------
# The join (#537) — what keeps already-written state working
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_canonical_key_matches_only_its_own_platform() -> None:
    key = "plugin:mureo-lineyahoo-bridge:yahoo_ads"
    assert plugin_platform_key_matches(key, "mureo-lineyahoo-bridge", "yahoo_ads")
    assert not plugin_platform_key_matches(key, "mureo-lineyahoo-bridge", "line_ads")
    assert not plugin_platform_key_matches(
        key, "mureo-lineyahoo-bridge", "yahoo_ads_display"
    )
    assert not plugin_platform_key_matches(key, "mureo-logly-bridge", "yahoo_ads")


@pytest.mark.unit
def test_legacy_key_still_joins_for_a_single_provider_distribution() -> None:
    """The #481 key and the #537 key denote the same platform here.

    A distribution that provides exactly one platform has exactly one
    candidate, so anything joining on the old key keeps joining — which is
    what makes existing state correct with no rewrite.
    """
    assert plugin_platform_key_matches(
        "plugin:mureo-logly-bridge", "mureo-logly-bridge", "logly_ads_context"
    )
    assert not plugin_platform_key_matches(
        "plugin:mureo-logly-bridge", "mureo-smartnews-bridge", "smartnews_ads"
    )


@pytest.mark.unit
def test_legacy_key_matches_every_provider_of_its_distribution() -> None:
    """It names a distribution, not a platform — so it is genuinely ambiguous.

    The permissiveness is deliberate and is why a caller that finds more
    than one candidate must refuse rather than pick one: this function
    cannot see the candidate set, so it cannot break the tie.
    """
    legacy = "plugin:mureo-lineyahoo-bridge"
    matched = [
        provider
        for provider in ("line_ads", "yahoo_ads", "yahoo_ads_display")
        if plugin_platform_key_matches(legacy, "mureo-lineyahoo-bridge", provider)
    ]
    assert matched == ["line_ads", "yahoo_ads", "yahoo_ads_display"]


@pytest.mark.unit
@pytest.mark.parametrize("key", ["google_ads", "plugin:", "plugin:acme-ads:", ""])
def test_non_plugin_keys_never_match(key: str) -> None:
    assert not plugin_platform_key_matches(key, "acme-ads", "acme_ads")
