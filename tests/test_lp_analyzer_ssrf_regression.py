"""Regression tests for the LP analyzer SSRF hardening.

Covers two fixes:

* M5 — ``LPAnalyzer._validate_url`` now delegates to the canonical
  ``mureo.core.url_guard`` guard, so multicast / unspecified addresses (which
  the previous in-module reimplementation let through) are rejected, for both
  literal IPs and DNS names that resolve to them.
* M6 — ``LPAnalyzer._fetch_html`` reads the response body as a stream and stops
  at ``_MAX_BODY_BYTES`` instead of materialising the whole body via
  ``response.content``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest

from mureo.analysis.lp_analyzer import _MAX_BODY_BYTES, LPAnalyzer

if TYPE_CHECKING:
    from collections.abc import Callable

# Captured before any test patches ``httpx.AsyncClient`` so the injecting
# factory can build a real client without recursing into the patch.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


# ---------------------------------------------------------------------------
# M5: multicast / unspecified addresses are now rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateUrlMulticastRegression:
    @pytest.mark.parametrize(
        "url",
        [
            "http://224.0.0.1/",  # IPv4 multicast (was missed before)
            "http://[ff02::1]/",  # IPv6 multicast (was missed before)
            "http://[::]/",  # IPv6 unspecified (was missed before)
        ],
    )
    def test_literal_multicast_or_unspecified_is_rejected(self, url: str) -> None:
        with pytest.raises(ValueError, match="(?i)internal network"):
            LPAnalyzer._validate_url(url)

    def test_hostname_resolving_to_multicast_is_rejected(self) -> None:
        # A public-looking hostname that resolves to a multicast address must be
        # rejected. DNS resolution happens inside the canonical guard.
        with (
            patch(
                "mureo.core.url_guard.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("224.0.0.1", 0))],
            ),
            pytest.raises(ValueError, match="(?i)internal network"),
        ):
            LPAnalyzer._validate_url("https://multicast.example.com/")


# ---------------------------------------------------------------------------
# M6: streaming body-size cap
# ---------------------------------------------------------------------------


class _CountingAsyncStream(httpx.AsyncByteStream):
    """Async byte stream that records how many chunks were actually pulled."""

    def __init__(self, chunk: bytes, count: int) -> None:
        self._chunk = chunk
        self._count = count
        self.emitted = 0

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        for _ in range(self._count):
            self.emitted += 1
            yield self._chunk

    async def aclose(self) -> None:
        return None


def _client_factory(transport: httpx.MockTransport) -> Callable[..., httpx.AsyncClient]:
    """Build a patched ``AsyncClient`` that injects ``transport``."""

    def _factory(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return _REAL_ASYNC_CLIENT(transport=transport, **kwargs)  # type: ignore[arg-type]

    return _factory


@pytest.mark.unit
class TestFetchHtmlBodyCap:
    @pytest.mark.asyncio
    async def test_oversized_body_is_truncated_and_stream_stops_early(self) -> None:
        # 100 chunks * 10_000 bytes = 1MB total, well over the 500KB cap.
        stream = _CountingAsyncStream(b"a" * 10_000, 100)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                stream=stream,
            )

        transport = httpx.MockTransport(handler)
        analyzer = LPAnalyzer()

        with patch(
            "mureo.analysis.lp_analyzer.httpx.AsyncClient",
            side_effect=_client_factory(transport),
        ):
            # Literal public IP avoids a real DNS lookup in _validate_url.
            html = await analyzer._fetch_html("https://93.184.216.34/")

        assert len(html) == _MAX_BODY_BYTES
        # We must have stopped reading once the cap was reached, not drained the
        # whole 1MB stream.
        assert stream.emitted == _MAX_BODY_BYTES // 10_000
        assert stream.emitted < 100

    @pytest.mark.asyncio
    async def test_small_body_is_returned_in_full(self) -> None:
        stream = _CountingAsyncStream(b"<html>ok</html>", 1)

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                stream=stream,
            )

        transport = httpx.MockTransport(handler)
        analyzer = LPAnalyzer()

        with patch(
            "mureo.analysis.lp_analyzer.httpx.AsyncClient",
            side_effect=_client_factory(transport),
        ):
            html = await analyzer._fetch_html("https://93.184.216.34/")

        assert html == "<html>ok</html>"
        assert stream.emitted == 1

    @pytest.mark.asyncio
    async def test_redirect_to_internal_host_is_rejected(self) -> None:
        # Confirms manual redirect validation still holds after the streaming
        # rewrite: a public URL that 302s to the cloud metadata IP is refused.
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

        transport = httpx.MockTransport(handler)
        analyzer = LPAnalyzer()

        with (
            patch(
                "mureo.analysis.lp_analyzer.httpx.AsyncClient",
                side_effect=_client_factory(transport),
            ),
            pytest.raises(ValueError, match="(?i)internal network"),
        ):
            await analyzer._fetch_html("https://93.184.216.34/")
