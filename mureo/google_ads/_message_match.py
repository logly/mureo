"""Landing-page screenshot capture via Playwright.

``LPScreenshotter`` renders a landing page to a PNG so the agent can compare
ad copy against what the page actually shows. Every navigation, including
redirect hops, is re-checked against the canonical SSRF guard.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from mureo.core.url_guard import UnsafeUrlError, validate_public_url

_SCREENSHOT_TIMEOUT_MS = 30_000
_VIEWPORT_WIDTH = 1280
_VIEWPORT_HEIGHT = 800


class _NavigationRequest(Protocol):
    """Structural view of the Playwright ``Request`` fields the guard reads."""

    @property
    def url(self) -> str: ...

    def is_navigation_request(self) -> bool: ...


class _NavigationRoute(Protocol):
    """Structural view of the Playwright ``Route`` API the guard drives."""

    @property
    def request(self) -> _NavigationRequest: ...

    async def abort(self) -> None: ...

    async def continue_(self) -> None: ...


class LPScreenshotter:
    """Capture LP screenshots using Playwright."""

    @staticmethod
    async def _guard_navigation(
        route: _NavigationRoute, blocked: dict[str, str]
    ) -> None:
        """Re-validate a navigation request against the canonical SSRF guard.

        ``page.goto`` auto-follows HTTP redirects, so a public URL could bounce
        the browser to an internal host (e.g. ``http://169.254.169.254/`` for
        cloud IAM credentials). This handler runs on every request; for
        top-level/frame navigations — including each redirect hop — it re-checks
        the target with :func:`validate_public_url` and aborts the request if it
        resolves to an internal address, recording the blocked URL in
        ``blocked``. Sub-resource requests are passed through unchanged.
        """
        request = route.request
        if not request.is_navigation_request():
            await route.continue_()
            return
        try:
            # The canonical guard does a blocking DNS lookup; keep it off the
            # event loop the browser is driven from.
            await asyncio.to_thread(validate_public_url, request.url)
        except UnsafeUrlError:
            blocked["url"] = request.url
            await route.abort()
            return
        await route.continue_()

    async def capture(self, url: str) -> bytes:
        """Return PNG binary screenshot of the URL.

        Raises:
            RuntimeError: If screenshot capture fails, or a redirect targets an
                internal host (SSRF protection).
        """
        from mureo.analysis.lp_analyzer import LPAnalyzer

        # SSRF protection: validate the initial URL up front. Redirect hops are
        # re-validated by the route guard below, because ``page.goto``
        # auto-follows redirects and would otherwise navigate to an internal
        # host before we could re-check it.
        LPAnalyzer._validate_url(url)

        try:
            from playwright.async_api import Error as PlaywrightError
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not available. Run: pip install playwright && playwright install"
            ) from exc

        blocked: dict[str, str] = {}

        async def _route_handler(route: _NavigationRoute) -> None:
            await self._guard_navigation(route, blocked)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT},
                )
                await page.route("**/*", _route_handler)
                try:
                    await page.goto(
                        url, timeout=_SCREENSHOT_TIMEOUT_MS, wait_until="networkidle"
                    )
                except PlaywrightError as exc:
                    if blocked:
                        raise RuntimeError(
                            "Refusing to navigate to internal redirect target: "
                            f"{blocked['url']}"
                        ) from exc
                    raise
                screenshot = await page.screenshot(full_page=False, type="png")
                return screenshot  # type: ignore[no-any-return, unused-ignore]
            finally:
                await browser.close()
