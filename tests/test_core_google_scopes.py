"""Unit tests for ``mureo.core.google_scopes``.

The consent screen lets the user untick any requested scope. The Google Ads
scope is the one the stored token exists for, so its absence fails the
setup; Search Console and GA4 read access are optional and only logged.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from mureo.core.google_scopes import (
    ANALYTICS_READONLY_SCOPE,
    GOOGLE_ADS_SCOPE,
    GOOGLE_SCOPES,
    SEARCH_CONSOLE_SCOPE,
    check_granted_scopes,
    granted_scopes,
)

pytestmark = pytest.mark.unit

_LOGGER = "mureo.core.google_scopes"


def test_requests_ads_search_console_and_analytics() -> None:
    assert GOOGLE_SCOPES == (
        GOOGLE_ADS_SCOPE,
        SEARCH_CONSOLE_SCOPE,
        ANALYTICS_READONLY_SCOPE,
    )


class TestGrantedScopes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                [GOOGLE_ADS_SCOPE, ANALYTICS_READONLY_SCOPE],
                (GOOGLE_ADS_SCOPE, ANALYTICS_READONLY_SCOPE),
            ),
            (
                f"{GOOGLE_ADS_SCOPE} {SEARCH_CONSOLE_SCOPE}",
                (GOOGLE_ADS_SCOPE, SEARCH_CONSOLE_SCOPE),
            ),
            (None, ()),
            ((GOOGLE_ADS_SCOPE, 7, None), (GOOGLE_ADS_SCOPE,)),
            ({"not": "a list"}, ()),
        ],
    )
    def test_reads_the_reported_set(
        self, raw: object, expected: tuple[str, ...]
    ) -> None:
        assert granted_scopes(SimpleNamespace(granted_scopes=raw)) == expected

    def test_an_absent_attribute_reads_as_nothing(self) -> None:
        assert granted_scopes(SimpleNamespace()) == ()


class TestCheckGrantedScopes:
    def test_an_unreported_set_passes_silently(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            check_granted_scopes(())

        assert caplog.records == []

    def test_a_grant_without_google_ads_fails(self) -> None:
        with pytest.raises(RuntimeError, match="Google Ads scope"):
            check_granted_scopes((SEARCH_CONSOLE_SCOPE, ANALYTICS_READONLY_SCOPE))

    def test_a_grant_without_analytics_only_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            check_granted_scopes((GOOGLE_ADS_SCOPE, SEARCH_CONSOLE_SCOPE))

        assert [r.getMessage() for r in caplog.records] == [
            f"Google did not grant: {ANALYTICS_READONLY_SCOPE}"
        ]

    def test_a_full_grant_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            check_granted_scopes(GOOGLE_SCOPES)

        assert caplog.records == []
