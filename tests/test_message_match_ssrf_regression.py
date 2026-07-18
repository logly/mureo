"""Regression tests for the LP screenshotter SSRF hardening (C3).

``LPScreenshotter.capture`` drives Playwright, whose ``page.goto`` auto-follows
HTTP redirects. Previously only the *initial* URL was validated, so a public URL
that redirected to an internal host (e.g. the cloud metadata endpoint) would be
navigated to anyway. ``capture`` now installs a ``page.route`` guard that
re-validates every navigation request — including each redirect hop — with the
canonical guard and aborts internal ones.

Playwright is not installed in CI, and launching a real headless browser here is
impractical, so these tests exercise the guard decision logic directly with fake
``Route``/``Request`` objects and confirm the initial-URL guard rejects internal
targets before any browser is launched. The behaviour of ``page.route`` invoking
the handler for redirect hops is a Playwright API contract not re-verified here.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mureo.google_ads._message_match import LPScreenshotter


class _FakeRequest:
    def __init__(self, url: str, navigation: bool = True) -> None:
        self.url = url
        self._navigation = navigation

    def is_navigation_request(self) -> bool:
        return self._navigation


class _FakeRoute:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


@pytest.mark.unit
class TestGuardNavigation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1/",
            "http://10.0.0.5/internal",
        ],
    )
    async def test_internal_navigation_is_aborted(self, url: str) -> None:
        route = _FakeRoute(_FakeRequest(url, navigation=True))
        blocked: dict[str, str] = {}

        await LPScreenshotter._guard_navigation(route, blocked)

        assert route.aborted is True
        assert route.continued is False
        assert blocked["url"] == url

    @pytest.mark.asyncio
    async def test_public_navigation_is_allowed(self) -> None:
        # Literal public IP avoids a real DNS lookup.
        route = _FakeRoute(_FakeRequest("http://93.184.216.34/", navigation=True))
        blocked: dict[str, str] = {}

        await LPScreenshotter._guard_navigation(route, blocked)

        assert route.continued is True
        assert route.aborted is False
        assert blocked == {}

    @pytest.mark.asyncio
    async def test_hostname_redirecting_to_internal_is_aborted(self) -> None:
        # A navigation to a public-looking host that resolves to a private IP —
        # the redirect-target case C3 is about — must be aborted.
        route = _FakeRoute(_FakeRequest("http://sneaky.example.com/", navigation=True))
        blocked: dict[str, str] = {}

        with patch(
            "mureo.core.url_guard.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("10.1.2.3", 0))],
        ):
            await LPScreenshotter._guard_navigation(route, blocked)

        assert route.aborted is True
        assert blocked["url"] == "http://sneaky.example.com/"

    @pytest.mark.asyncio
    async def test_non_navigation_request_is_passed_through(self) -> None:
        # Sub-resource (non-navigation) requests are not guarded, even internal
        # ones — the guard only governs top-level/frame navigation.
        route = _FakeRoute(_FakeRequest("http://127.0.0.1/asset.png", navigation=False))
        blocked: dict[str, str] = {}

        await LPScreenshotter._guard_navigation(route, blocked)

        assert route.continued is True
        assert route.aborted is False
        assert blocked == {}


@pytest.mark.unit
class TestCaptureInitialUrlGuard:
    @pytest.mark.asyncio
    async def test_internal_initial_url_rejected_before_browser_launch(self) -> None:
        # An internal initial URL must be refused by _validate_url before any
        # attempt to import/launch Playwright, so this raises even though
        # Playwright is not installed.
        screenshotter = LPScreenshotter()
        with pytest.raises(ValueError, match="(?i)internal network"):
            await screenshotter.capture("http://169.254.169.254/latest/meta-data/")
